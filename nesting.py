"""
Material Optimization (Nesting) module for CNC DXF generator.
Provides algorithms for optimizing material usage by arranging multiple parts on sheets.
"""

import math
from typing import List, Tuple, Dict, Optional
import copy


class Part:
    """Represents a part to be nested with its dimensions and properties."""

    def __init__(self, width: float, height: float, name: str = "", rotation_allowed: bool = True):
        self.width = width
        self.height = height
        self.name = name
        self.rotation_allowed = rotation_allowed
        self.x = 0.0  # Position on sheet
        self.y = 0.0
        self.rotation = 0  # 0 or 90 degrees

    def get_current_dimensions(self) -> Tuple[float, float]:
        """Get the current width and height considering rotation."""
        if self.rotation == 0:
            return self.width, self.height
        else:
            return self.height, self.width

    def get_area(self) -> float:
        """Get the area of the part."""
        return self.width * self.height

    def rotate(self):
        """Rotate the part 90 degrees."""
        if self.rotation_allowed:
            self.rotation = (self.rotation + 90) % 180

    def copy(self):
        """Create a copy of the part."""
        new_part = Part(self.width, self.height, self.name, self.rotation_allowed)
        new_part.x = self.x
        new_part.y = self.y
        new_part.rotation = self.rotation
        return new_part


class Sheet:
    """Represents a sheet of material with placed parts."""

    def __init__(self, width: float, height: float):
        self.width = width
        self.height = height
        self.parts: List[Part] = []
        self.used_area = 0.0

    def get_total_area(self) -> float:
        """Get the total area of the sheet."""
        return self.width * self.height

    def get_used_area(self) -> float:
        """Get the total area used by placed parts."""
        return sum(part.get_area() for part in self.parts)

    def get_waste_area(self) -> float:
        """Get the waste area (unused space)."""
        return self.get_total_area() - self.get_used_area()

    def get_utilization_percentage(self) -> float:
        """Get the material utilization percentage."""
        if self.get_total_area() == 0:
            return 0.0
        return (self.get_used_area() / self.get_total_area()) * 100.0

    def can_place_part(self, part: Part, x: float, y: float) -> bool:
        """Check if a part can be placed at the given position."""
        part_width, part_height = part.get_current_dimensions()

        # Check if part fits within sheet boundaries
        if x + part_width > self.width or y + part_height > self.height:
            return False

        # Check for overlap with existing parts
        for existing_part in self.parts:
            if self.parts_overlap(part, x, y, existing_part):
                return False

        return True

    def parts_overlap(self, part1: Part, x1: float, y1: float, part2: Part) -> bool:
        """Check if two parts overlap."""
        w1, h1 = part1.get_current_dimensions()
        w2, h2 = part2.get_current_dimensions()

        # Check for rectangle overlap
        return not (x1 + w1 <= part2.x or
                   part2.x + w2 <= x1 or
                   y1 + h1 <= part2.y or
                   part2.y + h2 <= y1)

    def place_part(self, part: Part, x: float, y: float) -> bool:
        """Place a part at the given position if possible."""
        if self.can_place_part(part, x, y):
            part.x = x
            part.y = y
            self.parts.append(part)
            self.used_area = self.get_used_area()  # Recalculate
            return True
        return False

    def remove_part(self, part: Part):
        """Remove a part from the sheet."""
        if part in self.parts:
            self.parts.remove(part)
            self.used_area = self.get_used_area()  # Recalculate


class NestingAlgorithm:
    """Base class for nesting algorithms."""

    def nest_parts(self, parts: List[Part], sheet_width: float, sheet_height: float) -> List[Sheet]:
        """Nest parts onto sheets. To be implemented by subclasses."""
        raise NotImplementedError


