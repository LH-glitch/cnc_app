import type { SliceParams, SliceEvent, ExportParams } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function* sliceSTL(
  file: File,
  params: SliceParams
): AsyncGenerator<SliceEvent> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("axis", params.axis);
  formData.append("slab_mode", params.slab_mode);
  formData.append("quality", params.quality);
  formData.append("slice_mode", params.slice_mode);
  formData.append("thickness", params.thickness.toString());
  formData.append("n_boards", params.n_boards.toString());
  formData.append("add_alignment", params.add_alignment.toString());
  formData.append("dowel_radius", params.dowel_radius.toString());
  formData.append("n_holes", params.n_holes.toString());

  if (params.edge_margin_mm !== undefined) {
    formData.append("edge_margin_mm", params.edge_margin_mm.toString());
  }

  const response = await fetch(`${API_BASE}/slice`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`Slice request failed: ${response.statusText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const jsonStr = line.slice(6).trim();
        if (jsonStr) {
          try {
            const event = JSON.parse(jsonStr) as SliceEvent;
            yield event;
          } catch {
            console.error("Failed to parse SSE event:", jsonStr);
          }
        }
      }
    }
  }
}

export async function exportDXF(params: ExportParams): Promise<Blob> {
  const response = await fetch(`${API_BASE}/export_dxf`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(params),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`DXF export failed: ${error}`);
  }

  return response.blob();
}

export async function exportDXFPerBoard(params: {
  result: ExportParams["result"];
  prefix?: string;
  filename?: string;
}): Promise<Blob> {
  const response = await fetch(`${API_BASE}/export_dxf_per_board`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      result: params.result,
      prefix: params.prefix || "board",
      filename: params.filename || "boards.zip",
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Per-board DXF export failed: ${error}`);
  }

  return response.blob();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/health`);
    return response.ok;
  } catch {
    return false;
  }
}
