"""
Preview engine — pure geometry/rendering layer.

No tkinter. No application state. No side effects.

Responsibilities
----------------
- Convert an ezdxf Document to a flat list of preview entity dicts
- Dispatch to per-template entity generators (params → entities)
- Render entity lists onto a matplotlib Axes
- Apply consistent axis styling

Entity dict format
------------------
  {'type': 'line',     'start': (x,y), 'end': (x,y),   'layer': str}
  {'type': 'circle',   'center': (x,y), 'radius': float, 'layer': str}
  {'type': 'polyline', 'points': [(x,y), ...],            'layer': str}

Layer keys: 'CUT' | 'HOLES' | 'SLOTS' | 'FOLDS' | 'TEMPLATE' | 'DIMENSIONS' | 'PATTERN'
"""

import math
from typing import Dict, List, Optional, Tuple
import entity_model as em

# ── Layer visual styles ───────────────────────────────────────────────────────
# Maps normalised layer key → (hex_color, linewidth, linestyle)
LAYER_STYLES: Dict[str, Tuple[str, float, str]] = {
    'CUT':        ('#e53935', 2.0, 'solid'),
    'HOLES':      ('#43a047', 1.5, 'solid'),
    'SLOTS':      ('#1e88e5', 1.5, 'solid'),
    'FOLDS':      ('#f9a825', 0.8, 'dashed'),
    'GROOVE':     ('#f9a825', 0.8, 'dashed'),
    'DIMENSIONS': ('#9e9e9e', 0.5, 'solid'),
    'TEMPLATE':   ('#8e24aa', 1.0, 'solid'),
    'PATTERN':    ('#fb8c00', 1.0, 'solid'),
    'RELIEF':     ('#00acc1', 2.0, 'solid'),   # cyan — visually distinct from CUT
}

# Raw DXF layer name → normalised preview layer key
_DXF_LAYER_MAP: Dict[str, str] = {
    'CUT':        'CUT',
    'FOLDS':      'FOLDS',
    'GROOVE':     'FOLDS',
    'HOLES':      'HOLES',
    'SLOTS':      'SLOTS',
    'TEMPLATE':   'TEMPLATE',
    'DIMENSIONS': 'DIMENSIONS',
    'PATTERN':    'PATTERN',
    'RELIEF':     'RELIEF',
}


# ── DXF document → entity list ───────────────────────────────────────────────

def extract_entities_from_dxf(doc) -> List[Dict]:
    """
    Convert an ezdxf Document's modelspace to a flat list of entity dicts.

    Handles LINE, CIRCLE, LWPOLYLINE, POLYLINE, ARC.
    Unknown entity types are silently skipped.
    """
    entities: List[Dict] = []

    for entity in doc.modelspace():
        dxftype = entity.dxftype()
        raw_layer = getattr(entity.dxf, 'layer', '').upper()
        layer = _DXF_LAYER_MAP.get(raw_layer, 'CUT')

        if dxftype == 'LINE':
            s, e = entity.dxf.start, entity.dxf.end
            entities.append({
                'type': 'line',
                'start': (s.x, s.y),
                'end': (e.x, e.y),
                'layer': layer,
            })

        elif dxftype == 'CIRCLE':
            c = entity.dxf.center
            entities.append({
                'type': 'circle',
                'center': (c.x, c.y),
                'radius': entity.dxf.radius,
                'layer': layer,
            })

        elif dxftype == 'LWPOLYLINE':
            pts = [(p[0], p[1]) for p in entity.get_points()]
            if pts:
                entities.append({'type': 'polyline', 'points': pts, 'layer': layer})

        elif dxftype == 'POLYLINE':
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices()]
            if pts:
                entities.append({'type': 'polyline', 'points': pts, 'layer': layer})

        elif dxftype == 'ARC':
            c = entity.dxf.center
            r = entity.dxf.radius
            a0, a1 = entity.dxf.start_angle, entity.dxf.end_angle
            pts = []
            angle = a0
            while angle <= a1:
                rad = math.radians(angle)
                pts.append((c.x + r * math.cos(rad), c.y + r * math.sin(rad)))
                angle += 5
            if pts:
                entities.append({'type': 'polyline', 'points': pts, 'layer': layer})

    em.ensure_schema(entities, source=em.SOURCE_GENERATOR)
    return entities


