/**
 * lib/api.ts — All communication with the Python FastAPI backend.
 *
 * Components import from here only — no fetch() calls inline in UI code.
 * The backend URL comes from NEXT_PUBLIC_API_URL so it works locally
 * and on Vercel without changing code.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Shared types (mirrors api.py JSON shapes) ─────────────────────────────────

export interface BoardSlice {
  index: number;
  y_min: number;
  y_max: number;
  thickness: number;
  label: string;
  /** contours[i] = array of [x, z] points forming a closed polygon */
  contours: Array<Array<[number, number]>>;
}

export interface SliceResult {
  board_thickness: number;
  n_boards: number;
  stacking_axis: string;
  slab_mode: string;
  model_span: number;
  mesh_bounds: number[];
  slices: BoardSlice[];
}

export interface SliceProgress {
  done: number;
  total: number;
}

// ── Slice parameters (all optional — backend has sensible defaults) ───────────

export interface SliceParams {
  /** Stacking axis: 'x' | 'y' | 'z' — default 'y' */
  axis?: "x" | "y" | "z";
  /** Profile mode — 'envelope' is recommended for fabrication */
  slab_mode?: "envelope" | "best_sample";
  /** Quality preset — 'accurate' for final DXF, 'fast' for previews */
  quality?: "accurate" | "fast";
  /** Whether to slice by fixed thickness or fixed board count */
  slice_mode?: "thickness" | "count";
  /** Board thickness in mm (used when slice_mode = 'thickness') */
  thickness?: number;
  /** Number of boards (used when slice_mode = 'count') */
  n_boards?: number;
  /** Add dowel alignment holes */
  add_alignment?: boolean;
  /** Dowel hole radius in mm */
  dowel_radius?: number;
  /** 2 | 3 | 4 alignment holes */
  n_holes?: 2 | 3 | 4;
  /** Hole edge margin in mm — omit for auto 20 % inset */
  edge_margin_mm?: number;
}

// ── POST /slice  (SSE streaming) ──────────────────────────────────────────────

/**
 * Upload an STL file and stream slicing progress via Server-Sent Events.
 *
 * onProgress fires for each board processed.
 * Returns the full SliceResult when done.
 * Throws if the backend returns an error event or the network fails.
 */
export async function sliceModel(
  file: File,
  params: SliceParams = {},
  onProgress?: (p: SliceProgress) => void
): Promise<SliceResult> {
  const form = new FormData();
  form.append("file", file);

  // Map camelCase params to the snake_case form fields the backend expects
  const fields: Record<string, string> = {
    axis: params.axis ?? "y",
    slab_mode: params.slab_mode ?? "envelope",
    quality: params.quality ?? "accurate",
    slice_mode: params.slice_mode ?? "thickness",
    thickness: String(params.thickness ?? 20),
    n_boards: String(params.n_boards ?? 5),
    add_alignment: String(params.add_alignment ?? true),
    dowel_radius: String(params.dowel_radius ?? 3.0),
    n_holes: String(params.n_holes ?? 4),
  };
  if (params.edge_margin_mm != null) {
    fields.edge_margin_mm = String(params.edge_margin_mm);
  }
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));

  const resp = await fetch(`${BASE}/slice`, { method: "POST", body: form });
  if (!resp.ok) {
    throw new Error(`Backend returned ${resp.status}: ${await resp.text()}`);
  }
  if (!resp.body) throw new Error("No response body from /slice");

  // Read the SSE stream line by line
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // keep any incomplete line

    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;

      let event: { type: string; done?: number; total?: number; data?: SliceResult; message?: string };
      try {
        event = JSON.parse(raw);
      } catch {
        continue; // ignore malformed lines
      }

      if (event.type === "error") {
        throw new Error(event.message ?? "Unknown slicing error");
      }
      if (event.type === "progress" && onProgress) {
        onProgress({ done: event.done!, total: event.total! });
      }
      if (event.type === "result" && event.data) {
        return event.data;
      }
    }
  }

  throw new Error("Stream ended without a result event");
}

// ── POST /export_dxf  (combined DXF download) ─────────────────────────────────

export interface ExportOptions {
  layout_gap?: number;
  sheet_width?: number | null;
  sheet_height?: number | null;
  sheet_spacing?: number;
  filename?: string;
}

/**
 * Request a combined DXF and trigger a browser file download.
 * Returns the raw Blob for callers that want to handle it themselves.
 */
