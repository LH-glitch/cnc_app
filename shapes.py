"""
Shapes module for CNC DXF generator.
Contains functions to generate different geometric shapes in DXF format.
"""

import math
import ezdxf
from tool_compensation import NoToolCompensation
from cut_types import ProfileCut


def add_rectangle(msp, width, height, tool_compensation=None, layer=None):
    """Add a rectangle to the modelspace and return its boundary points."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    # Apply tool compensation
    offset_width, offset_height = tool_compensation.offset_rectangle(width, height)

    # Create rectangle with offset dimensions
    points = [(0, 0), (offset_width, 0), (offset_width, offset_height), (0, offset_height), (0, 0)]
    polyline = msp.add_lwpolyline(points)
    if layer:
        polyline.dxf.layer = layer
    return points[:-1]  # Return boundary without closing point


def add_flanged_shape(msp, boundary_points, bend_values=None, bend_top=0, bend_bottom=0, bend_left=0, bend_right=0, layer=None, fold_layer=None, relief_type='none', relief_size=3.0, relief_layer='RELIEF'):
    """Add flanges to a polygon boundary as optional bend edges."""
    if layer is None:
        layer = 'CUT'
    if fold_layer is None:
        fold_layer = 'FOLDS'

    if bend_values is None:
        bend_values = {}

    bend_values = {
        'top': float(bend_values.get('top', bend_top)),
        'bottom': float(bend_values.get('bottom', bend_bottom)),
        'left': float(bend_values.get('left', bend_left)),
        'right': float(bend_values.get('right', bend_right))
    }

    def make_line(point, direction):
        x0, y0 = point
        dx, dy = direction
        a = dy
        b = -dx
        c = -(a * x0 + b * y0)
        return (a, b, c)

    def intersect_lines(line1, line2):
        a1, b1, c1 = line1
        a2, b2, c2 = line2
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-9:
            return None
        x = (b1 * c2 - b2 * c1) / det
        y = (a2 * c1 - a1 * c2) / det
        return (x, y)

    if not boundary_points:
        return {
            'bend_top': bend_values['top'],
            'bend_bottom': bend_values['bottom'],
            'bend_left': bend_values['left'],
            'bend_right': bend_values['right'],
            'boundary': []
        }

    polygon = [tuple(point) for point in boundary_points]
    if polygon[0] != polygon[-1]:
        polygon.append(polygon[0])

    def signed_area(points):
        area = 0.0
        for i in range(len(points) - 1):
            x1, y1 = points[i]
            x2, y2 = points[i + 1]
            area += x1 * y2 - x2 * y1
        return area * 0.5

    def normalize_vector(dx, dy):
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 0 else (0.0, 0.0)

    def outward_normal(dx, dy, ccw):
        if ccw:
            normal = (dy, -dx)
        else:
            normal = (-dy, dx)
        return normalize_vector(*normal)

    def classify_direction(nx, ny):
        if abs(nx) >= abs(ny):
            return 'right' if nx > 0 else 'left'
        return 'top' if ny > 0 else 'bottom'

    ccw = signed_area(polygon) >= 0
    edges = []
    for index in range(len(polygon) - 1):
        x1, y1 = polygon[index]
        x2, y2 = polygon[index + 1]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue

        normal = outward_normal(dx, dy, ccw)
        edge_key = classify_direction(*normal)
        depth = bend_values.get(edge_key, 0)
        line = make_line((x1, y1), (dx, dy))

        edges.append({
            'x1': x1,
            'y1': y1,
            'x2': x2,
            'y2': y2,
            'dx': dx,
            'dy': dy,
            'normal': normal,
            'edge_key': edge_key,
            'depth': depth,
            'length': length,
            'line': line
        })

    offset_lines = []
    for edge in edges:
        if edge['depth'] > 0:
            offset_point = (
                edge['x1'] + edge['normal'][0] * edge['depth'],
                edge['y1'] + edge['normal'][1] * edge['depth']
            )
        else:
            offset_point = (edge['x1'], edge['y1'])
        offset_lines.append(make_line(offset_point, (edge['dx'], edge['dy'])))

    corner_points = []
    for index, edge in enumerate(edges):
        if edge['depth'] > 0:
            prev_index = (index - 1) % len(edges)
            next_index = (index + 1) % len(edges)
            prev_line = edges[prev_index]['line']
            next_line = edges[next_index]['line']
            prev_intersect = intersect_lines(offset_lines[index], prev_line)
            next_intersect = intersect_lines(offset_lines[index], next_line)
            corner_points.append((prev_intersect, next_intersect))
        else:
            corner_points.append(None)

    for index, edge in enumerate(edges):
        if edge['depth'] <= 0:
            continue

        p1 = (edge['x1'], edge['y1'])
        p2 = (edge['x2'], edge['y2'])
        corner_data = corner_points[index]
        if corner_data and corner_data[0] and corner_data[1]:
            q1 = corner_data[0]
            q2 = corner_data[1]
        else:
            # Fallback to offset along edge
            q1 = (
                edge['x1'] + edge['normal'][0] * edge['depth'],
                edge['y1'] + edge['normal'][1] * edge['depth']
            )
            q2 = (
                edge['x2'] + edge['normal'][0] * edge['depth'],
                edge['y2'] + edge['normal'][1] * edge['depth']
            )

        add_fold_line(msp, p1[0], p1[1], p2[0], p2[1], layer=fold_layer)
        flange_points = [p1, p2, q2, q1, p1]
        flange = msp.add_lwpolyline(flange_points)
        if layer:
            flange.dxf.layer = layer

        # Relief cuts at fold-line endpoints (bend intersections)
        _add_corner_relief(msp, p1[0], p1[1], relief_type, relief_size,
                           layer=layer, relief_layer=relief_layer)
        _add_corner_relief(msp, p2[0], p2[1], relief_type, relief_size,
                           layer=layer, relief_layer=relief_layer)

    return {
        'bend_top': bend_values['top'],
        'bend_bottom': bend_values['bottom'],
        'bend_left': bend_values['left'],
        'bend_right': bend_values['right'],
        'boundary': boundary_points
    }


def add_flanged_rectangle(msp, width, height, bend_top=0, bend_bottom=0, bend_left=0, bend_right=0, layer=None, fold_layer=None, relief_type='none', relief_size=3.0, relief_layer='RELIEF'):
    """Add a rectangular panel with optional edge flanges and fold lines."""
    if layer is None:
        layer = 'CUT'
    if fold_layer is None:
        fold_layer = 'FOLDS'

    boundary = [(0, 0), (width, 0), (width, height), (0, height)]
    base = msp.add_lwpolyline(boundary + [boundary[0]])
    base.dxf.layer = layer
    return add_flanged_shape(
        msp,
        boundary,
        bend_top=bend_top,
        bend_bottom=bend_bottom,
        bend_left=bend_left,
        bend_right=bend_right,
        layer=layer,
        fold_layer=fold_layer,
        relief_type=relief_type,
        relief_size=relief_size,
        relief_layer=relief_layer,
    )


def add_circle_shape(msp, radius, tool_compensation=None, layer=None):
    """Add a circle to the modelspace and return its center and radius."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    # Apply tool compensation
    cx, cy, offset_radius = tool_compensation.offset_circle(0, 0, radius)

    circle = msp.add_circle((cx, cy), offset_radius)
    if layer:
        circle.dxf.layer = layer
    return (cx, cy, offset_radius)


