"""
tests/test_editor_operations.py — Tests for editor mutations and undo/redo.

Tests are written against entity_model functions directly — no Tk canvas
required.  The canvas is a thin dispatch layer; the mutation logic lives
in entity_model and the pure undo snapshot mechanism.

Run with:  python -m pytest tests/ -v
       or: python tests/test_editor_operations.py
"""

import copy
import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import entity_model as em


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_entities():
    """Return a fresh list of three test entities."""
    return em.ensure_schema([
        em.make_line((0, 0), (10, 0), layer='CUT'),
        em.make_circle((5, 5), 3.0, layer='HOLES'),
        em.make_polyline([(20, 0), (30, 0), (30, 10)], layer='CUT'),
    ])


class UndoBuffer:
    """Minimal snapshot-based undo/redo matching InteractiveCanvas behaviour."""
    def __init__(self, limit: int = 40):
        self._stack: list = []
        self._redo:  list = []
        self._limit  = limit

    def push(self, entities: list) -> None:
        self._redo.clear()
        self._stack.append(copy.deepcopy(entities))
        if len(self._stack) > self._limit:
            self._stack.pop(0)

    def undo(self, entities: list) -> bool:
        if not self._stack: return False
        self._redo.append(copy.deepcopy(entities))
        snapshot = self._stack.pop()
        entities.clear(); entities.extend(snapshot)
        return True

    def redo(self, entities: list) -> bool:
        if not self._redo: return False
        self._stack.append(copy.deepcopy(entities))
        snapshot = self._redo.pop()
        entities.clear(); entities.extend(snapshot)
        return True

    @property
    def can_undo(self) -> bool: return bool(self._stack)
    @property
    def can_redo(self) -> bool: return bool(self._redo)


# ── Move (translate) tests ────────────────────────────────────────────────────

def test_move_line():
    ents = _make_entities()
    original_start = ents[0]['start']
    em.translate(ents[0], 5, 3)
    assert ents[0]['start'] == (5.0, 3.0)
    assert ents[0]['end']   == (15.0, 3.0)


def test_move_circle():
    ents = _make_entities()
    em.translate(ents[1], -2, 4)
    assert ents[1]['center'] == (3.0, 9.0)


def test_move_polyline():
    ents = _make_entities()
    em.translate(ents[2], 10, -5)
    assert ents[2]['points'][0] == (30.0, -5.0)
    assert ents[2]['points'][1] == (40.0, -5.0)


def test_move_preserves_id():
    ents = _make_entities()
    original_id = ents[0]['id']
    em.translate(ents[0], 1, 1)
    assert ents[0]['id'] == original_id


def test_move_preserves_layer():
    ents = _make_entities()
    em.translate(ents[1], 0, 0)
    assert ents[1]['layer'] == 'HOLES'


def test_move_then_undo():
    ents = _make_entities()
    buf = UndoBuffer()
    original_start = ents[0]['start']

    buf.push(ents)
    em.translate(ents[0], 5, 3)
    assert ents[0]['start'] == (5.0, 3.0)

    buf.undo(ents)
    assert ents[0]['start'] == original_start


# ── Delete tests ──────────────────────────────────────────────────────────────

def _delete(entities, selected_indices):
    """Simulate InteractiveCanvas.delete_selected()."""
    for idx in sorted(selected_indices, reverse=True):
        if 0 <= idx < len(entities):
            del entities[idx]


def test_delete_first():
    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    _delete(ents, {0})
    assert len(ents) == 2
    # Remaining entities are circle and polyline
    assert ents[0]['type'] == 'circle'


def test_delete_multiple():
    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    _delete(ents, {0, 2})
    assert len(ents) == 1
    assert ents[0]['type'] == 'circle'


def test_delete_all():
    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    _delete(ents, {0, 1, 2})
    assert len(ents) == 0


