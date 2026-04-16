"""
slicer.py — Stacked contour slicer: 3D mesh → ordered 2D CNC boards.

Slices a mesh along the chosen stacking axis into flat boards that,
when assembled, approximate the original 3D shape (ribbed/layered
wooden construction style).

Axis semantics
--------------
  Slice along X → boards are in the Y-Z plane  (Y horiz, Z vert on board)
  Slice along Y → boards are in the X-Z plane  (X horiz, Z vert on board)  [default]
  Slice along Z → boards are in the X-Y plane  (X horiz, Y vert on board)

Implementation: remap_axis() permutes (x,y,z) columns so the chosen axis
becomes the new internal Y before slicing.  After permuting:
  horizontal board coord ← new col-0 (original values depend on axis)
  vertical   board coord ← new col-2

Workflow
--------
  1.  load_mesh(path)                    → (N,3,3) numpy float array
      mesh_from_box / mesh_from_cylinder → parametric test meshes
  2a. slice_model(tris, board_thickness) → SliceResult
  2b. slice_model_by_count(tris, n)      → SliceResult  (thickness computed)
  3.  add_alignment_geometry(result, …)  → mutates slices in-place
  4a. slices_to_entities(result)         → List[entity_model dicts]  (→ Editor)
  4b. slices_to_dxf(result, path)        → DXF file
      slices_to_dxf_single(sl, path)     → single-board DXF

Axis remapping
--------------
  remap_axis(triangles, axis) permutes (x,y,z) so the chosen axis becomes
  the new Y (stacking axis).  Valid values: 'x', 'y' (default), 'z'.

Alignment geometry (Priority 4)
---------------------------------
  add_alignment_geometry() stamps the same circles on every board so
  dowel holes line up after assembly:
    • center_mark  — small cross-hair circle at bounding-box centre (TEMPLATE)
    • dowel_holes  — one or more circles at fixed offsets from centre (HOLES)
  The alignment positions are chosen once from the tightest bounding box of
  the full model and applied identically to every slice.

Cleanup rules
-------------
  • Segments < _SEG_TOL mm → dropped (noise)
  • Stitching gap > _STITCH_TOL mm → new sub-contour
  • Contours < 3 pts → discarded
  • Douglas-Peucker: ε = board_thickness × 0.05

Dependencies
------------
  numpy       — required for mesh operations
  numpy-stl   — optional; built-in ASCII/binary STL parser used if absent
  ezdxf       — DXF export (already a project dependency)
"""

import math
import struct
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import entity_model as em

# ── Type aliases ──────────────────────────────────────────────────────────────

Vertex  = Tuple[float, float, float]
Segment = Tuple[Tuple[float, float], Tuple[float, float]]
Contour = List[Tuple[float, float]]   # closed polygon in (x, z) board space

# ── Constants ─────────────────────────────────────────────────────────────────

_SEG_TOL     = 1e-6   # mm — discard degenerate segments
_STITCH_TOL  = 0.5    # mm — max endpoint gap during chain stitching
_DEFAULT_GAP = 20.0   # mm — default gap between boards in DXF layout

# Valid stacking axes
AXIS_X = 'x'
AXIS_Y = 'y'
AXIS_Z = 'z'

# Board plane labels: for each stacking axis, the two axes visible on a board
_BOARD_PLANE: Dict[str, Tuple[str, str, str]] = {
    'y': ('X-Z',  'X', 'Z'),   # horiz=X, vert=Z
    'x': ('Y-Z',  'Y', 'Z'),   # horiz=Y, vert=Z
    'z': ('X-Y',  'X', 'Y'),   # horiz=X, vert=Y
}


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class BoardSlice:
    """One horizontal cross-section of the 3D object."""
    index:      int
    y_min:      float             # lower stacking-axis bound of this board (mm)
    y_max:      float             # upper stacking-axis bound of this board (mm)
    thickness:  float             # y_max − y_min (mm)
    contours:   List[Contour]     # outer + inner contours in (x, z) space
    label:      str = ''

    def __post_init__(self):
        if not self.label:
            # Placeholder label — _build_slices overwrites this with the real
            # axis name after all slices are complete.
            self.label = f'Board {self.index + 1}  {self.y_min:.1f}–{self.y_max:.1f} mm'


@dataclass
class SliceResult:
    """Full output of a slicing run."""
    slices:          List[BoardSlice]
    mesh_bounds:     Tuple[float, float, float, float, float, float]
    board_thickness: float
    n_boards:        int
    stacking_axis:   str = 'y'
    source_path:     str = ''
    slab_mode:       str = 'best_sample'   # 'envelope' is the GUI default

    @property
    def model_span(self) -> float:
        """Total length along the stacking axis (mm)."""
        return self.mesh_bounds[3] - self.mesh_bounds[2]   # y_max − y_min


# ── Mesh loading ──────────────────────────────────────────────────────────────

def load_mesh(path: str):
    """
    Load an STL file.  Returns a (N, 3, 3) numpy float array.

    Tries numpy-stl first; falls back to the built-in parser.
    """
    try:
        from stl import mesh as stl_mesh
        import numpy as np
        m = stl_mesh.Mesh.from_file(path)
        return np.stack([m.v0, m.v1, m.v2], axis=1)
    except ImportError:
        pass
    return _load_stl_builtin(path)