export async function exportDXF(
  result: SliceResult,
  opts: ExportOptions = {}
): Promise<Blob> {
  const body = {
    result,
    layout_gap: opts.layout_gap ?? 20,
    sheet_width: opts.sheet_width ?? null,
    sheet_height: opts.sheet_height ?? null,
    sheet_spacing: opts.sheet_spacing ?? 10,
    filename: opts.filename ?? "boards.dxf",
  };

  const resp = await fetch(`${BASE}/export_dxf`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`Export failed (${resp.status}): ${await resp.text()}`);
  }

  const blob = await resp.blob();
  triggerDownload(blob, getFilename(resp, opts.filename ?? "boards.dxf"));
  return blob;
}

// ── POST /export_dxf_per_board  (zip of individual DXFs) ──────────────────────

/**
 * Request a zip of per-board DXF files and trigger a browser download.
 */
export async function exportDXFPerBoard(
  result: SliceResult,
  opts: { prefix?: string; filename?: string } = {}
): Promise<Blob> {
  const body = {
    result,
    prefix: opts.prefix ?? "board",
    filename: opts.filename ?? "boards.zip",
  };

  const resp = await fetch(`${BASE}/export_dxf_per_board`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(
      `Per-board export failed (${resp.status}): ${await resp.text()}`
    );
  }

  const blob = await resp.blob();
  triggerDownload(blob, getFilename(resp, opts.filename ?? "boards.zip"));
  return blob;
}

// ── Photo → DXF ───────────────────────────────────────────────────────────────

export type TraceMode = "accurate" | "contour_art" | "stroke" | "halftone" | "one_line" | "ai_pattern";

export interface TraceParams {
  blur: number;        // 0–5  pre-blur (denoise)
  sensitivity: number; // 1–10 — edge sigma (accurate) or contour levels (contour_art)
  simplify: number;    // 0–15 RDP epsilon
  min_length: number;  // 5–80 minimum contour perimeter in px
  invert: boolean;
  mode: TraceMode;
}

/** Each contour is an array of [row, col] points (image coordinate space). */
export interface TraceResult {
  contours: [number, number][][];
  cleaned_image: string;   // grayscale + blur preview
  edges_image: string;     // Canny edges (accurate) or posterized bands (contour_art)
  preview_image: string;   // alias for edges_image (backward compat)
  n_contours: number;
  total_points: number;
  image_width: number;
  image_height: number;
  mode_used: string;
  // stroke mode extras
  binary?: string;
  segments?: string;
  merged?: string;
  n_raw_segments?: number;
  n_merges?: number;
  n_bridges?: number;
  n_discarded?: number;
  n_crossings?: number;
  coverage_pct?: number;
  avg_stroke_len?: number;
  total_skel_px?: number;
}

export interface ParamHints {
  simplify?: number;
  min_length?: number;
  sensitivity?: number;
}

export interface AnalyzeResult {
  image_type: "line_art" | "silhouette" | "logo" | "photo";
  recommended_mode: TraceMode;
  description: string;
  recommendation: string;
  artistic_description: string;
  edge_density: number;
  contrast: number;
  param_hints?: ParamHints;
}

export async function analyzePhoto(file: File, prompt = ""): Promise<AnalyzeResult> {
  const form = new FormData();
  form.append("file", file);
  if (prompt) form.append("prompt", prompt);
  const resp = await fetch(`${BASE}/photo-to-dxf/analyze`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`Analysis failed (${resp.status}): ${await resp.text()}`);
  return resp.json();
}

// ── Halftone / Dot mode ───────────────────────────────────────────────────────

export interface HalftoneParams {
  density: number;      // 10–150 grid cells across longer axis
  min_radius: number;   // 0.5–5 px minimum circle radius
  max_radius: number;   // 1–20 px maximum circle radius
  contrast: number;     // 0.5–3.0 contrast boost before mapping
  invert: boolean;
  placement_mode?: "organic_density" | "hex_packing" | "flow_field";
  randomness?: number;
  density_sensitivity?: number;
}

export interface HalftoneResult {
  circles: [number, number, number][];  // [row, col, radius]
  preview_image: string;                // base64 PNG preview
  density_heatmap?: string;
  n_circles: number;
  image_width: number;
  image_height: number;
  placement_mode?: string;
  open_area_pct?: number;
  min_bridge_px?: number;
  max_hole_diameter_px?: number;
  strength_score?: number;
  strength_label?: string;
}

