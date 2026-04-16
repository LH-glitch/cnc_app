"""
panel_decomposition.py — 3D panel assembly → 2D flat CNC panels.

Manufacturing decomposition: treats a simple 3D object as an assembly of
flat boards and returns the constituent 2D panels with correct dimensions,
labels, and edge-connection hints (joint type + mating panel).

Supported shapes
----------------
  box       W × D × H  →  6 panels  (bottom + 4 walls + optional top)
  l_shape   W × D × H  →  2 panels  (base + vertical leg)
  channel   W × D × H  →  3 panels  (base + left wall + right wall)

Joint types
-----------
  'butt'  — simple square edge, fastened / glued
  'fold'  — score/groove and bend (sheet metal, ALCUBOND)
  'open'  — free edge, no joint

Output
------
  panels_to_entities(panels)      →  preview_engine entity list (for canvas)
  panels_to_dxf(panels, path)     →  writes arranged DXF file
"""

import math
import ezdxf
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from layers import LayerManager
import entity_model as em


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class EdgeHint:
    """A connection annotation on one edge of a panel."""
    side:        str   # 'top' | 'bottom' | 'left' | 'right'
    joint:       str   # 'butt' | 'fold' | 'open'
    connects_to: str   # label of mating panel, or '' if open


@dataclass
class Panel:
    """One flat board in the decomposed assembly."""
    label:     str
    width:     float                          # mm  (horizontal extent in flat layout)
    height:    float                          # mm  (vertical extent in flat layout)
    thickness: float              = 1.5       # material thickness, mm
    edges:     List[EdgeHint]     = field(default_factory=list)
    notes:     str                = ''


# ── Decomposition functions ───────────────────────────────────────────────────

def decompose_box(
    width:        float,
    depth:        float,
    wall_height:  float,
    thickness:    float = 1.5,
    include_top:  bool  = False,
) -> List[Panel]:
    """
    Decompose a rectangular box into flat panels (butt-joint sizing).

    The bottom panel sits *inside* the four walls.
    Wall net height = wall_height − thickness (bottom panel occupies that space).
    """
    inner_w  = width - 2 * thickness
    inner_d  = depth - 2 * thickness
    net_wall = wall_height - thickness

    if inner_w <= 0 or inner_d <= 0 or net_wall <= 0:
        raise ValueError(
            "Dimensions too small for the given thickness — increase width/depth/height."
        )

    bottom = Panel(
        label='A – Bottom',
        width=inner_w, height=inner_d, thickness=thickness,
        edges=[
            EdgeHint('top',    'butt', 'C – Front'),
            EdgeHint('bottom', 'butt', 'D – Back'),
            EdgeHint('left',   'butt', 'E – Left'),
            EdgeHint('right',  'butt', 'F – Right'),
        ],
        notes=f'Inner size {inner_w:.1f} × {inner_d:.1f} mm, sits inside walls',
    )
    panels: List[Panel] = [bottom]

    if include_top:
        panels.append(Panel(
            label='B – Top / Lid',
            width=inner_w, height=inner_d, thickness=thickness,
            edges=list(bottom.edges),
            notes='Same size as bottom panel',
        ))

    front = Panel(
        label='C – Front Wall',
        width=width, height=net_wall, thickness=thickness,
        edges=[
            EdgeHint('bottom', 'butt', 'A – Bottom'),
            EdgeHint('left',   'butt', 'E – Left'),
            EdgeHint('right',  'butt', 'F – Right'),
            EdgeHint('top',    'open', ''),
        ],
        notes=f'Full width {width:.1f} mm, net height {net_wall:.1f} mm',
    )
    back = Panel(
        label='D – Back Wall',
        width=width, height=net_wall, thickness=thickness,
        edges=list(front.edges),
        notes=front.notes,
    )
    back.label = 'D – Back Wall'

    left = Panel(
        label='E – Left Wall',
        width=depth, height=net_wall, thickness=thickness,
        edges=[
            EdgeHint('bottom', 'butt', 'A – Bottom'),
            EdgeHint('top',    'open', ''),
            EdgeHint('left',   'butt', 'D – Back'),
            EdgeHint('right',  'butt', 'C – Front'),
        ],
        notes=f'Full depth {depth:.1f} mm',
    )
    right = Panel(
        label='F – Right Wall',
        width=depth, height=net_wall, thickness=thickness,
        edges=list(left.edges),
        notes=left.notes,
    )
    right.label = 'F – Right Wall'

    panels += [front, back, left, right]
    return panels


