import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from grainprofiler.app.data_loader import DataLoader
from grainprofiler.widgets.sample_analysis_window import SampleAnalysisWindow
from grainprofiler.widgets.sample_info_panel import SampleInfoPanel


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def suppress_modal_errors(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)


@pytest.mark.parametrize("encoding", ["gb18030", "utf-8-sig", "utf-16", "utf-16-be"])
def test_spreadsheet_csv_loads_and_metadata_edits_keep_encoding(app, tmp_path, encoding):
    (tmp_path / "measurements.csv").write_text(
        "kernel_name,length_px\n玉米_A_kernel_001.jpg,10\n", encoding=encoding,
    )
    metadata = tmp_path / "metadata.csv"
    text = "image_name,plant_name,weight_g,sample_code\r\n玉米_A.jpg,品种一,2.50,0007\r\n"
    if encoding == "utf-16-be":
        metadata.write_bytes(b"\xfe\xff" + text.encode(encoding))
        (tmp_path / "measurements.csv").write_bytes(
            b"\xfe\xff" + "kernel_name,length_px\n玉米_A_kernel_001.jpg,10\n".encode(encoding)
        )
    else:
        metadata.write_bytes(text.encode(encoding))

    loader = DataLoader()
    result = loader.load(str(tmp_path))
    assert result.ok
    assert result.image_names == ["玉米_A.jpg"]
    panel = SampleInfoPanel()
    panel.load_sample("玉米_A.jpg", loader)
    assert panel._meta_edits["plant_name"].text() == "品种一"
    assert panel._meta_edits["weight_g"].text() == "2.50"
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("3.75")
    panel._save_btns["weight_g"].click()

    raw = metadata.read_bytes()
    if encoding == "utf-16-be":
        assert raw.startswith(b"\xfe\xff")
        decoded = raw.decode("utf-16")
    else:
        if encoding == "utf-8-sig":
            assert raw.startswith(b"\xef\xbb\xbf")
        decoded = raw.decode(encoding)
    assert "\r\n" in decoded
    rows = list(csv.DictReader(decoded.splitlines()))
    assert rows == [{"image_name": "玉米_A.jpg", "plant_name": "品种一", "weight_g": "3.75", "sample_code": "0007"}]
    assert loader.get_image_metadata("玉米_A.jpg")["weight_g"] == "3.75"


def test_spreadsheet_encoded_plant_medians_work_in_analysis(app, tmp_path):
    path = tmp_path / "final_output_plant_median.csv"
    path.write_bytes(
        "plant_name,weight_g,n_kernels,median_length_mm\n品种一,4.0,2,10\n".encode("gb18030")
    )
    window = SampleAnalysisWindow(str(path))
    assert window.is_ok
    assert window._df.loc[0, "plant_name"] == "品种一"
    assert window._df.loc[0, "weight_per_kernel_g"] == 2.0


def test_invalid_latent_row_does_not_hide_later_samples_or_imply_zero_is_original(app, tmp_path):
    from grainprofiler.widgets.vae_latent_window import VAELatentWindow

    profiles = tmp_path / "rep_width_profiles.txt"
    profiles.write_text("\n".join(name + " " + " ".join(["1"] * 100) for name in ("A", "B", "C")), encoding="utf-8")
    latents = tmp_path / "latent_traits.csv"
    latents.write_text(
        "plant_id,latent_1,latent_2,latent_3,latent_4,latent_5\n"
        "A,1,2,3,0,0\nB,broken,2,3,0,0\nC,1,2,3,0,0\n", encoding="utf-8",
    )
    window = VAELatentWindow(str(profiles), str(latents))
    assert window.is_ok
    assert window._latents["C"] == [1.0, 2.0, 3.0, 0.0, 0.0]
    window._on_plant_selected("B")
    assert "unavailable" in window._latent_notice.text().lower()
    assert "no saved latent" in window._ax.get_legend_handles_labels()[1][-1].lower()
    window.close()


