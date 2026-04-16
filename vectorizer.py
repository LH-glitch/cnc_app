"""
vectorizer.py — Image → preview_engine entity pipeline.

Pure functions. No GUI state, no side effects. Caller is responsible for I/O.

Pipeline
--------
  load/normalise → denoise → edge detect → find contours →
  filter by area → simplify (Douglas-Peucker) → convert to entity dicts

Entry points
------------
  vectorize(image, ...)            → List[Dict]  (preview_engine format)
  vectorize_to_dxf(image, path)    → int  (entity count)

Dependencies: opencv-python, numpy (optional — raises ImportError if absent)
"""

from typing import Dict, List, Optional, Tuple, Union
import math
import entity_model as em


# ── Public API ────────────────────────────────────────────────────────────────

def vectorize(
    image,                              # file path str, OR numpy/cv2 array
    threshold1:        float = 50.0,    # Canny lower threshold
    threshold2:        float = 150.0,   # Canny upper threshold
    min_contour_area:  float = 100.0,   # minimum area in pixels² to keep
    epsilon_factor:    float = 0.01,    # D-P tolerance as fraction of perimeter
    scale_px_to_mm:    float = 1.0,     # pixels → mm scale factor
    blur_kernel:       int   = 3,       # Gaussian blur kernel size (odd)
    max_entities:      int   = 2000,    # safety cap on output entities
) -> List[Dict]:
    """
    Convert an image to a list of preview_engine entity dicts (polylines on CUT layer).

    Parameters
    ----------
    image           : file path (str) or numpy ndarray (BGR or grayscale)
    threshold1/2    : Canny edge detection thresholds
    min_contour_area: contours smaller than this (px²) are discarded
    epsilon_factor  : Douglas-Peucker simplification (fraction of perimeter)
    scale_px_to_mm  : multiply pixel coords by this to get mm
    blur_kernel     : Gaussian pre-blur kernel size (forced odd)
    max_entities    : hard cap on number of output entities

    Returns
    -------
    List of {'type': 'polyline', 'points': [...], 'layer': 'CUT'} dicts.
    """
    cv2, np = _require_cv()

    # ── 1. Load / normalise ─────────────────────────────────────────────────
    gray = _to_gray(image, cv2, np)
    h_px, w_px = gray.shape

    # ── 2. Denoise ──────────────────────────────────────────────────────────
    k = blur_kernel | 1       # ensure odd
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

    # ── 3. Edge detection ───────────────────────────────────────────────────
    edges = cv2.Canny(blurred, threshold1, threshold2)

    # ── 4. Find contours ────────────────────────────────────────────────────
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

    # ── 5. Simplify, filter, convert ────────────────────────────────────────
    entities: List[Dict] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_contour_area:
            continue

        perimeter = cv2.arcLength(contour, closed=False)
        epsilon   = epsilon_factor * max(perimeter, 1.0)
        simplified = cv2.approxPolyDP(contour, epsilon, closed=False)

        # Pixel → world (mm), flip Y so origin is bottom-left
        pts: List[Tuple[float, float]] = [
            (float(pt[0][0]) * scale_px_to_mm,
             (h_px - float(pt[0][1])) * scale_px_to_mm)
            for pt in simplified
        ]

        if len(pts) >= 2:
            entities.append(em.make_polyline(pts, layer=em.LAYER_CUT, source=em.SOURCE_IMAGE))
            if len(entities) >= max_entities:
                break

    return entities


def detect_circles(
    image,
    min_radius:  float = 5.0,    # minimum circle radius in px
    max_radius:  float = 500.0,
    scale_px_to_mm: float = 1.0,
    blur_kernel: int = 5,
) -> List[Dict]:
    """
    Detect circles in an image using Hough Circle Transform.

    Returns circle entity dicts on layer 'HOLES'.
    """
    cv2, np = _require_cv()
    gray = _to_gray(image, cv2, np)
    k    = blur_kernel | 1
    blurred = cv2.GaussianBlur(gray, (k, k), 0)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(min_radius * 2, 10),
        param1=100,
        param2=30,
        minRadius=int(min_radius),
        maxRadius=int(max_radius),
    )

    entities: List[Dict] = []
    if circles is not None:
        h_px = gray.shape[0]
        for cx, cy, r in circles[0]:
            entities.append(em.make_circle(
                center=(float(cx) * scale_px_to_mm,
                        (h_px - float(cy)) * scale_px_to_mm),
                radius=float(r) * scale_px_to_mm,
                layer=em.LAYER_HOLES,
                source=em.SOURCE_IMAGE,
            ))
    return entities


def vectorize_combined(
    image,
    detect_lines_only: bool = True,
    detect_circles_also: bool = False,
    **kwargs,
) -> List[Dict]:
    """
    Convenience: run vectorize() and optionally detect_circles().
    Returns combined entity list.
    """
    entities = vectorize(image, **{k: v for k, v in kwargs.items()
                                   if k in vectorize.__code__.co_varnames})
    if detect_circles_also:
        scale = kwargs.get('scale_px_to_mm', 1.0)
        entities += detect_circles(image, scale_px_to_mm=scale)
    return entities


def vectorize_to_dxf(
    image,
    output_path: str,
    **kwargs,
) -> int:
    """
    Vectorize an image and save directly to a DXF file.

    Returns the number of entities written.
    """
    import ezdxf
    from layers import LayerManager

    entities = vectorize(image, **kwargs)

    doc = ezdxf.new()
    LayerManager(doc)
    msp = doc.modelspace()

    for entity in entities:
        if entity['type'] == 'polyline' and len(entity['points']) >= 2:
            poly = msp.add_lwpolyline(entity['points'])
            poly.dxf.layer = LayerManager.CUT_LAYER
        elif entity['type'] == 'circle':
            c = msp.add_circle(entity['center'], entity['radius'])
            c.dxf.layer = LayerManager.HOLES_LAYER

    doc.saveas(output_path)
    return len(entities)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require_cv():
    """Import cv2 + numpy or raise a clear ImportError."""
    try:
        import cv2
        import numpy as np
        return cv2, np
    except ImportError:
        raise ImportError(
            "vectorizer requires opencv-python and numpy.\n"
            "Install with:  pip install opencv-python numpy"
        )


def _to_gray(image, cv2, np):
    """Load or convert image to grayscale numpy array."""
    if isinstance(image, str):
        img = cv2.imread(image)
        if img is None:
            raise ValueError(f"Could not load image: {image!r}")
    else:
        img = np.array(image)

    if img.ndim == 3 and img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    if img.ndim == 2:
        return img.astype('uint8')
    raise ValueError(f"Unsupported image shape: {img.shape}")


# ── Scale estimation ──────────────────────────────────────────────────────────

def estimate_scale(image_width_px: int, target_width_mm: float) -> float:
    """
    Given the pixel width of an image and the known real-world width (mm),
    return the scale factor (mm per pixel).
    """
    if image_width_px <= 0:
        raise ValueError("image_width_px must be positive")
    return target_width_mm / image_width_px