def remap_axis(triangles, axis: str):
    """
    Permute triangle vertex columns so that `axis` becomes the new Y
    (the internal stacking axis used by the slicer).

    'y' (default) → no change          → boards in X-Z plane
    'x'           → (x,y,z)→(y,x,z)   → boards in Y-Z plane
    'z'           → (x,y,z)→(x,z,y)   → boards in X-Y plane

    After remapping, col-0 = board horizontal, col-2 = board vertical.
    """
    import numpy as np
    axis = axis.lower()
    if axis == 'y':
        return triangles
    if axis == 'x':
        # Stack along original X: swap cols 0 and 1
        # Board cross-section shows original Y (horiz) × original Z (vert)
        t = triangles.copy()
        t[:, :, 0], t[:, :, 1] = triangles[:, :, 1].copy(), triangles[:, :, 0].copy()
        return t
    if axis == 'z':
        # Stack along original Z: swap cols 1 and 2
        # Board cross-section shows original X (horiz) × original Y (vert)
        t = triangles.copy()
        t[:, :, 1], t[:, :, 2] = triangles[:, :, 2].copy(), triangles[:, :, 1].copy()
        return t
    raise ValueError(f"axis must be 'x', 'y', or 'z', got {axis!r}")


def board_plane_info(stacking_axis: str) -> Tuple[str, str, str]:
    """
    Return ``(plane_name, horiz_axis, vert_axis)`` for a given stacking axis.

    Examples
    --------
    >>> board_plane_info('y')   # ('X-Z', 'X', 'Z')
    >>> board_plane_info('x')   # ('Y-Z', 'Y', 'Z')
    >>> board_plane_info('z')   # ('X-Y', 'X', 'Y')
    """
    return _BOARD_PLANE.get(stacking_axis.lower(), ('X-Z', 'X', 'Z'))


def mesh_from_box(width: float, height: float, depth: float):
    """(12, 3, 3) box mesh — useful for testing."""
    import numpy as np
    w, h, d = width / 2, height / 2, depth / 2
    corners = [
        (-w, -h, -d), ( w, -h, -d), ( w,  h, -d), (-w,  h, -d),
        (-w, -h,  d), ( w, -h,  d), ( w,  h,  d), (-w,  h,  d),
    ]
    faces = [
        (0,1,2),(0,2,3), (4,6,5),(4,7,6),
        (0,5,1),(0,4,5), (2,6,3),(6,7,3),
        (0,3,7),(0,7,4), (1,5,6),(1,6,2),
    ]
    return np.array([[corners[a], corners[b], corners[c]] for a,b,c in faces],
                    dtype=float)


def mesh_from_sphere(radius: float, lat_segs: int = 18, lon_segs: int = 36):
    """Closed sphere mesh centred at origin — useful for envelope testing."""
    import numpy as np, math
    tris = []
    for i in range(lat_segs):
        phi0 = math.pi * i       / lat_segs - math.pi / 2
        phi1 = math.pi * (i + 1) / lat_segs - math.pi / 2
        for j in range(lon_segs):
            th0 = 2 * math.pi * j       / lon_segs
            th1 = 2 * math.pi * (j + 1) / lon_segs
            def v(phi, th):
                return (radius*math.cos(phi)*math.cos(th),
                        radius*math.sin(phi),
                        radius*math.cos(phi)*math.sin(th))
            a, b, c, d = v(phi0,th0), v(phi0,th1), v(phi1,th1), v(phi1,th0)
            tris += [[a, b, c], [a, c, d]]
    return np.array(tris, dtype=float)


def mesh_from_cone(base_radius: float, height: float, segments: int = 36):
    """Closed cone mesh — apex at top, base centred at origin."""
    import numpy as np, math
    apex   = (0.0, height, 0.0)
    origin = (0.0, 0.0,   0.0)
    angles = [2 * math.pi * i / segments for i in range(segments)]
    tris = []
    for i in range(segments):
        a0, a1 = angles[i], angles[(i+1) % segments]
        b0 = (base_radius * math.cos(a0), 0.0, base_radius * math.sin(a0))
        b1 = (base_radius * math.cos(a1), 0.0, base_radius * math.sin(a1))
        tris += [[b0, b1, apex], [origin, b1, b0]]   # side + base
    return np.array(tris, dtype=float)


def mesh_from_cylinder(radius: float, height: float, segments: int = 36):
    """Closed cylinder mesh — useful for testing round cross-sections."""
    import numpy as np
    angles = [2 * math.pi * i / segments for i in range(segments)]
    top_y, bot_y = height / 2, -height / 2
    tris = []
    for i in range(segments):
        a0, a1 = angles[i], angles[(i + 1) % segments]
        x0, z0 = radius * math.cos(a0), radius * math.sin(a0)
        x1, z1 = radius * math.cos(a1), radius * math.sin(a1)
        tris += [
            [(x0, bot_y, z0), (x1, bot_y, z1), (x1, top_y, z1)],
            [(x0, bot_y, z0), (x1, top_y, z1), (x0, top_y, z0)],
            [(0,  top_y, 0),  (x0, top_y, z0), (x1, top_y, z1)],
            [(0,  bot_y, 0),  (x1, bot_y, z1), (x0, bot_y, z0)],
        ]
    return np.array(tris, dtype=float)


# ── Slicing entry points ──────────────────────────────────────────────────────

def slice_model(
    triangles,
    board_thickness: float,
    *,
    stacking_axis:     str   = 'y',
    y_min:             Optional[float] = None,
    y_max:             Optional[float] = None,
    simplify:          bool  = True,
    slab_samples:      int   = 5,
    slab_mode:         str   = 'best_sample',
    quality:           str   = 'accurate',
    progress_callback          = None,
    source_path:       str   = '',
) -> SliceResult:
    """
    Slice a triangle mesh into boards of `board_thickness` mm.

    Each board is a consecutive slab between two parallel planes.

    slab_mode='best_sample' (default)
        Pick the cross-section plane with the largest area within each slab.
        Fast; correct for nested cross-sections (sphere, cone, box).

    slab_mode='envelope'
        Union of all sampled cross-sections via rasterization.  Correct for
        shapes whose cross-section shifts or rotates across a slab.

    The number of boards is ceil(model_span / board_thickness).
    """
    import numpy as np

    tris = remap_axis(triangles, stacking_axis)
    verts = tris.reshape(-1, 3)
    bounds = (
        float(verts[:, 0].min()), float(verts[:, 0].max()),
        float(verts[:, 1].min()), float(verts[:, 1].max()),
        float(verts[:, 2].min()), float(verts[:, 2].max()),
    )
    lo_bound = bounds[2] if y_min is None else y_min
    hi_bound = bounds[3] if y_max is None else y_max

    span = hi_bound - lo_bound
    if span <= 0:
        raise ValueError('Mesh has zero height along the stacking axis.')
    if board_thickness <= 0:
        raise ValueError('board_thickness must be > 0.')

    n_boards = max(1, math.ceil(span / board_thickness))
    slices = _build_slices(tris, bounds, lo_bound, hi_bound,
                           board_thickness, n_boards, simplify,
                           stacking_axis=stacking_axis,
                           slab_samples=max(1, slab_samples),
                           slab_mode=slab_mode,
                           quality=quality,
                           progress_callback=progress_callback)
    return SliceResult(
        slices=slices,
        mesh_bounds=bounds,
        board_thickness=board_thickness,
        n_boards=len(slices),
        stacking_axis=stacking_axis,
        source_path=source_path,
        slab_mode=slab_mode,
    )


