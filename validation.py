"""
Validation module for CNC DXF generator.
Contains geometric validation functions for shapes and holes.
"""

import math


def polygon_center(points):
    """Calculate the centroid of a polygon."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def point_inside_circle(x, y, cx, cy, r, hole_r=0):
    """Check if a point with hole radius is inside a circle."""
    return math.hypot(x - cx, y - cy) + hole_r <= r


def point_inside_rectangle(x, y, width, height, hole_r=0):
    """Check if a point with hole radius is inside a rectangle."""
    return (
        x - hole_r >= 0 and
        x + hole_r <= width and
        y - hole_r >= 0 and
        y + hole_r <= height
    )


def point_inside_ellipse(x, y, cx, cy, rx, ry, hole_r=0):
    """Check if a point with hole radius is inside an ellipse."""
    if rx <= hole_r or ry <= hole_r:
        return False
    val = ((x - cx) ** 2) / ((rx - hole_r) ** 2) + ((y - cy) ** 2) / ((ry - hole_r) ** 2)
    return val <= 1


def point_in_polygon(x, y, polygon):
    """Check if a point is inside a polygon using ray casting."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def hole_inside_polygon(x, y, hole_r, polygon):
    """Check if a circular hole fits completely inside a polygon."""
    # For proper validation, we need to check that the entire hole fits
    # This is complex for arbitrary polygons. For now, use center check with margin
    # and add edge distance validation where possible
    return point_in_polygon(x, y, polygon) and polygon_edge_distance(x, y, polygon) >= hole_r


def slot_inside_polygon(slot_x, slot_y, slot_width, slot_height, slot_angle, polygon):
    """Check if a rectangular slot fits completely inside a polygon."""
    # Get the four corners of the slot
    corners = get_slot_corners(slot_x, slot_y, slot_width, slot_height, slot_angle)
    # Check if all corners are inside the polygon
    return all(point_in_polygon(cx, cy, polygon) for cx, cy in corners)


def polygon_edge_distance(x, y, polygon):
    """Calculate minimum distance from point to polygon edges."""
    min_distance = float('inf')
    n = len(polygon)
    for i in range(n):
        # Distance to line segment
        dist = point_to_line_distance(x, y, polygon[i], polygon[(i + 1) % n])
        min_distance = min(min_distance, dist)
    return min_distance


def point_to_line_distance(px, py, line_start, line_end):
    """Calculate distance from point to line segment."""
    x1, y1 = line_start
    x2, y2 = line_end
    
    # Vector from line start to end
    dx = x2 - x1
    dy = y2 - y1
    
    # If line segment has zero length
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    
    # Parameter t represents position along line segment
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    
    # Closest point on line segment
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    
    return math.hypot(px - closest_x, py - closest_y)


def get_slot_corners(x, y, width, height, angle):
    """Get the four corners of a rotated rectangular slot."""
    # Half dimensions
    hw = width / 2
    hh = height / 2
    
    # Corners relative to center (before rotation)
    corners = [
        (-hw, -hh),  # bottom-left
        (hw, -hh),   # bottom-right
        (hw, hh),    # top-right
        (-hw, hh)    # top-left
    ]
    
    # Rotate corners
    cos_a = math.cos(math.radians(angle))
    sin_a = math.sin(math.radians(angle))
    
    rotated_corners = []
    for cx, cy in corners:
        # Rotate point
        rx = cx * cos_a - cy * sin_a
        ry = cx * sin_a + cy * cos_a
        # Translate to slot position
        rotated_corners.append((x + rx, y + ry))
    
    return rotated_corners


def circle_fully_inside_shape(cx, cy, r, shape_type, shape_params):
    """Check if entire circle fits within shape boundaries."""
    if shape_type == 'rectangle':
        width, height = shape_params['width'], shape_params['height']
        return point_inside_rectangle(cx, cy, width, height, r)
    elif shape_type == 'circle':
        shape_r = shape_params['radius']
        return point_inside_circle(cx, cy, 0, 0, shape_r, r)
    elif shape_type == 'ellipse':
        rx, ry = shape_params['rx'], shape_params['ry']
        return point_inside_ellipse(cx, cy, 0, 0, rx, ry, r)
    elif shape_type in ['triangle', 'hexagon', 'rounded_rectangle']:
        polygon = shape_params['polygon']
        return hole_inside_polygon(cx, cy, r, polygon)
    else:
        return False


def slot_fully_inside_shape(sx, sy, sw, sh, angle, shape_type, shape_params):
    """Check if entire slot fits within shape boundaries."""
    if shape_type == 'rectangle':
        width, height = shape_params['width'], shape_params['height']
        # For rectangle, check all corners
        corners = get_slot_corners(sx, sy, sw, sh, angle)
        return all(
            0 <= cx <= width and 0 <= cy <= height
            for cx, cy in corners
        )
    elif shape_type == 'circle':
        # Check if all slot corners are inside the circle
        shape_r = shape_params['radius']
        corners = get_slot_corners(sx, sy, sw, sh, angle)
        return all(
            math.hypot(cx, cy) + max(sw, sh)/2 <= shape_r  # Rough approximation
            for cx, cy in corners
        )
    elif shape_type in ['triangle', 'hexagon', 'rounded_rectangle']:
        polygon = shape_params['polygon']
        return slot_inside_polygon(sx, sy, sw, sh, angle, polygon)
    else:
        return False