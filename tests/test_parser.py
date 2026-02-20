"""Tests for the command parser (inkmcpcli.py).

These tests don't require Inkscape to be running.
"""

import sys
import os
import pytest

# Add parent dirs to path so we can import inkmcp modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from inkmcpcli import (
    parse_command_string,
    parse_attributes,
    parse_tag_and_attributes,
    parse_children_array,
    strip_python_comments,
)


class TestParseCommandString:
    """Tests for the main parse_command_string entry point."""

    def test_simple_rect(self):
        result = parse_command_string("rect x=100 y=50 width=200 height=100")
        assert result["tag"] == "rect"
        assert result["attributes"]["x"] == "100"
        assert result["attributes"]["y"] == "50"
        assert result["attributes"]["width"] == "200"
        assert result["attributes"]["height"] == "100"

    def test_circle_with_fill(self):
        result = parse_command_string("circle cx=150 cy=150 r=75 fill=#ff0000")
        assert result["tag"] == "circle"
        assert result["attributes"]["cx"] == "150"
        assert result["attributes"]["r"] == "75"
        assert result["attributes"]["fill"] == "#ff0000"

    def test_element_with_id(self):
        result = parse_command_string("rect id=my_rect x=0 y=0 width=10 height=10")
        assert result["attributes"]["id"] == "my_rect"

    def test_text_with_quoted_content(self):
        result = parse_command_string("text x=50 y=100 text='Hello World' font-size=16")
        assert result["tag"] == "text"
        assert result["attributes"]["text"] == "Hello World"
        assert result["attributes"]["font-size"] == "16"

    def test_path_with_d_attribute(self):
        result = parse_command_string("path id=p1 d='M 20,50 C 20,50 80,20 80,80'")
        assert result["tag"] == "path"
        assert "M 20,50" in result["attributes"]["d"]

    def test_empty_command(self):
        result = parse_command_string("")
        assert result["tag"] == ""

    def test_get_info(self):
        result = parse_command_string("get-info")
        assert result["tag"] == "get-info"

    def test_get_selection(self):
        result = parse_command_string("get-selection")
        assert result["tag"] == "get-selection"

    def test_get_info_by_id(self):
        result = parse_command_string("get-info-by-id id=rect1")
        assert result["tag"] == "get-info-by-id"
        assert result["attributes"]["id"] == "rect1"

    def test_execute_code(self):
        result = parse_command_string(
            "execute-code code='print(42)'"
        )
        assert result["tag"] == "execute-code"
        assert result["attributes"]["code"] == "print(42)"

    def test_open_file(self):
        result = parse_command_string("open-file path=/tmp/test.svg")
        assert result["tag"] == "open-file"
        assert result["attributes"]["path"] == "/tmp/test.svg"

    def test_export_document_image(self):
        result = parse_command_string(
            "export-document-image format=png return_base64=true"
        )
        assert result["tag"] == "export-document-image"
        assert result["attributes"]["format"] == "png"
        assert result["attributes"]["return_base64"] == "true"

    def test_export_pdf(self):
        result = parse_command_string(
            "export-document-image format=pdf output_path=/tmp/out.pdf"
        )
        assert result["tag"] == "export-document-image"
        assert result["attributes"]["format"] == "pdf"
        assert result["attributes"]["output_path"] == "/tmp/out.pdf"

    def test_hyphenated_attributes(self):
        result = parse_command_string(
            "rect stroke-width=2 stroke-dasharray='5,3' fill-opacity=0.5"
        )
        assert result["attributes"]["stroke-width"] == "2"
        assert result["attributes"]["stroke-dasharray"] == "5,3"
        assert result["attributes"]["fill-opacity"] == "0.5"

    def test_inkscape_namespaced_attribute(self):
        result = parse_command_string(
            "path id=p1 inkscape:label=MyPath d='M 0,0 L 100,100'"
        )
        assert result["attributes"]["inkscape:label"] == "MyPath"


class TestParseAttributes:
    """Tests for the attribute parser."""

    def test_basic_key_value(self):
        result = parse_attributes("x=100 y=200")
        assert result["x"] == "100"
        assert result["y"] == "200"

    def test_double_quoted_value(self):
        result = parse_attributes('text="Hello World"')
        assert result["text"] == "Hello World"

    def test_single_quoted_value(self):
        result = parse_attributes("text='Hello World'")
        assert result["text"] == "Hello World"

    def test_hash_color(self):
        result = parse_attributes("fill=#ff0000 stroke=#333333")
        assert result["fill"] == "#ff0000"
        assert result["stroke"] == "#333333"

    def test_url_value(self):
        result = parse_attributes("fill=url(#grad1)")
        assert result["fill"] == "url(#grad1)"

    def test_empty_string(self):
        result = parse_attributes("")
        assert result == {}


class TestParseChildren:
    """Tests for children array parsing."""

    def test_simple_children(self):
        result = parse_children_array(
            "[{rect x=0 y=0 width=10 height=10}, {circle cx=50 cy=50 r=10}]"
        )
        assert len(result) == 2
        assert result[0]["tag"] == "rect"
        assert result[1]["tag"] == "circle"

    def test_children_with_ids(self):
        result = parse_children_array(
            "[{rect id=bg x=0 y=0}, {circle id=dot cx=10 cy=10 r=5}]"
        )
        assert result[0]["attributes"]["id"] == "bg"
        assert result[1]["attributes"]["id"] == "dot"

    def test_nested_children(self):
        result = parse_children_array(
            "[{g id=group children=[{rect id=inner x=0 y=0}]}]"
        )
        assert len(result) == 1
        assert result[0]["tag"] == "g"
        assert len(result[0]["children"]) == 1
        assert result[0]["children"][0]["tag"] == "rect"

    def test_gradient_stops(self):
        result = parse_children_array(
            "[{stop offset=0% stop-color=red}, {stop offset=100% stop-color=blue}]"
        )
        assert len(result) == 2
        assert result[0]["attributes"]["stop-color"] == "red"
        assert result[1]["attributes"]["stop-color"] == "blue"


class TestGroupParsing:
    """Tests for group elements with children."""

    def test_group_with_children(self):
        result = parse_command_string(
            "g id=scene children=[{rect id=bg x=0 y=0 width=200 height=200 fill=white}, "
            "{circle id=sun cx=100 cy=50 r=20 fill=yellow}]"
        )
        assert result["tag"] == "g"
        assert result["attributes"]["id"] == "scene"
        assert len(result["children"]) == 2
        assert result["children"][0]["tag"] == "rect"
        assert result["children"][1]["tag"] == "circle"

    def test_gradient_with_stops(self):
        result = parse_command_string(
            "linearGradient id=grad1 x1=50 y1=50 x2=150 y2=50 "
            "gradientUnits=userSpaceOnUse "
            "children=[{stop offset=0% stop-color=red}, {stop offset=100% stop-color=blue}]"
        )
        assert result["tag"] == "linearGradient"
        assert len(result["children"]) == 2
        assert result["children"][0]["attributes"]["offset"] == "0%"


class TestStripPythonComments:
    """Tests for comment stripping utility."""

    def test_strip_line_comment(self):
        result = strip_python_comments("x = 1  # comment")
        assert "# comment" not in result
        assert "x = 1" in result

    def test_preserve_hash_in_string(self):
        result = strip_python_comments('color = "#ff0000"')
        assert "#ff0000" in result

    def test_strip_full_line_comment(self):
        code = "# full line comment\nx = 1"
        result = strip_python_comments(code)
        assert "x = 1" in result

    def test_empty_code(self):
        result = strip_python_comments("")
        assert result == ""
