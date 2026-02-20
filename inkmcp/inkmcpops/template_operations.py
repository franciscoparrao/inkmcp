"""Template operations module for applying publication styles."""

import json
import os
import re
from typing import Dict, Any, List, Optional
from .common import create_success_response, create_error_response

# Path to built-in templates
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
STYLES_FILE = os.path.join(TEMPLATES_DIR, "styles.json")

# User custom templates — separate file, never overwrites built-in
_USER_TEMPLATES_PATHS = [
    os.path.expanduser("~/.config/inkscape/extensions/inkmcp/user_templates.json"),
    os.path.expanduser("~/.config/inkmcp/user_templates.json"),
]


def _get_user_templates_file() -> str:
    """Return the first existing user templates path, or the primary default."""
    for p in _USER_TEMPLATES_PATHS:
        if os.path.exists(p):
            return p
    return _USER_TEMPLATES_PATHS[0]


def _load_builtin_templates() -> Dict[str, Any]:
    """Load built-in templates from styles.json."""
    if not os.path.exists(STYLES_FILE):
        return {}
    with open(STYLES_FILE, "r") as f:
        return json.load(f)


def _load_user_templates() -> Dict[str, Any]:
    """Load user custom templates."""
    path = _get_user_templates_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_user_templates(templates: Dict[str, Any]) -> str:
    """Save user templates to disk. Returns the path written."""
    path = _get_user_templates_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(templates, f, indent=2)
    return path


def load_templates() -> Dict[str, Any]:
    """Load all templates: built-in merged with user custom.

    User templates override built-in if they share the same ID.
    """
    templates = _load_builtin_templates()
    user = _load_user_templates()
    templates.update(user)
    return templates


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_VALID_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")


def _validate_template_id(template_id: str) -> Optional[str]:
    """Return error message if ID is invalid, else None."""
    if not template_id:
        return "Template ID cannot be empty"
    if not _VALID_ID_RE.match(template_id):
        return "Template ID must be alphanumeric with hyphens/underscores only"
    return None


def _validate_template_data(data: Dict[str, Any]) -> Optional[str]:
    """Return error message if template data is structurally invalid, else None."""
    if "name" not in data:
        return "Template must have a 'name' field"
    colors = data.get("colors", {})
    palette = colors.get("palette", [])
    if not palette:
        return "Template must have 'colors.palette' with at least one color"
    for c in palette:
        if not _HEX_COLOR_RE.match(c):
            return f"Invalid hex color in palette: {c}"
    return None


# ---------------------------------------------------------------------------
# Custom template CRUD
# ---------------------------------------------------------------------------

def save_template(
    template_id: str,
    template_data: Dict[str, Any],
    force: bool = False,
) -> Dict[str, Any]:
    """Save a custom template.

    Args:
        template_id: Unique identifier for the template.
        template_data: Template structure (name, colors, fonts, axes, etc.).
        force: If True, allow overriding a built-in template.

    Returns:
        Standardized response.
    """
    err = _validate_template_id(template_id)
    if err:
        return create_error_response(err)

    err = _validate_template_data(template_data)
    if err:
        return create_error_response(err)

    # Check if overriding built-in
    if not force:
        builtin = _load_builtin_templates()
        if template_id in builtin:
            user = _load_user_templates()
            if template_id not in user:
                return create_error_response(
                    f"'{template_id}' is a built-in template. "
                    "Use force=true to override it."
                )

    template_data["custom"] = True
    user_templates = _load_user_templates()
    user_templates[template_id] = template_data
    path = _save_user_templates(user_templates)

    return create_success_response(
        f"Template '{template_id}' saved",
        template_id=template_id,
        template_name=template_data.get("name", template_id),
        saved_to=path,
    )


def delete_template(template_id: str) -> Dict[str, Any]:
    """Delete a custom template. Cannot delete built-in templates.

    Args:
        template_id: Template identifier to delete.

    Returns:
        Standardized response.
    """
    user_templates = _load_user_templates()
    if template_id not in user_templates:
        builtin = _load_builtin_templates()
        if template_id in builtin:
            return create_error_response(
                f"'{template_id}' is a built-in template and cannot be deleted"
            )
        return create_error_response(f"Template '{template_id}' not found")

    del user_templates[template_id]
    _save_user_templates(user_templates)

    return create_success_response(f"Template '{template_id}' deleted")


