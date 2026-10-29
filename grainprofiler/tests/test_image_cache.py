import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from grainprofiler.widgets.sample_view import SampleView


def test_large_image_cache_preserves_original_coordinates(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = QImage(5408, 4056, QImage.Format_RGB888)
    image.fill(0xFFCCAA)
    photo = tmp_path / "large.jpg"
    assert image.save(str(photo))
    view = SampleView()
    first = view._load_cached_pixmap(str(photo))
    second = view._load_cached_pixmap(str(photo))
    assert first is second
    pixmap, width, height = first
    assert (width, height) == (5408, 4056)
    assert pixmap.width() <= 2400
    assert abs(pixmap.width() / pixmap.height() - width / height) < 0.01
    assert app is not None


def test_exif_rotation_matches_pipeline_image_coordinates(tmp_path):
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    photo = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (80, 40), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(photo, exif=exif)
    view = SampleView()
    pixmap, width, height = view._load_cached_pixmap(str(photo))
    assert (width, height) == (40, 80)
    assert (pixmap.width(), pixmap.height()) == (40, 80)
    assert app is not None