def slice_model_by_count(
    triangles,
    n_boards: int,
    *,
    stacking_axis:     str   = 'y',
    y_min:             Optional[float] = None,
    y_max:             Optional[float] = None,
    simplify:          bool  = True,
    slab_samples:      int   = 5,
    slab_mode:         str   = 'best_sample',
    quality:           str   = 'accurate',
    progress_callback          = None,
    source_path:       str   = '',
) -> SliceResult:
    """
    Slice into exactly `n_boards` equal-thickness boards.

    board_thickness = model_span / n_boards.
    See slice_model() for slab_mode documentation.
    """
    if n_boards < 1:
        raise ValueError('n_boards must be >= 1.')
    import numpy as np
    tris = remap_axis(triangles, stacking_axis)
    verts = tris.reshape(-1, 3)
    bounds = (
        float(verts[:, 0].min()), float(verts[:, 0].max()),
        float(verts[:, 1].min()), float(verts[:, 1].max()),
        float(verts[:, 2].min()), float(verts[:, 2].max()),
    )
    lo_bound = bounds[2] if y_min is None else y_min
    hi_bound = bounds[3] if y_max is None else y_max

    span = hi_bound - lo_bound
    if span <= 0:
        raise ValueError('Mesh has zero height along the stacking axis.')

    board_thickness = span / n_boards
    slices = _build_slices(tris, bounds, lo_bound, hi_bound,
                           board_thickness, n_boards, simplify,
                           stacking_axis=stacking_axis,
                           slab_samples=max(1, slab_samples),
                           slab_mode=slab_mode,
                           quality=quality,
                           progress_callback=progress_callback)
    return SliceResult(
        slices=slices,
        mesh_bounds=bounds,
        board_thickness=board_thickness,
        n_boards=len(slices),
        stacking_axis=stacking_axis,
        source_path=source_path,
        slab_mode=slab_mode,
    )


# Module-level Figure singleton — created once, reused across all slab calls
# to avoid the 25 ms overhead of Figure() construction per board.
_ENV_FIG = None
_ENV_AX  = None


def _get_env_axes():
    """Return (fig, ax), creating the singleton on first call."""
    global _ENV_FIG, _ENV_AX
    if _ENV_FIG is None:
        from matplotlib.figure import Figure as _F
        _ENV_FIG = _F()
        _ENV_AX  = _ENV_FIG.add_subplot(111)
    _ENV_AX.cla()   # clear between uses
    return _ENV_FIG, _ENV_AX


def _slab_envelope_contours(
    tris,
    lo: float,
    hi: float,
    n_samples: int,
    simplify_tol: float,
    grid_res: int = 120,
) -> Optional[List]:
    """
    Compute the board 2D cut profile as the **union envelope** of all
    cross-sections within the slab [lo, hi].

    Algorithm
    ---------
    1. Sample ``n_samples`` planes uniformly inside the slab.
    2. Rasterize each outer cross-section contour onto a shared grid.
    3. OR all rasterised masks → union of all cross-section footprints.
    4. Extract the boundary of the union using matplotlib's contour finder.

    Why this is better than picking a single best sample
    -----------------------------------------------------
    If cross-sections are geometrically nested (sphere, cone) the result is
    identical to best-sample.  If cross-sections shift position, rotate, or
    split/merge across the slab (twisted shapes, crescents, disconnected
    sub-parts), this method captures the full spatial extent while
    best-sample would miss everything outside the chosen plane.

    Limitations
    -----------
    * Inner voids that only exist in some samples are unioned away.
      Model-inherent holes that persist through the whole slab are preserved
      because no sample fills those grid cells.
    * Resolution is limited by ``grid_res`` (default 200 × 200).
    """
    import numpy as np

    n_s     = max(n_samples, 2)   # allow as few as 2 for fast mode
    sub     = (hi - lo) / n_s
    y_vals  = [lo + sub * (k + 0.5) for k in range(n_s)]

    all_pts: List[Tuple[float, float]] = []
    sample_outers: List[List[Tuple[float, float]]] = []

    for y_s in y_vals:
        segs = _intersect_triangles(tris, y_s)
        if not segs:
            continue
        contours = _stitch_segments(segs)
        contours = [c for c in contours if len(c) >= 3]
        if not contours:
            continue
        # Largest-area contour = outer shell for this sample
        outer = max(contours, key=_contour_area)
        sample_outers.append(outer)
        all_pts.extend(outer)

    if not sample_outers:
        return None

    pts_arr = np.array(all_pts)
    margin  = max((pts_arr[:, 0].max() - pts_arr[:, 0].min()) * 0.05,
                  (pts_arr[:, 1].max() - pts_arr[:, 1].min()) * 0.05, 1.0)
    xmin = float(pts_arr[:, 0].min()) - margin
    xmax = float(pts_arr[:, 0].max()) + margin
    zmin = float(pts_arr[:, 1].min()) - margin
    zmax = float(pts_arr[:, 1].max()) + margin

    xs = np.linspace(xmin, xmax, grid_res)
    zs = np.linspace(zmin, zmax, grid_res)
    XX, ZZ = np.meshgrid(xs, zs)
    grid_pts = np.column_stack([XX.ravel(), ZZ.ravel()])

    from matplotlib.path import Path as _MplPath
    filled = np.zeros(grid_res * grid_res, dtype=bool)
    for outer in sample_outers:
        path = _MplPath(outer + [outer[0]])
        filled |= path.contains_points(grid_pts)

    filled_grid = filled.reshape(grid_res, grid_res).astype(float)

    # Extract the boundary using the reused module-level Figure/Axes.
    _fig, _ax = _get_env_axes()
    cs = _ax.contour(XX, ZZ, filled_grid, levels=[0.5])

    result: List[Contour] = []
    try:
        for seg_arr in cs.allsegs[0]:          # allsegs[level_idx][path_idx]
            pts_list = [(float(p[0]), float(p[1])) for p in seg_arr]
            if len(pts_list) >= 3:
                result.append(pts_list)
    except (AttributeError, IndexError):
        # Older matplotlib: use .collections
        for coll in cs.collections:
            for mpl_path in coll.get_paths():
                pts_list = [(float(p[0]), float(p[1]))
                            for p in mpl_path.vertices]
                if len(pts_list) >= 3:
                    result.append(pts_list)

    if not result:
        return None

    if simplify_tol > 0:
        result = [_simplify(c, simplify_tol) for c in result]
    result = [c for c in result if len(c) >= 3]
    return result or None


