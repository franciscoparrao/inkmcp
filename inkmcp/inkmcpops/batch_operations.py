"""Batch processing operations for improving multiple SVG/PDF figures.

Processes multiple files with publication templates without requiring
Inkscape GUI or D-Bus. Uses lxml for SVG manipulation and the
inkscape CLI for PDF<->SVG conversion.

Features:
- Batch processing with publication templates
- Dry-run analysis mode (no modifications)
- Auto color mapping (perceptual distance)
- Incremental processing (skip unchanged files)
- Watch mode (poll for changes)
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from lxml import etree

from .color_utils import analyze_colors, auto_map_colors, extract_data_colors
from .common import create_success_response, create_error_response
from .matplotlib_utils import is_matplotlib_svg, cleanup_matplotlib_svg
from .template_operations import generate_apply_code, load_templates


# Supported file extensions
SVG_EXTENSIONS = {".svg"}
PDF_EXTENSIONS = {".pdf"}
PROCESSABLE_EXTENSIONS = SVG_EXTENSIONS | PDF_EXTENSIONS

MANIFEST_FILENAME = ".batch_manifest.json"


def list_processable_files(path: str, pattern: str = "") -> List[str]:
    """List SVG and PDF files in a directory or parse a comma-separated file list.

    Args:
        path: Directory path or comma-separated list of file paths.
        pattern: Optional glob-like filter (e.g., 'fig_*').

    Returns:
        List of absolute file paths.
    """
    files = []

    if "," in path:
        # Comma-separated list of files
        for f in path.split(","):
            f = f.strip()
            f = os.path.expanduser(f)
            if os.path.isfile(f) and _is_processable(f):
                files.append(os.path.abspath(f))
    elif os.path.isdir(path):
        for entry in sorted(os.listdir(path)):
            full = os.path.join(path, entry)
            if os.path.isfile(full) and _is_processable(full):
                if pattern:
                    import fnmatch
                    if not fnmatch.fnmatch(entry, pattern):
                        continue
                files.append(os.path.abspath(full))
    elif os.path.isfile(path) and _is_processable(path):
        files.append(os.path.abspath(path))

    return files


# ---------------------------------------------------------------------------
# Dry-run / Analysis
# ---------------------------------------------------------------------------

def analyze_file(filepath: str, template_palette: Optional[List[str]] = None) -> Dict[str, Any]:
    """Analyze a single SVG/PDF file without modifying it.

    Returns element counts, matplotlib detection, color analysis,
    and suggested color mapping if template_palette is provided.
    """
    basename = os.path.basename(filepath)
    name, ext = os.path.splitext(basename)
    ext = ext.lower()

    svg_path = filepath
    is_pdf = ext in PDF_EXTENSIONS
    temp_svg = None

    try:
        if is_pdf:
            temp_svg = os.path.join(
                tempfile.gettempdir(), f"analyze_{name}_{os.getpid()}.svg"
            )
            _pdf_to_svg(filepath, temp_svg)
            svg_path = temp_svg

        parser = etree.XMLParser(remove_blank_text=False, recover=True)
        tree = etree.parse(svg_path, parser)
        root = tree.getroot()

        # Element counts
        element_counts: Dict[str, int] = {}
        total_elements = 0
        for elem in root.iter():
            if not isinstance(elem.tag, str):
                continue
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            element_counts[tag] = element_counts.get(tag, 0) + 1
            total_elements += 1

        # Matplotlib detection
        matplotlib_detected = is_matplotlib_svg(root)

        # Color analysis
        color_info = analyze_colors(root, template_palette)

        # Document dimensions
        width = root.get("width", "?")
        height = root.get("height", "?")
        viewbox = root.get("viewBox", "")

        return {
            "file": basename,
            "file_type": ext.lstrip("."),
            "status": "analyzed",
            "dimensions": f"{width} x {height}",
            "viewBox": viewbox,
            "total_elements": total_elements,
            "element_counts": element_counts,
            "matplotlib_detected": matplotlib_detected,
            "color_analysis": color_info,
        }

    finally:
        if temp_svg and os.path.exists(temp_svg):
            os.unlink(temp_svg)


def batch_analyze(
    input_path: str,
    template_id: str = "",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyze multiple files without modifying them (dry-run).

    Args:
        input_path: Directory, single file, or comma-separated list.
        template_id: Optional template for color mapping suggestions.
        options: Optional dict with pattern filter.

    Returns:
        Standardized response with analysis results per file.
    """
    opts = options or {}
    input_path = os.path.expanduser(input_path)
    pattern = opts.get("pattern", "")
    files = list_processable_files(input_path, pattern)

    if not files:
        return create_error_response(
            f"No processable files (SVG/PDF) found at: {input_path}"
        )

    # Get template palette if specified
    template_palette = None
    if template_id:
        templates = load_templates()
        if template_id in templates:
            template_palette = templates[template_id].get("colors", {}).get("palette", [])

    file_analyses = []
    for filepath in files:
        try:
            analysis = analyze_file(filepath, template_palette)
            file_analyses.append(analysis)
        except Exception as e:
            file_analyses.append({
                "file": os.path.basename(filepath),
                "status": "error",
                "error": str(e),
            })

    # Aggregate summary
    total_mpl = sum(1 for a in file_analyses if a.get("matplotlib_detected"))
    total_ok = sum(1 for a in file_analyses if a.get("status") == "analyzed")

    # Collect all unique data colors across files
    all_data_colors: Dict[str, int] = {}
    for a in file_analyses:
        color_info = a.get("color_analysis", {})
        for dc in color_info.get("data_colors", []):
            c = dc["color"]
            all_data_colors[c] = all_data_colors.get(c, 0) + dc["count"]

    summary = f"Analysis complete: {total_ok} files analyzed"
    if total_mpl:
        summary += f", {total_mpl} matplotlib detected"

    result_data = {
        "files_analyzed": total_ok,
        "matplotlib_count": total_mpl,
        "file_analyses": file_analyses,
        "aggregate_data_colors": sorted(
            all_data_colors.items(), key=lambda x: -x[1]
        ),
    }

    if template_palette:
        # Aggregate suggested mapping across all files
        agg_colors = [(c, n) for c, n in all_data_colors.items()]
        agg_colors.sort(key=lambda x: -x[1])
        result_data["aggregate_suggested_mapping"] = auto_map_colors(
            agg_colors, template_palette
        )
        result_data["analysis_template"] = template_id

    return create_success_response(summary, **result_data)


