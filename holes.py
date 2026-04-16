"""
Holes module for CNC DXF generator.
Contains functions to generate hole patterns and add holes to DXF files.
"""

import math
import ezdxf
from validation import (
    point_inside_circle, point_inside_rectangle, point_inside_ellipse,
    hole_inside_polygon, circle_fully_inside_shape, polygon_center
)


class HolePattern:
    """Base class for hole patterns."""

    def __init__(self, hole_radius):
        self.hole_radius = hole_radius

    def get_holes(self, shape_params):
        """Return list of (x, y) hole positions. To be implemented by subclasses."""
        raise NotImplementedError

    def validate_holes(self, holes, shape_params):
        """Validate that all holes fit within the shape. To be implemented by subclasses."""
        raise NotImplementedError


class NoHoles(HolePattern):
    """No holes pattern."""

    def get_holes(self, shape_params):
        return []

    def validate_holes(self, holes, shape_params):
        return True


class CenterHole(HolePattern):
    """Single center hole pattern."""

    def get_holes(self, shape_params):
        shape_type = shape_params.get('type')
        if shape_type == 'rectangle':
            width, height = shape_params['width'], shape_params['height']
            return [(width / 2, height / 2)]
        elif shape_type == 'circle':
            return [(0, 0)]
        elif shape_type == 'ellipse':
            return [(0, 0)]
        elif shape_type in ['triangle', 'hexagon', 'rounded_rectangle']:
            polygon = shape_params['polygon']
            center_x, center_y = polygon_center(polygon)
            return [(center_x, center_y)]
        else:
            raise ValueError(f"Unsupported shape type for center hole: {shape_type}")

    def validate_holes(self, holes, shape_params):
        shape_type = shape_params.get('type')
        if shape_type == 'rectangle':
            width, height = shape_params['width'], shape_params['height']
            x, y = holes[0]
            return point_inside_rectangle(x, y, width, height, self.hole_radius)
        elif shape_type == 'circle':
            x, y = holes[0]
            radius = shape_params['radius']
            return point_inside_circle(x, y, 0, 0, radius, self.hole_radius)
        elif shape_type == 'ellipse':
            x, y = holes[0]
            rx, ry = shape_params['rx'], shape_params['ry']
            return point_inside_ellipse(x, y, 0, 0, rx, ry, self.hole_radius)
        elif shape_type in ['triangle', 'hexagon']:
            x, y = holes[0]
            polygon = shape_params['polygon']
            return hole_inside_polygon(x, y, self.hole_radius, polygon)
        else:
            return False


class RelativeHoles(HolePattern):
    """Relative hole pattern based on offsets."""

    def __init__(self, hole_radius, offset_x, offset_y):
        super().__init__(hole_radius)
        self.offset_x = offset_x
        self.offset_y = offset_y

    def get_holes(self, shape_params):
        shape_type = shape_params.get('type')
        if shape_type == 'rectangle':
            width, height = shape_params['width'], shape_params['height']
            return [
                (self.offset_x, self.offset_y),
                (width - self.offset_x, self.offset_y),
                (width - self.offset_x, height - self.offset_y),
                (self.offset_x, height - self.offset_y)
            ]
        elif shape_type == 'circle':
            return [
                (self.offset_x, self.offset_y),
                (-self.offset_x, self.offset_y),
                (-self.offset_x, -self.offset_y),
                (self.offset_x, -self.offset_y)
            ]
        elif shape_type == 'ellipse':
            return [
                (self.offset_x, self.offset_y),
                (-self.offset_x, self.offset_y),
                (-self.offset_x, -self.offset_y),
                (self.offset_x, -self.offset_y)
            ]
        elif shape_type == 'triangle':
            width, height = shape_params['width'], shape_params['height']
            return [
                (self.offset_x, self.offset_y),
                (width - self.offset_x, self.offset_y),
                (width / 2, height - self.offset_y)
            ]
        elif shape_type == 'hexagon':
            return [
                (self.offset_x, 0),
                (-self.offset_x, 0),
                (self.offset_x / 2, self.offset_y),
                (-self.offset_x / 2, self.offset_y),
                (self.offset_x / 2, -self.offset_y),
                (-self.offset_x / 2, -self.offset_y)
            ]
        else:
            raise ValueError(f"Unsupported shape type for relative holes: {shape_type}")

    def validate_holes(self, holes, shape_params):
        shape_type = shape_params.get('type')
        for x, y in holes:
            if shape_type == 'rectangle':
                width, height = shape_params['width'], shape_params['height']
                if not point_inside_rectangle(x, y, width, height, self.hole_radius):
                    return False
            elif shape_type == 'circle':
                radius = shape_params['radius']
                if not point_inside_circle(x, y, 0, 0, radius, self.hole_radius):
                    return False
            elif shape_type == 'ellipse':
                rx, ry = shape_params['rx'], shape_params['ry']
                if not point_inside_ellipse(x, y, 0, 0, rx, ry, self.hole_radius):
                    return False
            elif shape_type in ['triangle', 'hexagon']:
                polygon = shape_params['polygon']
                if not hole_inside_polygon(x, y, self.hole_radius, polygon):
                    return False
        return True


