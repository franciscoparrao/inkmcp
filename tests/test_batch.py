"""Tests for batch processing and matplotlib utilities.

These tests don't require Inkscape to be running.
"""

import sys
import os
import json
import tempfile
import shutil
from unittest import mock

import pytest
from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))

from inkmcpops.matplotlib_utils import (
    is_matplotlib_svg,
    cleanup_matplotlib_svg,
    _parse_dimension,
    _remove_background_rects,
    _remove_redundant_styles,
    _normalize_matplotlib_fonts,
)
from inkmcpops.batch_operations import (
    list_processable_files,
    batch_improve,
    batch_analyze,
    batch_watch,
    process_single_file,
    analyze_file,
    handle_batch_action,
    handle_analyze_action,
    handle_watch_action,
    _is_processable,
    _load_manifest,
    _save_manifest,
    _filter_changed_files,
)


# ---------------------------------------------------------------------------
# SVG fixtures
# ---------------------------------------------------------------------------

MINIMAL_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">
  <rect id="bg" x="0" y="0" width="800" height="600" style="fill:#ffffff"/>
  <text id="title" x="100" y="50" style="font-family:Arial;font-size:14px">Title</text>
  <rect id="bar1" x="100" y="100" width="50" height="200" style="fill:#4682b4"/>
</svg>'''

MATPLOTLIB_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     width="640" height="480" viewBox="0 0 640 480">
  <metadata>
    <rdf:RDF>
      <rdf:Description>
        <dc:creator>matplotlib version 3.8.2</dc:creator>
      </rdf:Description>
    </rdf:RDF>
  </metadata>
  <defs>
    <style type="text/css">
      *{stroke-linecap:butt;stroke-linejoin:round;}
      .DejaVu { font-family: DejaVu Sans; }
    </style>
  </defs>
  <rect id="figure_1" x="0" y="0" width="640" height="480" fill="#ffffff"/>
  <g id="axes_1">
    <rect id="patch_1" x="80" y="40" width="500" height="380" style="fill:#ffffff"/>
    <text id="text_1" x="320" y="30" style="font-family:DejaVu Sans;font-size:14px">Chart Title</text>
    <path id="line_1" d="M 100,200 L 200,150 L 300,180" style="fill:none;stroke:#1f77b4"/>
  </g>
</svg>'''

MATPLOTLIB_SVG_BY_IDS = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480">
  <g id="figure_1">
    <g id="axes_1">
      <rect id="patch_1" x="0" y="0" width="640" height="480" fill="white"/>
    </g>
  </g>
</svg>'''

NON_MATPLOTLIB_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
  <rect id="shape1" x="10" y="10" width="100" height="100" fill="blue"/>
  <circle id="shape2" cx="150" cy="150" r="30" fill="red"/>
</svg>'''


def _parse_svg(svg_str):
    """Parse SVG string into lxml element."""
    return etree.fromstring(svg_str.encode())


# ---------------------------------------------------------------------------
# Matplotlib detection tests
# ---------------------------------------------------------------------------

class TestIsMatplotlibSvg:
    """Tests for matplotlib SVG detection."""

    def test_detect_by_dc_creator(self):
        root = _parse_svg(MATPLOTLIB_SVG)
        assert is_matplotlib_svg(root) is True

    def test_detect_by_ids(self):
        root = _parse_svg(MATPLOTLIB_SVG_BY_IDS)
        assert is_matplotlib_svg(root) is True

    def test_non_matplotlib(self):
        root = _parse_svg(NON_MATPLOTLIB_SVG)
        assert is_matplotlib_svg(root) is False

    def test_minimal_svg(self):
        root = _parse_svg(MINIMAL_SVG)
        assert is_matplotlib_svg(root) is False

    def test_detect_by_comment_inside_svg(self):
        """Comment inside the SVG element is detected."""
        svg_with_comment = '''<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <!-- Created with matplotlib (version 3.8) -->
  <rect x="0" y="0" width="100" height="100"/>
</svg>'''
        root = _parse_svg(svg_with_comment)
        assert is_matplotlib_svg(root) is True


