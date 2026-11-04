"""Left sidebar: Open button + searchable sample list + theme toggle."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
)


class SampleItemDelegate(QStyledItemDelegate):
    """Paint a lightweight menu indicator only for the hovered row."""

    def paint(self, painter, option, index):
        row = QStyleOptionViewItem(option)
        visible = option.rect.intersected(self.parent().viewport().rect())
        row.rect.setRight(max(row.rect.left(), visible.right() - 28))
        super().paint(painter, row, index)
        if option.state & QStyle.State_MouseOver:
            painter.save()
            role = QPalette.HighlightedText if option.state & QStyle.State_Selected else QPalette.Text
            painter.setPen(option.palette.color(role))
            marker = QRect(visible.right() - 27, visible.top(), 28, visible.height())
            painter.drawText(marker, Qt.AlignCenter, "...")
            painter.restore()


class NavPanel(QFrame):
    """Left navigation panel."""

    folder_opened = Signal(str)
    sample_selected = Signal(str)
    theme_toggled = Signal()

    def __init__(self, parent=None, settings: QSettings | None = None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._settings = settings if settings is not None else QSettings("grainprofiler", "grainprofiler")
        self._folder_key = ""
        self._sample_ids: list[str] = []
        self._ordered_ids: list[str] = []
        self._positions: dict[str, int] = {}
        self._items: dict[str, QListWidgetItem] = {}
        self._plant_names: dict[str, str] = {}
        self._pinned: set[str] = set()
        self._aliases: dict[str, str] = {}
        self._last_search = ""
        self._menu_pressed: str | None = None
        self._dark_mode = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # --- Open button ---
        self._open_btn = QPushButton("Open Result Folder")
        self._open_btn.clicked.connect(self._on_open_clicked)
        layout.addWidget(self._open_btn)

        # --- Path label ---
        self._path_label = QLabel("")
        self._path_label.setWordWrap(True)
        self._path_label.setObjectName("navPathLabel")
        layout.addWidget(self._path_label)

        # --- Theme toggle ---
        theme_row = QHBoxLayout()
        self._theme_btn = QPushButton("Light Theme")
        self._theme_btn.clicked.connect(self._on_theme_clicked)
        theme_row.addWidget(self._theme_btn)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        # --- Filter and jump search ---
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter samples...")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(lambda: self._rebuild_list(self._filter_edit.text()))
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._filter_edit)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search image or plant name...")
        self._search_edit.setClearButtonEnabled(True)
        self._search_action = self._search_edit.addAction(QIcon(), QLineEdit.LeadingPosition)
        self._search_action.setToolTip("Find next matching sample")
        self._search_action.triggered.connect(self._jump_to_search)
        self._search_edit.returnPressed.connect(self._jump_to_search)
        self._search_edit.textChanged.connect(lambda _text: self._search_message.hide())
        layout.addWidget(self._search_edit)
        self._search_message = QLabel("No matching sample")
        self._search_message.hide()
        layout.addWidget(self._search_message)

        # --- Sample list ---
        self._list = QListWidget()
        self._list.setItemDelegate(SampleItemDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.viewport().installEventFilter(self)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        # --- Count label ---
        self._count_label = QLabel("")
        self._count_label.setObjectName("navCountLabel")
        layout.addWidget(self._count_label)
        self._update_search_icon()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def populate(self, sample_ids: list[str], result_dir: str, plant_names: dict[str, str] | None = None) -> None:
        canonical = os.path.normcase(str(Path(result_dir).expanduser().resolve()))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self._folder_key = f"folders/{digest}"
        self._sample_ids = list(sample_ids)
        self._plant_names = plant_names or {}
        self._pinned = {sid for sid in self._load_json("pinned", []) if isinstance(sid, str)} & set(self._sample_ids)
        aliases = self._load_json("aliases", {})
        self._aliases = {str(k): str(v) for k, v in aliases.items() if k in self._sample_ids and v}
        self._filter_timer.stop()
        self._filter_edit.blockSignals(True)
        self._filter_edit.clear()
        self._filter_edit.blockSignals(False)
        self._search_edit.clear()
        self._last_search = ""
        self._path_label.setText(result_dir)
        remembered = str(self._settings.value(f"{self._folder_key}/last_sample", "") or "")
        self._rebuild_list(requested=remembered, force_emit=True)

    def clear_data(self) -> None:
        self._sample_ids = []
        self._ordered_ids = []
        self._items.clear()
        self._folder_key = ""
        self._path_label.setText("")
        self._filter_timer.stop()
        self._filter_edit.blockSignals(True)
        self._filter_edit.clear()
        self._filter_edit.blockSignals(False)
        self._search_edit.clear()
        self._list.blockSignals(True)
        self._list.clear()
        self._list.blockSignals(False)
        self._count_label.setText("")

    def set_theme_state(self, dark: bool) -> None:
        self._dark_mode = dark
        self._theme_btn.setText("Light Theme" if dark else "Dark Theme")
        self._update_search_icon()

    def current_sample(self) -> str:
        item = self._list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else ""

    def select_sample(self, image_name: str) -> bool:
        if image_name not in self._sample_ids:
            return False
        if image_name not in self._items:
            self._filter_timer.stop()
            self._filter_edit.blockSignals(True)
            self._filter_edit.clear()
            self._filter_edit.blockSignals(False)
            self._rebuild_list(requested=image_name)
        else:
            self._list.setCurrentItem(self._items[image_name])
            self._list.scrollToItem(self._items[image_name])
        return True

    def navigate(self, offset: int) -> None:
        target = self._list.currentRow() + offset
        if 0 <= target < self._list.count():
            self._list.setCurrentRow(target)
            self._list.scrollToItem(self._list.currentItem())

    def set_pinned(self, image_name: str, pinned: bool) -> None:
        if image_name not in self._sample_ids:
            return
        if pinned:
            self._pinned.add(image_name)
        else:
            self._pinned.discard(image_name)
        self._settings.setValue(f"{self._folder_key}/pinned", json.dumps(sorted(self._pinned), ensure_ascii=False))
        self._rebuild_list(self._filter_edit.text())

    def set_alias(self, image_name: str, alias: str) -> None:
        if image_name not in self._sample_ids:
            return
        alias = alias.strip()
        if alias:
            self._aliases[image_name] = alias
        else:
            self._aliases.pop(image_name, None)
        self._settings.setValue(f"{self._folder_key}/aliases", json.dumps(self._aliases, ensure_ascii=False))
        self._rebuild_list(self._filter_edit.text())

    def update_plant_name(self, image_name: str, plant_name: str) -> None:
        self._plant_names[image_name] = plant_name
        if self._filter_edit.text():
            self._filter_timer.stop()
            self._rebuild_list(self._filter_edit.text())
            return
        item = self._items.get(image_name)
        if item is not None:
            item.setToolTip(f"Image: {image_name}\nPlant: {plant_name}")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_open_clicked(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        dlg_dir = QFileDialog.getExistingDirectory(self, "Select Result Folder")
        if dlg_dir:
            self.folder_opened.emit(dlg_dir)

    def _on_theme_clicked(self) -> None:
        self.theme_toggled.emit()

    def _on_filter_changed(self, text: str) -> None:
        self._filter_timer.start()

    def _on_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            image_name = str(current.data(Qt.UserRole))
            self._count_label.setText(f"{self._positions[image_name]} / {len(self._sample_ids)} samples")
            if self._folder_key:
                self._settings.setValue(f"{self._folder_key}/last_sample", image_name)
            self.sample_selected.emit(image_name)

    def _jump_to_search(self) -> None:
        query = self._search_edit.text().strip().casefold()
        if not query:
            return
        def fields(image_name):
            return (
                image_name.casefold(), Path(image_name).stem.casefold(),
                self._plant_names.get(image_name, "").casefold(),
                self._aliases.get(image_name, "").casefold(),
            )
        exact = [sid for sid in self._ordered_ids if query in fields(sid)]
        exact_set = set(exact)
        matches = exact + [
            sid for sid in self._ordered_ids
            if sid not in exact_set and any(query in field for field in fields(sid))
        ]
        if not matches:
            self._search_message.show()
            self._last_search = ""
            return
        current = self.current_sample()
        index = (matches.index(current) + 1) % len(matches) if query == self._last_search and current in matches else 0
        self._last_search = query
        self._search_message.hide()
        if self._filter_edit.text():
            self._filter_timer.stop()
            self._filter_edit.blockSignals(True)
            self._filter_edit.clear()
            self._filter_edit.blockSignals(False)
            self._rebuild_list(requested=matches[index])
        else:
            self.select_sample(matches[index])
        self._list.setFocus(Qt.OtherFocusReason)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_json(self, name: str, default):
        raw = self._settings.value(f"{self._folder_key}/{name}", "")
        try:
            value = json.loads(str(raw)) if raw else default
            return value if isinstance(value, type(default)) else default
        except (TypeError, ValueError):
            return default

    def _update_search_icon(self) -> None:
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#eeeeee" if self._dark_mode else "#222222"), 2))
        painter.drawEllipse(QRectF(3, 3, 9, 9))
        painter.drawLine(11, 11, 17, 17)
        painter.end()
        self._search_action.setIcon(QIcon(pixmap))

    def _sample_menu(self, image_name: str) -> QMenu:
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        pin = menu.addAction("Pin sample")
        pin.setCheckable(True)
        pin.setChecked(image_name in self._pinned)
        pin.triggered.connect(lambda checked: self.set_pinned(image_name, checked))
        copy = menu.addAction("Copy image name")
        copy.triggered.connect(lambda: QApplication.clipboard().setText(image_name))
        alias = menu.addAction("Rename display label...")
        alias.triggered.connect(lambda: self._prompt_alias(image_name))
        return menu

    def _prompt_alias(self, image_name: str) -> None:
        alias, accepted = QInputDialog.getText(
            self, "Display label", "Label for this viewer (the image name does not change):",
            text=self._aliases.get(image_name, ""),
        )
        if accepted:
            self.set_alias(image_name, alias)

    def _show_context_menu(self, position) -> None:
        item = self._list.itemAt(position)
        if item is not None:
            self._sample_menu(str(item.data(Qt.UserRole))).exec(self._list.viewport().mapToGlobal(position))

    def eventFilter(self, watched, event):
        if watched is self._list.viewport() and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            if event.button() == Qt.LeftButton:
                position = event.position().toPoint()
                item = self._list.itemAt(position)
                if event.type() == QEvent.MouseButtonPress:
                    self._menu_pressed = None
                    visible_right = min(self._list.visualItemRect(item).right(), self._list.viewport().rect().right()) if item is not None else -1
                    if item is not None and position.x() >= visible_right - 28:
                        self._menu_pressed = str(item.data(Qt.UserRole))
                        return True
                elif event.type() == QEvent.MouseButtonRelease and self._menu_pressed is not None:
                    selected, self._menu_pressed = self._menu_pressed, None
                    if item is not None and str(item.data(Qt.UserRole)) == selected:
                        self._sample_menu(selected).exec(self._list.viewport().mapToGlobal(position))
                    return True
        return super().eventFilter(watched, event)

    def _rebuild_list(self, filter_text: str = "", requested: str = "", force_emit: bool = False) -> None:
        previous = self.current_sample()
        self._ordered_ids = [sid for sid in self._sample_ids if sid in self._pinned]
        self._ordered_ids.extend(sid for sid in self._sample_ids if sid not in self._pinned)
        self._positions = {sid: index + 1 for index, sid in enumerate(self._ordered_ids)}
        filt = filter_text.strip().casefold()
        visible = [
            sid for sid in self._ordered_ids
            if not filt or filt in sid.casefold() or filt in self._plant_names.get(sid, "").casefold()
            or filt in self._aliases.get(sid, "").casefold()
        ]
        target = requested if requested in visible else previous if previous in visible and not force_emit else visible[0] if visible else ""
        self._items = {}
        self._list.setUpdatesEnabled(False)
        self._list.blockSignals(True)
        self._list.clear()
        for sid in visible:
            label = self._aliases.get(sid, sid)
            if sid in self._aliases:
                label = f"{label}  ·  {sid}"
            if sid in self._pinned:
                label = f"★ {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, sid)
            item.setToolTip(f"Image: {sid}\nPlant: {self._plant_names.get(sid, '')}")
            self._list.addItem(item)
            self._items[sid] = item
        if target:
            self._list.setCurrentItem(self._items[target])
        self._list.blockSignals(False)
        self._list.setUpdatesEnabled(True)
        self._count_label.setText(f"{self._positions.get(target, 0)} / {len(self._sample_ids)} samples")
        if target:
            self._list.scrollToItem(self._items[target])
            if force_emit or target != previous:
                self._on_item_changed(self._items[target], None)
