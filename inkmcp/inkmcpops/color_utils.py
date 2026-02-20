"""Color extraction, analysis, and auto-mapping utilities.

Provides perceptual color distance (CIE76 deltaE in LAB space) and
automatic color mapping from SVG data colors to template palettes.
"""

import math
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from lxml import etree


# ---------------------------------------------------------------------------
# Named CSS colors (basic set for SVG parsing)
# ---------------------------------------------------------------------------

NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000",
    "green": "#008000", "blue": "#0000ff", "yellow": "#ffff00",
    "cyan": "#00ffff", "magenta": "#ff00ff", "orange": "#ffa500",
    "purple": "#800080", "pink": "#ffc0cb", "brown": "#a52a2a",
    "gray": "#808080", "grey": "#808080", "silver": "#c0c0c0",
    "navy": "#000080", "teal": "#008080", "maroon": "#800000",
    "olive": "#808000", "lime": "#00ff00", "aqua": "#00ffff",
    "fuchsia": "#ff00ff", "coral": "#ff7f50", "salmon": "#fa8072",
    "gold": "#ffd700", "khaki": "#f0e68c", "plum": "#dda0dd",
    "tan": "#d2b48c", "beige": "#f5f5dc", "ivory": "#fffff0",
    "indigo": "#4b0082", "violet": "#ee82ee", "crimson": "#dc143c",
    "tomato": "#ff6347", "steelblue": "#4682b4", "darkblue": "#00008b",
    "darkgreen": "#006400", "darkred": "#8b0000", "lightblue": "#add8e6",
    "lightgreen": "#90ee90", "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3",
    "darkgray": "#a9a9a9", "darkgrey": "#a9a9a9",
}


