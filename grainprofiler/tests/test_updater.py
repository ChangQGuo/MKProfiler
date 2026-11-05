"""Behavioral tests for the standalone Windows updater."""

import copy
import ctypes
import hashlib
import io
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request

from grainprofiler.app import updater


OWNER = "Example"
REPO = "MKProfiler"
TAG = "v1.10"
ZIP_NAME = "MKProfiler_v1.10_20261105.zip"
CHECKSUM_NAME = "MKProfiler_v1.10_20261105.sha256.txt"
ASSET_BASE = "https://github.com/Example/MKProfiler/releases/download/v1.10/"


def release_metadata():
    return {
        "tag_name": TAG,
        "draft": False,
        "prerelease": False,
        "body": "Notes",
        "assets": [
            {"name": ZIP_NAME, "state": "uploaded", "browser_download_url": ASSET_BASE + ZIP_NAME},
            {"name": CHECKSUM_NAME, "state": "uploaded", "browser_download_url": ASSET_BASE + CHECKSUM_NAME},
        ],
        "zipball_url": "https://api.github.com/repos/Example/MKProfiler/zipball/v1.10",
    }


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class VersionTests(unittest.TestCase):
    def test_versions_are_compared_numerically_and_ignore_trailing_zeroes(self):
        from grainprofiler.app import updater

        for candidate, current, expected in [
            ("v1.10", "1.9", True),
            ("1.2.1", "v1.2", True),
            ("1.2", "1.2.0", False),
            ("1.2.0", "1.2.1", False),
        ]:
            with self.subTest(candidate=candidate, current=current):
                self.assertEqual(updater.is_newer_version(candidate, current), expected)

    def test_prereleases_and_malformed_versions_are_rejected(self):
        from grainprofiler.app import updater

        for version in ("v1.2-beta", "1", "1.2+local", "v01.2", "1.2/3", "", "9" * 5000 + ".1"):
            with self.subTest(version=version):
                with self.assertRaises(updater.UpdateError):
                    updater.is_newer_version(version, "1.2")


