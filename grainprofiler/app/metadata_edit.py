"""Validate and persist explicit edits to sample metadata."""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import math
import os
import stat
import tempfile
from pathlib import Path

from grainprofiler.app.csv_io import ambiguous_csv_examples, decode_csv_bytes, decode_metadata_with_damaged_ocr


def _read_csv(path: Path, *, encoding: str | None = None, require_unambiguous: bool = False):
    original = path.read_bytes()
    if require_unambiguous and encoding is None and ambiguous_csv_examples(original):
        raise ValueError("The metadata CSV encoding is ambiguous. Reopen the result folder and select its encoding.")
    try:
        text, encoding, bom = decode_csv_bytes(original, encoding=encoding)
    except UnicodeDecodeError:
        if path.name != "metadata.csv" or encoding not in (None, "utf-8"):
            raise
        text, _ = decode_metadata_with_damaged_ocr(original)
        encoding, bom = "utf-8", codecs.BOM_UTF8
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows or len(set(rows[0])) != len(rows[0]):
        raise ValueError(f"Invalid or duplicate CSV headers: {path.name}")
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        raise ValueError(f"Malformed CSV row: {path.name}")
    return original, rows, encoding, bom, "\r\n" if "\r\n" in text else "\n"


def _encode_csv(rows, encoding, bom, newline):
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=newline).writerows(rows)
    return bom + output.getvalue().encode(encoding, errors="surrogateescape")


def _replace_files(changes):
    """Stage all files first; restore replaced files if a later replace fails."""
    staged = []
    replaced = []
    try:
        for path, original, updated in changes:
            mode = stat.S_IMODE(path.stat().st_mode) if original is not None else None
            with tempfile.NamedTemporaryFile(prefix=".mkprofiler-", dir=path.parent, delete=False) as handle:
                staged.append(Path(handle.name))
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(staged[-1], mode)
        for (path, original, updated), temporary in zip(changes, staged):
            current = path.read_bytes() if path.exists() else None
            if current != original:
                raise OSError(f"{path.name} changed since it was read; please reload it.")
            os.replace(temporary, path)
            replaced.append((path, original, updated))
    except Exception as error:
        rollback_errors = []
        for path, original, updated in reversed(replaced):
            try:
                if not path.exists() or path.read_bytes() != updated:
                    raise OSError("file changed during save; automatic restore refused")
                if original is None:
                    path.unlink()
                    continue
                mode = stat.S_IMODE(path.stat().st_mode)
                with tempfile.NamedTemporaryFile(prefix=".mkprofiler-rollback-", dir=path.parent, delete=False) as handle:
                    rollback = Path(handle.name)
                    staged.append(rollback)
                    handle.write(original)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(rollback, mode)
                os.replace(rollback, path)
            except OSError as rollback_error:
                rollback_errors.append(f"{path.name}: {rollback_error}")
        if rollback_errors:
            raise OSError(f"Save failed ({error}); restore failed: {'; '.join(rollback_errors)}") from error
        raise
    finally:
        for temporary in staged:
            temporary.unlink(missing_ok=True)


def save_metadata_edit(result_dir: str, image_name: str, key: str, value: str, expected: str,
                       *, metadata_encoding: str | None = None, metadata_digest: str | None = None,
                       mapping_encoding: str | None = None, mapping_digest: str | None = None,
                       metadata_mtime: int | None = None, mapping_mtime: int | None = None,
                       source_plant_name: str | None = None) -> str:
    """Save one confirmed edit, returning a warning when related IDs are ambiguous."""
    if key not in {"plant_name", "weight_g"}:
        raise ValueError("This metadata field cannot be edited.")
    value = value.strip()
    if not value or value == "—":
        raise ValueError("The value cannot be empty.")
    if key == "weight_g" and value != "-":
        try:
            weight = float(value)
        except ValueError as error:
            raise ValueError("Weight must be a finite non-negative number or '-' if unavailable.") from error
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("Weight must be a finite non-negative number or '-' if unavailable.")

    root = Path(result_dir)
    metadata_path = root / "metadata.csv"
    original, rows, encoding, bom, newline = _read_csv(
        metadata_path, encoding=metadata_encoding, require_unambiguous=True,
    )
    if ((metadata_digest is not None and hashlib.sha256(original).hexdigest() != metadata_digest)
            or (metadata_mtime is not None and metadata_path.stat().st_mtime_ns != metadata_mtime)):
        raise ValueError("The metadata.csv encoding selection is out of date; the file changed. Reopen the result folder.")
    header = rows[0]
    if "image_name" not in header or key not in header:
        raise ValueError("metadata.csv is missing the image or selected field.")
    image_col, value_col = header.index("image_name"), header.index(key)
    matches = [row for row in rows[1:] if row[image_col] == image_name]
    if len(matches) != 1:
        raise ValueError("Expected exactly one metadata row for this image.")
    row = matches[0]
    old = row[value_col]
    if old == expected or (expected == "—" and not old.strip()):
        unchanged_on_disk = True
    elif key == "weight_g":
        try:
            unchanged_on_disk = float(old) == float(expected)
        except ValueError:
            unchanged_on_disk = old == expected
    else:
        unchanged_on_disk = old == expected
    if not unchanged_on_disk:
        raise ValueError("The displayed value is out of date; reload the result folder.")

    changes = []
    warning = ""
    if key == "plant_name" and old != value:
        # Derived results retain the original identifier. Record the association
        # per image so a rename cannot display another plant's existing results.
        mapping_path = root / "metadata_original_plant_names.csv"
        columns = ["image_name", "source_plant_name", "current_plant_name"]
        if mapping_path.exists():
            map_original, mapping, map_encoding, map_bom, map_newline = _read_csv(
                mapping_path, encoding=mapping_encoding, require_unambiguous=True,
            )
            if ((mapping_digest is not None and hashlib.sha256(map_original).hexdigest() != mapping_digest)
                    or (mapping_mtime is not None and mapping_path.stat().st_mtime_ns != mapping_mtime)):
                raise ValueError("The original-name association changed; reopen the result folder.")
            if mapping[0] != columns:
                raise ValueError("Invalid metadata_original_plant_names.csv headers.")
        else:
            map_original, mapping, map_encoding, map_bom, map_newline = None, [columns], "utf-8", b"", "\n"
        map_matches = [entry for entry in mapping[1:] if entry[0] == image_name]
        if len(map_matches) > 1:
            raise ValueError("Duplicate image in metadata_original_plant_names.csv.")
        if map_matches:
            entry = map_matches[0]
            if entry[2] != old:
                raise ValueError("The metadata association is out of date; review the result folder.")
            entry[2] = value
        else:
            mapping.append([image_name, source_plant_name or "", value])
        # The application owns this association file. Mark its UTF-8 encoding
        # explicitly so future edits never need to guess between encodings.
        changes.append((mapping_path, map_original, _encode_csv(mapping, "utf-8", codecs.BOM_UTF8, map_newline)))
        warning = "Saved. Existing derived results keep their original plant ID; rerun the pipeline to update them."
    row[value_col] = value
    changes.insert(0, (metadata_path, original, _encode_csv(rows, encoding, bom, newline)))
    _replace_files(changes)
    return warning