def decompose_l_shape(
    base_width: float,
    base_depth: float,
    leg_height: float,
    thickness:  float = 1.5,
) -> List[Panel]:
    """
    Decompose an L-shape into two flat panels joined by a fold/score line.
    """
    base = Panel(
        label='A – Base',
        width=base_width, height=base_depth, thickness=thickness,
        edges=[EdgeHint('top', 'fold', 'B – Leg')],
        notes=f'Horizontal base {base_width:.1f} × {base_depth:.1f} mm',
    )
    leg = Panel(
        label='B – Leg',
        width=base_width, height=leg_height, thickness=thickness,
        edges=[EdgeHint('bottom', 'fold', 'A – Base')],
        notes=f'Vertical leg {base_width:.1f} × {leg_height:.1f} mm',
    )
    return [base, leg]


def decompose_channel(
    base_width:  float,
    base_depth:  float,
    wall_height: float,
    thickness:   float = 1.5,
) -> List[Panel]:
    """
    Decompose a U-channel into three flat panels joined by fold lines.
    """
    base = Panel(
        label='A – Base',
        width=base_width, height=base_depth, thickness=thickness,
        edges=[
            EdgeHint('left',  'fold', 'B – Left Wall'),
            EdgeHint('right', 'fold', 'C – Right Wall'),
        ],
        notes=f'Base {base_width:.1f} × {base_depth:.1f} mm',
    )
    left_wall = Panel(
        label='B – Left Wall',
        width=base_depth, height=wall_height, thickness=thickness,
        edges=[EdgeHint('right', 'fold', 'A – Base')],
        notes=f'Left wall {base_depth:.1f} × {wall_height:.1f} mm',
    )
    right_wall = Panel(
        label='C – Right Wall',
        width=base_depth, height=wall_height, thickness=thickness,
        edges=[EdgeHint('left', 'fold', 'A – Base')],
        notes=f'Right wall {base_depth:.1f} × {wall_height:.1f} mm',
    )
    return [base, left_wall, right_wall]


# Dispatcher
_DECOMPOSERS = {
    'box':     decompose_box,
    'l_shape': decompose_l_shape,
    'channel': decompose_channel,
}

def decompose(shape: str, **params) -> List[Panel]:
    """
    Generic entry point.

    decompose('box',     width=300, depth=200, wall_height=100)
    decompose('l_shape', base_width=200, base_depth=100, leg_height=80)
    decompose('channel', base_width=200, base_depth=100, wall_height=60)
    """
    fn = _DECOMPOSERS.get(shape)
    if fn is None:
        raise ValueError(f"Unknown shape {shape!r}. Choose from: {list(_DECOMPOSERS)}")
    return fn(**params)


# ── Entity generation (for preview_engine / InteractiveCanvas) ────────────────

_PANEL_GAP = 20.0    # mm gap between panels in the arranged layout


def panels_to_entities(panels: List[Panel]) -> List[Dict]:
    """
    Convert a panel list to entity_model entity dicts.

    Panels are arranged left-to-right with _PANEL_GAP spacing.
    Each panel shows: outline (CUT), edge-hint ticks (FOLDS / TEMPLATE).
    """
    entities: List[Dict] = []
    x_cursor = 0.0

    for panel in panels:
        x0, y0 = x_cursor, 0.0
        x1, y1 = x0 + panel.width, y0 + panel.height

        # Outer outline
        entities.append(em.make_polyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
            layer=em.LAYER_CUT,
            closed=False,
            label=panel.label,
            source=em.SOURCE_PANEL,
        ))

        # Edge-hint tick marks (centred on each edge)
        tick = max(min(panel.width, panel.height) * 0.06, 4.0)
        for hint in panel.edges:
            if hint.joint == 'open':
                continue
            layer = em.LAYER_FOLDS if hint.joint == 'fold' else em.LAYER_TEMPLATE
            mw, mh = x0 + panel.width / 2, y0 + panel.height / 2
            if hint.side == 'bottom':
                pts = [(mw - tick, y0), (mw + tick, y0)]
            elif hint.side == 'top':
                pts = [(mw - tick, y1), (mw + tick, y1)]
            elif hint.side == 'left':
                pts = [(x0, mh - tick), (x0, mh + tick)]
            else:   # right
                pts = [(x1, mh - tick), (x1, mh + tick)]
            entities.append(em.make_polyline(pts, layer=layer, source=em.SOURCE_PANEL))

        x_cursor += panel.width + _PANEL_GAP

    return entities