# ── Per-template entity generators ───────────────────────────────────────────

def generate_preview_entities(template_name: str, params: Dict) -> List[Dict]:
    """
    Generate a preview entity list for the given template and params.

    ``params`` values are strings (as they come from form fields).
    Coercion to float is handled internally.

    Raises ValueError if the template name is unknown or a required param is
    missing/invalid.
    """
    _generators = {
        'Rectangle':            _gen_rectangle,
        'Box Flat Pattern':     lambda p: _gen_flat_pattern('box',       p),
        'L Bracket Flat Pattern': lambda p: _gen_flat_pattern('l_bracket', p),
        'Channel Flat Pattern': lambda p: _gen_flat_pattern('channel',   p),
    }
    gen = _generators.get(template_name)
    if gen is None:
        raise ValueError(f"Unknown template: {template_name!r}")
    return gen(params)


def _gen_rectangle(params: Dict) -> List[Dict]:
    from dxf_generator import DXFGenerator
    from holes import NoHoles

    generator = DXFGenerator()
    shape_params = {
        'width':       float(params['width']),
        'height':      float(params['height']),
        'bend_top':    float(params.get('bend_top', 0)),
        'bend_bottom': float(params.get('bend_bottom', 0)),
        'bend_left':   float(params.get('bend_left', 0)),
        'bend_right':  float(params.get('bend_right', 0)),
        'relief_type': params.get('relief_type', 'none'),
        'relief_size': float(params.get('relief_size', 3.0)),
    }
    pattern_params = None
    if params.get('pattern_enabled'):
        pattern_params = {
            'enabled':      True,
            'pattern_type': params.get('pattern_type', 'circles'),
            'pattern_size': float(params.get('pattern_size', 10)),
            'spacing_x':    float(params.get('spacing_x', 20)),
            'spacing_y':    float(params.get('spacing_y', 20)),
            'inner_margin': float(params.get('inner_margin', 5)),
        }
    doc = generator.generate_dxf_in_memory(
        'rectangle', shape_params, NoHoles(0), pattern_params=pattern_params
    )
    return extract_entities_from_dxf(doc)


def _gen_flat_pattern(pattern_type: str, params: Dict) -> List[Dict]:
    from dxf_generator import DXFGenerator, Material

    _dim_keys: Dict[str, Tuple[str, ...]] = {
        'box':       ('base_width', 'base_depth', 'wall_height'),
        'l_bracket': ('base_width', 'base_depth', 'leg_height'),
        'channel':   ('base_width', 'base_depth', 'wall_height'),
    }
    template_params = {k: float(params[k]) for k in _dim_keys[pattern_type]}
    bend_values = {
        'top':    float(params.get('bend_top', 0)),
        'bottom': float(params.get('bend_bottom', 0)),
        'left':   float(params.get('bend_left', 0)),
        'right':  float(params.get('bend_right', 0)),
    }
    relief_type = params.get('relief_type', 'none')
    relief_size = float(params.get('relief_size', 3.0))
    generator = DXFGenerator()
    generator.generate_flat_pattern_template(
        pattern_type, template_params, Material(),
        bend_values=bend_values,
        relief_type=relief_type,
        relief_size=relief_size,
    )
    return extract_entities_from_dxf(generator.doc)


# ── Issue highlighting helpers ───────────────────────────────────────────────

def _entity_centroid(entity: Dict) -> Optional[Tuple[float, float]]:
    """Return a representative (x, y) for an entity, used for issue highlighting."""
    etype = entity['type']
    if etype == 'circle':
        return entity['center']
    if etype == 'line':
        s, e = entity['start'], entity['end']
        return ((s[0] + e[0]) / 2, (s[1] + e[1]) / 2)
    if etype == 'polyline':
        pts = entity['points']
        if pts:
            return (
                sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts),
            )
    return None


