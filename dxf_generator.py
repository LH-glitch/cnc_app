"""
DXF Generator module for CNC DXF generator.
Main logic for creating DXF files with shapes and holes.
"""

import math
import ezdxf
from shapes import (
    add_rectangle, add_circle_shape, add_triangle, add_rounded_rectangle,
    add_ellipse_shape, add_hexagon, add_rectangular_slot,
    add_fold_line, add_groove_line, add_flanged_shape, add_flanged_rectangle,
    add_box_flat_pattern, add_l_bracket_flat_pattern, add_channel_flat_pattern
)
from holes import add_circle_hole, NoHoles, CenterHole, RelativeHoles, CustomHoles
from validation import polygon_center, circle_fully_inside_shape, slot_fully_inside_shape


class Material:
    """Material parameters for folded part and bend allowance."""

    def __init__(self, name='steel', thickness=1.0, k_factor=0.33, bend_radius=None, grain_direction='longitudinal'):
        self.name = name
        self.thickness = thickness
        self.k_factor = k_factor
        self.bend_radius = bend_radius if bend_radius is not None else max(thickness * 1.5, 1.0)
        self.grain_direction = grain_direction

    def bend_allowance(self, angle_deg=90):
        """Calculate bend allowance for a given bend angle."""
        angle_rad = math.radians(angle_deg)
        return self.k_factor * angle_rad * (self.thickness + self.bend_radius)

    def relief_gap(self):
        """Suggested relief gap for formed features."""
        return max(self.thickness * 0.5, 0.5)
from tool_compensation import NoToolCompensation
from cut_types import ProfileCut, PocketCut, DrillCut, SlotCut
from layers import LayerManager
from patterns import PatternGenerator


