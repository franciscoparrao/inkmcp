"""Tests for the template system.

These tests don't require Inkscape to be running.
"""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))

from inkmcpops.template_operations import (
    load_templates,
    list_templates,
    get_template_info,
    generate_apply_code,
    handle_template_action,
)


class TestLoadTemplates:
    """Tests for template loading."""

    def test_load_returns_dict(self):
        result = load_templates()
        assert isinstance(result, dict)

    def test_known_templates_exist(self):
        templates = load_templates()
        assert "nature" in templates
        assert "science" in templates
        assert "elsevier" in templates
        assert "ieee" in templates
        assert "colorblind_safe" in templates

    def test_template_structure(self):
        templates = load_templates()
        for key, tmpl in templates.items():
            assert "name" in tmpl, f"{key} missing name"
            assert "description" in tmpl, f"{key} missing description"
            assert "fonts" in tmpl, f"{key} missing fonts"
            assert "colors" in tmpl, f"{key} missing colors"
            assert "axes" in tmpl, f"{key} missing axes"
            assert "palette" in tmpl["colors"], f"{key} missing palette"

    def test_palettes_have_colors(self):
        templates = load_templates()
        for key, tmpl in templates.items():
            palette = tmpl["colors"]["palette"]
            assert len(palette) >= 4, f"{key} palette too small: {len(palette)}"
            for color in palette:
                assert color.startswith("#"), f"{key} has non-hex color: {color}"


class TestListTemplates:
    """Tests for list-templates command."""

    def test_list_returns_success(self):
        result = list_templates()
        assert result["status"] == "success"

    def test_list_contains_templates(self):
        result = list_templates()
        templates = result["data"]["templates"]
        assert len(templates) >= 5

    def test_list_template_fields(self):
        result = list_templates()
        for tmpl in result["data"]["templates"]:
            assert "id" in tmpl
            assert "name" in tmpl
            assert "description" in tmpl
            assert "palette" in tmpl


class TestGetTemplateInfo:
    """Tests for get-template command."""

    def test_get_existing_template(self):
        result = get_template_info("nature")
        assert result["status"] == "success"
        assert result["data"]["template_id"] == "nature"
        assert "fonts" in result["data"]
        assert "colors" in result["data"]

    def test_get_nonexistent_template(self):
        result = get_template_info("nonexistent")
        assert result["status"] == "error"
        assert "not found" in result["data"]["error"]
        assert "nature" in result["data"]["error"]  # should list available


class TestGenerateApplyCode:
    """Tests for apply-template code generation."""

    def test_generate_code_success(self):
        result = generate_apply_code("nature")
        assert result["status"] == "success"
        assert "code" in result["data"]
        assert len(result["data"]["code"]) > 0

    def test_generated_code_is_valid_python(self):
        result = generate_apply_code("nature")
        code = result["data"]["code"]
        # Should parse without syntax errors
        compile(code, "<template>", "exec")

    def test_generate_code_nonexistent(self):
        result = generate_apply_code("nonexistent")
        assert result["status"] == "error"

    def test_generate_with_fonts_disabled(self):
        result = generate_apply_code("nature", {"apply_fonts": False})
        code = result["data"]["code"]
        assert "font-family" not in code

    def test_generate_with_color_map(self):
        result = generate_apply_code("nature", {
            "color_map": {"#4682b4": "#2171b5", "#ff6347": "#e6550d"}
        })
        code = result["data"]["code"]
        assert "color_map" in code
        assert "#4682b4" in code

    def test_all_templates_generate_valid_code(self):
        templates = load_templates()
        for key in templates:
            result = generate_apply_code(key)
            assert result["status"] == "success", f"Failed for {key}"
            code = result["data"]["code"]
            compile(code, f"<{key}>", "exec")


class TestHandleTemplateAction:
    """Tests for the action router."""

    def test_list_action(self):
        result = handle_template_action("list-templates", {})
        assert result["status"] == "success"

    def test_get_action(self):
        result = handle_template_action("get-template", {"name": "nature"})
        assert result["status"] == "success"

    def test_get_action_no_name(self):
        result = handle_template_action("get-template", {})
        assert result["status"] == "error"

    def test_apply_action(self):
        result = handle_template_action("apply-template", {"name": "science"})
        assert result["status"] == "success"
        assert "code" in result["data"]

    def test_apply_action_no_name(self):
        result = handle_template_action("apply-template", {})
        assert result["status"] == "error"

    def test_unknown_action(self):
        result = handle_template_action("unknown-action", {})
        assert result["status"] == "error"
