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

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],   # tighten in production
    allow_methods=['*'],
    allow_headers=['*'],
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
    summary='Slice an STL file into boards',
    response_description='Server-Sent Events stream of progress and result',
)
async def slice_endpoint(
    file:           UploadFile        = File(...,   description='STL file to slice'),
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
    Upload an STL file and slicing parameters.

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
    # Buffer upload to a temp file so the background thread can read it safely.
    ext     = os.path.splitext(file.filename or '')[1] or '.stl'
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


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('api:app', host='0.0.0.0', port=8000, reload=True)
