"""Document export operations module"""

import tempfile
import base64
import os
from typing import Dict, Any
from inkex.command import call
from .common import create_success_response, create_error_response


def export_document_image(extension_instance, svg, attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Export document as image or PDF.

    Supported formats: png, pdf, eps, ps
    For png: supports max_size, return_base64, area parameters
    For pdf/eps/ps: supports output_path, area parameters
    """
    try:
        # Get export parameters
        format_type = attributes.get('format', 'png')
        area = attributes.get('area', 'page')  # page, drawing, selection

        # Determine area flag
        if area == 'drawing':
            export_area = '--export-area-drawing'
        else:
            export_area = '--export-area-page'

        # Allow user-specified output path (useful for saving to specific location)
        user_output = attributes.get('output_path', '')

        if user_output:
            output_path = user_output
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        else:
            output_fd, output_path = tempfile.mkstemp(suffix=f'.{format_type}', prefix='inkscape_export_')
            os.close(output_fd)

        # Save current document to temp SVG file
        temp_svg_fd, temp_svg = tempfile.mkstemp(suffix='.svg')
        os.close(temp_svg_fd)
        with open(temp_svg, 'wb') as f:
            extension_instance.save(f)

        if format_type == 'png':
            max_size = int(attributes.get('max_size', 800))
            return_base64_val = attributes.get('return_base64', 'true')
            if isinstance(return_base64_val, bool):
                return_base64 = return_base64_val
            else:
                return_base64 = str(return_base64_val).lower() == 'true'

            # Calculate DPI to respect max_size
            dpi = 96
            if max_size:
                width = float(svg.get('width', '100').replace('mm', '').replace('px', ''))
                if max_size < width:
                    dpi = int((max_size / width) * 96)

            call('inkscape',
                 '--export-type=png',
                 f'--export-filename={output_path}',
                 f'--export-dpi={dpi}',
                 export_area,
                 temp_svg)

        elif format_type in ('pdf', 'eps', 'ps'):
            call('inkscape',
                 f'--export-type={format_type}',
                 f'--export-filename={output_path}',
                 export_area,
                 temp_svg)

        else:
            os.unlink(temp_svg)
            return create_error_response(f"Unsupported format: {format_type}. Use png, pdf, eps, or ps.")

        # Clean up temp SVG
        os.unlink(temp_svg)

        # Get file info
        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        response_data = {
            "export_path": output_path,
            "format": format_type,
            "file_size": file_size,
            "area": area
        }

        # Add base64 data if requested (only for png)
        if format_type == 'png':
            return_base64_val = attributes.get('return_base64', 'true')
            if isinstance(return_base64_val, bool):
                return_base64 = return_base64_val
            else:
                return_base64 = str(return_base64_val).lower() == 'true'

            if return_base64 and os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    image_data = f.read()
                    base64_data = base64.b64encode(image_data).decode('utf-8')
                    response_data["base64_data"] = base64_data

        return create_success_response(
            f"Document exported as {format_type.upper()} -> {output_path}",
            **response_data
        )

    except Exception as e:
        return create_error_response(f"Export failed: {str(e)}")