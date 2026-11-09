"""Top-level main window orchestrating all panels."""

from __future__ import annotations

import csv
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from threading import Thread

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFontComboBox,
    QKeySequenceEdit,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from grainprofiler import __version__
from grainprofiler.app.appearance import THEMES, appearance_stylesheet
from grainprofiler.app.csv_io import csv_file_sha256, remove_csv_record
from grainprofiler.app.data_loader import DataLoader
from grainprofiler.app.settings import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from grainprofiler.app.updater import check_for_update, prepare_update, schedule_install
from grainprofiler.resources.action_icons import action_icon
from grainprofiler.widgets.nav_panel import NavPanel
from grainprofiler.widgets.welcome_widget import WelcomeWidget

_SETTINGS_NO_ERROR = QSettings.NoError

# ---------------------------------------------------------------------------
# Theme stylesheets
# ---------------------------------------------------------------------------

_DARK_THEME = """
    QMainWindow { background-color: #2B2B2B; color: #E0E0E0; }
    QLabel { color: #FFFFFF; }
    QLabel#welcomeTitle { font-size: 34px; font-weight: bold; color: #7BAFD4; }
    QLabel#welcomeSubtitle { font-size: 18px; }
    QLabel#welcomeHint { font-size: 15px; color: #AAA; }
    QLabel#navPathLabel { font-size: 13px; color: #999; }
    QLabel#navCountLabel { font-size: 13px; color: #999; }
    QGroupBox {
        font-weight: bold; font-size: 15px;
        border: 1px solid #444; border-radius: 4px;
        margin-top: 8px; padding-top: 16px; color: #FFF;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #FFF; }
    QTableView {
        font-size: 14px;
        gridline-color: #555; background-color: #1A1A1A;
        alternate-background-color: #222;
        selection-background-color: #2C6FAC; color: #FFF;
    }
    QHeaderView::section {
        font-size: 14px;
        background-color: #252525; color: #EEE;
        padding: 5px; border: 1px solid #333;
    }
    QListWidget { font-size: 14px; background-color: #1A1A1A; color: #EEE; border: 1px solid #444; }
    QListWidget::item:selected { background-color: #2C6FAC; }
    QListWidget::item:hover { background-color: #2A2A2A; }
    QPushButton {
        font-size: 14px;
        background-color: #3A3A3A; color: #E0E0E0;
        border: 1px solid #555; border-radius: 3px; padding: 7px 16px;
    }
    QPushButton:hover { background-color: #4A4A4A; }
    QPushButton:pressed { background-color: #2C6FAC; }
    QLineEdit {
        font-size: 14px;
        background-color: #323232; color: #E0E0E0;
        border: 1px solid #555; border-radius: 3px; padding: 5px;
    }
    QMenuBar { font-size: 14px; background-color: #333; color: #CCC; }
    QMenuBar::item:selected { background-color: #2C6FAC; }
    QMenu { font-size: 14px; background-color: #333; color: #DDD; border: 1px solid #555; }
    QMenu::item:selected { background-color: #2C6FAC; }
    QStatusBar { font-size: 13px; background-color: #333; color: #AAA; }
    QScrollArea { border: none; }
    QDialog { background-color: #2B2B2B; color: #E0E0E0; }
    QToolBar { background-color: #333; border: none; spacing: 6px; padding: 4px; }
    QToolBar QToolButton { color: #EEE; font-size: 14px; padding: 4px 10px; }
    QScrollBar:vertical {
        background: #3A3A3A; width: 12px; border-radius: 4px;
    }
    QScrollBar::handle:vertical {
        background: #777; min-height: 30px; border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover { background: #999; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal {
        background: #3A3A3A; height: 12px; border-radius: 4px;
    }
    QScrollBar::handle:horizontal {
        background: #777; min-width: 30px; border-radius: 4px;
    }
    QScrollBar::handle:horizontal:hover { background: #999; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QSplitter::handle { background: #666; }
"""