def add_triangle(msp, width, height, tool_compensation=None, layer=None):
    """Add an isosceles triangle to the modelspace and return its vertices."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    # For triangles, we'll apply a simple offset (not perfect but functional)
    offset_distance = tool_compensation.get_offset_distance()

    # Calculate offset points
    points = [(0, 0), (width, 0), (width / 2, height), (0, 0)]

    # Apply offset to each point (simple approximation)
    offset_points = []
    for x, y in points:
        offset_points.append((x + offset_distance, y + offset_distance))

    msp.add_lwpolyline(offset_points)
    return offset_points[:-1]  # Return vertices without closing point


def add_rounded_rectangle(msp, width, height, corner_r, tool_compensation=None, layer=None):
    """Add a rounded rectangle to the modelspace and return its boundary points."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    offset_distance = tool_compensation.get_offset_distance()
    offset_width = width + 2 * offset_distance
    offset_height = height + 2 * offset_distance
    offset_corner_r = max(0, corner_r + offset_distance)

    if offset_corner_r * 2 > offset_width or offset_corner_r * 2 > offset_height:
        # Fall back to regular rectangle if corner radius becomes too large
        points = [(0, 0), (offset_width, 0), (offset_width, offset_height), (0, offset_height), (0, 0)]
        msp.add_lwpolyline(points)
        return points[:-1]

    # Lines
    msp.add_line((offset_corner_r, 0), (offset_width - offset_corner_r, 0))
    msp.add_line((offset_width, offset_corner_r), (offset_width, offset_height - offset_corner_r))
    msp.add_line((offset_width - offset_corner_r, offset_height), (offset_corner_r, offset_height))
    msp.add_line((0, offset_height - offset_corner_r), (0, offset_corner_r))

    # Arcs
    msp.add_arc((offset_width - offset_corner_r, offset_corner_r), offset_corner_r, 270, 360)
    msp.add_arc((offset_width - offset_corner_r, offset_height - offset_corner_r), offset_corner_r, 0, 90)
    msp.add_arc((offset_corner_r, offset_height - offset_corner_r), offset_corner_r, 90, 180)
    msp.add_arc((offset_corner_r, offset_corner_r), offset_corner_r, 180, 270)

    # Return approximate boundary polygon for validation
    return [(0, 0), (offset_width, 0), (offset_width, offset_height), (0, offset_height)]


