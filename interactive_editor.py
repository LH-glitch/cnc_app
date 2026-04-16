"""
interactive_editor.py — Zoomable, pannable, interactive tk.Canvas for CNC entity editing.

Pure widget: owns no application state.  Callers pass entities via set_entities();
all mutations are applied in-place to that list.

Entity dict format: see entity_model.py (additive superset of preview_engine format).

Coordinate convention
---------------------
  World  : mm, Y-up  (same as DXF / preview_engine)
  Screen : pixels, Y-down  (tk.Canvas native)

  screen_x =  (world_x - vp_ox) * scale
  screen_y = canvas_h - (world_y - vp_oy) * scale

Features
--------
  • Select: LMB click  (Ctrl = add/toggle to selection)
  • Box select: LMB drag on empty space
  • Move: LMB drag selected entities
  • Nudge: Arrow keys (1 mm; Shift = 10 mm)
  • Duplicate: Ctrl+D (clone + offset 5 mm)
  • Delete: Delete / Backspace
  • Rotate: Ctrl+R (90°) or Ctrl+Shift+R (−90°) around selection centroid
  • Pan: RMB or MMB drag
  • Zoom: scroll wheel, centred on cursor
  • Undo/Redo: Ctrl+Z / Ctrl+Y (20-step stack)
"""

import copy
import math
import tkinter as tk
from typing import Callable, Dict, List, Optional, Set, Tuple

from preview_engine import LAYER_STYLES
import entity_model as em

# ── Visual constants ──────────────────────────────────────────────────────────
_SEL_FILL    = '#00bcd4'    # selected entity stroke colour
_SEL_OUTLINE = '#0097a7'    # dashed outline around selection bounding box
_SEL_BONUS   = 2.5          # extra line-width when selected
_HIT_R       = 8            # pixel hit-test radius for point entities
_BOX_COLOR   = '#1565c0'    # rubber-band box stroke
_GRID_COLOR  = '#e4e7eb'
_AXIS_COLOR  = '#bdc3cc'
_GRID_MIN_PX = 35
_NUDGE_SMALL = 1.0          # mm per arrow key press
_NUDGE_LARGE = 10.0         # mm with Shift held
_DUP_OFFSET  = 5.0          # mm offset for Ctrl+D duplicate
_UNDO_LIMIT  = 40