def capture_template_from_svg(
    svg_root,
    template_id: str,
    name: str = "",
    description: str = "",
) -> Dict[str, Any]:
    """Analyze an SVG and generate a template from its visual style.

    Extracts dominant fonts, data colors, axis colors, and grid colors.

    Args:
        svg_root: lxml SVG root element.
        template_id: ID for the new template.
        name: Human-readable name.
        description: Description text.

    Returns:
        Standardized response with the captured template data.
    """
    from .color_utils import extract_data_colors, extract_colors, is_grayscale

    err = _validate_template_id(template_id)
    if err:
        return create_error_response(err)

    # --- Extract palette (non-grayscale data colors) ---
    data_colors = extract_data_colors(svg_root)
    palette = [c for c, _ in data_colors[:8]]  # top 8 data colors
    if not palette:
        return create_error_response(
            "No data colors found in SVG. Cannot capture template."
        )

    # --- Extract structural colors (grayscale: axis, grid, text) ---
    all_colors = extract_colors(svg_root)
    gray_colors = sorted(
        [(c, n) for c, n in all_colors.items() if is_grayscale(c)],
        key=lambda x: -x[1],
    )
    # Heuristic: darkest gray = axis/text, lighter gray = grid
    axis_color = "#000000"
    grid_color = "#e0e0e0"
    text_color = "#000000"
    from .color_utils import color_lightness
    for c, _ in gray_colors:
        L = color_lightness(c)
        if L < 30:
            axis_color = c
            text_color = c
        elif 50 < L < 85:
            grid_color = c

    # --- Extract dominant font ---
    font_counter: Dict[str, int] = {}
    size_counter: Dict[str, int] = {}
    for elem in svg_root.iter():
        if not isinstance(elem.tag, str):
            continue
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag not in ("text", "tspan"):
            continue
        style = elem.get("style", "")
        fm = re.search(r"font-family:\s*([^;]+)", style)
        if fm:
            font_counter[fm.group(1).strip()] = font_counter.get(fm.group(1).strip(), 0) + 1
        sm = re.search(r"font-size:\s*([^;]+)", style)
        if sm:
            size_counter[sm.group(1).strip()] = size_counter.get(sm.group(1).strip(), 0) + 1

    dominant_font = "Helvetica,Arial,sans-serif"
    if font_counter:
        dominant_font = max(font_counter, key=font_counter.get)

    dominant_size = "12px"
    if size_counter:
        dominant_size = max(size_counter, key=size_counter.get)

    template_data = {
        "name": name or template_id,
        "description": description or f"Template captured from SVG",
        "custom": True,
        "fonts": {
            "title": {"family": dominant_font, "size": "16px", "weight": "bold"},
            "axis_label": {"family": dominant_font, "size": dominant_size, "weight": "normal"},
            "tick_label": {"family": dominant_font, "size": "10px", "weight": "normal"},
            "legend": {"family": dominant_font, "size": "11px", "weight": "normal"},
            "annotation": {"family": dominant_font, "size": "10px", "weight": "normal"},
        },
        "colors": {
            "palette": palette,
            "background": "none",
            "grid": grid_color,
            "axis": axis_color,
            "text": text_color,
        },
        "axes": {
            "line_width": "0.75",
            "tick_width": "0.5",
            "grid_width": "0.3",
            "grid_style": "solid",
            "spines": ["bottom", "left"],
        },
        "bars": {
            "opacity": "0.9",
            "stroke_width": "0",
        },
    }

    return create_success_response(
        f"Template captured as '{template_id}'",
        template_id=template_id,
        template_data=template_data,
    )


def list_templates() -> Dict[str, Any]:
    """List all available templates with descriptions."""
    templates = load_templates()
    if not templates:
        return create_error_response("No templates found")

    template_list = []
    for key, tmpl in templates.items():
        entry = {
            "id": key,
            "name": tmpl.get("name", key),
            "description": tmpl.get("description", ""),
            "palette": tmpl.get("colors", {}).get("palette", []),
        }
        if tmpl.get("custom"):
            entry["custom"] = True
        template_list.append(entry)

    custom_count = sum(1 for t in template_list if t.get("custom"))
    msg = f"{len(template_list)} templates available"
    if custom_count:
        msg += f" ({custom_count} custom)"

    return create_success_response(msg, templates=template_list)


def get_template_info(template_id: str) -> Dict[str, Any]:
    """Get detailed info about a specific template."""
    templates = load_templates()
    if template_id not in templates:
        available = ", ".join(templates.keys())
        return create_error_response(
            f"Template '{template_id}' not found. Available: {available}"
        )

    tmpl = templates[template_id]
    return create_success_response(
        f"Template: {tmpl.get('name', template_id)}",
        template_id=template_id,
        **tmpl,
    )