# ── DXF export ────────────────────────────────────────────────────────────────

def panels_to_dxf(panels: List[Panel], output_path: str) -> None:
    """
    Write all panels to a single DXF file, arranged left-to-right.

    Layers used:
      CUT         — panel outlines
      DIMENSIONS  — label + dimension text
      FOLDS       — fold/score edge hints
      TEMPLATE    — butt-joint edge hints
    """
    doc = ezdxf.new()
    LayerManager(doc)
    msp = doc.modelspace()

    x_cursor = 0.0
    for panel in panels:
        x0, y0 = x_cursor, 0.0
        x1, y1 = x0 + panel.width, y0 + panel.height
        cx,  cy = (x0 + x1) / 2, (y0 + y1) / 2

        # Panel outline
        outline = msp.add_lwpolyline(
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        )
        outline.dxf.layer = LayerManager.CUT_LAYER

        # Label text
        label_h = max(min(panel.width, panel.height) * 0.08, 3.0)
        _add_centered_text(msp, panel.label, cx, cy + label_h, label_h,
                           LayerManager.DIMENSION_LAYER)

        # Dimension text
        dim_str = f'{panel.width:.1f} W × {panel.height:.1f} H mm'
        _add_centered_text(msp, dim_str, cx, cy - label_h * 0.6,
                           max(label_h * 0.55, 2.0), LayerManager.DIMENSION_LAYER)

        # Notes text (small, below dim)
        if panel.notes:
            _add_centered_text(msp, panel.notes, cx, cy - label_h * 1.6,
                               max(label_h * 0.4, 1.5), LayerManager.DIMENSION_LAYER)

        # Edge hint ticks
        tick = max(min(panel.width, panel.height) * 0.06, 4.0)
        mw, mh = cx, cy
        for hint in panel.edges:
            if hint.joint == 'open':
                continue
            layer = (LayerManager.FOLDS_LAYER
                     if hint.joint == 'fold' else LayerManager.TEMPLATE_LAYER)
            if hint.side == 'bottom':
                p1, p2 = (mw - tick, y0), (mw + tick, y0)
            elif hint.side == 'top':
                p1, p2 = (mw - tick, y1), (mw + tick, y1)
            elif hint.side == 'left':
                p1, p2 = (x0, mh - tick), (x0, mh + tick)
            else:
                p1, p2 = (x1, mh - tick), (x1, mh + tick)
            ln = msp.add_line(p1, p2)
            ln.dxf.layer = layer

        x_cursor += panel.width + _PANEL_GAP

    doc.saveas(output_path)


def _add_centered_text(msp, text: str, x: float, y: float,
                        height: float, layer: str) -> None:
    t = msp.add_text(text, dxfattribs={'height': height, 'layer': layer})
    t.dxf.insert = (x, y)
    try:
        t.dxf.halign = 2   # center
        t.dxf.valign = 2
    except Exception:
        pass


# ── Bounding-box helper (for nesting / layout) ────────────────────────────────

def panels_bounding_box(panels: List[Panel]) -> tuple:
    """Return (total_width, max_height) of the arranged layout."""
    if not panels:
        return (0.0, 0.0)
    total_w = sum(p.width for p in panels) + _PANEL_GAP * (len(panels) - 1)
    max_h   = max(p.height for p in panels)
    return (total_w, max_h)
