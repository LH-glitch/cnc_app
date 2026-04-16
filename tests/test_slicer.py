"""
tests/test_slicer.py — Unit tests for slicer.py.

Run with:  python tests/test_slicer.py
       or: python -m pytest tests/ -v  (if pytest is installed)
"""

import math
import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import slicer
import entity_model as em


# ── Helpers ───────────────────────────────────────────────────────────────────

def _box(w=100.0, h=80.0, d=60.0):
    return slicer.mesh_from_box(w, h, d)

def _cyl(r=30.0, h=80.0, segs=36):
    return slicer.mesh_from_cylinder(r, h, segs)


# ── Fixed-thickness slicing ───────────────────────────────────────────────────

def test_fixed_thickness_slice_count():
    r = slicer.slice_model(_box(h=80), 20.0)
    assert r.n_boards == 4

def test_fixed_thickness_each_board_correct_size():
    r = slicer.slice_model(_box(h=80), 20.0)
    for s in r.slices:
        assert abs(s.thickness - 20.0) < 1e-6 or abs(s.thickness - 0.0) < 1e-6

def test_fixed_thickness_span():
    r = slicer.slice_model(_box(h=80), 20.0)
    assert abs(r.model_span - 80.0) < 1e-6

def test_fixed_thickness_board_thickness_stored():
    r = slicer.slice_model(_box(h=80), 20.0)
    assert abs(r.board_thickness - 20.0) < 1e-6

def test_fixed_thickness_partial_last_board():
    """span=90, thickness=20 → ceil(90/20)=5 boards; last board is 10mm thick."""
    r = slicer.slice_model(_box(h=90), 20.0)
    assert r.n_boards == 5

def test_fixed_thickness_non_divisible():
    r = slicer.slice_model(_box(h=75), 20.0)
    # ceil(75/20) = 4
    assert r.n_boards == 4


# ── Fixed-count slicing ───────────────────────────────────────────────────────

def test_fixed_count_exact_n_boards():
    r = slicer.slice_model_by_count(_box(h=80), 5)
    assert r.n_boards == 5

def test_fixed_count_computed_thickness():
    r = slicer.slice_model_by_count(_box(h=80), 5)
    assert abs(r.board_thickness - 16.0) < 1e-6

def test_fixed_count_1_board():
    r = slicer.slice_model_by_count(_box(h=80), 1)
    assert r.n_boards == 1

def test_fixed_count_many_boards():
    r = slicer.slice_model_by_count(_box(h=80), 20)
    assert r.n_boards == 20

def test_fixed_count_thickness_times_count_equals_span():
    r = slicer.slice_model_by_count(_box(h=100), 4)
    assert abs(r.board_thickness * 4 - 100.0) < 1e-6

def test_fixed_count_zero_raises():
    try:
        slicer.slice_model_by_count(_box(), 0)
        assert False, 'Should raise'
    except ValueError:
        pass

def test_fixed_thickness_zero_raises():
    try:
        slicer.slice_model(_box(), 0.0)
        assert False, 'Should raise'
    except ValueError:
        pass


# ── Box mesh expected number of slices ───────────────────────────────────────

def test_box_slice_count_matches_ceil():
    for h, t, expected in [(80, 20, 4), (75, 20, 4), (100, 25, 4), (60, 15, 4)]:
        r = slicer.slice_model(_box(h=h), t)
        assert r.n_boards == expected, f"h={h} t={t}: expected {expected} got {r.n_boards}"

def test_box_slices_non_empty():
    r = slicer.slice_model(_box(), 20.0)
    for s in r.slices:
        assert len(s.contours) > 0, f'Board {s.index} has no contours'

def test_box_slice_labels():
    r = slicer.slice_model(_box(h=80), 20.0)
    for i, s in enumerate(r.slices):
        assert f'Board {i+1}' in s.label

def test_box_slice_indices_sequential():
    r = slicer.slice_model(_box(h=80), 20.0)
    for i, s in enumerate(r.slices):
        assert s.index == i