class BottomLeftFill(NestingAlgorithm):
    """Bottom-left fill nesting algorithm."""

    def nest_parts(self, parts: List[Part], sheet_width: float, sheet_height: float) -> List[Sheet]:
        """Nest parts using bottom-left fill algorithm."""
        sheets = []
        remaining_parts = parts.copy()

        while remaining_parts:
            sheet = Sheet(sheet_width, sheet_height)
            placed_parts = []

            # Sort remaining parts by area (largest first)
            remaining_parts.sort(key=lambda p: p.get_area(), reverse=True)

            for part in remaining_parts[:]:  # Copy the list to avoid modification during iteration
                placed = False

                # Try placing without rotation first
                if self._try_place_part(sheet, part, 0):
                    placed = True
                # If rotation is allowed, try with rotation
                elif part.rotation_allowed:
                    part.rotate()
                    if self._try_place_part(sheet, part, 0):
                        placed = True
                    else:
                        # Rotate back if placement failed
                        part.rotate()

                if placed:
                    placed_parts.append(part)
                    remaining_parts.remove(part)

            if placed_parts:
                sheets.append(sheet)
            else:
                # No more parts can fit, create a new sheet for remaining parts
                break

        # If there are still remaining parts, put them on additional sheets
        while remaining_parts:
            sheet = Sheet(sheet_width, sheet_height)
            # Just place them in a simple grid pattern
            x, y = 0, 0
            max_height_in_row = 0

            for part in remaining_parts[:]:
                part_width, part_height = part.get_current_dimensions()

                if x + part_width > sheet_width:
                    # Move to next row
                    x = 0
                    y += max_height_in_row
                    max_height_in_row = 0

                if y + part_height > sheet_height:
                    # Sheet is full
                    break

                if sheet.place_part(part, x, y):
                    remaining_parts.remove(part)
                    x += part_width
                    max_height_in_row = max(max_height_in_row, part_height)

            sheets.append(sheet)
            if not remaining_parts:
                break

        return sheets

    def _try_place_part(self, sheet: Sheet, part: Part, start_y: float) -> bool:
        """Try to place a part on the sheet starting from a given Y position."""
        part_width, part_height = part.get_current_dimensions()

        # Try positions from bottom-left
        for y in range(int(start_y), int(sheet.height - part_height) + 1):
            for x in range(int(sheet.width - part_width) + 1):
                if sheet.can_place_part(part, float(x), float(y)):
                    sheet.place_part(part, float(x), float(y))
                    return True
        return False


