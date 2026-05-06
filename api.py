"""
api.py — FastAPI layer for the CNC DXF Generator engine.

Wraps the existing core modules (slicer.py, entity_model.py) as HTTP endpoints.
Does NOT import or depend on the GUI.  Core modules are unchanged.

Run
---
    uvicorn api:app --reload --port 8000

Or via the CLI helper at the bottom of this file:
    python api.py

API summary
-----------
    POST /slice             Upload STL + params → SSE stream of progress + result
    GET  /jobs/{id}/result  Poll for a completed result (alternative to SSE)
    POST /export_dxf        SliceResult JSON + options → DXF file download
    GET  /health            Liveness check

SSE event format
----------------
Every event on the /slice stream is a JSON object on the ``data:`` line:

    data: {"type": "progress", "done": 3, "total": 10}
    data: {"type": "result",   "job_id": "…", "data": { …SliceResult… }}
    data: {"type": "error",    "message": "…"}

The stream closes immediately after the result or error event.

Dependencies
------------
    pip install "fastapi[standard]" uvicorn
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import uuid
from typing import Any, Dict, List, Optional

# Must be set before any slicer import to avoid "no display" errors on
# headless servers (Railway, Heroku, etc.).  Agg is a non-interactive
# PNG/SVG backend; it has no dependency on X11 or a display.
import matplotlib
matplotlib.use('Agg')

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import slicer as _slicer

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title='CNC DXF Generator API',
    description=(
        'Slice 3D meshes into CNC-ready board profiles and export DXF files.\n\n'
        'This API wraps the same core engine used by the desktop GUI. '
        'All slicing logic lives in slicer.py and is unchanged.'
    ),
    version='1.0.0',
)

# CORS origins are read from the environment so the same binary works
# locally (allow localhost) and in production (allow the Vercel domain).
#
# Local dev:   CORS_ORIGINS not set → allow localhost:3000 + localhost:3001
# Production:  CORS_ORIGINS=https://your-app.vercel.app
#
# Multiple origins: comma-separated
#   CORS_ORIGINS=https://your-app.vercel.app,https://staging.vercel.app
_cors_env = os.environ.get('CORS_ORIGINS', '')
_cors_origins: list[str] = (
    [o.strip() for o in _cors_env.split(',') if o.strip()]
    if _cors_env
    else ['http://localhost:3000', 'http://localhost:3001']
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Catch-all for any Vercel deployment (preview + production URLs).
    # The explicit CORS_ORIGINS env var takes precedence for tighter control.
    allow_origin_regex=r'https://.*\.vercel\.app',
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Content-Type', 'Accept'],
    expose_headers=['Content-Disposition'],  # needed so JS can read the filename
)


# ── Serialization ─────────────────────────────────────────────────────────────

def result_to_json(result: _slicer.SliceResult) -> Dict[str, Any]:
    """
    Convert a SliceResult to a JSON-serializable dict.

    Contour points are stored as [[x, z], …] lists.
    All values are plain Python floats/ints/strings — no numpy types.
    """
    return {
        'board_thickness': float(result.board_thickness),
        'n_boards':        int(result.n_boards),
        'stacking_axis':   result.stacking_axis,
        'slab_mode':       result.slab_mode,
        'source_path':     result.source_path,
        'model_span':      float(result.model_span),
        'mesh_bounds':     [float(v) for v in result.mesh_bounds],
        'slices': [
            {
                'index':     int(s.index),
                'y_min':     float(s.y_min),
                'y_max':     float(s.y_max),
                'thickness': float(s.thickness),
                'label':     s.label,
                'contours': [
                    [[float(p[0]), float(p[1])] for p in contour]
                    for contour in s.contours
                ],
            }
            for s in result.slices
        ],
    }


def result_from_json(data: Dict[str, Any]) -> _slicer.SliceResult:
    """
    Reconstruct a SliceResult from a serialized dict (the inverse of result_to_json).

    Raises KeyError / TypeError / ValueError on malformed input.
    """
    slices = [
        _slicer.BoardSlice(
            index=int(s['index']),
            y_min=float(s['y_min']),
            y_max=float(s['y_max']),
            thickness=float(s['thickness']),
            contours=[
                [(float(p[0]), float(p[1])) for p in contour]
                for contour in s['contours']
            ],
            label=str(s.get('label', '')),
        )
        for s in data['slices']
    ]
    return _slicer.SliceResult(
        slices=slices,
        mesh_bounds=tuple(float(v) for v in data['mesh_bounds']),
        board_thickness=float(data['board_thickness']),
        n_boards=int(data['n_boards']),
        stacking_axis=str(data.get('stacking_axis', 'y')),
        source_path=str(data.get('source_path', '')),
        slab_mode=str(data.get('slab_mode', 'envelope')),
    )


# ── In-memory job store ───────────────────────────────────────────────────────

class _Job:
    """State for a single background slice job."""

    def __init__(self) -> None:
        self.id: str = str(uuid.uuid4())
        self.done: bool = False
        self.error: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
        self._events: List[str] = []
        self._lock = threading.Lock()

    def push(self, event: Dict[str, Any]) -> None:
        """Append a serialized SSE event (thread-safe)."""
        with self._lock:
            self._events.append(json.dumps(event, separators=(',', ':')))

    def drain(self) -> List[str]:
        """Return and clear all pending events (thread-safe)."""
        with self._lock:
            out, self._events = self._events, []
        return out


# Keyed by job_id.  In production, replace with Redis or a proper task queue.
_jobs: Dict[str, _Job] = {}


# ── POST /slice ───────────────────────────────────────────────────────────────

@app.post(
    '/slice',
    summary='Slice a 3D mesh into boards',
    response_description='Server-Sent Events stream of progress and result',
)
async def slice_endpoint(
    file:           UploadFile        = File(...,   description='3D model file to slice (STL or OBJ)'),
    axis:           str               = Form('y',   description="Stacking axis: 'x', 'y', or 'z'"),
    slab_mode:      str               = Form('envelope',
                                             description="Profile mode: 'envelope' or 'best_sample'"),
    quality:        str               = Form('accurate',
                                             description="Quality preset: 'accurate' or 'fast'"),
    slice_mode:     str               = Form('thickness',
                                             description="'thickness' (fixed mm) or 'count' (fixed N)"),
    thickness:      float             = Form(20.0,  description='Board thickness mm (slice_mode=thickness)'),
    n_boards:       int               = Form(5,     description='Board count (slice_mode=count)'),
    add_alignment:  bool              = Form(True,  description='Add dowel alignment holes'),
    dowel_radius:   float             = Form(3.0,   description='Dowel hole radius mm'),
    n_holes:        int               = Form(4,     description='Alignment hole count: 2, 3, or 4'),
    edge_margin_mm: Optional[float]   = Form(None,  description='Hole edge margin mm; omit for auto 20 %'),
) -> StreamingResponse:
    """
    Upload a 3D mesh file and slicing parameters.

    Returns a **Server-Sent Events** stream.  Connect with `EventSource` or
    any SSE client; each `data:` line is a JSON object:

    ```
    {"type": "progress", "done": 3,  "total": 10}
    {"type": "result",   "job_id": "…", "data": { …SliceResult… }}
    {"type": "error",    "message": "…"}
    ```

    The `result` payload from the `result` event can be sent directly to
    `POST /export_dxf` to generate the DXF file.
    """
    ext = os.path.splitext(file.filename or '')[1].lower() or '.stl'
    if ext not in ('.stl', '.obj'):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Accepted formats: .stl, .obj",
        )

    # Buffer upload to a temp file so the background thread can read it safely.
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        contents = await file.read()
        os.write(tmp_fd, contents)
    finally:
        os.close(tmp_fd)

    job = _Job()
    _jobs[job.id] = job

    def _worker() -> None:
        try:
            tris = _slicer.load_mesh(tmp_path)

            def _cb(done: int, total: int) -> None:
                job.push({'type': 'progress', 'done': done, 'total': total})

            if slice_mode == 'count':
                result = _slicer.slice_model_by_count(
                    tris, n_boards,
                    stacking_axis=axis,
                    slab_mode=slab_mode,
                    quality=quality,
                    progress_callback=_cb,
                )
            else:
                result = _slicer.slice_model(
                    tris, thickness,
                    stacking_axis=axis,
                    slab_mode=slab_mode,
                    quality=quality,
                    progress_callback=_cb,
                )

            if add_alignment:
                _slicer.add_alignment_geometry(
                    result,
                    dowel_radius=dowel_radius,
                    n_holes=n_holes,
                    edge_margin_mm=edge_margin_mm,
                )

            job.result = result_to_json(result)
            job.push({'type': 'result', 'job_id': job.id, 'data': job.result})

        except Exception as exc:
            job.error = str(exc)
            job.push({'type': 'error', 'message': str(exc)})
        finally:
            job.done = True
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    threading.Thread(target=_worker, daemon=True).start()

    async def _stream():
        try:
            while True:
                for raw in job.drain():
                    yield f'data: {raw}\n\n'
                if job.done:
                    for raw in job.drain():   # flush any final events
                        yield f'data: {raw}\n\n'
                    break
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass   # client disconnected — safe to exit

    return StreamingResponse(
        _stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',   # disable nginx buffering
        },
    )


# ── GET /jobs/{job_id}/result ─────────────────────────────────────────────────

@app.get(
    '/jobs/{job_id}/result',
    summary='Poll for a completed slice result',
)
async def job_result(job_id: str):
    """
    Non-streaming alternative to reading the SSE stream.

    * **202 Accepted** — job is still running; poll again.
    * **200 OK**       — job finished; body is the SliceResult JSON.
    * **404 Not Found** — unknown job_id.
    * **500**          — job failed; body has the error message.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail=f'Job {job_id!r} not found.')
    if not job.done:
        return JSONResponse({'status': 'running', 'job_id': job_id}, status_code=202)
    if job.error:
        raise HTTPException(500, detail=job.error)
    return job.result


# ── POST /export_dxf ──────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    """Request body for DXF export."""
    result:        Dict[str, Any]   # SliceResult as returned by /slice
    layout_gap:    float = 20.0     # mm gap between boards in linear strip
    sheet_width:   Optional[float] = None  # mm — enable sheet layout when set
    sheet_height:  Optional[float] = None
    sheet_spacing: float = 10.0
    filename:      str   = 'boards.dxf'


@app.post(
    '/export_dxf',
    summary='Generate a DXF file from a slice result',
    response_class=FileResponse,
)
async def export_dxf(body: ExportRequest, background_tasks: BackgroundTasks):
    """
    Accept a serialized SliceResult (the `data` field from a `result` SSE event)
    and return a DXF file.

    Supports:
    - **Linear strip layout** (default): boards laid out left-to-right.
    - **Sheet layout**: set `sheet_width` and `sheet_height` to pack boards
      onto CNC sheets with row-by-row packing.

    The returned file has `Content-Disposition: attachment` so browsers
    will prompt a download.
    """
    try:
        result = result_from_json(body.result)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, detail=f'Invalid result payload: {exc}')

    sheet_layout_result = None
    if body.sheet_width and body.sheet_height:
        try:
            sheet_layout_result = _slicer.sheet_layout(
                result,
                body.sheet_width,
                body.sheet_height,
                spacing=body.sheet_spacing,
            )
        except Exception as exc:
            raise HTTPException(400, detail=f'Sheet layout error: {exc}')

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)

    try:
        _slicer.slices_to_dxf(
            result,
            tmp_path,
            layout_gap=body.layout_gap,
            sheet_layout_result=sheet_layout_result,
        )
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise HTTPException(500, detail=f'DXF generation failed: {exc}')

    # Delete the temp file after the response is sent.
    background_tasks.add_task(os.unlink, tmp_path)

    return FileResponse(
        tmp_path,
        media_type='application/octet-stream',
        filename=body.filename,
        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'},
    )


# ── POST /export_dxf_per_board ────────────────────────────────────────────────

class PerBoardExportRequest(BaseModel):
    """Request body for per-board zip export."""
    result:   Dict[str, Any]
    prefix:   str = 'board'
    filename: str = 'boards.zip'


@app.post(
    '/export_dxf_per_board',
    summary='Export one DXF per board, returned as a zip archive',
    response_class=FileResponse,
)
async def export_dxf_per_board(
    body: PerBoardExportRequest,
    background_tasks: BackgroundTasks,
):
    """
    Export each board as a separate DXF file inside a zip archive.
    Equivalent to the desktop GUI's "Export Per-Board DXF…" button.
    """
    import zipfile

    try:
        result = result_from_json(body.result)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, detail=f'Invalid result payload: {exc}')

    # Write per-board DXFs to a temp dir, then zip them.
    tmp_dir  = tempfile.mkdtemp()
    zip_fd, zip_path = tempfile.mkstemp(suffix='.zip')
    os.close(zip_fd)

    try:
        _slicer.slices_to_dxf_per_board(result, tmp_dir, prefix=body.prefix)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fname in sorted(os.listdir(tmp_dir)):
                zf.write(os.path.join(tmp_dir, fname), arcname=fname)
    except Exception as exc:
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        raise HTTPException(500, detail=f'Per-board export failed: {exc}')
    finally:
        # Clean up temp DXF dir regardless of success/failure.
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    background_tasks.add_task(os.unlink, zip_path)

    return FileResponse(
        zip_path,
        media_type='application/zip',
        filename=body.filename,
        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'},
    )


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get('/health', summary='Liveness check', include_in_schema=False)
async def health():
    return {'status': 'ok', 'version': app.version}


# ── Photo → DXF ──────────────────────────────────────────────────────────────

import base64
import io as _io

import numpy as _np
from PIL import Image as _PIL, ImageFilter as _PILFilter
from skimage import (
    measure as _sk_measure, feature as _sk_feature, morphology as _sk_morph,
    filters as _sk_filters, exposure as _sk_exp, restoration as _sk_rest,
)


def _rdp(points: "_np.ndarray", epsilon: float) -> list:
    """Iterative Ramer–Douglas–Peucker simplification. Returns sorted index list."""
    n = len(points)
    if n <= 2:
        return list(range(n))
    stack: list = [(0, n - 1)]
    keep: set = {0, n - 1}
    while stack:
        s, e = stack.pop()
        if e - s <= 1:
            continue
        seg = points[e] - points[s]
        seg_len_sq = float(_np.dot(seg, seg))
        mid = points[s + 1:e]
        if seg_len_sq < 1e-12:
            dists = _np.linalg.norm(mid - points[s], axis=1)
        else:
            t = _np.clip(_np.dot(mid - points[s], seg) / seg_len_sq, 0.0, 1.0)
            dists = _np.linalg.norm(mid - (points[s] + _np.outer(t, seg)), axis=1)
        mi = int(_np.argmax(dists))
        mg = s + 1 + mi
        if dists[mi] > epsilon:
            keep.add(mg)
            stack.append((s, mg))
            stack.append((mg, e))
    return sorted(keep)


def _contour_perimeter(c: "_np.ndarray") -> float:
    """Arc length of a polyline in pixels."""
    diffs = _np.diff(c, axis=0)
    return float(_np.sum(_np.linalg.norm(diffs, axis=1)))


def _adaptive_rdp(c: "_np.ndarray", base_eps: float) -> list:
    """
    RDP with curvature-adaptive epsilon.
    Splits the contour at high-turn vertices, runs standard RDP on each
    inter-split segment — tight epsilon for curved regions, loose for
    near-straight runs.  Preserves arc detail while aggressively simplifying
    long straight edges.
    """
    n = len(c)
    if n <= 3:
        return _rdp(c, base_eps)

    v1 = c[1:-1] - c[:-2]
    v2 = c[2:]   - c[1:-1]
    l1 = _np.linalg.norm(v1, axis=1)
    l2 = _np.linalg.norm(v2, axis=1)
    valid = (l1 > 1e-9) & (l2 > 1e-9)
    denom = _np.where(valid, l1 * l2, 1.0)
    cos_a = _np.where(valid, _np.einsum('ij,ij->i', v1, v2) / denom, 1.0)
    angles = _np.arccos(_np.clip(cos_a, -1.0, 1.0))  # shape (n-2,), radians

    # Anchor the path at every vertex whose turn angle exceeds ~26°
    SPLIT_ANGLE = 0.45
    splits = [0] + [i + 1 for i in range(len(angles)) if angles[i] > SPLIT_ANGLE] + [n - 1]
    splits = sorted(set(splits))

    keep: set = set(splits)
    for k in range(len(splits) - 1):
        s, e = splits[k], splits[k + 1]
        if e - s <= 1:
            continue
        seg      = c[s:e + 1]
        seg_angs = angles[s:e - 1]
        mean_ang = float(seg_angs.mean()) if len(seg_angs) > 0 else 0.0
        if mean_ang > 0.35:
            eps = base_eps * 0.45      # curved — preserve detail
        elif mean_ang > 0.12:
            eps = base_eps * 0.85      # gently curved
        else:
            eps = base_eps * 1.80      # near-straight — simplify freely
        keep.update(s + idx for idx in _rdp(seg, eps))

    return sorted(keep)


