import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate()


def test_background_update_errors_are_silent_but_manual_check_reports_them(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(main_module, "check_for_update", lambda *args: (_ for _ in ()).throw(RuntimeError("offline")))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window = main_module.MainWindow()

    window._check_for_updates(manual=False)
    wait_for(lambda: not window._update_checking)
    assert warnings == []
    window._check_for_updates(manual=True)
    wait_for(lambda: not window._update_checking)
    assert len(warnings) == 1
    assert "network" in warnings[0].lower()
    window.close()


def test_manual_check_reports_up_to_date_without_downloading(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(main_module, "check_for_update", lambda *args: None)
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    window = main_module.MainWindow()
    window._check_for_updates(manual=True)
    wait_for(lambda: not window._update_checking)
    assert messages and "up to date" in messages[0].lower()
    assert not window._update_downloading
    window.close()


def test_unsaved_metadata_prevents_installing_a_downloaded_update(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    warnings, installs, cleaned = [], [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(main_module, "schedule_install", lambda *args: installs.append(True))

    class Pending:
        def has_pending_metadata_edits(self):
            return True

    class Prepared:
        def cleanup(self):
            cleaned.append(True)

    window = main_module.MainWindow()
    window._info_panel = Pending()
    window._on_update_downloaded(Prepared(), "")
    assert not installs
    assert cleaned == [True]
    assert warnings
    window._info_panel = None
    window.close()


def test_update_download_requires_explicit_confirmation(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    window = main_module.MainWindow()
    monkeypatch.setattr(main_module.sys, "frozen", True, raising=False)
    started = []
    monkeypatch.setattr(window, "_start_update_download", lambda release: started.append(release.version))

    class Release:
        version = "1.3"

    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    window._on_update_checked(Release(), "", False)
    assert not started
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    window._on_update_checked(Release(), "", False)
    assert started == ["1.3"]
    window.close()


def test_confirmed_install_records_recovery_information(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    cleaned = []

    class Prepared:
        def cleanup(self):
            cleaned.append(True)

    class Pending:
        status_path = tmp_path / "status.txt"
        backup_path = tmp_path / "backup.exe"
        backup_sha256 = "a" * 64

        def authorize(self):
            pass

    monkeypatch.setattr(main_module, "schedule_install", lambda prepared: Pending())
    window = main_module.MainWindow()
    window._on_update_downloaded(Prepared(), "")
    assert cleaned == [True]
    assert settings.value("update/status_path") == str(Pending.status_path)
    assert settings.value("update/backup_path") == str(Pending.backup_path)
    assert settings.value("update/backup_sha256") == "a" * 64
    assert window._closing


def test_settings_failure_never_authorizes_or_closes_app(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    warnings, authorized, cleaned = [], [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    class Prepared:
        def cleanup(self):
            cleaned.append(True)

    class Pending:
        status_path = tmp_path / "status.txt"
        backup_path = tmp_path / "backup.exe"
        backup_sha256 = "a" * 64

        def authorize(self):
            authorized.append(True)

    class FailedSettings:
        def setValue(self, *args):
            settings.setValue(*args)

        def sync(self):
            pass

        def status(self):
            return QSettings.AccessError

    monkeypatch.setattr(main_module, "schedule_install", lambda prepared: Pending())
    window = main_module.MainWindow()
    window._settings = FailedSettings()
    window._on_update_downloaded(Prepared(), "")
    assert not authorized
    assert not window._closing
    assert cleaned and warnings
    window._settings = settings
    window.close()


def test_failed_restart_reports_failure_without_deleting_backup(app, tmp_path, monkeypatch):
    import grainprofiler.app.main_window as main_module

    settings = QSettings(str(tmp_path / "update.ini"), QSettings.IniFormat)
    monkeypatch.setattr(main_module, "QSettings", lambda *args: settings)
    monkeypatch.setattr(main_module.sys, "executable", str(tmp_path / "MKProfiler.exe"))
    status = tmp_path / ("MKProfiler.exe.update-status-" + "a" * 32 + ".txt")
    status.write_text("failed", encoding="ascii")
    backup = tmp_path / "old-version.bak"
    backup.write_bytes(b"original")
    settings.setValue("update/status_path", str(status))
    settings.setValue("update/backup_path", str(backup))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window = main_module.MainWindow()
    window._report_update_status()
    assert warnings and "failed" in warnings[0].lower()
    assert backup.read_bytes() == b"original"
    assert settings.value("update/status_path") is None
    window.close()


def test_startup_acknowledges_only_a_safe_local_update_marker(tmp_path, monkeypatch):
    import grainprofiler.main as entry

    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry.sys, "executable", str(tmp_path / "MKProfiler.exe"))
    ready = tmp_path / (".MKProfiler-update-" + "a" * 32 + ".ready")
    monkeypatch.setenv("MKPROFILER_UPDATE_READY", str(ready))
    entry._signal_update_ready()
    assert ready.read_text(encoding="ascii") == "ready"
    assert "MKPROFILER_UPDATE_READY" not in os.environ

    outside = tmp_path.parent / (".MKProfiler-update-" + "b" * 32 + ".ready")
    monkeypatch.setenv("MKPROFILER_UPDATE_READY", str(outside))
    entry._signal_update_ready()
    assert not outside.exists()