def test_delete_undo():
    ents = _make_entities()
    buf = UndoBuffer()
    original_ids = [e['id'] for e in ents]

    buf.push(ents)
    _delete(ents, {1})
    assert len(ents) == 2

    buf.undo(ents)
    assert len(ents) == 3
    assert [e['id'] for e in ents] == original_ids


def test_delete_undo_redo():
    ents = _make_entities()
    buf = UndoBuffer()
    circle_id = ents[1]['id']

    buf.push(ents)
    _delete(ents, {1})
    assert not any(e['id'] == circle_id for e in ents)

    buf.undo(ents)
    assert any(e['id'] == circle_id for e in ents)

    buf.redo(ents)
    assert not any(e['id'] == circle_id for e in ents)


# ── Duplicate tests ───────────────────────────────────────────────────────────

_DUP_OFFSET = 5.0

def _duplicate(entities, selected_indices):
    """Simulate InteractiveCanvas.duplicate_selected()."""
    new_entities = [
        em.clone_with_offset(entities[i], _DUP_OFFSET, -_DUP_OFFSET)
        for i in sorted(selected_indices)
        if 0 <= i < len(entities)
    ]
    entities.extend(new_entities)
    return set(range(len(entities) - len(new_entities), len(entities)))


def test_duplicate_creates_new_entity():
    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    new_sel = _duplicate(ents, {0})
    assert len(ents) == 4


def test_duplicate_has_new_id():
    ents = _make_entities()
    orig_id = ents[0]['id']
    new_sel = _duplicate(ents, {0})
    duped = ents[list(new_sel)[0]]
    assert duped['id'] != orig_id


def test_duplicate_offset_applied():
    ents = _make_entities()
    orig_start = ents[0]['start']
    _duplicate(ents, {0})
    duped = ents[-1]
    assert duped['start'] == (orig_start[0] + _DUP_OFFSET,
                               orig_start[1] - _DUP_OFFSET)


def test_duplicate_preserves_layer():
    ents = _make_entities()
    _duplicate(ents, {1})
    duped = ents[-1]
    assert duped['layer'] == 'HOLES'


def test_duplicate_does_not_mutate_original():
    ents = _make_entities()
    orig_start = ents[0]['start']
    _duplicate(ents, {0})
    assert ents[0]['start'] == orig_start


def test_duplicate_undo():
    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    _duplicate(ents, {0})
    assert len(ents) == 4

    buf.undo(ents)
    assert len(ents) == 3


def test_duplicate_multiple_selected():
    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    _duplicate(ents, {0, 2})
    assert len(ents) == 5


# ── Rotate tests ──────────────────────────────────────────────────────────────

def test_rotate_line_90_around_origin():
    e = em.make_line((1, 0), (2, 0))
    em.rotate(e, 90.0, 0.0, 0.0)
    assert abs(e['start'][0] - 0.0) < 1e-9
    assert abs(e['start'][1] - 1.0) < 1e-9
    assert abs(e['end'][0]   - 0.0) < 1e-9
    assert abs(e['end'][1]   - 2.0) < 1e-9


def test_rotate_circle_does_not_change_radius():
    e = em.make_circle((3, 0), 5.0)
    em.rotate(e, 45.0, 0.0, 0.0)
    assert e['radius'] == 5.0


def test_rotate_selected_around_bbox_centroid():
    """Rotate two entities 180° around their combined bounding box centroid."""
    ents = [
        em.make_line((0, 0), (10, 0)),
        em.make_line((0, 10), (10, 10)),
    ]
    em.ensure_schema(ents)
    selected = [ents[0], ents[1]]
    bb = em.bounding_box(selected)
    cx = (bb[0] + bb[2]) / 2   # 5.0
    cy = (bb[1] + bb[3]) / 2   # 5.0

    for e in selected:
        em.rotate(e, 180.0, cx, cy)

    # After 180° rotation around (5,5): (0,0) → (10,10), (10,0) → (0,10)
    assert abs(ents[0]['start'][0] - 10.0) < 1e-9
    assert abs(ents[0]['start'][1] - 10.0) < 1e-9