class DXFGenerator:
    """Main class for generating DXF files with shapes and holes."""

    def __init__(self, tool_compensation=None):
        self.doc = None
        self.msp = None
        self.layer_manager = None
        self.tool_compensation = tool_compensation or NoToolCompensation()

    def create_document(self):
        """Create a new DXF document with layers."""
        self.doc = ezdxf.new()
        self.layer_manager = LayerManager(self.doc)
        self.msp = self.doc.modelspace()

    def create_material(self, name='steel', thickness=1.0, k_factor=0.33, bend_radius=None, grain_direction='longitudinal'):
        """Create a material profile for sheet metal and bend allowance."""
        return Material(name=name, thickness=thickness, k_factor=k_factor, bend_radius=bend_radius, grain_direction=grain_direction)

    def generate_flat_pattern_template(self, template_type, template_params, material=None, filename=None, bend_values=None, relief_type='none', relief_size=3.0):
        """Generate a flat pattern DXF for a folded part template."""
        self.create_document()
        material = material or Material()

        if template_type == 'box':
            info = add_box_flat_pattern(
                self.msp,
                template_params['base_width'],
                template_params['base_depth'],
                template_params['wall_height'],
                material,
                layer=LayerManager.TEMPLATE_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )
        elif template_type == 'l_bracket':
            info = add_l_bracket_flat_pattern(
                self.msp,
                template_params['base_width'],
                template_params['base_depth'],
                template_params['leg_height'],
                material,
                layer=LayerManager.TEMPLATE_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )
        elif template_type == 'channel':
            info = add_channel_flat_pattern(
                self.msp,
                template_params['base_width'],
                template_params['base_depth'],
                template_params['wall_height'],
                material,
                layer=LayerManager.TEMPLATE_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )
        else:
            raise ValueError(f"Unsupported template type: {template_type}")

        boundary = info.get('boundary', [])
        if boundary and bend_values and any(float(bend_values.get(k, 0)) > 0 for k in ('top', 'bottom', 'left', 'right')):
            add_flanged_shape(
                self.msp,
                boundary,
                bend_values=bend_values,
                layer=LayerManager.CUT_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )

        if filename:
            self.save_file(filename)
        return info

    def get_flat_pattern_preview_data(self, template_type, template_params, material=None, relief_type='none', relief_size=3.0):
        """Return preview metadata for the flat pattern layout."""
        temp_doc = ezdxf.new()
        LayerManager(temp_doc)
        temp_msp = temp_doc.modelspace()
        material = material or Material()

        if template_type == 'box':
            return add_box_flat_pattern(
                temp_msp,
                template_params['base_width'],
                template_params['base_depth'],
                template_params['wall_height'],
                material,
                layer=LayerManager.TEMPLATE_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )
        elif template_type == 'l_bracket':
            return add_l_bracket_flat_pattern(
                temp_msp,
                template_params['base_width'],
                template_params['base_depth'],
                template_params['leg_height'],
                material,
                layer=LayerManager.TEMPLATE_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )
        elif template_type == 'channel':
            return add_channel_flat_pattern(
                temp_msp,
                template_params['base_width'],
                template_params['base_depth'],
                template_params['wall_height'],
                material,
                layer=LayerManager.TEMPLATE_LAYER,
                fold_layer=LayerManager.FOLDS_LAYER,
                relief_type=relief_type,
                relief_size=relief_size,
                relief_layer=LayerManager.RELIEF_LAYER,
            )
        else:
            raise ValueError(f"Unsupported template type: {template_type}")

    def get_folded_intent_preview_data(self, template_type, template_params, material=None):
        """Return preview metadata for folded intent, including fold line positions."""
        material = material or Material()
        preview = self.get_flat_pattern_preview_data(template_type, template_params, material)
        preview_data = preview.copy()
        if 'fold_lines' in preview_data:
            preview_data['folded_intent'] = {
                'fold_lines': preview_data['fold_lines'],
                'material': {
                    'name': material.name,
                    'thickness': material.thickness,
                    'bend_radius': material.bend_radius,
                    'grain_direction': material.grain_direction
                },
                'fold_count': len(preview_data['fold_lines']),
                'fold_directions': [f.get('direction', 'up') for f in preview_data['fold_lines']]
            }
        return preview_data

    def suggest_layouts(self, part_width, part_height, sheet_width, sheet_height, margin=5):
        """Suggest simple layout options to reduce material waste."""
        options = []
        sheet_area = sheet_width * sheet_height

        for orientation in [0, 90]:
            if orientation == 0:
                width = part_width
                height = part_height
            else:
                width = part_height
                height = part_width

            fits = width + 2 * margin <= sheet_width and height + 2 * margin <= sheet_height
            used_area = width * height if fits else 0
            waste_ratio = 1 - used_area / sheet_area if fits else None
            options.append({
                'orientation': orientation,
                'width': width,
                'height': height,
                'fits': fits,
                'margin': margin,
                'waste_ratio': waste_ratio,
                'placement': (margin, margin) if fits else None
            })

        options.sort(key=lambda x: (not x['fits'], x['waste_ratio'] if x['waste_ratio'] is not None else 1.0))
        return options

    def generate_shape(self, shape_type, cut_type=None, **params):
        """Generate a shape and return shape parameters for hole validation."""
        if cut_type is None:
            cut_type = ProfileCut(self.tool_compensation)

        # Determine which layer to use
        layer_name = cut_type.get_layer_name()
        msp = self.layer_manager.get_layer_modelspace(layer_name)

        if shape_type == 'rectangle':
            polygon = add_rectangle(msp, params['width'], params['height'], self.tool_compensation, layer_name)
            return {'type': 'rectangle', 'width': params['width'], 'height': params['height'], 'polygon': polygon}
        elif shape_type == 'circle':
            cx, cy, r = add_circle_shape(msp, params['radius'], self.tool_compensation, layer_name)
            return {'type': 'circle', 'radius': params['radius']}
        elif shape_type == 'triangle':
            polygon = add_triangle(msp, params['width'], params['height'], self.tool_compensation, layer_name)
            return {'type': 'triangle', 'width': params['width'], 'height': params['height'], 'polygon': polygon}
        elif shape_type == 'rounded_rectangle':
            polygon = add_rounded_rectangle(msp, params['width'], params['height'], params['corner_radius'], self.tool_compensation, layer_name)
            return {'type': 'rounded_rectangle', 'width': params['width'], 'height': params['height'], 'polygon': polygon}
        elif shape_type == 'ellipse':
            cx, cy, rx, ry = add_ellipse_shape(msp, params['rx'], params['ry'], self.tool_compensation, layer_name)
            return {'type': 'ellipse', 'rx': params['rx'], 'ry': params['ry']}
        elif shape_type == 'hexagon':
            polygon = add_hexagon(msp, params['side'], self.tool_compensation, layer_name)
            return {'type': 'hexagon', 'side': params['side'], 'polygon': polygon}
        elif shape_type == 'flanged_rectangle':
            info = add_flanged_rectangle(
                msp,
                params['width'],
                params['height'],
                params.get('bend_top', 0),
                params.get('bend_bottom', 0),
                params.get('bend_left', 0),
                params.get('bend_right', 0),
                layer=layer_name,
                fold_layer=LayerManager.FOLDS_LAYER
            )
            return {
                'type': 'flanged_rectangle',
                'width': params['width'],
                'height': params['height'],
                'bend_top': params.get('bend_top', 0),
                'bend_bottom': params.get('bend_bottom', 0),
                'bend_left': params.get('bend_left', 0),
                'bend_right': params.get('bend_right', 0),
                'info': info
            }
        else:
            raise ValueError(f"Unsupported shape type: {shape_type}")

    def add_holes(self, hole_pattern, shape_params, cut_type=None):
        """Add holes to the DXF based on the hole pattern."""
        if cut_type is None:
            cut_type = DrillCut(self.tool_compensation)

        holes = hole_pattern.get_holes(shape_params)
        if not hole_pattern.validate_holes(holes, shape_params):
            raise ValueError("Holes do not fit within the shape boundaries.")

        layer_name = cut_type.get_layer_name()
        msp = self.layer_manager.get_layer_modelspace(layer_name)

        for x, y in holes:
            add_circle_hole(msp, x, y, hole_pattern.hole_radius, self.tool_compensation, layer_name)

    def add_slots(self, slots, shape_params, cut_type=None):
        """Add slots to the DXF."""
        if cut_type is None:
            cut_type = SlotCut(self.tool_compensation)

        shape_type = shape_params.get('type')
        layer_name = cut_type.get_layer_name()
        msp = self.layer_manager.get_layer_modelspace(layer_name)

        for slot in slots:
            if isinstance(slot, dict):
                # New slot format with orientation
                x, y, width, height, angle = slot['x'], slot['y'], slot['width'], slot['height'], slot['angle']
                orientation = slot.get('orientation', 'horizontal')
            else:
                # Legacy tuple format
                x, y, width, height, angle = slot
                orientation = 'horizontal'

            if not slot_fully_inside_shape(x, y, width, height, angle, shape_type, shape_params):
                raise ValueError("Slot does not fit within the shape boundaries.")
            add_rectangular_slot(msp, x, y, width, height, angle, self.tool_compensation, layer_name)

    def save_file(self, filename):
        """Save the DXF document to a file."""
        self.doc.saveas(filename)
        print(f"DXF file '{filename}' created successfully!")

    def get_dxf_bytes(self):
        """Return the DXF content as bytes (for GUI/AI integration)."""
        import io
        import tempfile
        import os
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.dxf', delete=False) as temp_file:
            temp_filename = temp_file.name
        
        try:
            # Save to temporary file
            self.doc.saveas(temp_filename)
            # Read back as bytes
            with open(temp_filename, 'rb') as f:
                return f.read()
        finally:
            # Clean up temporary file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def get_dxf_string(self):
        """Return the DXF content as a string (for GUI/AI integration)."""
        import tempfile
        import os
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.dxf', delete=False) as temp_file:
            temp_filename = temp_file.name
        
        try:
            # Save to temporary file
            self.doc.saveas(temp_filename)
            # Read back as string
            with open(temp_filename, 'r', encoding='utf-8') as f:
                return f.read()
        finally:
            # Clean up temporary file
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    def generate_flanged_panel(self, width, height, bend_top=0, bend_bottom=0, bend_left=0, bend_right=0, filename=None):
        """Generate a flanged panel flat pattern DXF."""
        self.create_document()
        info = add_flanged_rectangle(
            self.msp,
            width,
            height,
            bend_top,
            bend_bottom,
            bend_left,
            bend_right,
            layer=LayerManager.CUT_LAYER,
            fold_layer=LayerManager.FOLDS_LAYER
        )
        if filename:
            self.save_file(filename)
        return info

    def generate_dxf(self, shape_type, shape_params, hole_pattern, filename=None, pattern_params=None):
        """Generate a complete DXF file with shape, holes, and optional patterns."""
        self.create_document()
        shape_info = self.generate_shape(shape_type, **shape_params)

        # Generate patterns if enabled (using original shape boundary before flanges)
        if pattern_params and pattern_params.get('enabled', False):
            self.add_patterns(shape_info, pattern_params)

        flange_keys = ['bend_top', 'bend_bottom', 'bend_left', 'bend_right']
        if any(float(shape_params.get(k, 0)) > 0 for k in flange_keys):
            boundary = shape_info.get('polygon') or shape_info.get('boundary')
            if boundary:
                add_flanged_shape(
                    self.msp,
                    boundary,
                    bend_top=shape_params.get('bend_top', 0),
                    bend_bottom=shape_params.get('bend_bottom', 0),
                    bend_left=shape_params.get('bend_left', 0),
                    bend_right=shape_params.get('bend_right', 0),
                    layer=LayerManager.CUT_LAYER,
                    fold_layer=LayerManager.FOLDS_LAYER,
                    relief_type=shape_params.get('relief_type', 'none'),
                    relief_size=float(shape_params.get('relief_size', 3.0)),
                    relief_layer=LayerManager.RELIEF_LAYER,
                )

        self.add_holes(hole_pattern, shape_info)
        if filename:
            self.save_file(filename)
            return filename
        else:
            return self.get_dxf_bytes()

    def generate_dxf_in_memory(self, shape_type, shape_params, hole_pattern, slots=None, pattern_params=None):
        """Generate a complete DXF in memory without saving to file."""
        self.create_document()
        shape_info = self.generate_shape(shape_type, **shape_params)

        # Generate patterns if enabled (using original shape boundary before flanges)
        if pattern_params and pattern_params.get('enabled', False):
            self.add_patterns(shape_info, pattern_params)

        flange_keys = ['bend_top', 'bend_bottom', 'bend_left', 'bend_right']
        if any(float(shape_params.get(k, 0)) > 0 for k in flange_keys):
            boundary = shape_info.get('polygon') or shape_info.get('boundary')
            if boundary:
                add_flanged_shape(
                    self.msp,
                    boundary,
                    bend_top=shape_params.get('bend_top', 0),
                    bend_bottom=shape_params.get('bend_bottom', 0),
                    bend_left=shape_params.get('bend_left', 0),
                    bend_right=shape_params.get('bend_right', 0),
                    layer=LayerManager.CUT_LAYER,
                    fold_layer=LayerManager.FOLDS_LAYER,
                    relief_type=shape_params.get('relief_type', 'none'),
                    relief_size=float(shape_params.get('relief_size', 3.0)),
                    relief_layer=LayerManager.RELIEF_LAYER,
                )

        self.add_holes(hole_pattern, shape_info)
        if slots:
            self.add_slots(slots, shape_info)
        return self.doc

    def add_patterns(self, shape_info, pattern_params):
        """Add interior cut patterns to the DXF."""
        pattern_generator = PatternGenerator()

        # Get the boundary polygon from shape_info
        boundary = shape_info.get('polygon') or shape_info.get('boundary')
        if not boundary:
            return

        # Generate pattern entities
        pattern_entities = pattern_generator.generate_pattern(
            pattern_type=pattern_params.get('pattern_type', 'circles'),
            boundary=boundary,
            pattern_size=float(pattern_params.get('pattern_size', 10)),
            spacing_x=float(pattern_params.get('spacing_x', 20)),
            spacing_y=float(pattern_params.get('spacing_y', 20)),
            inner_margin=float(pattern_params.get('inner_margin', 5))
        )

        # Add pattern entities to DXF
        pattern_layer = LayerManager.PATTERN_LAYER
        msp = self.layer_manager.get_layer_modelspace(pattern_layer)

        for entity in pattern_entities:
            if entity['type'] == 'circle':
                center = entity['center']
                radius = entity['radius']
                msp.add_circle(center, radius, dxfattribs={'layer': pattern_layer})
            elif entity['type'] == 'polyline':
                points = entity['points']
                if points:
                    # Create a polyline
                    polyline = msp.add_lwpolyline(points, dxfattribs={'layer': pattern_layer})
                    polyline.close()  # Close the shape

    def get_shape_preview_data(self, shape_type, **params):
        """Get shape data for GUI preview (bounding box, vertices, etc.)."""
        # Create a temporary document to get shape info
        temp_doc = ezdxf.new()
        temp_msp = temp_doc.modelspace()
        
        if shape_type == 'rectangle':
            polygon = add_rectangle(temp_msp, params['width'], params['height'])
            return {
                'type': 'rectangle',
                'width': params['width'],
                'height': params['height'],
                'vertices': polygon,
                'bounding_box': (0, 0, params['width'], params['height'])
            }
        elif shape_type == 'circle':
            cx, cy, r = add_circle_shape(temp_msp, params['radius'])
            return {
                'type': 'circle',
                'center': (cx, cy),
                'radius': r,
                'bounding_box': (-r, -r, r, r)
            }
        elif shape_type == 'triangle':
            polygon = add_triangle(temp_msp, params['width'], params['height'])
            return {
                'type': 'triangle',
                'width': params['width'],
                'height': params['height'],
                'vertices': polygon,
                'bounding_box': (0, 0, params['width'], params['height'])
            }
        elif shape_type == 'rounded_rectangle':
            polygon = add_rounded_rectangle(temp_msp, params['width'], params['height'], params['corner_radius'])
            return {
                'type': 'rounded_rectangle',
                'width': params['width'],
                'height': params['height'],
                'corner_radius': params['corner_radius'],
                'vertices': polygon,
                'bounding_box': (0, 0, params['width'], params['height'])
            }
        elif shape_type == 'ellipse':
            cx, cy, rx, ry = add_ellipse_shape(temp_msp, params['rx'], params['ry'])
            return {
                'type': 'ellipse',
                'center': (cx, cy),
                'rx': rx,
                'ry': ry,
                'bounding_box': (-rx, -ry, rx, ry)
            }
        elif shape_type == 'hexagon':
            polygon = add_hexagon(temp_msp, params['side'])
            # Calculate bounding box for hexagon
            xs = [p[0] for p in polygon]
            ys = [p[1] for p in polygon]
            return {
                'type': 'hexagon',
                'side': params['side'],
                'vertices': polygon,
                'bounding_box': (min(xs), min(ys), max(xs), max(ys))
            }
        else:
            raise ValueError(f"Unsupported shape type: {shape_type}")


