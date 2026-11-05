"""Application entry point."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from grainprofiler import __version__
from grainprofiler.app.main_window import MainWindow

_ICON_PNG = (
    Path(__file__).resolve().parent.parent
    / "grainprofiler_minifig" / "图标.png"
)


def _signal_update_ready() -> None:
    """Acknowledge an update only after the packaged window has opened."""
    value = os.environ.pop("MKPROFILER_UPDATE_READY", "")
    if not value or not getattr(sys, "frozen", False):
        return
    marker = Path(value)
    if (not marker.is_absolute() or marker.parent != Path(sys.executable).absolute().parent
            or not re.fullmatch(r"\.MKProfiler-update-[0-9a-f]{32}\.ready", marker.name)):
        return
    try:
        with marker.open("x", encoding="ascii") as output:
            output.write("ready")
    except OSError:
        pass


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("MKProfiler")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("MKProfiler")

    # Splash screen
    splash_pix = QPixmap(str(_ICON_PNG))
    if not splash_pix.isNull():
        splash_pix = splash_pix.scaled(
            400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        splash = QSplashScreen(splash_pix)
        splash.show()
        app.processEvents()
        QTimer.singleShot(1500, splash.close)

    window = MainWindow()
    window.show()
    QTimer.singleShot(0, _signal_update_ready)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
