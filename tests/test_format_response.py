"""Tests for format_response() in inkscape_mcp_server.py.

These tests don't require Inkscape to be running.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'inkmcp'))

from inkscape_mcp_server import format_response


class TestFormatResponseGetInfo:
    """Tests for get-info response formatting."""

    def test_document_info_dimensions(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Document information",
                "dimensions": {"width": "210mm", "height": "297mm"},
                "viewBox": ["0", "0", "210", "297"],
                "elementCounts": {"rect": 5, "circle": 3, "text": 2, "svg": 1},
            },
        })
        assert "210mm" in result
        assert "297mm" in result
        assert "viewBox" in result
        assert "rect: 5" in result
        assert "circle: 3" in result
        assert "11 total" in result

    def test_document_info_viewbox_string(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Document information",
                "dimensions": {"width": "100", "height": "100"},
                "viewBox": "0 0 100 100",
                "elementCounts": {},
            },
        })
        assert "0 0 100 100" in result

    def test_element_counts_sorted_by_frequency(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Document information",
                "elementCounts": {"path": 20, "rect": 5, "circle": 10},
            },
        })
        # path (20) should appear before circle (10) before rect (5)
        path_pos = result.index("path: 20")
        circle_pos = result.index("circle: 10")
        rect_pos = result.index("rect: 5")
        assert path_pos < circle_pos < rect_pos


class TestFormatResponseGetInfoById:
    """Tests for get-info-by-id response formatting."""

    def test_element_info_with_attributes(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Element information for rect1",
                "id": "rect1",
                "tag": "rect",
                "label": "My Rectangle",
                "attributes": {"x": "10", "y": "20", "width": "100", "height": "50"},
                "style": {"fill": "#ff0000", "stroke": "#000000"},
            },
        })
        assert "rect1" in result
        assert "My Rectangle" in result
        assert "x: 10" in result
        assert "fill: #ff0000" in result

    def test_element_info_no_label(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Element info",
                "id": "c1",
                "tag": "circle",
                "label": None,
            },
        })
        assert "Label" not in result


class TestFormatResponseExecuteCode:
    """Tests for execute-code response formatting."""

    def test_successful_execution_with_output(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Code executed successfully",
                "execution_successful": True,
                "output": "Hello from Inkscape\n",
                "errors": "",
                "elements_created": [],
            },
        })
        assert "[OK]" in result
        assert "Success" in result
        assert "Hello from Inkscape" in result

    def test_failed_execution_with_errors(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Code execution failed",
                "execution_successful": False,
                "output": "",
                "errors": "NameError: name 'foo' is not defined",
                "elements_created": [],
            },
        })
        assert "[FAILED]" in result
        assert "Failed" in result
        assert "NameError" in result

    def test_execution_with_return_value(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Code executed successfully",
                "execution_successful": True,
                "return_value": "42",
                "output": "",
                "errors": "",
            },
        })
        assert "42" in result

    def test_execution_with_local_variables(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Code executed successfully",
                "execution_successful": True,
                "local_variables": {"x": [1, 2, 3], "name": "test"},
                "output": "",
                "errors": "",
            },
        })
        assert "Variables" in result
        assert "x" in result
        assert "name" in result

    def test_execution_with_elements_created(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Code executed successfully",
                "execution_successful": True,
                "elements_created": ["3 new elements added"],
                "output": "",
                "errors": "",
            },
        })
        assert "Created" in result


class TestFormatResponseElementCreation:
    """Tests for element creation response formatting."""

    def test_simple_element(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "rect created successfully",
                "id": "my_rect",
                "tag": "rect",
            },
        })
        assert "[OK]" in result
        assert "my_rect" in result

    def test_id_mapping(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "3 elements created successfully",
                "id": "scene",
                "tag": "g",
                "id_mapping": {"scene": "scene", "bg": "bg", "sun": "sun_1"},
            },
        })
        assert "scene" in result
        assert "sun -> sun_1" in result
        assert "collision" in result

    def test_generated_ids_warning(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "circle created",
                "id": "circle123",
                "tag": "circle",
                "generated_ids": ["circle123"],
            },
        })
        assert "WARNING" in result
        assert "circle123" in result


class TestFormatResponseExport:
    """Tests for export response formatting."""

    def test_export_details(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Document exported as PNG",
                "export_path": "/tmp/inkscape_export_abc.png",
                "file_size": 12345,
            },
        })
        assert "/tmp/inkscape_export_abc.png" in result
        assert "12345" in result

    def test_export_pdf(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Document exported as PDF -> /tmp/out.pdf",
                "export_path": "/tmp/out.pdf",
                "format": "pdf",
                "file_size": 54321,
            },
        })
        assert "PDF" in result
        assert "/tmp/out.pdf" in result


class TestFormatResponseSelection:
    """Tests for selection response formatting."""

    def test_selection_with_elements(self):
        result = format_response({
            "status": "success",
            "data": {
                "message": "Selection information",
                "count": 2,
                "elements": [
                    {"tag": "rect", "id": "r1"},
                    {"tag": "circle", "id": "c1"},
                ],
            },
        })
        assert "Count" in result
        assert "2" in result
        assert "rect (r1)" in result
        assert "circle (c1)" in result

    def test_many_elements_truncated(self):
        elements = [{"tag": "rect", "id": f"r{i}"} for i in range(10)]
        result = format_response({
            "status": "success",
            "data": {
                "message": "Selection",
                "count": 10,
                "elements": elements,
            },
        })
        assert "and 7 more" in result


class TestFormatResponseErrors:
    """Tests for error response formatting."""

    def test_error_response(self):
        result = format_response({
            "status": "error",
            "data": {"error": "D-Bus call failed: timeout"},
        })
        assert "[ERROR]" in result
        assert "timeout" in result

    def test_unknown_error(self):
        result = format_response({"status": "error", "data": {}})
        assert "[ERROR]" in result
        assert "Unknown error" in result

    def test_success_no_details(self):
        result = format_response({
            "status": "success",
            "data": {"message": "Operation completed"},
        })
        assert "[OK]" in result
        assert "Operation completed" in result