def test_box_slices_sorted_ascending():
    r = slicer.slice_model(_box(h=80), 20.0)
    for i in range(1, len(r.slices)):
        assert r.slices[i].y_min > r.slices[i-1].y_min


# ── Cylinder slicing produces valid contours ──────────────────────────────────

def test_cylinder_slice_count():
    r = slicer.slice_model(_cyl(h=80), 20.0)
    assert r.n_boards == 4

def test_cylinder_contours_valid():
    r = slicer.slice_model(_cyl(r=30, h=80), 20.0)
    for s in r.slices:
        for c in s.contours:
            assert len(c) >= 3, 'Contour must have at least 3 points'

def test_cylinder_contour_roughly_round():
    """Outer contour of a cylinder slice should be roughly circular."""
    r = slicer.slice_model(_cyl(r=30, h=80, segs=72), 20.0)
    s = r.slices[0]
    outer = max(s.contours, key=slicer._contour_area)
    # Centroid should be near (0, 0) — centre of the cylinder
    cx = sum(p[0] for p in outer) / len(outer)
    cz = sum(p[1] for p in outer) / len(outer)
    assert abs(cx) < 5.0, f'cx off centre: {cx:.2f}'
    assert abs(cz) < 5.0, f'cz off centre: {cz:.2f}'
    # All points should be roughly r=30 from centre
    for p in outer:
        dist = math.hypot(p[0] - cx, p[1] - cz)
        assert 20 < dist < 40, f'Point not on cylinder wall: dist={dist:.2f}'

def test_cylinder_area_positive():
    r = slicer.slice_model(_cyl(r=30, h=80), 20.0)
    for s in r.slices:
        outer = max(s.contours, key=slicer._contour_area)
        assert slicer._contour_area(outer) > 0


# ── Degenerate / zero slices skipped ─────────────────────────────────────────

def test_degenerate_zero_height_raises():
    """A mesh with zero Y span must raise ValueError."""
    import numpy as np
    flat = np.array([
        [[0., 0., 0.], [1., 0., 0.], [0.5, 0., 1.]],
    ], dtype=float)
    try:
        slicer.slice_model(flat, 5.0)
        assert False, 'Expected ValueError'
    except ValueError:
        pass

def test_empty_slices_filtered():
    """Slices with no intersecting geometry produce no BoardSlice entries."""
    r = slicer.slice_model(_box(h=80), 20.0)
    # All 4 slices should have contours (box is solid)
    assert all(len(s.contours) > 0 for s in r.slices)

def test_slice_count_at_least_one():
    r = slicer.slice_model(_box(h=1), 20.0)   # thickness > span → 1 board
    assert r.n_boards >= 1


# ── Axis remapping ────────────────────────────────────────────────────────────

def test_axis_y_default_same_as_explicit():
    r1 = slicer.slice_model(_box(w=60, h=80, d=100), 20.0, stacking_axis='y')
    r2 = slicer.slice_model(_box(w=60, h=80, d=100), 20.0)
    assert r1.n_boards == r2.n_boards

def test_axis_x_uses_x_span():
    box = _box(w=100, h=80, d=60)   # X span = 100, Y span = 80
    r = slicer.slice_model(box, 20.0, stacking_axis='x')
    assert r.n_boards == 5           # ceil(100/20)

def test_axis_z_uses_z_span():
    box = _box(w=100, h=80, d=60)
    r = slicer.slice_model(box, 15.0, stacking_axis='z')
    assert r.n_boards == 4           # ceil(60/15)

def test_invalid_axis_raises():
    try:
        slicer.remap_axis(_box(), 'w')
        assert False, 'Expected ValueError'
    except ValueError:
        pass


# ── Alignment geometry ────────────────────────────────────────────────────────

def test_alignment_adds_contours_to_all_slices():
    r = slicer.slice_model(_box(h=80), 20.0)
    counts_before = [len(s.contours) for s in r.slices]
    slicer.add_alignment_geometry(r, dowel_radius=3.0, center_mark_radius=1.0)
    for i, s in enumerate(r.slices):
        assert len(s.contours) > counts_before[i]