def add_ellipse_shape(msp, rx, ry, tool_compensation=None, layer=None):
    """Add an ellipse to the modelspace and return its parameters."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    offset_distance = tool_compensation.get_offset_distance()
    offset_rx = rx + offset_distance
    offset_ry = ry + offset_distance

    msp.add_ellipse(center=(0, 0), major_axis=(offset_rx, 0), ratio=offset_ry / offset_rx)
    return (0, 0, offset_rx, offset_ry)


def add_hexagon(msp, side, tool_compensation=None, layer=None):
    """Add a regular hexagon to the modelspace and return its vertices."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    offset_distance = tool_compensation.get_offset_distance()

    points = []
    for i in range(6):
        angle_deg = 60 * i
        angle_rad = math.radians(angle_deg)
        x = side * math.cos(angle_rad) + offset_distance
        y = side * math.sin(angle_rad) + offset_distance
        points.append((x, y))
    points.append(points[0])  # Close the polygon
    msp.add_lwpolyline(points)
    return points[:-1]  # Return vertices without closing point


def add_rectangular_slot(msp, x, y, width, height, angle=0, tool_compensation=None, layer=None):
    """Add a rectangular slot to the modelspace at specified position and angle."""
    if tool_compensation is None:
        tool_compensation = NoToolCompensation()

    # Apply tool compensation to slot dimensions
    offset_distance = tool_compensation.get_offset_distance()
    offset_width = width + 2 * abs(offset_distance)  # Slots always need clearance
    offset_height = height + 2 * abs(offset_distance)

    # Get the four corners of the slot
    from validation import get_slot_corners
    corners = get_slot_corners(x, y, offset_width, offset_height, angle)
    # Close the rectangle
    slot_points = corners + [corners[0]]
    polyline = msp.add_lwpolyline(slot_points)
    if layer:
        polyline.dxf.layer = layer
    return corners


def _add_dimension_text(msp, x, y, text, layer=None, height=4.0):
    """Add a small dimension label to the modelspace."""
    dim = msp.add_text(text, dxfattribs={
        'height': height,
        'layer': layer if layer else '0'
    })
    dim.dxf.insert = (x, y)
    try:
        dim.dxf.halign = 2
        dim.dxf.valign = 2
    except Exception:
        pass
    return dim


def _ensure_linetype(doc, name):
    """Ensure a linetype exists in the DXF document."""
    if name is None:
        return
    try:
        if name not in doc.linetypes:
            doc.linetypes.new(name, dxfattribs={
                'description': 'Dashed __ __ __'
            })
    except Exception:
        pass


