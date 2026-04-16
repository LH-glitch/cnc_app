"""
Pattern generation module for CNC DXF generator.
Creates interior cut patterns within shape boundaries.
"""

import math
from typing import List, Tuple, Dict, Any


class PatternGenerator:
    """Generate interior cut patterns within shape boundaries."""

    def __init__(self):
        pass

    def generate_pattern(self, pattern_type: str, boundary: List[Tuple[float, float]],
                        pattern_size: float, spacing_x: float, spacing_y: float,
                        inner_margin: float) -> List[Dict[str, Any]]:
        """
        Generate pattern entities within the boundary.

        Args:
            pattern_type: Type of pattern ('circles', 'squares', 'triangles')
            boundary: List of (x, y) points defining the shape boundary
            pattern_size: Size of each pattern element
            spacing_x: Horizontal spacing between elements
            spacing_y: Vertical spacing between elements
            inner_margin: Margin from boundary to keep pattern away from edges

        Returns:
            List of pattern entities with type, position, and size info
        """
        if not boundary:
            return []

        # Calculate bounding box of the boundary
        min_x = min(p[0] for p in boundary)
        max_x = max(p[0] for p in boundary)
        min_y = min(p[1] for p in boundary)
        max_y = max(p[1] for p in boundary)

        # Apply inner margin
        min_x += inner_margin
        max_x -= inner_margin
        min_y += inner_margin
        max_y -= inner_margin

        # Ensure we have valid bounds
        if min_x >= max_x or min_y >= max_y:
            return []

        entities = []

        # Generate grid of pattern elements
        x = min_x
        while x <= max_x:
            y = min_y
            while y <= max_y:
                # Check if this position is inside the boundary
                if self._point_in_polygon((x, y), boundary):
                    entity = self._create_pattern_element(pattern_type, x, y, pattern_size)
                    if entity:
                        entities.append(entity)
                y += spacing_y
            x += spacing_x

        return entities

    def _point_in_polygon(self, point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
        """
        Check if a point is inside a polygon using ray casting algorithm.

        Args:
            point: (x, y) coordinates to test
            polygon: List of (x, y) points defining the polygon

        Returns:
            True if point is inside polygon
        """
        x, y = point
        n = len(polygon)
        inside = False

        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    def _create_pattern_element(self, pattern_type: str, x: float, y: float, size: float) -> Dict[str, Any]:
        """
        Create a single pattern element.

        Args:
            pattern_type: Type of pattern element
            x, y: Center position
            size: Size of the element

        Returns:
            Dictionary describing the pattern element
        """
        if pattern_type == 'circles':
            return {
                'type': 'circle',
                'center': (x, y),
                'radius': size / 2
            }
        elif pattern_type == 'squares':
            half_size = size / 2
            return {
                'type': 'polyline',
                'points': [
                    (x - half_size, y - half_size),
                    (x + half_size, y - half_size),
                    (x + half_size, y + half_size),
                    (x - half_size, y + half_size),
                    (x - half_size, y - half_size)  # Close the square
                ]
            }
        elif pattern_type == 'triangles':
            height = size * math.sqrt(3) / 2  # Height of equilateral triangle
            return {
                'type': 'polyline',
                'points': [
                    (x, y + height / 3),  # Top
                    (x - size / 2, y - height * 2 / 3),  # Bottom left
                    (x + size / 2, y - height * 2 / 3),  # Bottom right
                    (x, y + height / 3)  # Back to top
                ]
            }
        else:
            return None