"""Tests for the template system.

These tests don't require Inkscape to be running.
"""

import sys
import os
import json
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))

from inkmcpops.template_operations import (
    load_templates,
    list_templates,
    get_template_info,
    generate_apply_code,
    handle_template_action,
    save_template,
    delete_template,
    capture_template_from_svg,
    _load_builtin_templates,
    _load_user_templates,
    _save_user_templates,
    _get_user_templates_file,
    _validate_template_id,
    _validate_template_data,
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

    def test_save_action(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import inkmcpops.template_operations as top
            orig = top._USER_TEMPLATES_PATHS
            top._USER_TEMPLATES_PATHS = [os.path.join(tmpdir, "user_templates.json")]
            try:
                result = handle_template_action("save-template", {
                    "name": "test_style",
                    "palette": "#ff0000,#00ff00,#0000ff",
                })
                assert result["status"] == "success"
            finally:
                top._USER_TEMPLATES_PATHS = orig

    def test_save_action_no_name(self):
        result = handle_template_action("save-template", {})
        assert result["status"] == "error"

    def test_delete_action_no_name(self):
        result = handle_template_action("delete-template", {})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------

class TestValidation:
    """Tests for template validation helpers."""

    def test_valid_id(self):
        assert _validate_template_id("my_style") is None
        assert _validate_template_id("test-123") is None

    def test_invalid_id_empty(self):
        assert _validate_template_id("") is not None

    def test_invalid_id_special_chars(self):
        assert _validate_template_id("my style!") is not None

    def test_valid_data(self):
        data = {"name": "Test", "colors": {"palette": ["#ff0000"]}}
        assert _validate_template_data(data) is None

    def test_invalid_data_no_name(self):
        data = {"colors": {"palette": ["#ff0000"]}}
        assert _validate_template_data(data) is not None

    def test_invalid_data_no_palette(self):
        data = {"name": "Test", "colors": {}}
        assert _validate_template_data(data) is not None

    def test_invalid_data_bad_color(self):
        data = {"name": "Test", "colors": {"palette": ["notacolor"]}}
        assert _validate_template_data(data) is not None


# ---------------------------------------------------------------------------
# Custom template CRUD tests
# ---------------------------------------------------------------------------

class TestSaveTemplate:
    """Tests for saving custom templates."""

    def _with_temp_user_dir(self):
        """Context manager to redirect user templates to a temp dir."""
        import inkmcpops.template_operations as top
        tmpdir = tempfile.mkdtemp()
        orig = top._USER_TEMPLATES_PATHS
        top._USER_TEMPLATES_PATHS = [os.path.join(tmpdir, "user_templates.json")]
        return tmpdir, orig

    def _restore(self, orig):
        import inkmcpops.template_operations as top
        top._USER_TEMPLATES_PATHS = orig

    def test_save_valid_template(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            data = {
                "name": "My Style",
                "colors": {"palette": ["#e6550d", "#2171b5"]},
            }
            result = save_template("my_style", data)
            assert result["status"] == "success"
            assert result["data"]["template_id"] == "my_style"
            assert "saved_to" in result["data"]
        finally:
            self._restore(orig)

    def test_save_missing_name(self):
        data = {"colors": {"palette": ["#ff0000"]}}
        result = save_template("test", data)
        assert result["status"] == "error"

    def test_save_missing_palette(self):
        data = {"name": "Test"}
        result = save_template("test", data)
        assert result["status"] == "error"

    def test_save_invalid_id(self):
        data = {"name": "Test", "colors": {"palette": ["#ff0000"]}}
        result = save_template("bad id!", data)
        assert result["status"] == "error"

    def test_save_over_builtin_fails(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            data = {"name": "Override", "colors": {"palette": ["#ff0000"]}}
            result = save_template("nature", data, force=False)
            assert result["status"] == "error"
            assert "built-in" in result["data"]["error"]
        finally:
            self._restore(orig)

    def test_save_over_builtin_with_force(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            data = {"name": "My Nature", "colors": {"palette": ["#ff0000"]}}
            result = save_template("nature", data, force=True)
            assert result["status"] == "success"
        finally:
            self._restore(orig)

    def test_save_marks_custom_true(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            data = {"name": "Test", "colors": {"palette": ["#ff0000"]}}
            save_template("test_x", data)
            import inkmcpops.template_operations as top
            user = top._load_user_templates()
            assert user["test_x"]["custom"] is True
        finally:
            self._restore(orig)

    def test_overwrite_existing_custom(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            data1 = {"name": "V1", "colors": {"palette": ["#ff0000"]}}
            save_template("my_tmpl", data1)
            data2 = {"name": "V2", "colors": {"palette": ["#00ff00"]}}
            result = save_template("my_tmpl", data2)
            assert result["status"] == "success"
            import inkmcpops.template_operations as top
            user = top._load_user_templates()
            assert user["my_tmpl"]["name"] == "V2"
        finally:
            self._restore(orig)


class TestDeleteTemplate:
    """Tests for deleting custom templates."""

    def _with_temp_user_dir(self):
        import inkmcpops.template_operations as top
        tmpdir = tempfile.mkdtemp()
        orig = top._USER_TEMPLATES_PATHS
        top._USER_TEMPLATES_PATHS = [os.path.join(tmpdir, "user_templates.json")]
        return tmpdir, orig

    def _restore(self, orig):
        import inkmcpops.template_operations as top
        top._USER_TEMPLATES_PATHS = orig

    def test_delete_custom_template(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            data = {"name": "Temp", "colors": {"palette": ["#ff0000"]}}
            save_template("to_delete", data)
            result = delete_template("to_delete")
            assert result["status"] == "success"
            import inkmcpops.template_operations as top
            user = top._load_user_templates()
            assert "to_delete" not in user
        finally:
            self._restore(orig)

    def test_delete_builtin_fails(self):
        result = delete_template("nature")
        assert result["status"] == "error"
        assert "built-in" in result["data"]["error"]

    def test_delete_nonexistent_fails(self):
        tmpdir, orig = self._with_temp_user_dir()
        try:
            result = delete_template("no_such_template")
            assert result["status"] == "error"
            assert "not found" in result["data"]["error"]
        finally:
            self._restore(orig)


class TestCaptureTemplateFromSvg:
    """Tests for capturing a template from an SVG."""

    def test_capture_with_colors(self):
        from lxml import etree
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
          <rect fill="#e6550d" width="50" height="100"/>
          <rect fill="#2171b5" width="50" height="100"/>
          <text style="font-family:Georgia;font-size:14px" x="10" y="10">Title</text>
        </svg>'''
        root = etree.fromstring(svg.encode())
        result = capture_template_from_svg(root, "captured", name="My Captured")
        assert result["status"] == "success"
        td = result["data"]["template_data"]
        assert len(td["colors"]["palette"]) >= 2
        assert td["custom"] is True
        assert td["name"] == "My Captured"

    def test_capture_no_data_colors(self):
        from lxml import etree
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
          <rect fill="#ffffff" width="200" height="200"/>
          <rect fill="#000000" width="100" height="100"/>
        </svg>'''
        root = etree.fromstring(svg.encode())
        result = capture_template_from_svg(root, "empty_cap")
        assert result["status"] == "error"
        assert "No data colors" in result["data"]["error"]

    def test_capture_invalid_id(self):
        from lxml import etree
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#ff0000"/></svg>'
        root = etree.fromstring(svg.encode())
        result = capture_template_from_svg(root, "bad id!")
        assert result["status"] == "error"


class TestLoadTemplatesMerge:
    """Tests for merging built-in and user templates."""

    def test_builtin_loaded(self):
        builtin = _load_builtin_templates()
        assert "nature" in builtin

    def test_user_override(self):
        import inkmcpops.template_operations as top
        tmpdir = tempfile.mkdtemp()
        orig = top._USER_TEMPLATES_PATHS
        top._USER_TEMPLATES_PATHS = [os.path.join(tmpdir, "user_templates.json")]
        try:
            data = {"name": "User Nature", "custom": True, "colors": {"palette": ["#ff0000"]}}
            top._save_user_templates({"nature": data})
            merged = load_templates()
            assert merged["nature"]["name"] == "User Nature"
            assert merged["nature"]["custom"] is True
        finally:
            top._USER_TEMPLATES_PATHS = orig

    def test_custom_flag_in_list(self):
        import inkmcpops.template_operations as top
        tmpdir = tempfile.mkdtemp()
        orig = top._USER_TEMPLATES_PATHS
        top._USER_TEMPLATES_PATHS = [os.path.join(tmpdir, "user_templates.json")]
        try:
            data = {"name": "Extra", "custom": True, "colors": {"palette": ["#ff0000"]}}
            top._save_user_templates({"extra_style": data})
            result = list_templates()
            assert result["status"] == "success"
            ids = {t["id"] for t in result["data"]["templates"]}
            assert "extra_style" in ids
            custom_entry = [t for t in result["data"]["templates"] if t["id"] == "extra_style"][0]
            assert custom_entry.get("custom") is True
            assert "custom" in result["data"]["message"]
        finally:
            top._USER_TEMPLATES_PATHS = orig
