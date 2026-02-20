"""HTML report generator for batch processing results.

Generates a self-contained HTML file with before/after SVG previews,
color palettes, and modification summaries.
"""

import base64
import os
from datetime import datetime
from typing import Any, Dict, List, Optional


def generate_report(
    file_results: List[Dict[str, Any]],
    output_dir: str,
    template_id: str,
    template_data: Dict[str, Any],
    before_svgs: Optional[Dict[str, str]] = None,
    color_map: Optional[Dict[str, str]] = None,
) -> str:
    """Generate an HTML report for batch processing results.

    Args:
        file_results: List of per-file result dicts from batch_improve.
        output_dir: Output directory where processed files live.
        template_id: Template identifier used.
        template_data: Full template data dict.
        before_svgs: Optional dict of {filepath: svg_string} for before previews.
        color_map: Optional color mapping applied.

    Returns:
        Path to the generated HTML report.
    """
    before_svgs = before_svgs or {}
    palette = template_data.get("colors", {}).get("palette", [])
    template_name = template_data.get("name", template_id)

    # Build file cards
    cards_html = []
    for fr in file_results:
        cards_html.append(_build_file_card(fr, output_dir, before_svgs))

    # Build report HTML
    html = _REPORT_TEMPLATE.format(
        title=f"Batch Report: {template_name}",
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        template_name=template_name,
        template_id=template_id,
        total_files=len(file_results),
        successful=sum(1 for r in file_results if r.get("status") == "ok"),
        failed=sum(1 for r in file_results if r.get("status") != "ok"),
        palette_html=_build_palette_html(palette),
        color_map_html=_build_color_map_html(color_map) if color_map else "",
        cards="\n".join(cards_html),
        output_dir=output_dir,
    )

    report_path = os.path.join(output_dir, "batch_report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    return report_path


def _build_file_card(
    fr: Dict[str, Any],
    output_dir: str,
    before_svgs: Dict[str, str],
) -> str:
    """Build HTML card for a single file result."""
    filename = fr.get("input", "?")
    status = fr.get("status", "error")

    if status != "ok":
        return f'''
        <div class="card error">
            <h3>{filename}</h3>
            <p class="error-text">Error: {fr.get("error", "Unknown error")}</p>
        </div>'''

    mpl = fr.get("matplotlib_detected", False)
    mods = fr.get("modifications", 0)
    output_name = fr.get("output", "?")
    output_path = fr.get("output_path", os.path.join(output_dir, output_name))

    # Before preview
    before_html = ""
    # Find matching before SVG by input filename
    for orig_path, svg_str in before_svgs.items():
        if os.path.basename(orig_path) == filename or orig_path.endswith(filename):
            b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
            before_html = f'<img class="preview" src="data:image/svg+xml;base64,{b64}" alt="Before">'
            break

    # After preview — try to read output SVG
    after_html = ""
    after_svg_path = output_path
    if not after_svg_path.endswith(".svg"):
        # Try to find the SVG version
        svg_variant = os.path.splitext(output_path)[0] + ".svg"
        if os.path.exists(svg_variant):
            after_svg_path = svg_variant

    if after_svg_path.endswith(".svg") and os.path.exists(after_svg_path):
        try:
            with open(after_svg_path, "r", encoding="utf-8") as f:
                after_svg = f.read()
            b64 = base64.b64encode(after_svg.encode("utf-8")).decode("ascii")
            after_html = f'<img class="preview" src="data:image/svg+xml;base64,{b64}" alt="After">'
        except Exception:
            after_html = '<p class="no-preview">Preview not available</p>'

    mpl_badge = '<span class="badge mpl">matplotlib</span>' if mpl else ""

    return f'''
    <div class="card">
        <h3>{filename} {mpl_badge}</h3>
        <p>{mods} modifications &rarr; {output_name}</p>
        <div class="previews">
            <div class="preview-box">
                <h4>Before</h4>
                {before_html if before_html else '<p class="no-preview">No preview</p>'}
            </div>
            <div class="preview-box">
                <h4>After</h4>
                {after_html if after_html else '<p class="no-preview">No preview</p>'}
            </div>
        </div>
    </div>'''


def _build_palette_html(palette: List[str]) -> str:
    """Build palette swatch HTML."""
    if not palette:
        return "<p>No palette defined</p>"
    swatches = []
    for color in palette:
        swatches.append(
            f'<div class="swatch" style="background:{color}" title="{color}">'
            f'<span>{color}</span></div>'
        )
    return '<div class="palette">' + "".join(swatches) + "</div>"


def _build_color_map_html(color_map: Dict[str, str]) -> str:
    """Build color mapping visualization."""
    if not color_map:
        return ""
    rows = []
    for src, dst in color_map.items():
        rows.append(f'''
        <div class="map-row">
            <div class="swatch small" style="background:{src}" title="{src}">
                <span>{src}</span>
            </div>
            <span class="arrow">&rarr;</span>
            <div class="swatch small" style="background:{dst}" title="{dst}">
                <span>{dst}</span>
            </div>
        </div>''')
    return f'''
    <div class="color-map">
        <h3>Color Mapping (auto)</h3>
        {"".join(rows)}
    </div>'''


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_REPORT_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
           background: #f5f5f5; color: #333; padding: 2rem; }}
    .header {{ background: #fff; padding: 1.5rem 2rem; border-radius: 8px;
               box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 1.5rem; }}
    .header h1 {{ font-size: 1.5rem; margin-bottom: 0.5rem; }}
    .header .meta {{ color: #666; font-size: 0.875rem; }}
    .stats {{ display: flex; gap: 1rem; margin: 1rem 0; }}
    .stat {{ background: #f0f0f0; padding: 0.5rem 1rem; border-radius: 6px;
             font-size: 0.875rem; }}
    .stat strong {{ font-size: 1.25rem; display: block; }}
    .stat.error strong {{ color: #d32f2f; }}
    .palette {{ display: flex; gap: 4px; margin: 0.5rem 0; flex-wrap: wrap; }}
    .swatch {{ width: 60px; height: 40px; border-radius: 4px; display: flex;
               align-items: flex-end; justify-content: center; border: 1px solid rgba(0,0,0,0.1); }}
    .swatch span {{ font-size: 0.625rem; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.5);
                    padding: 2px; }}
    .swatch.small {{ width: 50px; height: 30px; }}
    .color-map {{ margin: 1rem 0; }}
    .map-row {{ display: flex; align-items: center; gap: 0.5rem; margin: 4px 0; }}
    .arrow {{ font-size: 1.25rem; color: #666; }}
    .cards {{ display: grid; gap: 1.5rem; }}
    .card {{ background: #fff; padding: 1.5rem; border-radius: 8px;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .card.error {{ border-left: 4px solid #d32f2f; }}
    .card h3 {{ font-size: 1.1rem; margin-bottom: 0.5rem; }}
    .badge {{ font-size: 0.7rem; padding: 2px 8px; border-radius: 10px;
              vertical-align: middle; font-weight: normal; }}
    .badge.mpl {{ background: #e3f2fd; color: #1565c0; }}
    .error-text {{ color: #d32f2f; }}
    .previews {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem; }}
    .preview-box {{ text-align: center; }}
    .preview-box h4 {{ font-size: 0.875rem; color: #666; margin-bottom: 0.5rem; }}
    .preview {{ max-width: 100%; max-height: 300px; border: 1px solid #e0e0e0;
                border-radius: 4px; background: #fff; }}
    .no-preview {{ color: #999; font-style: italic; padding: 2rem; }}
    .footer {{ margin-top: 2rem; text-align: center; color: #999; font-size: 0.75rem; }}
</style>
</head>
<body>
<div class="header">
    <h1>{title}</h1>
    <div class="meta">Generated: {timestamp} | Output: <code>{output_dir}</code></div>
    <div class="stats">
        <div class="stat"><strong>{total_files}</strong> Total files</div>
        <div class="stat"><strong>{successful}</strong> Processed</div>
        <div class="stat error"><strong>{failed}</strong> Failed</div>
    </div>
    <h3>Template: {template_name} <small>({template_id})</small></h3>
    {palette_html}
    {color_map_html}
</div>
<div class="cards">
{cards}
</div>
<div class="footer">
    Generated by InkscapeMCP batch processor
</div>
</body>
</html>'''