def _encode_png(arr_uint8: "_np.ndarray") -> str:
    """Encode a uint8 grayscale or RGB numpy array as a base64 PNG data-URI."""
    mode = 'L' if arr_uint8.ndim == 2 else 'RGB'
    buf = _io.BytesIO()
    _PIL.fromarray(arr_uint8, mode=mode).save(buf, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def _analyze_image(arr: "_np.ndarray") -> dict:
    """Classify image type and recommend a tracing mode."""
    edges = _sk_feature.canny(arr, sigma=2.0)
    edge_density = float(edges.mean())

    p5  = float(_np.percentile(arr, 5))
    p95 = float(_np.percentile(arr, 95))
    contrast = p95 - p5

    hist, _ = _np.histogram(arr.ravel(), bins=16, range=(0.0, 1.0))
    total      = float(hist.sum())
    dark_frac  = float(hist[:3].sum())  / total
    light_frac = float(hist[13:].sum()) / total
    mid_frac   = 1.0 - dark_frac - light_frac

    if edge_density > 0.07:
        image_type       = 'line_art'
        recommended_mode = 'stroke'
        description      = 'High edge density — likely a sketch, pen drawing, or line art.'
        recommendation   = 'High-Fidelity Stroke extracts each drawn stroke as one continuous centerline path — ideal for this type of image.'
        artistic         = 'Accurate Trace works too; Contour Art turns the drawing into topographic bands with a stylized effect.'
    elif contrast > 0.65 and mid_frac < 0.35:
        image_type       = 'silhouette'
        recommended_mode = 'accurate'
        description      = 'High contrast with clear dark/light separation — silhouette or bold graphic.'
        recommendation   = 'Accurate Trace extracts clean outer edges and shape boundaries with minimal noise.'
        artistic         = 'Contour Art adds inner topographic layers revealing subtle tone variation within the shape.'
    elif contrast > 0.45 and edge_density > 0.025:
        image_type       = 'logo'
        recommended_mode = 'accurate'
        description      = 'Crisp edges and moderate contrast — likely a logo or graphic design.'
        recommendation   = 'Accurate Trace preserves the original geometry with faithful vector outlines.'
        artistic         = 'Contour Art gives the graphic a carved-relief look with concentric layer bands.'
    else:
        image_type       = 'photo'
        recommended_mode = 'contour_art'
        description      = 'Continuous-tone image — likely a photograph or portrait.'
        recommendation   = 'Contour Art transforms tonal depth into topographic lines, like a relief map of the scene.'
        artistic         = 'Each band represents a brightness slice — more levels means finer tonal detail.'

    return {
        'image_type':        image_type,
        'recommended_mode':  recommended_mode,
        'description':       description,
        'recommendation':    recommendation,
        'artistic_description': artistic,
        'edge_density':      round(edge_density, 4),
        'contrast':          round(contrast, 3),
        'param_hints':       {},
    }


# Keyword sets for prompt-based override
_KW_STROKE   = {'face', 'portrait', 'sketch', 'ink', 'pen', 'hair', 'stroke', 'fidelity',
                'fine detail', 'fine details', 'handdrawn', 'hand drawn', 'drawing', 'doodle'}
_KW_ACCURATE = {'edge', 'cut', 'cnc', 'outline', 'silhouette', 'simple', 'simplif',
                'laser', 'clean', 'minimal', 'bold', 'logo'}
_KW_CONTOUR  = {'contour', 'artistic', 'level', 'tonal', 'topograph', 'depth', 'relief',
                'layers', 'styliz'}
_KW_HALFTONE = {'dot', 'halftone', 'circle', 'drill', 'hole', 'stipple', 'pointilism',
                'pointillism', 'screen', 'engrav', 'dots', 'circles'}


def _apply_prompt_override(result: dict, prompt: str) -> dict:
    """Adjust analysis result based on user's free-text intent description."""
    p = prompt.lower()
    hints: dict = {}

    # Mode override — check specificity order: halftone > stroke > accurate > contour
    if any(kw in p for kw in _KW_HALFTONE):
        result['recommended_mode'] = 'halftone'
        result['recommendation']   = 'Your description suggests Dot / Halftone style — maps brightness to circle size.'
    elif any(kw in p for kw in _KW_STROKE):
        result['recommended_mode'] = 'stroke'
        result['recommendation']   = 'Your description suggests High-Fidelity Stroke — follows each drawn line faithfully.'
    elif any(kw in p for kw in _KW_ACCURATE):
        result['recommended_mode'] = 'accurate'
        result['recommendation']   = 'Your description suggests Accurate Trace — clean edges for CNC or laser cutting.'
    elif any(kw in p for kw in _KW_CONTOUR):
        result['recommended_mode'] = 'contour_art'
        result['recommendation']   = 'Your description suggests Contour Art — tonal depth mapped to layered bands.'

    # Parameter hints — independent of mode detection
    if any(kw in p for kw in ('simplif', 'simple', 'clean', 'minimal', 'cnc cut', 'laser cut')):
        hints['simplify']    = 8
        hints['min_length']  = 25
    if any(kw in p for kw in ('fine detail', 'fine details', 'detailed', 'all detail', 'keep detail')):
        hints['simplify']    = 2
        hints['min_length']  = 5
        hints['sensitivity'] = 7
    if any(kw in p for kw in ('outer contour', 'outline only', 'silhouette only', 'contour only')):
        hints['min_length']  = 50
        hints['simplify']    = 6
    if any(kw in p for kw in ('artistic', 'styliz', 'creative')):
        hints['sensitivity'] = 8

    if hints:
        result['param_hints'] = hints
    return result


def _halftone_grid_legacy(
    arr:        "_np.ndarray",  # float [0,1] grayscale, dark=subject
    density:    int   = 30,     # grid cells along the longer axis
    min_radius: float = 0.5,    # min circle radius in image pixels
    max_radius: float = 8.0,    # max circle radius in image pixels
    contrast:   float = 1.5,    # contrast multiplier before mapping
    invert:     bool  = False,  # swap bright/dark mapping
    gamma:      float = 0.8,    # gamma < 1 lifts shadow detail before mapping
    placement_mode: str = 'organic_density',
    randomness: float = 0.55,
    density_sensitivity: float = 1.25,
) -> list:
    """
    Divide image into a grid; map mean cell brightness → circle radius.
    Darker cells → larger circles (more ink / more material removed).
    Returns list of [center_row, center_col, radius] in image pixel coords.
    """
    h, w = arr.shape

    # Gamma correction: lifts shadow detail so dark mid-tones map to
    # distinguishable radii instead of collapsing near max_radius.
    arr_g = _np.clip(arr, 1e-6, 1.0) ** gamma

    # Contrast boost (clip to [0,1])
    mid     = float(_np.median(arr_g))
    boosted = _np.clip((arr_g - mid) * contrast + mid, 0.0, 1.0)
    if invert:
        boosted = 1.0 - boosted

    # Soft edge-proximity map: cells near structural edges get a slight radius
    # boost so image outlines stay readable at any density setting.
    edge_map  = _sk_feature.canny(arr, sigma=1.5).astype(float)
    edge_soft = _sk_filters.gaussian(edge_map, sigma=max(1.5, max(w, h) / (density * 4)))

    # Grid cell size — density = cells along the LONGER axis
    cell   = max(w, h) / density
    rows   = max(1, round(h / cell))
    cols   = max(1, round(w / cell))
    cell_h = h / rows
    cell_w = w / cols
    r_span = max_radius - min_radius

    circles: list = []
    for gr in range(rows):
        for gc in range(cols):
            r0 = int(gr * cell_h);  r1 = min(h, int((gr + 1) * cell_h))
            c0 = int(gc * cell_w);  c1 = min(w, int((gc + 1) * cell_w))
            cell_px = boosted[r0:r1, c0:c1]
            if cell_px.size == 0:
                continue
            brightness = float(cell_px.mean())
            # Non-linear (power 0.7) radius mapping: expands mid-tone discrimination
            # compared to the linear map, giving finer dot-size variation in greys.
            radius = min_radius + (1.0 - brightness) ** 0.7 * r_span
            # Edge proximity boost: up to +12 % of radius range near strong edges
            cr_i = min(h - 1, int((r0 + r1) * 0.5))
            cc_i = min(w - 1, int((c0 + c1) * 0.5))
            radius = min(max_radius, radius + float(edge_soft[cr_i, cc_i]) * r_span * 0.12)
            if radius > min_radius * 0.3:
                circles.append([
                    round((r0 + r1) * 0.5, 2),
                    round((c0 + c1) * 0.5, 2),
                    round(radius, 3),
                ])

    return circles


def _halftone_grid(
    arr: "_np.ndarray",
    density: int = 30,
    min_radius: float = 0.5,
    max_radius: float = 8.0,
    contrast: float = 1.5,
    invert: bool = False,
    gamma: float = 0.8,
    placement_mode: str = 'organic_density',
    randomness: float = 0.55,
    density_sensitivity: float = 1.25,
) -> list:
    """Image-driven halftone holes with fabrication-aware spacing."""
    import math as _math
    import random as _random

    h, w = arr.shape
    placement_mode = (placement_mode or 'organic_density').strip().lower()
    placement_mode = {
        'organic': 'organic_density',
        'organic density': 'organic_density',
        'hex': 'hex_packing',
        'hex packing': 'hex_packing',
        'flow': 'flow_field',
        'flow field': 'flow_field',
    }.get(placement_mode, placement_mode)
    if placement_mode not in {'organic_density', 'hex_packing', 'flow_field'}:
        placement_mode = 'organic_density'
    randomness = max(0.0, min(1.0, float(randomness)))
    density_sensitivity = max(0.35, min(3.0, float(density_sensitivity)))

    arr_g = _np.clip(arr, 1e-6, 1.0) ** gamma
    mid = float(_np.median(arr_g))
    boosted = _np.clip((arr_g - mid) * contrast + mid, 0.0, 1.0)
    if invert:
        boosted = 1.0 - boosted

    edge_map = _sk_feature.canny(arr, sigma=1.5).astype(float)
    edge_soft = _sk_filters.gaussian(edge_map, sigma=max(1.5, max(w, h) / (density * 4)))
    edge_soft = edge_soft / max(float(edge_soft.max()), 1e-6)

    r_span = max_radius - min_radius
    base_step = max(2.0, max(w, h) / max(5, density))
    base_bridge = max(1.0, min_radius * 0.85, base_step * 0.10)
    edge_margin = max_radius + base_bridge * 0.5
    darkness = _np.clip((1.0 - boosted) ** density_sensitivity, 0.0, 1.0)

    circles: list = []
    bin_size = max(1.0, max_radius * 2.0 + base_bridge)
    bins: dict = {}

    def sample(map_arr: "_np.ndarray", row: float, col: float) -> float:
        rr = int(min(h - 1, max(0, round(row))))
        cc = int(min(w - 1, max(0, round(col))))
        return float(map_arr[rr, cc])

    def radius_for(row: float, col: float, tone: Optional[float] = None) -> float:
        t = sample(darkness, row, col) if tone is None else tone
        e = sample(edge_soft, row, col)
        return max(min_radius, min(max_radius, min_radius + (t ** 0.72) * r_span + e * r_span * 0.10))

    def add_circle(row: float, col: float, radius: float, bridge: float) -> bool:
        if row < edge_margin or col < edge_margin or row > h - edge_margin or col > w - edge_margin:
            return False
        br, bc = int(row // bin_size), int(col // bin_size)
        for rr in range(br - 1, br + 2):
            for cc in range(bc - 1, bc + 2):
                for orow, ocol, orad in bins.get((rr, cc), []):
                    if _math.hypot(row - orow, col - ocol) < radius + orad + bridge:
                        return False
        circles.append([round(row, 2), round(col, 2), round(radius, 3)])
        bins.setdefault((br, bc), []).append((row, col, radius))
        return True

    rng = _random.Random(1337)

    if placement_mode == 'hex_packing':
        step = max(min_radius * 2.0 + base_bridge, base_step)
        y_step = step * _math.sqrt(3.0) * 0.5
        row_i = 0
        y = edge_margin
        while y <= h - edge_margin:
            x = edge_margin + (step * 0.5 if row_i % 2 else 0.0)
            while x <= w - edge_margin:
                tone = sample(darkness, y, x)
                keep = min(1.0, 0.10 + tone * 1.05 + sample(edge_soft, y, x) * 0.20)
                if rng.random() < keep:
                    jitter = step * 0.10 * randomness
                    row = y + rng.uniform(-jitter, jitter)
                    col = x + rng.uniform(-jitter, jitter)
                    add_circle(row, col, radius_for(row, col, tone), base_bridge)
                x += step
            row_i += 1
            y += y_step
        return circles

    if placement_mode == 'flow_field':
        gy = _sk_filters.scharr_v(boosted)
        gx = _sk_filters.scharr_h(boosted)
        grad = _np.hypot(gx, gy)
        grad = grad / max(float(grad.max()), 1e-6)
        step = max(min_radius * 2.0 + base_bridge, base_step * 0.92)
        for y0 in _np.arange(edge_margin, h - edge_margin, step):
            phase = rng.uniform(-step * 0.45, step * 0.45) * randomness
            for x0 in _np.arange(edge_margin + phase, w - edge_margin, step):
                row, col = float(y0), float(x0)
                rr = int(min(h - 1, max(0, round(row))))
                cc = int(min(w - 1, max(0, round(col))))
                g = float(grad[rr, cc])
                vx, vy = -float(gy[rr, cc]), float(gx[rr, cc])
                mag = _math.hypot(vx, vy) or 1.0
                flow_shift = (g * 1.25 + 0.15) * step * randomness
                row += (vy / mag) * rng.uniform(-flow_shift, flow_shift)
                col += (vx / mag) * rng.uniform(-flow_shift, flow_shift)
                tone = sample(darkness, row, col)
                keep = min(1.0, 0.06 + tone * 0.98 + g * 0.35)
                if rng.random() < keep:
                    add_circle(row, col, radius_for(row, col, tone), base_bridge)
        return circles

    max_attempts = int(min(260000, max(2500, density * density * 24)))
    accepted_target = int(min(45000, max(200, density * density * 2.8)))
    for _ in range(max_attempts):
        if len(circles) >= accepted_target:
            break
        row = rng.uniform(edge_margin, h - edge_margin)
        col = rng.uniform(edge_margin, w - edge_margin)
        tone = sample(darkness, row, col)
        probability = min(1.0, 0.015 + tone * 1.15 + sample(edge_soft, row, col) * 0.20)
        if rng.random() > probability:
            continue
        local_bridge = base_bridge + (1.0 - tone) * base_step * (0.35 + randomness * 0.35)
        add_circle(row, col, radius_for(row, col, tone), local_bridge)

    return circles


def _halftone_density_heatmap(arr: "_np.ndarray", contrast: float, invert: bool, sensitivity: float) -> str:
    arr_g = _np.clip(arr, 1e-6, 1.0) ** 0.8
    mid = float(_np.median(arr_g))
    boosted = _np.clip((arr_g - mid) * contrast + mid, 0.0, 1.0)
    if invert:
        boosted = 1.0 - boosted
    d = _np.clip((1.0 - boosted) ** max(0.35, min(3.0, sensitivity)), 0.0, 1.0)
    rgb = _np.zeros((*d.shape, 3), dtype=_np.uint8)
    rgb[..., 0] = _np.clip(255 * d, 0, 255).astype(_np.uint8)
    rgb[..., 1] = _np.clip(190 * (1.0 - _np.abs(d - 0.55) * 1.8), 0, 190).astype(_np.uint8)
    rgb[..., 2] = _np.clip(180 * (1.0 - d), 0, 180).astype(_np.uint8)
    return _encode_png(rgb)


def _halftone_fabrication_metrics(circles: list, w: int, h: int, min_radius: float, max_radius: float) -> dict:
    import math as _math
    panel_area = max(1.0, float(w * h))
    open_area = sum(_math.pi * float(c[2]) * float(c[2]) for c in circles if len(c) >= 3)
    open_pct = max(0.0, min(95.0, open_area / panel_area * 100.0))
    min_bridge = None
    bin_size = max(1.0, max_radius * 2.5)
    bins: dict = {}
    for idx, c in enumerate(circles):
        row, col, _ = map(float, c[:3])
        bins.setdefault((int(row // bin_size), int(col // bin_size)), []).append(idx)
    for i, a in enumerate(circles):
        ar, ac, rad_a = map(float, a[:3])
        br_i, bc_i = int(ar // bin_size), int(ac // bin_size)
        for rr in range(br_i - 1, br_i + 2):
            for cc in range(bc_i - 1, bc_i + 2):
                for j in bins.get((rr, cc), []):
                    if j <= i:
                        continue
                    br, bc, rad_b = map(float, circles[j][:3])
                    gap = _math.hypot(ar - br, ac - bc) - rad_a - rad_b
                    if min_bridge is None or gap < min_bridge:
                        min_bridge = gap
    if min_bridge is None:
        min_bridge = 0.0
    target_bridge = max(1.0, min_radius * 0.85)
    bridge_score = max(0.0, min(1.0, min_bridge / max(target_bridge, 1e-6)))
    open_score = 1.0 if open_pct <= 35.0 else max(0.0, 1.0 - (open_pct - 35.0) / 35.0)
    strength_score = int(round(100.0 * min(bridge_score, open_score)))
    strength = 'High' if strength_score >= 72 else 'Moderate' if strength_score >= 45 else 'Low'
    return {
        'open_area_pct': round(open_pct, 1),
        'min_bridge_px': round(float(min_bridge), 2),
        'max_hole_diameter_px': round(float(max_radius) * 2.0, 2),
        'strength_score': strength_score,
        'strength_label': strength,
    }


def _chaikin(pts: "_np.ndarray", iters: int = 1) -> "_np.ndarray":
    """Chaikin corner-cutting: smooths polyline curves while preserving endpoints."""
    for _ in range(iters):
        if len(pts) < 3:
            break
        new_pts = [pts[0]]
        for i in range(len(pts) - 1):
            new_pts.append(0.75 * pts[i] + 0.25 * pts[i + 1])
            new_pts.append(0.25 * pts[i] + 0.75 * pts[i + 1])
        new_pts.append(pts[-1])
        pts = _np.array(new_pts)
    return pts


_SEG_PALETTE = [
    (255,  80,  80), ( 80, 200,  80), ( 80, 120, 255), (255, 200,   0),
    (255, 100, 200), (  0, 220, 220), (200, 120, 255), (  0, 200, 140),
    (255, 160,  40), (160, 255,  80), ( 80, 200, 255), (255,  80, 160),
]


def _render_paths_img(height: int, width: int, path_list: list) -> str:
    """Render pixel-coordinate paths into a colour PNG data-URI (diagnostic)."""
    canvas = _np.zeros((height, width, 3), dtype=_np.uint8)
    for i, path in enumerate(path_list):
        if not path:
            continue
        col = _np.array(_SEG_PALETTE[i % len(_SEG_PALETTE)], dtype=_np.uint8)
        rs  = _np.clip([int(p[0]) for p in path], 0, height - 1)
        cs  = _np.clip([int(p[1]) for p in path], 0, width  - 1)
        canvas[rs, cs] = col
    return _encode_png(canvas)


def _hifi_stroke_paths(
    arr: "_np.ndarray",
    sensitivity: float,
    min_arc: int,
    simplify_eps: float,
) -> dict:
    """
    High-Fidelity Line Art stroke tracer.
    Optimised for sketch portraits, pen/ink drawings, overlapping flowing lines.

    Pipeline
    --------
    1.  CLAHE contrast enhancement (faint strokes become visible)
    2.  Bilateral edge-preserving denoise (smooth noise, keep stroke edges sharp)
    3.  Sauvola adaptive binarisation ∪ global Otsu (thin AND bold strokes)
    4.  Morphological cleanup
    5.  Skeletonisation to 1-px centrelines
    6.  Direction-aware pixel graph construction (segment extraction)
    7.  Optimal junction pairing — crossing disambiguation via exhaustive search
        for n≤4 branches, greedy otherwise
    8.  Global stroke assembly: follow pairing decisions end-to-end
    9.  Two-pass gap bridging (direction + distance compatible endpoints)
    10. Very gentle RDP + two-pass Chaikin smoothing

    Returns a dict compatible with _stroke_paths_v2 plus 'n_crossings'.
    """
    import math as _math

    h, w = arr.shape

    # ── 1. CLAHE ──────────────────────────────────────────────────────────────
    enhanced   = _sk_exp.equalize_adapthist(arr, clip_limit=0.015)
    cleaned_b64 = _encode_png((_np.clip(enhanced, 0, 1) * 255).astype(_np.uint8))

    # ── 2. Bilateral edge-preserving denoise ──────────────────────────────────
    sigma_sp = max(0.5, 1.8 - (sensitivity - 1.0) * 0.12)
    denoised = _sk_rest.denoise_bilateral(
        enhanced.astype(float), sigma_color=0.10,
        sigma_spatial=sigma_sp, channel_axis=None,
    )

    # ── 3. Sauvola ∪ Otsu binarisation ───────────────────────────────────────
    k_sauv = max(0.04, 0.30 - (sensitivity - 1.0) * 0.029)
    win    = int(max(15, min(51, (h + w) // 55)) | 1)
    t_sauv  = _sk_filters.threshold_sauvola(denoised, window_size=win, k=k_sauv)
    b_sauv  = denoised < t_sauv
    try:
        t_otsu = _sk_filters.threshold_otsu(denoised)
    except Exception:
        t_otsu = 0.5
    b_otsu  = denoised < (t_otsu + (sensitivity - 5.5) * -0.025)
    binary  = b_sauv | b_otsu

    # ── 4. Morphological cleanup ──────────────────────────────────────────────
    min_blob = max(3, min_arc // 10)
    binary   = _sk_morph.remove_small_objects(binary.astype(bool), max_size=max(0, min_blob - 1))
    binary   = _sk_morph.closing(binary, _sk_morph.disk(1))
    binary   = _sk_morph.opening(binary, _sk_morph.disk(1))
    binary_b64 = _encode_png((binary.astype(_np.uint8)) * 255)

    # ── 5. Skeletonise ────────────────────────────────────────────────────────
    skel = _sk_morph.skeletonize(binary)

    # Spur pruning via distance transform: skeleton pixels in regions where the
    # original stroke is thinner than ~1 px are feathered-edge artefacts or
    # diagonal staircase noise — remove them before building the pixel graph.
    from scipy.ndimage import distance_transform_edt as _dte
    dt     = _dte(binary)
    min_dt = max(0.5, 0.85 - (sensitivity - 5.0) * 0.04)
    skel   = skel & (dt >= min_dt)

    skel_b64      = _encode_png((skel.astype(_np.uint8)) * 255)
    ys, xs        = _np.where(skel)
    total_skel_px = int(len(ys))

    _empty = dict(
        paths=[], cleaned=cleaned_b64, binary=binary_b64, skeleton=skel_b64,
        segments=cleaned_b64, merged=cleaned_b64, n_raw_segments=0,
        n_merges=0, n_bridges=0, n_discarded=0, n_crossings=0,
        coverage_pct=0.0, avg_stroke_len=0.0, total_skel_px=total_skel_px,
    )
    if total_skel_px == 0:
        return _empty

    pix_set: set = set(zip(ys.tolist(), xs.tolist()))

    def nbrs8(r: int, c: int) -> list:
        return [(r + dr, c + dc)
                for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                if (dr, dc) != (0, 0) and (r + dr, c + dc) in pix_set]

    # ── 6. Pixel graph ────────────────────────────────────────────────────────
    degree   = {p: len(nbrs8(*p)) for p in pix_set}
    node_set = {p for p, d in degree.items() if d != 2}

    # Extract segments: chains of degree-2 pixels between node pixels
    visited  = set(node_set)
    raw_segs: list = []       # (node_a, node_b, [pixels...])

    for sn in node_set:
        for nb in nbrs8(*sn):
            if nb in visited:
                continue
            chain = [sn, nb]
            visited.add(nb)
            prev, cur = sn, nb
            while True:
                cands = [p for p in nbrs8(*cur) if p != prev]
                nds   = [p for p in cands if p in node_set]
                d2s   = [p for p in cands if p not in node_set and p not in visited]
                if nds:
                    chain.append(nds[0]); break
                elif d2s:
                    nxt = d2s[0]; visited.add(nxt)
                    chain.append(nxt); prev, cur = cur, nxt
                else:
                    break
            end = chain[-1] if chain[-1] in node_set else cur
            if len(chain) >= 2:
                raw_segs.append((sn, end, chain))

    # Direct node-to-node edges (adjacent junction pixels have no degree-2 bridge,
    # so they are skipped by the chain tracer above — add them explicitly so the
    # junction collapser can later identify and collapse crossing diamonds).
    _direct_seen: set = set()
    for sn in node_set:
        for nb in nbrs8(*sn):
            if nb in node_set:
                key = (sn, nb) if sn < nb else (nb, sn)
                if key not in _direct_seen:
                    _direct_seen.add(key)
                    raw_segs.append((sn, nb, [sn, nb]))

    # Isolated loops (no junction nodes in cycle)
    for p in pix_set:
        if p not in visited:
            visited.add(p); loop = [p]; prev, cur = None, p
            while True:
                cands = [nb for nb in nbrs8(*cur) if nb != prev and nb not in visited]
                if not cands:
                    break
                nxt = cands[0]; visited.add(nxt)
                loop.append(nxt); prev, cur = cur, nxt
            if len(loop) >= 2:
                loop.append(loop[0])
                raw_segs.append((loop[0], loop[0], loop))

    segs_b64 = _render_paths_img(h, w, [s[2] for s in raw_segs])

    # ── 6b. Junction bridge collapsing ────────────────────────────────────────
    # At stroke crossings the skeleton produces a 2–6 px "diamond" of junction
    # pixels connected by very short segments.  These fragment what should be a
    # clean X-crossing into many 3-branch nodes, each seeing only a partial
    # picture of the crossing.  Collapsing those short inter-junction segments
    # via union-find reduces the cluster to one virtual super-node so the
    # optimal pairing sees all four arms at once.
    J_THRESH = 5  # px: junction-to-junction segments ≤ this length are collapsed

    j_par: dict = {n: n for n in node_set}

    def _jfind(x):
        root = x
        while j_par.get(root, root) != root:
            root = j_par[root]
        # Path compression
        while j_par.get(x, x) != root:
            j_par[x], x = root, j_par[x]
        return root

    def _junion(a, b):
        ra, rb = _jfind(a), _jfind(b)
        if ra != rb:
            j_par[ra] = rb

    collapse_idx: set = set()
    for i, (a, b, pix) in enumerate(raw_segs):
        if a == b or a not in node_set or b not in node_set:
            continue
        if degree.get(a, 0) < 3 or degree.get(b, 0) < 3:
            continue
        if len(pix) <= J_THRESH + 2:
            _junion(a, b)
            collapse_idx.add(i)

    # Remap segment endpoints to their virtual junction roots; drop intra-cluster segs
    raw_segs_r: list = []
    for i, (a, b, pix) in enumerate(raw_segs):
        if i in collapse_idx:
            continue
        va = _jfind(a) if a in node_set else a
        vb = _jfind(b) if b in node_set else b
        if va == vb and a in node_set and b in node_set:
            continue   # intra-cluster bridge — drop
        raw_segs_r.append((va, vb, pix))
    raw_segs = raw_segs_r
    n_raw = len(raw_segs)

    # ── 7. Optimal junction pairing (crossing disambiguation) ─────────────────
    LOOK = 15  # pixels ahead for direction estimation (wider = better for curves)

    def outdir(pixels: list, from_end: int) -> tuple:
        """Unit vector pointing FROM pixels[from_end] INTO the segment."""
        pts = pixels if from_end == 0 else list(reversed(pixels))
        n   = min(LOOK, len(pts) - 1)
        if n == 0:
            return (0.0, 0.0)
        dr, dc = pts[n][0] - pts[0][0], pts[n][1] - pts[0][1]
        L = _math.hypot(dr, dc)
        return (dr / L, dc / L) if L > 1e-9 else (0.0, 0.0)

    # Build node_adj from remapped segments (virtual node IDs as keys)
    all_vnodes: set = set()
    for va, vb, _ in raw_segs:
        all_vnodes.add(va)
        if va != vb:
            all_vnodes.add(vb)
    node_adj: dict = {n: [] for n in all_vnodes}
    for i, (a, b, pix) in enumerate(raw_segs):
        da = outdir(pix, 0)
        db = outdir(pix, -1)
        node_adj[a].append((i, b, da))
        if a != b:
            node_adj[b].append((i, a, db))

    def ap_score(d1: tuple, d2: tuple) -> float:
        """Anti-parallel score: +1 = perfectly straight through, -1 = U-turn."""
        return -(d1[0] * d2[0] + d1[1] * d2[1])

    def best_pairing(branches: list) -> list:
        """
        Optimal pairing of branches at a junction for maximum direction continuity.
        branches: [(seg_idx, other_node, outdir), ...]
        Returns: [(seg_a, seg_b), ...] pairs to join through this node.
        Only pairs where individual ap_score > -0.17 (~100° angle) are included.
        """
        n = len(branches)
        if n < 2:
            return []

        def S(i: int, j: int) -> float:
            return ap_score(branches[i][2], branches[j][2])

        if n == 2:
            # Accept if the two branches form an angle ≤ ~110°
            return [(branches[0][0], branches[1][0])] if S(0, 1) > -0.35 else []

        if n == 3:
            opts = [(S(i, j), branches[i][0], branches[j][0])
                    for i in range(3) for j in range(i + 1, 3)]
            best = max(opts, key=lambda x: x[0])
            return [(best[1], best[2])] if best[0] > -0.17 else []

        if n == 4:
            # All 3 perfect matchings; only keep pairs whose individual score > -0.17
            m0 = [(branches[i][0], branches[j][0]) for i, j in [(0,1),(2,3)] if S(i,j) > -0.17]
            m1 = [(branches[i][0], branches[j][0]) for i, j in [(0,2),(1,3)] if S(i,j) > -0.17]
            m2 = [(branches[i][0], branches[j][0]) for i, j in [(0,3),(1,2)] if S(i,j) > -0.17]
            t0 = sum(S(i,j) for i,j in [(0,1),(2,3)] if S(i,j) > -0.17)
            t1 = sum(S(i,j) for i,j in [(0,2),(1,3)] if S(i,j) > -0.17)
            t2 = sum(S(i,j) for i,j in [(0,3),(1,2)] if S(i,j) > -0.17)
            return max([(t0, m0), (t1, m1), (t2, m2)], key=lambda x: x[0])[1]

        # n ≥ 5: greedy by score, only keep pairs above angle threshold
        pairs: list = []
        used  = [False] * n
        cands = sorted([(S(i, j), i, j)
                        for i in range(n) for j in range(i + 1, n)],
                       key=lambda x: -x[0])
        for s, i, j in cands:
            if s <= -0.17:
                break
            if not used[i] and not used[j]:
                pairs.append((branches[i][0], branches[j][0]))
                used[i] = used[j] = True
        return pairs

    # Count crossings from effective degrees (after junction collapsing)
    n_crossings = sum(1 for brs in node_adj.values() if len(brs) >= 3)

    # continuation[(seg_idx, junction_node)] = next_seg_idx
    cont: dict = {}
    for node, brs in node_adj.items():
        if len(brs) < 2:
            continue
        for sa, sb in best_pairing(brs):
            cont[(sa, node)] = sb
            cont[(sb, node)] = sa

    # ── 8. Global stroke assembly ─────────────────────────────────────────────
    used_s: set = set()
    assembled: list = []
    n_merges = 0

    def orient_seg(seg_idx: int, entry_node) -> tuple:
        a, b, pix = raw_segs[seg_idx]
        if a == entry_node:
            return pix, b
        return list(reversed(pix)), a

    def trace_stroke(start_i: int, entry_node) -> list:
        nonlocal n_merges
        pxs: list = []
        si, en = start_i, entry_node
        while si is not None and si not in used_s:
            used_s.add(si)
            spix, exit_nd = orient_seg(si, en)
            pxs = pxs + (spix[1:] if pxs else spix)
            nxt = cont.get((si, exit_nd))
            if nxt is not None and nxt not in used_s:
                n_merges += 1
                si, en = nxt, exit_nd
            else:
                break
        return pxs

    # Start from true endpoints (effective degree 1) to capture full strokes
    for node, brs in node_adj.items():
        if len(brs) == 1:
            si = brs[0][0]
            if si not in used_s:
                s = trace_stroke(si, node)
                if s:
                    assembled.append(s)

    # Remaining segments (loops, orphaned pieces)
    for i in range(len(raw_segs)):
        if i not in used_s:
            a = raw_segs[i][0]
            s = trace_stroke(i, a)
            if s:
                assembled.append(s)

    merged_b64 = _render_paths_img(h, w, assembled)

    # ── 9. Two-pass gap bridging ──────────────────────────────────────────────
    n_bridges = 0

    def ep_dir(s: list, tail: bool) -> tuple:
        """Direction of stroke at an endpoint."""
        n = min(LOOK, len(s) - 1)
        if n == 0:
            return (0.0, 0.0)
        if tail:
            dr, dc = s[-1][0] - s[-1 - n][0], s[-1][1] - s[-1 - n][1]
        else:
            dr, dc = s[0][0] - s[n][0], s[0][1] - s[n][1]
        L = _math.hypot(dr, dc)
        return (dr / L, dc / L) if L > 1e-9 else (0.0, 0.0)

    for pass_gap, pass_cos in [(50, 0.40), (30, 0.58)]:
        eps_list = []
        for i, s in enumerate(assembled):
            if len(s) < 2:
                continue
            eps_list.append((i, False, s[0],  ep_dir(s, False)))
            eps_list.append((i, True,  s[-1], ep_dir(s, True)))

        consumed: set = set()
        for ia, (si, tail_a, pa, da) in enumerate(eps_list):
            if si in consumed:
                continue
            best_score, best_ib = -1.0, -1
            for ib, (sj, tail_b, pb, db) in enumerate(eps_list):
                if sj == si or sj in consumed or ib == ia:
                    continue
                dr, dc = pb[0] - pa[0], pb[1] - pa[1]
                dist   = _math.hypot(dr, dc)
                if dist < 1 or dist > pass_gap:
                    continue
                dir_ab = (dr / dist, dc / dist)
                dot_a  =  da[0] * dir_ab[0] + da[1] * dir_ab[1]
                dot_b  = -db[0] * dir_ab[0] - db[1] * dir_ab[1]
                if dot_a < pass_cos or dot_b < pass_cos:
                    continue
                sc = dot_a + dot_b - dist / pass_gap
                if sc > best_score:
                    best_score, best_ib = sc, ib

            if best_ib >= 0:
                sj, tail_b, pb, db = eps_list[best_ib]
                sa_px = assembled[si]
                sb_px = assembled[sj]
                if tail_a and not tail_b:
                    assembled[si] = sa_px + sb_px
                elif tail_a and tail_b:
                    assembled[si] = sa_px + list(reversed(sb_px))
                elif not tail_a and tail_b:
                    assembled[si] = sb_px + sa_px
                else:
                    assembled[si] = list(reversed(sb_px)) + sa_px
                assembled[sj] = []
                consumed.add(sj)
                n_bridges += 1

    # ── 10. Filter, RDP, Chaikin ──────────────────────────────────────────────
    n_discarded = 0
    covered_px  = 0
    result: list = []
    min_len = max(2, min_arc // 10)          # very lenient to preserve fine detail
    # epsilon ≥ 0.8 eliminates sub-pixel staircase noise from diagonal skeleton lines
    eps_rdp = max(0.8, simplify_eps / 4.0)

    for s in assembled:
        if len(s) < 2:
            continue
        arc = sum(_math.hypot(s[k+1][0]-s[k][0], s[k+1][1]-s[k][1])
                  for k in range(len(s)-1))
        if arc < min_len:
            n_discarded += 1
            continue
        pts  = _np.array(s, dtype=float)
        idx  = _rdp(pts, eps_rdp)
        simp = pts[idx]
        # Two Chaikin passes for long curves (arc > 40 px) gives smoother arcs;
        # short strokes stay sharp with one pass to avoid over-rounding endpoints.
        smoothed = _chaikin(simp, iters=2 if arc > 40 else 1)
        if len(smoothed) >= 2:
            covered_px += len(s)
            result.append(smoothed.tolist())

    result.sort(key=lambda p: -len(p))
    result = result[:3000]   # allow dense portrait detail

    coverage_pct   = round(covered_px / max(total_skel_px, 1) * 100, 1)
    avg_stroke_len = round(covered_px / max(len(result), 1), 1)

    return dict(
        paths=result, cleaned=cleaned_b64, binary=binary_b64,
        skeleton=skel_b64, segments=segs_b64, merged=merged_b64,
        n_raw_segments=n_raw, n_merges=n_merges, n_bridges=n_bridges,
        n_discarded=n_discarded, n_crossings=n_crossings,
        coverage_pct=coverage_pct, avg_stroke_len=avg_stroke_len,
        total_skel_px=total_skel_px,
    )


def _stroke_paths_v2(
    arr: "_np.ndarray",   # float [0,1], pre-blurred, dark=stroke
    sensitivity: float,   # 1–10: higher → more / fainter strokes
    min_arc: int,         # user-facing min path length (px)
    simplify_eps: float,  # base RDP epsilon (will be reduced for strokes)
) -> dict:
    """
    Advanced stroke tracer for sketch / line-art images.

    Stages
    ------
    1. Normalise + CLAHE contrast enhancement (faint strokes become visible)
    2. Sauvola adaptive binarisation ∪ global Otsu (captures thin AND bold strokes)
    3. Morphological cleanup (close 1-px gaps, remove noise blobs)
    4. Skeletonise → 1-pixel wide centrelines
    5. Graph construction (segment nodes at junctions and endpoints)
    6. Two-pass greedy junction merging (tight 25°, then relaxed 40°)
    7. Two-pass gap bridging (strict 30°/30 px, then relaxed 45°/20 px)
    8. Lenient length filter (1/4 of user setting) → preserve small details
    9. Gentle RDP (1/5 of other modes) + 1-iter Chaikin smoothing

    Returns dict with paths, all diagnostic images, and coverage metrics.
    """
    h, w = arr.shape

    # ── 1. Normalise + CLAHE ─────────────────────────────────────────────────
    p2, p98   = float(_np.percentile(arr, 2)), float(_np.percentile(arr, 98))
    arr_norm  = _np.clip((arr - p2) / max(p98 - p2, 1e-6), 0.0, 1.0)
    arr_clahe = _sk_exp.equalize_adapthist(arr_norm, clip_limit=0.015)
    cleaned_b64 = _encode_png((arr_clahe * 255).astype(_np.uint8))

    # ── 2. Binarise ──────────────────────────────────────────────────────────
    # Sauvola k: higher sensitivity → lower k → more strokes captured
    k_sauvola = max(0.04, 0.35 - (sensitivity - 1.0) * 0.034)  # 1→0.35, 10→0.04
    win_size  = int(max(15, min(51, (h + w) // 55)) | 1)        # odd, ≤51

    try:
        t_sauvola = _sk_filters.threshold_sauvola(arr_clahe, window_size=win_size, k=k_sauvola)
        binary    = arr_clahe < t_sauvola
    except Exception:
        t_sauvola = float(_sk_filters.threshold_otsu(arr_clahe))
        binary    = arr_clahe < float(t_sauvola)

    # Union with global Otsu: bold strokes are never missed
    try:
        t_otsu = float(_sk_filters.threshold_otsu(arr_clahe))
    except Exception:
        t_otsu = 0.5
    binary = binary | (arr_clahe < t_otsu)

    # ── 3. Morphological cleanup ─────────────────────────────────────────────
    binary   = _sk_morph.closing(binary, _sk_morph.disk(1))
    min_blob = max(4, min_arc // 8)
    binary   = _sk_morph.remove_small_objects(binary.astype(bool), max_size=max(0, min_blob - 1))
    binary_b64 = _encode_png((binary.astype(_np.uint8)) * 255)

    # ── 4. Skeletonise ───────────────────────────────────────────────────────
    skel     = _sk_morph.skeletonize(binary)
    skel_b64 = _encode_png((skel.astype(_np.uint8)) * 255)

    ys, xs = _np.where(skel)
    total_skel_px = int(len(ys))
    if total_skel_px == 0:
        empty = skel_b64
        return {
            'paths': [], 'cleaned': cleaned_b64, 'binary': binary_b64,
            'skeleton': empty, 'segments': empty, 'merged': empty,
            'n_raw_segments': 0, 'n_merges': 0, 'n_bridges': 0,
            'n_discarded': 0, 'coverage_pct': 0.0,
            'avg_stroke_len': 0.0, 'total_skel_px': 0,
        }

    pix_set: set = set(zip(ys.tolist(), xs.tolist()))

    def nbrs8(r: int, c: int) -> list:
        return [(r + dr, c + dc)
                for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                if (dr, dc) != (0, 0) and (r + dr, c + dc) in pix_set]

    deg: dict = {p: len(nbrs8(*p)) for p in pix_set}
    node_set: set = {p for p, d in deg.items() if d != 2}
    if not node_set:
        node_set = {min(pix_set)}

    # ── 5. Graph: trace segments between node pairs ──────────────────────────
    visited_edges: set = set()
    raw_segs: list     = []

    for node in sorted(node_set):
        for nbr in sorted(nbrs8(*node)):
            ekey = (min(node, nbr), max(node, nbr))
            if ekey in visited_edges:
                continue
            visited_edges.add(ekey)
            path: list = [node, nbr]
            prev, cur  = node, nbr
            while cur not in node_set:
                cands = [n for n in nbrs8(*cur) if n != prev]
                if not cands:
                    break
                nxt = cands[0]
                visited_edges.add((min(cur, nxt), max(cur, nxt)))
                prev, cur = cur, nxt
                path.append(cur)
            raw_segs.append(path)

    n_raw    = len(raw_segs)
    segs_b64 = _render_paths_img(h, w, raw_segs)

    # ── 6. Two-pass junction merging ─────────────────────────────────────────
    WIN = 16

    def seg_dir(seg: list, at_start: bool, win: int = WIN) -> "_np.ndarray":
        pts = _np.array(seg[:win] if at_start else seg[-win:], dtype=float)
        if len(pts) < 2:
            return _np.zeros(2)
        v = (pts[-1] - pts[0]) if at_start else (pts[0] - pts[-1])
        m = float(_np.linalg.norm(v))
        return v / m if m > 1e-9 else _np.zeros(2)

    segs: list  = [list(s) for s in raw_segs]
    active: set = set(range(len(segs)))
    n_merges    = 0

    # Pass 1: tight collinearity (≤25°), pass 2: relaxed (≤40°)
    for cos_junc in (_np.cos(_np.radians(25)), _np.cos(_np.radians(40))):
        changed = True
        while changed:
            changed = False
            nm: dict = {}
            for i in active:
                s = segs[i]
                if not s:
                    continue
                nm.setdefault(s[0],  []).append((i, True))
                if len(s) > 1:
                    nm.setdefault(s[-1], []).append((i, False))

            for node, entries in nm.items():
                entries = [(i, a) for i, a in entries if i in active]
                if len(entries) < 2:
                    continue
                best_cos, best_pair = cos_junc, None
                for a in range(len(entries)):
                    i, ia = entries[a]
                    di = seg_dir(segs[i], ia)
                    for b in range(a + 1, len(entries)):
                        j, ja = entries[b]
                        dj = seg_dir(segs[j], ja)
                        cv = float(-_np.dot(di, dj))
                        if cv > best_cos:
                            best_cos, best_pair = cv, (a, b)
                if best_pair is None:
                    continue
                a_idx, b_idx = best_pair
                i, ia = entries[a_idx]
                j, ja = entries[b_idx]
                si = segs[i] if not ia else list(reversed(segs[i]))
                sj = segs[j][1:] if not ja else list(reversed(segs[j]))[1:]
                segs[i] = si + sj
                active.discard(j)
                n_merges += 1
                changed = True
                break

    # ── 7. Two-pass gap bridging ─────────────────────────────────────────────
    n_bridges = 0

    for pass_cos, pass_gap in (
        (_np.cos(_np.radians(30)), 30),
        (_np.cos(_np.radians(45)), 20),
    ):
        changed = True
        while changed:
            changed = False
            eps_info: list = []
            for i in active:
                s = segs[i]
                if len(s) < 2:
                    continue
                eps_info.append((i, True,  _np.array(s[0],  float), seg_dir(s, True)))
                eps_info.append((i, False, _np.array(s[-1], float), seg_dir(s, False)))

            best_score, best_m = -_np.inf, None
            for a in range(len(eps_info)):
                i, ia, pi, di = eps_info[a]
                di_tail = -di if ia else di
                for b in range(a + 1, len(eps_info)):
                    j, ja, pj, dj = eps_info[b]
                    if i == j:
                        continue
                    dj_tail = -dj if ja else dj
                    gap     = pj - pi
                    gap_len = float(_np.linalg.norm(gap))
                    if gap_len < 1.0 or gap_len > pass_gap:
                        continue
                    gd      = gap / gap_len
                    cos_val = min(float(_np.dot(di_tail,  gd)),
                                  float(_np.dot(dj_tail, -gd)))
                    if cos_val < pass_cos:
                        continue
                    score = cos_val - gap_len / pass_gap * 0.3
                    if score > best_score:
                        best_score, best_m = score, (i, ia, j, ja)

            if best_m is None:
                break
            i, ia, j, ja = best_m
            si = segs[i] if not ia else list(reversed(segs[i]))
            sj = segs[j][1:] if not ja else list(reversed(segs[j]))[1:]
            segs[i] = si + sj
            active.discard(j)
            n_bridges += 1
            changed = True

    merged_b64 = _render_paths_img(h, w, [segs[i] for i in active])

    # ── 8. Length filter + gentle RDP + Chaikin smoothing ───────────────────
    eff_min     = max(3, min_arc // 4)          # lenient: keep small real features
    eps_rdp     = max(0.08, simplify_eps / 5.0) # 5× gentler than other modes
    n_discarded = 0
    covered_px  = 0
    result: list = []

    for i in active:
        seg = segs[i]
        if len(seg) < 2:
            continue
        pts = _np.array(seg, dtype=float)
        if _contour_perimeter(pts) < eff_min:
            n_discarded += 1
            continue
        covered_px += len(seg)
        idx      = _rdp(pts, eps_rdp)
        simp     = pts[idx]
        smoothed = _chaikin(simp, iters=1)  # one pass rounds corners gently
        if len(smoothed) >= 2:
            result.append(smoothed.tolist())

    result.sort(key=lambda p: -len(p))
    result = result[:1500]

    coverage_pct   = round(covered_px / max(total_skel_px, 1) * 100, 1)
    avg_stroke_len = round(covered_px / max(len(result), 1), 1)

    return {
        'paths':          result,
        'cleaned':        cleaned_b64,
        'binary':         binary_b64,
        'skeleton':       skel_b64,
        'segments':       segs_b64,
        'merged':         merged_b64,
        'n_raw_segments': n_raw,
        'n_merges':       n_merges,
        'n_bridges':      n_bridges,
        'n_discarded':    n_discarded,
        'coverage_pct':   coverage_pct,
        'avg_stroke_len': avg_stroke_len,
        'total_skel_px':  total_skel_px,
    }


# kept for reference — replaced by _stroke_paths_v2
def _stroke_paths(
    arr: "_np.ndarray",
    sensitivity: float,
    min_arc: int,
    simplify_eps: float,
    invert: bool,
) -> "tuple[str, list]":
    """
    Skeleton-based stroke tracer for sketch / line-art images.

    Pipeline:
      1. Otsu binarize (sensitivity offsets the threshold to include faint lines)
      2. Remove tiny blobs, close small gaps in strokes
      3. Skeletonize → 1-pixel wide centerlines
      4. Build pixel graph (segments between junction/endpoint nodes)
      5. Greedy junction merging (pair most-collinear edges at every branch)
      6. Gap bridging (connect nearby compatible open endpoints)
      7. Filter by arc length + RDP simplification

    Returns (skeleton_b64_image, list_of_simplified_paths).
    """
    # ── 1. Binarize ───────────────────────────────────────────────────────────
    try:
        t = _sk_filters.threshold_otsu(arr)
    except Exception:
        t = 0.5
    # sensitivity 1–10: higher → lower threshold → more (fainter) strokes included
    offset = (sensitivity - 5.5) * (-0.04)   # maps 1→+0.18, 10→-0.18
    binary = (arr < (t + offset))
    if invert:
        binary = ~binary

    # ── 2. Morphological cleanup ──────────────────────────────────────────────
    min_blob = max(6, min_arc // 5)
    binary   = _sk_morph.remove_small_objects(binary.astype(bool), max_size=min_blob - 1)
    binary   = _sk_morph.closing(binary, _sk_morph.disk(1))

    # ── 3. Skeletonize ────────────────────────────────────────────────────────
    skel      = _sk_morph.skeletonize(binary)
    skel_b64  = _encode_png((skel.astype(_np.uint8)) * 255)

    ys, xs = _np.where(skel)
    if len(ys) == 0:
        return skel_b64, []

    pix_set: set = set(zip(ys.tolist(), xs.tolist()))

    def nbrs8(r: int, c: int) -> list:
        return [(r + dr, c + dc)
                for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                if (dr, dc) != (0, 0) and (r + dr, c + dc) in pix_set]

    deg: dict = {p: len(nbrs8(*p)) for p in pix_set}
    # "Nodes" = pixels that are NOT ordinary pass-through (degree ≠ 2)
    node_set: set = {p for p, d in deg.items() if d != 2}
    if not node_set:
        node_set = {min(pix_set)}

    # ── 4. Trace path segments between node pairs ─────────────────────────────
    visited_edges: set = set()
    raw_segs: list     = []

    for node in sorted(node_set):
        for nbr in sorted(nbrs8(*node)):
            ekey = (min(node, nbr), max(node, nbr))
            if ekey in visited_edges:
                continue
            visited_edges.add(ekey)

            path: list = [node, nbr]
            prev, cur = node, nbr
            while cur not in node_set:
                cands = [n for n in nbrs8(*cur) if n != prev]
                if not cands:
                    break
                nxt = cands[0]
                visited_edges.add((min(cur, nxt), max(cur, nxt)))
                prev, cur = cur, nxt
                path.append(cur)
            raw_segs.append(path)

    # ── 5. Greedy junction merging ────────────────────────────────────────────
    # At each branch node, repeatedly find the most-collinear pair of meeting
    # segments and fuse them into one long path.  This is the key step that
    # converts many short fragments into long natural strokes.
    WIN = 14   # pixels used to estimate direction at each endpoint

    def seg_dir(seg: list, at_start: bool) -> "_np.ndarray":
        pts = _np.array(seg[:WIN] if at_start else seg[-WIN:], dtype=float)
        if len(pts) < 2:
            return _np.zeros(2)
        v = (pts[-1] - pts[0]) if at_start else (pts[0] - pts[-1])
        m = float(_np.linalg.norm(v))
        return v / m if m > 1e-9 else _np.zeros(2)

    segs: list  = [list(s) for s in raw_segs]
    active: set = set(range(len(segs)))
    COS_JUNC    = _np.cos(_np.radians(30))   # within 30° → merge at junction

    changed = True
    while changed:
        changed = False
        # Rebuild node→segment map each pass (cheap compared to correctness)
        nm: dict = {}
        for i in active:
            s = segs[i]
            if not s:
                continue
            nm.setdefault(s[0],  []).append((i, True))
            if len(s) > 1:
                nm.setdefault(s[-1], []).append((i, False))

        for node, entries in nm.items():
            entries = [(i, a) for i, a in entries if i in active]
            if len(entries) < 2:
                continue

            # Find the pair of segments whose outgoing directions are most anti-parallel
            # (i.e., they are most nearly collinear through this node)
            best_cos, best_pair = COS_JUNC, None
            for a in range(len(entries)):
                i, ia = entries[a]
                di = seg_dir(segs[i], ia)
                for b in range(a + 1, len(entries)):
                    j, ja = entries[b]
                    dj = seg_dir(segs[j], ja)
                    cos_val = float(-_np.dot(di, dj))  # anti-parallel → collinear pass-through
                    if cos_val > best_cos:
                        best_cos, best_pair = cos_val, (a, b)

            if best_pair is None:
                continue

            a_idx, b_idx = best_pair
            i, ia = entries[a_idx]
            j, ja = entries[b_idx]

            # Fuse: orient seg_i so its tail is at `node`, then append seg_j's body
            si = segs[i] if not ia else list(reversed(segs[i]))
            sj = segs[j][1:] if not ja else list(reversed(segs[j]))[1:]
            segs[i] = si + sj
            active.discard(j)
            changed = True
            break   # rebuild map and restart

    # ── 6. Gap bridging ───────────────────────────────────────────────────────
    # Connect open endpoints that are spatially close AND directionally compatible.
    # This handles strokes that are nearly touching or have tiny gaps after skeletonize.
    GAP_MAX  = 18                              # max bridge distance in pixels
    COS_GAP  = _np.cos(_np.radians(35))        # direction alignment threshold

    changed = True
    while changed:
        changed = False
        eps_info: list = []
        for i in active:
            s = segs[i]
            if len(s) < 2:
                continue
            eps_info.append((i, True,  _np.array(s[0],  float), seg_dir(s, True)))
            eps_info.append((i, False, _np.array(s[-1], float), seg_dir(s, False)))

        best_score, best_m = -_np.inf, None

        for a in range(len(eps_info)):
            i, ia, pi, di = eps_info[a]
            di_tail = -di if ia else di   # direction leaving this endpoint along the stroke

            for b in range(a + 1, len(eps_info)):
                j, ja, pj, dj = eps_info[b]
                if i == j:
                    continue
                dj_tail = -dj if ja else dj

                gap_vec = pj - pi
                gap_len = float(_np.linalg.norm(gap_vec))
                if gap_len < 1.0 or gap_len > GAP_MAX:
                    continue
                gd = gap_vec / gap_len

                # Both tails should be pointing toward each other across the gap
                cos_i = float(_np.dot(di_tail,  gd))
                cos_j = float(_np.dot(dj_tail, -gd))
                cos_val = min(cos_i, cos_j)
                if cos_val < COS_GAP:
                    continue

                score = cos_val - gap_len / GAP_MAX * 0.25
                if score > best_score:
                    best_score, best_m = score, (i, ia, j, ja)

        if best_m is None:
            break
        i, ia, j, ja = best_m
        si = segs[i] if not ia else list(reversed(segs[i]))
        sj = segs[j][1:] if not ja else list(reversed(segs[j]))[1:]
        segs[i] = si + sj
        active.discard(j)
        changed = True

    # ── 7. Filter by arc length + RDP simplification ──────────────────────────
    result: list = []
    for i in active:
        seg = segs[i]
        if len(seg) < 2:
            continue
        pts = _np.array(seg, dtype=float)
        if _contour_perimeter(pts) < min_arc:
            continue
        idx        = _rdp(pts, simplify_eps)
        simplified = pts[idx]
        if len(simplified) >= 2:
            result.append(simplified.tolist())

    result.sort(key=lambda p: -len(p))
    return skel_b64, result[:800]


@app.post('/photo-to-dxf/analyze', summary='Analyze image and recommend a tracing mode')
async def photo_analyze(
    file:   UploadFile = File(...),
    prompt: str        = Form('', description='Optional free-text intent from the user'),
):
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Image too large (max 20 MB)')
    try:
        img = _PIL.open(_io.BytesIO(raw)).convert('L')
    except Exception as exc:
        raise HTTPException(400, f'Cannot open image: {exc}')

    w, h = img.size
    if max(w, h) > 600:
        sf = 600 / max(w, h)
        img = img.resize((int(w * sf), int(h * sf)), _PIL.LANCZOS)

    arr    = _np.asarray(img, dtype=float) / 255.0
    result = _analyze_image(arr)
    if prompt.strip():
        result = _apply_prompt_override(result, prompt.strip())
    return JSONResponse(result)


class AiRecommendRequest(BaseModel):
    image_type:   str
    edge_density: float
    contrast:     float
    prompt:       str = ''


@app.post('/ai-recommend', summary='LLM-powered tracing mode recommendation')
async def ai_recommend(body: AiRecommendRequest):
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        return JSONResponse({'source': 'none', 'error': 'OPENAI_API_KEY not configured'})

    _SYSTEM = (
        'You are an expert CNC fabrication assistant. '
        'Given image analysis data and an optional user intent, recommend the best tracing mode '
        'from: accurate, contour_art, stroke, halftone.\n'
        '- accurate: logos, silhouettes, bold line art with clear edges\n'
        '- contour_art: portraits, landscapes, tonal images with gradients\n'
        '- stroke: hand-drawn sketches, pen/ink, single-stroke line art\n'
        '- halftone: portraits or photos that will be engraved as dot patterns\n\n'
        'Respond ONLY with a JSON object (no markdown) with these keys:\n'
        '  recommended_mode: string (one of the four modes)\n'
        '  confidence: number 0.0–1.0\n'
        '  explanation: string (1–2 sentences, plain language)\n'
        '  reasoning: string (1 sentence on why this mode fits)\n'
        '  param_hints: object with optional keys simplify, min_length, sensitivity (numbers)'
    )

    _USER = (
        f'Image type: {body.image_type}\n'
        f'Edge density: {body.edge_density:.3f}\n'
        f'Contrast: {body.contrast:.3f}\n'
        f'User intent: {body.prompt or "(none provided)"}'
    )

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model='gpt-4o-mini',
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': _SYSTEM},
                {'role': 'user',   'content': _USER},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or '{}'
        data = json.loads(raw)
        data['source'] = 'ai'
        # Ensure required keys exist
        data.setdefault('recommended_mode', 'accurate')
        data.setdefault('confidence', 0.5)
        data.setdefault('explanation', '')
        data.setdefault('reasoning', '')
        data.setdefault('param_hints', {})
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({'source': 'none', 'error': str(exc)})


@app.post('/photo-to-dxf/halftone', summary='Convert image to halftone circle grid')
async def photo_halftone(
    file:       UploadFile = File(...),
    density:    int        = Form(30,   description='Grid cells along longer axis (10–80)'),
    min_radius: float      = Form(0.5,  description='Minimum circle radius in px'),
    max_radius: float      = Form(8.0,  description='Maximum circle radius in px'),
    contrast:   float      = Form(1.5,  description='Contrast boost before mapping (0.5–3.0)'),
    blur:       float      = Form(1.0,  description='Pre-blur radius (0–5)'),
    invert:     bool       = Form(False,description='Invert: bright areas → large circles'),
    placement_mode: str    = Form('organic_density', description='organic_density, hex_packing, or flow_field'),
    randomness: float      = Form(0.55, description='Organic jitter/randomness (0-1)'),
    density_sensitivity: float = Form(1.25, description='Brightness-to-density response (0.35-3.0)'),
):
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Image too large (max 20 MB)')
    try:
        img = _PIL.open(_io.BytesIO(raw)).convert('L')
    except Exception as exc:
        raise HTTPException(400, f'Cannot open image: {exc}')

    # Resize to max 1400px (same as trace endpoint)
    w, h = img.size
    if max(w, h) > 1400:
        sf = 1400 / max(w, h)
        img = img.resize((int(w * sf), int(h * sf)), _PIL.LANCZOS)
        w, h = img.size

    if blur > 0.2:
        img = img.filter(_PILFilter.GaussianBlur(radius=blur))

    arr = _np.asarray(img, dtype=float) / 255.0

    density    = max(5,   min(100, density))
    min_radius = max(0.1, min(20.0, min_radius))
    max_radius = max(min_radius + 0.1, min(50.0, max_radius))
    contrast   = max(0.1, min(5.0,  contrast))
    randomness = max(0.0, min(1.0, randomness))
    density_sensitivity = max(0.35, min(3.0, density_sensitivity))

    circles = _halftone_grid(
        arr, density, min_radius, max_radius, contrast, invert,
        placement_mode=placement_mode,
        randomness=randomness,
        density_sensitivity=density_sensitivity,
    )

    # Build a preview image: draw filled circles on white canvas
    import math as _math2
    canvas = (_np.ones((h, w), dtype=_np.uint8) * 255)
    for cr, cc, r in circles:
        ri, ci, ri_px = int(cr), int(cc), max(1, int(r))
        rr0, rr1 = max(0, ri - ri_px - 1), min(h, ri + ri_px + 2)
        cc0, cc1 = max(0, ci - ri_px - 1), min(w, ci + ri_px + 2)
        for rp in range(rr0, rr1):
            for cp in range(cc0, cc1):
                if _math2.hypot(rp - cr, cp - cc) <= r:
                    canvas[rp, cp] = 0
    preview_b64 = _encode_png(canvas)
    metrics = _halftone_fabrication_metrics(circles, w, h, min_radius, max_radius)
    heatmap_b64 = _halftone_density_heatmap(arr, contrast, invert, density_sensitivity)

    return JSONResponse({
        'circles':      circles,
        'preview_image': preview_b64,
        'density_heatmap': heatmap_b64,
        'n_circles':    len(circles),
        'image_width':  w,
        'image_height': h,
        'placement_mode': placement_mode,
        **metrics,
    })


class HalftoneExportRequest(BaseModel):
    circles:      List[List[float]]  # [[row, col, radius], ...]
    image_width:  int
    image_height: int
    scale:        float = 1.0        # mm per pixel
    filename:     str   = 'halftone.dxf'


@app.post('/photo-to-dxf/export-halftone', summary='Export halftone circles as DXF')
async def export_halftone(body: HalftoneExportRequest, background_tasks: BackgroundTasks):
    import ezdxf

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    h, s = body.image_height, body.scale
    for entry in body.circles:
        if len(entry) < 3:
            continue
        row, col, radius = float(entry[0]), float(entry[1]), float(entry[2])
        x = col    * s
        y = (h - row) * s   # flip Y so DXF origin is bottom-left
        r = radius * s
        if r > 0:
            msp.add_circle((x, y), radius=r)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    doc.saveas(tmp_path)
    background_tasks.add_task(os.unlink, tmp_path)

    return FileResponse(
        tmp_path,
        media_type='application/octet-stream',
        filename=body.filename,
        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'},
    )


@app.post('/photo-to-dxf/trace', summary='Detect vector contours from an image (two modes)')
async def photo_trace(
    file:        UploadFile = File(...,   description='Image file (JPG, PNG, BMP, WebP)'),
    mode:        str        = Form('accurate', description="'accurate' (Canny) or 'contour_art' (iso-contours)"),
    blur:        float      = Form(1.5,   description='Pre-blur radius 0–5 (denoise)'),
    sensitivity: float      = Form(5.0,   description='Edge sensitivity 1–10 (accurate) or contour levels (contour_art)'),
    simplify:    float      = Form(2.0,   description='RDP path simplification 0–15'),
    min_length:  int        = Form(15,    description='Minimum contour length in pixels 5–80'),
    invert:      bool       = Form(False, description='Invert (dark subject on light background)'),
):
    """
    Two tracing modes:

    **accurate** — Canny edge detection pipeline:
      grayscale → blur → Canny → dilation → find_contours → RDP

    **contour_art** — Iso-contour / topographic pipeline:
      grayscale → blur → find_contours at N evenly-spaced levels → RDP
      Produces layered topographic-style art; `sensitivity` controls the number of bands.
    """
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Image too large (max 20 MB)')

    try:
        img = _PIL.open(_io.BytesIO(raw)).convert('L')
    except Exception as exc:
        raise HTTPException(400, f'Cannot open image: {exc}')

    # ── 1. Resize ────────────────────────────────────────────────────────────
    w, h = img.size
    if max(w, h) > 1400:
        sf = 1400 / max(w, h)
        img = img.resize((int(w * sf), int(h * sf)), _PIL.LANCZOS)
        w, h = img.size

    arr = _np.asarray(img, dtype=float) / 255.0
    if invert:
        arr = 1.0 - arr

    # ── 2. Pre-process: CLAHE + bilateral edge-preserving denoise ────────────
    # stroke mode has its own CLAHE + bilateral internally; skip here to avoid
    # double-processing.  For accurate / contour_art, bilateral replaces the
    # old Gaussian blur: it smooths noise without smearing edge boundaries,
    # so subsequent edge detection sees sharper transitions.
    if mode != 'stroke':
        arr = _sk_exp.equalize_adapthist(arr, clip_limit=0.018)
        if blur > 0.2:
            sigma_sp = max(1.0, blur * 1.8)
            arr = _sk_rest.denoise_bilateral(
                arr, sigma_color=0.10, sigma_spatial=sigma_sp, channel_axis=None,
            )

    cleaned_b64 = _encode_png((_np.clip(arr, 0, 1) * 255).astype(_np.uint8))

    # ── 3. Mode-specific pipeline ────────────────────────────────────────────
    stroke_meta: dict = {}
    if mode == 'stroke':
        # High-Fidelity stroke tracer: optimal junction pairing + global assembly
        stroke_r    = _hifi_stroke_paths(arr, sensitivity, min_length, simplify * 0.5 + 0.2)
        cleaned_b64 = stroke_r['cleaned']
        edges_b64   = stroke_r['skeleton']
        out         = stroke_r['paths']
        stroke_meta = {k: v for k, v in stroke_r.items()
                       if k not in ('paths', 'cleaned', 'skeleton')}

    elif mode == 'contour_art':
        # Iso-contour topographic mode
        n_levels = max(3, min(15, round(sensitivity * 1.3)))
        levels   = _np.linspace(0.12, 0.88, n_levels)

        raw_contours: list = []
        for level in levels:
            raw_contours.extend(_sk_measure.find_contours(arr, float(level)))

        quantized = (_np.floor(arr * n_levels) / n_levels * 255).astype(_np.uint8)
        edges_b64 = _encode_png(quantized)

        base_eps = simplify * 0.5 + 0.2
        out = []
        for c in raw_contours:
            ca    = _np.array(c)
            perim = _contour_perimeter(ca)
            if perim < min_length:
                continue
            idx        = _adaptive_rdp(ca, base_eps)
            simplified = ca[idx]
            if len(simplified) >= 2:
                out.append(simplified.tolist())
        out.sort(key=lambda c: -len(c))
        out = out[:600]

    else:
        # Accurate: Canny + Scharr gradient combined edge detection pipeline
        sigma = max(0.5, (11.0 - sensitivity) * 0.38)

        # Canny: spatially clean, well-localised strong edges
        edges_canny = _sk_feature.canny(arr, sigma=sigma)

        # Scharr gradient magnitude: catches faint edges that fall below Canny's
        # hysteresis thresholds (thin strokes, low-contrast transitions).
        gx = _sk_filters.scharr_h(arr)
        gy = _sk_filters.scharr_v(arr)
        grad_mag    = _np.hypot(gx, gy)
        grad_thresh = float(_np.percentile(grad_mag, max(82.0, 100.0 - sensitivity * 1.8)))
        edges_grad  = grad_mag > grad_thresh

        edges     = edges_canny | edges_grad
        edges_b64 = _encode_png((edges * 255).astype(_np.uint8))

        # Close broken edge segments (connects short gaps in faint lines),
        # then open to remove isolated single-pixel noise speckle.
        edges = _sk_morph.closing(edges, _sk_morph.disk(1))
        edges = _sk_morph.opening(edges, _sk_morph.disk(1))

        dilated      = _sk_morph.dilation(edges, _sk_morph.square(2))
        raw_contours = _sk_measure.find_contours(dilated.astype(float), 0.5)

        base_eps = simplify * 0.5 + 0.2
        out = []
        for c in raw_contours:
            ca    = _np.array(c)
            perim = _contour_perimeter(ca)
            if perim < min_length:
                continue
            # Reject tight noise clusters: mean step < 1.2 px AND barely above
            # min_length indicates a jagged rasterisation artefact, not a real edge.
            steps = _np.linalg.norm(_np.diff(ca, axis=0), axis=1)
            if steps.size > 0 and float(steps.mean()) < 1.2 and perim < min_length * 1.5:
                continue
            idx        = _adaptive_rdp(ca, base_eps)
            simplified = ca[idx]
            if len(simplified) >= 2:
                out.append(simplified.tolist())
        out.sort(key=lambda c: -len(c))
        out = out[:600]

    total_points = sum(len(c) for c in out)

    response: dict = {
        'contours':      out,
        'cleaned_image': cleaned_b64,
        'edges_image':   edges_b64,
        'preview_image': edges_b64,
        'n_contours':    len(out),
        'total_points':  total_points,
        'image_width':   w,
        'image_height':  h,
        'mode_used':     mode,
    }
    if stroke_meta:
        response.update(stroke_meta)
    return JSONResponse(response)


class PhotoExportRequest(BaseModel):
    contours:     List[List[List[float]]]
    image_width:  int
    image_height: int
    scale:        float = 1.0
    filename:     str   = 'traced.dxf'


@app.post('/photo-to-dxf/export', summary='Export traced contours as a DXF file')
async def photo_export(body: PhotoExportRequest, background_tasks: BackgroundTasks):
    import ezdxf

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    h, s = body.image_height, body.scale
    for contour in body.contours:
        if len(contour) < 2:
            continue
        pts = [(float(p[1]) * s, float(h - p[0]) * s) for p in contour]
        msp.add_lwpolyline(pts, close=True)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    doc.saveas(tmp_path)
    background_tasks.add_task(os.unlink, tmp_path)

    return FileResponse(
        tmp_path,
        media_type='application/octet-stream',
        filename=body.filename,
        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'},
    )


# ── One-Line Drawing ─────────────────────────────────────────────────────────

_SKEL_OFFSETS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]


def _trace_skel_chains(skel: "_np.ndarray", step: int) -> list:
    """Extract ordered pixel chains from a skeletonized image, downsampled by step."""
    from skimage.measure import label as _lbl
    labeled = _lbl(skel, connectivity=2)
    chains: list = []

    for cid in range(1, int(labeled.max()) + 1):
        ys, xs = _np.where(labeled == cid)
        if len(ys) < 2:
            continue

        pix_set: set = set(zip(ys.tolist(), xs.tolist()))

        # Find an endpoint (degree-1 pixel) to start the walk
        start = None
        for p in pix_set:
            if sum(1 for dr, dc in _SKEL_OFFSETS if (p[0]+dr, p[1]+dc) in pix_set) == 1:
                start = p
                break
        if start is None:
            start = (int(ys[0]), int(xs[0]))

        visited: set = {start}
        chain: list = [list(start)]
        cur = start

        while True:
            cands = [(cur[0]+dr, cur[1]+dc)
                     for dr, dc in _SKEL_OFFSETS
                     if (cur[0]+dr, cur[1]+dc) in pix_set
                     and (cur[0]+dr, cur[1]+dc) not in visited]
            if not cands:
                break
            # Prefer continuing in same direction
            if len(chain) >= 2:
                dr_p = cur[0] - chain[-2][0]
                dc_p = cur[1] - chain[-2][1]
                best_nb = min(cands,
                              key=lambda p: abs(p[0]-cur[0]-dr_p) + abs(p[1]-cur[1]-dc_p))
            else:
                best_nb = cands[0]
            visited.add(best_nb)
            chain.append(list(best_nb))
            cur = best_nb

        if step > 1 and len(chain) > 2:
            sampled = chain[::step]
            if sampled[-1] != chain[-1]:
                sampled.append(chain[-1])
            chain = sampled

        if len(chain) >= 2:
            chains.append(chain)

    return chains


def _greedy_connect_chains(chains: list, jump_penalty: float) -> list:
    """
    Greedy nearest-neighbor tour through all chains.

    Returns a list of ``(points, is_jump)`` segment tuples.
    Real chain segments have ``is_jump=False``; the two-point connector
    between consecutive chains has ``is_jump=True``.
    """
    import math

    remaining = list(range(len(chains)))
    start_i = max(remaining, key=lambda i: len(chains[i]))
    remaining.remove(start_i)

    segments: list = [(list(chains[start_i]), False)]

    def _end_heading(chain: list, from_end: bool) -> tuple:
        if len(chain) < 2:
            return (0.0, 0.0)
        p1, p2 = (chain[-2], chain[-1]) if from_end else (chain[1], chain[0])
        dr, dc = p2[0] - p1[0], p2[1] - p1[1]
        d = math.hypot(dr, dc)
        return (dr / d, dc / d) if d > 1e-9 else (0.0, 0.0)

    cur_end  = segments[-1][0][-1]
    cur_head = _end_heading(chains[start_i], True)

    while remaining:
        best_score, best_idx, best_rev = float('inf'), -1, False
        for i in remaining:
            c = chains[i]
            for rev in (False, True):
                entry = c[0] if not rev else c[-1]
                d = math.hypot(entry[0] - cur_end[0], entry[1] - cur_end[1])
                if jump_penalty > 0 and d > 1e-9:
                    dir_r = (entry[0] - cur_end[0]) / d
                    dir_c = (entry[1] - cur_end[1]) / d
                    cos_a = cur_head[0] * dir_r + cur_head[1] * dir_c
                    score = d * (1.0 + jump_penalty * max(0.0, -cos_a) * 1.5)
                else:
                    score = d
                if score < best_score:
                    best_score, best_idx, best_rev = score, i, rev

        chosen = list(chains[best_idx])
        if best_rev:
            chosen = list(reversed(chosen))

        # Two-point jump connector: [current_end → chosen_start]
        segments.append(([cur_end, chosen[0]], True))
        segments.append((chosen, False))

        cur_end  = chosen[-1]
        cur_head = _end_heading(chosen, True)
        remaining.remove(best_idx)

    return segments


@app.post('/photo-to-dxf/one-line', summary='Generate one-line drawing from image')
async def photo_one_line(
    file:         UploadFile = File(...,    description='Image file'),
    detail:       float      = Form(5.0,    description='Detail level 1–10'),
    simplify:     float      = Form(3.0,    description='RDP epsilon'),
    jump_penalty: float      = Form(0.5,    description='Jump direction penalty 0–1'),
    blur:         float      = Form(1.0,    description='Pre-blur 0–5'),
    invert:       bool       = Form(False,  description='Invert dark/light'),
) -> JSONResponse:
    """Convert an image to a single continuous line path for plotter/CNC engraving."""
    import math
    from skimage.filters import threshold_sauvola, threshold_otsu
    from skimage.morphology import skeletonize, closing, disk, remove_small_objects
    from PIL import Image as _PILImg, ImageDraw as _IDraw

    contents = await file.read()
    pil_img  = _PIL.open(_io.BytesIO(contents)).convert('L')

    max_dim = 600
    iw, ih  = pil_img.width, pil_img.height
    if max(iw, ih) > max_dim:
        s = max_dim / max(iw, ih)
        pil_img = pil_img.resize((int(iw * s), int(ih * s)), _PIL.LANCZOS)

    w, h = pil_img.width, pil_img.height
    arr  = _np.array(pil_img, dtype=float) / 255.0

    enhanced = _sk_exp.equalize_adapthist(arr, clip_limit=0.015)
    sigma_sp = max(0.5, 1.8 - (detail - 1.0) * 0.08)
    denoised = _sk_rest.denoise_bilateral(enhanced, sigma_color=0.10,
                                          sigma_spatial=sigma_sp, channel_axis=None)
    if blur > 0:
        denoised = _sk_filters.gaussian(denoised, sigma=blur * 0.5)

    k_sauv = max(0.04, 0.28 - (detail - 5.0) * 0.02)
    win    = int(max(15, min(51, (h + w) // 55)) | 1)
    b_sauv = denoised < threshold_sauvola(denoised, window_size=win, k=k_sauv)
    b_otsu = denoised < threshold_otsu(denoised)
    binary = b_sauv | b_otsu
    if invert:
        binary = ~binary

    min_blob = max(2, int(h * w // 80000))
    binary   = remove_small_objects(binary, max_size=max(0, min_blob - 1))
    binary   = closing(binary, disk(1))
    skel     = skeletonize(binary)

    step   = max(1, int(11 - detail))
    chains = _trace_skel_chains(skel, step)
    if not chains:
        return JSONResponse({'error': 'No paths found — try adjusting Detail or Invert.'}, status_code=422)

    raw_segments = _greedy_connect_chains(chains, jump_penalty)

    # Apply RDP per real segment; concatenate into a flat path tracking jump indices.
    flat_path:    list = []
    jump_indices: list = []   # i where flat_path[i] → flat_path[i+1] is a jump connector

    for pts, is_jump in raw_segments:
        if not pts:
            continue
        if not is_jump and simplify > 0 and len(pts) > 2:
            pts_np   = _np.array(pts, dtype=float)
            idx_list = _rdp(pts_np, simplify)
            pts      = [pts[k] for k in idx_list]
        if is_jump:
            # pts = [prev_end, next_start]; prev_end already in flat_path
            if flat_path:
                jump_indices.append(len(flat_path) - 1)
                flat_path.append(pts[-1])
            else:
                flat_path.extend(pts)
        else:
            if flat_path:
                flat_path.extend(pts[1:])   # first pt equals previous jump end
            else:
                flat_path.extend(pts)

    path = flat_path

    # Preview: real segments in cyan, jump connectors in dim orange
    prev_img = _PILImg.new('RGB', (w, h), (6, 6, 15))
    draw     = _IDraw.Draw(prev_img)
    jump_set = set(jump_indices)
    for i in range(len(path) - 1):
        r1, c1 = int(path[i][0]),   int(path[i][1])
        r2, c2 = int(path[i+1][0]), int(path[i+1][1])
        color  = (100, 60, 30) if i in jump_set else (34, 211, 238)
        draw.line([(c1, r1), (c2, r2)], fill=color, width=1)
    buf = _io.BytesIO()
    prev_img.save(buf, 'PNG')
    preview_b64 = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    n_jumps   = len(jump_indices)
    jump_lens = [
        math.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
        for i in jump_indices if i + 1 < len(path)
    ]
    longest_jump = round(max(jump_lens), 1) if jump_lens else 0.0
    total_len    = sum(
        math.hypot(path[i+1][0]-path[i][0], path[i+1][1]-path[i][1])
        for i in range(len(path) - 1)
    ) if len(path) > 1 else 0.0

    return JSONResponse({
        'path':             path,
        'jump_indices':     jump_indices,
        'n_points':         len(path),
        'n_jumps':          n_jumps,
        'longest_jump':     longest_jump,
        'total_length_px':  round(total_len, 1),
        'preview_image':    preview_b64,
        'skeleton_image':   _encode_png((skel.astype(_np.uint8) * 255)),
        'cleaned_image':    _encode_png((enhanced * 255).astype(_np.uint8)),
        'image_width':      w,
        'image_height':     h,
    })


class OneLineExportRequest(BaseModel):
    path:         List[List[float]]
    image_width:  int
    image_height: int
    scale:        float = 1.0
    filename:     str   = 'one-line.dxf'


@app.post('/photo-to-dxf/export-one-line', summary='Export one-line path as DXF (single LWPOLYLINE on layer ONE_LINE)')
async def photo_export_one_line(body: OneLineExportRequest, background_tasks: BackgroundTasks):
    import ezdxf
    doc = ezdxf.new('R2010')
    doc.layers.new(name='ONE_LINE', dxfattribs={'color': 4})   # cyan
    msp = doc.modelspace()

    h, s = body.image_height, body.scale
    if len(body.path) >= 2:
        pts = [(float(p[1]) * s, float(h - p[0]) * s) for p in body.path]
        msp.add_lwpolyline(pts, dxfattribs={'layer': 'ONE_LINE'})

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    doc.saveas(tmp_path)
    background_tasks.add_task(os.unlink, tmp_path)

    return FileResponse(
        tmp_path,
        media_type='application/octet-stream',
        filename=body.filename,
        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# DXF GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class DxfGenRequest(BaseModel):
    shape: str = 'rectangle'       # rectangle | circle | rounded_rect | slot | l_bracket | t_bracket
    width: float = 100.0
    height: float = 80.0
    radius: float = 10.0           # corner radius / circle radius
    slot_length: float = 60.0
    slot_width: float = 15.0
    flange_w: float = 40.0         # L/T bracket flange width
    flange_h: float = 20.0
    thickness: float = 3.0         # material thickness for notches
    hole: bool = False
    hole_radius: float = 5.0
    hole_x: float = 0.0            # offset from centre; 0 = centre
    hole_y: float = 0.0
    kerf: float = 0.0
    filename: str = 'shape.dxf'


def _dxf_rounded_rect(msp, x0: float, y0: float, w: float, h: float, r: float):
    import ezdxf, math
    r = min(r, w / 2, h / 2)
    # Four straight edges
    msp.add_line((x0 + r, y0),         (x0 + w - r, y0))
    msp.add_line((x0 + w, y0 + r),     (x0 + w, y0 + h - r))
    msp.add_line((x0 + w - r, y0 + h), (x0 + r, y0 + h))
    msp.add_line((x0 + r, y0 + h),     (x0, y0 + h - r))
    msp.add_line((x0, y0 + h - r),     (x0, y0 + r))
    msp.add_line((x0, y0 + r),         (x0 + r, y0))
    # Four corners
    msp.add_arc((x0 + r,     y0 + r),     r, 180, 270)
    msp.add_arc((x0 + w - r, y0 + r),     r, 270, 360)
    msp.add_arc((x0 + w - r, y0 + h - r), r, 0,   90)
    msp.add_arc((x0 + r,     y0 + h - r), r, 90,  180)


@app.post('/dxf-generator/export', summary='Generate parametric DXF shape')
async def dxf_generator_export(body: DxfGenRequest, background_tasks: BackgroundTasks):
    import ezdxf, math

    k = body.kerf / 2
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    if body.shape == 'circle':
        r = max(0.1, body.radius - k)
        msp.add_circle((0, 0), radius=r)
        if body.hole:
            hr = max(0.1, body.hole_radius + k)
            msp.add_circle((body.hole_x, body.hole_y), radius=hr)

    elif body.shape == 'rounded_rect':
        w, h = body.width - 2 * k, body.height - 2 * k
        _dxf_rounded_rect(msp, 0, 0, w, h, body.radius)
        if body.hole:
            hr = max(0.1, body.hole_radius + k)
            msp.add_circle((w / 2 + body.hole_x, h / 2 + body.hole_y), radius=hr)

    elif body.shape == 'slot':
        sl, sw = body.slot_length - 2 * k, body.slot_width - 2 * k
        r = sw / 2
        msp.add_line((r, 0), (sl - r, 0))
        msp.add_line((sl - r, sw), (r, sw))
        msp.add_arc((r,      r), r, 90,  270)
        msp.add_arc((sl - r, r), r, 270, 90)

    elif body.shape == 'l_bracket':
        w, h = body.width - 2 * k, body.height - 2 * k
        fw, fh = body.flange_w, body.flange_h
        pts = [(0,0),(w,0),(w,fh),(fw,fh),(fw,h),(0,h),(0,0)]
        for i in range(len(pts) - 1):
            msp.add_line(pts[i], pts[i + 1])

    elif body.shape == 't_bracket':
        w, h = body.width - 2 * k, body.height - 2 * k
        fw, fh = body.flange_w, body.flange_h
        cx = w / 2
        pts = [
            (0, 0), (w, 0), (w, fh), (cx + fw / 2, fh),
            (cx + fw / 2, h), (cx - fw / 2, h),
            (cx - fw / 2, fh), (0, fh), (0, 0),
        ]
        for i in range(len(pts) - 1):
            msp.add_line(pts[i], pts[i + 1])

    else:  # rectangle
        w, h = body.width - 2 * k, body.height - 2 * k
        msp.add_lwpolyline([(0,0),(w,0),(w,h),(0,h)], close=True)
        if body.hole:
            hr = max(0.1, body.hole_radius + k)
            msp.add_circle((w / 2 + body.hole_x, h / 2 + body.hole_y), radius=hr)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    doc.saveas(tmp_path)
    background_tasks.add_task(os.unlink, tmp_path)
    return FileResponse(tmp_path, media_type='application/octet-stream', filename=body.filename,
                        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'})


# ═══════════════════════════════════════════════════════════════════════════════
# SHEET LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

class SheetPart(BaseModel):
    label: str = 'Part'
    width: float
    height: float
    qty: int = 1

class SheetLayoutRequest(BaseModel):
    sheet_width: float = 1220.0
    sheet_height: float = 2440.0
    spacing: float = 5.0
    parts: List[SheetPart] = []
    filename: str = 'layout.dxf'

class PackedRect(BaseModel):
    label: str
    x: float
    y: float
    width: float
    height: float
    sheet: int

def _shelf_pack(parts_flat: List[dict], sw: float, sh: float, spacing: float):
    placed, sheets = [], 0
    remaining = list(parts_flat)
    while remaining:
        sheet_placed, shelf_x, shelf_y, shelf_h = [], spacing, spacing, 0
        still_remaining = []
        for p in remaining:
            pw, ph = p['width'] + spacing, p['height'] + spacing
            if pw > sw - spacing or ph > sh - spacing:
                still_remaining.append(p)
                continue
            if shelf_x + pw > sw - spacing:
                shelf_x  = spacing
                shelf_y += shelf_h + spacing
                shelf_h  = 0
            if shelf_y + ph > sh - spacing:
                still_remaining.append(p)
                continue
            sheet_placed.append({**p, 'x': shelf_x, 'y': shelf_y, 'sheet': sheets})
            shelf_x += pw
            shelf_h  = max(shelf_h, ph)
        placed.extend(sheet_placed)
        if not sheet_placed:
            break
        remaining = still_remaining
        sheets += 1
    return placed, sheets or 1


@app.post('/sheet-layout/pack', summary='Pack parts onto sheets (shelf algorithm)')
async def sheet_layout_pack(body: SheetLayoutRequest):
    parts_flat = []
    for p in body.parts:
        for _ in range(max(1, p.qty)):
            parts_flat.append({'label': p.label, 'width': p.width, 'height': p.height})
    parts_flat.sort(key=lambda p: -p['height'])

    placed, n_sheets = _shelf_pack(parts_flat, body.sheet_width, body.sheet_height, body.spacing)
    total_area = body.sheet_width * body.sheet_height * n_sheets
    used_area  = sum(p['width'] * p['height'] for p in placed)
    efficiency = round(used_area / total_area * 100, 1) if total_area > 0 else 0

    return JSONResponse({
        'placed': placed,
        'n_sheets': n_sheets,
        'n_placed': len(placed),
        'n_failed': len(parts_flat) - len(placed),
        'efficiency_pct': efficiency,
        'sheet_width': body.sheet_width,
        'sheet_height': body.sheet_height,
    })


@app.post('/sheet-layout/export', summary='Export sheet layout as DXF')
async def sheet_layout_export(body: SheetLayoutRequest, background_tasks: BackgroundTasks):
    import ezdxf

    parts_flat = []
    for p in body.parts:
        for _ in range(max(1, p.qty)):
            parts_flat.append({'label': p.label, 'width': p.width, 'height': p.height})
    parts_flat.sort(key=lambda p: -p['height'])
    placed, n_sheets = _shelf_pack(parts_flat, body.sheet_width, body.sheet_height, body.spacing)

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    for sheet_idx in range(n_sheets):
        ox = sheet_idx * (body.sheet_width + 50)
        # Sheet border
        msp.add_lwpolyline([
            (ox, 0), (ox + body.sheet_width, 0),
            (ox + body.sheet_width, body.sheet_height),
            (ox, body.sheet_height),
        ], close=True, dxfattribs={'color': 8})
        # Parts
        for p in placed:
            if p['sheet'] != sheet_idx:
                continue
            x, y, pw, ph = ox + p['x'], p['y'], p['width'], p['height']
            msp.add_lwpolyline([(x, y),(x+pw, y),(x+pw, y+ph),(x, y+ph)], close=True)
            msp.add_text(p['label'], dxfattribs={'height': min(pw, ph) * 0.12 or 5}).set_placement((x + pw/2, y + ph/2))

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    doc.saveas(tmp_path)
    background_tasks.add_task(os.unlink, tmp_path)
    return FileResponse(tmp_path, media_type='application/octet-stream', filename=body.filename,
                        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'})


# ═══════════════════════════════════════════════════════════════════════════════
# 3D PANELS
# ═══════════════════════════════════════════════════════════════════════════════

class PanelRequest(BaseModel):
    pattern: str   = 'diamond'   # diamond | hexagon | chevron | brick
    panel_w: float = 120.0
    panel_h: float = 80.0
    cols: int      = 5
    rows: int      = 4
    gap: float     = 3.0
    bevel: float   = 8.0         # inset bevel line depth
    tab_w: float   = 8.0
    tab_h: float   = 5.0
    add_tabs: bool = True
    filename: str  = 'panels.dxf'


def _panel_shape(pattern: str, pw: float, ph: float, bevel: float):
    """Return list of (x,y) vertices for one panel face."""
    if pattern == 'diamond':
        hw, hh = pw / 2, ph / 2
        return [(hw, 0), (pw, hh), (hw, ph), (0, hh)]
    elif pattern == 'hexagon':
        import math
        r = min(pw, ph) / 2
        return [(r + r * math.cos(math.radians(60 * i)), r + r * math.sin(math.radians(60 * i))) for i in range(6)]
    elif pattern == 'chevron':
        off = pw * 0.25
        return [(0, 0), (pw, 0), (pw - off, ph), (off, ph)]
    else:  # brick
        return [(0, 0), (pw, 0), (pw, ph), (0, ph)]


@app.post('/panels/generate', summary='Generate panel layout data')
async def panels_generate(body: PanelRequest):
    panels = []
    import math
    pw, ph, gap = body.panel_w, body.panel_h, body.gap
    step_x = pw + gap
    step_y = ph + gap

    for row in range(body.rows):
        offset_x = (step_x / 2) if (row % 2 == 1 and body.pattern in ('brick', 'chevron')) else 0
        for col in range(body.cols):
            ox = col * step_x + offset_x
            oy = row * step_y
            verts = _panel_shape(body.pattern, pw, ph, body.bevel)
            panels.append({
                'id': row * body.cols + col,
                'row': row, 'col': col,
                'ox': ox, 'oy': oy,
                'vertices': verts,
            })

    total_w = body.cols * step_x - gap + (step_x / 2 if body.pattern in ('brick','chevron') else 0)
    total_h = body.rows * step_y - gap
    return JSONResponse({
        'panels': panels,
        'n_panels': len(panels),
        'pattern': body.pattern,
        'panel_w': pw,
        'panel_h': ph,
        'total_w': total_w,
        'total_h': total_h,
    })


@app.post('/panels/export', summary='Export panel layout as DXF')
async def panels_export(body: PanelRequest, background_tasks: BackgroundTasks):
    import ezdxf, math

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    pw, ph, gap = body.panel_w, body.panel_h, body.gap
    step_x, step_y = pw + gap, ph + gap

    for row in range(body.rows):
        offset_x = (step_x / 2) if (row % 2 == 1 and body.pattern in ('brick', 'chevron')) else 0
        for col in range(body.cols):
            ox = col * step_x + offset_x
            oy = row * step_y
            verts = _panel_shape(body.pattern, pw, ph, body.bevel)
            closed = [(ox + x, oy + y) for x, y in verts]
            msp.add_lwpolyline(closed, close=True)
            # Bevel inset line
            if body.bevel > 0 and body.pattern == 'diamond':
                b = body.bevel
                hw, hh = pw / 2, ph / 2
                inner = [(ox+hw, oy+b),(ox+pw-b, oy+hh),(ox+hw, oy+ph-b),(ox+b, oy+hh)]
                msp.add_lwpolyline(inner, close=True, dxfattribs={'color': 8})
            # Tabs
            if body.add_tabs:
                tw, th = body.tab_w, body.tab_h
                cx, cy = ox + pw / 2, oy + ph / 2
                # Bottom tab
                msp.add_lwpolyline([
                    (cx - tw/2, oy), (cx + tw/2, oy),
                    (cx + tw/2, oy - th), (cx - tw/2, oy - th),
                ], close=True, dxfattribs={'color': 3})

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    doc.saveas(tmp_path)
    background_tasks.add_task(os.unlink, tmp_path)
    return FileResponse(tmp_path, media_type='application/octet-stream', filename=body.filename,
                        headers={'Content-Disposition': f'attachment; filename="{body.filename}"'})


# ═══════════════════════════════════════════════════════════════════════════════
# ALUCOBOND CLADDING
# ═══════════════════════════════════════════════════════════════════════════════

import math as _math
import io   as _io_mod
import csv  as _csv
import zipfile as _zipfile

_FACE_ABBR = {'north': 'N', 'south': 'S', 'east': 'E', 'west': 'W'}

class AlucobondBuilding(BaseModel):
    width:  float = 12000.0   # mm
    depth:  float = 8000.0
    height: float = 9000.0

class AlucobondCladding(BaseModel):
    offset:       float = 50.0
    panel_width:  float = 1200.0
    panel_height: float = 600.0
    joint_gap:    float = 10.0
    return_depth: float = 30.0
    pattern:      str   = 'horizontal'  # horizontal | vertical | brick

class AlucobondPanelsRequest(BaseModel):
    building: AlucobondBuilding
    cladding: AlucobondCladding

class AlucobondPanelDxfRequest(BaseModel):
    panel: dict
    filename: str = 'panel.dxf'


# ── Layout helper ─────────────────────────────────────────────────────────────

def _row_x_positions(pw: float, gap: float, face_w: float, is_brick_offset: bool) -> list[tuple[float, float]]:
    """Return (x_start, visible_width) pairs for one row, left-to-right."""
    positions: list[tuple[float, float]] = []
    if is_brick_offset:
        # Half-panel at left edge (brick starter)
        hw = pw / 2.0
        if hw > 0.5:
            positions.append((0.0, min(hw, face_w)))
        x = hw + gap
    else:
        x = 0.0
    while x < face_w - 0.5:
        vw = min(pw, face_w - x)
        if vw > 0.5:
            positions.append((x, vw))
        x += pw + gap
    return positions


def _alucobond_face_panels(face: str, face_w: float, face_h: float, c: AlucobondCladding) -> list:
    pw, ph = c.panel_width, c.panel_height
    gap, ret = c.joint_gap, c.return_depth

    if c.pattern == 'vertical':
        pw, ph = ph, pw

    # Build row y-positions
    row_ys: list[tuple[float, float]] = []
    y = 0.0
    while y < face_h - 0.5:
        vh = min(ph, face_h - y)
        if vh > 0.5:
            row_ys.append((y, vh))
        y += ph + gap
    n_rows = len(row_ys)

    abbr = _FACE_ABBR.get(face, face[0].upper())
    panels = []

    for row_idx, (y, vis_h) in enumerate(row_ys):
        is_brick_offset = (c.pattern == 'brick') and (row_idx % 2 == 1)
        x_positions = _row_x_positions(pw, gap, face_w, is_brick_offset)
        n_cols = len(x_positions)

        for col_idx, (x, vis_w) in enumerate(x_positions):
            # Edge detection: within 0.5 mm of the face boundary
            is_left   = (x < 0.5)
            is_right  = (x + vis_w > face_w - 0.5)
            is_bottom = (row_idx == 0)
            is_top    = (row_idx == n_rows - 1)

            r_left   = ret if is_left   else 0.0
            r_right  = ret if is_right  else 0.0
            r_bottom = ret if is_bottom else 0.0
            r_top    = ret if is_top    else 0.0

            edge_flags = sum([is_left, is_right, is_bottom, is_top])
            ptype = 'corner' if edge_flags >= 2 else ('edge' if edge_flags == 1 else 'interior')

            bw = r_left + vis_w + r_right
            bh = r_bottom + vis_h + r_top

            # Fold line positions in blank coordinate space
            fold_lines = []
            if r_bottom: fold_lines.append({'axis': 'h', 'position': round(r_bottom,       2)})
            if r_top:    fold_lines.append({'axis': 'h', 'position': round(r_bottom + vis_h, 2)})
            if r_left:   fold_lines.append({'axis': 'v', 'position': round(r_left,           2)})
            if r_right:  fold_lines.append({'axis': 'v', 'position': round(r_left + vis_w,   2)})

            panels.append({
                'id':           f'{abbr}{row_idx:02d}-{col_idx:02d}',
                'face':         face,
                'row':          row_idx,
                'col':          col_idx,
                'nRows':        n_rows,
                'nCols':        n_cols,
                'visibleWidth':  round(vis_w, 2),
                'visibleHeight': round(vis_h, 2),
                'visibleArea':   round(vis_w * vis_h / 1_000_000, 4),  # m²
                'returns':       {'left': r_left, 'right': r_right,
                                  'top': r_top,   'bottom': r_bottom},
                'blankWidth':    round(bw, 2),
                'blankHeight':   round(bh, 2),
                'blankArea':     round(bw * bh / 1_000_000, 4),        # m²
                'type':          ptype,
                'faceOrigin':    [round(x, 2), round(y, 2)],
                'foldLines':     fold_lines,
            })
    return panels


# ── DXF generation (shared by single-export and bulk-export) ──────────────────

def _build_panel_dxf(p: dict) -> bytes:
    import ezdxf
    ret = p['returns']
    vw  = float(p['visibleWidth']);  vh = float(p['visibleHeight'])
    rl  = float(ret['left']);        rr = float(ret['right'])
    rt  = float(ret['top']);         rb = float(ret['bottom'])
    bw  = rl + vw + rr;             bh = rb + vh + rt

    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    doc.layers.add('OUTLINE',     color=7)
    doc.layers.add('FOLD_LINES',  color=1)   # red  – 90° bends
    doc.layers.add('CUT_MARKS',   color=3)   # green – corner waste removed
    doc.layers.add('VISIBLE_FACE',color=4)   # cyan  – finished face boundary
    doc.layers.add('ANNOTATIONS', color=5)   # blue  – dims + text

    # DASHED linetype for fold lines
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[8.0, -4.0])

    fold_attr = {'layer': 'FOLD_LINES', 'linetype': 'DASHED', 'ltscale': 5.0}

    # ── Outer blank ──
    msp.add_lwpolyline(
        [(0,0),(bw,0),(bw,bh),(0,bh)], close=True,
        dxfattribs={'layer': 'OUTLINE', 'lineweight': 50},
    )

    # ── Fold lines (span full blank width/height) ──
    if rb: msp.add_line((0, rb),       (bw, rb),       dxfattribs=fold_attr)
    if rt: msp.add_line((0, rb + vh),  (bw, rb + vh),  dxfattribs=fold_attr)
    if rl: msp.add_line((rl, 0),       (rl, bh),       dxfattribs=fold_attr)
    if rr: msp.add_line((rl + vw, 0),  (rl + vw, bh),  dxfattribs=fold_attr)

    # ── Corner cut-out marks (waste squares) ──
    def cut_sq(x: float, y: float, w: float, h: float) -> None:
        if w > 0 and h > 0:
            msp.add_lwpolyline([(x,y),(x+w,y),(x+w,y+h),(x,y+h)], close=True,
                               dxfattribs={'layer': 'CUT_MARKS'})
            msp.add_line((x, y),   (x+w, y+h), dxfattribs={'layer': 'CUT_MARKS'})
            msp.add_line((x+w, y), (x,   y+h), dxfattribs={'layer': 'CUT_MARKS'})

    if rl and rb: cut_sq(0,       0,       rl, rb)
    if rr and rb: cut_sq(rl + vw, 0,       rr, rb)
    if rl and rt: cut_sq(0,       rb + vh, rl, rt)
    if rr and rt: cut_sq(rl + vw, rb + vh, rr, rt)

    # ── Visible-face boundary ──
    msp.add_lwpolyline(
        [(rl,rb),(rl+vw,rb),(rl+vw,rb+vh),(rl,rb+vh)], close=True,
        dxfattribs={'layer': 'VISIBLE_FACE', 'lineweight': 25},
    )

    # ── Return depth labels (centred in each return band) ──
    ann = {'layer': 'ANNOTATIONS'}
    def mid_text(cx: float, cy: float, txt: str, h: float = 10.0) -> None:
        msp.add_text(txt, dxfattribs={**ann, 'height': h,
                                      'halign': 1, 'valign': 2,
                                      'insert': (cx, cy), 'align_point': (cx, cy)})

    if rb: mid_text(bw / 2,              rb / 2,              f'↕ {rb:.0f}')
    if rt: mid_text(bw / 2,              rb + vh + rt / 2,    f'↕ {rt:.0f}')
    if rl: mid_text(rl / 2,              bh / 2,              f'↔ {rl:.0f}')
    if rr: mid_text(rl + vw + rr / 2,    bh / 2,              f'↔ {rr:.0f}')

    # ── Header annotations ──
    msp.add_text(
        f"PANEL  {p.get('id','?')}   |   FACE: {p.get('face','?').upper()}   |   TYPE: {p.get('type','?').upper()}",
        dxfattribs={**ann, 'insert': (0, bh + 28), 'height': 20},
    )
    msp.add_text(
        f"Blank: {bw:.0f} × {bh:.0f} mm     Visible face: {vw:.0f} × {vh:.0f} mm     Row {p.get('row','')}  Col {p.get('col','')}",
        dxfattribs={**ann, 'insert': (0, bh + 54), 'height': 14},
    )
    returns_parts = [f"{k[0].upper()}={v:.0f}" for k, v in ret.items() if v]
    if returns_parts:
        msp.add_text(
            'Returns: ' + '  '.join(returns_parts) + ' mm    (fold 90° inward)',
            dxfattribs={**ann, 'insert': (0, bh + 74), 'height': 12},
        )

    # ── Dimensions ──
    try:
        msp.add_linear_dim(base=(bw/2, -35), p1=(0,0), p2=(bw,0),
                           dimstyle='Standard', dxfattribs=ann).render()
        msp.add_linear_dim(base=(-35, bh/2), p1=(0,0), p2=(0,bh),
                           angle=90, dimstyle='Standard', dxfattribs=ann).render()
    except Exception:
        pass

    buf = _io_mod.BytesIO()
    doc.write(buf)
    return buf.getvalue()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post('/alucobond/panels', summary='Generate Alucobond panel layout for a rectangular building')
async def alucobond_panels(body: AlucobondPanelsRequest):
    b, c = body.building, body.cladding
    W, D, H = b.width, b.depth, b.height

    # N/S faces own the full skin width (W + 2×offset) to cover corner strips.
    # E/W faces span only the building depth (D) — they sit between the corner strips.
    skin_w = W + 2 * c.offset
    face_defs = [('north', skin_w, H), ('south', skin_w, H), ('east', D, H), ('west', D, H)]

    all_panels: list = []
    face_stats: dict = {}
    for face_name, fw, fh in face_defs:
        fps = _alucobond_face_panels(face_name, fw, fh, c)
        all_panels.extend(fps)
        face_stats[face_name] = {
            'count':           len(fps),
            'visibleAreaM2':   round(sum(p['visibleArea'] for p in fps), 3),
            'blankAreaM2':     round(sum(p['blankArea']   for p in fps), 3),
        }

    counts = {'interior': 0, 'edge': 0, 'corner': 0}
    for p in all_panels:
        counts[p['type']] += 1

    total_vis  = round(sum(p['visibleArea'] for p in all_panels), 3)
    total_blnk = round(sum(p['blankArea']   for p in all_panels), 3)
    waste_pct  = round((total_blnk - total_vis) / total_blnk * 100, 1) if total_blnk else 0

    return {
        'panels': all_panels,
        'stats': {
            'total':         len(all_panels),
            'interior':      counts['interior'],
            'edge':          counts['edge'],
            'corner':        counts['corner'],
            'visibleAreaM2': total_vis,
            'blankAreaM2':   total_blnk,
            'wastePct':      waste_pct,
            'byFace':        face_stats,
        },
    }


@app.post('/alucobond/panel-dxf', summary='Export flat-blank DXF for one panel')
async def alucobond_panel_dxf(body: AlucobondPanelDxfRequest, background_tasks: BackgroundTasks):
    dxf_bytes = _build_panel_dxf(body.panel)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    with open(tmp_path, 'wb') as fh:
        fh.write(dxf_bytes)
    background_tasks.add_task(os.unlink, tmp_path)
    filename = body.filename or f"panel_{body.panel.get('id','unknown')}.dxf"
    return FileResponse(tmp_path, media_type='application/octet-stream', filename=filename,
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@app.post('/alucobond/export-all', summary='Export all panels as a ZIP of DXFs + manifest CSV')
async def alucobond_export_all(body: AlucobondPanelsRequest, background_tasks: BackgroundTasks):
    b, c = body.building, body.cladding
    W, D, H = b.width, b.depth, b.height
    skin_w = W + 2 * c.offset
    face_defs = [('north', skin_w, H), ('south', skin_w, H), ('east', D, H), ('west', D, H)]

    all_panels: list = []
    for face_name, fw, fh in face_defs:
        all_panels.extend(_alucobond_face_panels(face_name, fw, fh, c))

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.zip')
    os.close(tmp_fd)

    with _zipfile.ZipFile(tmp_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
        # One DXF per panel, organised by face folder
        for p in all_panels:
            dxf_bytes = _build_panel_dxf(p)
            zf.writestr(f"{p['face']}/{p['id']}.dxf", dxf_bytes)

        # Manifest CSV
        csv_buf = _io_mod.StringIO()
        writer = _csv.writer(csv_buf)
        writer.writerow([
            'ID', 'Face', 'Row', 'Col', 'Type',
            'Visible W (mm)', 'Visible H (mm)',
            'Blank W (mm)',   'Blank H (mm)',
            'Return L (mm)', 'Return R (mm)', 'Return T (mm)', 'Return B (mm)',
            'Visible Area (m²)', 'Blank Area (m²)',
            'Fold Lines',
        ])
        for p in all_panels:
            r = p['returns']
            folds = '; '.join(
                f"{fl['axis'].upper()}@{fl['position']:.0f}" for fl in p['foldLines']
            )
            writer.writerow([
                p['id'], p['face'], p['row'], p['col'], p['type'],
                p['visibleWidth'], p['visibleHeight'],
                p['blankWidth'],   p['blankHeight'],
                r['left'], r['right'], r['top'], r['bottom'],
                p['visibleArea'], p['blankArea'],
                folds,
            ])
        zf.writestr('manifest.csv', csv_buf.getvalue())

    background_tasks.add_task(os.unlink, tmp_path)
    return FileResponse(tmp_path, media_type='application/zip', filename='alucobond_panels.zip',
                        headers={'Content-Disposition': 'attachment; filename="alucobond_panels.zip"'})


# ── Folded Board ──────────────────────────────────────────────────────────────

class FoldedBoardDxfRequest(BaseModel):
    width:             float         # mm — face width  (W)
    height:            float         # mm — face height (H)
    edge_depth:        float         # mm — return depth (d)
    filename:          str = 'folded_board.dxf'
    design_lines:      list[dict] = []           # [{x1,y1,x2,y2}] — decorative groove lines
    developed_polygon: list[list[float]] = []    # [[x,y]...] — unfolded face corners in mm
    design_angle:      float = 0.0               # degrees — decorative bend angle


@app.post('/folded-board/dxf', summary='Export flat-blank DXF for a folded rectangular board')
async def folded_board_dxf(body: FoldedBoardDxfRequest, background_tasks: BackgroundTasks):
    import ezdxf

    W = float(body.width)
    H = float(body.height)
    d = float(body.edge_depth)

    # ── base geometry (matches frontend computeBoard) ────────────────────────
    face = [(-W/2, H/2), (W/2, H/2), (W/2, -H/2), (-W/2, -H/2)]

    fold_lines = [
        ((-W/2,  H/2), ( W/2,  H/2)),
        (( W/2,  H/2), ( W/2, -H/2)),
        (( W/2, -H/2), (-W/2, -H/2)),
        ((-W/2, -H/2), (-W/2,  H/2)),
    ]

    plus = [
        (-W/2,      H/2 + d),
        ( W/2,      H/2 + d),
        ( W/2,      H/2    ),
        ( W/2 + d,  H/2    ),
        ( W/2 + d, -H/2    ),
        ( W/2,     -H/2    ),
        ( W/2,    -(H/2+d) ),
        (-W/2,    -(H/2+d) ),
        (-W/2,     -H/2    ),
        (-(W/2+d), -H/2    ),
        (-(W/2+d),  H/2    ),
        (-W/2,      H/2    ),
    ]

    # When a developed polygon is supplied, promote it to fabrication geometry:
    # CUT/BEND/FACE all use developed extents; original W×H face becomes a reference.
    W_lbl, H_lbl = W, H
    orig_face = list(face)

    if len(body.developed_polygon) >= 3:
        dev_pts = [(float(p[0]), float(p[1])) for p in body.developed_polygon]
        dev_xs  = [p[0] for p in dev_pts]
        dev_ys  = [p[1] for p in dev_pts]
        fab_w   = max(dev_xs) - min(dev_xs)
        fab_h   = max(dev_ys) - min(dev_ys)
        W_lbl, H_lbl = fab_w, fab_h
        face = dev_pts
        fold_lines = [
            ((-fab_w/2,  fab_h/2), ( fab_w/2,  fab_h/2)),
            (( fab_w/2,  fab_h/2), ( fab_w/2, -fab_h/2)),
            (( fab_w/2, -fab_h/2), (-fab_w/2, -fab_h/2)),
            ((-fab_w/2, -fab_h/2), (-fab_w/2,  fab_h/2)),
        ]
        plus = [
            (-fab_w/2,      fab_h/2 + d),
            ( fab_w/2,      fab_h/2 + d),
            ( fab_w/2,      fab_h/2    ),
            ( fab_w/2 + d,  fab_h/2    ),
            ( fab_w/2 + d, -fab_h/2    ),
            ( fab_w/2,     -fab_h/2    ),
            ( fab_w/2,    -(fab_h/2+d) ),
            (-fab_w/2,    -(fab_h/2+d) ),
            (-fab_w/2,     -fab_h/2    ),
            (-(fab_w/2+d), -fab_h/2    ),
            (-(fab_w/2+d),  fab_h/2    ),
            (-fab_w/2,      fab_h/2    ),
        ]

    # ── build DXF ───────────────────────────────────────────────────────────
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    doc.layers.add('FACE',          color=5)   # blue
    doc.layers.add('BEND',          color=1)   # red
    doc.layers.add('CUT',           color=3)   # green
    doc.layers.add('LABELS',        color=7)   # white
    doc.layers.add('DESIGN_GROOVE', color=6)   # magenta
    doc.layers.add('DEVELOPED',     color=4)   # cyan
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[8.0, -4.0])
    da = {'linetype': 'DASHED', 'ltscale': 5.0}

    # FACE — visible rectangle
    msp.add_lwpolyline(face, close=True, dxfattribs={'layer': 'FACE'})

    # CUT — plus-shaped blank boundary (closed polyline)
    msp.add_lwpolyline(plus, close=True, dxfattribs={'layer': 'CUT'})

    # BEND — fold score lines (dashed)
    for a, b in fold_lines:
        msp.add_line(a, b, dxfattribs={'layer': 'BEND', **da})

    # DESIGN_GROOVE — decorative groove lines on face (dashed, magenta)
    for dl in body.design_lines:
        msp.add_line(
            (float(dl['x1']), float(dl['y1'])),
            (float(dl['x2']), float(dl['y2'])),
            dxfattribs={'layer': 'DESIGN_GROOVE', **da},
        )
    if body.design_lines:
        msp.add_text('DESIGN_GROOVE (decorative)', dxfattribs={
            'layer': 'DESIGN_GROOVE', 'height': 10,
            'insert': (-W_lbl/2, -(H_lbl/2 + d + 40)),
        })

    # DEVELOPED — original visible face as dashed reference outline
    if len(body.developed_polygon) >= 3:
        msp.add_lwpolyline(orig_face, close=True, dxfattribs={'layer': 'DEVELOPED', **da})
        angle = float(body.design_angle)
        msp.add_text(
            f'Visible face: {W:.0f} x {H:.0f} mm  |  Fabrication (developed): {W_lbl:.1f} x {H_lbl:.1f} mm  (bend {angle:.0f} deg)',
            dxfattribs={
                'layer': 'DEVELOPED', 'height': 10,
                'insert': (-W_lbl/2, -(H_lbl/2 + d + 54)),
            },
        )

    # LABELS — dimensions (fabrication size when developed)
    msp.add_text(f'W={W_lbl:.1f}mm', dxfattribs={
        'layer': 'LABELS', 'height': 14,
        'insert': (-W_lbl/4, H_lbl/2 + d + 20),
    })
    msp.add_text(f'H={H_lbl:.1f}mm', dxfattribs={
        'layer': 'LABELS', 'height': 14,
        'insert': (W_lbl/2 + d + 12, 0),
    })
    msp.add_text(f'Edge depth: {d:.0f}mm  |  Bend: 90deg inward', dxfattribs={
        'layer': 'LABELS', 'height': 12,
        'insert': (-(W_lbl/2 + d), -(H_lbl/2 + d + 24)),
    })

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    with open(tmp_path, 'w') as fh:
        doc.write(fh)
    background_tasks.add_task(os.unlink, tmp_path)
    fn = body.filename or 'folded_board.dxf'
    return FileResponse(tmp_path, media_type='application/octet-stream',
                        filename=fn,
                        headers={'Content-Disposition': f'attachment; filename="{fn}"'})


# ── Corner wrap panel DXF ─────────────────────────────────────────────────────

class CornerWrapDxfRequest(BaseModel):
    segA:       float          # mm — segment width on Wall A
    segB:       float          # mm — segment width on Wall B
    height:     float          # mm — face height
    edge_depth: float          # mm — return / fold depth
    filename:   str = 'corner_wrap.dxf'


@app.post('/corner-wrap/dxf', summary='Export flat-blank DXF for an inside-corner wrap panel')
async def corner_wrap_dxf(body: CornerWrapDxfRequest, background_tasks: BackgroundTasks):
    import ezdxf

    A  = float(body.segA)
    B  = float(body.segB)
    H  = float(body.height)
    d  = float(body.edge_depth)

    # ── Flat-blank layout ────────────────────────────────────────────────────
    #
    #  The wrap panel unfolds as a rectangle with two V-notch relief cuts:
    #  one at the top and one at the bottom of the corner-bend line.
    #
    #  X axis: left return → Face A → Face B → right return
    #  Y axis: bottom return → face → top return
    #
    #   Total width  W_tot = 2d + A + B
    #   Total height H_tot = 2d + H
    #   Bend line at X = d + A  (the 90° corner fold)
    #
    #  V-notch vertices (relief cuts at bend × return intersections):
    #   bottom: (d+A, d)    top: (d+A, d+H)
    #
    # ── CUT polygon — 10 vertices, counter-clockwise ────────────────────────

    W_tot = 2 * d + A + B
    H_tot = 2 * d + H
    bx    = d + A            # bend line X

    cut = [
        (0,     0    ),      # bottom-left
        (A,     0    ),      # before bottom V-notch (left wing)
        (bx,    d    ),      # bottom V-notch inner vertex
        (bx+d,  0    ),      # after bottom V-notch  (right wing)
        (W_tot, 0    ),      # bottom-right
        (W_tot, H_tot),      # top-right
        (bx+d,  H_tot),      # before top V-notch    (right wing)
        (bx,    d + H),      # top V-notch inner vertex
        (A,     H_tot),      # after top V-notch     (left wing)
        (0,     H_tot),      # top-left
    ]

    # ── Build DXF ────────────────────────────────────────────────────────────
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    doc.layers.add('CUT',    color=3)   # green
    doc.layers.add('BEND',   color=1)   # red
    doc.layers.add('FACE',   color=5)   # blue
    doc.layers.add('LABELS', color=7)   # white
    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[8.0, -4.0])
    da = {'linetype': 'DASHED', 'ltscale': 5.0}

    # CUT — outer boundary with V-notch relief cuts
    msp.add_lwpolyline(cut, close=True, dxfattribs={'layer': 'CUT'})

    # FACE — two face rectangles (Wall A and Wall B segments)
    msp.add_lwpolyline(
        [(d, d), (bx, d), (bx, d+H), (d, d+H)],
        close=True, dxfattribs={'layer': 'FACE'},
    )
    msp.add_lwpolyline(
        [(bx, d), (bx+B, d), (bx+B, d+H), (bx, d+H)],
        close=True, dxfattribs={'layer': 'FACE'},
    )

    # BEND — 7 score lines:
    #  1 corner bend (main 90° wrap fold)
    #  2 outer return folds (left / right)
    #  4 top/bottom return folds (split at bend line)
    bend_lines = [
        ((bx,     d  ), (bx,     d+H)),   # corner wrap bend
        ((d,      d  ), (d,      d+H)),   # left outer return
        ((bx+B,   d  ), (bx+B,   d+H)),   # right outer return
        ((d,      d+H), (bx,     d+H)),   # top return — Wall A half
        ((bx,     d+H), (bx+B,   d+H)),   # top return — Wall B half
        ((d,      d  ), (bx,     d  )),   # bottom return — Wall A half
        ((bx,     d  ), (bx+B,   d  )),   # bottom return — Wall B half
    ]
    for p1, p2 in bend_lines:
        msp.add_line(p1, p2, dxfattribs={'layer': 'BEND', **da})

    # LABELS
    lbl_h = max(10.0, min(A, B, H) * 0.04)
    msp.add_text(f'A={A:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h,
                    'insert': (d + A/2, d + H/2)})
    msp.add_text(f'B={B:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h,
                    'insert': (bx + B/2, d + H/2)})
    msp.add_text(f'H={H:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h,
                    'insert': (d/2, d + H/2)})
    msp.add_text(f'd={d:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': max(8.0, lbl_h*0.8),
                    'insert': (d + A/2, H_tot + 6)})
    msp.add_text('90deg inside corner wrap',
        dxfattribs={'layer': 'LABELS', 'height': max(8.0, lbl_h*0.8),
                    'insert': (0, -18)})

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    with open(tmp_path, 'w') as fh:
        doc.write(fh)
    background_tasks.add_task(os.unlink, tmp_path)
    fn = body.filename or 'corner_wrap.dxf'
    return FileResponse(tmp_path, media_type='application/octet-stream',
                        filename=fn,
                        headers={'Content-Disposition': f'attachment; filename="{fn}"'})


# ── Outside corner wrap DXF ──────────────────────────────────────────────────
#
#  Flat blank for a convex (outside) 90° corner wrap panel.
#
#  Layout (left → right):
#    d_return | segFrom (Wall A/C face) | arc_w (= π/2 × d) | segTo (Wall B/D face) | d_return
#  Height: d_return (bottom) + face_height + d_return (top)
#
#  Bend lines (4 vertical):
#    x = d                              (from-return fold)
#    x = d + segFrom                    (face-from → arc transition)
#    x = d + segFrom + arc_w            (arc → face-to transition)
#    x = d + segFrom + arc_w + segTo    (to-return fold)
#
#  No V-notch relief needed — outside folds don't clash.

import math as _math

class CornerWrapOutsideDxfRequest(BaseModel):
    segFrom:    float
    segTo:      float
    height:     float
    edge_depth: float
    filename:   str = 'corner_wrap_outside.dxf'


@app.post('/corner-wrap-outside/dxf', summary='Export flat-blank DXF for an outside-corner wrap panel')
async def corner_wrap_outside_dxf(body: CornerWrapOutsideDxfRequest, background_tasks: BackgroundTasks):
    import ezdxf

    A  = float(body.segFrom)
    B  = float(body.segTo)
    H  = float(body.height)
    d  = float(body.edge_depth)

    arc_w  = _math.pi / 2 * d          # arc unrolled width
    W_tot  = d + A + arc_w + B + d     # total blank width
    H_tot  = d + H + d                 # total blank height

    # Bend line X positions
    bx1 = d                            # from-return fold
    bx2 = d + A                        # face-from → arc
    bx3 = d + A + arc_w               # arc → face-to
    bx4 = d + A + arc_w + B           # to-return fold

    doc = ezdxf.new('R2010')
    doc.layers.add('CUT',    color=3)
    doc.layers.add('BEND',   color=1)
    doc.layers.add('FACE',   color=5)
    doc.layers.add('LABELS', color=7)
    msp = doc.modelspace()

    # CUT — rectangle outline
    rect = [(0, 0), (W_tot, 0), (W_tot, H_tot), (0, H_tot), (0, 0)]
    msp.add_lwpolyline(rect, dxfattribs={'layer': 'CUT', 'closed': True})

    # BEND — 4 vertical fold lines
    for bx in [bx1, bx2, bx3, bx4]:
        msp.add_line((bx, 0), (bx, H_tot), dxfattribs={'layer': 'BEND'})
    # BEND — 4 horizontal return fold lines
    for by in [d, d + H]:
        msp.add_line((0, by), (W_tot, by), dxfattribs={'layer': 'BEND'})

    # FACE outlines — face-from and face-to rectangles
    msp.add_lwpolyline(
        [(bx1, d), (bx2, d), (bx2, d+H), (bx1, d+H)],
        dxfattribs={'layer': 'FACE', 'closed': True})
    msp.add_lwpolyline(
        [(bx3, d), (bx4, d), (bx4, d+H), (bx3, d+H)],
        dxfattribs={'layer': 'FACE', 'closed': True})

    # LABELS
    lbl_h = max(H * 0.06, 8.0)
    msp.add_text(f'A={A:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h,
                    'insert': (bx1 + A/2, d + H/2)})
    msp.add_text(f'arc={arc_w:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h * 0.85,
                    'insert': (bx2 + arc_w/2, d + H/2)})
    msp.add_text(f'B={B:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h,
                    'insert': (bx3 + B/2, d + H/2)})
    msp.add_text(f'd={d:.0f}mm',
        dxfattribs={'layer': 'LABELS', 'height': lbl_h * 0.8,
                    'insert': (d/2, d + H/2)})
    msp.add_text('90deg outside corner wrap',
        dxfattribs={'layer': 'LABELS', 'height': max(8.0, lbl_h * 0.8),
                    'insert': (0, -18)})

    import tempfile
    tmp_path = tempfile.mktemp(suffix='.dxf')
    with open(tmp_path, 'w') as fh:
        doc.write(fh)
    background_tasks.add_task(os.unlink, tmp_path)
    fn = body.filename or 'corner_wrap_outside.dxf'
    return FileResponse(tmp_path, media_type='application/octet-stream',
                        filename=fn,
                        headers={'Content-Disposition': f'attachment; filename="{fn}"'})


# ── Multi-corner wrap DXF ────────────────────────────────────────────────────
#
#  Flat blank for a panel that crosses N walls and N-1 corners.
#
#  Layout (left → right, X axis):
#    d_return | face_0 | arc_0 | face_1 | arc_1 | … | face_N | d_return
#
#  arc_i width  = (corner_angles[i] in radians) × edge_depth
#
#  Height (Y axis):
#    d_return (bottom) | face_height | d_return (top)
#
#  Layers:
#    CUT    — outer rectangular boundary
#    BEND   — vertical fold lines at each face boundary + returns;
#             horizontal return lines at top/bottom
#    FACE   — face rectangle outlines
#    LABELS — face widths, arc angles, overall dimensions

class MultiWrapDxfRequest(BaseModel):
    face_widths:   List[float]       # mm — one entry per wall face
    corner_angles: List[float]       # degrees — one entry per corner (len = len(face_widths) - 1)
    height:        float             # mm — face height
    edge_depth:    float             # mm — return fold depth
    filename:      str = 'multi_wrap.dxf'


@app.post('/multi-wrap/dxf', summary='Export flat-blank DXF for a multi-corner wrap panel')
async def multi_wrap_dxf(body: MultiWrapDxfRequest, background_tasks: BackgroundTasks):
    import ezdxf, math

    faces  = [float(w) for w in body.face_widths]
    angles = [float(a) for a in body.corner_angles]
    H      = float(body.height)
    d      = float(body.edge_depth)

    if not faces:
        raise HTTPException(status_code=422, detail='face_widths must not be empty')
    if len(angles) != len(faces) - 1:
        raise HTTPException(status_code=422,
            detail=f'corner_angles length ({len(angles)}) must equal face_widths length - 1 ({len(faces) - 1})')

    # Arc unrolled width at each corner
    arc_ws = [math.pi / 180.0 * a * d for a in angles]

    flat_w = d + sum(faces) + sum(arc_ws) + d
    flat_h = d + H + d

    # ── Cumulative x positions of each section boundary ──────────────────────
    # section_xs[i] = x at start of face i (after any preceding arc)
    # bend_xs = x coordinates of each inter-face bend line pair (start, end of arc)
    section_xs: list[float] = []
    bend_start_xs: list[float] = []   # x where face i ends / arc i starts
    bend_end_xs:   list[float] = []   # x where arc i ends / face i+1 starts
    x = d
    for i, fw in enumerate(faces):
        section_xs.append(x)
        x += fw
        if i < len(arc_ws):
            bend_start_xs.append(x)
            x += arc_ws[i]
            bend_end_xs.append(x)

    # ── DXF document ─────────────────────────────────────────────────────────
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()

    doc.layers.add('CUT',    color=3)    # green
    doc.layers.add('BEND',   color=1)    # red (dashed)
    doc.layers.add('FACE',   color=5)    # blue
    doc.layers.add('LABELS', color=7)    # white

    if 'DASHED' not in doc.linetypes:
        doc.linetypes.add('DASHED', pattern=[8.0, -4.0])
    da = {'linetype': 'DASHED', 'ltscale': 5.0}

    # CUT — simple outer rectangle
    msp.add_lwpolyline(
        [(0, 0), (flat_w, 0), (flat_w, flat_h), (0, flat_h)],
        close=True, dxfattribs={'layer': 'CUT'},
    )

    # BEND — left / right outer returns
    msp.add_line((d, 0), (d, flat_h), dxfattribs={'layer': 'BEND', **da})
    msp.add_line((flat_w - d, 0), (flat_w - d, flat_h), dxfattribs={'layer': 'BEND', **da})

    # BEND — horizontal top / bottom return lines
    msp.add_line((0, d),          (flat_w, d),          dxfattribs={'layer': 'BEND', **da})
    msp.add_line((0, flat_h - d), (flat_w, flat_h - d), dxfattribs={'layer': 'BEND', **da})

    # BEND — vertical lines at each arc boundary (two per corner: arc start, arc end)
    for bx_s, bx_e in zip(bend_start_xs, bend_end_xs):
        msp.add_line((bx_s, 0), (bx_s, flat_h), dxfattribs={'layer': 'BEND', **da})
        if abs(bx_e - bx_s) > 0.1:   # skip zero-width arcs (d=0)
            msp.add_line((bx_e, 0), (bx_e, flat_h), dxfattribs={'layer': 'BEND', **da})

    # FACE — outline for each wall face
    for i, fw in enumerate(faces):
        x0 = section_xs[i]
        msp.add_lwpolyline(
            [(x0, d), (x0 + fw, d), (x0 + fw, d + H), (x0, d + H)],
            close=True, dxfattribs={'layer': 'FACE'},
        )

    # LABELS — face widths and arc angles
    lbl_h = max(10.0, H * 0.05)
    for i, fw in enumerate(faces):
        x0 = section_xs[i]
        tag = chr(ord('A') + i) if i < 26 else str(i + 1)
        msp.add_text(
            f'{tag}={fw:.0f}mm',
            dxfattribs={'layer': 'LABELS', 'height': lbl_h,
                        'insert': (x0 + fw / 2, d + H / 2)},
        )
        if i < len(angles):
            arc_cx = bend_start_xs[i] + arc_ws[i] / 2
            msp.add_text(
                f'{angles[i]:.0f}°',
                dxfattribs={'layer': 'LABELS',
                            'height': max(8.0, lbl_h * 0.75),
                            'insert': (arc_cx, d + H * 0.35)},
            )

    # Overall dimension label
    n_corners = len(angles)
    msp.add_text(
        f'H={H:.0f}  d={d:.0f}  total={flat_w:.0f}×{flat_h:.0f}mm  '
        f'{len(faces)} faces  {n_corners} bend{"s" if n_corners != 1 else ""}',
        dxfattribs={'layer': 'LABELS', 'height': max(8.0, lbl_h * 0.75),
                    'insert': (0, -20)},
    )

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.dxf')
    os.close(tmp_fd)
    with open(tmp_path, 'w') as fh:
        doc.write(fh)
    background_tasks.add_task(os.unlink, tmp_path)
    fn = body.filename or 'multi_wrap.dxf'
    return FileResponse(tmp_path, media_type='application/octet-stream',
                        filename=fn,
                        headers={'Content-Disposition': f'attachment; filename="{fn}"'})


# ── AI Pattern Maker ──────────────────────────────────────────────────────────

def _analyze_for_pattern(img_gray: '_np.ndarray') -> dict:
    """Extract image features used to drive pattern generation."""
    from scipy.ndimage import gaussian_filter, sobel
    edges         = _sk_feature.canny(img_gray, sigma=2.0)
    edge_density  = float(edges.mean())
    contrast      = float(img_gray.std())
    dy            = sobel(img_gray, axis=0)
    dx            = sobel(img_gray, axis=1)
    magnitudes    = _np.hypot(dx, dy)
    angles        = _np.arctan2(dy, dx) % _np.pi
    hist, bins    = _np.histogram(angles.ravel(), bins=36, weights=magnitudes.ravel())
    best          = int(hist.argmax())
    dominant_ang  = float((bins[best] + bins[best + 1]) / 2 * 180.0 / _np.pi)
    sigma_bm      = max(3.0, min(img_gray.shape) * 0.05)
    brightness_map = gaussian_filter(img_gray, sigma=sigma_bm)
    return {
        'edge_density':       edge_density,
        'contrast':           contrast,
        'dominant_angle_deg': dominant_ang,
        'brightness_map':     brightness_map,
    }


def _gen_contour_relief(img_gray, detail, style, min_spacing, max_elements):
    """Luminance iso-contour lines at evenly-spaced brightness levels."""
    from scipy.ndimage import gaussian_filter
    n_levels = max(3, int(detail * 2))
    levels   = _np.linspace(0.08, 0.92, n_levels)
    sigma    = 1.5 if style in ('clean', 'geometric') else 3.0
    rdp_eps  = 0.8 if style in ('clean', 'geometric') else 2.5
    blurred  = gaussian_filter(img_gray, sigma=sigma)
    elements, warnings = [], []
    for li, level in enumerate(levels):
        for contour in _sk_measure.find_contours(blurred, level):
            if len(contour) < 3:
                continue
            idx = _rdp(_np.array(contour, dtype=float), rdp_eps)
            pts = [list(contour[k]) for k in idx]
            if len(pts) < 2:
                continue
            perim = sum(
                _np.hypot(pts[j+1][0] - pts[j][0], pts[j+1][1] - pts[j][1])
                for j in range(len(pts) - 1)
            )
            if perim < min_spacing * 2:
                continue
            elements.append({'type': 'polyline', 'points': pts, 'layer': 'PATTERN_CUT', 'level': li})
            if len(elements) >= max_elements:
                warnings.append(f'Element limit ({max_elements}) reached — some contours omitted')
                return elements, warnings
    return elements, warnings


def _gen_groove_pattern(img_gray, detail, style, min_spacing, max_elements, analysis):
    """Horizontal scan-line grooves with brightness-modulated spacing."""
    from scipy.ndimage import gaussian_filter
    h, w     = img_gray.shape
    smooth   = gaussian_filter(img_gray, sigma=max(1.5, min_spacing * 0.3))
    min_step = float(min_spacing)
    max_step = max(min_step * 1.5, min_step * (5.5 - detail * 0.4))
    elements, warnings = [], []
    if style in ('clean', 'geometric'):
        y = min_step / 2
        while y < h:
            row        = int(_np.clip(y, 0, h - 1))
            brightness = float(smooth[row, :].mean())
            elements.append({'type': 'line', 'x1': 0.0, 'y1': float(y),
                             'x2': float(w), 'y2': float(y), 'layer': 'PATTERN_GROOVE'})
            if len(elements) >= max_elements:
                warnings.append('Element limit reached')
                break
            y += max(min_step, min_step + brightness * (max_step - min_step))
    else:
        freq   = 2.0 * _np.pi / max(1.0, min_spacing * 4 + detail * 2)
        x_step = max(1, int(min_spacing * 0.5))
        y      = min_step / 2
        while y < h:
            row          = int(_np.clip(y, 0, h - 1))
            brightness_r = smooth[row, :]
            pts = []
            for x in range(0, int(w) + 1, x_step):
                col     = min(x, w - 1)
                local_b = float(brightness_r[col])
                amp     = (1.0 - local_b) * min_spacing * 0.6
                pts.append([float(y + amp * _np.sin(x * freq)), float(x)])
            if len(pts) >= 2:
                elements.append({'type': 'polyline', 'points': pts, 'layer': 'PATTERN_GROOVE', 'level': 0})
            avg_b = float(brightness_r.mean())
            y    += max(min_step, min_step + avg_b * (max_step - min_step))
            if len(elements) >= max_elements:
                warnings.append('Element limit reached')
                break
    return elements, warnings


def _gen_perforation(img_gray, detail, style, min_spacing, min_hole_size, max_elements):
    """Grid of circles sized by local brightness — drilling/perforation pattern."""
    from scipy.ndimage import gaussian_filter
    h, w    = img_gray.shape
    smooth  = gaussian_filter(img_gray, sigma=max(1.5, min_spacing * 0.4))
    cell    = float(min_spacing)
    max_r   = cell * 0.45
    min_r   = max(min_hole_size / 2.0, 0.5)
    use_hex = style in ('organic', 'facade')
    elements, warnings = [], []
    row_i, cy = 0, cell / 2
    while cy < h:
        cx_off = (cell / 2) if (use_hex and row_i % 2 == 1) else 0.0
        cx     = cx_off + cell / 2
        while cx < w:
            ri = int(_np.clip(cy, 0, h - 1))
            ci = int(_np.clip(cx, 0, w - 1))
            brightness = float(smooth[ri, ci])
            r = min_r + (1.0 - brightness) * (max_r - min_r)
            if r >= min_r:
                elements.append({'type': 'circle', 'cx': float(cx), 'cy': float(cy),
                                 'r': round(r, 2), 'layer': 'PATTERN_HOLES'})
                if len(elements) >= max_elements:
                    warnings.append('Element limit reached')
                    break
            cx += cell
        cy += cell;  row_i += 1
        if len(elements) >= max_elements:
            break
    return elements, warnings


def _gen_facade(img_gray, detail, style, min_spacing, max_elements, panel_shape):
    """Geometric tiling where cells are drawn or scaled according to brightness."""
    from scipy.ndimage import gaussian_filter
    h, w      = img_gray.shape
    smooth    = gaussian_filter(img_gray, sigma=max(2.0, min_spacing * 0.5))
    threshold = 0.5
    elements, warnings = [], []

    def _sample(cy, cx):
        return float(smooth[int(_np.clip(cy, 0, h - 1)), int(_np.clip(cx, 0, w - 1))])

    if panel_shape == 'hexagon':
        R     = min_spacing * 0.55
        col_w = R * _np.sqrt(3)
        row_h = R * 1.5

        def _hex(cx, cy, r):
            pts = [[cy + r * _np.sin(_np.radians(60 * k)),
                    cx + r * _np.cos(_np.radians(60 * k))] for k in range(6)]
            pts.append(pts[0])
            return pts

        row_i, cy = 0, R
        while cy - R < h + R:
            cx = ((col_w / 2) if row_i % 2 == 1 else 0.0) + col_w / 2
            while cx - R < w + R:
                b = _sample(cy, cx)
                if style in ('clean', 'geometric'):
                    if b < threshold:
                        elements.append({'type': 'polyline', 'points': _hex(cx, cy, R),
                                         'layer': 'PATTERN_CUT', 'level': 0})
                else:
                    sr = R * (0.25 + (1 - b) * 0.75)
                    if sr >= min_spacing * 0.12:
                        elements.append({'type': 'polyline', 'points': _hex(cx, cy, sr),
                                         'layer': 'PATTERN_CUT', 'level': 0})
                cx += col_w
                if len(elements) >= max_elements:
                    break
            cy += row_h;  row_i += 1
            if len(elements) >= max_elements:
                break

    elif panel_shape == 'triangle':
        side  = min_spacing * 1.2
        h_tri = side * _np.sqrt(3) / 2
        hs    = side / 2

        def _tri(cx, cy, up):
            if up:
                return [[cy, cx - hs], [cy, cx + hs], [cy - h_tri, cx], [cy, cx - hs]]
            return [[cy, cx - hs], [cy, cx + hs], [cy + h_tri, cx], [cy, cx - hs]]

        cy = 0.0
        while cy < h + h_tri:
            cx = 0.0
            while cx < w + side:
                for up in (True, False):
                    pts = _tri(cx, cy, up)
                    ccy = (pts[0][0] + pts[1][0] + pts[2][0]) / 3
                    ccx = (pts[0][1] + pts[1][1] + pts[2][1]) / 3
                    if _sample(ccy, ccx) < threshold:
                        elements.append({'type': 'polyline', 'points': pts,
                                         'layer': 'PATTERN_CUT', 'level': 0})
                    if len(elements) >= max_elements:
                        break
                cx += side
                if len(elements) >= max_elements:
                    break
            cy += h_tri
            if len(elements) >= max_elements:
                break

    elif panel_shape == 'diamond':
        d = min_spacing * 0.9

        def _diamond(cx, cy, r):
            return [[cy - r, cx], [cy, cx + r], [cy + r, cx], [cy, cx - r], [cy - r, cx]]

        row_i, cy = 0, d
        while cy < h + d:
            cx = (d if row_i % 2 == 1 else 0.0) + d
            while cx < w + d:
                b = _sample(cy, cx)
                if b < threshold:
                    r = d * (0.5 + (1 - b) * 0.5) if style == 'organic' else d
                    elements.append({'type': 'polyline', 'points': _diamond(cx, cy, r),
                                     'layer': 'PATTERN_CUT', 'level': 0})
                cx += d * 2
                if len(elements) >= max_elements:
                    break
            cy += d;  row_i += 1
            if len(elements) >= max_elements:
                break

    elif panel_shape == 'wave':
        amp_base = min_spacing * 0.5
        freq     = 2.0 * _np.pi / max(1.0, min_spacing * 3)
        x_step   = max(1, int(min_spacing * 0.4))
        y        = min_spacing / 2
        while y < h:
            pts = []
            for x in range(0, int(w) + 1, x_step):
                b   = _sample(y, x)
                amp = amp_base * (1.0 - b) * 1.5
                pts.append([y + amp * _np.sin(x * freq), float(x)])
            if len(pts) >= 2:
                elements.append({'type': 'polyline', 'points': pts, 'layer': 'PATTERN_CUT', 'level': 0})
            y += min_spacing
            if len(elements) >= max_elements:
                break

    if len(elements) >= max_elements:
        warnings.append(f'Element limit ({max_elements}) reached')
    return elements, warnings


def _render_pattern_preview(elements: list, w: int, h: int, img_gray=None) -> str:
    """Render pattern elements onto a dark PIL image → base64 PNG data-URI."""
    from PIL import ImageDraw
    canvas = _PIL.new('RGB', (w, h), (8, 8, 18))
    if img_gray is not None:
        ghost_u8 = (_np.clip(img_gray, 0, 1) * 30).astype(_np.uint8)
        ghost    = _PIL.fromarray(ghost_u8, 'L').convert('RGB')
        blended  = (_np.array(canvas, dtype=float) * 0.7
                    + _np.array(ghost,  dtype=float) * 0.3).astype(_np.uint8)
        canvas   = _PIL.fromarray(blended, 'RGB')
    draw = ImageDraw.Draw(canvas)
    layer_colors = {
        'PATTERN_CUT':     (34,  211, 238),
        'PATTERN_GROOVE':  (167, 139, 250),
        'PATTERN_HOLES':   (74,  222, 128),
        'ANALYSIS_GUIDES': (251, 146,  60),
    }
    for el in elements:
        color = layer_colors.get(el.get('layer', 'PATTERN_CUT'), (180, 180, 180))
        et    = el.get('type')
        if et == 'polyline':
            pts_xy = [(float(p[1]), float(p[0])) for p in el['points']]
            if len(pts_xy) >= 2:
                draw.line(pts_xy, fill=color, width=1)
        elif et == 'circle':
            cx, cy, r = el['cx'], el['cy'], el['r']
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=1)
        elif et == 'line':
            draw.line([(el['x1'], el['y1']), (el['x2'], el['y2'])], fill=color, width=1)
    return _encode_png(_np.array(canvas))


def _run_fabrication_checks(elements, pattern_type, min_spacing, min_hole_size, scale, img_w, img_h):
    """scale = mm per pixel; returns fabrication readiness dict."""
    OP_MAP = {
        'perforation':    ('Drilling',              'CNC drilling — variable hole grid'),
        'groove':         ('Groove routing',        'Ball-end / V-groove routing along scan lines'),
        'contour_relief': ('Multi-level engraving', 'Multi-pass contour engraving across brightness levels'),
        'facade':         ('Contour cutting',       'Through-cut geometric panel openings'),
    }
    op_type, op_label = OP_MAP.get(pattern_type, ('Unknown', 'Unknown operation'))
    checks = []
    feed_rate = 3000.0   # mm/min conservative
    setup_min = 10.0

    circles    = [e for e in elements if e.get('type') == 'circle']
    path_els   = [e for e in elements if e.get('type') in ('line', 'polyline')]

    total_path_mm = 0.0
    for el in path_els:
        if el['type'] == 'line':
            dx = (el['x2'] - el['x1']) * scale
            dy = (el['y2'] - el['y1']) * scale
            total_path_mm += (dx**2 + dy**2) ** 0.5
        else:
            pts = el['points']
            for i in range(len(pts) - 1):
                dx = (pts[i + 1][1] - pts[i][1]) * scale
                dy = (pts[i + 1][0] - pts[i][0]) * scale
                total_path_mm += (dx**2 + dy**2) ** 0.5

    estimated_time_min = round(setup_min + len(circles) * 3.5 / 60.0 + total_path_mm / feed_rate, 1)

    # 1 — Hole diameter (perforation only)
    if pattern_type == 'perforation' and circles:
        min_diam_mm = min(e['r'] for e in circles) * 2 * scale
        if min_diam_mm < 2.0:
            checks.append({'severity': 'error',   'code': 'hole_too_small',
                'message': f'Smallest hole is {min_diam_mm:.1f} mm — absolute minimum drill diameter is 2 mm'})
        elif min_diam_mm < 3.0:
            checks.append({'severity': 'warning', 'code': 'hole_below_safe',
                'message': f'Smallest hole is {min_diam_mm:.1f} mm — recommended safe minimum is 3 mm'})
        else:
            checks.append({'severity': 'ok',      'code': 'hole_diameter',
                'message': f'Hole diameters OK (min {min_diam_mm:.1f} mm)'})

    # 2 — Hole clearance (perforation only)
    if pattern_type == 'perforation' and circles:
        max_r_px     = max(e['r'] for e in circles)
        clearance_mm = (min_spacing - 2 * max_r_px) * scale
        if clearance_mm < 0.5:
            checks.append({'severity': 'error',   'code': 'holes_too_close',
                'message': f'Hole clearance is {clearance_mm:.1f} mm — risk of material breakout'})
        elif clearance_mm < 1.5:
            checks.append({'severity': 'warning', 'code': 'holes_close',
                'message': f'Hole clearance is {clearance_mm:.1f} mm — consider increasing Min Spacing'})
        else:
            checks.append({'severity': 'ok',      'code': 'hole_spacing',
                'message': f'Hole clearance OK ({clearance_mm:.1f} mm)'})

    # 3 — Groove line spacing (groove only)
    if pattern_type == 'groove':
        spacing_mm = min_spacing * scale
        if spacing_mm < 2.0:
            checks.append({'severity': 'error',   'code': 'grooves_too_close',
                'message': f'Groove spacing is {spacing_mm:.1f} mm — minimum recommended is 2 mm'})
        elif spacing_mm < 4.0:
            checks.append({'severity': 'warning', 'code': 'grooves_close',
                'message': f'Groove spacing is {spacing_mm:.1f} mm — tight for router; consider 4 mm+'})
        else:
            checks.append({'severity': 'ok',      'code': 'groove_spacing',
                'message': f'Groove spacing OK ({spacing_mm:.1f} mm)'})

    # 4 — Tiny contours (contour_relief and facade)
    if pattern_type in ('contour_relief', 'facade'):
        min_perim_mm = max(3.0, min_spacing * 2 * scale)
        tiny = []
        for el in elements:
            if el.get('type') == 'polyline':
                pts  = el['points']
                perim = sum(
                    ((pts[i + 1][1] - pts[i][1])**2 + (pts[i + 1][0] - pts[i][0])**2) ** 0.5
                    for i in range(len(pts) - 1)
                ) * scale
                if perim < min_perim_mm:
                    tiny.append(perim)
        if tiny:
            pct = len(tiny) / max(1, len(elements)) * 100
            if pct > 20:
                checks.append({'severity': 'error',   'code': 'tiny_contours',
                    'message': f'{len(tiny)} contours ({pct:.0f}%) too small (<{min_perim_mm:.1f} mm) — increase Min Spacing or Detail'})
            else:
                checks.append({'severity': 'warning', 'code': 'tiny_contours',
                    'message': f'{len(tiny)} tiny contours (<{min_perim_mm:.1f} mm) — some may not cut cleanly'})
        else:
            checks.append({'severity': 'ok', 'code': 'contour_size',
                'message': 'Contour sizes OK'})

    # 5 — CNC time
    if estimated_time_min > 120:
        checks.append({'severity': 'error',   'code': 'cnc_time',
            'message': f'Estimated time is {estimated_time_min:.0f} min — reduce Max Elements or increase Min Spacing'})
    elif estimated_time_min > 45:
        checks.append({'severity': 'warning', 'code': 'cnc_time',
            'message': f'Estimated time is {estimated_time_min:.0f} min — consider reducing complexity'})
    else:
        checks.append({'severity': 'ok',      'code': 'cnc_time',
            'message': f'Estimated CNC time: {estimated_time_min:.0f} min'})

    # 6 — Sheet size (standard 2440 × 1220 mm)
    pw_mm, ph_mm = img_w * scale, img_h * scale
    if pw_mm > 2440 or ph_mm > 1220:
        checks.append({'severity': 'error',   'code': 'sheet_size',
            'message': f'Pattern is {pw_mm:.0f}×{ph_mm:.0f} mm — exceeds standard sheet (2440×1220 mm)'})
    elif pw_mm > 2196 or ph_mm > 1098:
        checks.append({'severity': 'warning', 'code': 'sheet_size',
            'message': f'Pattern is {pw_mm:.0f}×{ph_mm:.0f} mm — close to sheet edge (2440×1220 mm)'})
    else:
        checks.append({'severity': 'ok',      'code': 'sheet_size',
            'message': f'Pattern fits on sheet ({pw_mm:.0f}×{ph_mm:.0f} mm)'})

    return {
        'operation_type':     op_type,
        'operation_label':    op_label,
        'estimated_time_min': estimated_time_min,
        'checks':             checks,
    }


class AiPatternExportRequest(BaseModel):
    elements:     list
    image_width:  int
    image_height: int
    scale:        float = 1.0
    filename:     str   = 'pattern.dxf'


@app.post('/photo-to-dxf/ai-pattern')
async def photo_ai_pattern(
    file:           UploadFile = File(...),
    pattern_type:   str   = Form('contour_relief'),
    style:          str   = Form('clean'),
    detail:         float = Form(5.0),
    min_spacing:    float = Form(8.0),
    min_hole_size:  float = Form(4.0),
    max_elements:   int   = Form(1500),
    panel_shape:    str   = Form('hexagon'),
    blur:           float = Form(1.0),
    invert:         bool  = Form(False),
    scale_mm_per_px: float = Form(1.0),
):
    from scipy.ndimage import gaussian_filter
    data     = await file.read()
    img_pil  = _PIL.open(_io.BytesIO(data)).convert('RGB')
    img_rgb  = _np.array(img_pil, dtype=float) / 255.0
    img_gray = (0.2126 * img_rgb[:, :, 0]
              + 0.7152 * img_rgb[:, :, 1]
              + 0.0722 * img_rgb[:, :, 2])
    h, w = img_gray.shape
    if blur > 0:
        img_gray = gaussian_filter(img_gray, sigma=blur)
    if invert:
        img_gray = 1.0 - img_gray
    analysis = _analyze_for_pattern(img_gray)
    all_warnings: list = []
    if pattern_type == 'contour_relief':
        elements, warns = _gen_contour_relief(img_gray, detail, style, min_spacing, max_elements)
    elif pattern_type == 'groove':
        elements, warns = _gen_groove_pattern(img_gray, detail, style, min_spacing, max_elements, analysis)
    elif pattern_type == 'perforation':
        elements, warns = _gen_perforation(img_gray, detail, style, min_spacing, min_hole_size, max_elements)
    elif pattern_type == 'facade':
        elements, warns = _gen_facade(img_gray, detail, style, min_spacing, max_elements, panel_shape)
    else:
        raise HTTPException(status_code=400, detail=f'Unknown pattern_type: {pattern_type}')
    all_warnings.extend(warns)
    n_by_layer: dict = {}
    for el in elements:
        lyr = el.get('layer', 'PATTERN_CUT')
        n_by_layer[lyr] = n_by_layer.get(lyr, 0) + 1
    preview_image = _render_pattern_preview(elements, w, h, img_gray)
    bmap_u8       = (analysis['brightness_map'] * 255).astype(_np.uint8)
    fabrication   = _run_fabrication_checks(
        elements, pattern_type, min_spacing, min_hole_size, scale_mm_per_px, w, h
    )
    return JSONResponse({
        'pattern_type': pattern_type,
        'style':        style,
        'n_elements':   len(elements),
        'n_by_layer':   n_by_layer,
        'image_width':  w,
        'image_height': h,
        'analysis': {
            'edge_density':       round(analysis['edge_density'],       4),
            'contrast':           round(analysis['contrast'],           4),
            'dominant_angle_deg': round(analysis['dominant_angle_deg'], 1),
            'brightness_map':     _encode_png(bmap_u8),
        },
        'elements':      elements,
        'preview_image': preview_image,
        'warnings':      all_warnings,
        'fabrication':   fabrication,
    })


@app.post('/photo-to-dxf/export-ai-pattern')
async def export_ai_pattern(req: AiPatternExportRequest):
    import ezdxf
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    for lname, lcolor in {
        'PATTERN_CUT':     4,
        'PATTERN_GROOVE':  6,
        'PATTERN_HOLES':   3,
        'ANALYSIS_GUIDES': 2,
    }.items():
        if doc.layers.get(lname) is None:
            doc.layers.new(lname, dxfattribs={'color': lcolor})
    img_h = float(req.image_height)
    s     = float(req.scale)
    for el in req.elements:
        layer = el.get('layer', 'PATTERN_CUT')
        et    = el.get('type')
        if et == 'polyline':
            pts = [(p[1] * s, (img_h - p[0]) * s) for p in el['points']]
            if len(pts) >= 2:
                msp.add_lwpolyline(pts, dxfattribs={'layer': layer})
        elif et == 'circle':
            msp.add_circle(
                (el['cx'] * s, (img_h - el['cy']) * s),
                el['r'] * s,
                dxfattribs={'layer': layer},
            )
        elif et == 'line':
            msp.add_line(
                (el['x1'] * s, (img_h - el['y1']) * s),
                (el['x2'] * s, (img_h - el['y2']) * s),
                dxfattribs={'layer': layer},
            )
    buf = _io.BytesIO()
    doc.write(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type='application/dxf',
        headers={'Content-Disposition': f'attachment; filename="{req.filename}"'},
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('api:app', host='0.0.0.0', port=8000, reload=True)
