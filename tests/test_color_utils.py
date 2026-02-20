"""Tests for color utilities — extraction, conversion, and auto-mapping.

These tests don't require Inkscape to be running.
"""

import sys
import os
import math

import pytest
from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))

from inkmcpops.color_utils import (
    hex_to_rgb,
    rgb_to_hex,
    rgb_to_lab,
    hex_to_lab,
    delta_e,
    is_grayscale,
    color_lightness,
    normalize_color,
    extract_colors,
    extract_data_colors,
    auto_map_colors,
    analyze_colors,
)


def _parse_svg(svg_str):
    return etree.fromstring(svg_str.encode())


# ---------------------------------------------------------------------------
# Color conversion tests
# ---------------------------------------------------------------------------

class TestHexToRgb:
    def test_basic(self):
        assert hex_to_rgb("#ff0000") == (255, 0, 0)
        assert hex_to_rgb("#00ff00") == (0, 255, 0)
        assert hex_to_rgb("#0000ff") == (0, 0, 255)

    def test_shorthand(self):
        assert hex_to_rgb("#f00") == (255, 0, 0)
        assert hex_to_rgb("#abc") == (170, 187, 204)

    def test_no_hash(self):
        assert hex_to_rgb("ff0000") == (255, 0, 0)

    def test_black_white(self):
        assert hex_to_rgb("#000000") == (0, 0, 0)
        assert hex_to_rgb("#ffffff") == (255, 255, 255)

    def test_invalid(self):
        with pytest.raises(ValueError):
            hex_to_rgb("#xyz")


class TestRgbToHex:
    def test_basic(self):
        assert rgb_to_hex(255, 0, 0) == "#ff0000"
        assert rgb_to_hex(0, 255, 0) == "#00ff00"

    def test_lowercase(self):
        result = rgb_to_hex(170, 187, 204)
        assert result == "#aabbcc"


class TestRgbToLab:
    def test_black(self):
        L, a, b = rgb_to_lab(0, 0, 0)
        assert abs(L) < 0.1
        assert abs(a) < 0.1
        assert abs(b) < 0.1

    def test_white(self):
        L, a, b = rgb_to_lab(255, 255, 255)
        assert abs(L - 100.0) < 0.1

    def test_red_positive_a(self):
        L, a, b = rgb_to_lab(255, 0, 0)
        assert a > 50  # Red has high positive a*

    def test_green_negative_a(self):
        L, a, b = rgb_to_lab(0, 128, 0)
        assert a < -20  # Green has negative a*

    def test_blue_negative_b(self):
        L, a, b = rgb_to_lab(0, 0, 255)
        assert b < -50  # Blue has large negative b*


class TestDeltaE:
    def test_identical_colors(self):
        lab = hex_to_lab("#ff0000")
        assert delta_e(lab, lab) == 0.0

    def test_similar_colors_small_distance(self):
        lab1 = hex_to_lab("#ff0000")
        lab2 = hex_to_lab("#ff1111")
        assert delta_e(lab1, lab2) < 10

    def test_different_colors_large_distance(self):
        lab1 = hex_to_lab("#ff0000")
        lab2 = hex_to_lab("#0000ff")
        assert delta_e(lab1, lab2) > 50

    def test_black_white_max_distance(self):
        lab1 = hex_to_lab("#000000")
        lab2 = hex_to_lab("#ffffff")
        assert delta_e(lab1, lab2) > 90


# ---------------------------------------------------------------------------
# Color classification tests
# ---------------------------------------------------------------------------

class TestIsGrayscale:
    def test_black(self):
        assert is_grayscale("#000000") is True

    def test_white(self):
        assert is_grayscale("#ffffff") is True

    def test_mid_gray(self):
        assert is_grayscale("#808080") is True

    def test_light_gray(self):
        assert is_grayscale("#d3d3d3") is True

    def test_red_is_not_gray(self):
        assert is_grayscale("#ff0000") is False

    def test_blue_is_not_gray(self):
        assert is_grayscale("#2171b5") is False

    def test_near_black_is_gray(self):
        assert is_grayscale("#1a1a1a") is True


class TestColorLightness:
    def test_black_is_zero(self):
        assert color_lightness("#000000") < 1.0

    def test_white_is_hundred(self):
        assert color_lightness("#ffffff") > 99.0

    def test_mid_gray(self):
        L = color_lightness("#808080")
        assert 40 < L < 70


# ---------------------------------------------------------------------------
# Color normalization tests
# ---------------------------------------------------------------------------

class TestNormalizeColor:
    def test_hex_6digit(self):
        assert normalize_color("#FF0000") == "#ff0000"

    def test_hex_3digit(self):
        assert normalize_color("#F00") == "#ff0000"

    def test_named_color(self):
        assert normalize_color("red") == "#ff0000"
        assert normalize_color("steelblue") == "#4682b4"

    def test_rgb_function(self):
        assert normalize_color("rgb(255, 0, 0)") == "#ff0000"

    def test_none_values(self):
        assert normalize_color("none") is None
        assert normalize_color("transparent") is None
        assert normalize_color("inherit") is None

    def test_url_reference(self):
        assert normalize_color("url(#grad1)") is None

    def test_empty(self):
        assert normalize_color("") is None

    def test_invalid(self):
        assert normalize_color("not-a-color") is None


