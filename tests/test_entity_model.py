"""
tests/test_entity_model.py — Unit tests for entity_model.py

Run with:  python -m pytest tests/ -v
       or: python tests/test_entity_model.py
"""

import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import entity_model as em


# ── Factory functions ─────────────────────────────────────────────────────────

def test_make_line_has_required_keys():
    e = em.make_line((0, 0), (10, 10))
    assert e['type'] == 'line'
    assert e['layer'] == 'CUT'
    assert 'id' in e
    assert e['start'] == (0.0, 0.0)
    assert e['end'] == (10.0, 10.0)


def test_make_circle_has_required_keys():
    e = em.make_circle((5, 5), 3.0)
    assert e['type'] == 'circle'
    assert e['layer'] == 'HOLES'
    assert 'id' in e
    assert e['center'] == (5.0, 5.0)
    assert e['radius'] == 3.0


def test_make_polyline_has_required_keys():
    e = em.make_polyline([(0, 0), (10, 0), (10, 10)])
    assert e['type'] == 'polyline'
    assert e['layer'] == 'CUT'
    assert 'id' in e
    assert len(e['points']) == 3


def test_factory_unique_ids():
    a = em.make_line((0, 0), (1, 0))
    b = em.make_line((0, 0), (1, 0))
    assert a['id'] != b['id']


def test_factory_source_label():
    e = em.make_polyline([(0, 0), (1, 0)], source='generator', label='Test')
    assert e['source'] == 'generator'
    assert e['label'] == 'Test'


# ── ensure_ids ────────────────────────────────────────────────────────────────

def test_ensure_ids_stamps_missing():
    entities = [{'type': 'line', 'layer': 'CUT', 'start': (0, 0), 'end': (1, 0)}]
    em.ensure_ids(entities)
    assert 'id' in entities[0]


def test_ensure_ids_preserves_existing():
    entities = [{'type': 'line', 'layer': 'CUT', 'start': (0, 0), 'end': (1, 0), 'id': 'my-id'}]
    em.ensure_ids(entities)
    assert entities[0]['id'] == 'my-id'


# ── ensure_schema ─────────────────────────────────────────────────────────────

def test_ensure_schema_stamps_source():
    entities = [{'type': 'line', 'layer': 'CUT', 'start': [0, 0], 'end': [10, 5]}]
    em.ensure_schema(entities, source='generator')
    e = entities[0]
    assert 'id' in e
    assert e['source'] == 'generator'
    # normalise: lists become tuples
    assert isinstance(e['start'], tuple)
    assert isinstance(e['end'], tuple)


def test_ensure_schema_respects_existing_source():
    entities = [em.make_line((0, 0), (1, 0), source='manual')]
    em.ensure_schema(entities, source='generator')
    assert entities[0]['source'] == 'manual'   # not overwritten


# ── normalize ─────────────────────────────────────────────────────────────────

def test_normalize_line_list_to_tuple():
    e = {'type': 'line', 'layer': 'CUT', 'start': [1, 2], 'end': [3, 4]}
    em.normalize(e)
    assert e['start'] == (1.0, 2.0)
    assert e['end'] == (3.0, 4.0)


def test_normalize_circle_list_to_tuple():
    e = {'type': 'circle', 'layer': 'HOLES', 'center': [5, 6], 'radius': 3}
    em.normalize(e)
    assert e['center'] == (5.0, 6.0)
    assert e['radius'] == 3.0


def test_normalize_polyline_list_to_tuple():
    e = {'type': 'polyline', 'layer': 'CUT', 'points': [[0, 0], [10, 0], [10, 10]]}
    em.normalize(e)
    assert all(isinstance(p, tuple) for p in e['points'])


# ── Transforms ────────────────────────────────────────────────────────────────

def test_translate_line():
    e = em.make_line((0, 0), (10, 0))
    em.translate(e, 5, 3)
    assert e['start'] == (5.0, 3.0)
    assert e['end'] == (15.0, 3.0)


def test_translate_circle():
    e = em.make_circle((0, 0), 5)
    em.translate(e, 2, -1)
    assert e['center'] == (2.0, -1.0)


def test_translate_polyline():
    e = em.make_polyline([(0, 0), (10, 0)])
    em.translate(e, 1, 2)
    assert e['points'] == [(1.0, 2.0), (11.0, 2.0)]


def test_rotate_line_90():
    e = em.make_line((1, 0), (0, 0))
    em.rotate(e, 90.0, 0.0, 0.0)
    # (1,0) rotated 90° → (0,1)
    assert abs(e['start'][0] - 0.0) < 1e-9
    assert abs(e['start'][1] - 1.0) < 1e-9


def test_rotate_circle_center_only():
    e = em.make_circle((1, 0), 5)
    em.rotate(e, 90.0, 0.0, 0.0)
    assert abs(e['center'][0] - 0.0) < 1e-9
    assert abs(e['center'][1] - 1.0) < 1e-9
    assert e['radius'] == 5.0   # radius must not change


# ── clone ─────────────────────────────────────────────────────────────────────

def test_clone_is_deep_copy():
    e = em.make_polyline([(0, 0), (10, 0)])
    c = em.clone(e)
    c['points'][0] = (99, 99)
    assert e['points'][0] == (0.0, 0.0)   # original unchanged


