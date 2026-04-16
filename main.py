"""
Main entry point for CNC DXF Generator.
Provides CLI interface and can be used programmatically for GUI/AI integration.
"""

from dxf_generator import (
    create_rectangle_dxf, create_circle_dxf, create_triangle_dxf,
    create_rounded_rectangle_dxf, create_ellipse_dxf, create_hexagon_dxf,
    create_rectangle_dxf_with_slots, create_circle_dxf_with_slots,
    create_triangle_dxf_with_slots, create_rounded_rectangle_dxf_with_slots,
    create_ellipse_dxf_with_slots, create_hexagon_dxf_with_slots
)
from holes import NoHoles, CenterHole, RelativeHoles, CustomHoles, GridHoles, CircularHoles
from tool_compensation import ToolCompensation, NoToolCompensation


# -----------------------------
# Input helpers
# -----------------------------
def get_positive_float(message):
    """Get a positive float from user input."""
    value = float(input(message))
    if value <= 0:
        raise ValueError("Value must be positive.")
    return value


def get_non_negative_int(message):
    """Get a non-negative integer from user input."""
    value = int(input(message))
    if value < 0:
        raise ValueError("Value cannot be negative.")
    return value


# -----------------------------
# Tool compensation creation from user input
# -----------------------------
def create_tool_compensation_from_input():
    """Create tool compensation based on user input."""
    use_compensation = input("Use tool diameter compensation? (y/n): ").strip().lower()

    if use_compensation == 'y':
        tool_diameter = get_positive_float("Enter tool diameter in mm: ")
        print("Cut direction:")
        print("1. Outside cut (tool stays outside the geometry)")
        print("2. Inside cut (tool cuts inside the geometry)")
        direction_choice = input("Choose cut direction (1/2): ").strip()

        if direction_choice == "1":
            cut_direction = "outside"
        elif direction_choice == "2":
            cut_direction = "inside"
        else:
            print("Invalid choice, defaulting to outside cut.")
            cut_direction = "outside"

        return ToolCompensation(tool_diameter, cut_direction)
    else:
        return NoToolCompensation()


# -----------------------------
# Hole pattern creation from user input
# -----------------------------
def create_hole_pattern_from_input():
    """Create a hole pattern based on user input."""
    print("\nHole options:")
    print("1. No holes")
    print("2. Center hole")
    print("3. Relative hole pattern")
    print("4. User-defined holes")
    print("5. Grid pattern")
    print("6. Circular pattern")

    choice = input("Choose hole option: ").strip()

    if choice == "1":
        return NoHoles(0)  # Hole radius doesn't matter for no holes

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        return CenterHole(hole_r)

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        print("Enter offsets for relative pattern:")
        offset_x = get_positive_float("Enter X offset: ")
        offset_y = get_positive_float("Enter Y offset: ")
        return RelativeHoles(hole_r, offset_x, offset_y)

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        positions = []
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            positions.append((x, y))
        return CustomHoles(hole_r, positions)

    elif choice == "5":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        rows = get_non_negative_int("Enter number of rows: ")
        cols = get_non_negative_int("Enter number of columns: ")
        spacing_x = get_positive_float("Enter X spacing between holes: ")
        spacing_y = get_positive_float("Enter Y spacing between holes: ")
        start_x = float(input("Enter starting X position (default 0): ") or 0)
        start_y = float(input("Enter starting Y position (default 0): ") or 0)
        return GridHoles(hole_r, rows, cols, spacing_x, spacing_y, start_x, start_y)

    elif choice == "6":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        count = get_non_negative_int("Enter number of holes: ")
        radius = get_positive_float("Enter pattern radius: ")
        start_angle = float(input("Enter starting angle in degrees (default 0): ") or 0)
        return CircularHoles(hole_r, count, radius, start_angle)

    else:
        raise ValueError("Invalid hole option.")


# -----------------------------
# Slot creation from user input
# -----------------------------
def create_slots_from_input():
    """Create slots based on user input."""
    slots = []
    add_slots = input("Add slots to the shape? (y/n): ").strip().lower()

    if add_slots == 'y':
        n = get_non_negative_int("Enter number of slots: ")
        for i in range(n):
            print(f"\nSlot {i+1}")
            x = float(input("Enter slot center X position: "))
            y = float(input("Enter slot center Y position: "))
            width = get_positive_float("Enter slot width: ")
            height = get_positive_float("Enter slot height: ")
            angle = float(input("Enter slot angle in degrees (0=horizontal, 90=vertical): ") or 0)

            print("Slot orientation:")
            print("1. Horizontal")
            print("2. Vertical")
            orientation_choice = input("Choose orientation (1/2): ").strip()
            if orientation_choice == "2":
                orientation = "vertical"
            else:
                orientation = "horizontal"

            # Store as dictionary for new format
            slots.append({
                'x': x,
                'y': y,
                'width': width,
                'height': height,
                'angle': angle,
                'orientation': orientation
            })

    return slots