# Convenience functions for backward compatibility and easy use
def create_rectangle_dxf(width, height, hole_pattern, filename="rectangle.dxf", tool_compensation=None, **kwargs):
    """Create a rectangle DXF with holes."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'width': width, 'height': height, **kwargs}
    generator.generate_dxf('rectangle', shape_params, hole_pattern, filename)


def create_circle_dxf(radius, hole_pattern, filename="circle.dxf", tool_compensation=None, **kwargs):
    """Create a circle DXF with holes."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'radius': radius, **kwargs}
    generator.generate_dxf('circle', shape_params, hole_pattern, filename)


def create_triangle_dxf(width, height, hole_pattern, filename="triangle.dxf", tool_compensation=None, **kwargs):
    """Create a triangle DXF with holes."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'width': width, 'height': height, **kwargs}
    generator.generate_dxf('triangle', shape_params, hole_pattern, filename)


def create_rounded_rectangle_dxf(width, height, corner_radius, hole_pattern, filename="rounded_rectangle.dxf", tool_compensation=None, **kwargs):
    """Create a rounded rectangle DXF with holes."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'width': width, 'height': height, 'corner_radius': corner_radius, **kwargs}
    generator.generate_dxf('rounded_rectangle', shape_params, hole_pattern, filename)


def create_ellipse_dxf(rx, ry, hole_pattern, filename="ellipse.dxf", tool_compensation=None, **kwargs):
    """Create an ellipse DXF with holes."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'rx': rx, 'ry': ry, **kwargs}
    generator.generate_dxf('ellipse', shape_params, hole_pattern, filename)


def create_hexagon_dxf(side, hole_pattern, filename="hexagon.dxf", tool_compensation=None, **kwargs):
    """Create a hexagon DXF with holes."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'side': side, **kwargs}
    generator.generate_dxf('hexagon', shape_params, hole_pattern, filename)