# ---------------------------------------------------------------------------
# Matplotlib cleanup tests
# ---------------------------------------------------------------------------

class TestCleanupMatplotlibSvg:
    """Tests for matplotlib SVG cleanup."""

    def test_removes_background_rect(self):
        root = _parse_svg(MATPLOTLIB_SVG)
        count = cleanup_matplotlib_svg(root)
        assert count > 0
        # The full-size white rect should be gone
        svg_ns = root.nsmap.get(None, "http://www.w3.org/2000/svg")
        bg_rects = []
        for rect in root.iter(f"{{{svg_ns}}}rect"):
            if rect.get("fill", "").lower() == "#ffffff":
                w = float(rect.get("width", "0"))
                h = float(rect.get("height", "0"))
                if w >= 600 and h >= 400:
                    bg_rects.append(rect)
        assert len(bg_rects) == 0

    def test_removes_style_block(self):
        root = _parse_svg(MATPLOTLIB_SVG)
        cleanup_matplotlib_svg(root)
        svg_ns = root.nsmap.get(None, "http://www.w3.org/2000/svg")
        styles = list(root.iter(f"{{{svg_ns}}}style"))
        assert len(styles) == 0

    def test_normalizes_fonts(self):
        root = _parse_svg(MATPLOTLIB_SVG)
        cleanup_matplotlib_svg(root)
        for elem in root.iter():
            style = elem.get("style", "")
            assert "DejaVu" not in style

    def test_returns_modification_count(self):
        root = _parse_svg(MATPLOTLIB_SVG)
        count = cleanup_matplotlib_svg(root)
        # Should have at least: 1 bg rect + 1 style + 1 font normalization
        assert count >= 3

    def test_no_modifications_on_clean_svg(self):
        root = _parse_svg(NON_MATPLOTLIB_SVG)
        count = cleanup_matplotlib_svg(root)
        assert count == 0