def test_newer_edited_csv_takes_precedence_over_stale_parquet(tmp_path, monkeypatch):
    csv_path = tmp_path / "measurements.csv"
    parquet_path = tmp_path / "measurements.parquet"
    csv_path.write_text("kernel_name,length_px\na_kernel_001.jpg,99\n", encoding="utf-8")
    parquet_path.write_bytes(b"stand-in for a readable parquet file")
    os.utime(parquet_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(csv_path, ns=(2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(pd, "read_parquet", lambda path: pd.DataFrame({
        "kernel_name": ["a_kernel_001.jpg"], "length_px": [10],
    }))

    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_kernel_measurement("a_kernel_001.jpg")["length_px"] == 99

    os.utime(parquet_path, ns=(3_000_000_000, 3_000_000_000))
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_kernel_measurement("a_kernel_001.jpg")["length_px"] == 10


def test_legacy_round_kernels_are_included_in_sample_table(app, tmp_path):
    (tmp_path / "measurements.csv").write_text(
        "kernel_name,length_px\na_kernel_001.jpg,10\na_kernel_002_round.jpg,8\n", encoding="utf-8",
    )
    (tmp_path / "metadata.csv").write_text(
        "image_name,plant_name,weight_g\na.jpg,A,1\n", encoding="utf-8",
    )
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    panel = SampleInfoPanel()
    panel.load_sample("a.jpg", loader)
    assert panel._meta_edits["kernel_count"].text() == "2"
    assert loader.get_kernels_for_sample("a.jpg") == ["a_kernel_001.jpg", "a_kernel_002_round.jpg"]
    assert panel._pandas_model._df["kernel_name"].tolist() == ["001", "002_round"]


def test_legacy_round_kernel_uses_unambiguous_original_detail_files(app, tmp_path):
    import json
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QGraphicsPixmapItem
    from grainprofiler.widgets.kernel_detail_dialog import KernelDetailDialog

    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_002_round.jpg,8\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\na.jpg,A,1\n", encoding="utf-8")
    (tmp_path / "axis_results.json").write_text(json.dumps([
        {"kernel_name": "a_kernel_002.jpg", "bottom": [1, 1], "top": [3, 3]}
    ]), encoding="utf-8")
    contours = tmp_path / "contours"
    contours.mkdir()
    (contours / "a.jpg_contours.json").write_text(
        json.dumps({"a_kernel_002.jpg": [[0, 0], [4, 0], [4, 4]]}), encoding="utf-8",
    )
    images = tmp_path / "subimages"
    images.mkdir()
    image = QImage(10, 10, QImage.Format_RGB888)
    image.fill(0xFFFFFF)
    assert image.save(str(images / "a_kernel_002.jpg"))
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_kernel_axis("a_kernel_002_round.jpg") is not None
    assert loader.get_kernel_contour("a_kernel_002_round.jpg") is not None
    detail = KernelDetailDialog("a_kernel_002_round.jpg", loader, str(tmp_path))
    assert any(isinstance(item, QGraphicsPixmapItem) for item in detail._scene.items())


def test_round_kernel_does_not_borrow_files_from_a_distinct_matching_kernel(tmp_path):
    import json

    (tmp_path / "measurements.csv").write_text(
        "kernel_name,length_px\na_kernel_002.jpg,9\na_kernel_002_round.jpg,8\n", encoding="utf-8",
    )
    (tmp_path / "axis_results.json").write_text(json.dumps([
        {"kernel_name": "a_kernel_002.jpg", "bottom": [1, 1], "top": [3, 3]}
    ]), encoding="utf-8")
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_kernel_axis("a_kernel_002_round.jpg") is None


def test_ambiguous_metadata_encoding_requires_choice_before_editing(tmp_path):
    from grainprofiler.app.metadata_edit import save_metadata_edit

    path = tmp_path / "metadata.csv"
    path.write_bytes("image_name,plant_name,weight_g,note\na.jpg,枚,1,枚\n".encode("gb18030"))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="encoding"):
        save_metadata_edit(str(tmp_path), "a.jpg", "plant_name", "玉米", "枚")
    assert path.read_bytes() == before
    save_metadata_edit(str(tmp_path), "a.jpg", "plant_name", "玉米", "枚", metadata_encoding="gb18030")
    with path.open(encoding="gb18030", newline="") as stream:
        assert list(csv.DictReader(stream)) == [
            {"image_name": "a.jpg", "plant_name": "玉米", "weight_g": "1", "note": "枚"}
        ]


def test_explicit_encoding_loads_ambiguous_metadata(tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_bytes("image_name,plant_name,weight_g\na.jpg,枚,1\n".encode("gb18030"))
    loader = DataLoader()
    assert loader.load(str(tmp_path), metadata_encoding="gb18030").ok
    assert loader.get_image_metadata("a.jpg")["plant_name"] == "枚"


def test_wrong_explicit_encoding_reports_error_instead_of_missing_metadata(tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_bytes("image_name,plant_name,weight_g\na.jpg,玉米,1\n".encode("gb18030"))
    result = DataLoader().load(str(tmp_path), metadata_encoding="utf-8")
    assert not result.ok
    assert any("metadata.csv" in error and "encoding" in error.lower() for error in result.errors)


def test_ambiguous_measurement_encoding_requires_choice_for_correct_image_association(tmp_path):
    (tmp_path / "measurements.csv").write_bytes("kernel_name,length_px\n枚_kernel_001.jpg,10\n".encode("gb18030"))
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\n枚.jpg,A,1\n", encoding="utf-8-sig")
    result = DataLoader().load(str(tmp_path))
    assert not result.ok
    assert "measurements.csv" in result.ambiguous_csvs
    loader = DataLoader()
    assert loader.load(str(tmp_path), csv_encodings={"measurements.csv": "gb18030"}).ok
    assert loader.get_sample_ids() == ["枚.jpg"]
    assert loader.get_kernels_for_sample("枚.jpg") == ["枚_kernel_001.jpg"]


def test_ambiguous_derived_tables_use_their_individual_selected_encodings(app, tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\na.jpg,枚,1\n", encoding="utf-8-sig")
    (tmp_path / "final_output_individual.csv").write_bytes(
        "kernel_name,plant_name\na_kernel_001.jpg,枚\n".encode("gb18030")
    )
    median = tmp_path / "final_output_plant_median.csv"
    median.write_bytes("plant_name,weight_g,n_kernels,median_length_mm\n枚,4,2,10\n".encode("gb18030"))
    result = DataLoader().load(str(tmp_path))
    assert set(result.ambiguous_csvs) == {"final_output_individual.csv", "final_output_plant_median.csv"}
    encodings = {name: "gb18030" for name in result.ambiguous_csvs}
    loader = DataLoader()
    assert loader.load(str(tmp_path), csv_encodings=encodings).ok
    assert loader.image_to_plant["a.jpg"] == "枚"
    assert loader.get_plant_median("枚")["median_length_mm"] == 10
    window = SampleAnalysisWindow(str(median), csv_encoding=encodings[median.name])
    assert window.is_ok
    assert window._df.loc[0, "plant_name"] == "枚"
    window.close()


def test_changed_metadata_is_not_saved_using_an_outdated_encoding_choice(app, tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    metadata = tmp_path / "metadata.csv"
    metadata.write_bytes("image_name,plant_name,weight_g,note\na.jpg,枚,1,枚\n".encode("gb18030"))
    loader = DataLoader()
    assert loader.load(str(tmp_path), metadata_encoding="gb18030").ok
    panel = SampleInfoPanel()
    panel.load_sample("a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("2")
    changed = "image_name,plant_name,weight_g,note\na.jpg,枚,1,外部变更\n".encode("gb18030")
    metadata.write_bytes(changed)
    panel._save_btns["weight_g"].click()
    assert metadata.read_bytes() == changed
    assert panel.has_pending_metadata_edits()


def test_automatically_detected_encoding_is_retained_when_a_save_becomes_ambiguous(app, tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    metadata = tmp_path / "metadata.csv"
    metadata.write_bytes("image_name,plant_name,weight_g\na.jpg,玉米,1\n".encode("gb18030"))
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    panel = SampleInfoPanel()
    panel.load_sample("a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("枚")
    panel._save_btns["plant_name"].click()
    assert loader.get_image_metadata("a.jpg")["plant_name"] == "枚"
    assert "枚" in metadata.read_bytes().decode("gb18030")


def test_gui_uses_chosen_encoding_for_ambiguous_metadata(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_bytes("image_name,plant_name,weight_g\na.jpg,枚,1\n".encode("gb18030"))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    choices = []
    monkeypatch.setattr(window, "_choose_csv_encoding", lambda filename, examples: choices.append((filename, examples)) or "gb18030", raising=False)
    window._on_folder_opened(str(tmp_path))
    assert len(choices) == 1
    assert window._info_panel._meta_edits["plant_name"].text() == "枚"
    assert window._data_loader.metadata_encoding == "gb18030"
    window._on_folder_opened(str(tmp_path))
    assert len(choices) == 1
    metadata = tmp_path / "metadata.csv"
    timestamp = metadata.stat().st_mtime_ns
    os.utime(metadata, ns=(timestamp + 1_000_000_000, timestamp + 1_000_000_000))
    window._on_folder_opened(str(tmp_path))
    assert len(choices) == 2
    window.close()


def test_gui_chooses_ambiguous_measurement_encoding_independently(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    (tmp_path / "measurements.csv").write_bytes("kernel_name,length_px\n枚_kernel_001.jpg,10\n".encode("gb18030"))
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\n枚.jpg,A,1\n", encoding="utf-8-sig")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    requested = []
    monkeypatch.setattr(window, "_choose_csv_encoding", lambda filename, previews: requested.append(filename) or "gb18030")
    window._on_folder_opened(str(tmp_path))
    assert requested == ["measurements.csv"]
    assert window._data_loader.get_sample_ids() == ["枚.jpg"]
    window.close()


def test_derived_identity_uses_original_individual_table_after_external_rename(tmp_path):
    (tmp_path / "measurements.csv").write_text(
        "kernel_name,length_px\na_kernel_001.jpg,10\nb_kernel_001.jpg,11\n", encoding="utf-8",
    )
    (tmp_path / "metadata.csv").write_text(
        "image_name,plant_name,weight_g\na.jpg,Beta,1\nb.jpg,Beta,2\n", encoding="utf-8",
    )
    (tmp_path / "final_output_individual.csv").write_text(
        "kernel_name,plant_name\na_kernel_001.jpg,Alpha\nb_kernel_001.jpg,Beta\n", encoding="utf-8",
    )
    (tmp_path / "final_output_plant_median.csv").write_text(
        "plant_name,median_length_mm\nAlpha,10\nBeta,20\n", encoding="utf-8",
    )
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    assert loader.get_image_metadata("a.jpg")["plant_name"] == "Beta"
    assert loader.image_to_plant["a.jpg"] == "Alpha"
    assert loader.get_plant_median(loader.image_to_plant["a.jpg"])["median_length_mm"] == 10
    assert loader.image_to_plant["b.jpg"] == "Beta"


def test_conflicting_original_individual_ids_do_not_guess_derived_identity(tmp_path):
    (tmp_path / "measurements.csv").write_text(
        "kernel_name,length_px\na_kernel_001.jpg,10\na_kernel_002.jpg,11\n", encoding="utf-8",
    )
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\na.jpg,Beta,1\n", encoding="utf-8")
    (tmp_path / "final_output_individual.csv").write_text(
        "kernel_name,plant_name\na_kernel_001.jpg,Alpha\na_kernel_002.jpg,Beta\n", encoding="utf-8",
    )
    loader = DataLoader()
    result = loader.load(str(tmp_path))
    assert result.ok
    assert loader.image_to_plant["a.jpg"] == ""
    assert any("conflict" in warning.lower() for warning in result.warnings)


def test_derived_identity_requires_evidence_or_explicit_trust(tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\na.jpg,Beta,1\n", encoding="utf-8")
    (tmp_path / "final_output_plant_median.csv").write_text("plant_name,median_length_mm\nBeta,20\n", encoding="utf-8")
    loader = DataLoader()
    result = loader.load(str(tmp_path))
    assert result.ok
    assert loader.image_to_plant["a.jpg"] == ""
    assert any("unverified" in warning.lower() for warning in result.warnings)
    trusted = DataLoader()
    assert trusted.load(str(tmp_path), trust_unverified_plant_ids=True).ok
    assert trusted.image_to_plant["a.jpg"] == "Beta"


def test_gui_rename_does_not_convert_unverified_identity_to_verified(app, tmp_path):
    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\na.jpg,Beta,1\n", encoding="utf-8")
    (tmp_path / "final_output_plant_median.csv").write_text("plant_name,median_length_mm\nBeta,20\n", encoding="utf-8")
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    panel = SampleInfoPanel()
    panel.load_sample("a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("Gamma")
    panel._save_btns["plant_name"].click()
    assert loader.image_to_plant["a.jpg"] == ""
    reopened = DataLoader()
    assert reopened.load(str(tmp_path)).ok
    assert reopened.image_to_plant["a.jpg"] == ""


def test_user_can_explicitly_trust_unverified_ids_for_one_open_folder(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    (tmp_path / "metadata.csv").write_text("image_name,plant_name,weight_g\na.jpg,Beta,1\n", encoding="utf-8")
    (tmp_path / "final_output_plant_median.csv").write_text("plant_name,median_length_mm\nBeta,20\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    window = main_module.MainWindow()
    window._on_folder_opened(str(tmp_path))
    assert window._data_loader.image_to_plant["a.jpg"] == ""
    assert "unverified" in window._info_panel._meta_notice.text().lower()
    assert window._trust_plant_ids_action.isEnabled()
    window._trust_plant_ids_action.trigger()
    assert window._data_loader.image_to_plant["a.jpg"] == "Beta"
    window._trust_plant_ids_action.trigger()
    assert window._data_loader.image_to_plant["a.jpg"] == ""
    window.close()


def test_missing_kernel_column_is_reported_instead_of_silent_empty_result(tmp_path):
    (tmp_path / "measurements.csv").write_text("wrong_column,length_px\na,10\n", encoding="utf-8")
    result = DataLoader().load(str(tmp_path))
    assert not result.ok
    assert "kernel_name" in result.errors[0]


def test_deleting_kernel_preserves_spreadsheet_csv_encoding(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    path = tmp_path / "measurements.csv"
    path.write_bytes("kernel_name,length_px\na_kernel_001.jpg,10\na_kernel_002.jpg,11\n".encode("utf-16"))
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window = main_module.MainWindow()
    window._data_loader = loader
    window._delete_kernel("a_kernel_001.jpg", "001")
    assert path.read_bytes().startswith(b"\xff\xfe")
    with path.open(encoding="utf-16", newline="") as stream:
        assert list(csv.DictReader(stream)) == [{"kernel_name": "a_kernel_002.jpg", "length_px": "11"}]
    window.close()


def test_deleting_kernel_preserves_selected_ambiguous_measurement_encoding(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    path = tmp_path / "measurements.csv"
    path.write_bytes("kernel_name,note\na_kernel_001.jpg,枚\na_kernel_002.jpg,枚\n".encode("gb18030"))
    loader = DataLoader()
    assert loader.load(str(tmp_path), csv_encodings={"measurements.csv": "gb18030"}).ok
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window = main_module.MainWindow()
    window._data_loader = loader
    window._delete_kernel("a_kernel_001.jpg", "001")
    with path.open(encoding="gb18030", newline="") as stream:
        assert list(csv.DictReader(stream)) == [{"kernel_name": "a_kernel_002.jpg", "note": "枚"}]
    assert loader.get_kernels_for_sample("a.jpg") == ["a_kernel_002.jpg"]
    window.close()


def test_deleting_does_not_overwrite_newer_parquet_from_older_csv(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    csv_path = tmp_path / "measurements.csv"
    parquet_path = tmp_path / "measurements.parquet"
    csv_path.write_text("kernel_name,length_px\na_kernel_001.jpg,10\na_kernel_002.jpg,11\n", encoding="utf-8")
    parquet_path.write_bytes(b"parquet-sentinel")
    os.utime(csv_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(parquet_path, ns=(2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(pd, "read_parquet", lambda path: pd.DataFrame({
        "kernel_name": ["a_kernel_001.jpg", "a_kernel_002.jpg", "a_kernel_003.jpg"],
        "length_px": [10, 12, 13],
    }))
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    original_csv, original_parquet = csv_path.read_bytes(), parquet_path.read_bytes()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window = main_module.MainWindow()
    window._data_loader = loader
    window._delete_kernel("a_kernel_001.jpg", "001")
    assert csv_path.read_bytes() == original_csv
    assert parquet_path.read_bytes() == original_parquet
    assert len(loader.get_kernels_for_sample("a.jpg")) == 3
    window.close()


def test_deleting_rejects_measurements_replaced_after_the_folder_was_opened(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    path = tmp_path / "measurements.csv"
    path.write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    changed = b"kernel_name,length_px\na_kernel_001.jpg,99\na_kernel_002.jpg,22\n"
    path.write_bytes(changed)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    window = main_module.MainWindow()
    window._data_loader = loader
    window._delete_kernel("a_kernel_001.jpg", "001")
    assert path.read_bytes() == changed
    assert loader.get_kernels_for_sample("a.jpg") == ["a_kernel_001.jpg"]
    window.close()


def test_changed_analysis_csv_must_be_reopened_before_reading(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    median = tmp_path / "final_output_plant_median.csv"
    median.write_bytes("plant_name,median_length_mm\n枚,10\n".encode("gb18030"))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    window = main_module.MainWindow()
    monkeypatch.setattr(window, "_choose_csv_encoding", lambda filename, previews: "gb18030")
    window._on_folder_opened(str(tmp_path))
    assert window._data_loader is not None
    median.write_bytes("plant_name,median_length_mm\nö,10\n".encode("utf-8"))
    window._on_trait_analysis()
    assert messages and "reopen" in messages[-1].lower()
    assert window._trait_panel is None
    window.close()


def test_changed_shape_profile_must_be_reopened_before_vae_analysis(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import grainprofiler.app.main_window as main_module

    (tmp_path / "measurements.csv").write_text("kernel_name,length_px\na_kernel_001.jpg,10\n", encoding="utf-8")
    profiles = tmp_path / "rep_width_profiles.txt"
    profiles.write_text("A " + " ".join(["1"] * 100) + "\n", encoding="utf-8")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    window = main_module.MainWindow()
    window._on_folder_opened(str(tmp_path))
    profiles.write_text("A " + " ".join(["2"] * 100) + "\n", encoding="utf-8")
    window._on_vae_latent()
    assert messages and "reopen" in messages[-1].lower()
    assert window._vae_panel is None
    window.close()