def create_box_flat_pattern_dxf(base_width, base_depth, wall_height, material=None, filename="box_flat_pattern.dxf", bend_top=0, bend_bottom=0, bend_left=0, bend_right=0, relief_type='none', relief_size=3.0):
    """Create a box flat pattern DXF for a folded sheet metal part."""
    generator = DXFGenerator()
    material = material or Material()
    generator.generate_flat_pattern_template(
        'box',
        {'base_width': base_width, 'base_depth': base_depth, 'wall_height': wall_height},
        material,
        filename,
        bend_values={
            'top': bend_top,
            'bottom': bend_bottom,
            'left': bend_left,
            'right': bend_right
        },
        relief_type=relief_type,
        relief_size=relief_size,
    )


def create_l_bracket_flat_pattern_dxf(base_width, base_depth, leg_height, material=None, filename="l_bracket_flat_pattern.dxf", bend_top=0, bend_bottom=0, bend_left=0, bend_right=0, relief_type='none', relief_size=3.0):
    """Create an L-bracket flat pattern DXF."""
    generator = DXFGenerator()
    material = material or Material()
    generator.generate_flat_pattern_template(
        'l_bracket',
        {'base_width': base_width, 'base_depth': base_depth, 'leg_height': leg_height},
        material,
        filename,
        bend_values={
            'top': bend_top,
            'bottom': bend_bottom,
            'left': bend_left,
            'right': bend_right
        },
        relief_type=relief_type,
        relief_size=relief_size,
    )