# ---------------------------------------------------------------------------
# Batch improve (with auto-color and incremental support)
# ---------------------------------------------------------------------------

def batch_improve(
    input_path: str,
    template_id: str,
    output_dir: str = "",
    export_format: str = "pdf",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Process multiple SVG/PDF files with a publication template.

    Args:
        input_path: Directory, single file, or comma-separated file list.
        template_id: Template identifier (e.g., 'nature', 'science').
        output_dir: Output directory. Defaults to 'improved/' inside input dir.
        export_format: Output format: 'pdf', 'svg', or 'png'.
        options: Optional dict with:
            - cleanup_matplotlib: bool (default: auto-detect)
            - apply_fonts: bool (default: True)
            - apply_colors: bool (default: True)
            - color_map: dict of color remappings
            - auto_color: bool (default: False) - auto-detect and map colors
            - pattern: str glob filter for files
            - incremental: bool (default: False) - skip unchanged files
            - report: bool (default: False) - generate HTML report

    Returns:
        Standardized response with batch results.
    """
    opts = options or {}

    # Validate template exists
    templates = load_templates()
    if template_id not in templates:
        available = ", ".join(templates.keys())
        return create_error_response(
            f"Template '{template_id}' not found. Available: {available}"
        )

    template_data = templates[template_id]

    # Collect files
    input_path = os.path.expanduser(input_path)
    pattern = opts.get("pattern", "")
    files = list_processable_files(input_path, pattern)
    if not files:
        return create_error_response(
            f"No processable files (SVG/PDF) found at: {input_path}"
        )

    # Determine output directory
    if not output_dir:
        if os.path.isdir(input_path):
            output_dir = os.path.join(input_path, "improved")
        else:
            parent = os.path.dirname(files[0])
            output_dir = os.path.join(parent, "improved")
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Incremental: load manifest and filter unchanged files
    manifest = {}
    incremental = opts.get("incremental", False)
    if incremental:
        manifest = _load_manifest(output_dir)
        files = _filter_changed_files(files, manifest)
        if not files:
            return create_success_response(
                "Incremental: all files up to date, nothing to process",
                files_processed=0,
                files_skipped=len(manifest),
                batch_template=template_id,
                output_dir=output_dir,
            )

    # Auto color mapping: analyze all files first to build aggregate mapping
    auto_color = opts.get("auto_color", False)
    if auto_color and "color_map" not in opts:
        palette = template_data.get("colors", {}).get("palette", [])
        if palette:
            agg_data_colors: Dict[str, int] = {}
            for filepath in files:
                try:
                    root = _load_svg_root(filepath)
                    for color, count in extract_data_colors(root):
                        agg_data_colors[color] = agg_data_colors.get(color, 0) + count
                except Exception:
                    pass
            if agg_data_colors:
                sorted_colors = sorted(agg_data_colors.items(), key=lambda x: -x[1])
                opts["color_map"] = auto_map_colors(sorted_colors, palette)

    # Generate template code (with potential auto color_map)
    gen_opts = {}
    for key in ("apply_fonts", "apply_colors", "color_map"):
        if key in opts:
            gen_opts[key] = opts[key]
    gen_result = generate_apply_code(template_id, gen_opts)
    if gen_result.get("status") != "success":
        return gen_result
    template_code = gen_result["data"]["code"]

    # Optionally save "before" SVGs for report
    generate_report = opts.get("report", False)
    before_svgs = {}
    if generate_report:
        for filepath in files:
            try:
                root = _load_svg_root(filepath)
                before_svgs[filepath] = etree.tostring(root, encoding="unicode")
            except Exception:
                pass

    # Process files
    file_results = []
    errors = []
    cleanup_mpl = opts.get("cleanup_matplotlib", None)

    for filepath in files:
        try:
            result = process_single_file(
                filepath, output_dir, template_code, export_format, cleanup_mpl
            )
            file_results.append(result)
            # Update manifest
            if incremental:
                manifest[filepath] = {
                    "mtime": os.path.getmtime(filepath),
                    "hash": _file_hash(filepath),
                    "processed_at": time.time(),
                }
        except Exception as e:
            error_entry = {
                "input": os.path.basename(filepath),
                "status": "error",
                "error": str(e),
            }
            file_results.append(error_entry)
            errors.append(f"{os.path.basename(filepath)}: {e}")

    # Save manifest for incremental mode
    if incremental:
        _save_manifest(output_dir, manifest)

    successful = sum(1 for r in file_results if r.get("status") == "ok")
    failed = len(file_results) - successful

    summary = f"Batch processing complete: {successful} files processed"
    if failed:
        summary += f", {failed} failed"

    response_data = dict(
        files_processed=successful,
        files_failed=failed,
        file_results=file_results,
        batch_template=template_id,
        output_dir=output_dir,
        errors=errors if errors else None,
    )

    if opts.get("color_map") and auto_color:
        response_data["auto_color_map"] = opts["color_map"]

    # Generate HTML report
    if generate_report:
        try:
            from .batch_report import generate_report as gen_report
            report_path = gen_report(
                file_results, output_dir, template_id, template_data,
                before_svgs=before_svgs,
                color_map=opts.get("color_map"),
            )
            response_data["report_path"] = report_path
        except Exception as e:
            errors.append(f"Report generation failed: {e}")

    return create_success_response(summary, **response_data)


def process_single_file(
    input_path: str,
    output_dir: str,
    template_code: str,
    export_format: str = "pdf",
    cleanup_matplotlib: Optional[bool] = None,
) -> Dict[str, Any]:
    """Process a single SVG or PDF file with template code.

    Args:
        input_path: Path to input SVG or PDF.
        output_dir: Directory for output files.
        template_code: Python code string from generate_apply_code().
        export_format: Output format ('pdf', 'svg', 'png').
        cleanup_matplotlib: Force matplotlib cleanup. None = auto-detect.

    Returns:
        Dict with processing results for this file.
    """
    basename = os.path.basename(input_path)
    name, ext = os.path.splitext(basename)
    ext = ext.lower()

    svg_path = input_path
    is_pdf = ext in PDF_EXTENSIONS
    temp_svg = None

    try:
        # Convert PDF to SVG if needed
        if is_pdf:
            temp_svg = os.path.join(
                tempfile.gettempdir(), f"batch_{name}_{os.getpid()}.svg"
            )
            _pdf_to_svg(input_path, temp_svg)
            svg_path = temp_svg

        # Parse SVG
        parser = etree.XMLParser(remove_blank_text=False, recover=True)
        tree = etree.parse(svg_path, parser)
        root = tree.getroot()

        modifications = 0
        matplotlib_detected = False

        # Matplotlib detection and cleanup
        if cleanup_matplotlib is True or (
            cleanup_matplotlib is None and is_matplotlib_svg(root)
        ):
            matplotlib_detected = True
            modifications += cleanup_matplotlib_svg(root)

        # Apply template code
        exec_globals = {
            "svg": root,
            "re": re,
            "etree": etree,
            "__builtins__": __builtins__,
        }
        exec_locals = {}
        exec(template_code, exec_globals, exec_locals)
        modifications += exec_locals.get("modified", 0)

        # Write output
        out_ext = f".{export_format}" if export_format != "svg" else ".svg"
        out_name = f"{name}{out_ext}"
        out_path = os.path.join(output_dir, out_name)

        if export_format == "svg":
            _save_svg(root, out_path)
        else:
            # Save intermediate SVG, then convert
            intermediate = os.path.join(
                tempfile.gettempdir(), f"batch_{name}_out_{os.getpid()}.svg"
            )
            _save_svg(root, intermediate)
            try:
                _svg_to_format(intermediate, out_path, export_format)
            finally:
                if os.path.exists(intermediate):
                    os.unlink(intermediate)

        return {
            "input": basename,
            "output": out_name,
            "output_path": out_path,
            "status": "ok",
            "matplotlib_detected": matplotlib_detected,
            "modifications": modifications,
        }

    finally:
        if temp_svg and os.path.exists(temp_svg):
            os.unlink(temp_svg)


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

def batch_watch(
    input_path: str,
    template_id: str,
    output_dir: str = "",
    export_format: str = "pdf",
    options: Optional[Dict[str, Any]] = None,
    interval: int = 5,
    duration: int = 300,
) -> Dict[str, Any]:
    """Watch a directory and re-process changed files.

    Polls for file changes at the specified interval. Processes only
    files that changed since the last check. Runs for up to `duration`
    seconds before returning cumulative results.

    Args:
        input_path: Directory to watch.
        template_id: Template identifier.
        output_dir: Output directory.
        export_format: Output format.
        options: Same as batch_improve options.
        interval: Polling interval in seconds.
        duration: Maximum watch duration in seconds.

    Returns:
        Standardized response with cumulative watch results.
    """
    opts = options or {}
    opts["incremental"] = True  # Always incremental in watch mode
    input_path = os.path.expanduser(input_path)

    if not os.path.isdir(input_path):
        return create_error_response(
            "batch-watch requires a directory path. "
            f"'{input_path}' is not a directory."
        )

    # Determine output directory
    if not output_dir:
        output_dir = os.path.join(input_path, "improved")
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    start_time = time.time()
    total_processed = 0
    total_errors = 0
    all_results = []
    cycles = 0

    while time.time() - start_time < duration:
        cycles += 1
        result = batch_improve(
            input_path, template_id, output_dir, export_format, opts
        )

        if result.get("status") == "success":
            data = result.get("data", {})
            processed = data.get("files_processed", 0)
            failed = data.get("files_failed", 0)
            total_processed += processed
            total_errors += failed
            if processed > 0 or failed > 0:
                all_results.extend(data.get("file_results", []))

        remaining = duration - (time.time() - start_time)
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))

    elapsed = int(time.time() - start_time)

    return create_success_response(
        f"Watch complete: {total_processed} files processed in {elapsed}s ({cycles} cycles)",
        files_processed=total_processed,
        files_failed=total_errors,
        watch_duration=elapsed,
        watch_cycles=cycles,
        file_results=all_results if all_results else None,
        batch_template=template_id,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# Manifest for incremental processing
# ---------------------------------------------------------------------------

def _load_manifest(output_dir: str) -> Dict[str, Any]:
    """Load processing manifest from output directory."""
    manifest_path = os.path.join(output_dir, MANIFEST_FILENAME)
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_manifest(output_dir: str, manifest: Dict[str, Any]) -> None:
    """Save processing manifest to output directory."""
    manifest_path = os.path.join(output_dir, MANIFEST_FILENAME)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def _filter_changed_files(files: List[str], manifest: Dict[str, Any]) -> List[str]:
    """Filter to only files that changed since last processing."""
    changed = []
    for filepath in files:
        entry = manifest.get(filepath, {})
        if not entry:
            changed.append(filepath)
            continue
        # Check mtime
        try:
            current_mtime = os.path.getmtime(filepath)
            if current_mtime != entry.get("mtime"):
                changed.append(filepath)
        except OSError:
            changed.append(filepath)
    return changed


def _file_hash(filepath: str) -> str:
    """Compute MD5 hash of a file for change detection."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_processable(filepath: str) -> bool:
    """Check if a file has a processable extension."""
    _, ext = os.path.splitext(filepath)
    return ext.lower() in PROCESSABLE_EXTENSIONS


def _load_svg_root(filepath: str) -> etree._Element:
    """Load and parse an SVG file (converting from PDF if needed)."""
    name, ext = os.path.splitext(os.path.basename(filepath))
    ext = ext.lower()
    svg_path = filepath
    temp_svg = None

    try:
        if ext in PDF_EXTENSIONS:
            temp_svg = os.path.join(
                tempfile.gettempdir(), f"load_{name}_{os.getpid()}.svg"
            )
            _pdf_to_svg(filepath, temp_svg)
            svg_path = temp_svg

        parser = etree.XMLParser(remove_blank_text=False, recover=True)
        tree = etree.parse(svg_path, parser)
        return tree.getroot()
    finally:
        if temp_svg and os.path.exists(temp_svg):
            os.unlink(temp_svg)


def _pdf_to_svg(pdf_path: str, svg_path: str) -> None:
    """Convert PDF to SVG using inkscape CLI."""
    result = subprocess.run(
        [
            "inkscape",
            pdf_path,
            "--export-type=svg",
            f"--export-filename={svg_path}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PDF to SVG conversion failed: {result.stderr}")
    if not os.path.exists(svg_path):
        raise RuntimeError(f"PDF to SVG conversion produced no output: {svg_path}")


def _svg_to_format(svg_path: str, output_path: str, fmt: str) -> None:
    """Convert SVG to target format using inkscape CLI."""
    result = subprocess.run(
        [
            "inkscape",
            svg_path,
            f"--export-type={fmt}",
            f"--export-filename={output_path}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SVG to {fmt.upper()} conversion failed: {result.stderr}")


def _save_svg(root: etree._Element, path: str) -> None:
    """Save lxml SVG tree to file."""
    svg_bytes = etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )
    with open(path, "wb") as f:
        f.write(svg_bytes)


# ---------------------------------------------------------------------------
# MCP command handlers
# ---------------------------------------------------------------------------

def handle_batch_action(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Route batch-improve command from the MCP server."""
    input_path = attributes.get("path", "")
    if not input_path:
        return create_error_response(
            "batch-improve requires path parameter. "
            "Usage: batch-improve path=/dir/with/figures/ template=nature"
        )

    template_id = attributes.get("template", "")
    if not template_id:
        return create_error_response(
            "batch-improve requires template parameter. "
            "Usage: batch-improve path=/dir/ template=nature"
        )

    output_dir = attributes.get("output", "")
    export_format = attributes.get("format", "pdf")

    if export_format not in ("pdf", "svg", "png"):
        return create_error_response(
            f"Unsupported format: {export_format}. Use pdf, svg, or png."
        )

    options = {}
    for key, parse_bool in [
        ("cleanup_matplotlib", True),
        ("apply_fonts", True),
        ("apply_colors", True),
        ("auto_color", True),
        ("incremental", True),
        ("report", True),
    ]:
        if key in attributes:
            val = str(attributes[key]).lower()
            options[key] = val == "true" if parse_bool else attributes[key]
    if "pattern" in attributes:
        options["pattern"] = attributes["pattern"]

    color_map_str = attributes.get("color_map", "")
    if color_map_str:
        try:
            options["color_map"] = json.loads(color_map_str)
        except Exception:
            pass

    return batch_improve(input_path, template_id, output_dir, export_format, options)


def handle_analyze_action(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Route batch-analyze (dry-run) command from the MCP server."""
    input_path = attributes.get("path", "")
    if not input_path:
        return create_error_response(
            "batch-analyze requires path parameter. "
            "Usage: batch-analyze path=/dir/with/figures/ template=nature"
        )

    template_id = attributes.get("template", "")
    options = {}
    if "pattern" in attributes:
        options["pattern"] = attributes["pattern"]

    return batch_analyze(input_path, template_id, options)


def handle_watch_action(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Route batch-watch command from the MCP server."""
    input_path = attributes.get("path", "")
    if not input_path:
        return create_error_response(
            "batch-watch requires path parameter. "
            "Usage: batch-watch path=/dir/ template=nature"
        )

    template_id = attributes.get("template", "")
    if not template_id:
        return create_error_response(
            "batch-watch requires template parameter. "
            "Usage: batch-watch path=/dir/ template=nature"
        )

    output_dir = attributes.get("output", "")
    export_format = attributes.get("format", "pdf")
    interval = int(attributes.get("interval", "5"))
    duration = int(attributes.get("duration", "300"))

    if export_format not in ("pdf", "svg", "png"):
        return create_error_response(
            f"Unsupported format: {export_format}. Use pdf, svg, or png."
        )

    options = {}
    for key in ("cleanup_matplotlib", "auto_color"):
        if key in attributes:
            options[key] = str(attributes[key]).lower() == "true"

    return batch_watch(
        input_path, template_id, output_dir, export_format,
        options, interval, duration,
    )