class TestRemoveBackgroundRects:
    """Tests for background rect removal."""

    def test_removes_full_size_white_rect(self):
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">
            <rect x="0" y="0" width="800" height="600" style="fill:#ffffff"/>
            <rect x="10" y="10" width="50" height="50" style="fill:blue"/>
        </svg>'''
        root = _parse_svg(svg)
        count = _remove_background_rects(root)
        assert count == 1

    def test_keeps_small_white_rects(self):
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">
            <rect x="10" y="10" width="50" height="50" style="fill:#ffffff"/>
        </svg>'''
        root = _parse_svg(svg)
        count = _remove_background_rects(root)
        assert count == 0

    def test_uses_viewbox_dimensions(self):
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480">
            <rect x="0" y="0" width="640" height="480" fill="#ffffff"/>
        </svg>'''
        root = _parse_svg(svg)
        count = _remove_background_rects(root)
        assert count == 1


class TestParseDimension:
    """Tests for dimension parsing."""

    def test_plain_number(self):
        assert _parse_dimension("100") == 100.0

    def test_with_px(self):
        assert _parse_dimension("100px") == 100.0

    def test_with_mm(self):
        assert _parse_dimension("50mm") == 50.0

    def test_empty(self):
        assert _parse_dimension("") == 0.0

    def test_invalid(self):
        assert _parse_dimension("abc") == 0.0

    def test_float(self):
        assert _parse_dimension("123.456") == 123.456


# ---------------------------------------------------------------------------
# Batch file listing tests
# ---------------------------------------------------------------------------

class TestListProcessableFiles:
    """Tests for file listing."""

    def test_list_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            for name in ["fig1.svg", "fig2.pdf", "readme.txt", "data.csv"]:
                open(os.path.join(tmpdir, name), "w").close()
            files = list_processable_files(tmpdir)
            basenames = [os.path.basename(f) for f in files]
            assert "fig1.svg" in basenames
            assert "fig2.pdf" in basenames
            assert "readme.txt" not in basenames
            assert "data.csv" not in basenames

    def test_comma_separated_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "a.svg")
            pdf_path = os.path.join(tmpdir, "b.pdf")
            open(svg_path, "w").close()
            open(pdf_path, "w").close()
            files = list_processable_files(f"{svg_path},{pdf_path}")
            assert len(files) == 2

    def test_single_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "fig.svg")
            open(svg_path, "w").close()
            files = list_processable_files(svg_path)
            assert len(files) == 1

    def test_pattern_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["fig_1.svg", "fig_2.svg", "chart.svg"]:
                open(os.path.join(tmpdir, name), "w").close()
            files = list_processable_files(tmpdir, "fig_*")
            basenames = [os.path.basename(f) for f in files]
            assert "fig_1.svg" in basenames
            assert "fig_2.svg" in basenames
            assert "chart.svg" not in basenames

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            files = list_processable_files(tmpdir)
            assert files == []

    def test_nonexistent_path(self):
        files = list_processable_files("/nonexistent/path")
        assert files == []


class TestIsProcessable:
    """Tests for file extension checking."""

    def test_svg(self):
        assert _is_processable("fig.svg") is True

    def test_pdf(self):
        assert _is_processable("fig.pdf") is True

    def test_png(self):
        assert _is_processable("fig.png") is False

    def test_txt(self):
        assert _is_processable("readme.txt") is False

    def test_uppercase(self):
        assert _is_processable("fig.SVG") is True

    def test_pdf_uppercase(self):
        assert _is_processable("fig.PDF") is True


# ---------------------------------------------------------------------------
# Batch processing tests (with mocked subprocess)
# ---------------------------------------------------------------------------

class TestProcessSingleFile:
    """Tests for single file processing."""

    def test_process_svg_file(self):
        """Process a simple SVG, apply template, verify output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write test SVG
            svg_path = os.path.join(tmpdir, "test.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            out_dir = os.path.join(tmpdir, "out")
            os.makedirs(out_dir)

            # Simple template code that just counts elements
            template_code = "modified = sum(1 for _ in svg.iter())"

            result = process_single_file(
                svg_path, out_dir, template_code, export_format="svg"
            )

            assert result["status"] == "ok"
            assert result["input"] == "test.svg"
            assert result["output"] == "test.svg"
            assert result["modifications"] > 0
            assert os.path.exists(os.path.join(out_dir, "test.svg"))

    def test_process_matplotlib_svg_auto_detect(self):
        """Auto-detect and clean matplotlib SVG."""
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "mpl_fig.svg")
            with open(svg_path, "w") as f:
                f.write(MATPLOTLIB_SVG)

            out_dir = os.path.join(tmpdir, "out")
            os.makedirs(out_dir)

            template_code = "modified = 0"

            result = process_single_file(
                svg_path, out_dir, template_code, export_format="svg"
            )

            assert result["status"] == "ok"
            assert result["matplotlib_detected"] is True
            assert result["modifications"] > 0

    def test_process_non_matplotlib_no_cleanup(self):
        """Non-matplotlib SVG should not trigger cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "normal.svg")
            with open(svg_path, "w") as f:
                f.write(NON_MATPLOTLIB_SVG)

            out_dir = os.path.join(tmpdir, "out")
            os.makedirs(out_dir)

            template_code = "modified = 0"

            result = process_single_file(
                svg_path, out_dir, template_code, export_format="svg"
            )

            assert result["status"] == "ok"
            assert result["matplotlib_detected"] is False
            assert result["modifications"] == 0

    @mock.patch("inkmcpops.batch_operations.subprocess.run")
    def test_process_pdf_calls_inkscape(self, mock_run):
        """PDF processing should call inkscape CLI for conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake PDF file
            pdf_path = os.path.join(tmpdir, "figure.pdf")
            with open(pdf_path, "w") as f:
                f.write("fake pdf")

            out_dir = os.path.join(tmpdir, "out")
            os.makedirs(out_dir)

            # Mock inkscape conversion: create SVG when called
            def side_effect(cmd, **kwargs):
                # Find the --export-filename arg to create the output file
                for arg in cmd:
                    if arg.startswith("--export-filename="):
                        out_path = arg.split("=", 1)[1]
                        if out_path.endswith(".svg"):
                            with open(out_path, "w") as f:
                                f.write(MINIMAL_SVG)
                        else:
                            open(out_path, "w").close()
                result = mock.Mock()
                result.returncode = 0
                result.stderr = ""
                return result

            mock_run.side_effect = side_effect

            template_code = "modified = 0"
            result = process_single_file(
                pdf_path, out_dir, template_code, export_format="pdf"
            )

            assert result["status"] == "ok"
            assert result["input"] == "figure.pdf"
            assert result["output"] == "figure.pdf"
            # Should have called inkscape twice: PDF->SVG and SVG->PDF
            assert mock_run.call_count == 2

    def test_template_code_has_svg_variable(self):
        """Verify that template code can access the svg root element."""
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "test.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            out_dir = os.path.join(tmpdir, "out")
            os.makedirs(out_dir)

            # Template code that modifies an element via svg variable
            template_code = '''