def test_rotate_undo():
    ents = _make_entities()
    buf = UndoBuffer()
    # Use 'end' — line goes (0,0)→(10,0); rotating 90° moves end to (0,10)
    original_end = tuple(ents[0]['end'])

    buf.push(ents)
    em.rotate(ents[0], 90.0, 0.0, 0.0)
    assert ents[0]['end'] != original_end   # (10,0) → (0,10)

    buf.undo(ents)
    assert abs(ents[0]['end'][0] - original_end[0]) < 1e-9
    assert abs(ents[0]['end'][1] - original_end[1]) < 1e-9


# ── Undo/redo stack behaviour ─────────────────────────────────────────────────

def test_undo_empty_is_noop():
    ents = _make_entities()
    buf = UndoBuffer()
    result = buf.undo(ents)
    assert result is False
    assert len(ents) == 3   # unchanged


def test_redo_empty_is_noop():
    ents = _make_entities()
    buf = UndoBuffer()
    result = buf.redo(ents)
    assert result is False


def test_redo_cleared_by_new_action():
    ents = _make_entities()
    buf = UndoBuffer()

    buf.push(ents)
    em.translate(ents[0], 5, 0)

    buf.push(ents)
    em.translate(ents[0], 5, 0)

    buf.undo(ents)
    assert buf.can_redo

    # A new push should clear the redo stack
    buf.push(ents)
    assert not buf.can_redo


def test_undo_redo_sequence():
    ents = _make_entities()
    buf = UndoBuffer()
    ids = [e['id'] for e in ents]

    # Action 1: delete entity 0
    buf.push(ents)
    _delete(ents, {0})
    assert len(ents) == 2

    # Action 2: duplicate entity 0 (now previously entity 1)
    buf.push(ents)
    _duplicate(ents, {0})
    assert len(ents) == 3

    # Undo action 2
    buf.undo(ents)
    assert len(ents) == 2

    # Undo action 1
    buf.undo(ents)
    assert len(ents) == 3
    assert [e['id'] for e in ents] == ids

    # Redo action 1
    buf.redo(ents)
    assert len(ents) == 2


def test_undo_limit():
    ents = [em.make_line((0, 0), (1, 0))]
    em.ensure_schema(ents)
    buf = UndoBuffer(limit=5)
    for i in range(10):
        buf.push(ents)
        em.translate(ents[0], 1, 0)
    # Only 5 undo steps available
    count = 0
    while buf.can_undo:
        buf.undo(ents); count += 1
    assert count == 5


# ── Lock/unlock ───────────────────────────────────────────────────────────────

def test_lock_makes_unselectable():
    e = em.make_line((0, 0), (1, 0))
    assert em.is_selectable(e)
    e['locked'] = True
    assert not em.is_selectable(e)


def test_unlock_restores_selectable():
    e = em.make_line((0, 0), (1, 0))
    e['locked'] = True
    e.pop('locked')
    assert em.is_selectable(e)


def test_locked_entity_is_valid():
    """Locking does not corrupt the entity."""
    e = em.make_line((0, 0), (1, 0))
    e['locked'] = True
    assert em.is_valid(e)


def test_locked_entity_translatable():
    """Locked entities can still be transformed by entity_model functions."""
    e = em.make_line((0, 0), (10, 0))
    e['locked'] = True
    em.translate(e, 5, 0)   # must not raise
    assert e['start'] == (5.0, 0.0)


# ── Export / import round-trip ────────────────────────────────────────────────