class InteractiveCanvas:
    """
    Zoomable, pannable, interactive CNC entity editor.

    Parameters
    ----------
    parent               : tk parent widget
    on_selection_change  : callable(count) — fired when selection changes
    on_modified          : callable()      — fired after any data mutation
    """

    def __init__(
        self,
        parent,
        on_selection_change: Optional[Callable[[int], None]] = None,
        on_modified:         Optional[Callable[[], None]]    = None,
    ):
        self._on_selection_change = on_selection_change
        self._on_modified         = on_modified

        self._canvas = tk.Canvas(
            parent,
            bg='#f9fafc',
            cursor='crosshair',
            highlightthickness=1,
            highlightbackground='#dde1e7',
        )

        # ── Viewport ──────────────────────────────────────────────────────────
        self._vp_ox:    float = -50.0
        self._vp_oy:    float = -50.0
        self._vp_scale: float = 3.0     # pixels per mm

        # ── Data ──────────────────────────────────────────────────────────────
        self._entities: List[Dict] = []
        self._selected: Set[int]   = set()   # indices into _entities

        # canvas item → entity index
        self._item_to_entity:  Dict[int, int]       = {}
        self._entity_to_items: Dict[int, List[int]] = {}

        # ── Interaction state ─────────────────────────────────────────────────
        self._mode = 'idle'         # 'idle' | 'drag' | 'box' | 'pan'

        # Drag-move
        self._drag_last:  Optional[Tuple[float, float]] = None
        self._drag_start: Optional[Tuple[float, float]] = None

        # Box-select rubber band
        self._box_start:  Optional[Tuple[float, float]] = None
        self._box_item:   Optional[int]                 = None

        # Pan
        self._pan_start:    Optional[Tuple[int, int]] = None
        self._pan_ox_saved: float = 0.0
        self._pan_oy_saved: float = 0.0

        # ── Undo stack ────────────────────────────────────────────────────────
        # Each entry is a deep-copy snapshot of self._entities
        self._undo_stack: List[List[Dict]] = []
        self._redo_stack: List[List[Dict]] = []

        # ── Event bindings ────────────────────────────────────────────────────
        c = self._canvas
        c.bind('<Configure>',       self._on_configure)
        c.bind('<ButtonPress-1>',   self._on_lmb_press)
        c.bind('<B1-Motion>',       self._on_lmb_motion)
        c.bind('<ButtonRelease-1>', self._on_lmb_release)
        c.bind('<ButtonPress-2>',   self._on_pan_press)
        c.bind('<B2-Motion>',       self._on_pan_motion)
        c.bind('<ButtonRelease-2>', self._on_pan_release)
        c.bind('<ButtonPress-3>',   self._on_pan_press)
        c.bind('<B3-Motion>',       self._on_pan_motion)
        c.bind('<ButtonRelease-3>', self._on_pan_release)
        c.bind('<MouseWheel>',      self._on_scroll)
        c.bind('<Button-4>',        self._on_scroll)
        c.bind('<Button-5>',        self._on_scroll)
        c.bind('<Delete>',          lambda _e: self.delete_selected())
        c.bind('<BackSpace>',       lambda _e: self.delete_selected())
        c.bind('<Left>',            lambda e: self._nudge(-_nudge(e), 0))
        c.bind('<Right>',           lambda e: self._nudge( _nudge(e), 0))
        c.bind('<Up>',              lambda e: self._nudge(0,  _nudge(e)))
        c.bind('<Down>',            lambda e: self._nudge(0, -_nudge(e)))
        c.bind('<Control-a>',       lambda _e: self.select_all())
        c.bind('<Control-A>',       lambda _e: self.select_all())
        c.bind('<Control-d>',       lambda _e: self.duplicate_selected())
        c.bind('<Control-D>',       lambda _e: self.duplicate_selected())
        c.bind('<Control-z>',       lambda _e: self.undo())
        c.bind('<Control-Z>',       lambda _e: self.undo())
        c.bind('<Control-y>',       lambda _e: self.redo())
        c.bind('<Control-Y>',       lambda _e: self.redo())
        c.bind('<Control-r>',       lambda _e: self.rotate_selected(90.0))
        c.bind('<Control-R>',       lambda _e: self.rotate_selected(-90.0))

    # ── Widget integration ────────────────────────────────────────────────────

    def pack(self, **kw):   self._canvas.pack(**kw)
    def grid(self, **kw):   self._canvas.grid(**kw)

    @property
    def widget(self) -> tk.Canvas:
        return self._canvas

    # ── Public API ────────────────────────────────────────────────────────────

    def set_entities(self, entities: List[Dict]) -> None:
        """Replace entity list, clear selection & undo stack, fit view, redraw."""
        em.ensure_schema(entities)   # stamp ids + normalise geometry
        self._entities = entities
        self._selected.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify_selection()
        self.fit_to_entities()

    def get_entities(self) -> List[Dict]:
        """Return the current entity list (live reference)."""
        return self._entities

    def fit_to_entities(self) -> None:
        xs, ys = self._all_coords()
        if not xs:
            self._vp_ox, self._vp_oy, self._vp_scale = -50.0, -50.0, 3.0
            self.redraw(); return

        w = max(self._canvas.winfo_width(),  1)
        h = max(self._canvas.winfo_height(), 1)
        ww = max(max(xs) - min(xs), 1.0)
        wh = max(max(ys) - min(ys), 1.0)
        m = 0.15
        self._vp_scale = max(0.1, min(
            min(w / (ww * (1 + 2*m)), h / (wh * (1 + 2*m))),
            500.0
        ))
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        self._vp_ox = cx - (w / 2) / self._vp_scale
        self._vp_oy = cy - (h / 2) / self._vp_scale
        self.redraw()

    def redraw(self) -> None:
        c = self._canvas
        c.delete('all')
        self._item_to_entity.clear()
        self._entity_to_items.clear()
        self._draw_grid()
        self._draw_axes()
        for idx, entity in enumerate(self._entities):
            self._draw_entity(idx, entity)
        self._draw_selection_box_outline()

    # ── Selection ─────────────────────────────────────────────────────────────

    def select_all(self) -> None:
        self._selected = set(range(len(self._entities)))
        self.redraw(); self._notify_selection()

    def clear_selection(self) -> None:
        self._selected.clear()
        self.redraw(); self._notify_selection()

    @property
    def selection_count(self) -> int:
        return len(self._selected)

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    # ── Mutations (all push undo) ─────────────────────────────────────────────

    def lock_selected(self) -> None:
        """Lock selected entities so they cannot be selected or moved."""
        if not self._selected: return
        self._push_undo()
        for idx in self._selected:
            if 0 <= idx < len(self._entities):
                self._entities[idx]['locked'] = True
        self._selected.clear()
        self.redraw(); self._notify_selection(); self._notify_modified()

    def unlock_all(self) -> None:
        """Remove lock from every entity in the canvas."""
        locked = [e for e in self._entities if e.get('locked')]
        if not locked: return
        self._push_undo()
        for e in locked:
            e.pop('locked', None)
        self.redraw(); self._notify_modified()

    def delete_selected(self) -> None:
        if not self._selected: return
        self._push_undo()
        for idx in sorted(self._selected, reverse=True):
            if 0 <= idx < len(self._entities):
                del self._entities[idx]
        self._selected.clear()
        self.redraw(); self._notify_selection(); self._notify_modified()

    def duplicate_selected(self) -> None:
        if not self._selected: return
        self._push_undo()
        new_entities = [
            em.clone_with_offset(self._entities[i], _DUP_OFFSET, -_DUP_OFFSET)
            for i in sorted(self._selected)
            if 0 <= i < len(self._entities)
        ]
        base = len(self._entities)
        self._entities.extend(new_entities)
        self._selected = set(range(base, base + len(new_entities)))
        self.redraw(); self._notify_selection(); self._notify_modified()

    def rotate_selected(self, angle_deg: float) -> None:
        if not self._selected: return
        sel_ents = [self._entities[i] for i in self._selected
                    if 0 <= i < len(self._entities)]
        if not sel_ents: return
        bb = em.bounding_box(sel_ents)
        if bb is None: return
        cx = (bb[0] + bb[2]) / 2
        cy = (bb[1] + bb[3]) / 2
        self._push_undo()
        for e in sel_ents:
            em.rotate(e, angle_deg, cx, cy)
        self.redraw(); self._notify_modified()

    # ── Undo / Redo ───────────────────────────────────────────────────────────

    def undo(self) -> None:
        if not self._undo_stack: return
        self._redo_stack.append(copy.deepcopy(self._entities))
        snapshot = self._undo_stack.pop()
        self._entities.clear()
        self._entities.extend(snapshot)
        self._selected.clear()
        self.redraw(); self._notify_selection(); self._notify_modified()

    def redo(self) -> None:
        if not self._redo_stack: return
        self._undo_stack.append(copy.deepcopy(self._entities))
        snapshot = self._redo_stack.pop()
        self._entities.clear()
        self._entities.extend(snapshot)
        self._selected.clear()
        self.redraw(); self._notify_selection(); self._notify_modified()

    @property
    def can_undo(self) -> bool: return bool(self._undo_stack)
    @property
    def can_redo(self) -> bool: return bool(self._redo_stack)

    def _push_undo(self) -> None:
        self._redo_stack.clear()
        self._undo_stack.append(copy.deepcopy(self._entities))
        if len(self._undo_stack) > _UNDO_LIMIT:
            self._undo_stack.pop(0)

    # ── Coordinate transforms ─────────────────────────────────────────────────

    def _w2s(self, wx: float, wy: float) -> Tuple[float, float]:
        h = max(self._canvas.winfo_height(), 1)
        return ((wx - self._vp_ox) * self._vp_scale,
                 h - (wy - self._vp_oy) * self._vp_scale)

    def _s2w(self, sx: float, sy: float) -> Tuple[float, float]:
        h = max(self._canvas.winfo_height(), 1)
        return (sx / self._vp_scale + self._vp_ox,
                (h - sy) / self._vp_scale + self._vp_oy)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _layer_style(self, layer: str) -> Tuple[str, float]:
        color, lw, _ = LAYER_STYLES.get(layer.upper(), ('#555555', 1.0, 'solid'))
        return color, max(1.0, lw)

    def _draw_entity(self, idx: int, entity: Dict) -> None:
        locked = entity.get('locked', False)
        if not locked and not entity.get('selectable', True):
            return   # non-selectable, non-locked → skip
        if not em.is_valid(entity):
            return   # skip corrupt entities silently
        layer     = entity.get('layer', 'CUT').upper()
        color, lw = self._layer_style(layer)
        selected  = idx in self._selected
        dash: tuple = ()
        if locked:
            color = '#aab0bb'   # muted gray for locked entities
            lw    = max(1.0, lw * 0.6)
            dash  = (4, 4)
        elif selected:
            color = _SEL_FILL
            lw   += _SEL_BONUS

        items: List[int] = []
        etype = entity['type']

        kw_line = dict(fill=color, width=lw, tags='entity', capstyle='round')
        kw_oval = dict(outline=color, fill='', width=lw, tags='entity')
        if dash:
            kw_line['dash'] = dash
            kw_oval['dash'] = dash

        try:
            if etype == 'line':
                sx1, sy1 = self._w2s(*entity['start'])
                sx2, sy2 = self._w2s(*entity['end'])
                items.append(self._canvas.create_line(sx1, sy1, sx2, sy2, **kw_line))

            elif etype == 'circle':
                cx, cy = entity['center']
                r = entity['radius']
                sx1, sy1 = self._w2s(cx - r, cy + r)
                sx2, sy2 = self._w2s(cx + r, cy - r)
                items.append(self._canvas.create_oval(sx1, sy1, sx2, sy2, **kw_oval))

            elif etype == 'polyline':
                pts = entity['points']
                if len(pts) >= 2:
                    flat = []
                    for wx, wy in pts:
                        sx, sy = self._w2s(wx, wy)
                        flat += [sx, sy]
                    if entity.get('closed') and len(pts) >= 3:
                        flat += list(self._w2s(*pts[0]))
                    kw_pl = dict(kw_line, joinstyle='round')
                    items.append(self._canvas.create_line(*flat, **kw_pl))
        except Exception:
            return   # discard items from failed draw

        for item in items:
            self._item_to_entity[item] = idx
        self._entity_to_items[idx] = items

    def _draw_selection_box_outline(self) -> None:
        """Draw a thin dashed bounding rectangle around all selected entities."""
        if not self._selected: return
        sel_ents = [self._entities[i] for i in self._selected
                    if 0 <= i < len(self._entities)]
        if not sel_ents: return
        bb = em.bounding_box(sel_ents)
        if bb is None: return
        sx1, sy1 = self._w2s(bb[0], bb[1])
        sx2, sy2 = self._w2s(bb[2], bb[3])
        # sy1 > sy2 in screen coords (Y flipped) — swap for proper rectangle
        if sy1 < sy2: sy1, sy2 = sy2, sy1
        pad = 4
        self._canvas.create_rectangle(
            sx1 - pad, sy1 + pad, sx2 + pad, sy2 - pad,
            outline=_SEL_OUTLINE, fill='', width=1,
            dash=(5, 3), tags='selbox',
        )

    def _draw_grid(self) -> None:
        w = max(self._canvas.winfo_width(),  1)
        h = max(self._canvas.winfo_height(), 1)
        raw = _GRID_MIN_PX / self._vp_scale
        mag = 10 ** math.floor(math.log10(max(raw, 1e-6)))
        step = mag
        for s in (mag, mag*2, mag*5, mag*10, mag*20, mag*50):
            if s * self._vp_scale >= _GRID_MIN_PX:
                step = s; break
        wx0, wy0 = self._s2w(0, h);  wx1, wy1 = self._s2w(w, 0)
        x = math.floor(wx0 / step) * step
        while x <= wx1 + step:
            sx, _ = self._w2s(x, 0)
            if 0 <= sx <= w:
                self._canvas.create_line(sx, 0, sx, h, fill=_GRID_COLOR, width=1, tags='grid')
            x += step
        y = math.floor(wy0 / step) * step
        while y <= wy1 + step:
            _, sy = self._w2s(0, y)
            if 0 <= sy <= h:
                self._canvas.create_line(0, sy, w, sy, fill=_GRID_COLOR, width=1, tags='grid')
            y += step
        # Grid spacing label in corner
        label = f'{step:.4g} mm'
        self._canvas.create_text(w - 4, h - 4, text=label, anchor='se',
                                  fill='#a0a8b4', font=('Consolas', 7), tags='grid')

    def _draw_axes(self) -> None:
        w = max(self._canvas.winfo_width(),  1)
        h = max(self._canvas.winfo_height(), 1)
        ox, oy = self._w2s(0.0, 0.0)
        self._canvas.create_line(0, oy, w, oy, fill=_AXIS_COLOR, width=1, dash=(6, 4), tags='axis')
        self._canvas.create_line(ox, 0, ox, h, fill=_AXIS_COLOR, width=1, dash=(6, 4), tags='axis')
        self._canvas.create_oval(ox-3, oy-3, ox+3, oy+3, fill=_AXIS_COLOR, outline='', tags='axis')
        # Axis labels
        self._canvas.create_text(ox + 5, oy - 8, text='0,0', fill=_AXIS_COLOR,
                                  font=('Consolas', 7), anchor='w', tags='axis')

    # ── Hit testing ───────────────────────────────────────────────────────────

    def _hit_test(self, sx: float, sy: float) -> Optional[int]:
        items = self._canvas.find_overlapping(
            sx - _HIT_R, sy - _HIT_R, sx + _HIT_R, sy + _HIT_R
        )
        for item in reversed(items):
            if item in self._item_to_entity:
                return self._item_to_entity[item]
        return None

    def _box_select(self, sx1: float, sy1: float, sx2: float, sy2: float,
                    add: bool = False) -> None:
        """Select all entities whose centroid falls inside the screen box."""
        wx1, wy1 = self._s2w(min(sx1, sx2), max(sy1, sy2))
        wx2, wy2 = self._s2w(max(sx1, sx2), min(sy1, sy2))

        if not add:
            self._selected.clear()

        for idx, entity in enumerate(self._entities):
            if not em.is_selectable(entity): continue
            c = em.centroid(entity)
            if c is None: continue
            if wx1 <= c[0] <= wx2 and wy1 <= c[1] <= wy2:
                self._selected.add(idx)

        self._notify_selection()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_configure(self, _event) -> None:
        self.redraw()

    def _on_lmb_press(self, event) -> None:
        self._canvas.focus_set()
        hit  = self._hit_test(event.x, event.y)
        ctrl = bool(event.state & 0x0004)

        if hit is not None:
            # Click on entity → start drag-move
            if hit not in self._selected:
                if not ctrl:
                    self._selected.clear()
                self._selected.add(hit)
                self.redraw(); self._notify_selection()
            self._mode      = 'drag'
            self._drag_start = (event.x, event.y)
            self._drag_last  = (event.x, event.y)
            self._push_undo()   # save state before drag begins
        else:
            # Click on empty space → box select
            if not ctrl:
                self._selected.clear()
            self._mode      = 'box'
            self._box_start = (event.x, event.y)
            if self._box_item:
                self._canvas.delete(self._box_item)
                self._box_item = None

    def _on_lmb_motion(self, event) -> None:
        if self._mode == 'drag' and self._drag_last:
            dx_s = event.x - self._drag_last[0]
            dy_s = event.y - self._drag_last[1]
            self._drag_last = (event.x, event.y)
            dx_w =  dx_s / self._vp_scale
            dy_w = -dy_s / self._vp_scale
            for idx in self._selected:
                if 0 <= idx < len(self._entities):
                    em.translate(self._entities[idx], dx_w, dy_w)
            self.redraw()

        elif self._mode == 'box' and self._box_start:
            # Draw rubber-band rectangle
            if self._box_item:
                self._canvas.delete(self._box_item)
            self._box_item = self._canvas.create_rectangle(
                self._box_start[0], self._box_start[1], event.x, event.y,
                outline=_BOX_COLOR, fill='#1565c015', width=1,
                dash=(4, 3), tags='rubberband',
            )

    def _on_lmb_release(self, event) -> None:
        ctrl = bool(event.state & 0x0004)

        if self._mode == 'drag':
            ds = self._drag_start
            moved = ds and (abs(event.x - ds[0]) > 2 or abs(event.y - ds[1]) > 2)
            if not moved:
                # Tiny move → treat as click; undo the pre-drag snapshot
                if self._undo_stack:
                    self._undo_stack.pop()
            else:
                self._notify_modified()

        elif self._mode == 'box' and self._box_start:
            if self._box_item:
                self._canvas.delete(self._box_item)
                self._box_item = None
            bs = self._box_start
            dist = abs(event.x - bs[0]) + abs(event.y - bs[1])
            if dist > 6:   # only commit if box is non-trivial
                self._box_select(bs[0], bs[1], event.x, event.y, add=ctrl)
                self.redraw()

        self._mode       = 'idle'
        self._drag_start = None
        self._drag_last  = None
        self._box_start  = None

    def _on_pan_press(self, event) -> None:
        self._mode         = 'pan'
        self._pan_start    = (event.x, event.y)
        self._pan_ox_saved = self._vp_ox
        self._pan_oy_saved = self._vp_oy
        self._canvas.config(cursor='fleur')

    def _on_pan_motion(self, event) -> None:
        if self._mode != 'pan' or not self._pan_start: return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        self._vp_ox = self._pan_ox_saved - dx / self._vp_scale
        self._vp_oy = self._pan_oy_saved + dy / self._vp_scale
        self.redraw()

    def _on_pan_release(self, _event) -> None:
        self._mode = 'idle'
        self._canvas.config(cursor='crosshair')

    def _on_scroll(self, event) -> None:
        up = event.num == 4 or (hasattr(event, 'delta') and event.delta > 0)
        factor = 1.15 if up else 1.0 / 1.15
        wx, wy = self._s2w(event.x, event.y)
        self._vp_scale = max(0.1, min(self._vp_scale * factor, 500.0))
        h = max(self._canvas.winfo_height(), 1)
        self._vp_ox = wx - event.x / self._vp_scale
        self._vp_oy = wy - (h - event.y) / self._vp_scale
        self.redraw()

    # ── Nudge ─────────────────────────────────────────────────────────────────

    def _nudge(self, dx: float, dy: float) -> None:
        if not self._selected: return
        self._push_undo()
        for idx in self._selected:
            if 0 <= idx < len(self._entities):
                em.translate(self._entities[idx], dx, dy)
        self.redraw(); self._notify_modified()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _all_coords(self) -> Tuple[List[float], List[float]]:
        xs: List[float] = []
        ys: List[float] = []
        for e in self._entities:
            etype = e.get('type')
            if etype == 'line':
                xs += [e['start'][0], e['end'][0]]
                ys += [e['start'][1], e['end'][1]]
            elif etype == 'circle':
                cx, cy, r = e['center'][0], e['center'][1], e['radius']
                xs += [cx-r, cx+r]; ys += [cy-r, cy+r]
            elif etype == 'polyline':
                for px, py in e['points']:
                    xs.append(px); ys.append(py)
        return xs, ys

    def _notify_selection(self) -> None:
        if self._on_selection_change:
            self._on_selection_change(len(self._selected))

    def _notify_modified(self) -> None:
        if self._on_modified:
            self._on_modified()


# ── Module helper ─────────────────────────────────────────────────────────────

def _nudge(event) -> float:
    """Return nudge distance based on Shift modifier."""
    return _NUDGE_LARGE if (event.state & 0x0001) else _NUDGE_SMALL