import re
modified = 0
for elem in svg.iter():
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
    if tag in ("text", "tspan"):
        style = elem.get("style", "")
        if style:
            style = re.sub(r"font-family:[^;]+", "font-family:Helvetica", style)
            elem.set("style", style)
            modified += 1
'''
            result = process_single_file(
                svg_path, out_dir, template_code, export_format="svg"
            )

            assert result["status"] == "ok"
            assert result["modifications"] >= 1

            # Verify the output SVG has the new font
            out_svg = os.path.join(out_dir, "test.svg")
            tree = etree.parse(out_svg)
            for elem in tree.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag == "text":
                    style = elem.get("style", "")
                    assert "Helvetica" in style


# ---------------------------------------------------------------------------
# Batch improve integration tests
# ---------------------------------------------------------------------------

class TestBatchImprove:
    """Tests for the batch_improve entry point."""

    def test_invalid_template(self):
        result = batch_improve("/tmp", "nonexistent_template")
        assert result["status"] == "error"
        assert "not found" in result["data"]["error"]

    def test_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = batch_improve(tmpdir, "nature", export_format="svg")
            assert result["status"] == "error"
            assert "No processable files" in result["data"]["error"]

    def test_batch_svg_files(self):
        """Process multiple SVG files with a real template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test SVGs
            for i in range(3):
                svg_path = os.path.join(tmpdir, f"fig{i}.svg")
                with open(svg_path, "w") as f:
                    f.write(MINIMAL_SVG)

            out_dir = os.path.join(tmpdir, "improved")
            result = batch_improve(
                tmpdir, "nature", output_dir=out_dir, export_format="svg"
            )

            assert result["status"] == "success"
            assert result["data"]["files_processed"] == 3
            assert result["data"]["batch_template"] == "nature"
            assert os.path.isdir(out_dir)

            # All output files should exist
            for fr in result["data"]["file_results"]:
                assert fr["status"] == "ok"
                assert os.path.exists(os.path.join(out_dir, fr["output"]))

    def test_batch_default_output_dir(self):
        """Default output dir should be 'improved/' inside input dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "fig.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            result = batch_improve(tmpdir, "nature", export_format="svg")
            assert result["status"] == "success"
            expected_dir = os.path.join(tmpdir, "improved")
            assert result["data"]["output_dir"] == expected_dir

    def test_batch_with_matplotlib_svgs(self):
        """Batch process with matplotlib detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # One matplotlib SVG and one normal
            mpl_path = os.path.join(tmpdir, "mpl.svg")
            with open(mpl_path, "w") as f:
                f.write(MATPLOTLIB_SVG)

            normal_path = os.path.join(tmpdir, "normal.svg")
            with open(normal_path, "w") as f:
                f.write(NON_MATPLOTLIB_SVG)

            result = batch_improve(tmpdir, "nature", export_format="svg")
            assert result["status"] == "success"
            assert result["data"]["files_processed"] == 2

            # Check matplotlib was detected on the right file
            file_results = {
                fr["input"]: fr for fr in result["data"]["file_results"]
            }
            assert file_results["mpl.svg"]["matplotlib_detected"] is True
            assert file_results["normal.svg"]["matplotlib_detected"] is False


# ---------------------------------------------------------------------------
# handle_batch_action tests
# ---------------------------------------------------------------------------

class TestHandleBatchAction:
    """Tests for the MCP server action handler."""

    def test_missing_path(self):
        result = handle_batch_action({"template": "nature"})
        assert result["status"] == "error"
        assert "path" in result["data"]["error"]

    def test_missing_template(self):
        result = handle_batch_action({"path": "/tmp"})
        assert result["status"] == "error"
        assert "template" in result["data"]["error"]

    def test_unsupported_format(self):
        result = handle_batch_action({
            "path": "/tmp",
            "template": "nature",
            "format": "gif",
        })
        assert result["status"] == "error"
        assert "gif" in result["data"]["error"]

    def test_valid_action(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "fig.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            result = handle_batch_action({
                "path": tmpdir,
                "template": "nature",
                "format": "svg",
            })
            assert result["status"] == "success"
            assert result["data"]["files_processed"] == 1


# ---------------------------------------------------------------------------
# Format response tests for batch results
# ---------------------------------------------------------------------------

class TestBatchFormatResponse:
    """Tests for batch response formatting."""

    def test_format_batch_success(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))
        from inkscape_mcp_server import format_response

        result = {
            "status": "success",
            "data": {
                "message": "Batch processing complete: 2 files processed",
                "files_processed": 2,
                "files_failed": 0,
                "batch_template": "nature",
                "output_dir": "/tmp/improved",
                "file_results": [
                    {"input": "fig1.svg", "output": "fig1.pdf", "status": "ok",
                     "matplotlib_detected": True, "modifications": 47},
                    {"input": "fig2.svg", "output": "fig2.pdf", "status": "ok",
                     "matplotlib_detected": False, "modifications": 23},
                ],
            },
        }
        text = format_response(result)
        assert "[OK]" in text
        assert "2" in text  # files_processed
        assert "nature" in text
        assert "fig1.svg" in text
        assert "matplotlib detected" in text
        assert "47 modifications" in text

    def test_format_batch_with_errors(self):
        from inkscape_mcp_server import format_response

        result = {
            "status": "success",
            "data": {
                "message": "Batch processing complete: 1 files processed, 1 failed",
                "files_processed": 1,
                "files_failed": 1,
                "batch_template": "science",
                "output_dir": "/tmp/out",
                "file_results": [
                    {"input": "ok.svg", "output": "ok.pdf", "status": "ok",
                     "matplotlib_detected": False, "modifications": 10},
                    {"input": "bad.svg", "status": "error", "error": "Parse failed"},
                ],
            },
        }
        text = format_response(result)
        assert "1" in text  # files_failed shows up
        assert "ERROR" in text
        assert "Parse failed" in text


# ---------------------------------------------------------------------------
# Dry-run / Analysis tests
# ---------------------------------------------------------------------------

class TestAnalyzeFile:
    """Tests for single file analysis (dry-run)."""

    def test_analyze_svg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "test.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            result = analyze_file(svg_path)
            assert result["status"] == "analyzed"
            assert result["total_elements"] > 0
            assert "element_counts" in result
            assert "color_analysis" in result
            assert result["matplotlib_detected"] is False

    def test_analyze_matplotlib_svg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "mpl.svg")
            with open(svg_path, "w") as f:
                f.write(MATPLOTLIB_SVG)

            result = analyze_file(svg_path)
            assert result["matplotlib_detected"] is True

    def test_analyze_with_palette(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "test.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            palette = ["#e6550d", "#2171b5", "#31a354"]
            result = analyze_file(svg_path, template_palette=palette)
            assert "suggested_mapping" in result["color_analysis"]


class TestBatchAnalyze:
    """Tests for batch analysis (dry-run)."""

    def test_basic_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["a.svg", "b.svg"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write(MINIMAL_SVG)

            result = batch_analyze(tmpdir)
            assert result["status"] == "success"
            assert result["data"]["files_analyzed"] == 2

    def test_analysis_with_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "fig.svg"), "w") as f:
                f.write(MINIMAL_SVG)

            result = batch_analyze(tmpdir, template_id="nature")
            assert result["status"] == "success"
            assert "aggregate_suggested_mapping" in result["data"]
            assert result["data"]["analysis_template"] == "nature"

    def test_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = batch_analyze(tmpdir)
            assert result["status"] == "error"

    def test_matplotlib_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "mpl.svg"), "w") as f:
                f.write(MATPLOTLIB_SVG)
            with open(os.path.join(tmpdir, "normal.svg"), "w") as f:
                f.write(NON_MATPLOTLIB_SVG)

            result = batch_analyze(tmpdir)
            assert result["data"]["matplotlib_count"] == 1


class TestHandleAnalyzeAction:
    """Tests for the analyze action handler."""

    def test_missing_path(self):
        result = handle_analyze_action({})
        assert result["status"] == "error"

    def test_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "fig.svg"), "w") as f:
                f.write(MINIMAL_SVG)

            result = handle_analyze_action({"path": tmpdir, "template": "nature"})
            assert result["status"] == "success"


# ---------------------------------------------------------------------------
# Incremental processing tests
# ---------------------------------------------------------------------------

class TestIncremental:
    """Tests for incremental (manifest-based) processing."""

    def test_manifest_save_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = {"/path/to/fig.svg": {"mtime": 12345.0, "hash": "abc"}}
            _save_manifest(tmpdir, manifest)
            loaded = _load_manifest(tmpdir)
            assert loaded["/path/to/fig.svg"]["mtime"] == 12345.0

    def test_manifest_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = _load_manifest(tmpdir)
            assert loaded == {}

    def test_filter_changed_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two files
            f1 = os.path.join(tmpdir, "a.svg")
            f2 = os.path.join(tmpdir, "b.svg")
            with open(f1, "w") as f:
                f.write(MINIMAL_SVG)
            with open(f2, "w") as f:
                f.write(MINIMAL_SVG)

            # Manifest says f1 was already processed at its current mtime
            manifest = {
                f1: {"mtime": os.path.getmtime(f1)},
            }
            changed = _filter_changed_files([f1, f2], manifest)
            assert f1 not in changed
            assert f2 in changed

    def test_incremental_batch(self):
        """First run processes all, second run skips unchanged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "fig.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            # First run
            result1 = batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"incremental": True},
            )
            assert result1["data"]["files_processed"] == 1

            # Second run — no changes
            result2 = batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"incremental": True},
            )
            assert result2["data"]["files_processed"] == 0

    def test_incremental_detects_changes(self):
        """After modifying a file, incremental should re-process it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            svg_path = os.path.join(tmpdir, "fig.svg")
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG)

            # First run
            batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"incremental": True},
            )

            # Modify file (touch with new content)
            import time
            time.sleep(0.05)  # Ensure mtime changes
            with open(svg_path, "w") as f:
                f.write(MINIMAL_SVG + "<!-- modified -->")

            # Second run should process the changed file
            result2 = batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"incremental": True},
            )
            assert result2["data"]["files_processed"] == 1


# ---------------------------------------------------------------------------
# Auto color mapping integration tests
# ---------------------------------------------------------------------------

class TestAutoColor:
    """Tests for auto_color option in batch_improve."""

    def test_auto_color_generates_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # SVG with distinct data colors
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
              <rect fill="#ff0000" width="50" height="100"/>
              <rect fill="#00ff00" width="50" height="100"/>
            </svg>'''
            with open(os.path.join(tmpdir, "fig.svg"), "w") as f:
                f.write(svg)

            result = batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"auto_color": True},
            )
            assert result["status"] == "success"
            assert "auto_color_map" in result["data"]
            color_map = result["data"]["auto_color_map"]
            assert len(color_map) >= 1