def _build_slices(
    tris, bounds, lo_bound, hi_bound,
    board_thickness, n_boards, simplify,
    stacking_axis:    str  = 'y',
    slab_samples:     int  = 5,
    slab_mode:        str  = 'best_sample',
    quality:          str  = 'accurate',
    progress_callback       = None,
) -> List[BoardSlice]:
    """
    Build the board list by slab-interval slicing.

    slab_mode='best_sample'  (default)
        For each slab, sample ``slab_samples`` cross-section planes and keep
        the one with the largest total contour area.  Fast and correct for
        shapes whose cross-sections are geometrically nested (sphere, cone,
        box, cylinder).

    slab_mode='envelope'
        Rasterise all sample cross-sections and extract the outer union
        boundary.  Correct for shapes where cross-sections shift position,
        rotate, or split/merge within one slab thickness.  Slower (~0.5–2 s
        per board depending on grid_res and n_samples).
    """
    # Quality presets: (slab_samples for envelope, raster grid_res)
    _Q = {'fast': (3, 60), 'accurate': (7, 120)}
    q_samples, grid_res = _Q.get(quality, (7, 120))

    slices: List[BoardSlice] = []
    simplify_tol = max(board_thickness * 0.05, _SEG_TOL)
    use_envelope = slab_mode == 'envelope'

    # For envelope, quality overrides the caller's slab_samples.
    # For best_sample, quality reduces the sample count (fast=3, accurate=5 min).
    if use_envelope:
        eff_samples = q_samples
    else:
        eff_samples = max(slab_samples, 3 if quality == 'fast' else slab_samples)

    for i in range(n_boards):
        lo = lo_bound + i * board_thickness
        hi = min(lo_bound + (i + 1) * board_thickness, hi_bound)

        if use_envelope:
            contours = _slab_envelope_contours(
                tris, lo, hi,
                n_samples=eff_samples,
                simplify_tol=simplify_tol if simplify else 0.0,
                grid_res=grid_res,
            )
            if contours is None:
                if progress_callback is not None:
                    progress_callback(i + 1, n_boards)
                continue
        else:
            # Sample planes; keep the one with the largest area.
            n_s     = eff_samples
            sub     = (hi - lo) / n_s
            y_vals  = [lo + sub * (k + 0.5) for k in range(n_s)]

            best_contours: Optional[List] = None
            best_area = -1.0

            for y_s in y_vals:
                segs = _intersect_triangles(tris, y_s)
                if not segs:
                    continue
                cands = _stitch_segments(segs)
                if simplify:
                    cands = [_simplify(c, simplify_tol) for c in cands]
                cands = [c for c in cands if len(c) >= 3]
                if not cands:
                    continue
                area = sum(_contour_area(c) for c in cands)
                if area > best_area:
                    best_area, best_contours = area, cands

            if best_contours is None:
                continue
            contours = best_contours

        slices.append(BoardSlice(
            index=i, y_min=lo, y_max=hi, thickness=(hi - lo),
            contours=contours,
        ))

        if progress_callback is not None:
            progress_callback(i + 1, n_boards)

    # Re-number; label uses the real stacking-axis name.
    ax_up = stacking_axis.upper()
    for new_idx, s in enumerate(slices):
        s.index = new_idx
        s.label = f'Board {new_idx + 1}  [{ax_up}: {s.y_min:.1f}–{s.y_max:.1f} mm]'

    return slices


# ── Alignment geometry ────────────────────────────────────────────────────────

def _point_in_contour(px: float, pz: float, contour: Contour) -> bool:
    """Ray-casting point-in-polygon test (2-D, contour in (x,z) space)."""
    n = len(contour)
    inside = False
    xi, zi = contour[0]
    for j in range(1, n + 1):
        xj, zj = contour[j % n]
        if ((zi > pz) != (zj > pz)) and (px < (xj - xi) * (pz - zi) / (zj - zi + 1e-18) + xi):
            inside = not inside
        xi, zi = xj, zj
    return inside