def create_channel_flat_pattern_dxf(base_width, base_depth, wall_height, material=None, filename="channel_flat_pattern.dxf", bend_top=0, bend_bottom=0, bend_left=0, bend_right=0, relief_type='none', relief_size=3.0):
    """Create a U-channel flat pattern DXF."""
    generator = DXFGenerator()
    material = material or Material()
    generator.generate_flat_pattern_template(
        'channel',
        {'base_width': base_width, 'base_depth': base_depth, 'wall_height': wall_height},
        material,
        filename,
        bend_values={
            'top': bend_top,
            'bottom': bend_bottom,
            'left': bend_left,
            'right': bend_right
        },
        relief_type=relief_type,
        relief_size=relief_size,
    )


def create_flanged_panel_dxf(width, height, bend_top, bend_bottom, bend_left, bend_right, filename="flanged_panel.dxf"):
    """Create a flanged panel DXF flat pattern."""
    generator = DXFGenerator()
    generator.generate_flanged_panel(width, height, bend_top, bend_bottom, bend_left, bend_right, filename)


# Functions for GUI/AI integration (return DXF content)
def create_rectangle_dxf_bytes(width, height, hole_pattern):
    """Create a rectangle DXF with holes and return as bytes."""
    generator = DXFGenerator()
    shape_params = {'width': width, 'height': height}
    generator.generate_dxf_in_memory('rectangle', shape_params, hole_pattern)
    return generator.get_dxf_bytes()


