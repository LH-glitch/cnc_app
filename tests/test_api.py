"""
tests/test_api.py — Integration tests for api.py

Uses FastAPI's TestClient (no real HTTP server needed).

Run:
    python -m pytest tests/test_api.py -v
"""

import json
import os
import sys
import struct
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient
from api import app, result_to_json, result_from_json
import slicer as _slicer

client = TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stl_bytes(triangles) -> bytes:
    """Write a minimal binary STL from a (N, 3, 3) triangle array."""
    import numpy as np
    tris = np.asarray(triangles, dtype='<f4')
    n    = len(tris)
    buf  = bytearray(80 + 4 + n * 50)
    struct.pack_into('<I', buf, 80, n)
    off = 84
    for tri in tris:
        normal = [0.0, 0.0, 0.0]
        struct.pack_into('<3f', buf, off, *normal)
        off += 12
        for v in tri:
            struct.pack_into('<3f', buf, off, *v)
            off += 12
        struct.pack_into('<H', buf, off, 0)
        off += 2
    return bytes(buf)


def _box_stl_bytes(w=100.0, h=80.0, d=60.0) -> bytes:
    """Binary STL for a box mesh."""
    tris = _slicer.mesh_from_box(w, h, d)
    return _make_stl_bytes(tris)


def _slice_via_api(
    stl_bytes: bytes,
    slab_mode: str = 'best_sample',
    quality: str = 'fast',
    thickness: float = 20.0,
) -> dict:
    """
    POST /slice and collect all SSE events.  Returns the 'data' dict from
    the final 'result' event.  Raises AssertionError on error event.
    """
    resp = client.post(
        '/slice',
        files={'file': ('test.stl', stl_bytes, 'application/octet-stream')},
        data={
            'axis':      'y',
            'slab_mode': slab_mode,
            'quality':   quality,
            'slice_mode': 'thickness',
            'thickness':  str(thickness),
            'add_alignment': 'true',
            'dowel_radius':  '3.0',
            'n_holes':       '4',
        },
    )
    assert resp.status_code == 200, resp.text
    assert 'text/event-stream' in resp.headers['content-type']

    result_data = None
    for line in resp.text.splitlines():
        if not line.startswith('data:'):
            continue
        event = json.loads(line[5:].strip())
        if event['type'] == 'error':
            raise AssertionError(f"API returned error: {event['message']}")
        if event['type'] == 'result':
            result_data = event['data']

    assert result_data is not None, 'No result event in SSE stream'
    return result_data


# ── Serialization round-trip ─────────────────────────────────────────────────

def test_result_to_json_structure():
    r = _slicer.slice_model(_slicer.mesh_from_box(100, 80, 60), 20.0)
    d = result_to_json(r)
    assert isinstance(d['board_thickness'], float)
    assert isinstance(d['n_boards'], int)
    assert isinstance(d['slices'], list)
    assert len(d['slices']) == r.n_boards
    assert 'contours' in d['slices'][0]


def test_result_roundtrip_preserves_values():
    r = _slicer.slice_model(_slicer.mesh_from_box(100, 80, 60), 20.0)
    d = result_to_json(r)
    r2 = result_from_json(d)
    assert r2.n_boards == r.n_boards
    assert abs(r2.board_thickness - r.board_thickness) < 1e-6
    assert r2.stacking_axis == r.stacking_axis
    assert r2.slab_mode == r.slab_mode


def test_result_roundtrip_contours():
    r = _slicer.slice_model(_slicer.mesh_from_box(100, 80, 60), 20.0)
    d = result_to_json(r)
    r2 = result_from_json(d)
    for s_orig, s_rt in zip(r.slices, r2.slices):
        assert len(s_rt.contours) == len(s_orig.contours)
        # Every point should round-trip to within float32 precision
        for c_orig, c_rt in zip(s_orig.contours, s_rt.contours):
            for (x0, z0), (x1, z1) in zip(c_orig, c_rt):
                assert abs(x0 - x1) < 1e-6
                assert abs(z0 - z1) < 1e-6


def test_result_to_json_all_python_types():
    """No numpy scalars — JSON must serialize without a custom encoder."""
    r = _slicer.slice_model(_slicer.mesh_from_box(100, 80, 60), 20.0)
    d = result_to_json(r)
    json.dumps(d)   # raises TypeError if any non-serializable value sneaks in


def test_result_from_json_rejects_bad_payload():
    import pytest
    with pytest.raises((KeyError, TypeError, ValueError)):
        result_from_json({'bad': 'payload'})


# ── GET /health ───────────────────────────────────────────────────────────────

def test_health():
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'ok'


# ── POST /slice — SSE stream ─────────────────────────────────────────────────

def test_slice_returns_sse_content_type():
    resp = client.post(
        '/slice',
        files={'file': ('box.stl', _box_stl_bytes(), 'application/octet-stream')},
        data={'slab_mode': 'best_sample', 'quality': 'fast'},
    )
    assert resp.status_code == 200
    assert 'text/event-stream' in resp.headers['content-type']


def test_slice_stream_contains_progress_events():
    resp = client.post(
        '/slice',
        files={'file': ('box.stl', _box_stl_bytes(), 'application/octet-stream')},
        data={'slab_mode': 'best_sample', 'quality': 'fast', 'thickness': '20'},
    )
    events = [
        json.loads(line[5:].strip())
        for line in resp.text.splitlines()
        if line.startswith('data:')
    ]
    progress = [e for e in events if e['type'] == 'progress']
    assert len(progress) > 0
    assert all('done' in e and 'total' in e for e in progress)


