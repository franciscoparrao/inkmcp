"""Template operations module for applying publication styles."""

import json
import os
from typing import Dict, Any, List
from .common import create_success_response, create_error_response

# Path to built-in templates
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
STYLES_FILE = os.path.join(TEMPLATES_DIR, "styles.json")


def load_templates() -> Dict[str, Any]:
    """Load all available templates from the styles file."""
    if not os.path.exists(STYLES_FILE):
        return {}
    with open(STYLES_FILE, "r") as f:
        return json.load(f)


def list_templates() -> Dict[str, Any]:
    """List all available templates with descriptions."""
    templates = load_templates()
    if not templates:
        return create_error_response("No templates found")

    template_list = []
    for key, tmpl in templates.items():
        template_list.append({
            "id": key,
            "name": tmpl.get("name", key),
            "description": tmpl.get("description", ""),
            "palette": tmpl.get("colors", {}).get("palette", []),
        })

    return create_success_response(
        f"{len(template_list)} templates available",
        templates=template_list,
    )


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

    else:
        return create_error_response(f"Unknown template action: {action}")
