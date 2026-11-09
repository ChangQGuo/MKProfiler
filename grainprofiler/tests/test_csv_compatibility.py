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