class ReleaseTests(unittest.TestCase):
    def test_release_parsing_selects_named_uploaded_assets(self):
        release = updater.parse_release_metadata(release_metadata(), OWNER, REPO)
        self.assertEqual((release.tag, release.version, release.notes), ("v1.10", "1.10", "Notes"))
        self.assertEqual(release.zip_url, ASSET_BASE + ZIP_NAME)
        self.assertEqual(release.checksum_url, ASSET_BASE + CHECKSUM_NAME)

    def test_drafts_prereleases_missing_and_duplicate_assets_are_rejected(self):
        for change in ("draft", "prerelease", "missing", "duplicate", "source_only", "unuploaded",
                       "multiple_dates", "multiple_checksums"):
            data = release_metadata()
            if change in ("draft", "prerelease"):
                data[change] = True
            elif change == "missing":
                data["assets"].pop()
            elif change == "duplicate":
                data["assets"].append(copy.deepcopy(data["assets"][0]))
            elif change == "source_only":
                data["assets"] = []
            elif change == "multiple_dates":
                data["assets"].append({
                    "name": "MKProfiler_v1.10_20261106.zip", "state": "uploaded",
                    "browser_download_url": ASSET_BASE + "MKProfiler_v1.10_20261106.zip",
                })
            elif change == "multiple_checksums":
                data["assets"].append({
                    "name": ZIP_NAME + ".sha256.txt", "state": "uploaded",
                    "browser_download_url": ASSET_BASE + ZIP_NAME + ".sha256.txt",
                })
            else:
                data["assets"][0]["state"] = "new"
            with self.subTest(change=change), self.assertRaises(updater.UpdateError):
                updater.parse_release_metadata(data, OWNER, REPO)

    def test_release_date_changes_and_both_checksum_naming_conventions_work(self):
        for date, zip_suffix in (("20261231", False), ("20270102", True)):
            data = release_metadata()
            zip_name = "MKProfiler_v1.10_" + date + ".zip"
            checksum = zip_name + ".sha256.txt" if zip_suffix else zip_name[:-4] + ".sha256.txt"
            data["assets"] = [
                {"name": zip_name, "state": "uploaded", "browser_download_url": ASSET_BASE + zip_name},
                {"name": checksum, "state": "uploaded", "browser_download_url": ASSET_BASE + checksum},
            ]
            with self.subTest(date=date, zip_suffix=zip_suffix):
                release = updater.parse_release_metadata(data, OWNER, REPO)
                self.assertEqual(release.zip_name, zip_name)
                self.assertEqual(release.checksum_url, ASSET_BASE + checksum)

    def test_requested_v12_release_filename_is_accepted(self):
        data = release_metadata()
        data["tag_name"] = "v1.2"
        base = "https://github.com/Example/MKProfiler/releases/download/v1.2/"
        data["assets"] = [
            {"name": "MKProfiler_v1.2_20261105.zip", "state": "uploaded",
             "browser_download_url": base + "MKProfiler_v1.2_20261105.zip"},
            {"name": "MKProfiler_v1.2_20261105.sha256.txt", "state": "uploaded",
             "browser_download_url": base + "MKProfiler_v1.2_20261105.sha256.txt"},
        ]
        release = updater.parse_release_metadata(data, OWNER, REPO)
        self.assertEqual(release.zip_name, "MKProfiler_v1.2_20261105.zip")

    def test_asset_urls_must_be_https_for_exact_release_and_repository(self):
        bad_urls = [
            ASSET_BASE.replace("https:", "http:") + ZIP_NAME,
            ASSET_BASE.replace("github.com", "github.com.evil.test") + ZIP_NAME,
            ASSET_BASE.replace("github.com", "github.com@evil.test") + ZIP_NAME,
            ASSET_BASE.replace("/Example/", "/Other/") + ZIP_NAME,
            ASSET_BASE.replace("/v1.10/", "/v9.9/") + ZIP_NAME,
            ASSET_BASE + ZIP_NAME + "?x=1",
            ASSET_BASE.replace("github.com", "github.com:444") + ZIP_NAME,
        ]
        for url in bad_urls:
            data = release_metadata()
            data["assets"][0]["browser_download_url"] = url
            with self.subTest(url=url), self.assertRaises(updater.UpdateError):
                updater.parse_release_metadata(data, OWNER, REPO)

    def test_only_allowed_https_redirects_are_followed(self):
        handler = updater._SafeRedirect({"github.com", "release-assets.githubusercontent.com"})
        request = Request(ASSET_BASE + ZIP_NAME)
        redirect = handler.redirect_request(
            request, None, 302, "Found", {},
            "https://release-assets.githubusercontent.com/download?signature=abc",
        )
        self.assertEqual(redirect.full_url, "https://release-assets.githubusercontent.com/download?signature=abc")
        for url in (
            "http://release-assets.githubusercontent.com/download",
            "https://release-assets.githubusercontent.com.evil.test/download",
            "https://github.com@evil.test/download",
            "https://api.github.com/repos/other/project",
        ):
            with self.subTest(url=url), self.assertRaises(updater.UpdateError):
                handler.redirect_request(request, None, 302, "Found", {}, url)

    def test_check_for_update_reads_release_and_compares_versions(self):
        payload = json.dumps(release_metadata()).encode()
        with mock.patch.object(updater, "_open_url", side_effect=lambda url, *a: Response(payload, url)):
            self.assertEqual(updater.check_for_update("1.9", OWNER, REPO).version, "1.10")
            self.assertIsNone(updater.check_for_update("1.10.0", OWNER, REPO))

    def test_private_or_unreachable_release_is_reported_as_error(self):
        error = HTTPError("https://api.github.com", 404, "Not Found", {}, None)
        with mock.patch.object(updater, "_open_url", side_effect=error):
            with self.assertRaises(updater.UpdateError):
                updater.check_for_update("1.2", OWNER, REPO)

    def test_open_url_uses_system_proxy_configuration(self):
        url = "https://api.github.com/repos/Example/MKProfiler/releases/latest"
        handlers = []

        class Opener:
            def open(self, request, timeout):
                return Response(b"{}", request.full_url)

        def build(*items):
            handlers.extend(items)
            return Opener()

        with mock.patch("urllib.request.getproxies", return_value={"https": "http://127.0.0.1:8765"}):
            with mock.patch.object(updater, "build_opener", side_effect=build):
                with updater._open_url(url, {"api.github.com"}, 5) as response:
                    self.assertEqual(response.read(), b"{}")
        proxies = [handler.proxies for handler in handlers if isinstance(handler, ProxyHandler)]
        self.assertEqual(proxies, [{"https": "http://127.0.0.1:8765"}])