def create_circle_dxf_bytes(radius, hole_pattern):
    """Create a circle DXF with holes and return as bytes."""
    generator = DXFGenerator()
    shape_params = {'radius': radius}
    generator.generate_dxf_in_memory('circle', shape_params, hole_pattern)
    return generator.get_dxf_bytes()


def create_triangle_dxf_bytes(width, height, hole_pattern):
    """Create a triangle DXF with holes and return as bytes."""
    generator = DXFGenerator()
    shape_params = {'width': width, 'height': height}
    generator.generate_dxf_in_memory('triangle', shape_params, hole_pattern)
    return generator.get_dxf_bytes()


def create_rounded_rectangle_dxf_bytes(width, height, corner_radius, hole_pattern):
    """Create a rounded rectangle DXF with holes and return as bytes."""
    generator = DXFGenerator()
    shape_params = {'width': width, 'height': height, 'corner_radius': corner_radius}
    generator.generate_dxf_in_memory('rounded_rectangle', shape_params, hole_pattern)
    return generator.get_dxf_bytes()


def create_ellipse_dxf_bytes(rx, ry, hole_pattern):
    """Create an ellipse DXF with holes and return as bytes."""
    generator = DXFGenerator()
    shape_params = {'rx': rx, 'ry': ry}
    generator.generate_dxf_in_memory('ellipse', shape_params, hole_pattern)
    return generator.get_dxf_bytes()