export async function traceHalftone(
  file: File,
  params: HalftoneParams,
): Promise<HalftoneResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("density",    String(params.density));
  form.append("min_radius", String(params.min_radius));
  form.append("max_radius", String(params.max_radius));
  form.append("contrast",   String(params.contrast));
  form.append("invert",     String(params.invert));
  if (params.placement_mode) form.append("placement_mode", params.placement_mode);
  if (params.randomness != null) form.append("randomness", String(params.randomness));
  if (params.density_sensitivity != null) form.append("density_sensitivity", String(params.density_sensitivity));

  const resp = await fetch(`${BASE}/photo-to-dxf/halftone`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`Halftone trace failed (${resp.status}): ${await resp.text()}`);
  return resp.json();
}

export async function exportHalftoneDXF(
  circles: [number, number, number][],
  imageWidth: number,
  imageHeight: number,
  scale: number,
  filename = "halftone.dxf",
): Promise<void> {
  const resp = await fetch(`${BASE}/photo-to-dxf/export-halftone`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ circles, image_width: imageWidth, image_height: imageHeight, scale, filename }),
  });
  if (!resp.ok) throw new Error(`Halftone export failed (${resp.status}): ${await resp.text()}`);
  const blob = await resp.blob();
  triggerDownload(blob, getFilename(resp, filename));
}

export async function tracePhoto(
  file: File,
  params: TraceParams,
): Promise<TraceResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("mode",        params.mode);
  form.append("blur",        String(params.blur));
  form.append("sensitivity", String(params.sensitivity));
  form.append("simplify",    String(params.simplify));
  form.append("min_length",  String(params.min_length));
  form.append("invert",      String(params.invert));

  const resp = await fetch(`${BASE}/photo-to-dxf/trace`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`Trace failed (${resp.status}): ${await resp.text()}`);
  return resp.json();
}