def _resolve_highlight(entity: Dict, issues) -> Optional[str]:
    """
    Return a highlight color string if any fabrication issue falls near this entity.

    ``issues`` is an iterable of objects with:
      .location: Optional[Tuple[float, float]]
      .highlight_color: str

    Uses a 5 mm position tolerance.
    """
    if not issues:
        return None
    loc = _entity_centroid(entity)
    if loc is None:
        return None
    for issue in issues:
        if issue.location:
            dx = abs(loc[0] - issue.location[0])
            dy = abs(loc[1] - issue.location[1])
            if dx < 5.0 and dy < 5.0:
                return issue.highlight_color
    return None


# ── Renderer ─────────────────────────────────────────────────────────────────

def render_entities(
    ax,
    entities: List[Dict],
    issues=None,
) -> List[Optional[float]]:
    """
    Draw an entity list onto a matplotlib Axes.

    Args:
        ax:       matplotlib Axes object.
        entities: list of entity dicts (from generate_preview_entities or
                  extract_entities_from_dxf).
        issues:   optional list of FabricationIssue objects for highlighting.

    Returns:
        Bounding box as [min_x, max_x, min_y, max_y].
        Elements are None when no entities were drawn.
    """
    import matplotlib.pyplot as plt

    bounds: List[Optional[float]] = [None, None, None, None]

    def _upd(x: float, y: float) -> None:
        if bounds[0] is None or x < bounds[0]: bounds[0] = x
        if bounds[1] is None or x > bounds[1]: bounds[1] = x
        if bounds[2] is None or y < bounds[2]: bounds[2] = y
        if bounds[3] is None or y > bounds[3]: bounds[3] = y

    for entity in entities:
        layer = entity.get('layer', 'CUT').upper()
        color, lw, style = LAYER_STYLES.get(layer, ('#333333', 1.0, 'solid'))

        hi = _resolve_highlight(entity, issues)
        if hi:
            color, lw = hi, max(lw, 3.0)

        etype = entity['type']
        if etype == 'line':
            s, e = entity['start'], entity['end']
            ax.plot([s[0], e[0]], [s[1], e[1]],
                    color=color, linestyle=style, linewidth=lw)
            _upd(s[0], s[1]); _upd(e[0], e[1])

        elif etype == 'circle':
            cx, cy, r = entity['center'][0], entity['center'][1], entity['radius']
            ax.add_patch(plt.Circle(
                (cx, cy), r, fill=False,
                edgecolor=color, linestyle=style, linewidth=lw,
            ))
            _upd(cx - r, cy - r); _upd(cx + r, cy + r)

        elif etype == 'polyline':
            pts = entity['points']
            if pts:
                xs, ys = zip(*pts)
                ax.plot(xs, ys, color=color, linestyle=style, linewidth=lw)
                for x, y in pts:
                    _upd(x, y)

    return bounds


def apply_ax_style(
    ax,
    title: str,
    bounds: List[Optional[float]],
    accent_color: str = '#1565c0',
    border_color: str = '#dde1e7',
) -> None:
    """
    Apply consistent axis decoration after rendering.

    Adds grid, crosshairs, labels, title, and zooms to fit content.
    Call *after* render_entities() on the same Axes.
    """
    ax.grid(True, color='#dde1e7', linewidth=0.4, alpha=0.8)
    ax.set_axisbelow(True)

    # Origin crosshairs
    ax.axhline(y=0, color='#9e9e9e', linewidth=0.6, alpha=0.6)
    ax.axvline(x=0, color='#9e9e9e', linewidth=0.6, alpha=0.6)
    ax.scatter([0], [0], color='#555555', s=16, marker='x', alpha=0.7)

    ax.set_xlabel('X (mm)', fontsize=8, color='#555555')
    ax.set_ylabel('Y (mm)', fontsize=8, color='#555555')
    ax.set_title(title, fontsize=9, color=accent_color, fontweight='bold')
    ax.tick_params(labelsize=7, colors='#555555')
    for spine in ax.spines.values():
        spine.set_edgecolor(border_color)

    if all(v is not None for v in bounds):
        w = bounds[1] - bounds[0]
        h = bounds[3] - bounds[2]
        margin = max(w * 0.1, h * 0.1, 10)
        ax.set_xlim(bounds[0] - margin, bounds[1] + margin)
        ax.set_ylim(bounds[2] - margin, bounds[3] + margin)
        ax.set_aspect('equal', adjustable='datalim')
