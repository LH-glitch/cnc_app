"use client";

import { useRef, useState, useCallback, DragEvent, ChangeEvent } from "react";
import {
  sliceModel,
  exportDXF,
  exportDXFPerBoard,
  SliceResult,
  SliceParams,
  SliceProgress,
} from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type SliceMode = "thickness" | "count";
type Axis = "x" | "y" | "z";
type Quality = "accurate" | "fast";
type SlabMode = "envelope" | "best_sample";
type AppState = "idle" | "slicing" | "done" | "error";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SegControl<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { label: string; value: T }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="seg-control">
      {options.map((o) => (
        <button
          key={o.value}
          className={`seg-btn${value === o.value ? " active" : ""}`}
          onClick={() => onChange(o.value)}
          type="button"
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function FieldRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      <span style={{ fontSize: 13, color: "var(--text-muted)", flexShrink: 0 }}>
        {label}
      </span>
      {children}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      className="glass-sm"
      style={{ padding: "14px 18px", textAlign: "center" }}
    >
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          background: "linear-gradient(135deg, #a78bfa, #38bdf8)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
        {label}
      </div>
      {sub && (
        <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 1 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Home() {
  // File
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Params
  const [axis, setAxis] = useState<Axis>("y");
  const [sliceMode, setSliceMode] = useState<SliceMode>("thickness");
  const [thickness, setThickness] = useState("20");
  const [nBoards, setNBoards] = useState("8");
  const [slabMode, setSlabMode] = useState<SlabMode>("envelope");
  const [quality, setQuality] = useState<Quality>("accurate");
  const [addAlignment, setAddAlignment] = useState(true);

  // State
  const [appState, setAppState] = useState<AppState>("idle");
  const [progress, setProgress] = useState<SliceProgress | null>(null);
  const [result, setResult] = useState<SliceResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [exportBusy, setExportBusy] = useState(false);

  // ── Drag & drop ───────────────────────────────────────────────────────────

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragging(false), []);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) acceptFile(f);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) acceptFile(f);
  };

  function acceptFile(f: File) {
    setFile(f);
    setResult(null);
    setErrorMsg("");
    setAppState("idle");
    setProgress(null);
  }

  // ── Slice ─────────────────────────────────────────────────────────────────

  async function handleSlice() {
    if (!file) return;
    setAppState("slicing");
    setProgress(null);
    setResult(null);
    setErrorMsg("");

    const params: SliceParams = {
      axis,
      slab_mode: slabMode,
      quality,
      slice_mode: sliceMode,
      thickness: parseFloat(thickness) || 20,
      n_boards: parseInt(nBoards) || 8,
      add_alignment: addAlignment,
    };

    try {
      const r = await sliceModel(file, params, (p) => setProgress(p));
      setResult(r);
      setAppState("done");
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setAppState("error");
    }
  }

  // ── Export ────────────────────────────────────────────────────────────────

  async function handleExport(mode: "combined" | "per_board") {
    if (!result) return;
    setExportBusy(true);
    try {
      if (mode === "combined") {
        await exportDXF(result, { filename: "boards.dxf" });
      } else {
        await exportDXFPerBoard(result, { filename: "boards.zip" });
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setExportBusy(false);
    }
  }

  // ── Progress % ────────────────────────────────────────────────────────────

  const progressPct =
    progress && progress.total > 0
      ? Math.round((progress.done / progress.total) * 100)
      : 0;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "32px 16px 80px",
        gap: 0,
      }}
    >
      {/* ── Header ── */}
      <header
        style={{
          width: "100%",
          maxWidth: 840,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 40,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* Logo mark */}
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: 9,
              background: "linear-gradient(135deg, #7c3aed, #0ea5e9)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 18,
              boxShadow: "0 0 16px rgba(124,58,237,0.5)",
            }}
          >
            ◈
          </div>
          <div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 700,
                color: "var(--text-primary)",
                letterSpacing: "-0.01em",
              }}
            >
              CNC DXF Generator
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              STL → board profiles → fabrication DXF
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <span className="chip chip-violet">Beta</span>
          <span className="chip chip-sky">v1.0</span>
        </div>
      </header>

      {/* ── Main card ── */}
      <div
        className="glass"
        style={{ width: "100%", maxWidth: 840, padding: "32px 36px", gap: 28, display: "flex", flexDirection: "column" }}
      >
        {/* ── Step 1: Upload ── */}
        <section>
          <SectionLabel step={1} title="Upload STL File" />

          <div
            className={`dropzone${dragging ? " over" : ""}`}
            style={{
              marginTop: 14,
              padding: file ? "20px 24px" : "40px 24px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 10,
            }}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".stl,.STL"
              style={{ display: "none" }}
              onChange={handleFileChange}
            />

            {file ? (
              <div style={{ display: "flex", alignItems: "center", gap: 14, width: "100%" }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 10,
                    background: "rgba(124,58,237,0.18)",
                    border: "1px solid rgba(124,58,237,0.3)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 20,
                    flexShrink: 0,
                  }}
                >
                  📐
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: "var(--text-primary)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {file.name}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                    {formatBytes(file.size)} · Click to replace
                  </div>
                </div>
                <span className="chip chip-green">Ready</span>
              </div>
            ) : (
              <>
                <div style={{ fontSize: 32, opacity: 0.5 }}>⬆</div>
                <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text-muted)" }}>
                  Drop your STL file here, or click to browse
                </div>
                <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                  Supports ASCII and binary STL
                </div>
              </>
            )}
          </div>
        </section>

        <hr style={{ border: "none", borderTop: "1px solid var(--glass-border)" }} />

        {/* ── Step 2: Parameters ── */}
        <section>
          <SectionLabel step={2} title="Slicing Parameters" />

          <div
            style={{
              marginTop: 16,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 20,
            }}
          >
            {/* Stacking axis */}
            <FieldRow label="Stacking axis">
              <SegControl
                options={[
                  { label: "X", value: "x" as Axis },
                  { label: "Y", value: "y" as Axis },
                  { label: "Z", value: "z" as Axis },
                ]}
                value={axis}
                onChange={setAxis}
              />
            </FieldRow>

            {/* Profile mode */}
            <FieldRow label="Board profile">
              <SegControl
                options={[
                  { label: "Envelope", value: "envelope" as SlabMode },
                  { label: "Best sample", value: "best_sample" as SlabMode },
                ]}
                value={slabMode}
                onChange={setSlabMode}
              />
            </FieldRow>

            {/* Slice mode */}
            <FieldRow label="Slice by">
              <SegControl
                options={[
                  { label: "Thickness", value: "thickness" as SliceMode },
                  { label: "Count", value: "count" as SliceMode },
                ]}
                value={sliceMode}
                onChange={setSliceMode}
              />
            </FieldRow>

            {/* Quality */}
            <FieldRow label="Quality">
              <SegControl
                options={[
                  { label: "Accurate", value: "accurate" as Quality },
                  { label: "Fast", value: "fast" as Quality },
                ]}
                value={quality}
                onChange={setQuality}
              />
            </FieldRow>

            {/* Thickness / count input */}
            {sliceMode === "thickness" ? (
              <FieldRow label="Board thickness (mm)">
                <input
                  type="number"
                  min={1}
                  max={200}
                  step={0.5}
                  value={thickness}
                  onChange={(e) => setThickness(e.target.value)}
                  className="input-dark"
                  style={{ width: 90, padding: "6px 10px", fontSize: 14 }}
                />
              </FieldRow>
            ) : (
              <FieldRow label="Number of boards">
                <input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={nBoards}
                  onChange={(e) => setNBoards(e.target.value)}
                  className="input-dark"
                  style={{ width: 90, padding: "6px 10px", fontSize: 14 }}
                />
              </FieldRow>
            )}

            {/* Alignment holes */}
            <FieldRow label="Alignment holes">
              <button
                type="button"
                onClick={() => setAddAlignment((v) => !v)}
                style={{
                  width: 44,
                  height: 24,
                  borderRadius: 9999,
                  border: "none",
                  cursor: "pointer",
                  position: "relative",
                  transition: "background 0.2s",
                  background: addAlignment
                    ? "linear-gradient(135deg, #7c3aed, #0ea5e9)"
                    : "rgba(255,255,255,0.1)",
                  flexShrink: 0,
                }}
                aria-pressed={addAlignment}
              >
                <span
                  style={{
                    position: "absolute",
                    top: 2,
                    left: addAlignment ? 22 : 2,
                    width: 20,
                    height: 20,
                    borderRadius: "50%",
                    background: "#fff",
                    transition: "left 0.2s",
                    boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
                  }}
                />
              </button>
            </FieldRow>
          </div>
        </section>

        <hr style={{ border: "none", borderTop: "1px solid var(--glass-border)" }} />

        {/* ── Step 3: Slice ── */}
        <section>
          <SectionLabel step={3} title="Slice" />

          <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
            <button
              className="btn-glow"
              onClick={handleSlice}
              disabled={!file || appState === "slicing"}
              style={{ padding: "14px 24px", fontSize: 15, width: "100%" }}
            >
              {appState === "slicing" ? (
                <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
                  <Spinner />
                  Slicing… {progress ? `board ${progress.done} / ${progress.total}` : ""}
                </span>
              ) : (
                "▶  Slice Model"
              )}
            </button>

            {/* Progress bar */}
            {appState === "slicing" && (
              <div>
                <div
                  className="progress-track"
                  style={{ height: 6 }}
                >
                  <div
                    className="progress-fill"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginTop: 6,
                    fontSize: 12,
                    color: "var(--text-muted)",
                  }}
                >
                  <span>
                    {progress
                      ? `Board ${progress.done} of ${progress.total}`
                      : "Starting…"}
                  </span>
                  <span>{progressPct}%</span>
                </div>
              </div>
            )}

            {/* Error */}
            {appState === "error" && (
              <div
                className="glass-sm"
                style={{
                  padding: "12px 16px",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  borderColor: "rgba(248,113,113,0.25)",
                }}
              >
                <span style={{ fontSize: 16, flexShrink: 0 }}>⚠</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#fca5a5" }}>
                    Slicing failed
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 3 }}>
                    {errorMsg}
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ── Step 4: Results + Export ── */}
        {result && appState === "done" && (
          <>
            <hr style={{ border: "none", borderTop: "1px solid var(--glass-border)" }} />

            <section>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
                <SectionLabel step={4} title="Results" />
                <span className="chip chip-green">✓ Done</span>
              </div>

              {/* Stats grid */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 10,
                  marginBottom: 20,
                }}
              >
                <StatCard
                  label="Boards"
                  value={String(result.n_boards)}
                />
                <StatCard
                  label="Thickness"
                  value={`${result.board_thickness.toFixed(1)}`}
                  sub="mm / board"
                />
                <StatCard
                  label="Model span"
                  value={`${result.model_span.toFixed(0)}`}
                  sub="mm"
                />
                <StatCard
                  label="Axis"
                  value={result.stacking_axis.toUpperCase()}
                  sub={result.slab_mode}
                />
              </div>

              {/* Board list preview */}
              <div
                className="glass-sm"
                style={{
                  padding: "4px 0",
                  maxHeight: 180,
                  overflowY: "auto",
                  marginBottom: 20,
                }}
              >
                {result.slices.map((sl) => (
                  <div
                    key={sl.index}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "8px 16px",
                      borderBottom: "1px solid rgba(255,255,255,0.04)",
                      fontSize: 13,
                    }}
                  >
                    <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-geist-mono)" }}>
                      {sl.label}
                    </span>
                    <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                      {sl.contours.length} contour{sl.contours.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                ))}
              </div>

              {/* Export buttons */}
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  className="btn-glow"
                  onClick={() => handleExport("combined")}
                  disabled={exportBusy}
                  style={{ flex: 1, padding: "12px 20px", fontSize: 14 }}
                >
                  {exportBusy ? <Spinner /> : "⬇  Download DXF"}
                </button>
                <button
                  className="btn-ghost"
                  onClick={() => handleExport("per_board")}
                  disabled={exportBusy}
                  style={{ flex: 1, padding: "12px 20px", fontSize: 14 }}
                >
                  {exportBusy ? <Spinner /> : "⬇  Per-board ZIP"}
                </button>
              </div>
            </section>
          </>
        )}
      </div>

      {/* ── Floating Open Editor button ── */}
      <a
        href="/editor"
        style={{
          position: "fixed",
          bottom: 28,
          right: 28,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "11px 20px",
          borderRadius: 12,
          background: "rgba(8,8,24,0.85)",
          border: "1px solid rgba(255,255,255,0.12)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          color: "var(--text-primary)",
          fontSize: 13,
          fontWeight: 600,
          textDecoration: "none",
          boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
          transition: "border-color 0.2s, box-shadow 0.2s, transform 0.12s",
          zIndex: 50,
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLAnchorElement).style.borderColor = "rgba(124,58,237,0.5)";
          (e.currentTarget as HTMLAnchorElement).style.boxShadow = "0 4px 24px rgba(0,0,0,0.5), 0 0 16px rgba(124,58,237,0.3)";
          (e.currentTarget as HTMLAnchorElement).style.transform = "translateY(-1px)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLAnchorElement).style.borderColor = "rgba(255,255,255,0.12)";
          (e.currentTarget as HTMLAnchorElement).style.boxShadow = "0 4px 24px rgba(0,0,0,0.5)";
          (e.currentTarget as HTMLAnchorElement).style.transform = "translateY(0)";
        }}
      >
        <span style={{ fontSize: 15 }}>✏</span>
        Open Editor
      </a>
    </main>
  );
}

// ── Shared small components ───────────────────────────────────────────────────

function SectionLabel({ step, title }: { step: number; title: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: "50%",
          background: "linear-gradient(135deg, #7c3aed, #0ea5e9)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 700,
          color: "#fff",
          flexShrink: 0,
        }}
      >
        {step}
      </div>
      <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
        {title}
      </span>
    </div>
  );
}

function Spinner() {
  return (
    <span
      style={{
        display: "inline-block",
        width: 14,
        height: 14,
        border: "2px solid rgba(255,255,255,0.25)",
        borderTopColor: "#fff",
        borderRadius: "50%",
        animation: "spin 0.7s linear infinite",
      }}
    />
  );
}

// Inject keyframe once
if (typeof document !== "undefined") {
  const id = "__cnc_spin";
  if (!document.getElementById(id)) {
    const s = document.createElement("style");
    s.id = id;
    s.textContent = "@keyframes spin { to { transform: rotate(360deg); } }";
    document.head.appendChild(s);
  }
}