def test_export_import_roundtrip():
    import tempfile, os
    from preview_engine import extract_entities_from_dxf

    original = em.ensure_schema([
        em.make_line((0, 0), (100, 0), layer='CUT'),
        em.make_circle((50, 50), 20, layer='HOLES'),
        em.make_polyline([(0, 0), (50, 0), (50, 50)], layer='CUT'),
    ])

    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name

    try:
        count = em.entities_to_dxf(original, path)
        assert count == 3

        import ezdxf
        doc = ezdxf.readfile(path)
        reloaded = extract_entities_from_dxf(doc)

        assert len(reloaded) == 3

        # Verify types preserved
        types_orig    = sorted(e['type'] for e in original)
        types_reload  = sorted(e['type'] for e in reloaded)
        assert types_orig == types_reload

        # Verify layers preserved
        layers_orig   = sorted(e['layer'] for e in original)
        layers_reload = sorted(e['layer'] for e in reloaded)
        assert layers_orig == layers_reload

        # All reloaded entities have ids (stamped by ensure_schema in extract)
        assert all('id' in e for e in reloaded)
        assert all('source' in e for e in reloaded)

    finally:
        os.unlink(path)


def test_export_preserves_geometry_line():
    import tempfile, os
    from preview_engine import extract_entities_from_dxf

    original = [em.make_line((10, 20), (30, 40), layer='CUT')]
    em.ensure_schema(original)

    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        em.entities_to_dxf(original, path)
        import ezdxf
        reloaded = extract_entities_from_dxf(ezdxf.readfile(path))
        line = next(e for e in reloaded if e['type'] == 'line')
        assert abs(line['start'][0] - 10.0) < 1e-4
        assert abs(line['start'][1] - 20.0) < 1e-4
        assert abs(line['end'][0]   - 30.0) < 1e-4
        assert abs(line['end'][1]   - 40.0) < 1e-4
    finally:
        os.unlink(path)


def test_export_preserves_geometry_circle():
    import tempfile, os
    from preview_engine import extract_entities_from_dxf

    original = [em.make_circle((15, 25), 7.5, layer='HOLES')]
    em.ensure_schema(original)

    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        em.entities_to_dxf(original, path)
        import ezdxf
        reloaded = extract_entities_from_dxf(ezdxf.readfile(path))
        c = next(e for e in reloaded if e['type'] == 'circle')
        assert abs(c['center'][0] - 15.0) < 1e-4
        assert abs(c['center'][1] - 25.0) < 1e-4
        assert abs(c['radius']    - 7.5)  < 1e-4
    finally:
        os.unlink(path)


def test_export_no_stale_entities_after_edit():
    """Delete one entity, export — exported count must match post-edit list."""
    import tempfile, os
    from preview_engine import extract_entities_from_dxf

    ents = _make_entities()
    buf = UndoBuffer()
    buf.push(ents)
    _delete(ents, {1})   # remove the circle
    assert len(ents) == 2

    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        count = em.entities_to_dxf(ents, path)
        assert count == 2    # not 3
        import ezdxf
        reloaded = extract_entities_from_dxf(ezdxf.readfile(path))
        assert len(reloaded) == 2
        assert not any(e['type'] == 'circle' for e in reloaded)
    finally:
        os.unlink(path)


def test_export_layer_cut_preserved():
    import tempfile, os
    from preview_engine import extract_entities_from_dxf

    ents = [em.make_line((0, 0), (1, 0), layer='CUT')]
    em.ensure_schema(ents)
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        em.entities_to_dxf(ents, path)
        import ezdxf
        reloaded = extract_entities_from_dxf(ezdxf.readfile(path))
        assert reloaded[0]['layer'] == 'CUT'
    finally:
        os.unlink(path)


def test_export_layer_holes_preserved():
    import tempfile, os
    from preview_engine import extract_entities_from_dxf

    ents = [em.make_circle((0, 0), 5, layer='HOLES')]
    em.ensure_schema(ents)
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        em.entities_to_dxf(ents, path)
        import ezdxf
        reloaded = extract_entities_from_dxf(ezdxf.readfile(path))
        assert reloaded[0]['layer'] == 'HOLES'
    finally:
        os.unlink(path)


if __name__ == '__main__':
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith('test_')]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
            passed += 1
        except Exception:
            print(f'  FAIL  {t.__name__}')
            traceback.print_exc()
            failed += 1
    print(f'\n{passed} passed, {failed} failed')