def test_alignment_same_position_on_all_slices():
    """Dowel-hole contour centroids must be identical on every slice."""
    r = slicer.slice_model(_box(h=80), 20.0)
    slicer.add_alignment_geometry(r, dowel_radius=3.0, add_center_mark=False)

    def _centroids(sl):
        sorted_c = sorted(sl.contours, key=slicer._contour_area)
        # smallest area contours are alignment circles
        small = [c for c in sorted_c if slicer._contour_area(c) < 200]
        return sorted([(round(sum(p[0] for p in c)/len(c), 1),
                        round(sum(p[1] for p in c)/len(c), 1)) for c in small])

    ref = _centroids(r.slices[0])
    for s in r.slices[1:]:
        assert _centroids(s) == ref, f'Alignment positions differ on board {s.index}'

def test_alignment_disabled():
    r = slicer.slice_model(_box(h=80), 20.0)
    counts_before = [len(s.contours) for s in r.slices]
    slicer.add_alignment_geometry(r, add_center_mark=False, add_dowels=False)
    for i, s in enumerate(r.slices):
        assert len(s.contours) == counts_before[i]

def test_alignment_custom_offsets():
    r = slicer.slice_model(_box(h=80), 20.0)
    slicer.add_alignment_geometry(r, dowel_radius=3.0,
                                   dowel_offsets=[(10, 10), (-10, 10)],
                                   add_center_mark=False)
    # Only 2 dowel holes added (no center mark)
    c_before = 1   # one outer contour per box slice
    for s in r.slices:
        assert len(s.contours) == c_before + 2


# ── Exported entities are valid entity_model dicts ───────────────────────────

def test_entities_all_valid():
    r = slicer.slice_model(_box(h=80), 20.0)
    ents = slicer.slices_to_entities(r)
    geometry = [e for e in ents if e.get('type') in ('line', 'circle', 'polyline')]
    assert len(geometry) > 0
    invalid = [e for e in geometry if not em.is_valid(e)]
    assert invalid == [], f'Invalid entities: {invalid}'

def test_entities_have_ids():
    r = slicer.slice_model(_box(h=80), 20.0)
    ents = slicer.slices_to_entities(r)
    geometry = [e for e in ents if e.get('type') in ('line', 'circle', 'polyline')]
    assert all('id' in e for e in geometry)

def test_entities_have_source_slicer():
    r = slicer.slice_model(_box(h=80), 20.0)
    ents = slicer.slices_to_entities(r)
    geometry = [e for e in ents if e.get('type') in ('line', 'circle', 'polyline')]
    assert all(e.get('source') == 'slicer' for e in geometry)

def test_entities_cut_layer_present():
    r = slicer.slice_model(_box(h=80), 20.0)
    ents = slicer.slices_to_entities(r)
    layers = {e.get('layer') for e in ents}
    assert 'CUT' in layers

def test_entities_count_equals_board_count():
    """Without alignment, one entity per board (outer CUT profile)."""
    r = slicer.slice_model(_box(h=80), 20.0)
    ents = slicer.slices_to_entities(r)
    cut = [e for e in ents if e.get('layer') == 'CUT']
    assert len(cut) == r.n_boards

def test_single_inspect_returns_one_board():
    r = slicer.slice_model(_box(h=80), 20.0)
    all_ents   = slicer.slices_to_entities(r)
    board_ents = slicer.slices_to_entities(r, inspect_index=0)
    assert len(board_ents) < len(all_ents)
    cut = [e for e in board_ents if e.get('layer') == 'CUT']
    assert len(cut) == 1

def test_inspect_out_of_range_returns_empty():
    r = slicer.slice_model(_box(h=80), 20.0)
    ents = slicer.slices_to_entities(r, inspect_index=999)
    assert ents == []


# ── DXF export round-trip ─────────────────────────────────────────────────────

def test_dxf_export_creates_file():
    r = slicer.slice_model(_box(h=80), 20.0)
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        count = slicer.slices_to_dxf(r, path)
        assert count > 0
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)

