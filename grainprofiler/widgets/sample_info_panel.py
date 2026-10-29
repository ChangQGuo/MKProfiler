"""Right-side panel: sample metadata + sortable kernel measurements table + calibration."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QTableView,
    QVBoxLayout, QWidget,
)

from grainprofiler.app.data_loader import DataLoader
from grainprofiler.app.metadata_edit import save_metadata_edit
from grainprofiler.models.pandas_model import PandasModel
from grainprofiler.models.sort_filter_proxy import SortFilterProxy

_STYLE_DARK = """
    QWidget { background-color:#111; }
    QGroupBox { font-weight:bold; font-size:16px; color:#FFF; background-color:#111; border:1px solid #333; border-radius:0px; margin-top:0px; padding-top:16px; }
    QGroupBox::title { color:#FFF; font-size:16px; subcontrol-origin:margin; left:8px; padding:0 2px; }
    QLabel { color:#FFF; font-size:15px; background:transparent; }
    QTableView { font-size:14px; color:#FFF; background-color:#0D0D0D; gridline-color:#222; alternate-background-color:#151515; selection-background-color:#2C6FAC; }
    QHeaderView::section { background-color:#1A1A1A; color:#EEE; font-size:14px; padding:5px; border:1px solid #222; }
    QLineEdit { background-color:#1A1A1A; color:#FFF; font-size:14px; border:1px solid #333; padding:5px; }
    QPushButton { background-color:#222; color:#FFF; font-size:14px; border:1px solid #444; border-radius:3px; padding:7px; margin:4px; }
    QPushButton:hover { background-color:#333; }
"""

_STYLE_LIGHT = """
    QWidget { background-color:#FAFAFA; }
    QGroupBox { font-weight:bold; font-size:16px; color:#000; background-color:#FAFAFA; border:1px solid #DDD; border-radius:0px; margin-top:0px; padding-top:16px; }
    QGroupBox::title { color:#000; font-size:16px; subcontrol-origin:margin; left:8px; padding:0 2px; }
    QLabel { color:#000; font-size:15px; background:transparent; }
    QTableView { font-size:14px; color:#000; background-color:#FFF; gridline-color:#DDD; alternate-background-color:#F5F5F5; selection-background-color:#2C6FAC; }
    QHeaderView::section { background-color:#E8E8E8; color:#000; font-size:14px; padding:5px; border:1px solid #CCC; }
    QLineEdit { background-color:#FFF; color:#000; font-size:14px; border:1px solid #CCC; padding:5px; }
    QPushButton { background-color:#E0E0E0; color:#000; font-size:14px; border:1px solid #BBB; border-radius:3px; padding:7px; margin:4px; }
    QPushButton:hover { background-color:#D0D0D0; }
"""

_COLS_DISPLAY = [
    "kernel_name", "length_px", "max_width_px",
    "area_px2", "perimeter_px", "circularity", "length_width_ratio", "eccentricity",
]
_CAL_COL = "cal_px"


class CalPandasModel(PandasModel):
    """PandasModel that shows the calibration column in red."""

    def data(self, index, role=Qt.DisplayRole):
        col = self._df.columns[index.column()]
        if col == _CAL_COL and role == Qt.ForegroundRole:
            return QColor(255, 60, 60)
        if col == _CAL_COL and role == Qt.DisplayRole:
            val = self._df.iat[index.row(), index.column()]
            if pd.isna(val) or val == 0:
                return ""
            return f"{float(val):.1f}"
        return super().data(index, role)


class SampleInfoPanel(QScrollArea):
    kernel_row_selected = Signal(str)
    kernel_row_double_clicked = Signal(str)
    metadata_saved = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(500)
        self.setWidgetResizable(True)
        self.set_dark_theme(True)  # default dark
        self._data_loader: DataLoader | None = None
        self._current_image: str = ""
        self._kernel_names: list[str] = []
        self._table_columns_sized: bool = False
        self._saved_meta_values: dict[str, str] = {}
        self._pending_meta: dict[str, dict[str, str]] = {}
        self._pending_meta_baselines: dict[str, dict[str, str]] = {}
        self._loading_metadata = False

        container = QWidget()
        self.setWidget(container)
        layout = QVBoxLayout(container)

        # --- Metadata ---
        mg = QGroupBox("Sample Info")
        mg_layout = QVBoxLayout()
        mg_header = QHBoxLayout()

        # Lock toggle
        self._lock_btn = QPushButton()
        self._lock_btn.setCheckable(True)
        self._lock_btn.setChecked(True)
        self._lock_btn.setFixedSize(36, 36)
        self._lock_btn.setIconSize(QSize(24, 24))
        self._lock_btn.setStyleSheet("padding: 0; margin: 0;")
        self._lock_btn.toggled.connect(self._on_lock_toggled)
        self._update_lock_icon(True)
        mg_header.addWidget(QLabel(""))
        mg_header.addStretch()
        mg_header.addWidget(self._lock_btn)
        mg_layout.addLayout(mg_header)

        self._meta_form = QFormLayout()
        self._meta_edits: dict[str, QLineEdit | QLabel] = {}
        self._save_btns: dict[str, QPushButton] = {}
        self._meta_readonly_vals: dict[str, str] = {}

        for key in ["plant_name", "weight_g"]:
            edit = QLineEdit("—")
            edit.setReadOnly(True)
            edit.setFont(QFont("Times New Roman", 14))
            if key == "weight_g":
                edit.setToolTip("Enter a non-negative weight or '-' when no reliable value is available.")
            edit.textChanged.connect(lambda text, k=key: self._on_meta_changed(k, text))
            self._meta_edits[key] = edit
            save = QPushButton("✓")
            save.setFixedSize(34, 34)
            save.setStyleSheet("padding: 0; margin: 0; color: #31a354; font-weight: bold;")
            save.setToolTip(f"Save {key.replace('_', ' ')}")
            save.setAccessibleName(f"Save {key.replace('_', ' ')}")
            save.clicked.connect(lambda _checked=False, k=key: self._on_meta_edited(k))
            save.hide()
            self._save_btns[key] = save
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(edit, 1)
            row.addWidget(save)
            self._meta_form.addRow(key.replace("_", " ").title() + ":", row)

        for key in ["mm_per_px", "kernel_count"]:
            lbl = QLabel("—")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._meta_edits[key] = lbl
            self._meta_form.addRow(key.replace("_", " ").title() + ":", lbl)

        mg_layout.addLayout(self._meta_form)
        self._meta_notice = QLabel("")
        self._meta_notice.setWordWrap(True)
        self._meta_notice.hide()
        mg_layout.addWidget(self._meta_notice)
        mg.setLayout(mg_layout)
        layout.addWidget(mg)

        # --- Plant Summary ---
        pg = QGroupBox("Plant Summary")
        self._plant_form = QFormLayout(pg)
        self._plant_lbls: dict[str, QLabel] = {}
        _plant_keys = [
            "n_kernels", "median_length_mm", "median_max_width_mm",
            "median_area_mm2", "median_circularity",
        ]
        for key in _plant_keys:
            lbl = QLabel("—")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._plant_lbls[key] = lbl
            self._plant_form.addRow(key.replace("_", " ").title() + ":", lbl)
        layout.addWidget(pg)

        # --- Kernel table (fills remaining space) ---
        tg = QGroupBox("Kernel Measurements")
        tvl = QVBoxLayout(tg)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by kernel ID...")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._on_filter)
        tvl.addWidget(self._filter_edit)

        self._table = QTableView()
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableView.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._table.clicked.connect(self._on_row_clicked)
        self._table.doubleClicked.connect(self._on_row_double_clicked)

        self._proxy = SortFilterProxy()
        self._pandas_model: CalPandasModel | None = None
        tvl.addWidget(self._table, stretch=1)
        layout.addWidget(tg, stretch=1)

        # --- Export ---
        eb = QPushButton("Export CSV")
        eb.clicked.connect(self.export_csv)
        layout.addWidget(eb)

    # ------------------------------------------------------------------
    def load_sample(self, image_name: str, data_loader: DataLoader) -> None:
        if self._data_loader is not None and self._data_loader is not data_loader:
            self._pending_meta.clear()
            self._pending_meta_baselines.clear()
        self._data_loader = data_loader
        self._current_image = image_name
        meta = data_loader.get_image_metadata(image_name)
        self._loading_metadata = True
        try:
            for key, widget in self._meta_edits.items():
                val = meta.get(key, "—") if meta is not None else "—"
                text = str(val) if not pd.isna(val) else "—"
                if isinstance(widget, QLineEdit):
                    self._saved_meta_values[key] = self._pending_meta_baselines.get(image_name, {}).get(key, text)
                    widget.setText(self._pending_meta.get(image_name, {}).get(key, text))
                else:
                    widget.setText(text)
        finally:
            self._loading_metadata = False
        for key, button in self._save_btns.items():
            button.setVisible(key in self._pending_meta.get(image_name, {}))
        self._meta_notice.hide()
        self._kernel_names = data_loader.get_kernels_for_sample(image_name)
        self._meta_edits["kernel_count"].setText(str(len(self._kernel_names)))
        self._build_table(data_loader)
        self._load_plant_summary(data_loader, image_name)

    def _load_plant_summary(self, dl: DataLoader, image_name: str) -> None:
        """Populate plant-level median stats for the current image's plant."""
        plant = dl.image_to_plant.get(image_name, "")
        row = dl.get_plant_median(plant) if plant else None
        if row is None:
            for lbl in self._plant_lbls.values():
                lbl.setText("—")
            return
        for key, lbl in self._plant_lbls.items():
            val = row.get(key)
            if val is None or (not isinstance(val, str) and pd.isna(val)):
                lbl.setText("—")
            elif key in ("median_length_mm", "median_max_width_mm", "median_area_mm2"):
                lbl.setText(f"{float(val):.2f}")
            elif key == "median_circularity":
                lbl.setText(f"{float(val):.4f}")
            else:
                lbl.setText(str(int(val)) if float(val) == int(float(val)) else f"{float(val):.1f}")

    def _build_table(self, dl: DataLoader) -> None:
        # Sort kernels by numeric suffix
        def _sort_key(kn):
            m = re.search(r"kernel_(\d+)", kn)
            return int(m.group(1)) if m else 0
        sorted_kernels = sorted(self._kernel_names, key=_sort_key)

        rows = []
        for kn in sorted_kernels:
            meas = dl.get_kernel_measurement(kn)
            if meas is not None:
                rows.append(meas.to_dict())
        df = pd.DataFrame(rows)
        cols = [c for c in _COLS_DISPLAY if c in df.columns]
        if not cols:
            cols = list(df.columns)
        df = df[cols].copy()

        # Insert calibration column right after length_px
        if "length_px" in df.columns:
            loc = df.columns.get_loc("length_px") + 1
            df.insert(loc, _CAL_COL, 0.0)
        else:
            df[_CAL_COL] = 0.0

        if "kernel_name" in df.columns:
            df["kernel_name"] = df["kernel_name"].apply(
                lambda x: x.split("_kernel_")[1].replace(".jpg", "")
                if "_kernel_" in str(x) else str(x)
            )

        # Save column widths before replacing model
        saved_widths = {}
        header = self._table.horizontalHeader()
        for c in range(header.count()):
            saved_widths[c] = header.sectionSize(c)

        self._pandas_model = CalPandasModel(df)
        self._proxy.setSourceModel(self._pandas_model)
        self._table.setModel(self._proxy)

        if not self._table_columns_sized:
            self._table.resizeColumnsToContents()
            self._table_columns_sized = True
        elif saved_widths:
            # Restore user-adjusted widths
            for c, w in saved_widths.items():
                if c < header.count():
                    header.resizeSection(c, w)

    def set_dark_theme(self, dark: bool) -> None:
        self._dark_mode = dark
        self.setStyleSheet(_STYLE_DARK if dark else _STYLE_LIGHT)
        if hasattr(self, "_lock_btn"):
            self._update_lock_icon(self._lock_btn.isChecked())

    # ------------------------------------------------------------------
    # Editable sample info
    # ------------------------------------------------------------------

    def _on_lock_toggled(self, checked: bool) -> None:
        self._update_lock_icon(checked)
        for key in ("plant_name", "weight_g"):
            w = self._meta_edits.get(key)
            if isinstance(w, QLineEdit):
                w.setReadOnly(checked)

    def _update_lock_icon(self, locked: bool) -> None:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#eeeeee" if self._dark_mode else "#222222"), 2))
        painter.drawRoundedRect(QRectF(5, 10, 14, 11), 2, 2)
        shackle = QPainterPath()
        if locked:
            shackle.moveTo(8, 10)
            shackle.lineTo(8, 7)
            shackle.cubicTo(8, 1, 16, 1, 16, 7)
            shackle.lineTo(16, 10)
        else:
            shackle.moveTo(8, 10)
            shackle.lineTo(8, 7)
            shackle.cubicTo(8, 1, 16, 1, 17, 5)
        painter.drawPath(shackle)
        painter.drawLine(12, 14, 12, 18)
        painter.end()
        self._lock_btn.setIcon(QIcon(pixmap))
        self._lock_btn.setToolTip("Unlock sample metadata" if locked else "Lock sample metadata")
        self._lock_btn.setAccessibleName("Locked" if locked else "Unlocked")

    def _on_meta_changed(self, key: str, text: str) -> None:
        if self._loading_metadata or not self._current_image:
            return
        if text == self._saved_meta_values.get(key):
            pending = self._pending_meta.get(self._current_image, {})
            pending.pop(key, None)
            baseline = self._pending_meta_baselines.get(self._current_image, {})
            baseline.pop(key, None)
            if not baseline:
                self._pending_meta_baselines.pop(self._current_image, None)
            if not pending:
                self._pending_meta.pop(self._current_image, None)
        else:
            if key not in self._pending_meta.get(self._current_image, {}):
                self._pending_meta_baselines.setdefault(self._current_image, {})[key] = self._saved_meta_values[key]
            self._pending_meta.setdefault(self._current_image, {})[key] = text
        self._save_btns[key].setVisible(key in self._pending_meta.get(self._current_image, {}))
        self._meta_notice.hide()

    def has_pending_metadata_edits(self) -> bool:
        return bool(self._pending_meta)

    def _on_meta_edited(self, key: str) -> None:
        """Save only the field confirmed by its checkmark."""
        if self._data_loader is None or not self._current_image:
            return
        w = self._meta_edits.get(key)
        if not isinstance(w, QLineEdit):
            return
        if key not in self._pending_meta.get(self._current_image, {}):
            return
        dl = self._data_loader
        image = self._current_image
        try:
            warning = save_metadata_edit(dl.result_dir, image, key, w.text(), self._saved_meta_values[key])
        except (OSError, UnicodeError, ValueError, csv.Error) as error:
            QMessageBox.warning(self, "Unable to save", str(error))
            return

        metadata = dl._read_csv(
            Path(dl.result_dir) / "metadata.csv",
            dtype={"image_name": "string", "plant_name": "string", "weight_g": "string"},
            keep_default_na=False, na_values=[""],
        )
        if metadata is not None:
            dl.metadata = metadata
            dl._meta_index = metadata.drop_duplicates("image_name").set_index("image_name", drop=False)
            try:
                dl._build_image_to_plant_map()
            except ValueError as error:
                QMessageBox.warning(self, "Saved, but reload failed", str(error))
        else:
            QMessageBox.warning(self, "Saved, but reload failed", "Reopen the result folder to refresh the display.")
        self._saved_meta_values[key] = w.text().strip()
        self._loading_metadata = True
        w.setText(self._saved_meta_values[key])
        self._loading_metadata = False
        self._pending_meta[image].pop(key, None)
        if not self._pending_meta[image]:
            del self._pending_meta[image]
        self._pending_meta_baselines[image].pop(key, None)
        if not self._pending_meta_baselines[image]:
            del self._pending_meta_baselines[image]
        self._save_btns[key].hide()
        self._meta_notice.setText(warning or "Saved in metadata.csv. Existing derived tables are not regenerated.")
        self._meta_notice.show()
        self.metadata_saved.emit(image)

    def update_calibration(self, cal_data: dict[str, float]) -> None:
        if self._pandas_model is None:
            return
        df = self._pandas_model._df
        for r in range(len(df)):
            display = str(df.iat[r, 0])
            # Full kernel name
            stem = self._current_image.replace(".jpg", "")
            full = f"{stem}_kernel_{display}.jpg"
            if full in cal_data:
                df.iat[r, df.columns.get_loc(_CAL_COL)] = cal_data[full]
        self._pandas_model.dataChanged.emit(
            self._pandas_model.index(0, 0),
            self._pandas_model.index(self._pandas_model.rowCount() - 1,
                                     self._pandas_model.columnCount() - 1),
        )

    def select_kernel(self, kernel_name: str) -> None:
        if self._pandas_model is None:
            return
        suffix = kernel_name.split("_kernel_")[1].replace(".jpg", "") if "_kernel_" in kernel_name else kernel_name
        for r in range(self._pandas_model.rowCount()):
            idx = self._pandas_model.index(r, 0)
            val = str(self._pandas_model.data(idx, Qt.DisplayRole))
            if suffix in val:
                proxy_idx = self._proxy.mapFromSource(idx)
                self._table.selectRow(proxy_idx.row())
                self._table.scrollTo(proxy_idx)
                break

    def export_csv(self) -> None:
        if self._pandas_model is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", f"{self._current_image}_measurements.csv",
            "CSV Files (*.csv)"
        )
        if path:
            self._pandas_model._df.to_csv(path, index=False)

    def _on_filter(self, text: str) -> None:
        self._proxy.set_filter(text)

    def _on_row_clicked(self, index) -> None:
        if self._data_loader is None or self._pandas_model is None:
            return
        src = self._proxy.mapToSource(index)
        row_data = self._pandas_model.get_row_data(src.row())
        if row_data is not None:
            dn = str(row_data.get("kernel_name", ""))
            stem = self._current_image.replace(".jpg", "")
            full = f"{stem}_kernel_{dn}.jpg"
            self.kernel_row_selected.emit(full)

    def _on_row_double_clicked(self, index) -> None:
        if self._data_loader is None or self._pandas_model is None:
            return
        src = self._proxy.mapToSource(index)
        row_data = self._pandas_model.get_row_data(src.row())
        if row_data is not None:
            dn = str(row_data.get("kernel_name", ""))
            stem = self._current_image.replace(".jpg", "")
            full = f"{stem}_kernel_{dn}.jpg"
            self.kernel_row_double_clicked.emit(full)