_LIGHT_THEME = """
    QMainWindow { background-color: #F5F5F5; color: #222; }
    QLabel { color: #222; }
    QLabel#welcomeTitle { font-size: 34px; font-weight: bold; color: #2C6FAC; }
    QLabel#welcomeSubtitle { font-size: 18px; }
    QLabel#welcomeHint { font-size: 15px; color: #666; }
    QLabel#navPathLabel { font-size: 13px; color: #555; }
    QLabel#navCountLabel { font-size: 13px; color: #555; }
    QGroupBox {
        font-weight: bold; font-size: 15px;
        border: 1px solid #CCC; border-radius: 4px;
        margin-top: 8px; padding-top: 16px; color: #222;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
    QTableView {
        font-size: 14px;
        gridline-color: #DDD; background-color: #FFF;
        alternate-background-color: #F0F4F8;
        selection-background-color: #2C6FAC; color: #222;
    }
    QHeaderView::section {
        font-size: 14px;
        background-color: #E8E8E8; color: #222;
        padding: 5px; border: 1px solid #CCC;
    }
    QListWidget { font-size: 14px; background-color: #FFF; color: #222; border: 1px solid #CCC; }
    QListWidget::item:selected { background-color: #2C6FAC; color: #FFF; }
    QListWidget::item:hover { background-color: #E8E8E8; }
    QPushButton {
        font-size: 14px;
        background-color: #E0E0E0; color: #222;
        border: 1px solid #BBB; border-radius: 3px; padding: 7px 16px;
    }
    QPushButton:hover { background-color: #D0D0D0; }
    QPushButton:pressed { background-color: #2C6FAC; color: #FFF; }
    QLineEdit {
        font-size: 14px;
        background-color: #FFF; color: #222;
        border: 1px solid #BBB; border-radius: 3px; padding: 5px;
    }
    QMenuBar { font-size: 14px; background-color: #ECECEC; color: #222; }
    QMenuBar::item:selected { background-color: #2C6FAC; color: #FFF; }
    QMenu { font-size: 14px; background-color: #FFF; color: #222; border: 1px solid #CCC; }
    QMenu::item:selected { background-color: #2C6FAC; color: #FFF; }
    QStatusBar { font-size: 13px; background-color: #ECECEC; color: #555; }
    QScrollArea { border: none; }
    QDialog { background-color: #F5F5F5; color: #222; }
    QToolBar { background-color: #E8E8E8; border: none; spacing: 6px; padding: 4px; }
    QToolBar QToolButton { color: #222; font-size: 14px; padding: 4px 10px; }
    QScrollBar:vertical {
        background: #E8E8E8; width: 12px; border-radius: 4px;
    }
    QScrollBar::handle:vertical {
        background: #AAA; min-height: 30px; border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover { background: #888; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal {
        background: #E8E8E8; height: 12px; border-radius: 4px;
    }
    QScrollBar::handle:horizontal {
        background: #AAA; min-width: 30px; border-radius: 4px;
    }
    QScrollBar::handle:horizontal:hover { background: #888; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


class _UpdateSignals(QObject):
    checked = Signal(object, str, bool)
    downloaded = Signal(object, str)


class MainWindow(QMainWindow):
    """grainprofiler application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MKProfiler — Maize Kernel Profiler")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        # Application font — use Times New Roman on Windows, serif on Linux
        import platform
        default_family = "serif" if platform.system() == "Linux" else "Times New Roman"

        # Keep the corn cursor inside the photo; splitters retain their resize cursor.
        from grainprofiler.resources.cursors import create_app_icon, create_corn_cursor
        QApplication.instance().setWindowIcon(create_app_icon())
        self._corn_cursor = create_corn_cursor()

        self._data_loader: DataLoader | None = None
        self._csv_encoding_keys: dict[str, str] = {}
        self._result_dir: str = ""
        self._update_checking = False
        self._update_downloading = False
        self._closing = False
        self._update_status_checks = 0
        self._update_signals = _UpdateSignals()
        self._update_signals.checked.connect(self._on_update_checked)
        self._update_signals.downloaded.connect(self._on_update_downloaded)

        self._settings = QSettings("grainprofiler", "grainprofiler")
        self._theme_name = str(self._settings.value("appearance/theme", "dark"))
        if self._theme_name not in THEMES:
            self._theme_name = "dark"
        self._font_family = str(self._settings.value("appearance/font_family", default_family) or default_family)
        try:
            self._font_size = max(10, min(22, int(self._settings.value("appearance/font_size", 14))))
        except (TypeError, ValueError):
            self._font_size = 14
        self._nav_panel = NavPanel(settings=self._settings)
        self._welcome = WelcomeWidget()

        self._dark_mode = THEMES[self._theme_name][1]
        self._apply_theme()
        self._restore_window_state()

        self._info_panel: object | None = None
        self._sample_view: object | None = None
        self._current_image_name: str = ""
        self._median_container: QWidget | None = None
        self._median_canvas: object | None = None
        self._median_boxplot: object | None = None
        self._top_splitter: QSplitter | None = None
        self._median_splitter: QSplitter | None = None
        self._cal_toolbar: QToolBar | None = None
        self._pca_panel: object | None = None
        self._vae_panel: object | None = None
        self._trait_panel: object | None = None

        self._stack = QStackedWidget()
        self._stack.addWidget(self._welcome)
        self._splitter: QSplitter | None = None

        self._build_menu_bar()
        self._build_status_bar()
        self._build_cal_toolbar()
        self._previous_key = QKeySequence(str(self._settings.value("shortcuts/previous", "Left")))
        self._next_key = QKeySequence(str(self._settings.value("shortcuts/next", "Right")))
        if self._previous_key.isEmpty() or self._next_key.isEmpty() or self._previous_key == self._next_key:
            self._previous_key, self._next_key = QKeySequence("Left"), QKeySequence("Right")
        QApplication.instance().installEventFilter(self)

        self.setCentralWidget(self._stack)

        # Wire signals
        self._nav_panel.folder_opened.connect(self._on_folder_opened)
        self._nav_panel.sample_selected.connect(self._on_sample_selected)

        # Auto-load last folder
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._auto_load_last)
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            QTimer.singleShot(1000, self._report_update_status)
            QTimer.singleShot(5000, lambda: self._check_for_updates(manual=False))

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        _, self._dark_mode, background, _ = THEMES[self._theme_name]
        QApplication.instance().setFont(QFont(self._font_family, self._font_size))
        handle = "#687f95" if self._dark_mode else "#a9b1ba"
        checked = "#395d78" if self._dark_mode else "#d4dce5"
        stylesheet = (_DARK_THEME if self._dark_mode else _LIGHT_THEME) + f"""
            QSplitter::handle {{ background: {handle}; }}
            QSplitter::handle:hover {{ background: #4b9ec8; }}
            QSplitter::handle:pressed {{ background: #31769d; }}
            QToolBar QToolButton:checked {{ background: {checked}; border-radius: 4px; }}
        """
        self.setStyleSheet(appearance_stylesheet(stylesheet, self._theme_name, self._font_size))
        self._nav_panel.setMinimumWidth(round(220 * self._font_size / 14))
        # Update viewport background for SampleView (if already created)
        if hasattr(self, '_sample_view') and self._sample_view is not None:
            from PySide6.QtGui import QBrush, QColor
            self._sample_view.setBackgroundBrush(QBrush(QColor(background)))
        if hasattr(self, '_info_panel') and self._info_panel is not None:
            self._info_panel.setMinimumWidth(round(300 * self._font_size / 14))
            self._info_panel.set_dark_theme(self._dark_mode, self._theme_name, self._font_size)
        if hasattr(self, '_visual_actions'):
            for name, action in self._visual_actions.items():
                action.setIcon(action_icon(name, self._dark_mode))
        self._nav_panel.set_theme_state(self._dark_mode)

    def _set_appearance(self, theme: str, font_family: str, font_size: int) -> None:
        if theme not in THEMES or not font_family.strip() or not 10 <= font_size <= 22:
            raise ValueError("Choose a valid theme, font and size between 10 and 22.")
        self._theme_name, self._font_family, self._font_size = theme, font_family, font_size
        self._settings.setValue("appearance/theme", theme)
        self._settings.setValue("appearance/font_family", font_family)
        self._settings.setValue("appearance/font_size", font_size)
        self._apply_theme()

    def _show_appearance_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Appearance")
        form = QFormLayout(dialog)
        themes = QComboBox(dialog)
        for key, (label, _dark, _background, _colours) in THEMES.items():
            themes.addItem(label, key)
        themes.setCurrentIndex(themes.findData(self._theme_name))
        fonts = QFontComboBox(dialog)
        fonts.setCurrentFont(QFont(self._font_family))
        size = QSpinBox(dialog)
        size.setRange(10, 22)
        size.setValue(self._font_size)
        form.addRow("Theme:", themes)
        form.addRow("Font:", fonts)
        form.addRow("Text size (default 14):", size)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form.addRow(buttons)

        def save():
            self._set_appearance(themes.currentData(), fonts.currentFont().family(), size.value())
            dialog.accept()

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        dialog.exec()

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _build_menu_bar(self) -> None:
        from PySide6.QtGui import QAction, QKeySequence
        from PySide6.QtWidgets import QMenuBar

        mb: QMenuBar = self.menuBar()

        file_menu = mb.addMenu("&File")
        open_action = QAction("&Open Result Folder...", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._nav_panel._on_open_clicked)
        file_menu.addAction(open_action)
        file_menu.addSeparator()

        # Recent folders submenu
        self._recent_menu = file_menu.addMenu("Recent Folders")
        self._recent_menu.aboutToShow.connect(self._update_recent_menu)

        export_action = QAction("&Export Sample CSV...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.triggered.connect(self._export_current_csv)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = mb.addMenu("&View")
        self._toggle_overlays_action = QAction("Show &Overlays", self)
        self._toggle_overlays_action.setCheckable(True)
        self._toggle_overlays_action.setChecked(True)
        self._toggle_overlays_action.triggered.connect(self._toggle_overlays)
        view_menu.addAction(self._toggle_overlays_action)
        view_menu.addSeparator()
        fit_action = QAction("&Fit to Window", self)
        fit_action.setShortcut(QKeySequence("Ctrl+0"))
        fit_action.triggered.connect(self._fit_to_window)
        view_menu.addAction(fit_action)

        # Tools menu
        tools_menu = mb.addMenu("&Tools")

        self._median_action = QAction("&Median Profile", self)
        self._median_action.setCheckable(True)
        self._median_action.setShortcut(QKeySequence("Ctrl+M"))
        self._median_action.setEnabled(False)
        self._median_action.triggered.connect(self._on_median_toggled)
        tools_menu.addAction(self._median_action)

        self._cal_action = QAction("&Calibration Ruler", self)
        self._cal_action.setCheckable(True)
        self._cal_action.setShortcut(QKeySequence("Ctrl+R"))
        self._cal_action.setEnabled(False)
        self._cal_action.triggered.connect(self._on_calibration_toggled)
        tools_menu.addAction(self._cal_action)

        # Analyze
        analyze_menu = mb.addMenu("&Analyze")
        pca_action = QAction("&PCA Analysis", self)
        pca_action.triggered.connect(self._on_pca)
        analyze_menu.addAction(pca_action)
        vae_action = QAction("&VAE Latent Explorer", self)
        vae_action.triggered.connect(self._on_vae_latent)
        analyze_menu.addAction(vae_action)
        trait_action = QAction("&Trait Distribution", self)
        trait_action.triggered.connect(self._on_trait_analysis)
        analyze_menu.addAction(trait_action)

        settings_menu = mb.addMenu("&Settings")
        appearance_action = QAction("Appearance...", self)
        appearance_action.triggered.connect(self._show_appearance_settings)
        settings_menu.addAction(appearance_action)
        shortcut_action = QAction("Keyboard shortcuts...", self)
        shortcut_action.triggered.connect(self._show_shortcut_settings)
        settings_menu.addAction(shortcut_action)
        self._trust_plant_ids_action = QAction("Use unverified current plant IDs", self)
        self._trust_plant_ids_action.setCheckable(True)
        self._trust_plant_ids_action.setEnabled(False)
        self._trust_plant_ids_action.triggered.connect(self._toggle_unverified_plant_ids)
        settings_menu.addAction(self._trust_plant_ids_action)

        help_menu = mb.addMenu("&Help")
        update_action = QAction("Check for updates...", self)
        update_action.triggered.connect(lambda: self._check_for_updates(manual=True))
        help_menu.addAction(update_action)
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        # The toolbar reuses the menu actions so their state and shortcuts stay in sync.
        self._visual_toolbar = QToolBar("Visualization", self)
        self._visual_toolbar.setObjectName("visualizationToolbar")
        self._visual_toolbar.setMovable(False)
        self._visual_toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._visual_actions = {
            "overlay": self._toggle_overlays_action,
            "fit": fit_action,
            "median": self._median_action,
            "ruler": self._cal_action,
            "pca": pca_action,
            "vae": vae_action,
            "distribution": trait_action,
        }
        for name, action in self._visual_actions.items():
            action.setIcon(action_icon(name, self._dark_mode))
            action.setToolTip(action.text().replace("&", ""))
            self._visual_toolbar.addAction(action)
        self.addToolBar(self._visual_toolbar)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _build_status_bar(self) -> None:
        self._status = QStatusBar()
        self._status.showMessage("Ready")
        self.setStatusBar(self._status)

    def _build_cal_toolbar(self) -> None:
        self._cal_toolbar = QToolBar("Calibration")
        self._cal_toolbar.setVisible(False)
        self._cal_toolbar.setMovable(False)

        from PySide6.QtGui import QAction

        self._cal_draw_toggle = QAction("Pan Mode", self)
        self._cal_draw_toggle.triggered.connect(self._on_cal_draw_toggle)
        self._cal_toolbar.addAction(self._cal_draw_toggle)

        undo_act = QAction("Undo", self)
        undo_act.triggered.connect(self._on_cal_undo)
        self._cal_toolbar.addAction(undo_act)

        self._cal_toolbar.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(lambda: self._on_calibration_toggled(False))
        self._cal_toolbar.addAction(exit_act)

        self.addToolBar(self._cal_toolbar)

    def _on_cal_draw_toggle(self) -> None:
        if self._sample_view is not None:
            draw = self._sample_view.toggle_cal_draw_mode()
            self._cal_draw_toggle.setText("Pan Mode" if draw else "Draw Mode")

    def _on_cal_undo(self) -> None:
        if self._sample_view is not None:
            self._sample_view.undo_calibration_line()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _choose_csv_encoding(self, filename: str, examples: tuple[str, str]) -> str | None:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Question)
        dialog.setTextFormat(Qt.PlainText)
        dialog.setWindowTitle("Choose CSV encoding")
        dialog.setText(f"{filename} can be decoded in two ways. Select the version that displays your text correctly.")
        dialog.setInformativeText(f"UTF-8: {examples[0]}\n\nGB18030: {examples[1]}")
        utf8 = dialog.addButton("UTF-8", QMessageBox.AcceptRole)
        chinese = dialog.addButton("GB18030", QMessageBox.AcceptRole)
        dialog.addButton(QMessageBox.Cancel)
        dialog.exec()
        if dialog.clickedButton() is utf8:
            return "utf-8"
        if dialog.clickedButton() is chinese:
            return "gb18030"
        return None

    def _on_folder_opened(self, result_dir: str) -> None:
        if self._info_panel is not None and self._info_panel.has_pending_metadata_edits():
            answer = QMessageBox.question(
                self, "Unsaved metadata", "Discard unconfirmed metadata changes and open another folder?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        dl = DataLoader()
        result = dl.load(result_dir)
        choices, digests, mtimes, encoding_keys = {}, {}, {}, {}
        for filename, (utf8, chinese, file_digest) in result.ambiguous_csvs.items():
            path = Path(result_dir) / filename
            path_digest = hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()
            encoding_key = "csv_encodings/" + path_digest
            try:
                file_mtime = path.stat().st_mtime_ns
            except OSError:
                QMessageBox.warning(self, "Result file changed", f"Cannot read {filename}; reopen the result folder.")
                return
            fingerprint = file_digest + ":" + str(file_mtime) + ":"
            cached = str(self._settings.value(encoding_key, ""))
            if cached in (fingerprint + "utf-8", fingerprint + "gb18030"):
                selected = cached.rsplit(":", 1)[1]
            else:
                selected = self._choose_csv_encoding(filename, (utf8, chinese))
                if selected is None:
                    return
                self._settings.setValue(encoding_key, fingerprint + selected)
            choices[filename] = selected
            digests[filename] = file_digest
            mtimes[filename] = file_mtime
            encoding_keys[filename] = encoding_key
        if choices:
            dl = DataLoader()
            result = dl.load(result_dir, csv_encodings=choices, csv_digests=digests, csv_mtimes=mtimes)
        if not result.ok:
            QMessageBox.critical(self, "Load Error", "\n".join(result.errors))
            return
        self._data_loader = dl
        self._csv_encoding_keys = encoding_keys
        self._trust_plant_ids_action.setChecked(False)
        self._trust_plant_ids_action.setEnabled(bool(dl._unverified_originals))
        self._result_dir = result_dir
        self._build_workspace()
        self._restore_splitter_sizes()
        plant_names = {}
        if {"image_name", "plant_name"} <= set(dl.metadata.columns):
            metadata = dl.metadata[["image_name", "plant_name"]].fillna("").drop_duplicates("image_name")
            plant_names = {str(row.image_name): str(row.plant_name) for row in metadata.itertuples(index=False)}
        self._nav_panel.populate(dl.get_sample_ids(), result_dir, plant_names=plant_names)
        self._median_action.setEnabled(True)
        self._cal_action.setEnabled(True)
        message = f"Loaded {len(dl.image_names)} samples, {result.total_kernels} kernels"
        if result.warnings:
            message += " | " + "; ".join(result.warnings)
        self._status.showMessage(message)
        self._stack.setCurrentIndex(1)
        if self._sample_view is not None:
            self._sample_view.setFocus(Qt.OtherFocusReason)
        # Save last folder + recent list
        settings = QSettings("grainprofiler", "grainprofiler")
        settings.setValue("last_folder", result_dir)
        self._add_recent_folder(result_dir)

    def _on_sample_selected(self, image_name: str) -> None:
        if self._data_loader is None:
            return
        self._current_image_name = image_name
        if self._sample_view is not None:
            self._sample_view.load_sample(image_name, self._data_loader)
        if self._info_panel is not None:
            self._info_panel.load_sample(image_name, self._data_loader)
        if self._median_action.isChecked():
            self._hide_median_chart()
            self._show_median_chart(image_name)
        self._status.showMessage(f"Sample: {image_name}")

    def _on_metadata_saved(self, image_name: str) -> None:
        if self._data_loader is not None and "metadata.csv" in self._csv_encoding_keys:
            try:
                digest = csv_file_sha256(Path(self._result_dir) / "metadata.csv")
                mtime = (Path(self._result_dir) / "metadata.csv").stat().st_mtime_ns
                self._data_loader.csv_digests["metadata.csv"] = digest
                self._data_loader.csv_mtimes["metadata.csv"] = mtime
                self._settings.setValue(self._csv_encoding_keys["metadata.csv"], digest + ":" + str(mtime) + ":" + self._data_loader.metadata_encoding)
            except OSError:
                pass
        if self._sample_view is not None:
            self._sample_view.update_metadata_caption(image_name)
        if self._data_loader is not None:
            self._trust_plant_ids_action.setEnabled(bool(self._data_loader._unverified_originals))
            metadata = self._data_loader.get_image_metadata(image_name)
            if metadata is not None:
                name = metadata.get("plant_name", "")
                self._nav_panel.update_plant_name(image_name, str(name) if name is not None else "")

    def _toggle_unverified_plant_ids(self, checked: bool) -> None:
        if self._data_loader is None:
            return
        if self._info_panel is not None and self._info_panel.has_pending_metadata_edits():
            QMessageBox.warning(self, "Unsaved metadata", "Save or discard pending edits before changing this setting.")
            self._trust_plant_ids_action.setChecked(not checked)
            return
        if checked:
            answer = QMessageBox.question(
                self, "Unverified plant IDs",
                "Some original plant IDs cannot be verified. If names were changed externally, using current IDs may display another plant's derived results. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self._trust_plant_ids_action.setChecked(False)
                return
        self._data_loader.trust_unverified_plant_ids = checked
        self._data_loader._build_image_to_plant_map()
        if self._current_image_name:
            self._on_sample_selected(self._current_image_name)

    def _set_navigation_shortcuts(self, previous: str, next_: str) -> None:
        previous_key = QKeySequence.fromString(previous, QKeySequence.PortableText)
        next_key = QKeySequence.fromString(next_, QKeySequence.PortableText)
        if previous_key.isEmpty() or next_key.isEmpty() or previous_key.count() != 1 or next_key.count() != 1:
            raise ValueError("Choose one key combination for each direction.")
        if previous_key == next_key:
            raise ValueError("Previous and next must use different shortcuts.")
        reserved = {
            action.shortcut().toString(QKeySequence.PortableText)
            for action in self.findChildren(QAction) if not action.shortcut().isEmpty()
        }
        previous_text = previous_key.toString(QKeySequence.PortableText)
        next_text = next_key.toString(QKeySequence.PortableText)
        if previous_text in reserved or next_text in reserved:
            raise ValueError("This shortcut is already used by a menu action.")
        self._previous_key, self._next_key = previous_key, next_key
        self._settings.setValue("shortcuts/previous", previous_text)
        self._settings.setValue("shortcuts/next", next_text)

    def _show_shortcut_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Keyboard shortcuts")
        form = QFormLayout(dialog)
        previous = QKeySequenceEdit(self._previous_key, dialog)
        next_ = QKeySequenceEdit(self._next_key, dialog)
        previous.setMaximumSequenceLength(1)
        next_.setMaximumSequenceLength(1)
        form.addRow("Previous image:", previous)
        form.addRow("Next image:", next_)
        form.addRow(QLabel("Shortcuts work while the photo or sample list has focus."))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        form.addRow(buttons)

        def save():
            try:
                self._set_navigation_shortcuts(
                    previous.keySequence().toString(QKeySequence.PortableText),
                    next_.keySequence().toString(QKeySequence.PortableText),
                )
            except ValueError as error:
                QMessageBox.warning(dialog, "Invalid shortcuts", str(error))
                return
            dialog.accept()

        def reset():
            previous.setKeySequence(QKeySequence("Left"))
            next_.setKeySequence(QKeySequence("Right"))

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(reset)
        dialog.exec()

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.KeyPress
            and isinstance(watched, QWidget)
            and watched.window() is self
            and self._data_loader is not None
            and self._stack.currentWidget() is self._splitter
        ):
            focus = QApplication.focusWidget()
            allowed = (self, self._splitter, self._nav_panel._list, self._nav_panel._list.viewport())
            if self._sample_view is not None:
                allowed += (self._sample_view, self._sample_view.viewport())
            if focus not in allowed:
                return False
            key = QKeySequence(event.keyCombination())
            if key == self._previous_key:
                self._on_navigate_prev()
                return True
            if key == self._next_key:
                self._on_navigate_next()
                return True
        return super().eventFilter(watched, event)

    def _export_current_csv(self) -> None:
        if self._info_panel is not None:
            self._info_panel.export_csv()

    def _toggle_overlays(self, visible: bool) -> None:
        if self._sample_view is not None:
            self._sample_view.set_overlays_visible(visible)
        self._toggle_overlays_action.setChecked(visible)

    def _fit_to_window(self) -> None:
        if self._sample_view is not None:
            self._sample_view.fitInView(
                self._sample_view.scene().sceneRect(), Qt.KeepAspectRatio
            )

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "About MKProfiler",
            f"MKProfiler v{__version__}\n\n"
            "Maize Kernel Profiler\n\n"
            "Desktop tool for visually inspecting pipeline outputs.\n"
            "No GPU or pipeline dependencies required.",
        )

    def _check_for_updates(self, manual: bool = False) -> None:
        if self._closing or self._update_checking or self._update_downloading:
            return
        self._update_checking = True
        signals = self._update_signals

        def run():
            try:
                release = check_for_update(__version__, "ChangQGuo", "MKProfiler")
                signals.checked.emit(release, "", manual)
            except Exception as error:
                signals.checked.emit(None, str(error), manual)

        Thread(target=run, name="mkprofiler-update-check", daemon=True).start()

    def _report_update_status(self) -> None:
        value = str(self._settings.value("update/status_path", "") or "")
        if not value or self._closing:
            return
        path = Path(value)
        if (path.parent != Path(sys.executable).absolute().parent
                or not re.fullmatch(r"MKProfiler\.exe\.update-status-[0-9a-f]{32}\.txt", path.name)):
            return
        try:
            with path.open("r", encoding="ascii") as source:
                status = source.read(64).strip()
        except (OSError, UnicodeError):
            return
        if status in ("pending", "ready"):
            self._update_status_checks += 1
            if self._update_status_checks < 35:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2000, self._report_update_status)
            return
        if status == "installed":
            self._status.showMessage("MKProfiler update installed", 10000)
        elif status == "installed-unverified":
            QMessageBox.warning(
                self, "Update status",
                "The new application started, but its startup could not be verified. "
                "A backup is available in the application folder.",
            )
        else:
            QMessageBox.warning(
                self, "Update failed",
                "The previous update failed or did not complete. A backup may be available in the application folder. "
                "Please try again or install the new version manually.",
            )
        self._settings.remove("update/status_path")
        self._settings.sync()

    def _on_update_checked(self, release, error: str, manual: bool) -> None:
        self._update_checking = False
        if self._closing:
            return
        if error:
            if manual:
                QMessageBox.warning(self, "Update check", "Could not check for updates. Check your network connection and try again.")
            return
        if release is None:
            if manual:
                QMessageBox.information(self, "Update check", "MKProfiler is up to date.")
            return
        if not getattr(sys, "frozen", False):
            QMessageBox.information(self, "Update available", f"MKProfiler v{release.version} is available on GitHub Releases. Automatic installation is available in the Windows executable.")
            return
        answer = QMessageBox.question(
            self, "Update available",
            f"MKProfiler v{release.version} is available. Download it in the background?\n\nYou can choose when to restart and install it.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._start_update_download(release)

    def _start_update_download(self, release) -> None:
        if self._update_downloading or self._closing:
            return
        self._update_downloading = True
        self._status.showMessage("Downloading and verifying the update in the background…")
        signals = self._update_signals

        def run():
            try:
                signals.downloaded.emit(prepare_update(release), "")
            except Exception as error:
                signals.downloaded.emit(None, str(error))

        Thread(target=run, name="mkprofiler-update-download", daemon=True).start()

    def _on_update_downloaded(self, prepared, error: str) -> None:
        self._update_downloading = False
        if self._closing:
            if prepared is not None:
                prepared.cleanup()
            return
        if error or prepared is None:
            self._status.showMessage("Update download or verification failed")
            QMessageBox.warning(self, "Update failed", "The update could not be downloaded or verified. Your current application has not been changed.")
            return
        self._status.showMessage("Update downloaded and verified")
        if self._info_panel is not None and self._info_panel.has_pending_metadata_edits():
            prepared.cleanup()
            QMessageBox.warning(self, "Unsaved metadata", "Save or discard your pending metadata edits before installing an update. You can then check for updates again.")
            return
        answer = QMessageBox.question(
            self, "Install update", "Restart MKProfiler and install the verified update now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            prepared.cleanup()
            return
        try:
            pending = schedule_install(prepared)
            self._settings.setValue("update/status_path", str(pending.status_path))
            self._settings.setValue("update/backup_path", str(pending.backup_path))
            self._settings.setValue("update/backup_sha256", pending.backup_sha256)
            self._settings.sync()
            if self._settings.status() != _SETTINGS_NO_ERROR:
                raise RuntimeError("Could not save update recovery information")
            pending.authorize()
        except Exception:
            prepared.cleanup()
            QMessageBox.warning(self, "Update failed", "The update could not be installed. Check that the application folder is writable; the existing application has not been changed.")
            return
        try:
            prepared.cleanup()
        except OSError:
            pass
        self.close()

    # ------------------------------------------------------------------
    # Workspace
    # ------------------------------------------------------------------

    def _build_workspace(self) -> None:
        from grainprofiler.widgets.sample_info_panel import SampleInfoPanel
        from grainprofiler.widgets.sample_view import SampleView

        # Remove old workspace from stack if re-opening
        if self._splitter is not None:
            self._stack.removeWidget(self._splitter)
            self._splitter.deleteLater()
            self._splitter = None

        self._sample_view = SampleView()
        self._sample_view.viewport().setCursor(self._corn_cursor)
        self._info_panel = SampleInfoPanel()

        self._sample_view.kernel_selected.connect(self._on_kernel_selected_from_view)
        self._sample_view.navigate_prev.connect(self._on_navigate_prev)
        self._sample_view.navigate_next.connect(self._on_navigate_next)
        self._info_panel.kernel_row_selected.connect(self._on_kernel_selected_from_table)
        self._info_panel.kernel_row_double_clicked.connect(self._open_kernel_detail)
        self._info_panel.metadata_saved.connect(self._on_metadata_saved)

        # Top area: SampleView | SimilarityBoxPlot (box plot added when median shown)
        self._top_splitter = QSplitter(Qt.Horizontal)
        self._top_splitter.setHandleWidth(9)
        self._top_splitter.addWidget(self._sample_view)

        # Wrap in vertical splitter: top_splitter / median_chart
        self._median_splitter = QSplitter(Qt.Vertical)
        self._median_splitter.setHandleWidth(9)
        self._median_splitter.addWidget(self._top_splitter)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(9)
        main_splitter.addWidget(self._nav_panel)
        main_splitter.addWidget(self._median_splitter)
        main_splitter.addWidget(self._info_panel)
        main_splitter.handle(1).setToolTip("Drag to resize the sample list")
        main_splitter.handle(2).setToolTip("Drag to resize sample information")
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setStretchFactor(2, 0)
        main_splitter.setSizes([250, 700, 350])
        main_splitter.splitterMoved.connect(self._on_splitter_moved)

        self._splitter = main_splitter
        self._stack.addWidget(main_splitter)
        self._apply_theme()

    def _on_kernel_selected_from_view(self, kernel_name: str) -> None:
        if self._info_panel is not None:
            self._info_panel.select_kernel(kernel_name)
        if not self._cal_action.isChecked():
            self._open_kernel_detail(kernel_name)

    def _on_kernel_selected_from_table(self, kernel_name: str) -> None:
        if self._sample_view is not None:
            self._sample_view.select_kernel(kernel_name)
        self._open_kernel_detail(kernel_name)

    def _open_kernel_detail(self, kernel_name: str) -> None:
        if self._data_loader is None:
            return
        from grainprofiler.widgets.kernel_detail_dialog import KernelDetailDialog
        dlg = KernelDetailDialog(kernel_name, self._data_loader, self._result_dir, self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Median profile
    # ------------------------------------------------------------------

    def _on_median_toggled(self, checked: bool) -> None:
        if checked and self._data_loader is not None:
            img = getattr(self, '_current_image_name', '')
            if img:
                self._show_median_chart(img)
            else:
                self._status.showMessage("Select a sample first")
                self._median_action.setChecked(False)
        elif not checked:
            self._hide_median_chart()

    def _show_median_chart(self, image_name: str = "") -> None:
        if self._median_splitter is None or self._data_loader is None:
            return
        self._hide_median_chart()  # clean up any previous chart
        dl = self._data_loader
        img = image_name or getattr(self, '_current_image_name', '')
        if not img:
            self._status.showMessage("Select a sample first")
            self._median_action.setChecked(False)
            return

        kernel_profiles = dl.get_kernel_width_profiles_for_image(img)
        if kernel_profiles:
            from grainprofiler.widgets.median_chart import MedianChart
            chart = MedianChart(kernel_profiles, img, self._dark_mode, self._median_splitter)

            # Bidirectional sync: median ↔ overlay ↔ table
            if self._sample_view is not None:
                chart.kernel_hovered.connect(self._on_median_kernel_hovered)
                chart.kernel_clicked.connect(self._sample_view.select_kernel)
                chart.kernel_clicked.connect(self._on_median_kernel_clicked_for_table)
                self._sample_view.kernel_hovered.connect(chart.highlight_kernel)
                self._sample_view.kernel_selected.connect(chart.highlight_kernel)
                if self._info_panel is not None:
                    self._info_panel.kernel_row_selected.connect(chart.highlight_kernel)

            self._median_canvas = chart
            self._median_splitter.addWidget(chart)

            # --- Box plot in right panel of top splitter ---
            try:
                from grainprofiler.widgets.similarity_boxplot import SimilarityBoxPlot
                boxplot = SimilarityBoxPlot(kernel_profiles, img, self._dark_mode,
                                            self._top_splitter)
                boxplot.kernel_hovered.connect(chart.highlight_kernel)
                boxplot.kernel_hovered.connect(self._sample_view.highlight_kernel)
                boxplot.kernel_clicked.connect(self._on_boxplot_kernel_clicked)
                boxplot.kernel_delete_requested.connect(self._on_kernel_delete_requested)
                self._median_boxplot = boxplot
                self._top_splitter.addWidget(boxplot)
                if self._top_splitter.width() > 0:
                    self._top_splitter.setSizes([
                        int(self._top_splitter.width() * 0.63),
                        int(self._top_splitter.width() * 0.37),
                    ])

                outliers = set(boxplot.outlier_kernels)
                if self._sample_view is not None:
                    self._sample_view.set_outlier_kernels(outliers)
            except Exception as e:
                self._status.showMessage(f"Box plot error: {e}")

            if self._median_splitter.height() > 0:
                self._median_splitter.setSizes([
                    int(self._median_splitter.height() * 0.62),
                    int(self._median_splitter.height() * 0.38),
                ])
            return

        # Fallback: pre-rendered PNG
        plant = dl.image_to_plant.get(img, "")
        from pathlib import Path
        png_path = Path(dl.result_dir) / "representative_shapes" / plant / f"{plant}_stacked_area.png" if plant else None
        if not png_path or not png_path.exists():
            self._status.showMessage("No median data (re-run Stage 5)")
            self._median_action.setChecked(False)
            return
        pixmap = QPixmap(str(png_path))
        if pixmap.isNull():
            self._median_action.setChecked(False)
            return
        from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView
        s = QGraphicsScene(); s.addItem(QGraphicsPixmapItem(pixmap)); s.setSceneRect(pixmap.rect())
        v = QGraphicsView(s); v.setRenderHints(QPainter.Antialiasing|QPainter.SmoothPixmapTransform)
        v.setDragMode(QGraphicsView.ScrollHandDrag); v.setMinimumHeight(200)
        self._median_canvas = v
        self._median_splitter.addWidget(v)
        self._median_splitter.setSizes([int(self._median_splitter.height() * 0.7),
                                        int(self._median_splitter.height() * 0.3)])

    def _hide_median_chart(self) -> None:
        # Remove box plot
        if self._median_boxplot is not None:
            boxplot = self._median_boxplot
            try:
                boxplot.kernel_hovered.disconnect()
            except Exception:
                pass
            try:
                boxplot.kernel_clicked.disconnect()
            except Exception:
                pass
            try:
                boxplot.kernel_delete_requested.disconnect()
            except Exception:
                pass
            if hasattr(boxplot, '_cleanup'):
                boxplot._cleanup()
            boxplot.hide()
            boxplot.setParent(None)
            boxplot.deleteLater()
            self._median_boxplot = None

        # Clear outlier highlights
        if self._sample_view is not None:
            self._sample_view.set_outlier_kernels(set())

        # Remove median chart
        if self._median_canvas is not None:
            chart = self._median_canvas
            try:
                chart.kernel_hovered.disconnect()
                chart.kernel_clicked.disconnect()
            except Exception:
                pass
            if self._sample_view is not None:
                try:
                    self._sample_view.kernel_hovered.disconnect(chart.highlight_kernel)
                    self._sample_view.kernel_selected.disconnect(chart.highlight_kernel)
                except Exception:
                    pass
            if self._info_panel is not None:
                try:
                    self._info_panel.kernel_row_selected.disconnect(chart.highlight_kernel)
                except Exception:
                    pass
            if hasattr(chart, '_cleanup'):
                chart._cleanup()
            chart.hide()
            chart.setParent(None)
            chart.deleteLater()
            self._median_canvas = None

    def _on_median_kernel_hovered(self, kn: str) -> None:
        if self._sample_view is not None:
            if kn:
                self._sample_view.highlight_kernel(kn)
            else:
                self._sample_view.clear_highlight()

    def _on_median_kernel_clicked_for_table(self, kn: str) -> None:
        if self._info_panel is not None:
            self._info_panel.select_kernel(kn)

    def _on_boxplot_kernel_clicked(self, kn: str) -> None:
        if self._sample_view is not None:
            self._sample_view.select_kernel(kn)
        if self._info_panel is not None:
            self._info_panel.select_kernel(kn)

    def _on_kernel_delete_requested(self, kn: str) -> None:
        """Handle kernel deletion from box plot right-click menu."""
        short = kn.split("_kernel_")[1].replace(".jpg", "") if "_kernel_" in kn else kn
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete Kernel {short}?\n\n"
            f"This will permanently remove all morphological data for this kernel.\n"
            f"Weight and kernel count will remain unchanged.\n\n"
            f"After deletion, please re-run pipeline from Stage 5 (shapes).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._delete_kernel(kn, short)

    def _mark_kernel_deleted_in_bbox(self, result_dir: str, image_name: str, kid: int) -> bool:
        """Mark a kernel's YOLO detection as ``deleted`` in yolo_bounding_boxes.json.

        Stage 3 (segmentation) reads this file and skips ``deleted`` detections, so
        re-running from Stage 3 stops the kernel from being re-segmented; Stages 4/5
        enumerate kernels from ``masks_binary/``, which Stage 3 then regenerates
        without it.  Returns ``True`` if the file was updated.
        """
        import json
        from pathlib import Path

        bbox_path = Path(result_dir) / "yolo_bounding_boxes.json"
        if not bbox_path.exists():
            return False

        try:
            with open(bbox_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False

        entry = data.get(image_name)
        if not isinstance(entry, dict):
            return False

        updated = False

        # 1. Flag the detection in the authoritative ``detections`` list.
        for det in entry.get("detections", []):
            if isinstance(det, dict) and int(det.get("kernel_id") or -1) == kid:
                det["deleted"] = True
                updated = True

        # 2. Drop it from ``accepted_detections`` (the branch the segmenter checks first).
        accepted = entry.get("accepted_detections")
        if isinstance(accepted, list):
            before = len(accepted)
            entry["accepted_detections"] = [
                d for d in accepted
                if not (isinstance(d, dict) and int(d.get("kernel_id") or -1) == kid)
            ]
            updated = updated or (len(entry["accepted_detections"]) != before)

        if not updated:
            return False

        try:
            with open(bbox_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            return False
        return True

    def _delete_kernel(self, kn: str, short: str) -> None:
        """Remove kernel from files AND in-memory DataLoader state."""
        if self._data_loader is None:
            return

        dl = self._data_loader
        result_dir = dl.result_dir

        import pandas as pd
        from pathlib import Path

        # 1. Update only one unambiguous measurements file.
        meas_csv = Path(result_dir) / "measurements.csv"
        meas_pqt = Path(result_dir) / "measurements.parquet"
        for path in (meas_csv, meas_pqt):
            expected = dl.measurement_fingerprints.get(path.name)
            try:
                unchanged = (not path.exists()) if expected is None else (
                    path.stat().st_mtime_ns == expected[1] and csv_file_sha256(path) == expected[0]
                )
            except OSError:
                unchanged = False
            if not unchanged:
                QMessageBox.warning(self, "Result file changed", f"{path.name} changed after loading. Reopen the result folder before deleting a kernel.")
                return
        if meas_csv.exists() and meas_pqt.exists():
            QMessageBox.warning(
                self, "Unable to delete kernel",
                "Both measurements.csv and measurements.parquet are present. Deletion is disabled until the two copies are reconciled, to avoid overwriting newer data.",
            )
            return
        if meas_csv.exists():
            try:
                remove_csv_record(
                    meas_csv, "kernel_name", kn,
                    encoding=dl.csv_encodings.get("measurements.csv"),
                    expected_sha256=dl.measurement_fingerprints["measurements.csv"][0],
                    expected_mtime=dl.measurement_fingerprints["measurements.csv"][1],
                )
            except (OSError, UnicodeError, ValueError, csv.Error) as error:
                QMessageBox.warning(self, "Unable to delete kernel", str(error))
                return
            dl.measurement_fingerprints["measurements.csv"] = (csv_file_sha256(meas_csv), meas_csv.stat().st_mtime_ns)
            if "measurements.csv" in dl.csv_encodings:
                digest = csv_file_sha256(meas_csv)
                mtime = meas_csv.stat().st_mtime_ns
                dl.csv_digests["measurements.csv"] = digest
                dl.csv_mtimes["measurements.csv"] = mtime
                if "measurements.csv" in self._csv_encoding_keys:
                    self._settings.setValue(
                        self._csv_encoding_keys["measurements.csv"], digest + ":" + str(mtime) + ":" + dl.csv_encodings["measurements.csv"],
                    )
        if meas_pqt.exists():
            staged = None
            try:
                original_digest, original_mtime = dl.measurement_fingerprints["measurements.parquet"]
                df = pd.read_parquet(meas_pqt)
                if "kernel_name" not in df.columns or kn not in set(df["kernel_name"].astype(str)):
                    raise ValueError("The selected kernel was not found in measurements.parquet.")
                df = df[df["kernel_name"] != kn]
                with tempfile.NamedTemporaryFile(dir=meas_pqt.parent, prefix=".mkprofiler-", suffix=".parquet", delete=False) as target:
                    staged = Path(target.name)
                df.to_parquet(staged, index=False)
                os.chmod(staged, stat.S_IMODE(meas_pqt.stat().st_mode))
                if meas_pqt.stat().st_mtime_ns != original_mtime or csv_file_sha256(meas_pqt) != original_digest:
                    raise OSError("measurements.parquet changed while saving; reopen the folder.")
                os.replace(staged, meas_pqt)
                dl.measurement_fingerprints["measurements.parquet"] = (csv_file_sha256(meas_pqt), meas_pqt.stat().st_mtime_ns)
            except Exception as error:
                QMessageBox.warning(self, "Unable to delete kernel", str(error))
                return
            finally:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError:
                        pass

        # 2. Remove from kernel_width_profiles.txt
        kwp_path = Path(result_dir) / "kernel_width_profiles.txt"
        if kwp_path.exists():
            with open(kwp_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open(kwp_path, "w", encoding="utf-8") as f:
                for line in lines:
                    if not line.startswith(kn + "\t") and not line.startswith(kn + " "):
                        f.write(line)

        # 2b. Persist the deletion marker so a pipeline re-run (Stage 3) skips it.
        try:
            kid = int(short)
        except (TypeError, ValueError):
            kid = None
        image_name = dl.kernel_to_image.get(kn)
        bbox_name = dl.get_bbox_image_name(image_name) if image_name else None
        if kid is not None and bbox_name:
            self._mark_kernel_deleted_in_bbox(result_dir, bbox_name, kid)

        # 3. Remove from in-memory DataLoader so the UI reflects the deletion
        dl.remove_kernel(kn)

        # 4. Show reminder
        QMessageBox.information(
            self,
            "Kernel Deleted",
            f"Kernel {short} has been deleted.\n\n"
            f"Please re-run pipeline from Stage 3 (segmentation):\n"
            f"  python pipeline/main.py config.yaml --from-stage segmentation",
        )

        # 5. Remove contour from tray image
        if self._sample_view is not None:
            self._sample_view.remove_kernel(kn)

        # 6. Refresh info panel (reload measurements)
        if self._info_panel is not None and self._current_image_name:
            self._info_panel.load_sample(self._current_image_name, self._data_loader)

        # 7. Refresh median panel
        img = getattr(self, '_current_image_name', '')
        if img and self._median_action.isChecked():
            self._hide_median_chart()
            self._show_median_chart(img)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def _on_calibration_toggled(self, checked: bool) -> None:
        self._cal_action.setChecked(checked)
        if self._cal_toolbar:
            self._cal_toolbar.setVisible(checked)
            self._cal_draw_toggle.setText("Pan Mode")
        if self._sample_view is not None:
            self._sample_view.set_calibration_mode(checked)
            if checked:
                try:
                    self._sample_view.calibration_changed.disconnect(self._on_cal_data_changed)
                except Exception:
                    pass
                self._sample_view.calibration_changed.connect(self._on_cal_data_changed)
            else:
                self._sample_view.viewport().setCursor(self._corn_cursor)
                try:
                    self._sample_view.calibration_changed.disconnect(self._on_cal_data_changed)
                except Exception:
                    pass
        if checked and self._median_action.isChecked():
            self._median_action.setChecked(False)
            self._hide_median_chart()

    def _on_pca(self) -> None:
        if self._data_loader is None:
            self._status.showMessage("Open a result folder first")
            return
        from pathlib import Path
        txt_path = Path(self._result_dir) / "rep_width_profiles.txt"
        if not txt_path.exists():
            QMessageBox.warning(self, "PCA", "rep_width_profiles.txt not found")
            return
        if not self._analysis_file_is_current(txt_path):
            return
        from grainprofiler.widgets.pca_window import PCAPanel
        # Remove old PCA panel if exists (cleanup mpl callbacks first)
        if hasattr(self, '_pca_panel') and self._pca_panel is not None:
            old = self._pca_panel
            self._stack.removeWidget(old)
            if hasattr(old, '_cleanup'):
                try:
                    old._cleanup()
                except Exception:
                    pass
            old.deleteLater()
            self._pca_panel = None
        panel = PCAPanel(str(txt_path), self._result_dir, self._dark_mode)
        if not panel.is_ok:
            return
        panel.back_clicked.connect(self._on_pca_back)
        self._pca_panel = panel
        self._stack.addWidget(panel)
        self._stack.setCurrentWidget(panel)

    def _on_pca_back(self) -> None:
        self._stack.setCurrentIndex(1)  # back to main splitter

    # ------------------------------------------------------------------
    # VAE Latent Explorer
    # ------------------------------------------------------------------

    def _analysis_file_is_current(self, path: Path) -> bool:
        expected = self._data_loader.analysis_file_digests.get(path.name)
        try:
            unchanged = (not path.exists()) if expected is None else (
                path.stat().st_mtime_ns == self._data_loader.analysis_file_mtimes[path.name]
                and csv_file_sha256(path) == expected
            )
        except OSError:
            unchanged = False
        if not unchanged:
            QMessageBox.warning(self, "Result file changed", f"{path.name} changed after loading. Reopen the result folder before analysis.")
        return unchanged

    def _on_vae_latent(self) -> None:
        if self._data_loader is None:
            self._status.showMessage("Open a result folder first")
            return
        from pathlib import Path
        profile_txt = Path(self._result_dir) / "rep_width_profiles.txt"
        latent_csv = Path(self._result_dir) / "latent_traits.csv"
        if not self._analysis_file_is_current(profile_txt) or not self._analysis_file_is_current(latent_csv):
            return
        if not profile_txt.exists():
            QMessageBox.warning(self, "VAE", "rep_width_profiles.txt not found")
            return
        from grainprofiler.widgets.vae_latent_window import VAELatentWindow
        if hasattr(self, '_vae_panel') and self._vae_panel is not None:
            old = self._vae_panel
            self._stack.removeWidget(old)
            if hasattr(old, '_cleanup'):
                try:
                    old._cleanup()
                except Exception:
                    pass
            old.deleteLater()
            self._vae_panel = None
        panel = VAELatentWindow(
            str(profile_txt), str(latent_csv), self._dark_mode,
            csv_encoding=self._data_loader.csv_encodings.get("latent_traits.csv"),
        )
        if not panel.is_ok:
            return
        panel.back_clicked.connect(self._on_vae_latent_back)
        self._vae_panel = panel
        self._stack.addWidget(panel)
        self._stack.setCurrentWidget(panel)

    def _on_vae_latent_back(self) -> None:
        self._stack.setCurrentIndex(1)  # back to main splitter

    # ------------------------------------------------------------------
    # Trait Distribution
    # ------------------------------------------------------------------

    def _on_trait_analysis(self) -> None:
        if self._data_loader is None:
            self._status.showMessage("Open a result folder first")
            return
        from pathlib import Path
        csv = Path(self._result_dir) / "final_output_plant_median.csv"
        if not self._analysis_file_is_current(csv):
            return
        if not csv.exists():
            QMessageBox.warning(self, "Analysis", "final_output_plant_median.csv not found")
            return
        from grainprofiler.widgets.sample_analysis_window import SampleAnalysisWindow
        if hasattr(self, '_trait_panel') and self._trait_panel is not None:
            old = self._trait_panel
            self._stack.removeWidget(old)
            if hasattr(old, '_cleanup'):
                try:
                    old._cleanup()
                except Exception:
                    pass
            old.deleteLater()
            self._trait_panel = None
        panel = SampleAnalysisWindow(
            str(csv), self._dark_mode,
            csv_encoding=self._data_loader.csv_encodings.get("final_output_plant_median.csv"),
        )
        if not panel.is_ok:
            return
        panel.back_clicked.connect(self._on_trait_back)
        self._trait_panel = panel
        self._stack.addWidget(panel)
        self._stack.setCurrentWidget(panel)

    def _on_trait_back(self) -> None:
        self._stack.setCurrentIndex(1)

    def _auto_load_last(self) -> None:
        path = QSettings("grainprofiler", "grainprofiler").value("last_folder", "")
        if path:
            from pathlib import Path
            if Path(str(path)).exists():
                self._on_folder_opened(str(path))

    def _on_cal_data_changed(self, cal_data: dict) -> None:
        if self._info_panel is not None:
            self._info_panel.update_calibration(cal_data)

    # ------------------------------------------------------------------
    # Recent folders
    # ------------------------------------------------------------------

    def _add_recent_folder(self, path: str) -> None:
        settings = QSettings("grainprofiler", "grainprofiler")
        recent = settings.value("recent_folders", []) or []
        if isinstance(recent, str):
            recent = [recent]
        # Remove duplicate and cap at 5
        recent = [p for p in recent if p != path]
        recent.insert(0, path)
        settings.setValue("recent_folders", recent[:5])

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        settings = QSettings("grainprofiler", "grainprofiler")
        recent = settings.value("recent_folders", []) or []
        if isinstance(recent, str):
            recent = [recent]
        if not recent:
            self._recent_menu.addAction("(empty)").setEnabled(False)
            return
        from PySide6.QtGui import QAction
        for p in recent:
            action = QAction(p, self)
            action.triggered.connect(lambda checked, path=p: self._on_recent_folder(path))
            self._recent_menu.addAction(action)
        self._recent_menu.addSeparator()
        clear_action = QAction("Clear Recent", self)
        clear_action.triggered.connect(self._clear_recent_folders)
        self._recent_menu.addAction(clear_action)

    def _on_recent_folder(self, path: str) -> None:
        from pathlib import Path
        if Path(path).exists():
            self._on_folder_opened(path)
        else:
            QMessageBox.warning(self, "Folder Not Found",
                                f"The folder no longer exists:\n{path}")
            self._add_recent_folder(path)  # will be filtered on next rebuild
            # Force remove dead entry
            settings = QSettings("grainprofiler", "grainprofiler")
            recent = settings.value("recent_folders", []) or []
            if isinstance(recent, str):
                recent = [recent]
            recent = [p for p in recent if p != path]
            settings.setValue("recent_folders", recent)

    def _clear_recent_folders(self) -> None:
        QSettings("grainprofiler", "grainprofiler").setValue("recent_folders", [])

    # ------------------------------------------------------------------
    # Window / splitter state persistence
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._info_panel is not None and self._info_panel.has_pending_metadata_edits():
            answer = QMessageBox.question(
                self, "Unsaved metadata", "Discard unconfirmed metadata changes and exit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._closing = True
        settings = QSettings("grainprofiler", "grainprofiler")
        settings.setValue("window_geometry", self.saveGeometry())
        if self._splitter is not None:
            settings.setValue("main_splitter_sizes", self._splitter.sizes())
        if self._median_splitter is not None:
            settings.setValue("median_splitter_sizes", self._median_splitter.sizes())
        if self._top_splitter is not None:
            settings.setValue("top_splitter_sizes", self._top_splitter.sizes())
        self._settings.sync()
        super().closeEvent(event)

    def _restore_window_state(self) -> None:
        settings = QSettings("grainprofiler", "grainprofiler")
        geo = settings.value("window_geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1400, 800)

    def _restore_splitter_sizes(self) -> None:
        settings = QSettings("grainprofiler", "grainprofiler")
        if self._splitter is not None:
            saved = settings.value("main_splitter_sizes")
            if saved is not None and len(saved) == 3:
                self._splitter.setSizes([int(s) for s in saved])

    def _on_splitter_moved(self, pos: int, index: int) -> None:
        if self._splitter is not None:
            QSettings("grainprofiler", "grainprofiler").setValue(
                "main_splitter_sizes", self._splitter.sizes()
            )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _on_navigate_prev(self) -> None:
        if self._data_loader is None:
            return
        self._nav_panel.navigate(-1)

    def _on_navigate_next(self) -> None:
        if self._data_loader is None:
            return
        self._nav_panel.navigate(1)
