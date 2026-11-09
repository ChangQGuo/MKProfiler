"""Read CSV files saved by the pipeline or common spreadsheet programs."""

from __future__ import annotations

import codecs
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


def decode_csv_bytes(data: bytes) -> tuple[str, str, bytes]:
    """Decode without replacement and return the encoding and BOM for saving."""
    for encoding, bom in _encodings(data[:4]):
        try:
            return data[len(bom):].decode(encoding), encoding, bom
        except UnicodeDecodeError as error:
            last_error = error
    raise last_error


def read_csv_compatible(path: str | Path, **kwargs) -> pd.DataFrame:
    """Try UTF encodings first, then the GB18030 encoding used by Chinese WPS."""
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
