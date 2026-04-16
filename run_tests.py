import os
import shutil
import math
from dxf_generator import (
    create_rectangle_dxf, create_circle_dxf, create_triangle_dxf,
    create_rounded_rectangle_dxf, create_ellipse_dxf, create_hexagon_dxf,
    create_rectangle_dxf_with_slots,
    create_box_flat_pattern_dxf, create_l_bracket_flat_pattern_dxf, create_channel_flat_pattern_dxf
)
from holes import NoHoles, CenterHole, RelativeHoles, CustomHoles, GridHoles, CircularHoles
from tool_compensation import ToolCompensation, NoToolCompensation

OUTPUT_DIR = os.path.join('output', 'tests')

if os.path.isdir(OUTPUT_DIR):
    deleted_count = 0
    for entry in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, entry)
        if os.path.isfile(file_path) and entry.lower().endswith('.dxf'):
            os.remove(file_path)
            deleted_count += 1
    print(f"Old DXF test files cleared ({deleted_count} deleted)")
else:
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def save_test(name, fn, *args, **kwargs):
    path = os.path.join(OUTPUT_DIR, name)
    print(f"Generating: {path}")
    fn(*args, filename=path, **kwargs)


def run_tests():
    # 1. Rectangle outer cut (no compensation)
    save_test(
        '1_rectangle_outer_no_compensation.dxf',
        create_rectangle_dxf,
        200, 100,
        NoHoles(0),
        tool_compensation=NoToolCompensation()
    )

    # 2. Rectangle inner cutout (inside compensation simulating cut-in)
    save_test(
        '2_rectangle_inner_inside_compensation.dxf',
        create_rectangle_dxf,
        200, 100,
        NoHoles(0),
        tool_compensation=ToolCompensation(tool_diameter=10, cut_direction='inside')
    )

    # 3. Panel with 4 corner holes
    corner_holes = RelativeHoles(hole_radius=5, offset_x=20, offset_y=20)
    save_test(
        '3_panel_4_corner_holes.dxf',
        create_rectangle_dxf,
        250, 150,
        corner_holes,
        tool_compensation=NoToolCompensation()
    )

    # 4. Panel with grid holes
    grid_holes = GridHoles(hole_radius=4, rows=4, cols=6, spacing_x=30, spacing_y=25, start_x=25, start_y=25)
    save_test(
        '4_panel_grid_holes.dxf',
        create_rectangle_dxf,
        250, 150,
        grid_holes,
        tool_compensation=NoToolCompensation()
    )

    # 5. Panel with circular hole pattern (rectangle center-based positions)
    circle_positions = []
    center_x, center_y = 125, 75
    pattern_radius = 40
    pattern_count = 12
    for i in range(pattern_count):
        a = (2 * 3.141592653589793 * i) / pattern_count
        circle_positions.append((center_x + pattern_radius * math.cos(a), center_y + pattern_radius * math.sin(a)))
    circular_holes = CustomHoles(hole_radius=3, positions=circle_positions)
    save_test(
        '5_panel_circular_holes.dxf',
        create_rectangle_dxf,
        250, 150,
        circular_holes,
        tool_compensation=NoToolCompensation()
    )

    # 6. Panel with horizontal slot
    slot_list = [{'x': 125, 'y': 75, 'width': 80, 'height': 12, 'angle': 0, 'orientation': 'horizontal'}]
    save_test(
        '6_panel_horizontal_slot_no_compensation.dxf',
        create_rectangle_dxf_with_slots,
        250, 150,
        NoHoles(0),
        slot_list,
        tool_compensation=NoToolCompensation()
    )

    # 7. Panel with vertical slot
    slot_list = [{'x': 125, 'y': 75, 'width': 12, 'height': 80, 'angle': 90, 'orientation': 'vertical'}]
    save_test(
        '7_panel_vertical_slot_no_compensation.dxf',
        create_rectangle_dxf_with_slots,
        250, 150,
        NoHoles(0),
        slot_list,
        tool_compensation=NoToolCompensation()
    )

    # 8. Rounded rectangle with center hole
    rounded_center_holes = CustomHoles(hole_radius=8, positions=[(110, 60)])
    save_test(
        '8_rounded_rectangle_center_hole.dxf',
        create_rounded_rectangle_dxf,
        220, 120, 15,
        rounded_center_holes,
        tool_compensation=NoToolCompensation()
    )

    # Versions with tool compensation (outside cut) for key sample types
    save_test(
        '1_rectangle_outer_with_compensation.dxf',
        create_rectangle_dxf,
        200, 100,
        NoHoles(0),
        tool_compensation=ToolCompensation(tool_diameter=6, cut_direction='outside')
    )

    save_test(
        '4_panel_grid_holes_with_compensation.dxf',
        create_rectangle_dxf,
        250, 150,
        grid_holes,
        tool_compensation=ToolCompensation(tool_diameter=6, cut_direction='outside')
    )

    save_test(
        '6_panel_horizontal_slot_with_compensation.dxf',
        create_rectangle_dxf_with_slots,
        250, 150,
        NoHoles(0),
        [{'x': 125, 'y': 75, 'width': 80, 'height': 12, 'angle': 0, 'orientation': 'horizontal'}],
        tool_compensation=ToolCompensation(tool_diameter=6, cut_direction='outside')
    )

    save_test(
        '9_box_flat_pattern.dxf',
        create_box_flat_pattern_dxf,
        120, 80, 30
    )

    save_test(
        '10_l_bracket_flat_pattern.dxf',
        create_l_bracket_flat_pattern_dxf,
        100, 50, 40
    )

    save_test(
        '11_channel_flat_pattern.dxf',
        create_channel_flat_pattern_dxf,
        140, 60, 25
    )

    print('|-- Test generation complete --|')


if __name__ == '__main__':
    run_tests()
