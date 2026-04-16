import math
import ezdxf


# -----------------------------
# Helpers
# -----------------------------
def get_positive_float(message):
    value = float(input(message))
    if value <= 0:
        raise ValueError("Value must be positive.")
    return value


def get_non_negative_int(message):
    value = int(input(message))
    if value < 0:
        raise ValueError("Value cannot be negative.")
    return value


def point_inside_circle(x, y, cx, cy, r, hole_r=0):
    return math.hypot(x - cx, y - cy) + hole_r <= r


def point_inside_rectangle(x, y, width, height, hole_r=0):
    return (
        x - hole_r >= 0 and
        x + hole_r <= width and
        y - hole_r >= 0 and
        y + hole_r <= height
    )


def point_inside_ellipse(x, y, cx, cy, rx, ry, hole_r=0):
    # approximate by shrinking ellipse by hole radius
    if rx <= hole_r or ry <= hole_r:
        return False
    val = ((x - cx) ** 2) / ((rx - hole_r) ** 2) + ((y - cy) ** 2) / ((ry - hole_r) ** 2)
    return val <= 1


def polygon_center(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def point_in_polygon(x, y, polygon):
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
    # simple check: center must be inside polygon
    # for MVP, this is enough. later we can do true edge distance validation
    return point_in_polygon(x, y, polygon)


def add_circle_hole(msp, x, y, r):
    msp.add_circle((x, y), r)


# -----------------------------
# Shape generators
# -----------------------------
def add_rectangle(msp, width, height):
    points = [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    msp.add_lwpolyline(points)
    return points[:-1]


def add_circle_shape(msp, radius):
    msp.add_circle((0, 0), radius)
    return (0, 0, radius)


def add_triangle(msp, width, height):
    points = [(0, 0), (width, 0), (width / 2, height), (0, 0)]
    msp.add_lwpolyline(points)
    return points[:-1]


def add_rounded_rectangle(msp, width, height, corner_r):
    if corner_r * 2 > width or corner_r * 2 > height:
        raise ValueError("Corner radius too large.")

    # lines
    msp.add_line((corner_r, 0), (width - corner_r, 0))
    msp.add_line((width, corner_r), (width, height - corner_r))
    msp.add_line((width - corner_r, height), (corner_r, height))
    msp.add_line((0, height - corner_r), (0, corner_r))

    # arcs
    msp.add_arc((width - corner_r, corner_r), corner_r, 270, 360)
    msp.add_arc((width - corner_r, height - corner_r), corner_r, 0, 90)
    msp.add_arc((corner_r, height - corner_r), corner_r, 90, 180)
    msp.add_arc((corner_r, corner_r), corner_r, 180, 270)

    # polygon for rough hole validation
    return [(0, 0), (width, 0), (width, height), (0, height)]


def add_ellipse_shape(msp, rx, ry):
    msp.add_ellipse(center=(0, 0), major_axis=(rx, 0), ratio=ry / rx)
    return (0, 0, rx, ry)


def add_hexagon(msp, side):
    points = []
    for i in range(6):
        angle_deg = 60 * i
        angle_rad = math.radians(angle_deg)
        x = side * math.cos(angle_rad)
        y = side * math.sin(angle_rad)
        points.append((x, y))
    points.append(points[0])
    msp.add_lwpolyline(points)
    return points[:-1]


# -----------------------------
# Hole menus
# -----------------------------
def hole_menu():
    print("\nHole options:")
    print("1. No holes")
    print("2. Center hole")
    print("3. Relative hole pattern")
    print("4. User-defined holes")
    return input("Choose hole option: ").strip()


# -----------------------------
# Rectangle with holes
# -----------------------------
def create_rectangle():
    width = get_positive_float("Enter width in mm: ")
    height = get_positive_float("Enter height in mm: ")

    doc = ezdxf.new()
    msp = doc.modelspace()

    polygon = add_rectangle(msp, width, height)

    choice = hole_menu()
    if choice == "1":
        filename = "rectangle.dxf"

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        cx, cy = width / 2, height / 2
        if not point_inside_rectangle(cx, cy, width, height, hole_r):
            print("Hole does not fit.")
            return
        add_circle_hole(msp, cx, cy, hole_r)
        filename = "rectangle_center_hole.dxf"

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        offset_x = get_positive_float("Enter X offset from left/right edge: ")
        offset_y = get_positive_float("Enter Y offset from bottom/top edge: ")

        holes = [
            (offset_x, offset_y),
            (width - offset_x, offset_y),
            (width - offset_x, height - offset_y),
            (offset_x, height - offset_y)
        ]

        for x, y in holes:
            if not point_inside_rectangle(x, y, width, height, hole_r):
                print("Relative holes do not fit.")
                return
            add_circle_hole(msp, x, y, hole_r)

        filename = "rectangle_relative_holes.dxf"

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            if not point_inside_rectangle(x, y, width, height, hole_r):
                print("Invalid hole position.")
                return
            add_circle_hole(msp, x, y, hole_r)
        filename = "rectangle_user_holes.dxf"

    else:
        print("Invalid hole option.")
        return

    doc.saveas(filename)
    print(f"DXF file '{filename}' created successfully!")


# -----------------------------
# Circle with holes
# -----------------------------
def create_circle():
    radius = get_positive_float("Enter circle radius in mm: ")

    doc = ezdxf.new()
    msp = doc.modelspace()

    cx, cy, r = add_circle_shape(msp, radius)

    choice = hole_menu()
    if choice == "1":
        filename = "circle.dxf"

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        if hole_r >= radius:
            print("Center hole too large.")
            return
        add_circle_hole(msp, 0, 0, hole_r)
        filename = "circle_center_hole.dxf"

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        hole_distance = get_positive_float("Enter distance of hole centers from center: ")

        holes = [
            (hole_distance, 0),
            (-hole_distance, 0),
            (0, hole_distance),
            (0, -hole_distance),
        ]

        for x, y in holes:
            if not point_inside_circle(x, y, 0, 0, radius, hole_r):
                print("Relative holes do not fit inside circle.")
                return
            add_circle_hole(msp, x, y, hole_r)

        filename = "circle_relative_holes.dxf"

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            if not point_inside_circle(x, y, 0, 0, radius, hole_r):
                print("Invalid hole position.")
                return
            add_circle_hole(msp, x, y, hole_r)
        filename = "circle_user_holes.dxf"

    else:
        print("Invalid hole option.")
        return

    doc.saveas(filename)
    print(f"DXF file '{filename}' created successfully!")


# -----------------------------
# Triangle with holes
# -----------------------------
def create_triangle():
    width = get_positive_float("Enter triangle base width in mm: ")
    height = get_positive_float("Enter triangle height in mm: ")

    doc = ezdxf.new()
    msp = doc.modelspace()

    polygon = add_triangle(msp, width, height)
    center_x, center_y = polygon_center(polygon)

    choice = hole_menu()
    if choice == "1":
        filename = "triangle.dxf"

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        if not hole_inside_polygon(center_x, center_y, hole_r, polygon):
            print("Center hole does not fit.")
            return
        add_circle_hole(msp, center_x, center_y, hole_r)
        filename = "triangle_center_hole.dxf"

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        offset = get_positive_float("Enter offset from vertices inward (simple version): ")

        holes = [
            (offset, offset),
            (width - offset, offset),
            (width / 2, height - offset),
        ]

        for x, y in holes:
            if not hole_inside_polygon(x, y, hole_r, polygon):
                print("Relative holes do not fit.")
                return
            add_circle_hole(msp, x, y, hole_r)

        filename = "triangle_relative_holes.dxf"

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            if not hole_inside_polygon(x, y, hole_r, polygon):
                print("Invalid hole position.")
                return
            add_circle_hole(msp, x, y, hole_r)
        filename = "triangle_user_holes.dxf"

    else:
        print("Invalid hole option.")
        return

    doc.saveas(filename)
    print(f"DXF file '{filename}' created successfully!")


# -----------------------------
# Rounded rectangle with holes
# -----------------------------
def create_rounded_rectangle():
    width = get_positive_float("Enter width in mm: ")
    height = get_positive_float("Enter height in mm: ")
    corner_r = get_positive_float("Enter corner radius in mm: ")

    doc = ezdxf.new()
    msp = doc.modelspace()

    polygon = add_rounded_rectangle(msp, width, height, corner_r)

    choice = hole_menu()
    if choice == "1":
        filename = "rounded_rectangle.dxf"

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        cx, cy = width / 2, height / 2
        if not point_inside_rectangle(cx, cy, width, height, hole_r):
            print("Center hole does not fit.")
            return
        add_circle_hole(msp, cx, cy, hole_r)
        filename = "rounded_rectangle_center_hole.dxf"

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        offset_x = get_positive_float("Enter X offset from left/right edge: ")
        offset_y = get_positive_float("Enter Y offset from bottom/top edge: ")

        holes = [
            (offset_x, offset_y),
            (width - offset_x, offset_y),
            (width - offset_x, height - offset_y),
            (offset_x, height - offset_y)
        ]

        for x, y in holes:
            if not point_inside_rectangle(x, y, width, height, hole_r):
                print("Relative holes do not fit.")
                return
            add_circle_hole(msp, x, y, hole_r)

        filename = "rounded_rectangle_relative_holes.dxf"

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            if not point_inside_rectangle(x, y, width, height, hole_r):
                print("Invalid hole position.")
                return
            add_circle_hole(msp, x, y, hole_r)
        filename = "rounded_rectangle_user_holes.dxf"

    else:
        print("Invalid hole option.")
        return

    doc.saveas(filename)
    print(f"DXF file '{filename}' created successfully!")


# -----------------------------
# Ellipse with holes
# -----------------------------
def create_ellipse():
    rx = get_positive_float("Enter ellipse X radius in mm: ")
    ry = get_positive_float("Enter ellipse Y radius in mm: ")

    doc = ezdxf.new()
    msp = doc.modelspace()

    cx, cy, _, _ = add_ellipse_shape(msp, rx, ry)

    choice = hole_menu()
    if choice == "1":
        filename = "ellipse.dxf"

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        if not point_inside_ellipse(0, 0, 0, 0, rx, ry, hole_r):
            print("Center hole too large.")
            return
        add_circle_hole(msp, 0, 0, hole_r)
        filename = "ellipse_center_hole.dxf"

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        offset_x = get_positive_float("Enter X offset from center: ")
        offset_y = get_positive_float("Enter Y offset from center: ")

        holes = [
            (offset_x, offset_y),
            (-offset_x, offset_y),
            (-offset_x, -offset_y),
            (offset_x, -offset_y)
        ]

        for x, y in holes:
            if not point_inside_ellipse(x, y, 0, 0, rx, ry, hole_r):
                print("Relative holes do not fit.")
                return
            add_circle_hole(msp, x, y, hole_r)

        filename = "ellipse_relative_holes.dxf"

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            if not point_inside_ellipse(x, y, 0, 0, rx, ry, hole_r):
                print("Invalid hole position.")
                return
            add_circle_hole(msp, x, y, hole_r)
        filename = "ellipse_user_holes.dxf"

    else:
        print("Invalid hole option.")
        return

    doc.saveas(filename)
    print(f"DXF file '{filename}' created successfully!")


# -----------------------------
# Hexagon with holes
# -----------------------------
def create_hexagon():
    side = get_positive_float("Enter hexagon side length in mm: ")

    doc = ezdxf.new()
    msp = doc.modelspace()

    polygon = add_hexagon(msp, side)
    center_x, center_y = polygon_center(polygon)

    choice = hole_menu()
    if choice == "1":
        filename = "hexagon.dxf"

    elif choice == "2":
        hole_r = get_positive_float("Enter center hole radius in mm: ")
        if not hole_inside_polygon(center_x, center_y, hole_r, polygon):
            print("Center hole does not fit.")
            return
        add_circle_hole(msp, center_x, center_y, hole_r)
        filename = "hexagon_center_hole.dxf"

    elif choice == "3":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        offset = get_positive_float("Enter offset from center along axes: ")

        holes = [
            (offset, 0),
            (-offset, 0),
            (offset / 2, offset),
            (-offset / 2, offset),
            (offset / 2, -offset),
            (-offset / 2, -offset),
        ]

        for x, y in holes:
            if not hole_inside_polygon(x, y, hole_r, polygon):
                print("Relative holes do not fit.")
                return
            add_circle_hole(msp, x, y, hole_r)

        filename = "hexagon_relative_holes.dxf"

    elif choice == "4":
        hole_r = get_positive_float("Enter hole radius in mm: ")
        n = get_non_negative_int("Enter number of holes: ")
        for i in range(n):
            print(f"\nHole {i+1}")
            x = float(input("Enter X position: "))
            y = float(input("Enter Y position: "))
            if not hole_inside_polygon(x, y, hole_r, polygon):
                print("Invalid hole position.")
                return
            add_circle_hole(msp, x, y, hole_r)
        filename = "hexagon_user_holes.dxf"

    else:
        print("Invalid hole option.")
        return

    doc.saveas(filename)
    print(f"DXF file '{filename}' created successfully!")


# -----------------------------
# Main menu
# -----------------------------
def show_menu():
    print("\n==== CNC DXF Generator ====")
    print("1. Rectangle")
    print("2. Circle")
    print("3. Triangle")
    print("4. Rounded rectangle")
    print("5. Ellipse")
    print("6. Hexagon")
    print("0. Exit")


def main():
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


main()