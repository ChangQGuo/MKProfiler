import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "appearance.ini"), QSettings.IniFormat)


def test_appearance_and_font_survive_restart(app, settings, monkeypatch):
    import grainprofiler.app.main_window as main_module

    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    window._build_workspace()
    window._stack.setCurrentWidget(window._splitter)
    window.show()
    app.processEvents()
    before = window._nav_panel._filter_edit.font().pixelSize()

    window._set_appearance("lavender", "Arial", 22)
    app.processEvents()
    assert window._nav_panel._filter_edit.font().pixelSize() > before
    assert window._nav_panel._filter_edit.font().family() == "Arial"
    assert window._info_panel._table.font().pixelSize() > before
    assert settings.value("appearance/theme") == "lavender"
    QTest.qWait(30)
    for key in ("plant_name", "weight_g"):
        editor = window._info_panel._meta_edits[key]
        assert editor.height() >= editor.sizeHint().height()
    window.close()
    window.deleteLater()
    app.processEvents()

    restored = main_module.MainWindow()
    assert restored._theme_name == "lavender"
    assert restored._font_family == "Arial"
    assert restored._font_size == 22
    restored.close()


def test_splitter_shows_resize_cursor_and_can_expand_side_panels(app, settings, monkeypatch):
    import grainprofiler.app.main_window as main_module

    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    window._build_workspace()
    assert QApplication.overrideCursor() is None
    assert window._splitter.handleWidth() >= 8
    assert window._splitter.handle(1).cursor().shape() == Qt.SplitHCursor
    assert window._splitter.handle(1).toolTip()
    assert window._nav_panel.maximumWidth() > 500
    assert window._info_panel.maximumWidth() > 700
    window.close()


def test_navigation_chevrons_only_appear_near_edges_and_remain_clickable(app):
    from grainprofiler.widgets.sample_view import SampleView

    view = SampleView()
    view.resize(400, 200)
    view._photo_pixmap = QPixmap(20, 20)
    view.scene().setSceneRect(0, 0, 20, 20)
    view.show()
    app.processEvents()
    viewport = view.viewport()
    events = []
    view.navigate_prev.connect(lambda: events.append("previous"))
    view.navigate_next.connect(lambda: events.append("next"))
    center_y = viewport.height() // 2

    QTest.mouseMove(viewport, QPoint(viewport.width() // 2, center_y))
    assert view._nav_hover is None
    QTest.mouseMove(viewport, QPoint(20, center_y))
    assert view._nav_hover == "left"
    QTest.mouseClick(viewport, Qt.LeftButton, pos=QPoint(20, center_y))
    assert events == ["previous"]
    QTest.mouseMove(viewport, QPoint(viewport.width() - 20, center_y))
    assert view._nav_hover == "right"
    QTest.mouseClick(viewport, Qt.LeftButton, pos=QPoint(viewport.width() - 20, center_y))
    assert events == ["previous", "next"]
    QApplication.sendEvent(viewport, QEvent(QEvent.Leave))
    assert view._nav_hover is None
    view.close()


def test_common_analysis_actions_have_icons_and_explanatory_tooltips(app, settings, monkeypatch):
    import grainprofiler.app.main_window as main_module

    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    actions = [action for action in window._visual_toolbar.actions() if not action.isSeparator()]
    assert len(actions) >= 5
    assert all(not action.icon().isNull() and action.toolTip() for action in actions)
    window.close()