# ---------------------------------------------------------------------------
# Watch mode tests
# ---------------------------------------------------------------------------

class TestBatchWatch:
    """Tests for watch mode."""

    def test_watch_non_directory(self):
        result = batch_watch("/nonexistent", "nature")
        assert result["status"] == "error"

    def test_watch_short_duration(self):
        """Watch with very short duration should return quickly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "fig.svg"), "w") as f:
                f.write(MINIMAL_SVG)

            result = batch_watch(
                tmpdir, "nature", export_format="svg",
                interval=1, duration=2,
            )
            assert result["status"] == "success"
            assert result["data"]["watch_duration"] <= 5  # Some slack
            assert result["data"]["files_processed"] >= 1

    def test_handle_watch_missing_path(self):
        result = handle_watch_action({"template": "nature"})
        assert result["status"] == "error"

    def test_handle_watch_missing_template(self):
        result = handle_watch_action({"path": "/tmp"})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Report generation tests
# ---------------------------------------------------------------------------

class TestBatchReport:
    """Tests for HTML report generation."""

    def test_report_generated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "fig.svg"), "w") as f:
                f.write(MINIMAL_SVG)

            result = batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"report": True},
            )
            assert result["status"] == "success"
            report_path = result["data"].get("report_path")
            assert report_path is not None
            assert os.path.exists(report_path)

            # Verify it's valid HTML
            with open(report_path, "r") as f:
                html = f.read()
            assert "<!DOCTYPE html>" in html
            assert "Nature" in html

    def test_report_contains_file_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "chart.svg"), "w") as f:
                f.write(MINIMAL_SVG)

            result = batch_improve(
                tmpdir, "nature", export_format="svg",
                options={"report": True},
            )
            report_path = result["data"]["report_path"]
            with open(report_path, "r") as f:
                html = f.read()
            assert "chart.svg" in html


# ---------------------------------------------------------------------------
# Format response tests for new features
# ---------------------------------------------------------------------------

class TestNewFormatResponse:
    """Tests for format_response with new batch features."""

    def test_format_analysis(self):
        from inkscape_mcp_server import format_response

        result = {
            "status": "success",
            "data": {
                "message": "Analysis complete: 2 files analyzed",
                "files_analyzed": 2,
                "matplotlib_count": 1,
                "analysis_template": "nature",
                "aggregate_data_colors": [("#ff0000", 10), ("#0000ff", 5)],
                "aggregate_suggested_mapping": {"#ff0000": "#e6550d"},
                "file_analyses": [
                    {"file": "a.svg", "status": "analyzed", "total_elements": 10,
                     "matplotlib_detected": False,
                     "color_analysis": {"total_unique_colors": 3, "data_colors": [{"color": "#ff0000", "count": 5}]}},
                    {"file": "b.svg", "status": "analyzed", "total_elements": 20,
                     "matplotlib_detected": True,
                     "color_analysis": {"total_unique_colors": 5, "data_colors": [{"color": "#0000ff", "count": 3}]}},
                ],
            },
        }
        text = format_response(result)
        assert "analyzed" in text.lower()
        assert "#ff0000" in text
        assert "nature" in text
        assert "[matplotlib]" in text

    def test_format_watch(self):
        from inkscape_mcp_server import format_response

        result = {
            "status": "success",
            "data": {
                "message": "Watch complete: 3 files processed in 10s (2 cycles)",
                "files_processed": 3,
                "watch_duration": 10,
                "watch_cycles": 2,
                "batch_template": "nature",
                "output_dir": "/tmp/out",
            },
        }
        text = format_response(result)
        assert "10s" in text
        assert "2 cycles" in text

    def test_format_auto_color_map(self):
        from inkscape_mcp_server import format_response

        result = {
            "status": "success",
            "data": {
                "message": "Batch processing complete: 1 files processed",
                "files_processed": 1,
                "batch_template": "nature",
                "output_dir": "/tmp/out",
                "auto_color_map": {"#ff0000": "#e6550d", "#0000ff": "#2171b5"},
                "file_results": [],
            },
        }
        text = format_response(result)
        assert "#ff0000 -> #e6550d" in text
        assert "Auto color mapping" in text
