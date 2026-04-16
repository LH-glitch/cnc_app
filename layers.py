"""
Layers module for CNC DXF generator.
Manages DXF layers for different machining features.
"""

import ezdxf


class LayerManager:
    """Manage DXF layers for CNC machining."""

    # Standard CNC layers
    CUT_LAYER = "CUT"
    HOLES_LAYER = "HOLES"
    SLOTS_LAYER = "SLOTS"
    FOLDS_LAYER = "FOLDS"
    GROOVE_LAYER = "GROOVE"
    TEMPLATE_LAYER = "TEMPLATE"
    DIMENSION_LAYER = "DIMENSIONS"
    PATTERN_LAYER = "PATTERN"
    RELIEF_LAYER = "RELIEF"
    LABELS_LAYER = "LABELS"
    DEFAULT_LAYER = "0"

    def __init__(self, doc):
        """
        Initialize layer manager with DXF document.

        Args:
            doc: ezdxf document
        """
        self.doc = doc
        self._ensure_layers()

    def _ensure_layers(self):
        """Ensure all required layers exist in the document."""
        layers = self.doc.layers

        # Create layers if they don't exist
        if self.CUT_LAYER not in layers:
            layers.new(self.CUT_LAYER, dxfattribs={'color': 1})  # Red

        if self.HOLES_LAYER not in layers:
            layers.new(self.HOLES_LAYER, dxfattribs={'color': 3})  # Green

        if self.SLOTS_LAYER not in layers:
            layers.new(self.SLOTS_LAYER, dxfattribs={'color': 5})  # Blue

        if self.FOLDS_LAYER not in layers:
            layers.new(self.FOLDS_LAYER, dxfattribs={'color': 6})  # Magenta

        if self.GROOVE_LAYER not in layers:
            layers.new(self.GROOVE_LAYER, dxfattribs={'color': 8})  # Gray

        if self.TEMPLATE_LAYER not in layers:
            layers.new(self.TEMPLATE_LAYER, dxfattribs={'color': 2})  # Yellow

        if self.DIMENSION_LAYER not in layers:
            layers.new(self.DIMENSION_LAYER, dxfattribs={'color': 4})  # Cyan

        if self.PATTERN_LAYER not in layers:
            layers.new(self.PATTERN_LAYER, dxfattribs={'color': 7})  # White

        if self.RELIEF_LAYER not in layers:
            layers.new(self.RELIEF_LAYER, dxfattribs={'color': 30})  # Orange

        if self.LABELS_LAYER not in layers:
            layers.new(self.LABELS_LAYER, dxfattribs={'color': 4})   # Cyan

    def get_modelspace(self, layer_name=None):
        """Get modelspace for a specific layer."""
        return self.doc.modelspace()

    def get_layer_modelspace(self, layer_name):
        """Get modelspace specifically for a layer."""
        # In ezdxf, all entities go to the main modelspace
        # Layers are assigned to entities, not modelspaces
        return self.doc.modelspace()

    @staticmethod
    def get_layer_for_feature(feature_type):
        """Get appropriate layer name for a machining feature."""
        if feature_type == "profile":
            return LayerManager.CUT_LAYER
        elif feature_type == "pocket":
            return LayerManager.CUT_LAYER
        elif feature_type == "drill":
            return LayerManager.HOLES_LAYER
        elif feature_type == "slot":
            return LayerManager.SLOTS_LAYER
        elif feature_type == "fold":
            return LayerManager.FOLDS_LAYER
        elif feature_type == "groove":
            return LayerManager.GROOVE_LAYER
        elif feature_type == "template":
            return LayerManager.TEMPLATE_LAYER
        elif feature_type == "pattern":
            return LayerManager.PATTERN_LAYER
        else:
            return LayerManager.DEFAULT_LAYER