def compute_grid_fit(width: float, height: float, sheet_width: float, sheet_height: float) -> Tuple[int, int, int]:
    """Compute how many parts fit in a simple rows-and-columns grid."""
    if width <= 0 or height <= 0:
        return 0, 0, 0
    cols = int(sheet_width // width)
    rows = int(sheet_height // height)
    return cols * rows, cols, rows


def evaluate_layout_option(width: float, height: float, sheet_width: float, sheet_height: float) -> Dict:
    """Evaluate a layout option for a given orientation."""
    count, cols, rows = compute_grid_fit(width, height, sheet_width, sheet_height)
    sheet_area = sheet_width * sheet_height
    used_area = width * height * count
    waste_area = sheet_area - used_area if count > 0 else sheet_area
    utilization = (used_area / sheet_area * 100.0) if sheet_area > 0 else 0.0
    return {
        'count': count,
        'cols': cols,
        'rows': rows,
        'used_area': used_area,
        'waste_area': waste_area,
        'utilization': utilization
    }


def get_part_dimensions(template_name: str, params: Dict, material=None) -> Tuple[float, float]:
    """Get the dimensions of a part based on template and parameters."""
    if template_name == 'Rectangle':
        width = float(params.get('width', 100))
        height = float(params.get('height', 50))
        return width, height

    elif template_name == 'Box Flat Pattern':
        base_width = float(params.get('base_width', 80))
        base_depth = float(params.get('base_depth', 40))
        wall_height = float(params.get('wall_height', 20))

        if material is None:
            from dxf_generator import Material
            material = Material()

        bend_allowance = material.bend_allowance(90)
        flange_length = wall_height + bend_allowance

        width = base_width + 2 * flange_length
        height = base_depth + 2 * flange_length
        return width, height

    elif template_name == 'L Bracket Flat Pattern':
        base_width = float(params.get('base_width', 80))
        base_depth = float(params.get('base_depth', 40))
        leg_height = float(params.get('leg_height', 30))

        if material is None:
            from dxf_generator import Material
            material = Material()

        bend_allowance = material.bend_allowance(90)
        flange_length = leg_height + bend_allowance

        width = base_width + flange_length
        height = base_depth
        return width, height

    elif template_name == 'Channel Flat Pattern':
        base_width = float(params.get('base_width', 80))
        base_depth = float(params.get('base_depth', 40))
        wall_height = float(params.get('wall_height', 20))

        if material is None:
            from dxf_generator import Material
            material = Material()

        bend_allowance = material.bend_allowance(90)
        flange_length = wall_height + bend_allowance

        width = base_width + 2 * flange_length
        height = base_depth
        return width, height

    # Default fallback
    return 100.0, 50.0


def suggest_orientation_layout(template_name: str, params: Dict, sheet_width: float, sheet_height: float) -> Dict:
    """Compare 0° and 90° layouts and suggest the better orientation."""
    width, height = get_part_dimensions(template_name, params)
    options = []

    for orientation in [0, 90]:
        if orientation == 0:
            layout_width, layout_height = width, height
        else:
            layout_width, layout_height = height, width

        layout = evaluate_layout_option(layout_width, layout_height, sheet_width, sheet_height)
        layout.update({'orientation': orientation, 'part_width': layout_width, 'part_height': layout_height})
        options.append(layout)

    best = max(options, key=lambda option: (option['count'], option['utilization']))
    suggestion_lines = []
    if best['orientation'] == 90 and best['count'] > options[0]['count']:
        suggestion_lines.append(
            f'Rotate part layout by 90° to fit {best["count"]} parts per sheet instead of {options[0]["count"]}.')
    elif best['orientation'] == 0 and options[1]['count'] > options[0]['count']:
        suggestion_lines.append(
            f'Keep parts at 0° orientation; rotated layout fits fewer parts ({options[1]["count"]}).')

    return {
        'options': options,
        'best': best,
        'suggestions': suggestion_lines
    }


def suggest_dimension_adjustments(template_name: str, params: Dict, sheet_width: float, sheet_height: float,
                                  max_adjust: int = 5) -> List[str]:
    """Suggest small dimension changes to improve nesting fit."""
    width, height = get_part_dimensions(template_name, params)
    original_layout = suggest_orientation_layout(template_name, params, sheet_width, sheet_height)
    original_count = original_layout['best']['count']
    suggestions = []

    for delta in range(1, max_adjust + 1):
        for dimension in ('width', 'height'):
            adjusted_width = width - delta if dimension == 'width' else width
            adjusted_height = height - delta if dimension == 'height' else height

            if adjusted_width <= 0 or adjusted_height <= 0:
                continue

            for orientation in [0, 90]:
                if orientation == 0:
                    layout_width, layout_height = adjusted_width, adjusted_height
                else:
                    layout_width, layout_height = adjusted_height, adjusted_width

                count, _, _ = compute_grid_fit(layout_width, layout_height, sheet_width, sheet_height)
                if count > original_count:
                    suggestions.append(
                        f'Reduce {dimension} by {delta} mm to fit {count} parts per sheet ' \
                        f'(current best {original_count}).')
                    break
            if suggestions and suggestions[-1].startswith(f'Reduce {dimension} by {delta}'):
                break

    # Avoid duplicate suggestions
    unique_suggestions = []
    for s in suggestions:
        if s not in unique_suggestions:
            unique_suggestions.append(s)

    return unique_suggestions


def create_parts_from_template(template_name: str, params: Dict, count: int, material=None) -> List[Part]:
    """Create multiple identical parts from a template."""
    width, height = get_part_dimensions(template_name, params, material)
    parts = []

    for i in range(count):
        name = f"{template_name} #{i+1}"
        part = Part(width, height, name, rotation_allowed=True)
        parts.append(part)
    return parts


def _create_parts_with_fixed_orientation(template_name: str, params: Dict, count: int, orientation: int,
                                         material=None) -> List[Part]:
    parts = create_parts_from_template(template_name, params, count, material)
    if orientation == 90:
        for part in parts:
            part.rotate()
    return parts


def optimize_nesting(template_name, params, sheet_width, sheet_height, part_count, material=None):
    parts = create_parts_from_template(template_name, params, part_count, material)
    algorithm = BottomLeftFill()
    sheets = algorithm.nest_parts(parts, sheet_width, sheet_height)

    orientation_summary = suggest_orientation_layout(template_name, params, sheet_width, sheet_height)
    dimension_suggestions = suggest_dimension_adjustments(template_name, params, sheet_width, sheet_height)

    total_parts_placed = sum(len(sheet.parts) for sheet in sheets)
    total_sheets_used = len(sheets)
    if sheets:
        avg_utilization = sum(sheet.get_utilization_percentage() for sheet in sheets) / len(sheets)
        total_waste = sum(sheet.get_waste_area() for sheet in sheets)
        total_material_used = sum(sheet.get_total_area() for sheet in sheets)
    else:
        avg_utilization = 0.0
        total_waste = 0.0
        total_material_used = 0.0

    suggestions = []
    suggestions.extend(orientation_summary['suggestions'])
    suggestions.extend(dimension_suggestions)
    if not suggestions:
        suggestions.append('Current nesting layout is already optimal for the selected sheet size.')

    return {
        'sheets': sheets,
        'total_parts_placed': total_parts_placed,
        'total_sheets_used': total_sheets_used,
        'parts_per_sheet': total_parts_placed / total_sheets_used if total_sheets_used > 0 else 0,
        'average_utilization': avg_utilization,
        'total_waste_area': total_waste,
        'total_material_used': total_material_used,
        'waste_percentage': (total_waste / total_material_used * 100) if total_material_used > 0 else 0,
        'best_orientation': orientation_summary['best']['orientation'],
        'layout_comparisons': orientation_summary['options'],
        'suggestions': suggestions
    }