def test_clone_new_id():
    e = em.make_line((0, 0), (1, 0))
    c = em.clone(e, new_id=True)
    assert c['id'] != e['id']


def test_clone_same_id():
    e = em.make_line((0, 0), (1, 0))
    c = em.clone(e, new_id=False)
    assert c['id'] == e['id']


def test_clone_with_offset():
    e = em.make_line((0, 0), (10, 0))
    c = em.clone_with_offset(e, 5, 3)
    assert c['start'] == (5.0, 3.0)
    assert e['start'] == (0.0, 0.0)   # original unchanged


# ── bounding_box ──────────────────────────────────────────────────────────────

def test_bounding_box_empty():
    assert em.bounding_box([]) is None


def test_bounding_box_line():
    e = em.make_line((-1, -2), (3, 4))
    bb = em.bounding_box([e])
    assert bb == (-1.0, -2.0, 3.0, 4.0)


def test_bounding_box_circle():
    e = em.make_circle((0, 0), 5)
    bb = em.bounding_box([e])
    assert bb == (-5.0, -5.0, 5.0, 5.0)


def test_bounding_box_mixed():
    entities = [
        em.make_line((0, 0), (10, 0)),
        em.make_circle((5, 5), 3),
    ]
    bb = em.bounding_box(entities)
    assert bb[0] == 0.0    # min_x = 0
    assert bb[1] == 0.0    # min_y = min(0, 5-3) = 2? no, line y=0 is lower → 0
    assert bb[2] == 10.0
    assert bb[3] == 8.0    # max_y = 5+3 = 8


# ── centroid ──────────────────────────────────────────────────────────────────

def test_centroid_circle():
    e = em.make_circle((3, 7), 2)
    assert em.centroid(e) == (3.0, 7.0)


def test_centroid_line():
    e = em.make_line((0, 0), (10, 4))
    assert em.centroid(e) == (5.0, 2.0)


def test_centroid_polyline():
    e = em.make_polyline([(0, 0), (4, 0), (4, 4), (0, 4)])
    cx, cy = em.centroid(e)
    assert cx == 2.0 and cy == 2.0


# ── validate / is_valid ───────────────────────────────────────────────────────

def test_validate_valid_line():
    e = em.make_line((0, 0), (10, 0))
    assert em.validate(e) == []


def test_validate_valid_circle():
    e = em.make_circle((0, 0), 5)
    assert em.validate(e) == []


def test_validate_valid_polyline():
    e = em.make_polyline([(0, 0), (10, 0)])
    assert em.validate(e) == []


def test_validate_unknown_type():
    errors = em.validate({'type': 'arc', 'layer': 'CUT', 'id': 'x'})
    assert any('Unknown type' in err for err in errors)


def test_validate_missing_layer():
    e = em.make_line((0, 0), (1, 0))
    del e['layer']
    errors = em.validate(e)
    assert any("'layer'" in err for err in errors)


def test_validate_zero_radius():
    e = em.make_circle((0, 0), 0)
    errors = em.validate(e)
    assert any('radius' in err for err in errors)


def test_validate_polyline_one_point():
    e = em.make_polyline([(0, 0)])
    # Only one point — should fail (but make_polyline allows it; validate catches it)
    errors = em.validate(e)
    assert any('2 points' in err for err in errors)


def test_is_valid_true():
    assert em.is_valid(em.make_line((0, 0), (1, 0)))


def test_is_valid_false():
    assert not em.is_valid({'type': 'line', 'layer': 'CUT', 'id': 'x'})


# ── is_selectable ─────────────────────────────────────────────────────────────

def test_is_selectable_default():
    assert em.is_selectable(em.make_line((0, 0), (1, 0)))


def test_is_selectable_false():
    e = em.make_line((0, 0), (1, 0))
    e['selectable'] = False
    assert not em.is_selectable(e)


def test_is_selectable_locked():
    e = em.make_line((0, 0), (1, 0))
    e['locked'] = True
    assert not em.is_selectable(e)


# ── panel_decomposition round-trip ────────────────────────────────────────────

def test_panel_entities_have_ids():
    from panel_decomposition import decompose_box, panels_to_entities
    panels = decompose_box(200, 150, 80)
    entities = panels_to_entities(panels)
    assert all('id' in e for e in entities)


def test_panel_entities_have_source():
    from panel_decomposition import decompose_box, panels_to_entities
    panels = decompose_box(200, 150, 80)
    entities = panels_to_entities(panels)
    assert all(e.get('source') == em.SOURCE_PANEL for e in entities)


def test_box_decompose_dimensions():
    from panel_decomposition import decompose_box
    panels = decompose_box(width=300, depth=200, wall_height=100, thickness=2.0)
    # Bottom panel inner size
    bottom = next(p for p in panels if 'Bottom' in p.label)
    assert abs(bottom.width  - (300 - 4.0)) < 0.01   # 300 - 2*2 = 296
    assert abs(bottom.height - (200 - 4.0)) < 0.01   # 200 - 2*2 = 196
    # Net wall height
    front = next(p for p in panels if 'Front' in p.label)
    assert abs(front.height - (100 - 2.0)) < 0.01    # 100 - thickness = 98


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
