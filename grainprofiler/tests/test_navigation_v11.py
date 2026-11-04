import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from grainprofiler.widgets.nav_panel import NavPanel


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)


def test_sample_counter_tracks_current_position(app, settings, tmp_path):
    nav = NavPanel(settings=settings)
    nav.populate(["a.jpg", "b.jpg", "c.jpg"], str(tmp_path))
    assert nav._count_label.text() == "1 / 3 samples"
    nav.select_sample("b.jpg")
    assert nav._count_label.text() == "2 / 3 samples"
    nav.navigate(1)
    assert nav.current_sample() == "c.jpg"
    assert nav._count_label.text() == "3 / 3 samples"


def test_folder_remembers_its_own_last_sample(app, settings, tmp_path):
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    nav = NavPanel(settings=settings)
    nav.populate(["a.jpg", "b.jpg", "c.jpg"], first)
    nav.select_sample("b.jpg")
    nav.populate(["a.jpg", "b.jpg", "c.jpg"], second)
    assert nav.current_sample() == "a.jpg"
    nav.select_sample("c.jpg")
    settings.sync()
    restored = NavPanel(settings=settings)
    restored.populate(["a.jpg", "b.jpg", "c.jpg"], first)
    assert restored.current_sample() == "b.jpg"
    restored.populate(["a.jpg", "b.jpg", "c.jpg"], second)
    assert restored.current_sample() == "c.jpg"
    restored.populate(["a.jpg"], first)
    assert restored.current_sample() == "a.jpg"


def test_search_jumps_to_plant_name_and_continues_browsing(app, settings, tmp_path):
    nav = NavPanel(settings=settings)
    nav.populate(
        ["2025001.jpg", "2025002.jpg", "2025003.jpg"],
        str(tmp_path),
        plant_names={"2025002.jpg": "Zhengdan 958"},
    )
    nav._filter_edit.setText("2025001")
    nav._search_edit.setText("zhengdan 958")
    nav._search_edit.returnPressed.emit()
    assert nav.current_sample() == "2025002.jpg"
    assert nav._filter_edit.text() == ""
    nav.navigate(1)
    assert nav.current_sample() == "2025003.jpg"
    assert nav._count_label.text() == "3 / 3 samples"
    nav._filter_edit.setText("2025002")
    nav._search_edit.setText("2025002.jpg")
    nav._search_edit.returnPressed.emit()
    assert nav._filter_edit.text() == ""
    nav.navigate(1)
    assert nav.current_sample() == "2025003.jpg"


def test_pin_alias_and_copy_preserve_original_image_name(app, settings, tmp_path):
    nav = NavPanel(settings=settings)
    ids = ["2025001.jpg", "2025002.jpg", "2025003.jpg"]
    nav.populate(ids, str(tmp_path))
    nav.set_pinned("2025002.jpg", True)
    nav.set_alias("2025002.jpg", "My sample")
    assert nav._list.item(0).data(Qt.UserRole) == "2025002.jpg"
    assert "My sample" in nav._list.item(0).text()
    menu = nav._sample_menu("2025002.jpg")
    next(action for action in menu.actions() if action.text() == "Copy image name").trigger()
    assert QApplication.clipboard().text() == "2025002.jpg"
    nav.select_sample("2025002.jpg")
    assert nav.current_sample() == "2025002.jpg"
    settings.sync()
    reopened = NavPanel(settings=settings)
    reopened.populate(ids, str(tmp_path))
    assert reopened._list.item(0).data(Qt.UserRole) == "2025002.jpg"
    assert "My sample" in reopened._list.item(0).text()
    assert reopened.current_sample() == "2025002.jpg"


