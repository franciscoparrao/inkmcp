#!/usr/bin/env python3
"""
Inkscape MCP Server
Model Context Protocol server for controlling Inkscape via D-Bus extension

Provides access to Inkscape operations through a unified tool interface
for SVG element creation, document manipulation, and code execution.
"""

import json
import logging
import os
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Union

from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ImageContent

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("InkscapeMCP")

# Server configuration
DEFAULT_DBUS_SERVICE = "org.inkscape.Inkscape"
DEFAULT_DBUS_PATH = "/org/inkscape/Inkscape"
DEFAULT_DBUS_INTERFACE = "org.gtk.Actions"
DEFAULT_ACTION_NAME = "org.khema.inkscape.mcp"


class InkscapeConnection:
    """Manages D-Bus connection to Inkscape"""

    def __init__(self):
        self.dbus_service = DEFAULT_DBUS_SERVICE
        self.dbus_path = DEFAULT_DBUS_PATH
        self.dbus_interface = DEFAULT_DBUS_INTERFACE
        self.action_name = DEFAULT_ACTION_NAME
        self._client_path = Path(__file__).parent / "inkmcpcli.py"

    def is_available(self) -> bool:
        """Check if Inkscape is running and MCP extension is available"""
        try:
            cmd = [
                "gdbus",
                "call",
                "--session",
                "--dest",
                self.dbus_service,
                "--object-path",
                self.dbus_path,
                "--method",
                f"{self.dbus_interface}.List",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode != 0:
                logger.warning("Inkscape D-Bus service not available")
                return False

            # Check if our generic MCP extension action is listed
            output = result.stdout
            return self.action_name in output

        except Exception as e:
            logger.error(f"Error checking Inkscape availability: {e}")
            return False

    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute operation using CLI client"""
        try:
            # Write operation data to temporary file
            params_file = os.path.join(tempfile.gettempdir(), "mcp_params.json")

            with open(params_file, "w") as f:
                json.dump(operation_data, f)

            # Execute via D-Bus
            cmd = [
                "gdbus",
                "call",
                "--session",
                "--dest",
                self.dbus_service,
                "--object-path",
                self.dbus_path,
                "--method",
                f"{self.dbus_interface}.Activate",
                self.action_name,
                "[]",
                "{}",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.error(f"D-Bus command failed: {result.stderr}")
                return {
                    "status": "error",
                    "data": {"error": f"D-Bus call failed: {result.stderr}"},
                }

            # Read response from response file
            response_file = operation_data.get("response_file")
            if response_file and os.path.exists(response_file):
                try:
                    with open(response_file, "r") as f:
                        response_data = json.load(f)
                    os.remove(response_file)  # Clean up
                    return response_data
                except Exception as e:
                    logger.error(f"Failed to read response file: {e}")
                    return {
                        "status": "error",
                        "data": {"error": f"Response file error: {e}"},
                    }
            else:
                # Assume success if no response file specified
                return {"status": "success", "data": {"message": "Operation completed"}}

        except subprocess.TimeoutExpired:
            logger.error("Operation timed out")
            return {"status": "error", "data": {"error": "Operation timed out"}}
        except Exception as e:
            logger.error(f"Operation execution error: {e}")
            return {"status": "error", "data": {"error": str(e)}}


# Global connection instance
_inkscape_connection: Optional[InkscapeConnection] = None


def get_inkscape_connection() -> InkscapeConnection:
    """Get or create Inkscape connection"""
    global _inkscape_connection

    if _inkscape_connection is None:
        _inkscape_connection = InkscapeConnection()

    if not _inkscape_connection.is_available():
        raise Exception(
            "Inkscape is not running or generic MCP extension is not available. "
            "Please start Inkscape and ensure the generic MCP extension is installed."
        )

    return _inkscape_connection


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    logger.info("Inkscape MCP server starting up")

    try:
        # Test connection on startup
        try:
            get_inkscape_connection()
            logger.info("Successfully connected to Inkscape on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Inkscape on startup: {e}")
            logger.warning(
                "Make sure Inkscape is running with the generic MCP extension before using tools"
            )

        yield {}
    finally:
        logger.info("Inkscape MCP server shut down")


# Create the MCP server
mcp = FastMCP("InkscapeMCP", lifespan=server_lifespan)


def format_response(result: Dict[str, Any]) -> str:
    """Format operation result for clean AI client display"""
    if result.get("status") == "success":
        data = result.get("data", {})
        message = data.get("message", "Operation completed successfully")

        # Add relevant details based on operation type
        details = []

        # Element creation details
        if "id" in data:
            details.append(f"**ID**: `{data['id']}`")
        if "tag" in data:
            details.append(f"**Type**: {data['tag']}")

        # Document info details (get-info)
        if "dimensions" in data:
            dims = data["dimensions"]
            details.append(f"**Dimensions**: {dims.get('width', '?')} x {dims.get('height', '?')}")
        if "viewBox" in data:
            vb = data["viewBox"]
            if isinstance(vb, list):
                details.append(f"**viewBox**: {' '.join(str(v) for v in vb)}")
            else:
                details.append(f"**viewBox**: {vb}")
        if "elementCounts" in data:
            counts = data["elementCounts"]
            total = sum(counts.values())
            details.append(f"**Elements**: {total} total")
            # Show counts sorted by frequency
            for tag, count in sorted(counts.items(), key=lambda x: -x[1]):
                details.append(f"  {tag}: {count}")

        # Element info details (get-info-by-id)
        if "label" in data and data["label"]:
            details.append(f"**Label**: {data['label']}")
        if "attributes" in data and isinstance(data["attributes"], dict):
            details.append("**Attributes**:")
            for attr, val in data["attributes"].items():
                details.append(f"  {attr}: {val}")
        if "style" in data and isinstance(data["style"], dict):
            details.append("**Style**:")
            for prop, val in data["style"].items():
                details.append(f"  {prop}: {val}")

        # Template details (list-templates / get-template)
        if "templates" in data and isinstance(data["templates"], list):
            for tmpl in data["templates"]:
                palette_str = " ".join(tmpl.get("palette", [])[:4])
                custom_tag = " [custom]" if tmpl.get("custom") else ""
                details.append(f"  **{tmpl['id']}**{custom_tag} - {tmpl.get('description', '')} [{palette_str}]")
        if "palette" in data and isinstance(data["palette"], list):
            details.append(f"**Palette**: {' '.join(data['palette'])}")
        if "code" in data and "template_name" in data:
            details.append(f"**Template**: {data['template_name']}")
            details.append(f"**Code length**: {len(data['code'])} chars")

        # Custom template save/delete details
        if "saved_to" in data:
            details.append(f"**Saved to**: {data['saved_to']}")
        if "template_data" in data and isinstance(data["template_data"], dict):
            td = data["template_data"]
            if td.get("colors", {}).get("palette"):
                details.append(f"**Captured palette**: {' '.join(td['colors']['palette'][:6])}")

        # Selection/info details
        if "count" in data:
            details.append(f"**Count**: {data['count']}")
        if "elements" in data:
            elements = data["elements"]
            if elements:
                details.append(f"**Elements**: {len(elements)} items")
                # Show first few elements
                for i, elem in enumerate(elements[:3]):
                    elem_desc = (
                        f"{elem.get('tag', 'unknown')} ({elem.get('id', 'no-id')})"
                    )
                    details.append(f"  {i + 1}. {elem_desc}")
                if len(elements) > 3:
                    details.append(f"  ... and {len(elements) - 3} more")

        # Export details
        if "export_path" in data:
            details.append(f"**File**: {data['export_path']}")
        if "file_size" in data:
            details.append(f"**Size**: {data['file_size']} bytes")

        # Code execution details
        if "execution_successful" in data:
            if data["execution_successful"]:
                details.append("**Execution**: Success")
            else:
                details.append("**Execution**: Failed")
        if "output" in data and data["output"]:
            details.append(f"**Output**:\n```\n{data['output'].rstrip()}\n```")
        if "errors" in data and data["errors"]:
            details.append(f"**Errors**:\n```\n{data['errors'].rstrip()}\n```")
        if "return_value" in data and data["return_value"] is not None:
            details.append(f"**Return value**: {data['return_value']}")
        if "elements_created" in data and data["elements_created"]:
            details.append(f"**Created**: {len(data['elements_created'])} elements")
        if "local_variables" in data and data["local_variables"]:
            lv = data["local_variables"]
            details.append(f"**Variables**: {', '.join(lv.keys())}")

        # ID mapping (requested -> actual)
        if "id_mapping" in data and data["id_mapping"]:
            details.append("**Element IDs** (requested -> actual):")
            for requested_id, actual_id in data["id_mapping"].items():
                if requested_id == actual_id:
                    details.append(f"  {requested_id}")
                else:
                    details.append(
                        f"  {requested_id} -> {actual_id} (collision resolved)"
                    )

        # Batch processing details
        if "files_processed" in data:
            details.append(f"**Files processed**: {data['files_processed']}")
            if data.get("files_failed"):
                details.append(f"**Files failed**: {data['files_failed']}")
            if data.get("files_skipped"):
                details.append(f"**Files skipped** (unchanged): {data['files_skipped']}")
        if "batch_template" in data:
            details.append(f"**Template**: {data['batch_template']}")
        if "output_dir" in data:
            details.append(f"**Output directory**: {data['output_dir']}")
        if "auto_color_map" in data:
            details.append("**Auto color mapping**:")
            for src, dst in data["auto_color_map"].items():
                details.append(f"  {src} -> {dst}")
        if "report_path" in data:
            details.append(f"**Report**: {data['report_path']}")

        # Watch mode details
        if "watch_duration" in data:
            details.append(f"**Watch duration**: {data['watch_duration']}s ({data.get('watch_cycles', 0)} cycles)")

        if "file_results" in data and isinstance(data["file_results"], list):
            details.append("")
            for fr in data["file_results"]:
                if fr.get("status") == "ok":
                    mpl = " (matplotlib detected)" if fr.get("matplotlib_detected") else ""
                    details.append(
                        f"  {fr['input']} -> {fr['output']}{mpl}, {fr.get('modifications', 0)} modifications"
                    )
                else:
                    details.append(f"  {fr['input']} -> ERROR: {fr.get('error', '?')}")

        # Analysis (dry-run) details
        if "files_analyzed" in data:
            details.append(f"**Files analyzed**: {data['files_analyzed']}")
            if data.get("matplotlib_count"):
                details.append(f"**Matplotlib detected**: {data['matplotlib_count']} files")
        if "analysis_template" in data:
            details.append(f"**Template for mapping**: {data['analysis_template']}")
        if "aggregate_data_colors" in data and data["aggregate_data_colors"]:
            details.append("**Data colors found** (across all files):")
            for color, count in data["aggregate_data_colors"][:10]:
                details.append(f"  {color} ({count} occurrences)")
            if len(data["aggregate_data_colors"]) > 10:
                details.append(f"  ... and {len(data['aggregate_data_colors']) - 10} more")
        if "aggregate_suggested_mapping" in data and data["aggregate_suggested_mapping"]:
            details.append("**Suggested color mapping**:")
            for src, dst in data["aggregate_suggested_mapping"].items():
                details.append(f"  {src} -> {dst}")
        if "file_analyses" in data and isinstance(data["file_analyses"], list):
            details.append("")
            for fa in data["file_analyses"]:
                if fa.get("status") == "analyzed":
                    mpl = " [matplotlib]" if fa.get("matplotlib_detected") else ""
                    n_colors = fa.get("color_analysis", {}).get("total_unique_colors", 0)
                    n_data = len(fa.get("color_analysis", {}).get("data_colors", []))
                    details.append(
                        f"  {fa['file']}: {fa['total_elements']} elements, "
                        f"{n_colors} colors ({n_data} data){mpl}"
                    )
                else:
                    details.append(f"  {fa['file']}: ERROR: {fa.get('error', '?')}")

        # Warning for missing IDs
        if "generated_ids" in data and data["generated_ids"]:
            details.append("WARNING: Elements created without IDs")
            details.append(
                "For better scene management, always specify 'id' for elements:"
            )
            for gen_id in data["generated_ids"]:
                elem_type = "".join(c for c in gen_id if c.isalpha())
                details.append(f"  {gen_id} (use: {elem_type} id=my_name ...)")

        # Build final response
        is_code_failure = (
            "execution_successful" in data and not data["execution_successful"]
        )

        status = "FAILED" if is_code_failure else "OK"

        if details:
            return f"[{status}] {message}\n\n" + "\n".join(details)
        else:
            return f"[{status}] {message}"

    else:
        error = result.get("data", {}).get("error", "Unknown error")
        return f"[ERROR] {error}"


@mcp.tool()
def inkscape_operation(ctx: Context, command: str) -> Union[str, ImageContent]:
    """
    Execute any Inkscape operation using the extension system.

    CRITICAL SYNTAX RULES - READ CAREFULLY:
    1. Single string parameter with space-separated key=value pairs
    2. Children use special bracket syntax: children=[{tag attr=val attr=val}, {tag attr=val}]
    3. NOT JSON objects - use space-separated attributes inside braces
    4. Use 'svg' variable in execute-code, NOT 'self.svg'

    Parameter: command (str) - Command string following exact syntax below

    ═══ BASIC ELEMENTS ═══
    MANDATORY: Always specify id for every element to enable later modification:
    "rect id=main_rect x=100 y=50 width=200 height=100 fill=blue stroke=black stroke-width=2"
    "circle id=logo_circle cx=150 cy=150 r=75 fill=#ff0000"
    "text id=title_text x=50 y=100 text='Hello World' font-size=16 fill=black"

    ═══ AUTOMATIC ELEMENT PLACEMENT ═══
    The system automatically places elements in the correct SVG sections:
    - Basic elements (rect, circle, text, path, etc.) → placed directly in <svg>
    - Definitions (linearGradient, radialGradient, pattern, filter, inkscape:path-effect, etc.) → automatically placed in <defs>

    Path effects example (use inkscape: namespace for Inkscape-specific elements):
    "inkscape:path-effect id=effect1 effect=powerstroke is_visible=true lpeversion=1.3 scale_width=1 interpolator_type=CentripetalCatmullRom interpolator_beta=0.2 start_linecap_type=zerowidth end_linecap_type=zerowidth offset_points='0.2,0.5 | 1,0.5 | 1.8,0.5' linejoin_type=round miter_limit=4 not_jump=false sort_points=true" → automatically goes to <defs>
    "path id=mypath d='M 20,50 C 20,50 80,20 80,80' inkscape:path-effect=#effect1 inkscape:original-d='M 20,50 C 20,50 80,20 80,80'" → path with effect applied

    Filters example (nested primitives with children syntax):
    "filter id=grunge children=[{feTurbulence baseFrequency=2.5 numOctaves=3 result=noise}, {feColorMatrix in=noise type=saturate values=0}, {feComponentTransfer children=[{feFuncA type=discrete tableValues='0 0 .3 0 0 .7 0 0 1'}]}, {feComposite operator=out in=SourceGraphic in2=noise}]" → automatically goes to <defs>
    "rect id=grunge_rect x=100 y=100 width=100 height=100 fill=blue filter=url(#grunge)" → rectangle with grunge texture

    Patterns example (repeating graphics):
    "pattern id=dots width=20 height=20 patternUnits=userSpaceOnUse children=[{circle cx=10 cy=10 r=5 fill=red}]" → automatically goes to <defs>
    "rect id=patterned_rect x=100 y=100 width=100 height=100 fill=url(#dots)" → rectangle with dot pattern

    IMPORTANT: Create defs elements (gradients, patterns, filters) as SEPARATE commands, not as children of groups:
    ✅ CORRECT: "linearGradient id=grad1 ..." (separate command) → automatically goes to <defs>
    ✅ CORRECT: "rect id=shape fill=url(#grad1)" (separate command) → uses the gradient
    ❌ WRONG: "g children=[{linearGradient ...}, {rect ...}]" → this makes gradient stay inside group (not in defs!)

    ═══ NESTED ELEMENTS (Groups) ═══
    Groups with children - ALWAYS specify id for parent and ALL children:
    "g id=house children=[{rect id=house_body x=100 y=200 width=200 height=150 fill=#F5DEB3}, {path id=house_roof d='M 90,200 L 200,100 L 310,200 Z' fill=#A52A2A}]"

    ═══ CODE EXECUTION ═══
    Execute Python code - use 'svg' variable, not 'self.svg':
    CRITICAL: inkex elements require .set() method with string values, NOT constructor arguments!
    "execute-code code='rect = inkex.Rectangle(); rect.set(\"x\", \"100\"); rect.set(\"y\", \"100\"); rect.set(\"width\", \"100\"); rect.set(\"height\", \"100\"); rect.set(\"fill\", \"blue\"); svg.append(rect)'"
    "execute-code code='circle = inkex.Circle(); circle.set(\"cx\", \"150\"); circle.set(\"cy\", \"100\"); circle.set(\"r\", \"20\"); svg.append(circle)'"

    Single-line code (use semicolons for multiple statements):
    "execute-code code='for i in range(3): circle = inkex.Circle(); circle.set(\"cx\", str(i*50+100)); circle.set(\"cy\", \"100\"); circle.set(\"r\", \"20\"); svg.append(circle)'"

    Multiline code (MUST be properly quoted with single quotes):
    "execute-code code='for i in range(3):\n    circle = inkex.Circle()\n    circle.set(\"cx\", str(i*50+100))\n    circle.set(\"cy\", \"100\")\n    circle.set(\"r\", \"20\")\n    svg.append(circle)'"

    Finding and modifying elements by ID (use get_element_by_id helper):
    "execute-code code='el = get_element_by_id(\"house_body\"); el.set(\"fill\", \"brown\") if el else None'"

    ═══ INFO & EXPORT OPERATIONS ═══
    "get-selection" - Get info about selected objects
    "get-info" - Get document information
    "get-info-by-id id=element_id" - Get info about a specific element
    "export-document-image format=png return_base64=true" - Screenshot as base64 image
    "export-document-image format=pdf output_path=/tmp/output.pdf" - Export as PDF
    "export-document-image format=pdf output_path=/tmp/out.pdf area=drawing" - Export drawing area as PDF
    Supported export formats: png, pdf, eps, ps

    ═══ FILE OPERATIONS ═══
    "open-file path=/path/to/file.svg" - Open SVG/PDF file in Inkscape
    "open-file path=/path/to/figure.pdf" - Open PDF for editing

    ═══ PUBLICATION TEMPLATES ═══
    "list-templates" - List available publication style templates (built-in + custom)
    "get-template name=nature" - Get detailed info about a template
    "apply-template name=nature" - Apply Nature journal style to current document
    "apply-template name=science" - Apply Science/AAAS style
    "apply-template name=elsevier" - Apply Elsevier style
    "apply-template name=ieee" - Apply IEEE style (grayscale-safe)
    "apply-template name=colorblind_safe" - Apply colorblind-safe palette (Wong 2011)
    Options: apply_fonts=true/false apply_colors=true/false

    ═══ CUSTOM TEMPLATES ═══
    "save-template name=my_style palette=#e6550d,#2171b5,#31a354 description='My custom style'" - Save custom template with palette
    "save-template name=my_style fonts={...} colors={...} axes={...}" - Save with full JSON config
    "save-template name=nature force=true palette=#ff0000,#0000ff" - Override built-in (requires force)
    "delete-template name=my_style" - Delete a custom template (cannot delete built-in)

    ═══ BATCH PROCESSING ═══
    Process multiple SVG/PDF files with a template (no Inkscape GUI needed):
    "batch-improve path=/dir/with/figures/ template=nature format=pdf" - Process all SVG/PDF files
    "batch-improve path=/dir/ template=science output=/dir/improved/" - Custom output directory
    "batch-improve path=fig1.pdf,fig2.pdf template=colorblind_safe" - Specific files
    "batch-improve path=/dir/ template=nature auto_color=true" - Auto-detect and map colors to palette
    "batch-improve path=/dir/ template=nature incremental=true" - Skip unchanged files
    "batch-improve path=/dir/ template=nature report=true format=svg" - Generate HTML before/after report
    Options: format=pdf/svg/png, cleanup_matplotlib=true/false (auto-detected), auto_color, incremental, report

    ═══ BATCH ANALYSIS (dry-run) ═══
    Analyze files without modifying them — shows element counts, colors, matplotlib detection:
    "batch-analyze path=/dir/with/figures/" - Basic analysis
    "batch-analyze path=/dir/ template=nature" - Analysis with suggested color mapping to palette

    ═══ BATCH WATCH ═══
    Monitor directory and re-process changed files:
    "batch-watch path=/dir/ template=nature format=pdf" - Watch with defaults (5s interval, 300s duration)
    "batch-watch path=/dir/ template=nature interval=10 duration=600" - Custom timing

    ═══ GRADIENTS ═══
    Use gradientUnits=userSpaceOnUse with absolute coordinates matching your shape:
    "linearGradient id=grad1 x1=50 y1=50 x2=150 y2=50 gradientUnits=userSpaceOnUse children=[{stop offset=0% stop-color=red}, {stop offset=100% stop-color=blue}]"
    "rect id=shape x=50 y=50 width=100 height=100 fill=url(#grad1)"

    "radialGradient id=glow cx=200 cy=200 r=50 gradientUnits=userSpaceOnUse children=[{stop offset=0% stop-color=#fff}, {stop offset=100% stop-color=#f00}]"
    "circle id=glowing_circle cx=200 cy=200 r=50 fill=url(#glow)"

    ═══ ID MANAGEMENT ═══
    ALWAYS specify id for every element - this enables later modification and scene management:
    - Input: "g id=scene children=[{rect id=house x=0 y=0}, {circle id=sun cx=100 cy=50}]"
    - Returns: {"id_mapping": {"scene": "scene", "house": "house", "sun": "sun"}}
    - Collision handling: If "house" exists, creates "house_1" and returns {"house": "house_1"}

    ═══ SEMANTIC ORGANIZATION ═══
    Use hierarchical grouping with descriptive IDs whenever possible:

    Example - Creating a park scene with tree:
    "g id=park_scene children=[{g id=tree1 children=[{rect id=trunk1 x=100 y=200 width=20 height=60 fill=brown}, {circle id=foliage1_1 cx=110 cy=180 r=25 fill=green}, {circle id=foliage1_2 cx=105 cy=175 r=20 fill=darkgreen}]}, {g id=house children=[{rect id=house_body x=200 y=180 width=80 height=60 fill=beige}, {polygon id=house_roof points='195,180 240,150 285,180' fill=red}]}]"

    ID Naming Examples:
    - Scene Group: id=park_scene, id=city_view, id=landscape
    - Object Groups: id=tree1, id=tree2, id=house, id=car1
    - Parts: id=trunk1, id=house_body, id=car1_wheel_left
    - Sub-parts: id=foliage1_1, id=foliage1_2, id=house_window1

    Later Modification Examples (use get_element_by_id helper):
    - Change trunk color: execute-code code="el = get_element_by_id('trunk1'); el.set('fill', 'darkbrown') if el else None"
    - Move entire tree: execute-code code="el = get_element_by_id('tree1'); el.set('transform', 'translate(50,0)') if el else None"

    """
    response_file = None
    try:
        # Parse the command string using the same logic as our client
        from inkmcpcli import parse_command_string

        parsed_data = parse_command_string(command)
        tag = parsed_data.get("tag", "")

        # Handle commands that don't need D-Bus / Inkscape GUI
        if tag == "batch-improve":
            from inkmcpops.batch_operations import handle_batch_action
            result = handle_batch_action(parsed_data.get("attributes", {}))
            return format_response(result)

        if tag == "batch-analyze":
            from inkmcpops.batch_operations import handle_analyze_action
            result = handle_analyze_action(parsed_data.get("attributes", {}))
            return format_response(result)

        if tag == "batch-watch":
            from inkmcpops.batch_operations import handle_watch_action
            result = handle_watch_action(parsed_data.get("attributes", {}))
            return format_response(result)

        if tag in ("list-templates", "get-template", "save-template", "delete-template"):
            from inkmcpops.template_operations import handle_template_action
            result = handle_template_action(tag, parsed_data.get("attributes", {}))
            return format_response(result)

        # Commands below require Inkscape D-Bus connection
        connection = get_inkscape_connection()

        if tag == "apply-template":
            from inkmcpops.template_operations import handle_template_action
            gen_result = handle_template_action(tag, parsed_data.get("attributes", {}))
            if gen_result.get("status") != "success":
                return format_response(gen_result)
            # Execute the generated code in Inkscape
            code = gen_result["data"]["code"]
            parsed_data = {
                "tag": "execute-code",
                "attributes": {"code": code},
            }
            # Fall through to normal execution below

        # Handle open-file directly via D-Bus (no extension needed)
        if parsed_data.get("tag") == "open-file":
            file_path = parsed_data.get("attributes", {}).get("path", "")
            if not file_path:
                return "[ERROR] open-file requires path parameter. Usage: open-file path=/path/to/file.svg"
            file_path = os.path.expanduser(file_path)
            if not os.path.exists(file_path):
                return f"[ERROR] File not found: {file_path}"
            uri = f"file://{os.path.abspath(file_path)}"
            cmd = [
                "gdbus", "call", "--session",
                "--dest", connection.dbus_service,
                "--object-path", connection.dbus_path,
                "--method", "org.gtk.Application.Open",
                f"['{uri}']", "", "{}",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return f"[ERROR] Failed to open file: {result.stderr}"
            return f"[OK] Opened {file_path} in Inkscape"

        # Create unique response file for this operation
        response_fd, response_file = tempfile.mkstemp(
            suffix=".json", prefix="mcp_response_"
        )
        os.close(response_fd)

        # Add response file to the operation data
        parsed_data["response_file"] = response_file

        logger.info(f"Executing command: {command}")
        logger.debug(f"Parsed data: {parsed_data}")

        result = connection.execute_operation(parsed_data)

        # Handle image export special case
        if (
            parsed_data.get("tag") == "export-document-image"
            and result.get("status") == "success"
            and "base64_data" in result.get("data", {})
        ):
            # Return actual image for viewport screenshot
            base64_data = result["data"]["base64_data"]
            return ImageContent(type="image", data=base64_data, mimeType="image/png")

        # Format and return text response
        return format_response(result)

    except Exception as e:
        logger.error(f"Error in inkscape_operation: {e}")
        return f"❌ Operation failed: {str(e)}"
    finally:
        # Clean up response file if it exists
        if response_file and os.path.exists(response_file):
            try:
                os.remove(response_file)
            except OSError:
                pass


def main():
    """Run the Inkscape MCP server"""
    logger.info("Starting Inkscape MCP Server...")
    mcp.run()


if __name__ == "__main__":
    main()
