import csv
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from grainprofiler.app.data_loader import DataLoader
from grainprofiler.widgets.sample_info_panel import SampleInfoPanel


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def suppress_modal_warnings(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)


@pytest.fixture
def results(tmp_path):
    def write(name, columns, rows):
        with (tmp_path / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    write("measurements.csv", ["kernel_name", "length_px"], [
        {"kernel_name": "image_a_kernel_001.jpg", "length_px": "100"},
        {"kernel_name": "image_b_kernel_001.jpg", "length_px": "120"},
    ])
    write("metadata.csv", ["image_name", "plant_name", "weight_g", "sample_code"], [
        {"image_name": "image_a.jpg", "plant_name": "001", "weight_g": "1.25", "sample_code": "0007"},
        {"image_name": "image_b.jpg", "plant_name": "002", "weight_g": "2.50", "sample_code": "0008"},
    ])
    write("latent_traits.csv", ["plant_id", "latent_1"], [
        {"plant_id": "001", "latent_1": "0.123456789"},
        {"plant_id": "002", "latent_1": "0.000000123"},
    ])
    write("final_output_plant_median.csv", ["plant_name", "median_length_mm"], [
        {"plant_name": "001", "median_length_mm": "10"},
        {"plant_name": "002", "median_length_mm": "20"},
    ])
    loader = DataLoader()
    assert loader.load(str(tmp_path)).ok
    return tmp_path, loader


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_weight_is_saved_only_after_click_and_cache_is_updated(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("3.75")
    panel._meta_edits["weight_g"].editingFinished.emit()
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "1.25"
    assert not panel._save_btns["weight_g"].isHidden()
    panel._save_btns["weight_g"].click()
    rows = read_rows(root / "metadata.csv")
    assert rows[0] == {"image_name": "image_a.jpg", "plant_name": "001", "weight_g": "3.75", "sample_code": "0007"}
    assert rows[1]["sample_code"] == "0008"
    assert float(loader.get_image_metadata("image_a.jpg")["weight_g"]) == 3.75
    assert panel._save_btns["weight_g"].isHidden()


def test_missing_weight_marker_can_be_confirmed_reloaded_and_corrected(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("-")
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "1.25"
    assert not panel._save_btns["weight_g"].isHidden()
    panel._save_btns["weight_g"].click()
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "-"
    assert read_rows(root / "metadata.csv")[1]["weight_g"] == "2.50"
    panel.load_sample("image_b.jpg", loader)
    panel.load_sample("image_a.jpg", loader)
    assert panel._meta_edits["weight_g"].text() == "-"
    reopened = DataLoader()
    assert reopened.load(str(root)).ok
    panel.load_sample("image_a.jpg", reopened)
    assert panel._meta_edits["weight_g"].text() == "-"
    panel._meta_edits["weight_g"].setText("4.25")
    panel._save_btns["weight_g"].click()
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "4.25"


def test_missing_weight_is_not_calculated_as_zero_in_analysis(app, tmp_path):
    import pandas as pd
    from grainprofiler.widgets.sample_analysis_window import SampleAnalysisWindow
    path = tmp_path / "plant_medians.csv"
    path.write_text(
        "plant_name,weight_g,n_kernels,median_length_mm\n"
        "A,-,4,10\nB,4.0,2,11\nC,0,0,12\n",
        encoding="utf-8",
    )
    window = SampleAnalysisWindow(str(path))
    assert window.is_ok
    assert window._df.loc[0, "weight_g"] == "-"
    assert pd.isna(window._df.loc[0, "weight_per_kernel_g"])
    assert window._df.loc[1, "weight_per_kernel_g"] == 2.0
    assert pd.isna(window._df.loc[2, "weight_per_kernel_g"])


def test_missing_weight_caption_has_no_gram_unit(app, results):
    from PySide6.QtGui import QImage
    from grainprofiler.widgets.sample_view import SampleView
    root, loader = results
    image = QImage(100, 80, QImage.Format_RGB888)
    image.fill(0xFFFFFF)
    assert image.save(str(root / "image_a.jpg"))
    view = SampleView()
    view.load_sample("image_a.jpg", loader)
    panel = SampleInfoPanel()
    panel.metadata_saved.connect(view.update_metadata_caption)
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("-")
    panel._save_btns["weight_g"].click()
    assert view._caption_label.text().strip().endswith("|  -")
    assert "-g" not in view._caption_label.text()
    view.load_sample("image_a.jpg", loader)
    assert view._caption_label.text().strip().endswith("|  -")


def test_rename_preserves_csv_text_and_latent_precision(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    assert panel._meta_edits["plant_name"].text() == "001"
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("001_new")
    panel._save_btns["plant_name"].click()
    assert read_rows(root / "metadata.csv")[0]["plant_name"] == "001_new"
    assert read_rows(root / "metadata.csv")[1]["plant_name"] == "002"
    assert read_rows(root / "latent_traits.csv") == [
        {"plant_id": "001", "latent_1": "0.123456789"},
        {"plant_id": "002", "latent_1": "0.000000123"},
    ]
    assert loader.get_image_metadata("image_a.jpg")["plant_name"] == "001_new"
    assert loader.image_to_plant["image_a.jpg"] == "001"
    reopened = DataLoader()
    assert reopened.load(str(root)).ok
    assert reopened.image_to_plant["image_a.jpg"] == "001"
    assert float(reopened.get_plant_median("001")["median_length_mm"]) == 10


def test_unconfirmed_edits_survive_sample_switch_without_disk_write(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("4.50")
    panel.load_sample("image_b.jpg", loader)
    panel.load_sample("image_a.jpg", loader)
    assert panel._meta_edits["weight_g"].text() == "4.50"
    assert panel.has_pending_metadata_edits()
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "1.25"


def test_lock_uses_icon_and_toggles_metadata_editability(app, results):
    _, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    assert panel._lock_btn.text() == ""
    assert not panel._lock_btn.icon().isNull()
    assert panel._meta_edits["plant_name"].isReadOnly()
    panel._lock_btn.click()
    assert not panel._meta_edits["plant_name"].isReadOnly()
    assert panel._lock_btn.accessibleName() == "Unlocked"


def test_saving_one_field_keeps_other_field_unconfirmed(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("corrected")
    panel._meta_edits["weight_g"].setText("9.75")
    panel._save_btns["weight_g"].click()
    assert read_rows(root / "metadata.csv")[0]["plant_name"] == "001"
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "9.75"
    assert panel._meta_edits["plant_name"].text() == "corrected"
    assert panel.has_pending_metadata_edits()


def test_shared_plant_name_does_not_rename_another_sample_latent(app, results):
    root, _ = results
    path = root / "metadata.csv"
    rows = read_rows(path)
    rows[1]["plant_name"] = "001"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    loader = DataLoader()
    assert loader.load(str(root)).ok
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("changed")
    panel._save_btns["plant_name"].click()
    assert read_rows(path)[1]["plant_name"] == "001"
    assert read_rows(root / "latent_traits.csv")[0]["plant_id"] == "001"
    assert loader.image_to_plant["image_a.jpg"] == "001"
    assert loader.image_to_plant["image_b.jpg"] == "001"


def test_failed_second_write_restores_original_metadata(app, results, monkeypatch):
    root, loader = results
    original_metadata = (root / "metadata.csv").read_bytes()
    original_latents = (root / "latent_traits.csv").read_bytes()
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    original_replace = os.replace

    def replace(source, destination):
        if Path(destination).name == "metadata_original_plant_names.csv":
            raise OSError("simulated write failure")
        original_replace(source, destination)

    monkeypatch.setattr("grainprofiler.app.metadata_edit.os.replace", replace)
    panel._meta_edits["plant_name"].setText("changed")
    panel._save_btns["plant_name"].click()
    assert (root / "metadata.csv").read_bytes() == original_metadata
    assert (root / "latent_traits.csv").read_bytes() == original_latents
    assert panel.has_pending_metadata_edits()


def test_existing_plant_name_does_not_change_summary_identity(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("002")
    panel._save_btns["plant_name"].click()
    panel.load_sample("image_b.jpg", loader)
    panel.load_sample("image_a.jpg", loader)
    assert panel._plant_lbls["median_length_mm"].text() == "10.00"
    reopened = DataLoader()
    assert reopened.load(str(root)).ok
    panel.load_sample("image_a.jpg", reopened)
    assert panel._plant_lbls["median_length_mm"].text() == "10.00"


def test_draft_rejects_external_edit_after_another_save(app, results, monkeypatch):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("10")
    rows = read_rows(root / "metadata.csv")
    rows[0]["weight_g"] = "99"
    with (root / "metadata.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    panel.load_sample("image_b.jpg", loader)
    panel._meta_edits["weight_g"].setText("5")
    panel._save_btns["weight_g"].click()
    panel.load_sample("image_a.jpg", loader)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[-1]))
    panel._save_btns["weight_g"].click()
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "99"
    assert messages and "out of date" in messages[0]
    assert panel.has_pending_metadata_edits()


def test_rollback_refuses_to_overwrite_concurrent_change(results, monkeypatch):
    from grainprofiler.app.metadata_edit import save_metadata_edit
    root, _ = results
    original_replace = os.replace
    def replace(source, destination):
        if Path(destination).name == "metadata_original_plant_names.csv":
            (root / "metadata.csv").write_text("external change", encoding="utf-8")
            raise OSError("simulated second write failure")
        original_replace(source, destination)
    monkeypatch.setattr("grainprofiler.app.metadata_edit.os.replace", replace)
    with pytest.raises(OSError, match="changed"):
        save_metadata_edit(str(root), "image_a.jpg", "plant_name", "new", "001")
    assert (root / "metadata.csv").read_text(encoding="utf-8") == "external change"


def test_literal_na_and_nan_values_can_be_corrected(app, results, monkeypatch):
    root, _ = results
    path = root / "metadata.csv"
    rows = read_rows(path)
    rows[0]["plant_name"] = "NA"
    rows[0]["weight_g"] = "NaN"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    loader = DataLoader()
    assert loader.load(str(root)).ok
    panel = SampleInfoPanel()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    panel.load_sample("image_a.jpg", loader)
    assert panel._meta_edits["plant_name"].text() == "NA"
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("corrected")
    panel._save_btns["plant_name"].click()
    panel._meta_edits["weight_g"].setText("1.5")
    panel._save_btns["weight_g"].click()
    assert read_rows(path)[0]["plant_name"] == "corrected"
    assert read_rows(path)[0]["weight_g"] == "1.5"


def test_deleted_kernel_is_removed_from_all_fast_lookups(results):
    _, loader = results
    loader.remove_kernel("image_a_kernel_001.jpg")
    assert loader.get_kernel_measurement("image_a_kernel_001.jpg") is None
    assert loader.get_kernels_for_sample("image_a.jpg") == []
    assert "image_a_kernel_001.jpg" not in loader.kernel_to_image


def test_vae_loader_preserves_text_plant_ids(tmp_path):
    from types import SimpleNamespace
    from grainprofiler.widgets.vae_latent_window import VAELatentWindow
    profile = tmp_path / "profiles.txt"
    profile.write_text("001 0.1 0.2\n", encoding="utf-8")
    latent = tmp_path / "latent.csv"
    latent.write_text("plant_id,z1,z2,z3,z4,z5\n001,1,2,3,4,5\n", encoding="utf-8")
    data = SimpleNamespace(_names=[], _profiles={}, _latents={})
    VAELatentWindow._load_data(data, str(profile), str(latent))
    assert data._names == ["001"]
    assert data._latents["001"] == [1, 2, 3, 4, 5]


def test_repeated_renames_retain_original_derived_identity(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    for name in ("first", "second"):
        panel._meta_edits["plant_name"].setText(name)
        panel._save_btns["plant_name"].click()
    association = read_rows(root / "metadata_original_plant_names.csv")
    assert association == [{"image_name": "image_a.jpg", "source_plant_name": "001", "current_plant_name": "second"}]
    reopened = DataLoader()
    assert reopened.load(str(root)).ok
    assert reopened.image_to_plant["image_a.jpg"] == "001"


def test_external_name_change_disables_stale_derived_association(app, results):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["plant_name"].setText("first")
    panel._save_btns["plant_name"].click()
    rows = read_rows(root / "metadata.csv")
    rows[0]["plant_name"] = "002"
    with (root / "metadata.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    reopened = DataLoader()
    assert reopened.load(str(root)).ok
    assert reopened.image_to_plant["image_a.jpg"] == ""
    assert reopened.get_median_profile("image_a.jpg") is None


def test_saved_metadata_updates_photo_caption(app, results):
    from PySide6.QtGui import QImage
    from grainprofiler.widgets.sample_view import SampleView
    root, loader = results
    image = QImage(100, 80, QImage.Format_RGB888)
    image.fill(0xFFFFFF)
    assert image.save(str(root / "image_a.jpg"))
    view = SampleView()
    view.load_sample("image_a.jpg", loader)
    panel = SampleInfoPanel()
    panel.metadata_saved.connect(view.update_metadata_caption)
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("3.5")
    panel._save_btns["weight_g"].click()
    assert "3.5g" in view._caption_label.text()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_save_preserves_metadata_permissions(results):
    from grainprofiler.app.metadata_edit import save_metadata_edit
    root, _ = results
    path = root / "metadata.csv"
    path.chmod(0o664)
    save_metadata_edit(str(root), "image_a.jpg", "weight_g", "3", "1.25")
    assert path.stat().st_mode & 0o777 == 0o664


def test_missing_weight_can_be_corrected(app, results):
    root, _ = results
    path = root / "metadata.csv"
    rows = read_rows(path)
    rows[0]["weight_g"] = ""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    loader = DataLoader()
    assert loader.load(str(root)).ok
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    panel._meta_edits["weight_g"].setText("1.75")
    panel._save_btns["weight_g"].click()
    assert read_rows(path)[0]["weight_g"] == "1.75"


@pytest.mark.parametrize("value", ["", "nan", "inf", "-1", "not-a-number"])
def test_invalid_weight_does_not_change_csv(app, results, value, monkeypatch):
    root, loader = results
    panel = SampleInfoPanel()
    panel.load_sample("image_a.jpg", loader)
    panel._lock_btn.click()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    panel._meta_edits["weight_g"].setText(value)
    panel._save_btns["weight_g"].click()
    assert read_rows(root / "metadata.csv")[0]["weight_g"] == "1.25"