def create_hexagon_dxf_bytes(side, hole_pattern, slots=None):
    """Create a hexagon DXF with holes and slots, return as bytes."""
    generator = DXFGenerator()
    shape_params = {'side': side}
    generator.generate_dxf_in_memory('hexagon', shape_params, hole_pattern, slots)
    return generator.get_dxf_bytes()


# Functions for file output with slots
def create_rectangle_dxf_with_slots(width, height, hole_pattern, slots, filename="rectangle_with_slots.dxf", tool_compensation=None):
    """Create a rectangle DXF with holes and slots."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'width': width, 'height': height}
    generator.generate_dxf_in_memory('rectangle', shape_params, hole_pattern, slots)
    generator.save_file(filename)


def create_circle_dxf_with_slots(radius, hole_pattern, slots, filename="circle_with_slots.dxf", tool_compensation=None):
    """Create a circle DXF with holes and slots."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'radius': radius}
    generator.generate_dxf_in_memory('circle', shape_params, hole_pattern, slots)
    generator.save_file(filename)


def create_triangle_dxf_with_slots(width, height, hole_pattern, slots, filename="triangle_with_slots.dxf", tool_compensation=None):
    """Create a triangle DXF with holes and slots."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'width': width, 'height': height}
    generator.generate_dxf_in_memory('triangle', shape_params, hole_pattern, slots)
    generator.save_file(filename)


def create_rounded_rectangle_dxf_with_slots(width, height, corner_radius, hole_pattern, slots, filename="rounded_rectangle_with_slots.dxf", tool_compensation=None):
    """Create a rounded rectangle DXF with holes and slots."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'width': width, 'height': height, 'corner_radius': corner_radius}
    generator.generate_dxf_in_memory('rounded_rectangle', shape_params, hole_pattern, slots)
    generator.save_file(filename)


def create_ellipse_dxf_with_slots(rx, ry, hole_pattern, slots, filename="ellipse_with_slots.dxf", tool_compensation=None):
    """Create an ellipse DXF with holes and slots."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'rx': rx, 'ry': ry}
    generator.generate_dxf_in_memory('ellipse', shape_params, hole_pattern, slots)
    generator.save_file(filename)


def create_hexagon_dxf_with_slots(side, hole_pattern, slots, filename="hexagon_with_slots.dxf", tool_compensation=None):
    """Create a hexagon DXF with holes and slots."""
    generator = DXFGenerator(tool_compensation)
    shape_params = {'side': side}
    generator.generate_dxf_in_memory('hexagon', shape_params, hole_pattern, slots)
    generator.save_file(filename)


# Preview functions for GUI integration
def get_rectangle_preview(width, height):
    """Get rectangle preview data for GUI."""
    generator = DXFGenerator()
    return generator.get_shape_preview_data('rectangle', width=width, height=height)


def get_circle_preview(radius):
    """Get circle preview data for GUI."""
    generator = DXFGenerator()
    return generator.get_shape_preview_data('circle', radius=radius)


def get_triangle_preview(width, height):
    """Get triangle preview data for GUI."""
    generator = DXFGenerator()
    return generator.get_shape_preview_data('triangle', width=width, height=height)


def get_rounded_rectangle_preview(width, height, corner_radius):
    """Get rounded rectangle preview data for GUI."""
    generator = DXFGenerator()
    return generator.get_shape_preview_data('rounded_rectangle', width=width, height=height, corner_radius=corner_radius)


def get_ellipse_preview(rx, ry):
    """Get ellipse preview data for GUI."""
    generator = DXFGenerator()
    return generator.get_shape_preview_data('ellipse', rx=rx, ry=ry)


def get_hexagon_preview(side):
    """Get hexagon preview data for GUI."""
    generator = DXFGenerator()
    return generator.get_shape_preview_data('hexagon', side=side)