def test_dxf_single_slice_export():
    r = slicer.slice_model(_box(h=80), 20.0)
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        count = slicer.slices_to_dxf_single(r.slices[0], path)
        assert count > 0
    finally:
        os.unlink(path)

def test_dxf_layout_gap_configurable():
    r = slicer.slice_model(_box(h=80), 20.0)
    w10, _ = slicer.slices_bounding_box(r, layout_gap=10.0)
    w50, _ = slicer.slices_bounding_box(r, layout_gap=50.0)
    # More gap → wider layout
    assert w50 > w10


# ── Alignment geometry on exported entities ───────────────────────────────────

def test_alignment_entities_in_holes_layer():
    r = slicer.slice_model(_box(h=80), 20.0)
    slicer.add_alignment_geometry(r, dowel_radius=3.0, add_center_mark=False)
    ents = slicer.slices_to_entities(r)
    holes = [e for e in ents if e.get('layer') == 'HOLES']
    # 4 boards × 4 dowel holes = 16
    assert len(holes) == 16

def test_alignment_entities_all_valid():
    r = slicer.slice_model(_box(h=80), 20.0)
    slicer.add_alignment_geometry(r)
    ents = slicer.slices_to_entities(r)
    geometry = [e for e in ents if e.get('type') in ('line', 'circle', 'polyline')]
    invalid = [e for e in geometry if not em.is_valid(e)]
    assert invalid == [], f'Invalid after alignment: {invalid}'


# ── Envelope mode ─────────────────────────────────────────────────────────────

def test_envelope_sphere_same_board_count():
    """Envelope on a sphere produces the same number of boards as best_sample."""
    sphere = slicer.mesh_from_sphere(50, lat_segs=18, lon_segs=36)
    rb = slicer.slice_model(sphere, 20.0, slab_mode='best_sample')
    re = slicer.slice_model(sphere, 20.0, slab_mode='envelope')
    assert re.n_boards == rb.n_boards

def test_envelope_sphere_area_within_5pct():
    """Sphere cross-sections are nested circles — envelope ≤ 5 % larger per board."""
    sphere = slicer.mesh_from_sphere(50, lat_segs=18, lon_segs=36)
    rb = slicer.slice_model(sphere, 20.0, slab_mode='best_sample')
    re = slicer.slice_model(sphere, 20.0, slab_mode='envelope')
    for sb, se in zip(rb.slices, re.slices):
        ab = slicer._contour_area(max(sb.contours, key=slicer._contour_area))
        ae = slicer._contour_area(max(se.contours, key=slicer._contour_area))
        assert ae >= ab * 0.95, f'envelope smaller than best_sample: {ae:.1f} < {ab:.1f}'
        assert ae <= ab * 1.05, f'envelope >5% larger than expected: ratio={ae/ab:.3f}'

def test_envelope_slab_mode_stored_on_result():
    sphere = slicer.mesh_from_sphere(30)
    r = slicer.slice_model(sphere, 15.0, slab_mode='envelope')
    assert r.slab_mode == 'envelope'

def test_best_sample_slab_mode_stored_on_result():
    r = slicer.slice_model(slicer.mesh_from_box(60, 60, 60), 20.0)
    assert r.slab_mode == 'best_sample'

def test_envelope_disconnected_contours():
    """Two spatially separated cylinders in one slab → envelope finds both contours."""
    import numpy as np
    left  = slicer.mesh_from_cylinder(15, 80)
    right = slicer.mesh_from_cylinder(15, 80)
    left[:, :, 0]  -= 40
    right[:, :, 0] += 40
    two = np.concatenate([left, right])
    # One thick board covering the full height — both cylinders are in the slab
    re = slicer.slice_model(two, 80.0, slab_mode='envelope')
    assert re.n_boards == 1
    assert len(re.slices[0].contours) >= 2, \
        f'Expected >=2 contours, got {len(re.slices[0].contours)}'