def add_fold_line(msp, x1, y1, x2, y2, layer=None, linetype='DASHED'):
    """Add a fold or bend line to the DXF modelspace."""
    _ensure_linetype(msp.doc, linetype)
    line = msp.add_line((x1, y1), (x2, y2))
    if layer:
        line.dxf.layer = layer
    if linetype:
        try:
            line.dxf.linetype = linetype
        except Exception:
            pass
    return line


def add_groove_line(msp, x1, y1, x2, y2, layer=None, linetype='DASHED'):
    """Add a groove or score line to the DXF modelspace."""
    return add_fold_line(msp, x1, y1, x2, y2, layer=layer, linetype=linetype)


def _add_corner_relief(msp, cx, cy, relief_type, relief_size, layer='CUT', relief_layer='RELIEF'):
    """Add a corner relief cut at a fold-line intersection point.

    relief_type : 'square' | 'round' | 'v_cut' | 'none'
    relief_size : diameter / side length / V-depth in mm
    relief_layer: DXF layer for the relief geometry (default 'RELIEF' so it
                  renders distinctly in preview and can be isolated in CAM)
    """
    if not relief_type or relief_type == 'none' or relief_size <= 0:
        return
    use_layer = relief_layer if relief_layer else layer
    if relief_type == 'square':
        half = relief_size / 2.0
        pts = [
            (cx - half, cy - half),
            (cx + half, cy - half),
            (cx + half, cy + half),
            (cx - half, cy + half),
            (cx - half, cy - half),
        ]
        poly = msp.add_lwpolyline(pts)
        poly.dxf.layer = use_layer
    elif relief_type == 'round':
        circle = msp.add_circle((cx, cy), relief_size / 2.0)
        circle.dxf.layer = use_layer
    elif relief_type == 'v_cut':
        # V-cut: two diagonal lines from centre, width = relief_size
        half = relief_size / 2.0
        l1 = msp.add_line((cx - half, cy - half), (cx + half, cy + half))
        l2 = msp.add_line((cx + half, cy - half), (cx - half, cy + half))
        l1.dxf.layer = use_layer
        l2.dxf.layer = use_layer