def add_alignment_geometry(
    result: SliceResult,
    *,
    dowel_radius:       float = 3.0,
    n_holes:            int   = 4,
    dowel_offsets:      Optional[List[Tuple[float, float]]] = None,
    edge_margin_mm:     Optional[float] = None,
    center_mark_radius: float = 1.0,
    add_center_mark:    bool  = True,
    add_dowels:         bool  = True,
) -> None:
    """
    Add alignment circles to every BoardSlice in-place.

    Hole positions are derived from the **global** bounding box across ALL
    slices so they are at identical absolute coordinates on every board —
    essential for correct dowel alignment during assembly.

    Parameters
    ----------
    result              : SliceResult
    dowel_radius        : radius of dowel-hole circles (mm)
    n_holes             : 2, 3, or 4 — number of alignment holes.
                          Ignored when ``dowel_offsets`` is given explicitly.
                          Patterns (relative to global bbox centre):
                          2 → left-centre and right-centre
                          3 → top-centre, bottom-left, bottom-right (triangle)
                          4 → four corners (default)
    dowel_offsets       : explicit list of (dx, dz) offsets; when given,
                          ``n_holes`` and ``edge_margin_mm`` are ignored.
    edge_margin_mm      : distance (mm) from the global bbox edge to each
                          hole centre.  Leave None for 20 % inset default.
    center_mark_radius  : radius of the centre-alignment circle (mm)
    add_center_mark     : add a small centre-mark circle on every slice
    add_dowels          : add dowel-hole circles at fixed positions

    Skip logic
    ----------
    A dowel hole is skipped for a specific board when:
      • Its centre falls outside the board's outer contour (it would be cut
        into empty space / air), OR
      • The board's bounding box is smaller than 4 × dowel_radius in either
        dimension (board too small to safely accommodate the hole).
    """
    if not result.slices:
        return

    # Global bbox across all outer contours
    all_xs: List[float] = []
    all_zs: List[float] = []
    for sl in result.slices:
        outer = max(sl.contours, key=_contour_area)
        all_xs.extend(p[0] for p in outer)
        all_zs.extend(p[1] for p in outer)

    if not all_xs:
        return

    x0, x1 = min(all_xs), max(all_xs)
    z0, z1 = min(all_zs), max(all_zs)
    cx = (x0 + x1) / 2
    cz = (z0 + z1) / 2
    w  = x1 - x0
    h  = z1 - z0

    if dowel_offsets is None:
        # Inset distances: margin-based or 20 % default
        if edge_margin_mm is not None:
            mx, mz = edge_margin_mm, edge_margin_mm
        else:
            mx, mz = w * 0.20, h * 0.20

        hx = w / 2 - mx   # half-span to hole along X
        hz = h / 2 - mz   # half-span to hole along Z

        if n_holes == 2:
            # Left-centre and right-centre
            dowel_offsets = [
                (-hx, 0.0),
                ( hx, 0.0),
            ]
        elif n_holes == 3:
            # Triangle: top-centre, bottom-left, bottom-right
            dowel_offsets = [
                ( 0.0,  hz),
                (-hx,  -hz),
                ( hx,  -hz),
            ]
        else:
            # Four corners (default, n_holes == 4 or any other value)
            dowel_offsets = [
                ( hx,  hz),
                (-hx,  hz),
                ( hx, -hz),
                (-hx, -hz),
            ]

    for sl in result.slices:
        if add_center_mark:
            sl.contours.append(_circle_contour(cx, cz, center_mark_radius, 16))

        if add_dowels:
            outer = max(sl.contours, key=_contour_area)
            # Board bbox for size check
            bxs = [p[0] for p in outer]; bzs = [p[1] for p in outer]
            bw = max(bxs) - min(bxs); bh = max(bzs) - min(bzs)
            too_small = (bw < 4 * dowel_radius) or (bh < 4 * dowel_radius)

            for dx, dz in dowel_offsets:
                hx, hz = cx + dx, cz + dz
                if too_small:
                    continue   # board too small — skip all holes for this board
                if not _point_in_contour(hx, hz, outer):
                    continue   # hole would land outside this board's profile
                sl.contours.append(_circle_contour(hx, hz, dowel_radius, 24))