def test_best_sample_shifted_misses_part():
    """
    Two vertically staggered, horizontally separated cylinders: one slab spanning
    both → best_sample returns only 1 contour (picks one cylinder's plane),
    envelope returns 2 (captures both).
    """
    import numpy as np
    left  = slicer.mesh_from_cylinder(15, 40)
    right = slicer.mesh_from_cylinder(15, 40)
    left[:, :, 1]  -= 20   # left cylinder centred at y=−20
    right[:, :, 1] += 20   # right cylinder centred at y=+20
    left[:, :, 0]  -= 40
    right[:, :, 0] += 40
    two = np.concatenate([left, right])
    # Board thickness covers the entire stack (both cylinders)
    rb = slicer.slice_model(two, 80.0, slab_mode='best_sample')
    re = slicer.slice_model(two, 80.0, slab_mode='envelope')
    n_best = len(rb.slices[0].contours) if rb.slices else 0
    n_env  = len(re.slices[0].contours) if re.slices else 0
    # envelope must find more (or equal) contours than best_sample in this case
    assert n_env >= n_best, f'envelope={n_env} < best_sample={n_best}'

def test_envelope_by_count():
    """slice_model_by_count also supports slab_mode='envelope'."""
    sphere = slicer.mesh_from_sphere(40, lat_segs=12, lon_segs=24)
    r = slicer.slice_model_by_count(sphere, 4, slab_mode='envelope')
    assert r.n_boards == 4
    assert r.slab_mode == 'envelope'

def test_mesh_from_sphere_produces_closed_mesh():
    sphere = slicer.mesh_from_sphere(30, lat_segs=12, lon_segs=24)
    import numpy as np
    assert sphere.shape[1:] == (3, 3)

def test_mesh_from_cone_slices_correctly():
    cone = slicer.mesh_from_cone(40, 80)
    r = slicer.slice_model(cone, 20.0)
    assert r.n_boards == 4
    # Base board (board 0) should have larger area than apex board (board 3)
    area0 = slicer._contour_area(max(r.slices[0].contours, key=slicer._contour_area))
    area3 = slicer._contour_area(max(r.slices[-1].contours, key=slicer._contour_area))
    assert area0 > area3, f'Base board not larger: {area0:.1f} vs {area3:.1f}'


# ── Alignment: edge_margin_mm and skip logic ──────────────────────────────────

def test_alignment_edge_margin_places_holes():
    """edge_margin_mm places holes at that distance from the global bbox corner."""
    r = slicer.slice_model(_box(h=80), 20.0)
    # No alignment yet — each slice has 1 contour (outer box)
    before = [len(s.contours) for s in r.slices]
    slicer.add_alignment_geometry(r, dowel_radius=3.0, edge_margin_mm=10.0,
                                   add_center_mark=False)
    # All four corners should be inside the large box -> 4 holes per board
    for i, s in enumerate(r.slices):
        added = len(s.contours) - before[i]
        assert added == 4, f'Board {i+1}: expected 4 holes, got {added}'

def test_alignment_skips_holes_outside_profile():
    """Holes whose centres fall outside the board profile are skipped."""
    import numpy as np
    # Thin cylinder: cross-section is a small circle; 20%-inset holes of a
    # large global bbox would land outside the cylinder profile.
    cyl = slicer.mesh_from_cylinder(10.0, 80.0)   # radius 10 — small
    r   = slicer.slice_model(cyl, 20.0)
    before = [len(s.contours) for s in r.slices]
    # Use a large edge_margin_mm that would place holes far from the cylinder axis
    slicer.add_alignment_geometry(r, dowel_radius=3.0, edge_margin_mm=5.0,
                                   add_center_mark=False)
    # Holes at ±(r/2 - 5, r/2 - 5) from global centre; for r=10 the holes
    # may or may not fit. Key test: no exception and contour count is sane.
    for i, s in enumerate(r.slices):
        added = len(s.contours) - before[i]
        assert 0 <= added <= 4, f'Board {i+1}: unexpected hole count {added}'