def _bounding_box(points):
    """Return bounding box for a list of points."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _format_dim(value):
    """Format a dimension number for DXF labels."""
    return f"{value:.1f}"


def _area_of_rectangle(width, height):
    return width * height


def _area_of_box_pattern(base_w, base_d, flange):
    return base_w * base_d + 2 * base_w * flange + 2 * base_d * flange


def _area_of_l_bracket(base_w, base_d, flange):
    return base_w * base_d + base_d * flange


def _area_of_channel(base_w, base_d, flange):
    return base_w * base_d + 2 * base_d * flange


def add_box_flat_pattern(msp, base_width, base_depth, wall_height, material, layer=None, fold_layer=None, dim_layer=None, relief_type='none', relief_size=3.0, relief_layer='RELIEF'):
    """Add a simple flat box pattern with fold lines for a sheet metal box."""
    if layer is None:
        layer = 'CUT'
    if fold_layer is None:
        fold_layer = 'FOLDS'
    if dim_layer is None:
        dim_layer = 'DIMENSIONS'

    # Bend allowance for each flange
    bend_allowance = material.bend_allowance(90)
    flange_length = wall_height + bend_allowance

    origin_x = flange_length
    origin_y = flange_length

    # Center base
    base_points = [
        (origin_x, origin_y),
        (origin_x + base_width, origin_y),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x, origin_y + base_depth),
        (origin_x, origin_y)
    ]
    base = msp.add_lwpolyline(base_points)
    base.dxf.layer = layer

    # Draw all four flanges
    # Top flange
    top_flange_points = [
        (origin_x, origin_y + base_depth),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x + base_width, origin_y + base_depth + flange_length),
        (origin_x, origin_y + base_depth + flange_length),
        (origin_x, origin_y + base_depth)
    ]
    top_flange = msp.add_lwpolyline(top_flange_points)
    top_flange.dxf.layer = layer

    # Bottom flange
    bottom_flange_points = [
        (origin_x, origin_y),
        (origin_x + base_width, origin_y),
        (origin_x + base_width, origin_y - flange_length),
        (origin_x, origin_y - flange_length),
        (origin_x, origin_y)
    ]
    bottom_flange = msp.add_lwpolyline(bottom_flange_points)
    bottom_flange.dxf.layer = layer

    # Left flange
    left_flange_points = [
        (origin_x, origin_y),
        (origin_x - flange_length, origin_y),
        (origin_x - flange_length, origin_y + base_depth),
        (origin_x, origin_y + base_depth),
        (origin_x, origin_y)
    ]
    left_flange = msp.add_lwpolyline(left_flange_points)
    left_flange.dxf.layer = layer

    # Right flange
    right_flange_points = [
        (origin_x + base_width, origin_y),
        (origin_x + base_width + flange_length, origin_y),
        (origin_x + base_width + flange_length, origin_y + base_depth),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x + base_width, origin_y)
    ]
    right_flange = msp.add_lwpolyline(right_flange_points)
    right_flange.dxf.layer = layer

    # Fold lines (drawn as dashed lines)
    fold_lines = [
        ((origin_x, origin_y), (origin_x + base_width, origin_y)),
        ((origin_x, origin_y + base_depth), (origin_x + base_width, origin_y + base_depth)),
        ((origin_x, origin_y), (origin_x, origin_y + base_depth)),
        ((origin_x + base_width, origin_y), (origin_x + base_width, origin_y + base_depth))
    ]
    fold_info = []
    for start, end in fold_lines:
        add_fold_line(msp, start[0], start[1], end[0], end[1], layer=fold_layer)
        fold_info.append({
            'from': start,
            'to': end,
            'direction': 'up'
        })

    # Corner relief cuts at each fold-line intersection (4 base corners)
    for cx, cy in [
        (origin_x, origin_y),
        (origin_x + base_width, origin_y),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x, origin_y + base_depth),
    ]:
        _add_corner_relief(msp, cx, cy, relief_type, relief_size,
                           layer=layer, relief_layer=relief_layer)

    # Dimensions
    _add_dimension_text(msp, origin_x + base_width / 2, origin_y - flange_length / 2, _format_dim(base_width), layer=dim_layer)
    _add_dimension_text(msp, origin_x + base_width + flange_length / 2, origin_y + base_depth / 2, _format_dim(base_depth), layer=dim_layer)
    _add_dimension_text(msp, origin_x + base_width / 2, origin_y + base_depth + flange_length / 2, _format_dim(flange_length), layer=dim_layer)

    # TRUE OUTER BOUNDARY - Cross-shaped polygon tracing the complete flat pattern perimeter
    cross_boundary = [
        # Bottom-left corner of bottom flange
        (origin_x, origin_y - flange_length),
        # Bottom edge of bottom flange
        (origin_x + base_width, origin_y - flange_length),
        # Right edge of bottom flange to base
        (origin_x + base_width, origin_y),
        # Bottom-right edge of right flange
        (origin_x + base_width + flange_length, origin_y),
        # Right edge of right flange
        (origin_x + base_width + flange_length, origin_y + base_depth),
        # Top-right corner of right flange
        (origin_x + base_width, origin_y + base_depth),
        # Right edge of top flange to corner
        (origin_x + base_width, origin_y + base_depth + flange_length),
        # Top edge of top flange
        (origin_x, origin_y + base_depth + flange_length),
        # Left edge of top flange back to base
        (origin_x, origin_y + base_depth),
        # Top-left corner of left flange
        (origin_x - flange_length, origin_y + base_depth),
        # Left edge of left flange
        (origin_x - flange_length, origin_y),
        # Bottom-left corner of left flange
        (origin_x, origin_y),
        # Back to start
        (origin_x, origin_y - flange_length)
    ]

    min_x = origin_x - flange_length
    min_y = origin_y - flange_length
    max_x = origin_x + base_width + flange_length
    max_y = origin_y + base_depth + flange_length
    sheet_width = max_x - min_x
    sheet_height = max_y - min_y
    sheet_area = sheet_width * sheet_height
    pattern_area = _area_of_box_pattern(base_width, base_depth, flange_length)
    waste_area = max(sheet_area - pattern_area, 0)

    return {
        'template': 'box',
        'base_origin': (origin_x, origin_y),
        'base_width': base_width,
        'base_depth': base_depth,
        'wall_height': wall_height,
        'flange_length': flange_length,
        'fold_lines': fold_info,
        'sheet_size': (sheet_width, sheet_height),
        'sheet_area': sheet_area,
        'pattern_area': pattern_area,
        'waste_area': waste_area,
        'number_of_folds': len(fold_info),
        'fold_directions': [f['direction'] for f in fold_info],
        'bounding_box': (min_x, min_y, max_x, max_y),
        'boundary': cross_boundary,
        'boundary_points_count': len(cross_boundary)
    }


def add_l_bracket_flat_pattern(msp, base_width, base_depth, leg_height, material, layer=None, fold_layer=None, dim_layer=None, relief_type='none', relief_size=3.0, relief_layer='RELIEF'):
    """Add a flat pattern for a simple L-shaped bracket."""
    if layer is None:
        layer = 'CUT'
    if fold_layer is None:
        fold_layer = 'FOLDS'
    if dim_layer is None:
        dim_layer = 'DIMENSIONS'

    bend_allowance = material.bend_allowance(90)
    flange_length = leg_height + bend_allowance

    origin_x = 0
    origin_y = 0

    base_points = [
        (origin_x, origin_y),
        (origin_x + base_width, origin_y),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x, origin_y + base_depth),
        (origin_x, origin_y)
    ]
    base = msp.add_lwpolyline(base_points)
    base.dxf.layer = layer

    # Draw right flange
    flange_points = [
        (origin_x + base_width, origin_y),
        (origin_x + base_width + flange_length, origin_y),
        (origin_x + base_width + flange_length, origin_y + base_depth),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x + base_width, origin_y)
    ]
    flange = msp.add_lwpolyline(flange_points)
    flange.dxf.layer = layer

    # Fold line (drawn as dashed)
    fold_line = ((origin_x + base_width, origin_y), (origin_x + base_width, origin_y + base_depth))
    add_fold_line(msp, fold_line[0][0], fold_line[0][1], fold_line[1][0], fold_line[1][1], layer=fold_layer)

    # Corner relief cuts at fold-line endpoints (top and bottom of the single bend)
    _add_corner_relief(msp, origin_x + base_width, origin_y, relief_type, relief_size,
                       layer=layer, relief_layer=relief_layer)
    _add_corner_relief(msp, origin_x + base_width, origin_y + base_depth, relief_type, relief_size,
                       layer=layer, relief_layer=relief_layer)

    _add_dimension_text(msp, base_width / 2, -leg_height / 4, _format_dim(base_width), layer=dim_layer)
    _add_dimension_text(msp, base_width + flange_length / 2, base_depth / 2, _format_dim(flange_length), layer=dim_layer)
    _add_dimension_text(msp, base_width + flange_length + 5, base_depth / 2, _format_dim(base_depth), layer=dim_layer)

    # TRUE OUTER BOUNDARY - L-shaped polygon (rectangle for our simplified L-pattern)
    l_boundary = [
        (origin_x, origin_y),
        (origin_x + base_width + flange_length, origin_y),
        (origin_x + base_width + flange_length, origin_y + base_depth),
        (origin_x, origin_y + base_depth)
    ]

    min_x = origin_x
    min_y = origin_y
    max_x = origin_x + base_width + flange_length
    max_y = origin_y + base_depth
    sheet_width = max_x - min_x
    sheet_height = max_y - min_y
    sheet_area = sheet_width * sheet_height
    pattern_area = _area_of_l_bracket(base_width, base_depth, flange_length)
    waste_area = max(sheet_area - pattern_area, 0)

    return {
        'template': 'l_bracket',
        'base_width': base_width,
        'base_depth': base_depth,
        'leg_height': leg_height,
        'flange_length': flange_length,
        'fold_lines': [{
            'from': fold_line[0],
            'to': fold_line[1],
            'direction': 'up'
        }],
        'sheet_size': (sheet_width, sheet_height),
        'sheet_area': sheet_area,
        'pattern_area': pattern_area,
        'waste_area': waste_area,
        'number_of_folds': 1,
        'fold_directions': ['up'],
        'bounding_box': (min_x, min_y, max_x, max_y),
        'boundary': l_boundary,
        'boundary_points_count': len(l_boundary)
    }


def add_channel_flat_pattern(msp, base_width, base_depth, wall_height, material, layer=None, fold_layer=None, dim_layer=None, relief_type='none', relief_size=3.0, relief_layer='RELIEF'):
    """Add a flat pattern for a U-channel sheet metal template."""
    if layer is None:
        layer = 'CUT'
    if fold_layer is None:
        fold_layer = 'FOLDS'
    if dim_layer is None:
        dim_layer = 'DIMENSIONS'

    bend_allowance = material.bend_allowance(90)
    flange_length = wall_height + bend_allowance

    origin_x = flange_length
    origin_y = 0

    base_points = [
        (origin_x, origin_y),
        (origin_x + base_width, origin_y),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x, origin_y + base_depth),
        (origin_x, origin_y)
    ]
    base = msp.add_lwpolyline(base_points)
    base.dxf.layer = layer

    # Draw left flange
    left_flange_points = [
        (0, origin_y),
        (origin_x, origin_y),
        (origin_x, origin_y + base_depth),
        (0, origin_y + base_depth),
        (0, origin_y)
    ]
    left_flange = msp.add_lwpolyline(left_flange_points)
    left_flange.dxf.layer = layer

    # Draw right flange
    right_flange_points = [
        (origin_x + base_width, origin_y),
        (origin_x + base_width + flange_length, origin_y),
        (origin_x + base_width + flange_length, origin_y + base_depth),
        (origin_x + base_width, origin_y + base_depth),
        (origin_x + base_width, origin_y)
    ]
    right_flange = msp.add_lwpolyline(right_flange_points)
    right_flange.dxf.layer = layer

    # Fold lines (drawn as dashed)
    fold_lines = [
        ((origin_x, origin_y), (origin_x, origin_y + base_depth)),
        ((origin_x + base_width, origin_y), (origin_x + base_width, origin_y + base_depth))
    ]
    fold_info = []
    for start, end in fold_lines:
        add_fold_line(msp, start[0], start[1], end[0], end[1], layer=fold_layer)
        fold_info.append({
            'from': start,
            'to': end,
            'direction': 'up'
        })

    # Corner relief cuts at both fold-line endpoints (4 corners, 2 per fold line)
    for cx, cy in [
        (origin_x, origin_y),
        (origin_x, origin_y + base_depth),
        (origin_x + base_width, origin_y),
        (origin_x + base_width, origin_y + base_depth),
    ]:
        _add_corner_relief(msp, cx, cy, relief_type, relief_size,
                           layer=layer, relief_layer=relief_layer)

    _add_dimension_text(msp, origin_x + base_width / 2, -flange_length / 4, _format_dim(base_width), layer=dim_layer)
    _add_dimension_text(msp, origin_x + base_width + flange_length / 2, base_depth / 2, _format_dim(flange_length), layer=dim_layer)
    _add_dimension_text(msp, origin_x + base_width + flange_length + 5, base_depth / 2, _format_dim(base_depth), layer=dim_layer)

    # TRUE OUTER BOUNDARY - U-shaped polygon
    channel_boundary = [
        (0, origin_y),
        (origin_x + base_width + flange_length, origin_y),
        (origin_x + base_width + flange_length, origin_y + base_depth),
        (0, origin_y + base_depth)
    ]

    min_x = 0
    min_y = origin_y
    max_x = origin_x + base_width + flange_length
    max_y = origin_y + base_depth
    sheet_width = max_x - min_x
    sheet_height = max_y - min_y
    sheet_area = sheet_width * sheet_height
    pattern_area = _area_of_channel(base_width, base_depth, flange_length)
    waste_area = max(sheet_area - pattern_area, 0)

    return {
        'template': 'channel',
        'base_width': base_width,
        'base_depth': base_depth,
        'wall_height': wall_height,
        'flange_length': flange_length,
        'fold_lines': fold_info,
        'sheet_size': (sheet_width, sheet_height),
        'sheet_area': sheet_area,
        'pattern_area': pattern_area,
        'waste_area': waste_area,
        'number_of_folds': len(fold_info),
        'fold_directions': [f['direction'] for f in fold_info],
        'bounding_box': (min_x, min_y, max_x, max_y),
        'boundary': channel_boundary,
        'boundary_points_count': len(channel_boundary)
    }

