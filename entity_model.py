"""
entity_model.py — Shared entity schema for all CNC modules.

Every module (preview_engine, interactive_editor, panel_decomposition,
vectorizer, dxf export) uses the same dict structure.  Extra keys are
always allowed — consumers must tolerate unknown keys.

Required keys
-------------
  type   : 'line' | 'circle' | 'polyline'
  layer  : str  (e.g. 'CUT', 'HOLES', 'FOLDS', 'RELIEF', 'TEMPLATE', …)
  id     : str  — stable identity (uuid hex); stamped by ensure_ids / ensure_schema

Type-specific geometry keys
---------------------------
  line     : start (x,y)  end (x,y)
  circle   : center (x,y)  radius float
  polyline : points [(x,y), …]  closed bool (optional, default False)

Optional metadata keys (never required by geometry code)
---------------------------------------------------------
  label      : str  — human name shown in UI
  source     : str  — 'generator' | 'panel' | 'image' | 'manual'
  selectable : bool — defaults True when absent
  locked     : bool — reserved for future UI lock; defaults False when absent

All geometry coordinates are stored as tuples of float.  normalize() coerces
list/array coords to tuples so transform functions always receive clean data.

Factory functions return minimal valid dicts; callers may add extra keys.
"""

import copy
import math
import uuid
from typing import Dict, List, Optional, Tuple


# ── Canonical layer names (mirrors LayerManager) ─────────────────────────────

LAYER_CUT        = 'CUT'
LAYER_HOLES      = 'HOLES'
LAYER_SLOTS      = 'SLOTS'
LAYER_FOLDS      = 'FOLDS'
LAYER_GROOVE     = 'GROOVE'
LAYER_TEMPLATE   = 'TEMPLATE'
LAYER_DIMENSIONS = 'DIMENSIONS'
LAYER_PATTERN    = 'PATTERN'
LAYER_RELIEF     = 'RELIEF'

# Canonical source tags
SOURCE_GENERATOR = 'generator'
SOURCE_PANEL     = 'panel'
SOURCE_IMAGE     = 'image'
SOURCE_MANUAL    = 'manual'


# ── Factory functions ─────────────────────────────────────────────────────────

def make_line(
    start: Tuple[float, float],
    end:   Tuple[float, float],
    layer: str = LAYER_CUT,
    *,
    label:  str = '',
    source: str = '',
) -> Dict:
    e = {
        'type':  'line',
        'layer': layer,
        'id':    uuid.uuid4().hex[:12],
        'start': (float(start[0]), float(start[1])),
        'end':   (float(end[0]),   float(end[1])),
    }
    if label:  e['label']  = label
    if source: e['source'] = source
    return e


def make_circle(
    center: Tuple[float, float],
    radius: float,
    layer:  str = LAYER_HOLES,
    *,
    label:  str = '',
    source: str = '',
) -> Dict:
    e = {
        'type':   'circle',
        'layer':  layer,
        'id':     uuid.uuid4().hex[:12],
        'center': (float(center[0]), float(center[1])),
        'radius': float(radius),
    }
    if label:  e['label']  = label
    if source: e['source'] = source
    return e


def make_polyline(
    points: List[Tuple[float, float]],
    layer:  str = LAYER_CUT,
    *,
    closed: bool = False,
    label:  str  = '',
    source: str  = '',
) -> Dict:
    e = {
        'type':   'polyline',
        'layer':  layer,
        'id':     uuid.uuid4().hex[:12],
        'points': [(float(p[0]), float(p[1])) for p in points],
    }
    if closed: e['closed'] = True
    if label:  e['label']  = label
    if source: e['source'] = source
    return e


# ── Schema helpers ────────────────────────────────────────────────────────────

def ensure_ids(entities: List[Dict]) -> List[Dict]:
    """Stamp a stable 'id' onto any entity that lacks one. Returns the same list."""
    for e in entities:
        if 'id' not in e:
            e['id'] = uuid.uuid4().hex[:12]
    return entities