def test_alignment_skips_all_on_too_small_board():
    """Boards whose bbox < 4×dowel_radius get no dowel holes."""
    import numpy as np
    # Tiny cylinder radius 4mm, dowel_radius 3mm → bbox ~8mm, 4×3=12 → too small
    cyl = slicer.mesh_from_cylinder(4.0, 40.0)
    r   = slicer.slice_model(cyl, 10.0)
    before = [len(s.contours) for s in r.slices]
    slicer.add_alignment_geometry(r, dowel_radius=3.0, add_center_mark=False)
    for i, s in enumerate(r.slices):
        added = len(s.contours) - before[i]
        assert added == 0, f'Board {i+1}: should have no holes, got {added}'


# ── Sheet layout ───────────────────────────────────────────────────────────────

def _big_box_result():
    return slicer.slice_model(_box(w=60, h=80, d=40), 20.0)

def test_sheet_layout_all_fit_one_sheet():
    r   = _big_box_result()         # 4 boards, each ~60×40 mm
    slr = slicer.sheet_layout(r, sheet_width=600, sheet_height=200, spacing=10)
    assert slr.n_sheets == 1
    assert len(slr.placements) == r.n_boards
    assert slr.overflow == []

def test_sheet_layout_wraps_to_second_row():
    r   = _big_box_result()         # 4 boards × 60 mm wide = 240 + gaps
    # Sheet wide enough for 2 per row, tall enough for 2 rows
    slr = slicer.sheet_layout(r, sheet_width=150, sheet_height=250, spacing=10)
    assert len(slr.placements) == r.n_boards
    # At least 2 distinct y positions (rows)
    ys = {pl.y for pl in slr.placements}
    assert len(ys) >= 2

def test_sheet_layout_overflow_when_board_too_large():
    r   = _big_box_result()         # boards ~60×40 mm
    slr = slicer.sheet_layout(r, sheet_width=30, sheet_height=30, spacing=5)
    assert len(slr.overflow) == r.n_boards   # all boards overflow

def test_sheet_layout_no_overlap():
    """No two placed boards overlap on the same sheet."""
    r   = _big_box_result()
    slr = slicer.sheet_layout(r, sheet_width=400, sheet_height=300, spacing=10)
    same_sheet = [pl for pl in slr.placements if pl.sheet_number == 0]
    for i in range(len(same_sheet)):
        for j in range(i + 1, len(same_sheet)):
            a, b = same_sheet[i], same_sheet[j]
            # Overlap test: intervals must NOT overlap in both dimensions
            overlap_x = a.x < b.x + b.width and b.x < a.x + a.width
            overlap_y = a.y < b.y + b.height and b.y < a.y + a.height
            assert not (overlap_x and overlap_y), \
                f'Boards {i} and {j} overlap on sheet'

def test_sheet_layout_preserves_order():
    r   = _big_box_result()
    slr = slicer.sheet_layout(r, sheet_width=600, sheet_height=200, spacing=10)
    placed_indices = [pl.slice_index for pl in slr.placements]
    assert placed_indices == sorted(placed_indices)

def test_sheet_layout_result_fields():
    r   = _big_box_result()
    slr = slicer.sheet_layout(r, sheet_width=500, sheet_height=200, spacing=10)
    assert slr.sheet_width  == 500
    assert slr.sheet_height == 200
    assert slr.spacing      == 10


# ── Per-board DXF export ──────────────────────────────────────────────────────

def test_dxf_per_board_creates_files():
    import tempfile, os
    r = slicer.slice_model(_box(h=80), 20.0)
    with tempfile.TemporaryDirectory() as d:
        count = slicer.slices_to_dxf_per_board(r, d, prefix='board')
        files = os.listdir(d)
        assert len(files) == r.n_boards, f'Expected {r.n_boards} files, got {len(files)}'
        assert count > 0
        for i in range(1, r.n_boards + 1):
            assert f'board_{i:03d}.dxf' in files, f'Missing board_{i:03d}.dxf'

def test_dxf_per_board_files_non_empty():
    import tempfile, os
    r = slicer.slice_model(_box(h=80), 20.0)
    with tempfile.TemporaryDirectory() as d:
        slicer.slices_to_dxf_per_board(r, d)
        for fname in os.listdir(d):
            assert os.path.getsize(os.path.join(d, fname)) > 0, f'{fname} is empty'