def _circle_contour(cx: float, cz: float, r: float, n: int) -> Contour:
    """Approximate a circle as a polygon for inclusion as a contour."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    return pts


# ── Entity generation ─────────────────────────────────────────────────────────

def slices_to_entities(
    result: SliceResult,
    *,
    layout_gap:          float = _DEFAULT_GAP,
    inspect_index:       Optional[int] = None,    # None = all, int = single board
    include_dowel_layer: bool  = True,
) -> List[Dict]:
    """
    Convert slices to entity_model dicts arranged left-to-right.

    Outer contour  → CUT layer
    Smaller inner contours → TEMPLATE layer (pockets)
    Tiny circles (area < 100 mm²) → HOLES layer (dowel / alignment holes)

    Parameters
    ----------
    layout_gap      : gap between boards in mm
    inspect_index   : if set, only return entities for that single board index
    """
    target = result.slices
    if inspect_index is not None:
        if 0 <= inspect_index < len(target):
            target = [target[inspect_index]]
        else:
            return []

    entities: List[Dict] = []
    x_cursor = 0.0

    for sl in target:
        if not sl.contours:
            continue

        # Identify outer (largest area) contour
        sorted_c = sorted(sl.contours, key=_contour_area, reverse=True)
        outer  = sorted_c[0]
        inners = sorted_c[1:]

        xs = [p[0] for p in outer]
        zs = [p[1] for p in outer]
        w  = max(xs) - min(xs)
        x_off = x_cursor - min(xs)

        def _shift(c: Contour) -> List[Tuple[float, float]]:
            return [(p[0] + x_off, p[1]) for p in c]

        # Outer CUT profile (closed)
        shifted_outer = _shift(outer)
        entities.append(em.make_polyline(
            shifted_outer + [shifted_outer[0]],
            layer=em.LAYER_CUT, closed=True,
            label=sl.label, source='slicer',
        ))

        # Inner contours: tiny circles → HOLES, others → TEMPLATE
        for inner in inners:
            area = _contour_area(inner)
            layer = em.LAYER_HOLES if area < 100.0 else em.LAYER_TEMPLATE
            shifted_i = _shift(inner)
            entities.append(em.make_polyline(
                shifted_i + [shifted_i[0]],
                layer=layer, closed=True,
                label=f'{sl.label} feature', source='slicer',
            ))

        x_cursor += w + layout_gap

    return entities


# ── DXF export ────────────────────────────────────────────────────────────────

def _write_board_to_msp(
    sl: 'BoardSlice',
    msp,
    x_off: float,
    y_off: float,
    lm: 'LayerManager',
    label_height: Optional[float] = None,
) -> int:
    """
    Write one board's contours + label to an ezdxf modelspace.

    All geometry is shifted by (x_off, y_off) so the board's bbox corner
    lands at the requested sheet position.

    Returns the number of entities written.
    """
    if not sl.contours:
        return 0

    sorted_c = sorted(sl.contours, key=_contour_area, reverse=True)
    outer  = sorted_c[0]
    inners = sorted_c[1:]

    # Shift so board's own bbox min corner is at (x_off, y_off)
    bx_min = min(p[0] for p in outer)
    bz_min = min(p[1] for p in outer)
    bx_max = max(p[0] for p in outer)
    bz_max = max(p[1] for p in outer)
    dx = x_off - bx_min
    dz = y_off - bz_min

    def _pts(c: 'Contour'):
        return [(p[0] + dx, p[1] + dz) for p in c]

    total = 0

    # Outer CUT profile
    poly = msp.add_lwpolyline(_pts(outer), dxfattribs={'layer': lm.CUT_LAYER})
    poly.close(True); total += 1

    # Inner contours
    for inner in inners:
        area  = _contour_area(inner)
        if area < 100.0:
            layer = lm.HOLES_LAYER
        else:
            layer = lm.TEMPLATE_LAYER
        pi = msp.add_lwpolyline(_pts(inner), dxfattribs={'layer': layer})
        pi.close(True); total += 1

    # Board label (centred inside the profile)
    board_w = bx_max - bx_min
    board_h = bz_max - bz_min
    h = label_height if label_height else max(min(board_w, board_h) * 0.06, 2.0)
    lx = x_off + board_w / 2
    lz = y_off + board_h / 2
    try:
        t = msp.add_text(sl.label, dxfattribs={'height': h, 'layer': lm.LABELS_LAYER})
        t.dxf.insert  = (lx, lz)
        t.dxf.halign  = 4   # MIDDLE_CENTER (ezdxf ≥ 0.16)
        t.dxf.valign  = 0
    except Exception:
        t = msp.add_text(sl.label, dxfattribs={'height': h, 'layer': lm.LABELS_LAYER})
        t.dxf.insert  = (lx, lz)
    total += 1

    # Thickness annotation below label
    thick_note = f't={sl.thickness:.1f} mm'
    try:
        tn = msp.add_text(thick_note, dxfattribs={'height': h * 0.7, 'layer': lm.LABELS_LAYER})
        tn.dxf.insert = (lx, lz - h * 1.4)
    except Exception:
        pass

    return total


def slices_to_dxf(
    result: 'SliceResult',
    output_path: str,
    *,
    layout_gap:   float = _DEFAULT_GAP,
    sheet_layout_result: Optional['SheetLayoutResult'] = None,
) -> int:
    """
    Write all slice contours to a single DXF file.  Returns entity count.

    Layout modes
    ------------
    If ``sheet_layout_result`` is provided, boards are placed according to
    the sheet packing result (row-by-row on one or more sheets, with sheet
    boundaries drawn as rectangles on the DIMENSIONS layer).

    Otherwise boards are placed left-to-right with ``layout_gap`` spacing
    (the original linear strip layout).

    Layers: CUT / HOLES / TEMPLATE / LABELS
    """
    import ezdxf
    from layers import LayerManager

    doc = ezdxf.new()
    lm  = LayerManager(doc)
    msp = doc.modelspace()
    total = 0

    sl_by_idx = {sl.index: sl for sl in result.slices}

    if sheet_layout_result is not None:
        slr = sheet_layout_result
        # Draw sheet boundary rectangles
        for sheet_no in range(slr.n_sheets):
            origin_x = sheet_no * (slr.sheet_width + _DEFAULT_GAP * 2)
            rect_pts = [
                (origin_x, 0),
                (origin_x + slr.sheet_width, 0),
                (origin_x + slr.sheet_width, slr.sheet_height),
                (origin_x, slr.sheet_height),
            ]
            r = msp.add_lwpolyline(rect_pts, dxfattribs={'layer': lm.DIMENSION_LAYER})
            r.close(True)

        for pl in slr.placements:
            sl = sl_by_idx.get(pl.slice_index)
            if sl is None:
                continue
            sheet_origin_x = pl.sheet_number * (slr.sheet_width + _DEFAULT_GAP * 2)
            total += _write_board_to_msp(
                sl, msp,
                x_off = sheet_origin_x + pl.x,
                y_off = pl.y,
                lm    = lm,
            )
    else:
        # Linear strip layout (original behaviour)
        x_cursor = 0.0
        for sl in result.slices:
            if not sl.contours:
                continue
            outer = max(sl.contours, key=_contour_area)
            bx_min = min(p[0] for p in outer)
            bx_max = max(p[0] for p in outer)
            w = bx_max - bx_min
            bz_min = min(p[1] for p in outer)
            total += _write_board_to_msp(sl, msp,
                                         x_off=x_cursor,
                                         y_off=-bz_min,
                                         lm=lm)
            x_cursor += w + layout_gap

    doc.saveas(output_path)
    return total


def slices_to_dxf_single(sl: 'BoardSlice', output_path: str) -> int:
    """
    Write a single BoardSlice to its own DXF file.

    The board is placed with its bbox corner at the origin.
    Returns entity count.
    """
    import ezdxf
    from layers import LayerManager

    doc = ezdxf.new()
    lm  = LayerManager(doc)
    msp = doc.modelspace()

    if not sl.contours:
        doc.saveas(output_path)
        return 0

    outer   = max(sl.contours, key=_contour_area)
    bx_min  = min(p[0] for p in outer)
    bz_min  = min(p[1] for p in outer)
    total   = _write_board_to_msp(sl, msp, x_off=-bx_min, y_off=-bz_min, lm=lm)

    doc.saveas(output_path)
    return total


def slices_to_dxf_per_board(
    result: 'SliceResult',
    output_dir:  str,
    prefix:      str = 'board',
) -> int:
    """
    Export each board to its own DXF file in ``output_dir``.

    Files are named ``{prefix}_{n:03d}.dxf`` (e.g. ``board_001.dxf``).
    Board origin is placed at (0, 0).

    Returns total entity count across all files.
    """
    import os
    total = 0
    for sl in result.slices:
        fname = f'{prefix}_{sl.index + 1:03d}.dxf'
        path  = os.path.join(output_dir, fname)
        total += slices_to_dxf_single(sl, path)
    return total


# ── Sheet layout ──────────────────────────────────────────────────────────────

@dataclass
class SheetPlacement:
    """Position of one board on a sheet."""
    slice_index: int
    x: float          # left edge of board's bbox on the sheet
    y: float          # bottom edge of board's bbox on the sheet
    width: float      # board bbox width
    height: float     # board bbox height
    sheet_number: int # 0-based sheet index (0 = fits on first sheet)


@dataclass
class SheetLayoutResult:
    placements:   List[SheetPlacement]
    n_sheets:     int
    sheet_width:  float
    sheet_height: float
    spacing:      float
    overflow:     List[int]   # slice indices that did not fit on any sheet


def sheet_layout(
    result: SliceResult,
    sheet_width:  float,
    sheet_height: float,
    spacing:      float = 10.0,
) -> SheetLayoutResult:
    """
    Greedy row-by-row packing of boards onto sheets.

    Boards are placed left-to-right.  When a board does not fit in the
    current row, a new row is started.  When a board does not fit on the
    current sheet, a new sheet is started.

    Parameters
    ----------
    result        : SliceResult (board order is preserved)
    sheet_width   : usable sheet width in mm
    sheet_height  : usable sheet height in mm
    spacing       : gap between boards (and from sheet edge) in mm

    Returns
    -------
    SheetLayoutResult with placement list, sheet count, and overflow list.
    """
    placements: List[SheetPlacement] = []
    overflow:   List[int]            = []

    cur_sheet  = 0
    row_x      = spacing          # left cursor within current row
    row_y      = spacing          # bottom of current row
    row_h      = 0.0              # tallest board in current row

    for sl in result.slices:
        if not sl.contours:
            continue
        outer = max(sl.contours, key=_contour_area)
        xs = [p[0] for p in outer]; zs = [p[1] for p in outer]
        bw = max(xs) - min(xs)
        bh = max(zs) - min(zs)

        # Board doesn't fit at all on the sheet
        if bw + 2 * spacing > sheet_width or bh + 2 * spacing > sheet_height:
            overflow.append(sl.index)
            continue

        # Try to place in current row
        if row_x + bw + spacing > sheet_width:
            # Wrap to next row
            row_y += row_h + spacing
            row_x  = spacing
            row_h  = 0.0

        if row_y + bh + spacing > sheet_height:
            # Start a new sheet
            cur_sheet += 1
            row_x = spacing
            row_y = spacing
            row_h = 0.0

        placements.append(SheetPlacement(
            slice_index  = sl.index,
            x            = row_x,
            y            = row_y,
            width        = bw,
            height       = bh,
            sheet_number = cur_sheet,
        ))
        row_x += bw + spacing
        row_h  = max(row_h, bh)

    return SheetLayoutResult(
        placements   = placements,
        n_sheets     = cur_sheet + 1 if placements else 0,
        sheet_width  = sheet_width,
        sheet_height = sheet_height,
        spacing      = spacing,
        overflow     = overflow,
    )


# ── Layout metrics ────────────────────────────────────────────────────────────

def slices_bounding_box(
    result: SliceResult,
    layout_gap: float = _DEFAULT_GAP,
) -> Tuple[float, float]:
    """Return (total_layout_width, max_board_depth) in mm."""
    widths, depths = [], []
    for sl in result.slices:
        if not sl.contours:
            continue
        outer = max(sl.contours, key=_contour_area)
        xs = [p[0] for p in outer]; zs = [p[1] for p in outer]
        widths.append(max(xs) - min(xs))
        depths.append(max(zs) - min(zs))
    if not widths:
        return (0.0, 0.0)
    total_w = sum(widths) + layout_gap * (len(widths) - 1)
    return (total_w, max(depths))


# ── Core slicing algorithm ────────────────────────────────────────────────────

def _intersect_triangles(triangles, y: float) -> List[Segment]:
    """
    Fast plane-mesh intersection.

    Uses numpy to pre-filter the ~1 % of triangles that actually straddle
    the plane, then runs the precise per-triangle intersection only on those.
    For a 13 k-triangle mesh this is ~100× faster than the naive full loop.
    """
    import numpy as np
    # d[i, j] = signed distance of vertex j of triangle i from the plane
    d = triangles[:, :, 1] - y          # shape (N, 3)
    all_pos = (d >= 0).all(axis=1)
    all_neg = (d <= 0).all(axis=1)
    cross   = ~(all_pos | all_neg)      # triangles that straddle the plane

    if not cross.any():
        return []

    tris_c = triangles[cross]
    d_c    = d[cross]

    segs: List[Segment] = []
    _EDGES = ((0, 1), (1, 2), (2, 0))
    for k in range(len(tris_c)):
        tri = tris_c[k]
        dk  = d_c[k]
        pts_xz: List[Tuple[float, float]] = []
        for i, j in _EDGES:
            di, dj = dk[i], dk[j]
            if (di < 0) == (dj < 0):
                continue
            denom = di - dj
            if abs(denom) < 1e-12:
                continue
            t = di / denom
            x = tri[i, 0] + t * (tri[j, 0] - tri[i, 0])
            z = tri[i, 2] + t * (tri[j, 2] - tri[i, 2])
            pts_xz.append((x, z))
        if len(pts_xz) >= 2:
            p0, p1 = pts_xz[0], pts_xz[1]
            if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) >= _SEG_TOL:
                segs.append((p0, p1))
    return segs


def _intersect_triangle(tri, y: float) -> Optional[Segment]:
    """Single-triangle intersection (kept for external callers/tests)."""
    v0, v1, v2 = tri
    pts = [v0, v1, v2]
    d   = [v[1] - y for v in pts]
    if all(di >= 0 for di in d) or all(di <= 0 for di in d):
        return None
    intersections: List[Tuple[float, float]] = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        di, dj = d[i], d[j]
        if (di < 0) == (dj < 0):
            continue
        if abs(di - dj) < 1e-12:
            continue
        t  = di / (di - dj)
        vi, vj = pts[i], pts[j]
        x  = vi[0] + t * (vj[0] - vi[0])
        z  = vi[2] + t * (vj[2] - vi[2])
        intersections.append((x, z))
    if len(intersections) < 2:
        return None
    p0, p1 = intersections[0], intersections[1]
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < _SEG_TOL:
        return None
    return (p0, p1)


def _stitch_segments(segments: List[Segment]) -> List[Contour]:
    """
    Chain segments into closed contours.

    Uses a spatial hash-map (endpoint → segment index) for O(N) average
    complexity instead of the previous O(N²) nearest-scan loop.  For a
    typical slice with 400 segments this is ~300× faster.
    """
    if not segments:
        return []

    # Quantise endpoints to a grid of _STITCH_TOL so nearby points hash equal.
    _PREC = 1.0 / _STITCH_TOL

    def _key(p: Tuple[float, float]) -> Tuple[int, int]:
        return (int(round(p[0] * _PREC)), int(round(p[1] * _PREC)))

    # Build endpoint → [(seg_idx, end_idx)]  (end_idx: 0=start, 1=end)
    ep_map: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for idx, seg in enumerate(segments):
        for end_i, pt in enumerate(seg):
            k = _key(pt)
            if k not in ep_map:
                ep_map[k] = []
            ep_map[k].append((idx, end_i))

    used    = bytearray(len(segments))   # faster than list[bool]
    contours: List[Contour] = []

    for start in range(len(segments)):
        if used[start]:
            continue

        used[start] = 1
        seg0  = segments[start]
        # Remove start's endpoints from map
        for end_i, pt in enumerate(seg0):
            k = _key(pt)
            ep_map[k] = [(i, e) for i, e in ep_map.get(k, []) if i != start]

        chain: List[Tuple[float, float]] = [seg0[0], seg0[1]]

        while True:
            tail = chain[-1]
            k    = _key(tail)
            found = False
            for seg_idx, end_i in ep_map.get(k, []):
                if used[seg_idx]:
                    continue
                used[seg_idx] = 1
                seg = segments[seg_idx]
                # Remove both endpoints from map
                for e2, pt2 in enumerate(seg):
                    k2 = _key(pt2)
                    ep_map[k2] = [(i, e) for i, e in ep_map.get(k2, []) if i != seg_idx]
                # The matched endpoint is end_i; we want the OTHER end
                chain.append(seg[1 - end_i])
                found = True
                break
            if not found:
                break

        if len(chain) >= 3:
            contours.append(chain)

    return contours


def _simplify(contour: Contour, tolerance: float) -> Contour:
    if len(contour) <= 2:
        return contour
    return _dp(contour, tolerance)


def _dp(pts: Contour, tol: float) -> Contour:
    if len(pts) <= 2:
        return pts
    start, end = pts[0], pts[-1]
    max_dist, max_idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = _point_line_dist(pts[i], start, end)
        if d > max_dist:
            max_dist, max_idx = d, i
    if max_dist > tol:
        return _dp(pts[:max_idx+1], tol)[:-1] + _dp(pts[max_idx:], tol)
    return [start, end]


def _point_line_dist(p, a, b) -> float:
    ax, az = a; bx, bz = b; px, pz = p
    dx, dz = bx - ax, bz - az
    sq = dx*dx + dz*dz
    if sq < 1e-12:
        return math.hypot(px-ax, pz-az)
    t = max(0.0, min(1.0, ((px-ax)*dx + (pz-az)*dz) / sq))
    return math.hypot(px-(ax+t*dx), pz-(az+t*dz))


def _contour_area(contour: Contour) -> float:
    n = len(contour)
    a = 0.0
    for i in range(n):
        j = (i+1) % n
        a += contour[i][0] * contour[j][1] - contour[j][0] * contour[i][1]
    return abs(a) / 2.0


# ── Built-in STL parser ───────────────────────────────────────────────────────

def _load_stl_builtin(path: str):
    import numpy as np
    with open(path, 'rb') as f:
        f.read(80)          # header
        try:
            n_tri = struct.unpack('<I', f.read(4))[0]
            tris = []
            for _ in range(n_tri):
                f.read(12)  # normal
                v0 = struct.unpack('<3f', f.read(12))
                v1 = struct.unpack('<3f', f.read(12))
                v2 = struct.unpack('<3f', f.read(12))
                f.read(2)   # attribute byte count
                tris.append([v0, v1, v2])
            if tris:
                return np.array(tris, dtype=float)
        except struct.error:
            pass

    tris, verts = [], []
    with open(path, 'r', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if line.startswith('vertex'):
                p = line.split()
                verts.append((float(p[1]), float(p[2]), float(p[3])))
            elif line.startswith('endloop'):
                if len(verts) == 3:
                    tris.append(verts)
                verts = []

    return np.array(tris, dtype=float)