def ensure_schema(entities: List[Dict], source: str = '') -> List[Dict]:
    """
    Stamp 'id' and optionally 'source' on every entity.
    Also normalises geometry coords to float tuples.
    Returns the same list.
    """
    for e in entities:
        if 'id' not in e:
            e['id'] = uuid.uuid4().hex[:12]
        if source and 'source' not in e:
            e['source'] = source
        normalize(e)
    return entities


def normalize(entity: Dict) -> None:
    """
    Coerce geometry fields in-place to (float, float) tuples.

    Guards against list-format coords from OpenCV/numpy/JSON round-trips.
    No-op if geometry is already tuples.
    """
    etype = entity.get('type')
    if etype == 'line':
        s, en = entity.get('start'), entity.get('end')
        if s is not None:
            entity['start'] = (float(s[0]), float(s[1]))
        if en is not None:
            entity['end'] = (float(en[0]), float(en[1]))
    elif etype == 'circle':
        c = entity.get('center')
        if c is not None:
            entity['center'] = (float(c[0]), float(c[1]))
        r = entity.get('radius')
        if r is not None:
            entity['radius'] = float(r)
    elif etype == 'polyline':
        pts = entity.get('points')
        if pts is not None:
            entity['points'] = [(float(p[0]), float(p[1])) for p in pts]


def is_selectable(entity: Dict) -> bool:
    return entity.get('selectable', True) and not entity.get('locked', False)


# ── Deep clone ────────────────────────────────────────────────────────────────

def clone(entity: Dict, new_id: bool = True) -> Dict:
    """
    Deep-copy an entity dict.

    new_id=True (default) assigns a fresh 'id' so the clone is distinct.
    """
    c = copy.deepcopy(entity)
    if new_id:
        c['id'] = uuid.uuid4().hex[:12]
    return c


def clone_with_offset(entity: Dict, dx: float, dy: float) -> Dict:
    """Clone an entity and translate it by (dx, dy)."""
    c = clone(entity)
    _translate(c, dx, dy)
    return c


# ── Geometry transforms (in-place) ───────────────────────────────────────────

def translate(entity: Dict, dx: float, dy: float) -> None:
    """Translate entity in-place."""
    _translate(entity, dx, dy)


def rotate(entity: Dict, angle_deg: float, cx: float = 0.0, cy: float = 0.0) -> None:
    """Rotate entity in-place around (cx, cy)."""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    def _rot(x: float, y: float) -> Tuple[float, float]:
        rx = x - cx;  ry = y - cy
        return (rx * cos_a - ry * sin_a + cx,
                rx * sin_a + ry * cos_a + cy)

    etype = entity['type']
    if etype == 'line':
        entity['start'] = _rot(*entity['start'])
        entity['end']   = _rot(*entity['end'])
    elif etype == 'circle':
        entity['center'] = _rot(*entity['center'])
        # radius unchanged
    elif etype == 'polyline':
        entity['points'] = [_rot(*p) for p in entity['points']]


def _translate(entity: Dict, dx: float, dy: float) -> None:
    etype = entity['type']
    if etype == 'line':
        entity['start'] = (entity['start'][0] + dx, entity['start'][1] + dy)
        entity['end']   = (entity['end'][0]   + dx, entity['end'][1]   + dy)
    elif etype == 'circle':
        entity['center'] = (entity['center'][0] + dx, entity['center'][1] + dy)
    elif etype == 'polyline':
        entity['points'] = [(x + dx, y + dy) for x, y in entity['points']]


# ── Bounding box ─────────────────────────────────────────────────────────────

