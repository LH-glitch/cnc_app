"""
Cut types module for CNC DXF generator.
Defines different types of machining operations.
"""

from enum import Enum


class CutType(Enum):
    """Enumeration of cut types for CNC machining."""
    PROFILE = "profile"      # Outer boundary cut
    POCKET = "pocket"        # Inner area cut
    DRILL = "drill"          # Hole drilling
    SLOT = "slot"            # Slot cutting
    FOLD = "fold"            # Fold/bend line
    GROOVE = "groove"        # Groove or score line


class MachiningFeature:
    """Base class for machining features."""

    def __init__(self, cut_type, tool_compensation=None):
        self.cut_type = cut_type
        if tool_compensation is None:
            from tool_compensation import NoToolCompensation
            tool_compensation = NoToolCompensation()
        self.tool_compensation = tool_compensation

    def get_layer_name(self):
        """Get the DXF layer name for this feature."""
        if self.cut_type == CutType.PROFILE:
            return "CUT"
        elif self.cut_type == CutType.POCKET:
            return "CUT"
        elif self.cut_type == CutType.DRILL:
            return "HOLES"
        elif self.cut_type == CutType.SLOT:
            return "SLOTS"
        else:
            return "DEFAULT"


class ProfileCut(MachiningFeature):
    """Profile cut - outer boundary machining."""

    def __init__(self, tool_compensation=None):
        super().__init__(CutType.PROFILE, tool_compensation)


class PocketCut(MachiningFeature):
    """Pocket cut - inner area machining."""

    def __init__(self, tool_compensation=None):
        super().__init__(CutType.POCKET, tool_compensation)


class DrillCut(MachiningFeature):
    """Drill cut - hole machining."""

    def __init__(self, tool_compensation=None):
        super().__init__(CutType.DRILL, tool_compensation)


class SlotCut(MachiningFeature):
    """Slot cut - slot machining."""

    def __init__(self, orientation='horizontal', tool_compensation=None):
        super().__init__(CutType.SLOT, tool_compensation)
        self.orientation = orientation  # 'horizontal' or 'vertical'


class FoldLineCut(MachiningFeature):
    """Fold line - sheet metal bend intent."""

    def __init__(self, tool_compensation=None):
        super().__init__(CutType.FOLD, tool_compensation)


class GrooveLineCut(MachiningFeature):
    """Groove or score line for formed parts."""

    def __init__(self, tool_compensation=None):
        super().__init__(CutType.GROOVE, tool_compensation)