# -----------------------------
# Shape creation functions with user input
# -----------------------------
def create_rectangle():
    """Create a rectangle with user input."""
    width = get_positive_float("Enter width in mm: ")
    height = get_positive_float("Enter height in mm: ")
    tool_compensation = create_tool_compensation_from_input()
    hole_pattern = create_hole_pattern_from_input()
    slots = create_slots_from_input()

    if slots:
        filename = f"rectangle_{hole_pattern.__class__.__name__.lower()}_with_slots.dxf"
        create_rectangle_dxf_with_slots(width, height, hole_pattern, slots, filename, tool_compensation)
    else:
        filename = f"rectangle_{hole_pattern.__class__.__name__.lower()}.dxf"
        create_rectangle_dxf(width, height, hole_pattern, filename, tool_compensation)


def create_circle():
    """Create a circle with user input."""
    radius = get_positive_float("Enter circle radius in mm: ")
    tool_compensation = create_tool_compensation_from_input()
    hole_pattern = create_hole_pattern_from_input()
    slots = create_slots_from_input()

    if slots:
        filename = f"circle_{hole_pattern.__class__.__name__.lower()}_with_slots.dxf"
        create_circle_dxf_with_slots(radius, hole_pattern, slots, filename, tool_compensation)
    else:
        filename = f"circle_{hole_pattern.__class__.__name__.lower()}.dxf"
        create_circle_dxf(radius, hole_pattern, filename, tool_compensation)


def create_triangle():
    """Create a triangle with user input."""
    width = get_positive_float("Enter triangle base width in mm: ")
    height = get_positive_float("Enter triangle height in mm: ")
    tool_compensation = create_tool_compensation_from_input()
    hole_pattern = create_hole_pattern_from_input()
    slots = create_slots_from_input()

    if slots:
        filename = f"triangle_{hole_pattern.__class__.__name__.lower()}_with_slots.dxf"
        create_triangle_dxf_with_slots(width, height, hole_pattern, slots, filename, tool_compensation)
    else:
        filename = f"triangle_{hole_pattern.__class__.__name__.lower()}.dxf"
        create_triangle_dxf(width, height, hole_pattern, filename, tool_compensation)


def create_rounded_rectangle():
    """Create a rounded rectangle with user input."""
    width = get_positive_float("Enter width in mm: ")
    height = get_positive_float("Enter height in mm: ")
    corner_r = get_positive_float("Enter corner radius in mm: ")
    tool_compensation = create_tool_compensation_from_input()
    hole_pattern = create_hole_pattern_from_input()
    slots = create_slots_from_input()

    if slots:
        filename = f"rounded_rectangle_{hole_pattern.__class__.__name__.lower()}_with_slots.dxf"
        create_rounded_rectangle_dxf_with_slots(width, height, corner_r, hole_pattern, slots, filename, tool_compensation)
    else:
        filename = f"rounded_rectangle_{hole_pattern.__class__.__name__.lower()}.dxf"
        create_rounded_rectangle_dxf(width, height, corner_r, hole_pattern, filename, tool_compensation)


def create_ellipse():
    """Create an ellipse with user input."""
    rx = get_positive_float("Enter ellipse X radius in mm: ")
    ry = get_positive_float("Enter ellipse Y radius in mm: ")
    tool_compensation = create_tool_compensation_from_input()
    hole_pattern = create_hole_pattern_from_input()
    slots = create_slots_from_input()

    if slots:
        filename = f"ellipse_{hole_pattern.__class__.__name__.lower()}_with_slots.dxf"
        create_ellipse_dxf_with_slots(rx, ry, hole_pattern, slots, filename, tool_compensation)
    else:
        filename = f"ellipse_{hole_pattern.__class__.__name__.lower()}.dxf"
        create_ellipse_dxf(rx, ry, hole_pattern, filename, tool_compensation)


def create_hexagon():
    """Create a hexagon with user input."""
    side = get_positive_float("Enter hexagon side length in mm: ")
    tool_compensation = create_tool_compensation_from_input()
    hole_pattern = create_hole_pattern_from_input()
    slots = create_slots_from_input()

    if slots:
        filename = f"hexagon_{hole_pattern.__class__.__name__.lower()}_with_slots.dxf"
        create_hexagon_dxf_with_slots(side, hole_pattern, slots, filename, tool_compensation)
    else:
        filename = f"hexagon_{hole_pattern.__class__.__name__.lower()}.dxf"
        create_hexagon_dxf(side, hole_pattern, filename, tool_compensation)


# -----------------------------
# Main menu
# -----------------------------
def show_menu():
    """Display the main menu."""
    print("\n==== CNC DXF Generator ====")
    print("1. Rectangle")
    print("2. Circle")
    print("3. Triangle")
    print("4. Rounded rectangle")
    print("5. Ellipse")
    print("6. Hexagon")
    print("0. Exit")


def main():
    """Main CLI loop."""
    while True:
        try:
            show_menu()
            choice = input("Choose shape: ").strip()

            if choice == "1":
                create_rectangle()
            elif choice == "2":
                create_circle()
            elif choice == "3":
                create_triangle()
            elif choice == "4":
                create_rounded_rectangle()
            elif choice == "5":
                create_ellipse()
            elif choice == "6":
                create_hexagon()
            elif choice == "0":
                print("Exiting program.")
                break
            else:
                print("Invalid choice.")

        except ValueError as e:
            print(f"Input error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