class GridHoles(HolePattern):
    """Grid pattern of holes based on panel size and spacing."""

    def __init__(self, hole_radius, rows=0, cols=0, spacing_x=0, spacing_y=0, start_x=0, start_y=0, margin=0):
        super().__init__(hole_radius)
        self.rows = rows
        self.cols = cols
        self.spacing_x = spacing_x
        self.spacing_y = spacing_y
        self.start_x = start_x
        self.start_y = start_y
        self.margin = margin

    def get_holes(self, shape_params):
        shape_type = shape_params.get('type')
        if shape_type == 'rectangle':
            width = shape_params['width']
            height = shape_params['height']
            if self.spacing_x <= 0 or self.spacing_y <= 0:
                print('GridHoles: invalid spacing values')
                return []

            margin_x = self.margin if self.start_x is None else self.start_x
            margin_y = self.margin if self.start_y is None else self.start_y
            margin_x = max(margin_x, self.hole_radius)
            margin_y = max(margin_y, self.hole_radius)

            available_width = width - 2 * margin_x
            available_height = height - 2 * margin_y
            if available_width <= 0 or available_height <= 0:
                print('GridHoles: no holes fit with current margin/spacing')
                return []

            cols = int(math.floor((available_width + 1e-9) / self.spacing_x))
            rows = int(math.floor((available_height + 1e-9) / self.spacing_y))
            if cols < 1 or rows < 1:
                return []

            extra_width = available_width - (cols - 1) * self.spacing_x
            extra_height = available_height - (rows - 1) * self.spacing_y
            start_x = margin_x + max(0.0, extra_width / 2)
            start_y = margin_y + max(0.0, extra_height / 2)

            holes = []
            for row in range(rows):
                for col in range(cols):
                    x = start_x + col * self.spacing_x
                    y = start_y + row * self.spacing_y
                    holes.append((x, y))
            return holes

        holes = []
        for row in range(self.rows):
            for col in range(self.cols):
                x = (self.start_x or 0) + col * self.spacing_x
                y = (self.start_y or 0) + row * self.spacing_y
                holes.append((x, y))
        return holes

    def validate_holes(self, holes, shape_params):
        shape_type = shape_params.get('type')
        for x, y in holes:
            if not circle_fully_inside_shape(x, y, self.hole_radius, shape_type, shape_params):
                return False
        return True


class CircularHoles(HolePattern):
    """Circular pattern of holes around center."""

    def __init__(self, hole_radius, count, radius, start_angle=0):
        super().__init__(hole_radius)
        self.count = count
        self.radius = radius
        self.start_angle = start_angle

    def get_holes(self, shape_params):
        holes = []
        angle_step = 360 / self.count
        for i in range(self.count):
            angle = math.radians(self.start_angle + i * angle_step)
            x = self.radius * math.cos(angle)
            y = self.radius * math.sin(angle)
            holes.append((x, y))
        return holes

    def validate_holes(self, holes, shape_params):
        shape_type = shape_params.get('type')
        for x, y in holes:
            if not circle_fully_inside_shape(x, y, self.hole_radius, shape_type, shape_params):
                return False
        return True


class CustomHoles(HolePattern):
    """Custom user-defined holes."""

    def __init__(self, hole_radius, positions):
        super().__init__(hole_radius)
        self.positions = positions  # List of (x, y) tuples

    def get_holes(self, shape_params):
        return self.positions

    def validate_holes(self, holes, shape_params):
        shape_type = shape_params.get('type')
        for x, y in holes:
            if shape_type == 'rectangle':
                width, height = shape_params['width'], shape_params['height']
                if not point_inside_rectangle(x, y, width, height, self.hole_radius):
                    return False
            elif shape_type == 'circle':
                radius = shape_params['radius']
                if not point_inside_circle(x, y, 0, 0, radius, self.hole_radius):
                    return False
            elif shape_type == 'ellipse':
                rx, ry = shape_params['rx'], shape_params['ry']
                if not point_inside_ellipse(x, y, 0, 0, rx, ry, self.hole_radius):
                    return False
            elif shape_type in ['triangle', 'hexagon']:
                polygon = shape_params['polygon']
                if not hole_inside_polygon(x, y, self.hole_radius, polygon):
                    return False
        return True


def add_circle_hole(msp, x, y, r, tool_compensation=None, layer=None):
    """Add a circular hole to the modelspace."""
    if tool_compensation is None:
        from tool_compensation import NoToolCompensation
        tool_compensation = NoToolCompensation()

    # For drill holes, we typically don't apply tool compensation to the hole size
    # The hole size in DXF represents the finished hole size
    # Tool compensation would be handled by the CAM software
    circle = msp.add_circle((x, y), r)
    if layer:
        circle.dxf.layer = layer