def bounding_box(entities: List[Dict]) -> Optional[Tuple[float, float, float, float]]:
    """
    Return (min_x, min_y, max_x, max_y) for a list of entities.
    Returns None if list is empty.
    """
    xs: List[float] = []
    ys: List[float] = []
    for e in entities:
        etype = e.get('type')
        if etype == 'line':
            xs += [e['start'][0], e['end'][0]]
            ys += [e['start'][1], e['end'][1]]
        elif etype == 'circle':
            cx, cy, r = e['center'][0], e['center'][1], e['radius']
            xs += [cx - r, cx + r];  ys += [cy - r, cy + r]
        elif etype == 'polyline':
            for px, py in e['points']:
                xs.append(px); ys.append(py)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def centroid(entity: Dict) -> Optional[Tuple[float, float]]:
    """Return geometric centroid of a single entity, or None."""
    etype = entity.get('type')
    if etype == 'circle':
        return entity['center']
    if etype == 'line':
        s, e = entity['start'], entity['end']
        return ((s[0] + e[0]) / 2, (s[1] + e[1]) / 2)
    if etype == 'polyline' and entity.get('points'):
        pts = entity['points']
        return (sum(p[0] for p in pts) / len(pts),
                sum(p[1] for p in pts) / len(pts))
    return None


# ── DXF export helpers ────────────────────────────────────────────────────────

def entities_to_dxf(entities: List[Dict], output_path: str) -> int:
    """
    Write a list of entities to a DXF file.  Returns entity count written.

    Respects 'layer' field; unrecognised types are skipped silently.
    """
    import ezdxf
    from layers import LayerManager

    doc = ezdxf.new()
    LayerManager(doc)
    msp = doc.modelspace()
    count = 0

    for entity in entities:
        etype = entity.get('type')
        layer = entity.get('layer', LAYER_CUT).upper()
        try:
            if etype == 'line':
                ln = msp.add_line(entity['start'], entity['end'])
                ln.dxf.layer = layer
                count += 1
            elif etype == 'circle':
                c = msp.add_circle(entity['center'], entity['radius'])
                c.dxf.layer = layer
                count += 1
            elif etype == 'polyline' and len(entity.get('points', [])) >= 2:
                closed = entity.get('closed', False)
                p = msp.add_lwpolyline(entity['points'],
                                       dxfattribs={'layer': layer})
                if closed:
                    p.close(True)
                count += 1
        except Exception:
            pass   # skip malformed entities

    doc.saveas(output_path)
    return count


# ── Validation ────────────────────────────────────────────────────────────────

def validate(entity: Dict) -> List[str]:
    """
    Return a list of problems with an entity dict.
    Empty list → valid.
    """
    errors: List[str] = []
    etype = entity.get('type')
    if etype not in ('line', 'circle', 'polyline'):
        errors.append(f"Unknown type: {etype!r}")
        return errors
    if 'layer' not in entity:
        errors.append("Missing 'layer'")
    if 'id' not in entity:
        errors.append("Missing 'id'")
    if etype == 'line':
        for key in ('start', 'end'):
            v = entity.get(key)
            if v is None or len(v) != 2:
                errors.append(f"Missing/invalid '{key}'")
            else:
                try:
                    float(v[0]); float(v[1])
                except (TypeError, ValueError):
                    errors.append(f"Non-numeric coords in '{key}'")
    elif etype == 'circle':
        c = entity.get('center')
        if c is None or len(c) != 2:
            errors.append("Missing/invalid 'center'")
        else:
            try:
                float(c[0]); float(c[1])
            except (TypeError, ValueError):
                errors.append("Non-numeric coords in 'center'")
        r = entity.get('radius')
        if r is None:
            errors.append("Missing 'radius'")
        elif float(r) <= 0:
            errors.append("radius must be > 0")
    elif etype == 'polyline':
        pts = entity.get('points', [])
        if len(pts) < 2:
            errors.append("polyline needs at least 2 points")
        else:
            for i, p in enumerate(pts):
                try:
                    float(p[0]); float(p[1])
                except (TypeError, ValueError, IndexError):
                    errors.append(f"Non-numeric coords in 'points[{i}]'")
                    break
    return errors


def is_valid(entity: Dict) -> bool:
    """Return True if entity passes validation."""
    return len(validate(entity)) == 0