def generate_apply_code(template_id: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
    """Generate Python code to apply a template to the current document.

    The generated code is meant to be executed via execute-code in the Inkscape extension.

    Args:
        template_id: Template identifier (e.g., 'nature', 'science')
        options: Optional overrides:
            - apply_fonts: bool (default True) - apply font changes
            - apply_colors: bool (default True) - apply color palette
            - apply_axes: bool (default True) - apply axis styling
            - color_map: dict - map original colors to palette colors
    """
    templates = load_templates()
    if template_id not in templates:
        available = ", ".join(templates.keys())
        return create_error_response(
            f"Template '{template_id}' not found. Available: {available}"
        )

    tmpl = templates[template_id]
    opts = options or {}
    apply_fonts = opts.get("apply_fonts", True)
    apply_colors = opts.get("apply_colors", True)

    code_parts = [
        "import re",
        f"template = {json.dumps(tmpl)}",
        "modified = 0",
    ]

    if apply_fonts:
        code_parts.append(_gen_font_code())

    if apply_colors:
        color_map = opts.get("color_map", {})
        if color_map:
            code_parts.append(_gen_color_map_code(color_map))
        code_parts.append(_gen_background_code())

    code_parts.append('print(f"Template applied: {modified} elements modified")')

    code = "\n".join(code_parts)

    return create_success_response(
        f"Generated apply code for template '{template_id}'",
        code=code,
        template_id=template_id,
        template_name=tmpl.get("name", template_id),
    )


def _gen_font_code() -> str:
    """Generate code to apply font styles from template."""
    return '''
fonts = template.get("fonts", {})
title_font = fonts.get("title", {})
default_family = title_font.get("family", "Helvetica,Arial,sans-serif")

for elem in svg.iter():
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
    if tag in ("text", "tspan"):
        style = elem.get("style", "")
        if style:
            style = re.sub(r"font-family:[^;]+", f"font-family:{default_family}", style)
            elem.set("style", style)
            modified += 1
'''


def _gen_color_map_code(color_map: Dict[str, str]) -> str:
    """Generate code to remap specific colors."""
    return f'''
color_map = {json.dumps(color_map)}
for elem in svg.iter():
    style = elem.get("style", "")
    if style:
        changed = False
        for old_color, new_color in color_map.items():
            if old_color.lower() in style.lower():
                style = re.sub(re.escape(old_color), new_color, style, flags=re.IGNORECASE)
                changed = True
        if changed:
            elem.set("style", style)
            modified += 1
'''


def _gen_background_code() -> str:
    """Generate code to make backgrounds transparent."""
    return '''
bg_color = template.get("colors", {}).get("background", "none")
if bg_color == "none":
    for elem in svg.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "rect":
            style = elem.get("style", "")
            w = elem.get("width", "0")
            h = elem.get("height", "0")
            try:
                is_full_width = float(str(w).replace("mm","").replace("px","")) > 500
                is_full_height = float(str(h).replace("mm","").replace("px","")) > 500
            except (ValueError, TypeError):
                is_full_width = False
                is_full_height = False
            if is_full_width and is_full_height and "fill:" in style:
                style = re.sub(r"fill:[^;]+", "fill:none", style)
                style = re.sub(r"stroke:[^;]+", "stroke:none", style)
                elem.set("style", style)
                modified += 1
'''


def handle_template_action(action: str, attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Route template-related actions.

    Supported actions:
        list-templates: List available templates
        get-template name=<id>: Get template details
        apply-template name=<id>: Generate code to apply template
        save-template name=<id> ...: Save a custom template
        delete-template name=<id>: Delete a custom template
    """
    if action == "list-templates":
        return list_templates()

    elif action == "get-template":
        name = attributes.get("name", "")
        if not name:
            return create_error_response("get-template requires name parameter")
        return get_template_info(name)

    elif action == "apply-template":
        name = attributes.get("name", "")
        if not name:
            return create_error_response("apply-template requires name parameter")

        options = {}
        if "apply_fonts" in attributes:
            options["apply_fonts"] = str(attributes["apply_fonts"]).lower() != "false"
        if "apply_colors" in attributes:
            options["apply_colors"] = str(attributes["apply_colors"]).lower() != "false"

        # Parse color_map if provided as JSON string
        color_map_str = attributes.get("color_map", "")
        if color_map_str:
            try:
                options["color_map"] = json.loads(color_map_str)
            except json.JSONDecodeError:
                pass

        return generate_apply_code(name, options)

    elif action == "save-template":
        name = attributes.get("name", "")
        if not name:
            return create_error_response("save-template requires name parameter")

        force = str(attributes.get("force", "false")).lower() == "true"

        # Build template data from attributes
        template_data: Dict[str, Any] = {}
        template_data["name"] = attributes.get("display_name", name)
        template_data["description"] = attributes.get("description", "")

        # Parse JSON sub-objects if provided
        for key in ("fonts", "colors", "axes", "bars"):
            raw = attributes.get(key, "")
            if raw:
                try:
                    template_data[key] = json.loads(raw) if isinstance(raw, str) else raw
                except json.JSONDecodeError:
                    return create_error_response(f"Invalid JSON for '{key}' field")

        # Shorthand: palette as comma-separated colors
        palette_str = attributes.get("palette", "")
        if palette_str and "colors" not in template_data:
            colors_list = [c.strip() for c in palette_str.split(",")]
            template_data["colors"] = {"palette": colors_list}
        elif palette_str:
            colors_list = [c.strip() for c in palette_str.split(",")]
            template_data["colors"]["palette"] = colors_list

        return save_template(name, template_data, force=force)

    elif action == "delete-template":
        name = attributes.get("name", "")
        if not name:
            return create_error_response("delete-template requires name parameter")
        return delete_template(name)

    else:
        return create_error_response(f"Unknown template action: {action}")
