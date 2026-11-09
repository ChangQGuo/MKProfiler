"""Standalone, synchronous update operations for a Qt worker thread."""

import base64
import ctypes
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_ASSET_HOSTS = frozenset({
    "github.com", "release-assets.githubusercontent.com",
    "objects.githubusercontent.com", "github-releases.githubusercontent.com",
})


class UpdateError(Exception):
    """An update could not be validated, downloaded, or scheduled."""


def _version_parts(version):
    if not isinstance(version, str) or len(version) > 128 or not re.fullmatch(
        r"v?(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))+", version
    ):
        raise UpdateError("Expected a stable numeric version such as v1.2")
    parts = tuple(int(part) for part in version.lstrip("v").split("."))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def is_newer_version(candidate, current):
    """Compare stable dotted versions numerically, ignoring trailing zeroes."""
    return _version_parts(candidate) > _version_parts(current)


@dataclass(frozen=True)
class Release:
    owner: str
    repository: str
    tag: str
    version: str
    notes: str
    zip_name: str
    zip_url: str
    checksum_url: str
    github_digest: str = ""


def _repository(owner, repository):
    if (not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner)
            or not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository)
            or repository in (".", "..")):
        raise UpdateError("Invalid GitHub repository")


def _validate_url(url, hosts):
    try:
        if (not isinstance(url, str) or url != url.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in url)):
            raise ValueError("invalid URL")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in hosts
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError("untrusted URL")
    except (TypeError, ValueError) as exc:
        raise UpdateError("Only trusted HTTPS download URLs are allowed") from exc
    return parsed


class _SafeRedirect(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = frozenset(hosts)

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _validate_url(newurl, self.hosts)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _open_url(url, hosts, timeout):
    _validate_url(url, hosts)
    # Respect the operating system's proxy settings; HTTPS still validates TLS.
    opener = build_opener(ProxyHandler(), _SafeRedirect(hosts))
    request = Request(url, headers={"User-Agent": "MKProfiler-Updater", "Accept": "application/vnd.github+json"})
    response = opener.open(request, timeout=timeout)
    try:
        _validate_url(response.geturl(), hosts)
    except Exception:
        response.close()
        raise
    return response


def _read_limited(url, hosts, limit, timeout):
    with _open_url(url, hosts, timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Update metadata exceeds the allowed size")
    return data


def parse_release_metadata(data, owner, repository):
    """Parse one stable GitHub release and require its explicit ZIP and SHA256 assets."""
    _repository(owner, repository)
    if (not isinstance(data, dict) or data.get("draft") is not False
            or data.get("prerelease") is not False):
        raise UpdateError("Release is not a published stable release")
    tag = data.get("tag_name")
    _version_parts(tag)
    version = tag.lstrip("v")
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Release assets are missing")
    pattern = re.compile(r"MKProfiler_v" + re.escape(version) + r"_(\d{8})\.zip")
    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            raise UpdateError("Invalid release asset")
        name = asset.get("name")
        match = pattern.fullmatch(name) if isinstance(name, str) else None
        if match:
            try:
                stamp = match.group(1)
                date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
            except ValueError as exc:
                raise UpdateError("Release ZIP has an invalid date") from exc
            candidates.append(asset)
    if len(candidates) != 1:
        raise UpdateError("Release must contain exactly one dated ZIP for its version")
    zip_asset = candidates[0]
    zip_name = zip_asset["name"]
    checksum_names = (zip_name[:-4] + ".sha256.txt", zip_name + ".sha256.txt")
    checksums = [asset for asset in assets if asset.get("name") in checksum_names]
    if len(checksums) != 1:
        raise UpdateError("Release must include its versioned ZIP and SHA256 file")
    checksum_asset = checksums[0]
    for asset in (zip_asset, checksum_asset):
        if asset.get("state") != "uploaded":
            raise UpdateError("Release assets must be uploaded")
        url = asset.get("browser_download_url")
        parsed = _validate_url(url, {"github.com"})
        expected = "/" + "/".join((owner, repository, "releases", "download", tag, asset["name"]))
        if parsed.path != expected or parsed.query:
            raise UpdateError("Release asset does not belong to the expected release")
    digest = zip_asset.get("digest")
    if digest is not None and (not isinstance(digest, str)
                               or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)):
        raise UpdateError("Invalid GitHub asset digest")
    notes = data.get("body") or ""
    if not isinstance(notes, str):
        raise UpdateError("Invalid release notes")
    return Release(owner, repository, tag, version, notes, zip_name,
                   zip_asset["browser_download_url"],
                   checksum_asset["browser_download_url"],
                   digest[7:].lower() if digest else "")


def check_for_update(current_version, owner, repository, timeout=15):
    """Return a newer Release, or None; perform this blocking call in a worker."""
    _version_parts(current_version)
    _repository(owner, repository)
    url = "https://api.github.com/repos/{}/{}/releases/latest".format(owner, repository)
    try:
        raw = _read_limited(url, {"api.github.com"}, 1024 * 1024, timeout)
        data = json.loads(raw.decode("utf-8"))
        release = parse_release_metadata(data, owner, repository)
    except (OSError, ValueError, UnicodeError):
        raise UpdateError("Could not read GitHub release metadata; the release may be unavailable or private") from None
    return release if is_newer_version(release.version, current_version) else None


@dataclass
class PreparedUpdate:
    """Verified executable in a private temporary directory; call cleanup when done."""
    release: Release
    executable: Path
    exe_sha256: str
    _temporary: tempfile.TemporaryDirectory

    def cleanup(self):
        self._temporary.cleanup()


def _revalidate_release(release):
    if not isinstance(release, Release):
        raise UpdateError("Expected a parsed release")
    checksum_name = _validate_url(release.checksum_url, {"github.com"}).path.rsplit("/", 1)[-1]
    data = {
        "tag_name": release.tag, "draft": False, "prerelease": False, "body": release.notes,
        "assets": [
            {"name": release.zip_name, "state": "uploaded", "browser_download_url": release.zip_url,
             "digest": "sha256:" + release.github_digest if release.github_digest else None},
            {"name": checksum_name, "state": "uploaded", "browser_download_url": release.checksum_url},
        ],
    }
    if parse_release_metadata(data, release.owner, release.repository) != release:
        raise UpdateError("Release metadata is inconsistent")


def _zip_sha256(manifest, name):
    try:
        text = manifest.decode("utf-8-sig")
    except UnicodeError as exc:
        raise UpdateError("Invalid SHA256 file") from exc
    hashes = []
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9A-Fa-f]{64})[ \t]+\*?([^\r\n]+)", line)
        if match and match.group(2) == name:
            hashes.append(match.group(1).lower())
    if len(hashes) != 1:
        raise UpdateError("SHA256 file must contain exactly one hash for the release ZIP")
    return hashes[0]


