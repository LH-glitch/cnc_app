#!/usr/bin/env python3
"""
Simple test script to generate a box flat pattern DXF for testing the preview.
"""

from dxf_generator import create_box_flat_pattern_dxf

# Generate a simple box flat pattern
create_box_flat_pattern_dxf(
    base_width=100,
    base_depth=80,
    wall_height=50,
    filename="test_box.dxf"
)

print("Generated test_box.dxf")