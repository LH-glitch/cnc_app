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
