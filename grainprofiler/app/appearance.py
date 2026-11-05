"""Theme colours and font scaling shared by the viewer panels."""

from __future__ import annotations

import re


THEMES = {
    "dark": ("Dark", True, "#2B2B2B", {}),
    "light": ("Light", False, "#F5F5F5", {}),
    "navy": ("Deep blue", True, "#142334", {
        "#2b2b2b": "#142334", "#1a1a1a": "#101d2c", "#111": "#132334",
        "#0d0d0d": "#0d1927", "#151515": "#192b3e", "#222": "#20354b",
        "#252525": "#20354b", "#2a2a2a": "#28425b", "#333": "#29435d",
        "#323232": "#253a50", "#3a3a3a": "#29435d", "#4a4a4a": "#365873",
        "#444": "#46627c", "#555": "#57718a", "#666": "#68829a",
        "#777": "#718ba4", "#999": "#a0b5c8", "#aaa": "#b5c7d8",
        "#2c6fac": "#397eb5",
    }),
    "lavender": ("Soft lavender", False, "#F4F0FA", {
        "#f5f5f5": "#f4f0fa", "#fafafa": "#f8f4fc", "#fff": "#fffaff",
        "#f0f4f8": "#f1eaf8", "#e8e8e8": "#e8dff0", "#ececec": "#eee8f5",
        "#e0e0e0": "#e1d7eb", "#d0d0d0": "#d2c4df", "#ddd": "#d7cadf",
        "#ccc": "#cbbbd6", "#bbb": "#b9a7c8", "#aaa": "#ab96bb",
        "#222": "#30253a", "#555": "#62566d", "#666": "#74687f",
        "#2c6fac": "#71518f",
    }),
    "cream": ("Warm cream", False, "#FAF6E8", {
        "#f5f5f5": "#faf6e8", "#fafafa": "#fffbed", "#fff": "#fffdf5",
        "#f0f4f8": "#f7f1dd", "#e8e8e8": "#eee6cc", "#ececec": "#f1ead5",
        "#e0e0e0": "#ebe0c2", "#d0d0d0": "#dbcca9", "#ddd": "#ded3b6",
        "#ccc": "#cfc09c", "#bbb": "#bfaf89", "#aaa": "#b19d76",
        "#222": "#372f21", "#555": "#655b46", "#666": "#776a50",
        "#2c6fac": "#8b6b30",
    }),
}


def appearance_stylesheet(stylesheet: str, theme: str, font_size: int) -> str:
    """Apply the selected palette and scale the original CSS pixel sizes."""
    colours = THEMES[theme][3]
    stylesheet = re.sub(
        r"#[0-9a-fA-F]{6}(?![0-9a-fA-F])|#[0-9a-fA-F]{3}(?![0-9a-fA-F])",
        lambda match: colours.get(match.group().lower(), match.group()), stylesheet,
    )
    return re.sub(
        r"font-size:\s*(\d+)px",
        lambda match: f"font-size: {max(9, round(int(match.group(1)) * font_size / 14))}px",
        stylesheet,
    )