def _validate_zip_members(archive):
    seen = set()
    executable = None
    for info in archive.infolist():
        name = info.orig_filename
        parts = name.rstrip("/").split("/")
        if (not name or name.startswith("/") or "\\" in name
                or any(not part or part in (".", "..") or part[-1] in (" ", ".")
                       or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                       or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                       for part in parts)):
            raise UpdateError("Unsafe path in release ZIP")
        key = name.rstrip("/").casefold()
        if key in seen:
            raise UpdateError("Duplicate path in release ZIP")
        seen.add(key)
        mode = (info.external_attr >> 16) if info.create_system == 3 else 0
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise UpdateError("Links and special files are not allowed in release ZIP")
        if name == "MKProfiler.exe" and not info.is_dir():
            executable = info
    if executable is None or executable.file_size <= 0 or executable.file_size > 1024 ** 3:
        raise UpdateError("Release ZIP must contain a reasonably sized root MKProfiler.exe")
    return executable


def _check_pe(path):
    with open(path, "rb") as executable:
        header = executable.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise UpdateError("Downloaded executable has an invalid PE header")
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        if offset < 64 or offset > path.stat().st_size - 24:
            raise UpdateError("Downloaded executable has an invalid PE header")
        executable.seek(offset)
        if executable.read(4) != b"PE\0\0":
            raise UpdateError("Downloaded executable has an invalid PE header")