# ---------------------------------------------------------------------------
# Color extraction tests
# ---------------------------------------------------------------------------

SVG_WITH_COLORS = '''<svg xmlns="http://www.w3.org/2000/svg">
  <rect style="fill:#ff0000;stroke:#000000" width="100" height="100"/>
  <circle fill="#2171b5" stroke="none" cx="50" cy="50" r="20"/>
  <path style="fill:#ff0000;stroke:#333333" d="M 0,0 L 100,100"/>
  <text fill="black" x="0" y="0">Hello</text>
</svg>'''

SVG_MIXED = '''<svg xmlns="http://www.w3.org/2000/svg">
  <rect fill="#4682b4" width="50" height="200"/>
  <rect fill="#4682b4" width="50" height="150"/>
  <rect fill="#e6550d" width="50" height="180"/>
  <text fill="#000000" x="0" y="0">Label</text>
  <line stroke="#cccccc" x1="0" y1="0" x2="100" y2="0"/>
</svg>'''


class TestExtractColors:
    def test_finds_all_colors(self):
        root = _parse_svg(SVG_WITH_COLORS)
        colors = extract_colors(root)
        assert "#ff0000" in colors
        assert "#2171b5" in colors
        assert "#000000" in colors

    def test_counts_occurrences(self):
        root = _parse_svg(SVG_WITH_COLORS)
        colors = extract_colors(root)
        assert colors["#ff0000"] == 2  # Two elements with red fill

    def test_finds_style_and_attr_colors(self):
        root = _parse_svg(SVG_WITH_COLORS)
        colors = extract_colors(root)
        # #2171b5 from fill attribute, #333333 from style stroke
        assert "#2171b5" in colors
        assert "#333333" in colors


class TestExtractDataColors:
    def test_excludes_grayscale(self):
        root = _parse_svg(SVG_MIXED)
        data_colors = extract_data_colors(root)
        color_values = [c for c, _ in data_colors]
        assert "#4682b4" in color_values
        assert "#e6550d" in color_values
        assert "#000000" not in color_values
        assert "#cccccc" not in color_values

    def test_sorted_by_frequency(self):
        root = _parse_svg(SVG_MIXED)
        data_colors = extract_data_colors(root)
        # #4682b4 appears 2x, #e6550d appears 1x
        assert data_colors[0][0] == "#4682b4"
        assert data_colors[0][1] == 2

    def test_empty_svg(self):
        root = _parse_svg('<svg xmlns="http://www.w3.org/2000/svg"/>')
        data_colors = extract_data_colors(root)
        assert data_colors == []


# ---------------------------------------------------------------------------
# Auto color mapping tests
# ---------------------------------------------------------------------------

class TestAutoMapColors:
    def test_basic_mapping(self):
        found = [("#ff0000", 10), ("#0000ff", 5)]
        palette = ["#e6550d", "#2171b5", "#31a354"]
        mapping = auto_map_colors(found, palette)
        assert len(mapping) == 2
        # Red should map to orange (closest), blue to blue (closest)
        assert mapping["#ff0000"] == "#e6550d"
        assert mapping["#0000ff"] == "#2171b5"

    def test_empty_found(self):
        mapping = auto_map_colors([], ["#ff0000"])
        assert mapping == {}

    def test_empty_palette(self):
        mapping = auto_map_colors([("#ff0000", 1)], [])
        assert mapping == {}

    def test_more_colors_than_palette(self):
        found = [("#ff0000", 10), ("#00ff00", 8), ("#0000ff", 5), ("#ffff00", 3)]
        palette = ["#e6550d", "#2171b5"]
        mapping = auto_map_colors(found, palette)
        # First two get unique assignments, rest reuse closest
        assert len(mapping) >= 2

    def test_no_mapping_when_same(self):
        """Colors already in the palette should not appear in the mapping."""
        found = [("#2171b5", 10)]
        palette = ["#2171b5", "#e6550d"]
        mapping = auto_map_colors(found, palette)
        assert "#2171b5" not in mapping  # Same color, no mapping needed

    def test_perceptual_mapping(self):
        """Verify mapping uses perceptual distance, not simple value."""
        # Orange (#ffa500) should be closer to red palette (#e6550d) than blue (#2171b5)
        found = [("#ffa500", 5)]
        palette = ["#e6550d", "#2171b5"]
        mapping = auto_map_colors(found, palette)
        assert mapping.get("#ffa500") == "#e6550d"


# ---------------------------------------------------------------------------
# Full analysis tests
# ---------------------------------------------------------------------------

class TestAnalyzeColors:
    def test_basic_analysis(self):
        root = _parse_svg(SVG_MIXED)
        result = analyze_colors(root)
        assert "total_unique_colors" in result
        assert "data_colors" in result
        assert "grayscale_colors" in result
        assert result["total_unique_colors"] >= 3

    def test_analysis_with_palette(self):
        root = _parse_svg(SVG_MIXED)
        palette = ["#e6550d", "#2171b5", "#31a354"]
        result = analyze_colors(root, palette)
        assert "suggested_mapping" in result
        assert isinstance(result["suggested_mapping"], dict)