def executable_bytes(marker=b"new"):
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    data[0xA0:0xA0 + len(marker)] = marker
    return bytes(data)


def archive_bytes(extra=(), executable=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("MKProfiler.exe", executable if executable is not None else executable_bytes())
        for name, contents in extra:
            if isinstance(name, str) and "\\" in name:
                info = zipfile.ZipInfo("placeholder")
                info.filename = name  # Preserve the unsafe raw ZIP name on Windows.
                name = info
            archive.writestr(name, contents)
    return output.getvalue()


class PreparationFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.release = updater.parse_release_metadata(release_metadata(), OWNER, REPO)

    def prepare(self, content, checksum=None, release=None, broken=False):
        release = release or self.release
        if checksum is None:
            checksum = (hashlib.sha256(content).hexdigest() + "  " + ZIP_NAME + "\n").encode()

        class Interrupted(Response):
            def read(self, size=-1):
                raise OSError("connection lost")

        def open_url(url, hosts, timeout):
            if url == release.checksum_url:
                return Response(checksum, url)
            if url == release.zip_url:
                return Interrupted(content, url) if broken else Response(content, url)
            raise AssertionError("Unexpected URL")

        with mock.patch.object(updater, "_open_url", side_effect=open_url):
            return updater.prepare_update(release, temp_dir=self.temp.name)


class PreparationTests(PreparationFixture, unittest.TestCase):
    def test_valid_archive_is_verified_and_only_executable_is_staged(self):
        data = archive_bytes(extra=[("README.txt", "notes"), ("SHA256.txt", "data")])
        prepared = self.prepare(data)
        directory = prepared.executable.parent
        self.assertEqual(prepared.executable.read_bytes(), executable_bytes())
        self.assertEqual(prepared.exe_sha256, hashlib.sha256(executable_bytes()).hexdigest())
        self.assertEqual([p.name for p in directory.iterdir()], ["MKProfiler.exe"])
        prepared.cleanup()
        self.assertFalse(directory.exists())

    def test_checksum_must_uniquely_identify_versioned_zip(self):
        data = archive_bytes()
        good = hashlib.sha256(data).hexdigest()
        cases = [
            b"wrong",
            (good + "  other.zip\n").encode(),
            (good + "  " + ZIP_NAME + "\n" + good + "  " + ZIP_NAME + "\n").encode(),
            ("0" * 64 + "  " + ZIP_NAME + "\n").encode(),
        ]
        for checksum in cases:
            with self.subTest(checksum=checksum), self.assertRaises(updater.UpdateError):
                self.prepare(data, checksum=checksum)

    def test_github_digest_must_agree_with_checksum_file(self):
        data = release_metadata()
        data["assets"][0]["digest"] = "sha256:" + "0" * 64
        release = updater.parse_release_metadata(data, OWNER, REPO)
        with self.assertRaises(updater.UpdateError):
            self.prepare(archive_bytes(), release=release)

    def test_corrupt_zip_bad_crc_and_invalid_executable_are_rejected(self):
        good = archive_bytes()
        corrupted_crc = good.replace(executable_bytes(), executable_bytes(b"bad"), 1)
        for data in (b"not a ZIP", corrupted_crc, archive_bytes(executable=b"not an exe")):
            with self.subTest(length=len(data)), self.assertRaises(updater.UpdateError):
                self.prepare(data)

    def test_unsafe_zip_paths_and_links_are_rejected(self):
        symlink = zipfile.ZipInfo("link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        for name in ("../escape", "/absolute", "C:/evil", "x\\evil", "dir/../../escape",
                     "CON.txt", "folder/trailing. ", "mkprofiler.exe", symlink):
            with self.subTest(name=str(name)), self.assertRaises(updater.UpdateError):
                self.prepare(archive_bytes(extra=[(name, "x")]))
        self.assertFalse((Path(self.temp.name) / "escape").exists())

    def test_interrupted_download_does_not_touch_installed_executable(self):
        installed = Path(self.temp.name) / "MKProfiler.exe"
        installed.write_bytes(b"original")
        with self.assertRaises(updater.UpdateError):
            self.prepare(archive_bytes(), broken=True)
        self.assertEqual(installed.read_bytes(), b"original")
        self.assertEqual(sorted(p.name for p in Path(self.temp.name).iterdir()), ["MKProfiler.exe"])


@unittest.skipUnless(os.name == "nt", "Windows replacement helper")
class InstallationTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.install_dir = Path(self.temp.name) / "Install space ' $(not-a-command) 中文"
        self.install_dir.mkdir()
        self.target = self.install_dir / "MKProfiler.exe"
        self.original = executable_bytes(b"old")
        self.target.write_bytes(self.original)

    def start_owner(self, source, sha256, *, restore=False, transient_status_lock=False, restart=False, authorize=True):
        script = """
import json, sys
from pathlib import Path
from grainprofiler.app import updater
source, digest, target, restore, transient_lock, restart, authorize = sys.argv[1:]
if transient_lock == "1":
    original_read = Path.read_text
    seen = [False]
    def read_with_transient_lock(path, *args, **kwargs):
        if "update-status-" in path.name and not seen[0]:
            seen[0] = True
            raise PermissionError("transient replacement lock")
        return original_read(path, *args, **kwargs)
    Path.read_text = read_with_transient_lock
if restore == "1":
    pending = updater.schedule_restore(Path(source), digest, executable_path=Path(target), restart=restart == "1")
else:
    prepared = updater.PreparedUpdate(None, Path(source), digest, None)
    pending = updater.schedule_install(prepared, executable_path=Path(target), restart=restart == "1")
if authorize == "1":
    pending.authorize()
print(json.dumps({"status": str(pending.status_path), "backup": str(pending.backup_path),
                  "backup_sha256": pending.backup_sha256}), flush=True)
sys.stdin.read(1)
"""
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", script, str(source), sha256, str(self.target),
             "1" if restore else "0", "1" if transient_status_lock else "0", "1" if restart else "0",
             "1" if authorize is True else "0" if authorize is False else "legacy"],
            cwd=str(Path(updater.__file__).parents[2]),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        def cleanup_owner():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        self.addCleanup(cleanup_owner)
        line = process.stdout.readline()
        if not line:
            self.fail("Owner could not schedule update: " + process.stderr.read())
        return process, json.loads(line)

    def finish_owner(self, process, status):
        process.communicate(input="x", timeout=10)
        self.assertEqual(process.returncode, 0)
        status_path = Path(status)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                state = status_path.read_text(encoding="utf-8").strip()
            except (PermissionError, FileNotFoundError):
                time.sleep(0.1)
                continue
            if state not in ("pending", "ready"):
                return state
            time.sleep(0.1)
        self.fail("Replacement helper did not finish")

    def test_real_helper_waits_for_exit_replaces_and_restores_backup(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(Path(pending["status"]).read_text(encoding="utf-8").strip(), "ready")
        self.assertEqual(self.finish_owner(process, pending["status"]), "installed")
        backup = Path(pending["backup"])
        self.assertEqual(self.target.read_bytes(), executable_bytes())
        self.assertEqual(backup.read_bytes(), self.original)

        self.assertEqual(pending["backup_sha256"], hashlib.sha256(self.original).hexdigest())
        process, restore = self.start_owner(backup, pending["backup_sha256"], restore=True)
        self.assertEqual(self.finish_owner(process, restore["status"]), "installed")
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(Path(restore["backup"]).read_bytes(), executable_bytes())

    def test_launch_failure_leaves_original_and_no_staged_files(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        with mock.patch.object(updater.subprocess, "Popen", side_effect=PermissionError("denied")):
            with self.assertRaises(updater.UpdateError):
                updater.schedule_install(prepared, executable_path=self.target, restart=False)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual([p.name for p in self.install_dir.iterdir()], ["MKProfiler.exe"])

    def test_modified_candidate_is_refused_before_launch(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        prepared.executable.write_bytes(executable_bytes(b"tampered"))
        with self.assertRaises(updater.UpdateError):
            updater.schedule_install(prepared, executable_path=self.target, restart=False)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_only_generated_backups_in_install_directory_can_be_restored(self):
        outside = Path(self.temp.name) / "arbitrary.exe"
        outside.write_bytes(executable_bytes(b"other"))
        with self.assertRaises(updater.UpdateError):
            updater.schedule_restore(outside, hashlib.sha256(outside.read_bytes()).hexdigest(),
                                     executable_path=self.target, restart=False)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_tampered_generated_backup_is_rejected(self):
        backup = self.install_dir / ("MKProfiler.exe.update-backup-" + "a" * 32 + ".bak")
        backup.write_bytes(executable_bytes(b"bad"))
        with self.assertRaises(updater.UpdateError):
            updater.schedule_restore(backup, hashlib.sha256(self.original).hexdigest(),
                                     executable_path=self.target, restart=False)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_candidate_changed_after_scheduling_never_replaces_original(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256)
        candidate = next(self.install_dir.glob(".MKProfiler-update-*.tmp"))
        candidate.write_bytes(executable_bytes(b"bad"))
        self.assertEqual(self.finish_owner(process, pending["status"]), "candidate-changed")
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(Path(pending["backup"]).exists())

    def test_changed_target_is_not_overwritten_by_stale_update(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256)
        changed = executable_bytes(b"other")
        self.target.write_bytes(changed)
        self.assertEqual(self.finish_owner(process, pending["status"]), "target-changed")
        self.assertEqual(self.target.read_bytes(), changed)

    def test_transient_status_lock_during_start_is_retried(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256,
                                            transient_status_lock=True)
        self.assertEqual(self.finish_owner(process, pending["status"]), "installed")
        self.assertEqual(self.target.read_bytes(), executable_bytes())

    def marker_executable(self, marker, *, acknowledge=False):
        windows_dir = updater._powershell()[1].parent
        compiler = windows_dir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
        if not compiler.is_file():
            self.skipTest("Windows .NET Framework C# compiler unavailable")
        source = Path(self.temp.name) / (marker + ".cs")
        binary = Path(self.temp.name) / (marker + ".exe")
        health = (
            'string ready=System.Environment.GetEnvironmentVariable("MKPROFILER_UPDATE_READY");'
            'if (string.IsNullOrEmpty(ready)) return; System.IO.File.WriteAllText(ready,"ready");'
            if acknowledge else ''
        )
        source.write_text(
            'class Program { static void Main() { ' + health + 'System.IO.File.WriteAllText('
            'System.IO.Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "'
            + marker + '"), "started"); } }', encoding="utf-8",
        )
        result = subprocess.run(
            [str(compiler), "/nologo", "/target:winexe", "/out:" + str(binary), str(source)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return binary.read_bytes()

    def test_failed_update_restarts_verified_old_binary_and_keeps_failure_status(self):
        original = self.marker_executable("old-restarted")
        self.target.write_bytes(original)
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, restart=True)
        next(self.install_dir.glob(".MKProfiler-update-*.tmp")).write_bytes(executable_bytes(b"bad"))
        self.assertEqual(self.finish_owner(process, pending["status"]), "candidate-changed")
        marker = self.install_dir / "old-restarted"
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(marker.exists(), "Verified old executable was not restarted")
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(Path(pending["status"]).read_text(encoding="utf-8").strip(), "candidate-changed")

    def test_unstartable_update_restores_and_restarts_old_version(self):
        original = self.marker_executable("old-after-restart-failure")
        self.target.write_bytes(original)
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, restart=True)
        self.assertEqual(self.finish_owner(process, pending["status"]), "restart-failed")
        marker = self.install_dir / "old-after-restart-failure"
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(marker.exists())
        self.assertEqual(self.target.read_bytes(), original)

    def test_update_exiting_before_ready_rolls_back(self):
        original = self.marker_executable("old-after-early-exit")
        self.target.write_bytes(original)
        new_binary = self.marker_executable("new-exited")
        prepared = self.prepare(archive_bytes(executable=new_binary))
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, restart=True)
        self.assertEqual(self.finish_owner(process, pending["status"]), "startup-failed")
        marker = self.install_dir / "old-after-early-exit"
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(marker.exists())
        self.assertEqual(self.target.read_bytes(), original)

    def test_update_signalling_ready_is_kept(self):
        new_binary = self.marker_executable("new-ready", acknowledge=True)
        prepared = self.prepare(archive_bytes(executable=new_binary))
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, restart=True)
        self.assertEqual(self.finish_owner(process, pending["status"]), "installed")
        marker = self.install_dir / "new-ready"
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(marker.exists())
        self.assertEqual(self.target.read_bytes(), new_binary)

    def test_unapproved_update_does_not_replace_after_owner_exits(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, authorize=False)
        self.assertEqual(self.finish_owner(process, pending["status"]), "not-authorized")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_failed_authorization_never_leaves_an_approval_marker(self):
        pending = updater.PendingInstall(self.install_dir / "status", self.install_dir / "backup", "a" * 64,
                                         self.install_dir / ".authorization")
        with mock.patch.object(updater.os, "fsync", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                pending.authorize()
        self.assertFalse((self.install_dir / ".authorization").exists())
        self.assertFalse((self.install_dir / ".authorization.tmp").exists())

    def test_incomplete_authorization_does_not_allow_replacement(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, authorize=False)
        token = Path(pending["status"]).name.removeprefix("MKProfiler.exe.update-status-").removesuffix(".txt")
        (self.install_dir / (".MKProfiler-update-" + token + ".authorized")).write_text("incomplete", encoding="ascii")
        self.assertEqual(self.finish_owner(process, pending["status"]), "not-authorized")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_waits_for_a_temporarily_locked_executable(self):
        from ctypes import wintypes

        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(self.target), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        released = threading.Event()

        def release():
            kernel.CloseHandle(handle)
            released.set()

        timer = threading.Timer(6, release)
        timer.start()
        try:
            self.assertEqual(self.finish_owner(process, pending["status"]), "installed")
            self.assertEqual(self.target.read_bytes(), executable_bytes())
        finally:
            timer.cancel()
            if not released.is_set():
                release()

    def test_failure_never_restarts_a_changed_target(self):
        original = self.marker_executable("old-marker")
        unexpected = self.marker_executable("unexpected-marker")
        self.target.write_bytes(original)
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256, restart=True)
        self.target.write_bytes(unexpected)
        self.assertEqual(self.finish_owner(process, pending["status"]), "target-changed")
        time.sleep(1)
        self.assertFalse((self.install_dir / "unexpected-marker").exists())
        self.assertEqual(self.target.read_bytes(), unexpected)

    def test_read_only_executable_is_preserved_when_replacement_fails(self):
        prepared = self.prepare(archive_bytes())
        self.addCleanup(prepared.cleanup)
        process, pending = self.start_owner(prepared.executable, prepared.exe_sha256)
        os.chmod(self.target, stat.S_IREAD)
        try:
            self.assertEqual(self.finish_owner(process, pending["status"]), "failed")
            self.assertEqual(self.target.read_bytes(), self.original)
        finally:
            os.chmod(self.target, stat.S_IREAD | stat.S_IWRITE)


if __name__ == "__main__":
    unittest.main()