def prepare_update(release, timeout=30, temp_dir=None):
    """Download and verify a release without modifying the installed application.

    The caller owns the returned object and must call cleanup(), including on
    cancellation. Downloads are anonymous; no credential store is accessed.
    """
    _revalidate_release(release)
    try:
        temporary = tempfile.TemporaryDirectory(prefix="mkprofiler-update-", dir=temp_dir)
    except OSError:
        raise UpdateError("Cannot create the update temporary directory") from None
    directory = Path(temporary.name)
    archive_path = directory / "release.zip"
    executable_path = directory / "MKProfiler.exe"
    try:
        manifest = _read_limited(release.checksum_url, _ASSET_HOSTS, 64 * 1024, timeout)
        expected_hash = _zip_sha256(manifest, release.zip_name)
        if release.github_digest and release.github_digest != expected_hash:
            raise UpdateError("GitHub asset digest and SHA256 file disagree")
        digest = hashlib.sha256()
        size = 0
        with _open_url(release.zip_url, _ASSET_HOSTS, timeout) as response, open(archive_path, "xb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 1024 ** 3:
                    raise UpdateError("Release ZIP exceeds the allowed size")
                digest.update(chunk)
                target.write(chunk)
        if digest.hexdigest() != expected_hash:
            raise UpdateError("Release ZIP failed its SHA256 check")
        exe_digest = hashlib.sha256()
        with zipfile.ZipFile(archive_path) as archive:
            info = _validate_zip_members(archive)
            with archive.open(info) as source, open(executable_path, "xb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    exe_digest.update(chunk)
                    target.write(chunk)
        _check_pe(executable_path)
        archive_path.unlink()
        return PreparedUpdate(release, executable_path, exe_digest.hexdigest(), temporary)
    except (OSError, ValueError, RuntimeError, EOFError, zipfile.BadZipFile, NotImplementedError):
        temporary.cleanup()
        raise UpdateError("Could not download or verify the update") from None
    except BaseException:
        temporary.cleanup()
        raise


@dataclass(frozen=True)
class PendingInstall:
    """Paths for checking the helper's status and recovering the previous version."""
    status_path: Path
    backup_path: Path
    backup_sha256: str
    _authorization_path: Path

    def authorize(self):
        """Permit replacement after the caller has saved recovery information."""
        created = False
        temporary = self._authorization_path.with_name(self._authorization_path.name + ".tmp")
        try:
            with temporary.open("x", encoding="ascii") as marker:
                created = True
                marker.write("authorized")
                marker.flush()
                os.fsync(marker.fileno())
            os.rename(temporary, self._authorization_path)
        except BaseException:
            if created:
                temporary.unlink(missing_ok=True)
            raise


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_executable(executable_path):
    if os.name != "nt":
        raise UpdateError("Installing updates is supported only on Windows")
    if executable_path is None:
        if not getattr(sys, "frozen", False):
            raise UpdateError("Installation requires the packaged application")
        executable_path = sys.executable
    path = Path(executable_path).absolute()
    try:
        info = path.lstat()
        if (path.name.casefold() != "mkprofiler.exe" or not path.is_file()
                or path.is_symlink()
                or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise UpdateError("The target must be the actual MKProfiler.exe file")
    except OSError as exc:
        raise UpdateError("The installed executable is unavailable") from exc
    return path


def _powershell():
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise UpdateError("Cannot locate the Windows system directory")
    system_dir = Path(buffer.value)
    executable = system_dir / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not executable.is_file():
        raise UpdateError("Windows PowerShell is unavailable")
    return executable, system_dir


def _replacement_command(target, candidate, backup, status, authorization, readiness, new_hash, old_hash, restart):
    # Every external string is encoded as data, never interpolated as PowerShell code.
    def literal(value):
        encoded = base64.b64encode(str(value).encode("utf-8")).decode("ascii")
        return "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))"

    values = {
        "target": literal(target), "candidate": literal(candidate), "backup": literal(backup),
        "status": literal(status), "authorization": literal(authorization), "readiness": literal(readiness),
        "newhash": literal(new_hash), "oldhash": literal(old_hash),
        "ownerpid": os.getpid(), "restart": "$true" if restart else "$false",
    }
    script = r"""
$ErrorActionPreference = 'Stop'
$target = %(target)s
$candidate = %(candidate)s
$backup = %(backup)s
$status = %(status)s
$authorization = %(authorization)s
$readiness = %(readiness)s
$newHash = %(newhash)s
$oldHash = %(oldhash)s
$ownerPid = %(ownerpid)s
$restart = %(restart)s
$state = 'failed'
$replaced = $false
function FileHash([string]$path) {
    $stream = [IO.File]::OpenRead($path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}
function WriteStatus([string]$value) {
    $tmp = $status + '.tmp'
    [IO.File]::WriteAllText($tmp, $value, [Text.Encoding]::ASCII)
    for ($i = 0; $i -lt 40; $i++) {
        try {
            [IO.File]::Replace($tmp, $status, [System.Management.Automation.Language.NullString]::Value)
            return
        } catch {
            if ($i -eq 39) { throw }
            [Threading.Thread]::Sleep(50)
        }
    }
}
function StartVerifiedTarget([string]$expectedHash, [string]$readyFile) {
    $stream = [IO.File]::Open($target, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $actual = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        if ($actual -ne $expectedHash) { return $null }
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = $target
        $start.WorkingDirectory = [IO.Path]::GetDirectoryName($target)
        $start.UseShellExecute = $false
        $start.EnvironmentVariables['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        if ($readyFile) { $start.EnvironmentVariables['MKPROFILER_UPDATE_READY'] = $readyFile }
        else { $start.EnvironmentVariables.Remove('MKPROFILER_UPDATE_READY') }
        $child = [Diagnostics.Process]::Start($start)
        if ($null -eq $child) { throw 'could not start target' }
        return $child
    } finally { $sha.Dispose(); $stream.Dispose() }
}
try {
    WriteStatus 'ready'
    try { $owner = [Diagnostics.Process]::GetProcessById($ownerPid) }
    catch { $owner = $null }
    if ($null -ne $owner) {
        try {
            if (-not $owner.WaitForExit(300000)) { $state = 'wait-timeout'; throw 'owner still running' }
        } finally { $owner.Dispose() }
    }
    if (-not [IO.File]::Exists($authorization) -or [IO.File]::ReadAllText($authorization) -ne 'authorized') {
        $state = 'not-authorized'; throw 'update not authorized'
    }
    if ((FileHash $target) -ne $oldHash) { $state = 'target-changed'; throw 'target changed' }
    if ((FileHash $candidate) -ne $newHash) { $state = 'candidate-changed'; throw 'candidate changed' }
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        try {
            [IO.File]::Replace($candidate, $target, $backup)
            $replaced = $true
            break
        } catch {
            $cause = $_.Exception
            while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
            $code = $cause.HResult -band 0xffff
            if ($code -notin @(32, 33) -or [IO.File]::Exists($backup) -or
                -not [IO.File]::Exists($target) -or $attempt -eq 119) { throw }
            [Threading.Thread]::Sleep(500)
        }
    }
    if ((FileHash $target) -ne $newHash) { throw 'replacement hash mismatch' }
    if ($restart) {
        try {
            $child = StartVerifiedTarget $newHash $readiness
            if ($null -eq $child) { throw 'target changed before restart' }
        } catch {
            $state = 'restart-failed'
            throw
        }
        $ready = $false
        try {
            $deadline = [DateTime]::UtcNow.AddSeconds(60)
            while ([DateTime]::UtcNow -lt $deadline) {
                if ([IO.File]::Exists($readiness)) {
                    try {
                        if ([IO.File]::ReadAllText($readiness) -eq 'ready') { $ready = $true; break }
                    } catch {}
                }
                if ($child.HasExited) { $state = 'startup-failed'; throw 'new application exited before becoming ready' }
                [Threading.Thread]::Sleep(200)
            }
        } finally { $child.Dispose() }
        if (-not $ready) { WriteStatus 'installed-unverified' }
        else { WriteStatus 'installed' }
    } else {
        WriteStatus 'installed'
    }
} catch {
    if ([IO.File]::Exists($backup)) {
        try {
            for ($attempt = 0; $attempt -lt 120; $attempt++) {
                try {
                    if (-not [IO.File]::Exists($target)) { [IO.File]::Move($backup, $target) }
                    elseif ($replaced -or (FileHash $target) -ne $oldHash) {
                        [IO.File]::Replace($backup, $target, [System.Management.Automation.Language.NullString]::Value)
                    }
                    break
                } catch {
                    $cause = $_.Exception
                    while ($null -ne $cause.InnerException) { $cause = $cause.InnerException }
                    $code = $cause.HResult -band 0xffff
                    if ($code -notin @(32, 33) -or $attempt -eq 119) { throw }
                    [Threading.Thread]::Sleep(500)
                }
            }
        } catch { $state = 'recovery-required' }
    }
    try { WriteStatus $state } catch {}
    if ($restart -and $state -ne 'not-authorized' -and $state -ne 'wait-timeout') {
        try { $old = StartVerifiedTarget $oldHash $null; if ($null -ne $old) { $old.Dispose() } } catch {}
    }
} finally {
    try { if ([IO.File]::Exists($candidate)) { [IO.File]::Delete($candidate) } } catch {}
    try { if ([IO.File]::Exists($authorization)) { [IO.File]::Delete($authorization) } } catch {}
    try { if ([IO.File]::Exists($readiness)) { [IO.File]::Delete($readiness) } } catch {}
    try { if ([IO.File]::Exists($status + '.tmp')) { [IO.File]::Delete($status + '.tmp') } } catch {}
}
""" % values
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _schedule_replacement(source, expected_hash, target, restart):
    powershell, system_dir = _powershell()
    token = uuid.uuid4().hex
    candidate = target.parent / (".MKProfiler-update-" + token + ".tmp")
    backup = target.parent / ("MKProfiler.exe.update-backup-" + token + ".bak")
    status = target.parent / ("MKProfiler.exe.update-status-" + token + ".txt")
    authorization = target.parent / (".MKProfiler-update-" + token + ".authorized")
    readiness = target.parent / (".MKProfiler-update-" + token + ".ready")
    candidate_created = False
    status_created = False
    helper = None
    try:
        old_hash = _hash_file(target)
        digest = hashlib.sha256()
        with open(source, "rb") as origin, open(candidate, "xb") as output:
            candidate_created = True
            for chunk in iter(lambda: origin.read(1024 * 1024), b""):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected_hash:
            raise UpdateError("Prepared executable changed after verification")
        _check_pe(candidate)
        with open(status, "x", encoding="utf-8") as output:
            status_created = True
            output.write("pending")
        command = _replacement_command(target, candidate, backup, status, authorization, readiness, expected_hash, old_hash, restart)
        helper = subprocess.Popen(
            [str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
            cwd=str(system_dir), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 10
        while True:
            try:
                state = status.read_text(encoding="ascii").strip()
            except (PermissionError, FileNotFoundError):
                state = "pending"
            if state == "ready":
                break
            if state != "pending" or helper.poll() is not None or time.monotonic() >= deadline:
                raise UpdateError("The update helper could not start")
            time.sleep(0.05)
        return PendingInstall(status, backup, old_hash, authorization)
    except BaseException as exc:
        if helper is not None and helper.poll() is None:
            helper.terminate()
            helper.wait(timeout=5)
        if candidate_created:
            candidate.unlink(missing_ok=True)
        if status_created:
            status.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise UpdateError("Cannot schedule the update; the installation may not be writable") from exc
        raise


def schedule_install(prepared, executable_path=None, restart=True):
    """Start a system helper, then the GUI must promptly exit to permit replacement.

    With no explicit target, only the running frozen MKProfiler.exe is eligible.
    Persist the returned backup details, then call authorize() before exiting;
    without authorization the helper does not replace the application.
    The status may be 'installed', 'installed-unverified', 'startup-failed',
    'restart-failed', 'not-authorized', 'failed', 'target-changed',
    'candidate-changed', 'wait-timeout', or 'recovery-required'. The previous
    executable is kept in backup_path when installation succeeds.
    Status reads can briefly fail while Windows replaces the status file;
    retry those reads. On failure, restart=True restarts the old executable
    only if its SHA256 still matches. No elevation or shell search is performed.
    """
    if not isinstance(prepared, PreparedUpdate) or not re.fullmatch(r"[0-9a-f]{64}", prepared.exe_sha256):
        raise UpdateError("Expected a verified prepared update")
    target = _target_executable(executable_path)
    return _schedule_replacement(prepared.executable, prepared.exe_sha256, target, restart)


def schedule_restore(backup_path, expected_sha256, executable_path=None, restart=True):
    """Schedule recovery; persist the new backup details and authorize before exiting."""
    target = _target_executable(executable_path)
    backup = Path(backup_path).absolute()
    expected = r"MKProfiler\.exe\.update-backup-[0-9a-f]{32}\.bak"
    try:
        if (backup.parent != target.parent or not re.fullmatch(expected, backup.name)
                or not backup.is_file() or backup.is_symlink()
                or backup.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise UpdateError("Backup must be a generated file in the installation directory")
        if (not isinstance(expected_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or _hash_file(backup) != expected_sha256):
            raise UpdateError("Backup SHA256 does not match the saved original")
        _check_pe(backup)
        return _schedule_replacement(backup, expected_sha256, target, restart)
    except OSError as exc:
        raise UpdateError("Cannot access the backup") from exc
