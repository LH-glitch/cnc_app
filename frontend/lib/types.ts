export interface Contour {
  points: [number, number][];
}

export interface BoardSlice {
  index: number;
  y_min: number;
  y_max: number;
  thickness: number;
  label: string;
  contours: [number, number][][];
}

export interface SliceResult {
  board_thickness: number;
  n_boards: number;
  stacking_axis: "x" | "y" | "z";
  slab_mode: "envelope" | "best_sample";
  source_path: string;
  model_span: number;
  mesh_bounds: number[];
  slices: BoardSlice[];
}

export interface SliceParams {
  axis: "x" | "y" | "z";
  slab_mode: "envelope" | "best_sample";
  quality: "accurate" | "fast";
  slice_mode: "thickness" | "count";
  thickness: number;
  n_boards: number;
  add_alignment: boolean;
  dowel_radius: number;
  n_holes: number;
  edge_margin_mm?: number;
}

export interface ExportParams {
  result: SliceResult;
  layout_gap: number;
  sheet_width?: number;
  sheet_height?: number;
  sheet_spacing?: number;
  filename: string;
}

export interface ProgressEvent {
  type: "progress";
  done: number;
  total: number;
}

export interface ResultEvent {
  type: "result";
  job_id: string;
  data: SliceResult;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type SliceEvent = ProgressEvent | ResultEvent | ErrorEvent;

export type Tool = "slicer" | "dxf-generator" | "photo-to-dxf" | "sheet-layout";