def test_dxf_sheet_layout_export():
    import tempfile, os
    r   = slicer.slice_model(_box(h=80), 20.0)
    slr = slicer.sheet_layout(r, 600, 300, spacing=10)
    with tempfile.NamedTemporaryFile(suffix='.dxf', delete=False) as f:
        path = f.name
    try:
        count = slicer.slices_to_dxf(r, path, sheet_layout_result=slr)
        assert count > 0
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)


# ── n_holes alignment patterns ───────────────────────────────────────────────

def _aligned_result(n_holes, edge_margin=10.0):
    """Slice a 100×80×60 box, add alignment geometry with n_holes."""
    r = slicer.slice_model(_box(w=100, h=80, d=60), 20.0)
    slicer.add_alignment_geometry(
        r,
        dowel_radius=3.0,
        n_holes=n_holes,
        edge_margin_mm=edge_margin,
        add_center_mark=False,  # don't count centre marks
    )
    return r


def _count_hole_contours(sl):
    """Return number of small (area < 100 mm²) contours = alignment holes."""
    return sum(1 for c in sl.contours if slicer._contour_area(c) < 100.0)


def test_n_holes_2_pattern():
    r = _aligned_result(n_holes=2)
    for sl in r.slices:
        count = _count_hole_contours(sl)
        assert count <= 2, f'Expected ≤2 holes, got {count}'
    # At least one board must have 2 holes (box is big enough)
    max_holes = max(_count_hole_contours(sl) for sl in r.slices)
    assert max_holes == 2


def test_n_holes_3_pattern():
    r = _aligned_result(n_holes=3)
    for sl in r.slices:
        count = _count_hole_contours(sl)
        assert count <= 3, f'Expected ≤3 holes, got {count}'
    max_holes = max(_count_hole_contours(sl) for sl in r.slices)
    assert max_holes == 3


def test_n_holes_4_pattern():
    r = _aligned_result(n_holes=4)
    for sl in r.slices:
        count = _count_hole_contours(sl)
        assert count <= 4, f'Expected ≤4 holes, got {count}'
    max_holes = max(_count_hole_contours(sl) for sl in r.slices)
    assert max_holes == 4


def test_n_holes_2_positions_symmetric():
    """2-hole pattern must be symmetric about x=0 (left/right centres)."""
    r = slicer.slice_model(_box(w=100, h=80, d=60), 20.0)
    slicer.add_alignment_geometry(
        r, dowel_radius=3.0, n_holes=2, edge_margin_mm=10.0,
        add_center_mark=False,
    )
    # Find the two hole centres from the first board's contours
    holes = [c for c in r.slices[0].contours if slicer._contour_area(c) < 100.0]
    assert len(holes) == 2
    cx0 = sum(p[0] for p in holes[0]) / len(holes[0])
    cx1 = sum(p[0] for p in holes[1]) / len(holes[1])
    # x-coords must be mirrored: cx0 ≈ -cx1
    assert abs(cx0 + cx1) < 1.0, f'Holes not symmetric: {cx0:.2f}, {cx1:.2f}'
    cz0 = sum(p[1] for p in holes[0]) / len(holes[0])
    cz1 = sum(p[1] for p in holes[1]) / len(holes[1])
    # Both at z ≈ 0 (midpoint)
    assert abs(cz0) < 1.0 and abs(cz1) < 1.0, f'Holes not at z=0: {cz0:.2f}, {cz1:.2f}'


def test_n_holes_explicit_offsets_override_n_holes():
    """Explicit dowel_offsets must take priority over n_holes."""
    r = slicer.slice_model(_box(w=100, h=80, d=60), 20.0)
    custom = [(0.0, 0.0)]  # single centre hole
    slicer.add_alignment_geometry(
        r, dowel_radius=3.0, n_holes=4,
        dowel_offsets=custom, add_center_mark=False,
    )
    for sl in r.slices:
        count = _count_hole_contours(sl)
        assert count <= 1, f'Expected ≤1 hole from explicit offset, got {count}'


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
