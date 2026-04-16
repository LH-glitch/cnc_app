#!/usr/bin/env python3
"""
Test the enhanced DXF preview functionality.
"""

import ezdxf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import NavigationToolbar2Tk
import os

def preview_dxf(filename):
    """Preview a DXF file with enhanced visualization."""

    if not os.path.exists(filename):
        print(f"File {filename} not found")
        return

    try:
        doc = ezdxf.readfile(filename)
        msp = doc.modelspace()
    except Exception as exc:
        print(f'Unable to load DXF: {exc}')
        return

    fig, ax = plt.subplots(figsize=(10, 8))
    bounds = [None, None, None, None]

    def update_bounds(x, y):
        nonlocal bounds
        if bounds[0] is None or x < bounds[0]:
            bounds[0] = x
        if bounds[1] is None or x > bounds[1]:
            bounds[1] = x
        if bounds[2] is None or y < bounds[2]:
            bounds[2] = y
        if bounds[3] is None or y > bounds[3]:
            bounds[3] = y

    for entity in msp:
        dxftype = entity.dxftype()
        layer_name = getattr(entity.dxf, 'layer', '').upper()
        if layer_name == 'CUT':
            color = 'red'
            linewidth = 2.0  # Thicker for CUT
            style = 'solid'
        elif layer_name == 'HOLES':
            color = 'green'
            linewidth = 1.5
            style = 'solid'
        elif layer_name == 'SLOTS':
            color = 'blue'
            linewidth = 1.5
            style = 'solid'
        elif layer_name in ('FOLDS', 'GROOVE'):
            color = 'gold'
            linewidth = 0.8  # Thinner for folds
            style = 'dashed'
        elif layer_name == 'DIMENSIONS':
            color = 'gray'
            linewidth = 0.5
            style = 'solid'
        elif layer_name == 'TEMPLATE':
            color = 'purple'
            linewidth = 1.0
            style = 'solid'
        else:
            color = 'black'
            linewidth = 1.0
            style = 'solid'

        if dxftype == 'LINE':
            start = entity.dxf.start
            end = entity.dxf.end
            ax.plot([start.x, end.x], [start.y, end.y], color=color, linestyle=style, linewidth=linewidth)
            update_bounds(start.x, start.y)
            update_bounds(end.x, end.y)
        elif dxftype == 'CIRCLE':
            center = entity.dxf.center
            radius = entity.dxf.radius
            circle = plt.Circle((center.x, center.y), radius, fill=False, edgecolor=color, linestyle=style, linewidth=linewidth)
            ax.add_patch(circle)
            update_bounds(center.x - radius, center.y - radius)
            update_bounds(center.x + radius, center.y + radius)
        elif dxftype == 'LWPOLYLINE':
            points = []
            for point in entity.get_points():
                points.append((point[0], point[1]))
            if points:
                xs, ys = zip(*points)
                ax.plot(xs, ys, color=color, linestyle=style, linewidth=linewidth)
                for x, y in points:
                    update_bounds(x, y)
        elif dxftype == 'POLYLINE':
            points = []
            for vertex in entity.vertices():
                location = vertex.dxf.location
                points.append((location.x, location.y))
            if points:
                xs, ys = zip(*points)
                ax.plot(xs, ys, color=color, linestyle=style, linewidth=linewidth)
                for x, y in points:
                    update_bounds(x, y)

    # Enhanced visualization features
    ax.set_aspect('equal', adjustable='datalim')  # Equal scaling

    # Add grid background
    ax.grid(True, which='both', color='lightgray', linestyle='-', linewidth=0.3, alpha=0.5)
    ax.set_axisbelow(True)  # Grid behind plot elements

    # Show origin (0,0) with crosshairs
    ax.axhline(y=0, color='black', linewidth=0.5, alpha=0.7)
    ax.axvline(x=0, color='black', linewidth=0.5, alpha=0.7)
    ax.scatter([0], [0], color='black', s=20, marker='x', alpha=0.7, label='Origin (0,0)')

    # Show bounding box if we have bounds
    if all(v is not None for v in bounds):
        min_x, max_x, min_y, max_y = bounds[0], bounds[1], bounds[2], bounds[3]
        bbox_rect = plt.Rectangle((min_x, min_y), max_x - min_x, max_y - min_y,
                                fill=False, edgecolor='darkblue', linewidth=1.0, linestyle='--', alpha=0.7)
        ax.add_patch(bbox_rect)

        # Add bounding box text
        ax.text(min_x, max_y + 5, f'Bounding Box: {max_x - min_x:.1f} x {max_y - min_y:.1f}',
               fontsize=9, color='darkblue', alpha=0.8,
               bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    ax.set_title(f'CNC DXF Preview: {os.path.basename(filename)}')

    # Set margins and zoom to fit content
    if all(v is not None for v in bounds):
        margin = max((bounds[1] - bounds[0]) * 0.1, (bounds[3] - bounds[2]) * 0.1, 10)
        ax.set_xlim(bounds[0] - margin, bounds[1] + margin)
        ax.set_ylim(bounds[2] - margin, bounds[3] + margin)

    # Add legend
    legend_elements = [
        plt.Line2D([0], [0], color='red', linewidth=2.0, label='CUT'),
        plt.Line2D([0], [0], color='green', linewidth=1.5, label='HOLES'),
        plt.Line2D([0], [0], color='blue', linewidth=1.5, label='SLOTS'),
        plt.Line2D([0], [0], color='gold', linewidth=0.8, linestyle='--', label='FOLDS'),
        plt.Line2D([0], [0], color='purple', linewidth=1.0, label='TEMPLATE'),
        plt.Line2D([0], [0], color='gray', linewidth=0.5, label='DIMENSIONS'),
        plt.Line2D([0], [0], color='black', linewidth=0.5, marker='x', label='Origin')
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=8, framealpha=0.9)

    plt.tight_layout()
    plt.savefig('preview_test.png', dpi=150, bbox_inches='tight')
    print("Preview saved as preview_test.png")

if __name__ == '__main__':
    preview_dxf('test_box.dxf')