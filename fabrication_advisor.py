"""
Smart Fabrication Advisor module for CNC DXF generator.
Analyzes designs for manufacturability issues and provides recommendations.
"""

import math
from typing import List, Tuple, Dict, Optional, Any
from enum import Enum


class IssueSeverity(Enum):
    """Severity levels for fabrication issues."""
    ERROR = "error"  # Will prevent proper manufacturing
    WARNING = "warning"  # May cause issues or inefficiency
    INFO = "info"  # Suggestions for improvement


class FabricationIssue:
    """Represents a fabrication issue with details."""

    def __init__(self, severity: IssueSeverity, message: str, recommendation: str,
                 location: Optional[Tuple[float, float]] = None, highlight_color: str = None):
        self.severity = severity
        self.message = message
        self.recommendation = recommendation
        self.location = location  # (x, y) coordinates for highlighting
        self.highlight_color = highlight_color or ("red" if severity == IssueSeverity.ERROR else "yellow")


class FabricationAdvisor:
    """Analyzes CNC designs for manufacturability issues."""

    def __init__(self, tool_diameter: float):
        self.tool_diameter = tool_diameter
        self.issues: List[FabricationIssue] = []

    def analyze_design(self, template_name: str, params: Dict, entities: List[Dict]) -> List[FabricationIssue]:
        """Analyze a complete design for fabrication issues."""
        self.issues = []

        # Basic parameter validation
        self._check_basic_parameters(template_name, params)

        # Analyze entities for specific issues
        self._analyze_entities(entities, params)

        # Template-specific checks
        if template_name == 'Rectangle':
            self._analyze_rectangle(params)
        elif template_name == 'Box Flat Pattern':
            self._analyze_box_flat_pattern(params)
        elif template_name == 'L Bracket Flat Pattern':
            self._analyze_l_bracket_flat_pattern(params)
        elif template_name == 'Channel Flat Pattern':
            self._analyze_channel_flat_pattern(params)

        return self.issues

    def _check_basic_parameters(self, template_name: str, params: Dict):
        """Check basic parameters for common issues."""
        # Tool diameter validation
        if self.tool_diameter <= 0:
            self.issues.append(FabricationIssue(
                IssueSeverity.ERROR,
                "Invalid tool diameter",
                "Tool diameter must be greater than 0mm"
            ))
            return  # Can't continue analysis without valid tool

        # Pattern checks if enabled
        if params.get('pattern_enabled', False):
            self._check_pattern_parameters(params)

    def _check_pattern_parameters(self, params: Dict):
        """Check pattern-related parameters."""
        pattern_size = float(params.get('pattern_size', 10))
        spacing_x = float(params.get('spacing_x', 20))
        spacing_y = float(params.get('spacing_y', 20))

        # Pattern size vs tool diameter
        if pattern_size < self.tool_diameter:
            self.issues.append(FabricationIssue(
                IssueSeverity.ERROR,
                f"Pattern size ({pattern_size}mm) is smaller than tool diameter ({self.tool_diameter}mm)",
                f"Increase pattern size to at least {self.tool_diameter}mm or use a smaller tool"
            ))

        # Spacing checks
        if spacing_x < pattern_size:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Pattern spacing X ({spacing_x}mm) is less than pattern size ({pattern_size}mm)",
                f"Increase spacing X to at least {pattern_size}mm for better material removal"
            ))

        if spacing_y < pattern_size:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Pattern spacing Y ({spacing_y}mm) is less than pattern size ({pattern_size}mm)",
                f"Increase spacing Y to at least {pattern_size}mm for better material removal"
            ))

    def _analyze_entities(self, entities: List[Dict], params: Dict):
        """Analyze DXF entities for fabrication issues."""
        holes = []
        slots = []
        corners = []

        for entity in entities:
            layer = entity.get('layer', '').upper()
            entity_type = entity['type']

            if layer == 'HOLES':
                if entity_type == 'circle':
                    holes.append(entity)
                elif entity_type == 'polyline':
                    # Check if it's a slot (rectangular polyline)
                    points = entity['points']
                    if len(points) == 4:  # Rectangle
                        slots.append(entity)

            # Detect sharp corners in CUT layer
            if layer == 'CUT' and entity_type == 'polyline':
                corners.extend(self._detect_sharp_corners(entity))

        # Check holes
        for hole in holes:
            self._check_hole(hole)

        # Check slots
        for slot in slots:
            self._check_slot(slot)

        # Check corners
        for corner in corners:
            self._check_corner(corner)

        # Check pattern distance from flanges
        if params.get('pattern_enabled', False):
            self._check_pattern_flange_distance(entities, params)

    def _check_hole(self, hole: Dict):
        """Check hole for manufacturability."""
        radius = hole['radius']
        diameter = radius * 2

        if diameter < self.tool_diameter:
            self.issues.append(FabricationIssue(
                IssueSeverity.ERROR,
                f"Hole diameter ({diameter:.1f}mm) is smaller than tool diameter ({self.tool_diameter}mm)",
                f"Increase hole diameter to at least {self.tool_diameter}mm or use a smaller tool",
                hole['center']
            ))
        elif diameter < self.tool_diameter * 1.1:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Hole diameter ({diameter:.1f}mm) is very close to tool diameter ({self.tool_diameter}mm)",
                f"Consider increasing hole diameter to {self.tool_diameter * 1.2:.1f}mm for better tool life",
                hole['center']
            ))

    def _check_slot(self, slot: Dict):
        """Check slot for manufacturability."""
        points = slot['points']
        if len(points) < 4:
            return

        # Calculate slot dimensions
        x_coords = [p[0] for p in points]
        y_coords = [p[1] for p in points]
        width = max(x_coords) - min(x_coords)
        height = max(y_coords) - min(y_coords)
        slot_width = min(width, height)

        if slot_width < self.tool_diameter:
            center_x = (min(x_coords) + max(x_coords)) / 2
            center_y = (min(y_coords) + max(y_coords)) / 2
            self.issues.append(FabricationIssue(
                IssueSeverity.ERROR,
                f"Slot width ({slot_width:.1f}mm) is smaller than tool diameter ({self.tool_diameter}mm)",
                f"Increase slot width to at least {self.tool_diameter}mm or use a smaller tool",
                (center_x, center_y)
            ))

    def _detect_sharp_corners(self, entity: Dict) -> List[Tuple[float, float]]:
        """Detect sharp internal corners in a polyline."""
        points = entity['points']
        if len(points) < 3:
            return []

        corners = []
        for i in range(len(points)):
            prev_point = points[i-1]
            curr_point = points[i]
            next_point = points[(i+1) % len(points)]

            # Calculate vectors
            v1 = (curr_point[0] - prev_point[0], curr_point[1] - prev_point[1])
            v2 = (next_point[0] - curr_point[0], next_point[1] - curr_point[1])

            # Calculate angle between vectors
            angle = self._calculate_angle(v1, v2)

            # Check for sharp internal corners (acute angles)
            if angle < 90:  # Less than 90 degrees
                corners.append(curr_point)

        return corners

    def _calculate_angle(self, v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
        """Calculate angle between two vectors in degrees."""
        dot_product = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag2 = math.sqrt(v2[0]**2 + v2[1]**2)

        if mag1 == 0 or mag2 == 0:
            return 180

        cos_angle = dot_product / (mag1 * mag2)
        cos_angle = max(-1, min(1, cos_angle))  # Clamp to avoid domain errors
        angle = math.degrees(math.acos(cos_angle))
        return angle

    def _check_corner(self, corner: Tuple[float, float]):
        """Check if a sharp corner is problematic."""
        self.issues.append(FabricationIssue(
            IssueSeverity.WARNING,
            "Sharp internal corner detected",
            "Consider adding fillet radius or using smaller tool for better finish",
            corner
        ))

    def _check_pattern_flange_distance(self, entities: List[Dict], params: Dict):
        """Check distance between patterns and flanges."""
        inner_margin = float(params.get('inner_margin', 5))
        pattern_size = float(params.get('pattern_size', 10))

        # Find flange boundaries
        flange_bounds = self._get_flange_bounds(entities)

        if not flange_bounds:
            return

        # Check if patterns are too close to flanges
        pattern_entities = [e for e in entities if e.get('layer', '').upper() == 'PATTERN']

        for pattern in pattern_entities:
            if pattern['type'] == 'circle':
                center = pattern['center']
                radius = pattern['radius']

                # Check distance to each flange
                for bound_name, bounds in flange_bounds.items():
                    distance = self._distance_to_bounds(center, bounds)
                    min_required = inner_margin + radius

                    if distance < min_required:
                        self.issues.append(FabricationIssue(
                            IssueSeverity.WARNING,
                            f"Pattern too close to {bound_name} flange",
                            f"Increase inner margin to at least {min_required - radius:.1f}mm",
                            center
                        ))

    def _get_flange_bounds(self, entities: List[Dict]) -> Dict[str, Tuple[float, float, float, float]]:
        """Get bounding boxes for flanges."""
        bounds = {}

        # Find min/max coordinates for each layer
        layers = {}
        for entity in entities:
            layer = entity.get('layer', '').upper()
            if layer not in ['CUT', 'FOLDS']:
                continue

            if layer not in layers:
                layers[layer] = {'min_x': float('inf'), 'max_x': float('-inf'),
                               'min_y': float('inf'), 'max_y': float('-inf')}

            if entity['type'] == 'line':
                x1, y1 = entity['start']
                x2, y2 = entity['end']
                layers[layer]['min_x'] = min(layers[layer]['min_x'], x1, x2)
                layers[layer]['max_x'] = max(layers[layer]['max_x'], x1, x2)
                layers[layer]['min_y'] = min(layers[layer]['min_y'], y1, y2)
                layers[layer]['max_y'] = max(layers[layer]['max_y'], y1, y2)
            elif entity['type'] == 'polyline':
                for x, y in entity['points']:
                    layers[layer]['min_x'] = min(layers[layer]['min_x'], x)
                    layers[layer]['max_x'] = max(layers[layer]['max_x'], x)
                    layers[layer]['min_y'] = min(layers[layer]['min_y'], y)
                    layers[layer]['max_y'] = max(layers[layer]['max_y'], y)

        # Convert to bounds tuples (min_x, max_x, min_y, max_y)
        for layer, layer_bounds in layers.items():
            if layer_bounds['min_x'] != float('inf'):
                bounds[layer] = (layer_bounds['min_x'], layer_bounds['max_x'],
                               layer_bounds['min_y'], layer_bounds['max_y'])

        return bounds

    def _distance_to_bounds(self, point: Tuple[float, float],
                          bounds: Tuple[float, float, float, float]) -> float:
        """Calculate minimum distance from point to rectangular bounds."""
        px, py = point
        min_x, max_x, min_y, max_y = bounds

        # Check if point is inside bounds
        if min_x <= px <= max_x and min_y <= py <= max_y:
            return 0

        # Calculate distance to each edge
        distances = [
            abs(px - min_x) if px < min_x else 0,  # Left edge
            abs(px - max_x) if px > max_x else 0,  # Right edge
            abs(py - min_y) if py < min_y else 0,  # Bottom edge
            abs(py - max_y) if py > max_y else 0,  # Top edge
        ]

        return max(distances)  # Return the largest distance (closest edge)

    def _check_relief_params(self, relief_type: str, relief_size: float,
                              bend_flanges: List[float]):
        """
        Shared relief validation for any flanged template.

        bend_flanges: list of active flange depths (>0) that share intersections.
        """
        if relief_type == 'none':
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                "No corner relief cuts — flanges will collide when bent",
                "Enable corner relief (square ≥2 mm, round ≥2 mm, or v_cut) at every "
                "fold-line intersection to prevent material overlap and tearing"
            ))
            return

        if relief_size <= 0:
            self.issues.append(FabricationIssue(
                IssueSeverity.ERROR,
                "Corner relief size is zero or negative",
                "Set relief size to a positive value (recommend ≥ material thickness + 0.5 mm)"
            ))
            return

        # Relief must be at least as wide as the tool diameter
        if relief_size < self.tool_diameter:
            self.issues.append(FabricationIssue(
                IssueSeverity.ERROR,
                f"Relief size ({relief_size:.1f} mm) is smaller than tool diameter "
                f"({self.tool_diameter:.1f} mm)",
                f"Increase relief size to at least {self.tool_diameter:.1f} mm so the "
                "tool can fully clear the corner"
            ))

        # For adjacent flanges meeting at a corner: the relief diameter/width must
        # be at least equal to the tool diameter (already checked above), which is
        # sufficient to prevent material overlap when walls are folded 90°.
        # No further flange-depth check needed for standard sheet metal.

    def _analyze_rectangle(self, params: Dict):
        """Template-specific analysis for rectangles."""
        width = float(params.get('width', 100))
        height = float(params.get('height', 50))

        if width < self.tool_diameter * 2:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Rectangle width ({width}mm) is very small for tool diameter ({self.tool_diameter}mm)",
                f"Consider increasing width to at least {self.tool_diameter * 2}mm"
            ))

        if height < self.tool_diameter * 2:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Rectangle height ({height}mm) is very small for tool diameter ({self.tool_diameter}mm)",
                f"Consider increasing height to at least {self.tool_diameter * 2}mm"
            ))

        # Check corner relief if any flanges are active
        bend_values = [
            float(params.get('bend_top', 0)),
            float(params.get('bend_bottom', 0)),
            float(params.get('bend_left', 0)),
            float(params.get('bend_right', 0)),
        ]
        active_bends = [v for v in bend_values if v > 0]
        if active_bends:
            relief_type = params.get('relief_type', 'none')
            relief_size = float(params.get('relief_size', 3.0))
            self._check_relief_params(relief_type, relief_size, active_bends)

    def _analyze_box_flat_pattern(self, params: Dict):
        """Template-specific analysis for box flat patterns."""
        wall_height = float(params.get('wall_height', 20))
        base_width  = float(params.get('base_width', 80))
        base_depth  = float(params.get('base_depth', 40))

        if wall_height < self.tool_diameter:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Wall height ({wall_height}mm) is smaller than tool diameter ({self.tool_diameter}mm)",
                f"Increase wall height to at least {self.tool_diameter}mm for better bend formation"
            ))

        # Box has 4 flanges meeting at 4 corners — relief is always needed
        relief_type = params.get('relief_type', 'none')
        relief_size = float(params.get('relief_size', 3.0))
        # All four flanges share corners; pass all four as active
        self._check_relief_params(relief_type, relief_size,
                                  [wall_height] * 4)

    def _analyze_l_bracket_flat_pattern(self, params: Dict):
        """Template-specific analysis for L-bracket flat patterns."""
        leg_height = float(params.get('leg_height', 30))

        if leg_height < self.tool_diameter:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Leg height ({leg_height}mm) is smaller than tool diameter ({self.tool_diameter}mm)",
                f"Increase leg height to at least {self.tool_diameter}mm for better bend formation"
            ))

        # Single fold — both endpoints need relief to prevent edge tearing
        relief_type = params.get('relief_type', 'none')
        relief_size = float(params.get('relief_size', 3.0))
        self._check_relief_params(relief_type, relief_size, [leg_height])

    def _analyze_channel_flat_pattern(self, params: Dict):
        """Template-specific analysis for channel flat patterns."""
        wall_height = float(params.get('wall_height', 20))

        if wall_height < self.tool_diameter:
            self.issues.append(FabricationIssue(
                IssueSeverity.WARNING,
                f"Wall height ({wall_height}mm) is smaller than tool diameter ({self.tool_diameter}mm)",
                f"Increase wall height to at least {self.tool_diameter}mm for better bend formation"
            ))

        # Two opposing flanges, each with 2 endpoint corners
        relief_type = params.get('relief_type', 'none')
        relief_size = float(params.get('relief_size', 3.0))
        self._check_relief_params(relief_type, relief_size,
                                  [wall_height, wall_height])