def test_hover_menu_hitbox_opens_actions_for_the_correct_image(app, settings, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    nav = NavPanel(settings=settings)
    nav.populate(["first.jpg", "second.jpg"], str(tmp_path))
    nav.show()
    app.processEvents()
    clicked = []

    class Menu:
        def exec(self, _position):
            clicked.append(True)

    monkeypatch.setattr(nav, "_sample_menu", lambda image_name: (clicked.append(image_name), Menu())[1])
    rect = nav._list.visualItemRect(nav._list.item(1))
    point = QPoint(rect.right() - 10, rect.center().y())
    QTest.mouseClick(nav._list.viewport(), Qt.LeftButton, pos=point)
    assert clicked == ["second.jpg", True]
    assert nav.current_sample() == "first.jpg"


def test_hover_menu_stays_visible_with_long_names(app, settings, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    nav = NavPanel(settings=settings)
    nav.setFixedWidth(300)
    nav.populate(["first.jpg", "very_long_" + "x" * 160 + ".jpg"], str(tmp_path))
    nav.show()
    app.processEvents()
    clicked = []

    class Menu:
        def exec(self, _position):
            clicked.append(True)

    monkeypatch.setattr(nav, "_sample_menu", lambda image_name: (clicked.append(image_name), Menu())[1])
    rect = nav._list.visualItemRect(nav._list.item(0))
    point = QPoint(nav._list.viewport().width() - 10, rect.center().y())
    QTest.mouseClick(nav._list.viewport(), Qt.LeftButton, pos=point)
    assert clicked == ["first.jpg", True]


def test_search_cycles_duplicate_plant_names_without_filtering(app, settings, tmp_path):
    nav = NavPanel(settings=settings)
    nav.populate(["a.jpg", "b.jpg", "c.jpg"], str(tmp_path), {"b.jpg": "Same", "c.jpg": "Same"})
    nav._search_edit.setText("same")
    nav._search_edit.returnPressed.emit()
    assert nav.current_sample() == "b.jpg"
    nav._search_edit.returnPressed.emit()
    assert nav.current_sample() == "c.jpg"
    nav._search_edit.returnPressed.emit()
    assert nav.current_sample() == "b.jpg"


def test_search_cycles_exact_then_partial_matches(app, settings, tmp_path):
    nav = NavPanel(settings=settings)
    nav.populate(["a.jpg", "abc.jpg", "abacus.jpg"], str(tmp_path))
    nav._search_edit.setText("a")
    for expected in ("a.jpg", "abc.jpg", "abacus.jpg", "a.jpg"):
        nav._search_edit.returnPressed.emit()
        assert nav.current_sample() == expected


def test_plant_name_change_refreshes_active_filter(app, settings, tmp_path):
    from PySide6.QtTest import QTest
    nav = NavPanel(settings=settings)
    nav.populate(["a.jpg", "b.jpg"], str(tmp_path), {"a.jpg": "OldPlant"})
    nav._filter_edit.setText("OldPlant")
    QTest.qWait(200)
    assert nav._list.count() == 1
    nav.update_plant_name("a.jpg", "NewPlant")
    QTest.qWait(200)
    assert nav._list.count() == 0


def test_loader_preserves_original_image_extension_for_search_and_copy(app, settings, tmp_path):
    import json
    from grainprofiler.app.data_loader import DataLoader
    from grainprofiler.widgets.sample_info_panel import SampleInfoPanel
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\n玉米_A_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\n玉米_A.JPG,中文品种,1\n", encoding="utf-8")
    contours = tmp_path / "contours"
    contours.mkdir()
    (contours / "玉米_A.JPG_contours.json").write_text(
        json.dumps({"玉米_A_kernel_001.jpg": [[0, 0], [1, 0], [1, 1]]}, ensure_ascii=False), encoding="utf-8",
    )
    (tmp_path / "yolo_bounding_boxes.json").write_text(
        json.dumps({"玉米_A.jpg": {"accepted_detections": [{"kernel_id": 1, "box": [2, 3, 12, 13]}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_sample_ids() == ["玉米_A.JPG"]
    assert loader.get_kernels_for_sample("玉米_A.JPG") == ["玉米_A_kernel_001.jpg"]
    assert loader.get_kernel_contour("玉米_A_kernel_001.jpg") is not None
    assert loader.get_bbox_image_name("玉米_A.JPG") == "玉米_A.jpg"
    assert loader.get_kernel_box("玉米_A_kernel_001.jpg") == (2, 3, 12, 13)
    panel = SampleInfoPanel()
    panel.load_sample("玉米_A.JPG", loader)
    panel.update_calibration({"玉米_A_kernel_001.jpg": 12.5})
    assert panel._pandas_model._df.loc[0, "cal_px"] == 12.5
    selected = []
    panel.kernel_row_selected.connect(selected.append)
    panel._on_row_clicked(panel._proxy.index(0, 0))
    assert selected == ["玉米_A_kernel_001.jpg"]
    nav = NavPanel(settings=settings)
    nav.populate(loader.get_sample_ids(), str(tmp_path), {"玉米_A.JPG": "中文品种"})
    nav._search_edit.setText("中文品种")
    nav._search_edit.returnPressed.emit()
    assert nav.current_sample() == "玉米_A.JPG"
    menu = nav._sample_menu(nav.current_sample())
    next(action for action in menu.actions() if action.text() == "Copy image name").trigger()
    assert QApplication.clipboard().text() == "玉米_A.JPG"


def test_loader_deduplicates_metadata_only_image_names(tmp_path):
    from grainprofiler.app.data_loader import DataLoader
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text(
        "image_name,plant_name,weight_g\nsame.jpg,First,1\nsame.jpg,Second,2\nother.jpg,Third,3\n",
        encoding="utf-8",
    )
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_sample_ids() == ["same.jpg", "other.jpg"]
    assert loader.image_to_plant["same.jpg"] == "First"


def test_contour_stem_with_dot_and_no_image_extension(tmp_path):
    import json
    from grainprofiler.app.data_loader import DataLoader
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\nv1.sample_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\nv1.sample.JPG,One,1\n", encoding="utf-8")
    contours = tmp_path / "contours"
    contours.mkdir()
    (contours / "v1.sample_contours.json").write_text(
        json.dumps({"v1.sample_kernel_001.jpg": [[0, 0], [1, 0], [1, 1]]}), encoding="utf-8",
    )
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_kernel_contour("v1.sample_kernel_001.jpg") is not None


def test_loader_refuses_ambiguous_image_stems_in_measurements(tmp_path):
    from grainprofiler.app.data_loader import DataLoader
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\nsample_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text(
        "image_name,plant_name,weight_g\nsample.jpg,A,1\nsample.png,B,2\n", encoding="utf-8",
    )
    result = DataLoader().load(str(tmp_path))
    assert not result.ok
    assert "ambiguous" in result.errors[0].lower()


def test_loader_does_not_guess_between_ambiguous_bbox_names(tmp_path):
    import json
    from grainprofiler.app.data_loader import DataLoader
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\nsample_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\nsample.JPG,A,1\n", encoding="utf-8")
    payload = {
        "sample.jpg": {"accepted_detections": [{"kernel_id": 1, "box": [1, 1, 5, 5]}]},
        "sample.JpG": {"accepted_detections": [{"kernel_id": 1, "box": [2, 2, 6, 6]}]},
    }
    (tmp_path / "yolo_bounding_boxes.json").write_text(json.dumps(payload), encoding="utf-8")
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_kernel_box("sample_kernel_001.jpg") is None


def test_kernel_delete_updates_original_bbox_key_when_extension_case_differs(app, settings, tmp_path, monkeypatch):
    import json
    import grainprofiler.app.main_window as main_module
    from grainprofiler.app.data_loader import DataLoader
    from PySide6.QtWidgets import QMessageBox
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\nsample_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\nsample.JPG,A,1\n", encoding="utf-8")
    bbox = tmp_path / "yolo_bounding_boxes.json"
    bbox.write_text(json.dumps({"sample.jpg": {"accepted_detections": [{"kernel_id": 1, "box": [1, 1, 5, 5]}]}}), encoding="utf-8")
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window = main_module.MainWindow()
    window._data_loader = loader
    window._delete_kernel("sample_kernel_001.jpg", "1")
    assert json.loads(bbox.read_text(encoding="utf-8"))["sample.jpg"]["accepted_detections"] == []
    window.close()


def test_arrow_keys_and_custom_keys_navigate_without_stealing_text_input(app, settings, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    import grainprofiler.app.main_window as main_module

    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "measurements.csv").write_text(
        "kernel_name,length_px\na_kernel_001.jpg,10\nb_kernel_001.jpg,10\nc_kernel_001.jpg,10\n",
        encoding="utf-8",
    )
    (result_dir / "metadata.csv").write_text(
        "image_name,plant_name,weight_g\na.jpg,A,1\nb.jpg,B,2\nc.jpg,C,3\n",
        encoding="utf-8",
    )
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        image = QImage(80, 60, QImage.Format_RGB888)
        image.fill(0xFFFFFF)
        assert image.save(str(result_dir / name))

    window = main_module.MainWindow()
    window.show()
    window._on_folder_opened(str(result_dir))
    app.processEvents()
    view = window._sample_view.viewport()
    window.activateWindow()
    window._sample_view.setFocus()
    app.processEvents()
    QTest.keyClick(view, Qt.Key_Right)
    assert window._current_image_name == "b.jpg"
    window._nav_panel._search_edit.setFocus()
    QTest.keyClick(window._nav_panel._search_edit, Qt.Key_Left)
    assert window._current_image_name == "b.jpg"
    window._info_panel._lock_btn.click()
    window._info_panel._meta_edits["plant_name"].setText("B_corrected")
    window._info_panel._save_btns["plant_name"].click()
    window._sample_view.setFocus()
    QTest.keyClick(view, Qt.Key_Left)
    assert window._current_image_name == "a.jpg"
    window._nav_panel._search_edit.setText("B_corrected")
    window._nav_panel._search_edit.setFocus()
    QTest.keyClick(window._nav_panel._search_edit, Qt.Key_Return)
    assert window._current_image_name == "b.jpg"
    assert app.focusWidget() is window._nav_panel._list
    QTest.keyClick(window._nav_panel._list, Qt.Key_Right)
    assert window._current_image_name == "c.jpg"
    QTest.keyClick(window._nav_panel._list, Qt.Key_Left)
    assert window._current_image_name == "b.jpg"

    window._set_navigation_shortcuts("F7", "F8")
    window._nav_panel._search_edit.setFocus()
    QTest.keyClick(window._nav_panel._search_edit, Qt.Key_F8)
    assert window._current_image_name == "b.jpg"
    window._info_panel._meta_edits["plant_name"].setFocus()
    QTest.keyClick(window._info_panel._meta_edits["plant_name"], Qt.Key_F8)
    assert window._current_image_name == "b.jpg"
    window._set_navigation_shortcuts("Space", "F8")
    lock = window._info_panel._lock_btn
    was_locked = lock.isChecked()
    lock.setFocus()
    QTest.keyClick(lock, Qt.Key_Space)
    assert lock.isChecked() != was_locked
    assert window._current_image_name == "b.jpg"
    window._set_navigation_shortcuts("Left", "Right")
    window._info_panel._table.setFocus()
    QTest.keyClick(window._info_panel._table, Qt.Key_Right)
    assert window._current_image_name == "b.jpg"
    window._set_navigation_shortcuts("A", "D")
    window._sample_view.setFocus()
    QTest.keyClick(view, Qt.Key_D)
    assert window._current_image_name == "c.jpg"
    QTest.keyClick(view, Qt.Key_A)
    assert window._current_image_name == "b.jpg"
    with pytest.raises(ValueError):
        window._set_navigation_shortcuts("A", "A")
    with pytest.raises(ValueError):
        window._set_navigation_shortcuts("Ctrl+O", "D")
    settings.sync()
    window.close()
    window.deleteLater()
    app.processEvents()
    reopened = main_module.MainWindow()
    reopened.show()
    QTest.qWait(250)
    assert reopened._current_image_name == "b.jpg"
    assert reopened._previous_key.toString() == "A"
    assert reopened._next_key.toString() == "D"
    reopened.close()


def test_shortcut_settings_dialog_saves_keys(app, settings, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QDialogButtonBox, QKeySequenceEdit
    import grainprofiler.app.main_window as main_module

    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    errors = []

    def edit_dialog():
        dialog = QApplication.activeModalWidget()
        try:
            editors = dialog.findChildren(QKeySequenceEdit)
            assert len(editors) == 2
            editors[0].setKeySequence(QKeySequence("F7"))
            editors[1].setKeySequence(QKeySequence("F8"))
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
        except Exception as error:
            errors.append(error)
            dialog.reject()

    QTimer.singleShot(0, edit_dialog)
    window._show_shortcut_settings()
    assert not errors
    assert settings.value("shortcuts/previous") == "F7"
    assert settings.value("shortcuts/next") == "F8"
    window.close()