# ---------------------------------------------------------------------------
# Color conversion: hex → RGB → XYZ → LAB
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color string to RGB tuple (0-255)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB tuple to hex color string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_lab(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """Convert RGB (0-255) to CIE LAB color space.

    Uses D65 illuminant reference white.
    """
    # RGB to linear sRGB
    def linearize(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = linearize(r), linearize(g), linearize(b)

    # Linear sRGB to XYZ (D65)
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041

    # D65 reference white
    xn, yn, zn = 0.95047, 1.00000, 1.08883

    def f(t):
        delta = 6.0 / 29.0
        if t > delta ** 3:
            return t ** (1.0 / 3.0)
        return t / (3.0 * delta * delta) + 4.0 / 29.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)

    return L, a, b_val


def hex_to_lab(hex_color: str) -> Tuple[float, float, float]:
    """Convert hex color to LAB."""
    return rgb_to_lab(*hex_to_rgb(hex_color))


def delta_e(lab1: Tuple[float, float, float], lab2: Tuple[float, float, float]) -> float:
    """CIE76 color difference (Euclidean distance in LAB space)."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2)))


# ---------------------------------------------------------------------------
# Color classification
# ---------------------------------------------------------------------------

def is_grayscale(hex_color: str, threshold: float = 15.0) -> bool:
    """Check if a color is grayscale (including near-black/white).

    Uses chroma in LAB space. True grays have a=0, b=0.
    """
    try:
        L, a, b = hex_to_lab(hex_color)
        chroma = math.sqrt(a * a + b * b)
        return chroma < threshold
    except (ValueError, TypeError):
        return False


def color_lightness(hex_color: str) -> float:
    """Get perceptual lightness (L* from LAB, 0=black, 100=white)."""
    try:
        L, _, _ = hex_to_lab(hex_color)
        return L
    except (ValueError, TypeError):
        return 50.0


# ---------------------------------------------------------------------------
# Color extraction from SVG
# ---------------------------------------------------------------------------

_HEX_PATTERN = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}\b")
_RGB_FUNC_PATTERN = re.compile(
    r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)


def normalize_color(color_str: str) -> Optional[str]:
    """Normalize a color value to lowercase 6-digit hex, or None if invalid."""
    color_str = color_str.strip().lower()

    if not color_str or color_str in ("none", "transparent", "inherit", "currentcolor"):
        return None

    # Named color
    if color_str in NAMED_COLORS:
        return NAMED_COLORS[color_str]

    # Hex
    if color_str.startswith("#"):
        h = color_str.lstrip("#")
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        if len(h) == 6:
            try:
                int(h, 16)
                return f"#{h}"
            except ValueError:
                return None
        return None

    # rgb() function
    m = _RGB_FUNC_PATTERN.match(color_str)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if all(0 <= c <= 255 for c in (r, g, b)):
            return rgb_to_hex(r, g, b)

    # url() references (gradients, patterns) — not a simple color
    if color_str.startswith("url("):
        return None

    return None


def extract_colors(svg_root: etree._Element) -> Dict[str, int]:
    """Extract all colors used in SVG elements with occurrence counts.

    Parses fill and stroke from both style attributes and direct attributes.

    Returns:
        Dict of normalized hex color → occurrence count.
    """
    color_counter: Counter = Counter()

    for elem in svg_root.iter():
        if not isinstance(elem.tag, str):
            continue

        # Extract from style attribute
        style = elem.get("style", "")
        if style:
            for prop in ("fill", "stroke"):
                match = re.search(rf"{prop}\s*:\s*([^;]+)", style)
                if match:
                    normalized = normalize_color(match.group(1))
                    if normalized:
                        color_counter[normalized] += 1

        # Extract from direct attributes
        for attr in ("fill", "stroke"):
            val = elem.get(attr, "")
            if val:
                normalized = normalize_color(val)
                if normalized:
                    color_counter[normalized] += 1

    return dict(color_counter)


def extract_data_colors(
    svg_root: etree._Element,
    min_occurrences: int = 1,
) -> List[Tuple[str, int]]:
    """Extract non-grayscale colors likely representing data (not structure).

    Filters out grayscale colors (black, white, grays) which are typically
    used for text, axes, and backgrounds — not data.

    Returns:
        List of (hex_color, count) sorted by frequency descending.
    """
    all_colors = extract_colors(svg_root)
    data_colors = [
        (color, count)
        for color, count in all_colors.items()
        if not is_grayscale(color) and count >= min_occurrences
    ]
    return sorted(data_colors, key=lambda x: -x[1])


# ---------------------------------------------------------------------------
# Auto color mapping
# ---------------------------------------------------------------------------

def auto_map_colors(
    found_colors: List[Tuple[str, int]],
    palette: List[str],
) -> Dict[str, str]:
    """Create optimal color mapping from found data colors to template palette.

    Uses greedy assignment: for each found color (sorted by frequency),
    assign to the closest unused palette color by perceptual distance.

    Args:
        found_colors: List of (hex_color, count) sorted by frequency.
        palette: Target template palette hex colors.

    Returns:
        Dict mapping original hex color → palette hex color.
    """
    if not found_colors or not palette:
        return {}

    # Pre-compute LAB values for palette
    palette_labs = []
    for p in palette:
        try:
            palette_labs.append((p, hex_to_lab(p)))
        except ValueError:
            continue

    color_map = {}
    used_palette = set()

    for src_color, _count in found_colors:
        try:
            src_lab = hex_to_lab(src_color)
        except ValueError:
            continue

        # Find closest unused palette color
        best_dist = float("inf")
        best_match = None

        for p_hex, p_lab in palette_labs:
            if p_hex in used_palette:
                continue
            dist = delta_e(src_lab, p_lab)
            if dist < best_dist:
                best_dist = dist
                best_match = p_hex

        if best_match is None:
            # All palette colors used — reuse closest overall
            for p_hex, p_lab in palette_labs:
                dist = delta_e(src_lab, p_lab)
                if dist < best_dist:
                    best_dist = dist
                    best_match = p_hex

        if best_match and best_match != src_color:
            color_map[src_color] = best_match
            used_palette.add(best_match)

    return color_map


def analyze_colors(
    svg_root: etree._Element,
    template_palette: Optional[List[str]] = None,
) -> Dict:
    """Full color analysis of an SVG for reporting.

    Returns:
        Dict with all_colors, data_colors, grayscale_colors,
        and optionally suggested_mapping if template_palette provided.
    """
    all_colors = extract_colors(svg_root)
    data_colors = extract_data_colors(svg_root)
    grayscale = {c: n for c, n in all_colors.items() if is_grayscale(c)}

    result = {
        "total_unique_colors": len(all_colors),
        "all_colors": all_colors,
        "data_colors": [{"color": c, "count": n} for c, n in data_colors],
        "grayscale_colors": grayscale,
    }

    if template_palette:
        mapping = auto_map_colors(data_colors, template_palette)
        result["suggested_mapping"] = mapping

    return result