export async function exportPhotoAsDXF(
  contours: [number, number][][],
  imageWidth: number,
  imageHeight: number,
  scale: number,
  filename = "traced.dxf",
): Promise<void> {
  const resp = await fetch(`${BASE}/photo-to-dxf/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contours, image_width: imageWidth, image_height: imageHeight, scale, filename }),
  });
  if (!resp.ok) throw new Error(`Export failed (${resp.status}): ${await resp.text()}`);
  const blob = await resp.blob();
  triggerDownload(blob, getFilename(resp, filename));
}

// ── One-Line Drawing ─────────────────────────────────────────────────────────

export interface OneLineParams {
  detail: number;       // 1–10 skeleton detail level
  simplify: number;     // 0–15 RDP epsilon
  jump_penalty: number; // 0–1 direction-continuity weight
  blur: number;         // 0–5 pre-blur
  invert: boolean;
}

export interface OneLineResult {
  path: [number, number][];   // [[row, col], ...]
  jump_indices: number[];     // indices i where path[i]→path[i+1] is a jump connector
  n_points: number;
  n_jumps: number;
  longest_jump: number;       // length of the longest jump connector in pixels
  total_length_px: number;
  preview_image: string;      // base64 PNG
  skeleton_image: string;
  cleaned_image: string;
  image_width: number;
  image_height: number;
}

export async function traceOneLine(
  file: File,
  params: OneLineParams,
): Promise<OneLineResult> {
  const form = new FormData();
  form.append("file",         file);
  form.append("detail",       String(params.detail));
  form.append("simplify",     String(params.simplify));
  form.append("jump_penalty", String(params.jump_penalty));
  form.append("blur",         String(params.blur));
  form.append("invert",       String(params.invert));

  const resp = await fetch(`${BASE}/photo-to-dxf/one-line`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`One-line trace failed (${resp.status}): ${await resp.text()}`);
  return resp.json();
}

export async function exportOneLineDXF(
  path: [number, number][],
  imageWidth: number,
  imageHeight: number,
  scale: number,
  filename = "one-line.dxf",
): Promise<void> {
  const resp = await fetch(`${BASE}/photo-to-dxf/export-one-line`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, image_width: imageWidth, image_height: imageHeight, scale, filename }),
  });
  if (!resp.ok) throw new Error(`One-line export failed (${resp.status}): ${await resp.text()}`);
  const blob = await resp.blob();
  triggerDownload(blob, getFilename(resp, filename));
}

// ── AI Pattern Maker ──────────────────────────────────────────────────────────

export type PatternType  = "contour_relief" | "groove" | "perforation" | "facade";
export type PatternStyle = "clean" | "organic" | "geometric" | "facade";
export type PanelShape   = "hexagon" | "triangle" | "diamond" | "wave";

export interface AiPatternParams {
  pattern_type:  PatternType;
  style:         PatternStyle;
  detail:        number;
  min_spacing:   number;
  min_hole_size: number;
  max_elements:  number;
  panel_shape:   PanelShape;
}

export interface AiPatternElement {
  type:    "polyline" | "circle" | "line";
  layer:   string;
  level?:  number;
  points?: [number, number][];
  cx?:     number;
  cy?:     number;
  r?:      number;
  x1?:     number;
  y1?:     number;
  x2?:     number;
  y2?:     number;
}

export interface AiPatternAnalysis {
  edge_density:       number;
  contrast:           number;
  dominant_angle_deg: number;
  brightness_map:     string;
}

export interface FabricationCheck {
  severity: "ok" | "warning" | "error";
  code:     string;
  message:  string;
}

export interface FabricationInfo {
  operation_type:     string;
  operation_label:    string;
  estimated_time_min: number;
  checks:             FabricationCheck[];
}

export interface AiPatternResult {
  pattern_type:  string;
  style:         string;
  n_elements:    number;
  n_by_layer:    Record<string, number>;
  image_width:   number;
  image_height:  number;
  analysis:      AiPatternAnalysis;
  elements:      AiPatternElement[];
  preview_image: string;
  warnings:      string[];
  fabrication:   FabricationInfo;
}

export async function generateAiPattern(
  file:          File,
  params:        AiPatternParams,
  blur           = 1.0,
  invert         = false,
  scaleMmPerPx   = 1.0,
): Promise<AiPatternResult> {
  const form = new FormData();
  form.append("file",            file);
  form.append("pattern_type",    params.pattern_type);
  form.append("style",           params.style);
  form.append("detail",          String(params.detail));
  form.append("min_spacing",     String(params.min_spacing));
  form.append("min_hole_size",   String(params.min_hole_size));
  form.append("max_elements",    String(params.max_elements));
  form.append("panel_shape",     params.panel_shape);
  form.append("blur",            String(blur));
  form.append("invert",          String(invert));
  form.append("scale_mm_per_px", String(scaleMmPerPx));
  const resp = await fetch(`${BASE}/photo-to-dxf/ai-pattern`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`AI Pattern failed (${resp.status}): ${await resp.text()}`);
  return resp.json();
}

export async function exportAiPatternDXF(
  result:   AiPatternResult,
  scale:    number,
  filename  = "pattern.dxf",
): Promise<void> {
  const resp = await fetch(`${BASE}/photo-to-dxf/export-ai-pattern`, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({
      elements:     result.elements,
      image_width:  result.image_width,
      image_height: result.image_height,
      scale,
      filename,
    }),
  });
  if (!resp.ok) throw new Error(`Pattern export failed (${resp.status}): ${await resp.text()}`);
  const blob = await resp.blob();
  triggerDownload(blob, getFilename(resp, filename));
}

// ── AI Copilot ────────────────────────────────────────────────────────────────

export interface AiRecommendResult {
  source: "ai" | "none";
  recommended_mode?: TraceMode;
  confidence?: number;
  explanation?: string;
  reasoning?: string;
  param_hints?: ParamHints;
  error?: string;
}

export async function aiRecommend(
  imageType: string,
  edgeDensity: number,
  contrast: number,
  prompt = "",
): Promise<AiRecommendResult> {
  try {
    const resp = await fetch(`${BASE}/ai-recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_type: imageType,
        edge_density: edgeDensity,
        contrast,
        prompt,
      }),
    });
    if (!resp.ok) return { source: "none", error: `HTTP ${resp.status}` };
    return resp.json();
  } catch (err) {
    return { source: "none", error: String(err) };
  }
}

// ── GET /health ───────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<boolean> {
  try {
    const resp = await fetch(`${BASE}/health`, { cache: "no-store" });
    return resp.ok;
  } catch {
    return false;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getFilename(resp: Response, fallback: string): string {
  const cd = resp.headers.get("Content-Disposition") ?? "";
  const m = cd.match(/filename="?([^";\s]+)"?/);
  return m?.[1] ?? fallback;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
