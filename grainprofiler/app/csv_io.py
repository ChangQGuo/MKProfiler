"""Read CSV files saved by the pipeline or common spreadsheet programs."""

from __future__ import annotations

import codecs
import csv
import hashlib
import os
import stat
import tempfile
from pathlib import Path

import pandas as pd


def _encodings(prefix: bytes) -> tuple[tuple[str, bytes], ...]:
    if prefix.startswith(codecs.BOM_UTF8):
        return (("utf-8", codecs.BOM_UTF8),)
    if prefix.startswith(codecs.BOM_UTF16_LE):
        return (("utf-16-le", codecs.BOM_UTF16_LE),)
    if prefix.startswith(codecs.BOM_UTF16_BE):
        return (("utf-16-be", codecs.BOM_UTF16_BE),)
    return (("utf-8", b""), ("gb18030", b""))


def ambiguous_csv_examples(data: bytes) -> tuple[str, str] | None:
    """Return differing previews when two unmarked encodings are both valid."""
    if len(_encodings(data[:4])) != 2 or data.isascii():
        return None
    try:
        utf8 = data.decode("utf-8")
        chinese = data.decode("gb18030")
    except UnicodeDecodeError:
        return None
    if utf8 == chinese:
        return None
    for left, right in zip(utf8.splitlines(), chinese.splitlines()):
        if left != right:
            return left[:180], right[:180]
    return utf8[:180], chinese[:180]


def ambiguous_csv_file(path: Path) -> tuple[str, str, str] | None:
    """Stream a CSV and return two previews and a fingerprint if its encoding is ambiguous."""
    with path.open("rb") as source:
        prefix = source.read(4)
        source.seek(0)
        if len(_encodings(prefix)) != 2:
            return None
        utf8 = codecs.getincrementaldecoder("utf-8")()
        chinese = codecs.getincrementaldecoder("gb18030")()
        digest = hashlib.sha256()
        examples = None
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            try:
                left = utf8.decode(block, final=False)
                right = chinese.decode(block, final=False)
            except UnicodeDecodeError:
                return None
            if examples is None and left != right:
                index = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
                start = max(0, index - 50)
                examples = (left[start:index + 100], right[start:index + 100])
        try:
            left = utf8.decode(b"", final=True)
            right = chinese.decode(b"", final=True)
        except UnicodeDecodeError:
            return None
        if examples is None and left != right:
            examples = (left[:180], right[:180])
        return (*examples, digest.hexdigest()) if examples else None


def csv_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_csv_bytes(data: bytes, encoding: str | None = None) -> tuple[str, str, bytes]:
    """Decode without replacement and return the encoding and BOM for saving."""
    candidates = _encodings(data[:4])
    if encoding is not None:
        candidates = tuple((name, bom) for name, bom in candidates if name == encoding)
        if not candidates:
            raise ValueError("Selected CSV encoding does not match the file's byte-order mark.")
    for candidate, bom in candidates:
        try:
            return data[len(bom):].decode(candidate), candidate, bom
        except UnicodeDecodeError as error:
            last_error = error
    raise last_error


def read_csv_compatible(path: str | Path, *, encoding: str | None = None, **kwargs) -> pd.DataFrame:
    """Try UTF encodings first, then the GB18030 encoding used by Chinese WPS."""
    if encoding is not None:
        return pd.read_csv(path, encoding=encoding, **kwargs)
    with open(path, "rb") as source:
        prefix = source.read(4)
    for encoding, bom in _encodings(prefix):
        pandas_encoding = "utf-16" if bom in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else (
            "utf-8-sig" if bom == codecs.BOM_UTF8 else encoding
        )
        try:
            return pd.read_csv(path, encoding=pandas_encoding, **kwargs)
        except UnicodeDecodeError as error:
            last_error = error
    raise last_error


def remove_csv_record(path: Path, column: str, value: str, *, encoding: str | None = None,
                      expected_sha256: str | None = None, expected_mtime: int | None = None) -> None:
    """Remove matching CSV rows without changing encoding or overwriting external edits."""
    digest = hashlib.sha256()
    original_mtime = path.stat().st_mtime_ns
    if expected_mtime is not None and original_mtime != expected_mtime:
        raise ValueError("The measurements CSV changed after its encoding was selected; reopen the folder.")
    with path.open("rb") as source:
        prefix = source.read(4)
        source.seek(0)
        candidates = _encodings(prefix)
        decoders = {name: codecs.getincrementaldecoder(name)() for name, _ in candidates}
        non_ascii = False
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            non_ascii = non_ascii or not block.isascii()
            for name, decoder in list(decoders.items()):
                try:
                    decoder.decode(block, final=False)
                except UnicodeDecodeError:
                    del decoders[name]
        for name, decoder in list(decoders.items()):
            try:
                decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                del decoders[name]
    if not decoders:
        raise ValueError("The measurements CSV encoding cannot be read safely.")
    if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
        raise ValueError("The measurements CSV changed after its encoding was selected; reopen the folder.")
    if encoding is not None and encoding not in decoders:
        raise ValueError("The selected measurements CSV encoding no longer matches the file.")
    if encoding is None and len(decoders) > 1 and non_ascii:
        raise ValueError("The measurements CSV encoding is ambiguous; save it as UTF-8 with BOM and reopen the folder.")
    encoding, bom = next((name, bom) for name, bom in candidates if name in decoders and (encoding is None or name == encoding))
    reader_encoding = "utf-16" if bom in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else (
        "utf-8-sig" if bom == codecs.BOM_UTF8 else encoding
    )
    temporary = None
    try:
        with path.open("r", encoding=reader_encoding, newline="") as source:
            rows = csv.reader(source)
            header = next(rows, None)
            if not header or len(header) != len(set(header)) or column not in header:
                raise ValueError("The measurements CSV has invalid headers.")
            column_index = header.index(column)
            with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline="", dir=path.parent,
                                             prefix=".mkprofiler-", delete=False) as target:
                temporary = Path(target.name)
                if bom:
                    target.write("\ufeff")
                newlines = source.newlines
                line_ending = "\r\n" if newlines == "\r\n" or isinstance(newlines, tuple) and "\r\n" in newlines else "\n"
                writer = csv.writer(target, lineterminator=line_ending)
                writer.writerow(header)
                removed = 0
                for row in rows:
                    if len(row) != len(header):
                        raise ValueError("The measurements CSV has a malformed row.")
                    if row[column_index] == value:
                        removed += 1
                    else:
                        writer.writerow(row)
                if not removed:
                    raise ValueError("The selected kernel was not found in measurements.csv.")
                target.flush()
                os.fsync(target.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        current = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                current.update(block)
        if current.digest() != digest.digest() or path.stat().st_mtime_ns != original_mtime:
            raise OSError("measurements.csv changed while saving; reopen the result folder.")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