def test_slice_stream_ends_with_result_event():
    data = _slice_via_api(_box_stl_bytes())
    assert 'slices' in data
    assert 'board_thickness' in data
    assert 'n_boards' in data


def test_slice_result_board_count():
    data = _slice_via_api(_box_stl_bytes(h=80), thickness=20.0)
    assert data['n_boards'] == 4


def test_slice_result_includes_alignment_holes():
    """add_alignment=true should add extra (tiny) contours to slices."""
    data = _slice_via_api(_box_stl_bytes(w=100, h=80, d=60), thickness=20.0)
    # At least one board should have >1 contour (outer profile + alignment holes)
    has_extra = any(len(s['contours']) > 1 for s in data['slices'])
    assert has_extra, 'Expected alignment contours in at least one board'


def test_slice_with_count_mode():
    resp = client.post(
        '/slice',
        files={'file': ('box.stl', _box_stl_bytes(), 'application/octet-stream')},
        data={
            'slab_mode':  'best_sample',
            'quality':    'fast',
            'slice_mode': 'count',
            'n_boards':   '5',
        },
    )
    events = [
        json.loads(line[5:].strip())
        for line in resp.text.splitlines()
        if line.startswith('data:')
    ]
    result_events = [e for e in events if e['type'] == 'result']
    assert result_events, 'No result event'
    assert result_events[0]['data']['n_boards'] == 5


def test_slice_invalid_axis_returns_error_event():
    resp = client.post(
        '/slice',
        files={'file': ('box.stl', _box_stl_bytes(), 'application/octet-stream')},
        data={'axis': 'w', 'quality': 'fast'},   # invalid axis
    )
    events = [
        json.loads(line[5:].strip())
        for line in resp.text.splitlines()
        if line.startswith('data:')
    ]
    error_events = [e for e in events if e['type'] == 'error']
    assert error_events, 'Expected an error event for invalid axis'


# ── GET /jobs/{id}/result — polling ──────────────────────────────────────────

def test_job_result_unknown_id_returns_404():
    resp = client.get('/jobs/does-not-exist/result')
    assert resp.status_code == 404


def test_job_result_returns_200_after_sse_completes():
    """After reading the full SSE stream the job result must be accessible."""
    # POST /slice — TestClient reads the full stream synchronously
    resp = client.post(
        '/slice',
        files={'file': ('box.stl', _box_stl_bytes(), 'application/octet-stream')},
        data={'slab_mode': 'best_sample', 'quality': 'fast'},
    )
    job_id = None
    for line in resp.text.splitlines():
        if line.startswith('data:'):
            ev = json.loads(line[5:].strip())
            if ev['type'] == 'result':
                job_id = ev['job_id']

    assert job_id is not None
    poll = client.get(f'/jobs/{job_id}/result')
    assert poll.status_code == 200
    assert 'n_boards' in poll.json()


# ── POST /export_dxf ─────────────────────────────────────────────────────────

def test_export_dxf_returns_file():
    data = _slice_via_api(_box_stl_bytes())
    resp = client.post('/export_dxf', json={'result': data})
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'application/octet-stream'
    assert len(resp.content) > 100    # non-empty binary


def test_export_dxf_content_is_valid_dxf():
    """The returned bytes must start with a valid DXF header."""
    data = _slice_via_api(_box_stl_bytes())
    resp = client.post('/export_dxf', json={'result': data})
    # DXF files start with "0\nSECTION" or similar ASCII header
    text = resp.content[:200].decode('utf-8', errors='replace')
    assert '0' in text and 'SECTION' in text, 'Response does not look like a DXF file'


def test_export_dxf_with_sheet_layout():
    data = _slice_via_api(_box_stl_bytes(h=80), thickness=20.0)
    resp = client.post('/export_dxf', json={
        'result':       data,
        'sheet_width':  600.0,
        'sheet_height': 300.0,
        'sheet_spacing': 10.0,
    })
    assert resp.status_code == 200
    assert len(resp.content) > 100


def test_export_dxf_bad_payload_returns_400():
    resp = client.post('/export_dxf', json={'result': {'bad': 'data'}})
    assert resp.status_code == 400


def test_export_dxf_custom_filename_in_header():
    data = _slice_via_api(_box_stl_bytes())
    resp = client.post('/export_dxf', json={
        'result':   data,
        'filename': 'my_part.dxf',
    })
    assert resp.status_code == 200
    assert 'my_part.dxf' in resp.headers.get('content-disposition', '')


# ── POST /export_dxf_per_board ────────────────────────────────────────────────

def test_export_per_board_returns_zip():
    data = _slice_via_api(_box_stl_bytes())
    resp = client.post('/export_dxf_per_board', json={'result': data})
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'application/zip'


def test_export_per_board_zip_contains_correct_files():
    import zipfile
    import io
    data = _slice_via_api(_box_stl_bytes(h=80), thickness=20.0)  # 4 boards
    resp = client.post('/export_dxf_per_board', json={
        'result': data,
        'prefix': 'board',
    })
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert len(names) == data['n_boards']
    assert 'board_001.dxf' in names
    assert f'board_00{data["n_boards"]}.dxf' in names


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
