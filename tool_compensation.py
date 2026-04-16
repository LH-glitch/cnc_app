"""
Tool compensation module for CNC DXF generator.
Handles tool diameter compensation and geometry offsetting.
"""

import math
from validation import polygon_center


class ToolCompensation:
    """Handle tool diameter compensation for CNC machining."""

    def __init__(self, tool_diameter, cut_direction='outside'):
        """
        Initialize tool compensation.

        Args:
            tool_diameter (float): Diameter of the cutting tool in mm
            cut_direction (str): 'inside' or 'outside' cut
        """
        self.tool_diameter = tool_diameter
        self.cut_direction = cut_direction
        self.tool_radius = tool_diameter / 2

    def get_offset_distance(self):
        """Get the offset distance based on cut direction."""
        if self.cut_direction == 'inside':
            return -self.tool_radius  # Negative offset for inside cuts
        elif self.cut_direction == 'outside':
            return self.tool_radius   # Positive offset for outside cuts
        else:
            raise ValueError(f"Invalid cut direction: {self.cut_direction}")

    def offset_point(self, x, y, offset_distance=None):
        """Offset a point by the tool radius."""
        if offset_distance is None:
            offset_distance = self.get_offset_distance()
        return x, y  # Points don't need offsetting for basic holes

    def offset_line(self, x1, y1, x2, y2, offset_distance=None):
        """Offset a line segment."""
        if offset_distance is None:
            offset_distance = self.get_offset_distance()

        # Calculate perpendicular vector
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx*dx + dy*dy)

        if length == 0:
            return x1, y1, x2, y2

        # Perpendicular unit vector
        px = -dy / length
        py = dx / length

        # Offset both points
        ox1 = x1 + px * offset_distance
        oy1 = y1 + py * offset_distance
        ox2 = x2 + px * offset_distance
        oy2 = y2 + py * offset_distance

        return ox1, oy1, ox2, oy2

    def offset_circle(self, cx, cy, r, offset_distance=None):
        """Offset a circle."""
        if offset_distance is None:
            offset_distance = self.get_offset_distance()
        return cx, cy, r + offset_distance

    def offset_rectangle(self, width, height, offset_distance=None):
        """Offset a rectangle."""
        if offset_distance is None:
            offset_distance = self.get_offset_distance()
        return width + 2 * offset_distance, height + 2 * offset_distance

    def offset_polygon(self, polygon, offset_distance=None):
        """Offset a polygon using simple vertex offset."""
        if offset_distance is None:
            offset_distance = self.get_offset_distance()

        # Simple vertex offset (not perfect for complex shapes)
        # For production use, would need proper polygon offsetting algorithm
        offset_polygon = []
        for x, y in polygon:
            offset_polygon.append((x, y))  # For now, no offset for polygons
        return offset_polygon


class NoToolCompensation:
    """No tool compensation - use original geometry."""

    def __init__(self):
        self.tool_diameter = 0
        self.cut_direction = 'none'
        self.tool_radius = 0

    def get_offset_distance(self):
        return 0

    def offset_point(self, x, y, offset_distance=None):
        return x, y

    def offset_line(self, x1, y1, x2, y2, offset_distance=None):
        return x1, y1, x2, y2

    def offset_circle(self, cx, cy, r, offset_distance=None):
        return cx, cy, r

    def offset_rectangle(self, width, height, offset_distance=None):
        return width, height

    def offset_polygon(self, polygon, offset_distance=None):
        return polygon