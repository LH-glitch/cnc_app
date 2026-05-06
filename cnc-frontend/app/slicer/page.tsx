"use client";

import {
  useRef, useState, useCallback, useEffect,
  DragEvent, ChangeEvent,
} from "react";
import dynamic from "next/dynamic";
import {
  sliceModel, exportDXF, exportDXFPerBoard,
  SliceResult, SliceParams, SliceProgress,
} from "@/lib/api";
import BoardCanvas from "@/app/components/BoardCanvas";

// Three.js viewer — client-only (no SSR)
const Board3DViewer = dynamic(() => import("@/app/components/Board3DViewer"), {
  ssr: false,
  loading: () => (
    <div style={{
      width: "100%", height: 380,
      background: "rgba(2,2,12,0.6)", borderRadius: 12,
      display: "flex", alignItems: "center", justifyContent: "center",
      color: "var(--text-subtle)", fontSize: 13,
    }}>
      Loading 3D viewer…
    </div>
  ),
});

// ── Types ─────────────────────────────────────────────────────────────────────

type SliceMode = "thickness" | "count";
type Axis      = "x" | "y" | "z";
type Quality   = "accurate" | "fast";
type SlabMode  = "envelope" | "best_sample";
type NHoles    = 2 | 3 | 4;
type AppState  = "idle" | "slicing" | "done" | "error";

// ── Shared primitives ─────────────────────────────────────────────────────────

function SegControl<T extends string>({
  options, value, onChange,
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
          style={{ padding: "5px 11px", fontSize: 12 }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function FieldRow({ label, sub, children }: { label: string; sub?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
      <div style={{ flexShrink: 0 }}>
        <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{label}</div>
        {sub && <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 1 }}>{sub}</div>}
      </div>
      {children}
    </div>
  );
}

function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span style={{
      display: "inline-block", width: size, height: size, flexShrink: 0,
      border: `${size <= 14 ? 2 : 3}px solid rgba(255,255,255,0.2)`,
      borderTopColor: "#fff", borderRadius: "50%",
      animation: "spin 0.7s linear infinite",
    }} />
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="glass-sm" style={{ padding: "12px 14px", textAlign: "center" }}>
      <div style={{
        fontSize: 20, fontWeight: 700, lineHeight: 1.2,
        background: "linear-gradient(135deg, #a78bfa, #38bdf8)",
        WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
      }}>
        {value}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      {sub && <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

// ── Step section — left panel building block ───────────────────────────────────

function StepSection({
  step, title, done, children,
}: {
  step: number; title: string; done?: boolean; children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", gap: 13, alignItems: "flex-start" }}>
      {/* Circle badge */}
      <div style={{
        width: 22, height: 22, borderRadius: "50%", flexShrink: 0, marginTop: 1,
        background: done
          ? "linear-gradient(135deg, rgba(34,197,94,0.7), rgba(16,163,74,0.7))"
          : "linear-gradient(135deg, rgba(124,58,237,0.55), rgba(14,165,233,0.55))",
        border: done ? "1px solid rgba(34,197,94,0.5)" : "1px solid rgba(124,58,237,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 10, fontWeight: 700,
        color: done ? "#bbf7d0" : "#ddd6fe",
      }}>
        {done ? "✓" : step}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 10, fontWeight: 700, color: "var(--text-subtle)",
          textTransform: "uppercase", letterSpacing: "0.09em", marginBottom: 12,
          paddingTop: 3,
        }}>
          {title}
        </div>
        {children}
      </div>
    </div>
  );
}

// Thin connector line between step circles
function StepConnector() {
  return (
    <div style={{ display: "flex", gap: 13, paddingLeft: 0 }}>
      <div style={{ width: 22, flexShrink: 0, display: "flex", justifyContent: "center" }}>
        <div style={{ width: 1, height: 14, background: "rgba(255,255,255,0.09)" }} />
      </div>
    </div>
  );
}

// Idle state illustration
function SlicerIllustration() {
  return (
    <svg viewBox="0 0 200 155" fill="none" xmlns="http://www.w3.org/2000/svg"
      style={{ width: 160, opacity: 0.6 }}>
      <polygon points="100,18 158,48 100,78 42,48"
        fill="rgba(124,58,237,0.10)" stroke="rgba(124,58,237,0.45)" strokeWidth="1.5" strokeLinejoin="round" />
      <polygon points="158,48 158,108 100,138 100,78"
        fill="rgba(14,165,233,0.07)" stroke="rgba(14,165,233,0.38)" strokeWidth="1.5" strokeLinejoin="round" />
      <polygon points="42,48 42,108 100,138 100,78"
        fill="rgba(124,58,237,0.05)" stroke="rgba(124,58,237,0.32)" strokeWidth="1.5" strokeLinejoin="round" />
      <line x1="158" y1="68"  x2="100" y2="98"  stroke="rgba(14,165,233,0.6)"  strokeWidth="1.2" strokeDasharray="4,3" />
      <line x1="158" y1="88"  x2="100" y2="118" stroke="rgba(14,165,233,0.6)"  strokeWidth="1.2" strokeDasharray="4,3" />
      <line x1="42"  y1="68"  x2="100" y2="98"  stroke="rgba(124,58,237,0.55)" strokeWidth="1.2" strokeDasharray="4,3" />
      <line x1="42"  y1="88"  x2="100" y2="118" stroke="rgba(124,58,237,0.55)" strokeWidth="1.2" strokeDasharray="4,3" />
      <line x1="174" y1="78" x2="190" y2="78" stroke="rgba(14,165,233,0.5)" strokeWidth="1.5" />
      <polygon points="190,75 196,78 190,81" fill="rgba(14,165,233,0.5)" />
    </svg>
  );
}

function formatBytes(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(2)} MB`;
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SlicerPage() {
  // File
  const [file,     setFile]     = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Params
  const [axis,          setAxis]          = useState<Axis>("y");
  const [slabMode,      setSlabMode]      = useState<SlabMode>("envelope");
  const [sliceMode,     setSliceMode]     = useState<SliceMode>("thickness");
  const [thickness,     setThickness]     = useState("20");
  const [nBoards,       setNBoards]       = useState("8");
  const [quality,       setQuality]       = useState<Quality>("accurate");
  const [addAlignment,  setAddAlignment]  = useState(true);
  const [nHoles,        setNHoles]        = useState<NHoles>(4);

  // App state
  const [appState,   setAppState]   = useState<AppState>("idle");
  const [progress,   setProgress]   = useState<SliceProgress | null>(null);
  const [result,     setResult]     = useState<SliceResult | null>(null);
  const [errorMsg,   setErrorMsg]   = useState("");
  const [exportBusy,    setExportBusy]    = useState<"combined" | "per_board" | null>(null);
  const [exportSuccess, setExportSuccess] = useState<"combined" | "per_board" | null>(null);

  // Viewer
  const [selectedBoard, setSelectedBoard] = useState(0);
  const [viewMode,      setViewMode]      = useState<"2d" | "3d">("2d");
  const boardStripRef = useRef<HTMLDivElement>(null);

  // Scroll the board strip to the selected pill
  useEffect(() => {
    const el = boardStripRef.current?.children[selectedBoard] as HTMLElement | undefined;
    el?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [selectedBoard]);

  // ── Drag & drop ─────────────────────────────────────────────────────────────
  const onDragOver  = useCallback((e: DragEvent) => { e.preventDefault(); setDragging(true); }, []);
  const onDragLeave = useCallback(() => setDragging(false), []);
  const onDrop      = useCallback((e: DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0]; if (f) acceptFile(f);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (f) acceptFile(f);
  };

  function acceptFile(f: File) {
    setFile(f); setResult(null); setErrorMsg("");
    setAppState("idle"); setProgress(null); setSelectedBoard(0);
  }

  // ── Slice ────────────────────────────────────────────────────────────────────
  async function handleSlice() {
    if (!file) return;
    setAppState("slicing"); setProgress(null); setResult(null); setErrorMsg(""); setSelectedBoard(0);

    const params: SliceParams = {
      axis, slab_mode: slabMode, quality, slice_mode: sliceMode,
      thickness: parseFloat(thickness) || 20,
      n_boards:  parseInt(nBoards) || 8,
      add_alignment: addAlignment, n_holes: nHoles,
    };

    try {
      const r = await sliceModel(file, params, (p) => setProgress(p));
      setResult(r); setAppState("done");
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setAppState("error");
    }
  }

  // ── Export ───────────────────────────────────────────────────────────────────
  async function handleExport(mode: "combined" | "per_board") {
    if (!result) return;
    setExportBusy(mode); setExportSuccess(null);
    try {
      if (mode === "combined") {
        await exportDXF(result, { filename: "boards.dxf" });
      } else {
        await exportDXFPerBoard(result, { filename: "boards.zip" });
      }
      setExportSuccess(mode);
      setTimeout(() => setExportSuccess(null), 2500);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setExportBusy(null);
    }
  }

  // ── Derived ─────────────────────────────────────────────────────────────────
  const progressPct  = progress && progress.total > 0
    ? Math.round((progress.done / progress.total) * 100) : 0;
  const totalBoards  = result?.slices.length ?? 0;
  const goBoard      = (i: number) => setSelectedBoard(Math.max(0, Math.min(i, totalBoards - 1)));

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>

      {/* ── Page title ── */}
      <div style={{
        padding: "28px 32px 0",
        display: "flex", alignItems: "baseline", gap: 14, flexShrink: 0,
      }}>
        <h1 style={{
          fontSize: 22, fontWeight: 700, color: "var(--text-primary)",
          letterSpacing: "-0.02em", margin: 0,
        }}>
          Stacked Slicer
        </h1>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          Slice a 3D mesh into CNC-ready board profiles
        </span>
        <span className="chip chip-green" style={{ marginLeft: "auto" }}>Live</span>
      </div>

      {/* ── Two-column workspace ── */}
      <div style={{
        flex: 1, display: "flex", gap: 20,
        padding: "20px 32px 40px", alignItems: "flex-start",
      }}>

        {/* ────────────────── LEFT PANEL — Steps 1–5 ────────────────── */}
        <div className="glass" style={{
          width: 360, flexShrink: 0,
          padding: "22px 22px",
          display: "flex", flexDirection: "column", gap: 0,
        }}>

          {/* ── Step 1: Upload ── */}
          <StepSection step={1} title="Upload Model" done={!!file}>
            <div
              className={`dropzone${dragging ? " over" : ""}`}
              style={{
                padding: file ? "12px 14px" : "28px 14px",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
                cursor: "pointer",
              }}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
            >
              <input ref={fileRef} type="file" accept=".stl,.STL,.obj,.OBJ"
                style={{ display: "none" }} onChange={onFileChange} />
              {file ? (
                <div style={{ display: "flex", alignItems: "center", gap: 10, width: "100%" }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 9, flexShrink: 0,
                    background: "rgba(124,58,237,0.18)", border: "1px solid rgba(124,58,237,0.3)",
                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: 17,
                  }}>📐</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-primary)" }}>
                      {file.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 1 }}>
                      {formatBytes(file.size)} · click to replace
                    </div>
                  </div>
                  <span className="chip chip-violet" style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    {file.name.split('.').pop()?.toUpperCase() ?? "3D"}
                  </span>
                  <span className="chip chip-green">Ready</span>
                </div>
              ) : (
                <>
                  <div style={{ fontSize: 26, opacity: 0.4, lineHeight: 1 }}>⬆</div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-muted)", textAlign: "center" }}>
                    Drop 3D model here or click to browse
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-subtle)" }}>
                    STL and OBJ supported
                  </div>
                </>
              )}
            </div>
          </StepSection>

          <StepConnector />

          {/* ── Step 2: Slicing Direction ── */}
          <StepSection step={2} title="Slicing Direction">
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
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
              <FieldRow label="Profile mode">
                <SegControl
                  options={[
                    { label: "Envelope",    value: "envelope"    as SlabMode },
                    { label: "Best sample", value: "best_sample" as SlabMode },
                  ]}
                  value={slabMode}
                  onChange={setSlabMode}
                />
              </FieldRow>
            </div>
          </StepSection>

          <StepConnector />

          {/* ── Step 3: Board Settings ── */}
          <StepSection step={3} title="Board Settings">
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <FieldRow label="Slice by">
                <SegControl
                  options={[
                    { label: "Thickness", value: "thickness" as SliceMode },
                    { label: "Count",     value: "count"     as SliceMode },
                  ]}
                  value={sliceMode}
                  onChange={setSliceMode}
                />
              </FieldRow>

              {sliceMode === "thickness" ? (
                <FieldRow label="Board thickness" sub="millimetres">
                  <input
                    type="number" min={1} max={200} step={0.5}
                    value={thickness}
                    onChange={(e) => setThickness(e.target.value)}
                    className="input-dark"
                    style={{ width: 76, padding: "6px 10px", fontSize: 14, textAlign: "right" }}
                  />
                </FieldRow>
              ) : (
                <FieldRow label="Number of boards">
                  <input
                    type="number" min={1} max={100} step={1}
                    value={nBoards}
                    onChange={(e) => setNBoards(e.target.value)}
                    className="input-dark"
                    style={{ width: 76, padding: "6px 10px", fontSize: 14, textAlign: "right" }}
                  />
                </FieldRow>
              )}

              <FieldRow label="Quality">
                <SegControl
                  options={[
                    { label: "Accurate", value: "accurate" as Quality },
                    { label: "Fast",     value: "fast"     as Quality },
                  ]}
                  value={quality}
                  onChange={setQuality}
                />
              </FieldRow>
            </div>
          </StepSection>

          <StepConnector />

          {/* ── Step 4: Alignment Holes ── */}
          <StepSection step={4} title="Alignment Holes">
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <FieldRow label="Enable dowel holes">
                <button
                  type="button"
                  onClick={() => setAddAlignment((v) => !v)}
                  style={{
                    width: 44, height: 24, borderRadius: 9999, border: "none",
                    cursor: "pointer", position: "relative", flexShrink: 0,
                    transition: "background 0.2s",
                    background: addAlignment
                      ? "linear-gradient(135deg, #7c3aed, #0ea5e9)"
                      : "rgba(255,255,255,0.10)",
                  }}
                  aria-pressed={addAlignment}
                >
                  <span style={{
                    position: "absolute", top: 2, width: 20, height: 20, borderRadius: "50%",
                    background: "#fff", transition: "left 0.2s", boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
                    left: addAlignment ? 22 : 2,
                  }} />
                </button>
              </FieldRow>

              {addAlignment && (
                <FieldRow label="Hole pattern">
                  <SegControl
                    options={[
                      { label: "2 holes", value: "2" },
                      { label: "3 holes", value: "3" },
                      { label: "4 holes", value: "4" },
                    ]}
                    value={String(nHoles)}
                    onChange={(v) => setNHoles(parseInt(v) as NHoles)}
                  />
                </FieldRow>
              )}
            </div>
          </StepSection>

          <StepConnector />

          {/* ── Step 5: Process ── */}
          <StepSection step={5} title="Process" done={!!result && appState === "done"}>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <button
                className="btn-glow"
                onClick={handleSlice}
                disabled={!file || appState === "slicing"}
                style={{
                  padding: "13px 20px", fontSize: 14, width: "100%",
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
                }}
              >
                {appState === "slicing" ? (
                  <>
                    <Spinner />
                    Slicing{progress ? ` · ${progress.done} / ${progress.total}` : "…"}
                  </>
                ) : (
                  "▶  Slice Model"
                )}
              </button>

              {appState === "slicing" && (
                <div>
                  <div className="progress-track" style={{ height: 5 }}>
                    <div className="progress-fill" style={{ width: `${progressPct}%` }} />
                  </div>
                  <div style={{
                    display: "flex", justifyContent: "space-between",
                    marginTop: 6, fontSize: 11, color: "var(--text-muted)",
                  }}>
                    <span>{progress ? `Board ${progress.done} of ${progress.total}` : "Starting…"}</span>
                    <span>{progressPct}%</span>
                  </div>
                </div>
              )}

              {appState === "error" && (
                <div className="glass-sm" style={{
                  padding: "11px 14px", display: "flex", flexDirection: "column", gap: 8,
                  borderColor: "rgba(248,113,113,0.25)",
                }}>
                  <div style={{ display: "flex", gap: 9, alignItems: "flex-start" }}>
                    <span style={{ fontSize: 14, flexShrink: 0, marginTop: 1 }}>⚠</span>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: "#fca5a5" }}>Slicing failed</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2, wordBreak: "break-word" }}>{errorMsg}</div>
                    </div>
                  </div>
                  <button
                    className="btn-ghost"
                    onClick={handleSlice}
                    disabled={!file}
                    style={{ padding: "6px 14px", fontSize: 12, width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}
                  >
                    ↺ Try again
                  </button>
                </div>
              )}

              {result && appState === "done" && (
                <div style={{ fontSize: 11, color: "var(--text-subtle)", textAlign: "center" }}>
                  {result.n_boards} boards · {result.board_thickness.toFixed(1)} mm each ·{" "}
                  {result.model_span.toFixed(0)} mm span
                </div>
              )}
            </div>
          </StepSection>

        </div>
        {/* end LEFT PANEL */}

        {/* ────────────────── RIGHT PANEL — Preview + Step 6 ────────────────── */}
        <div className="glass" style={{
          flex: 1, minWidth: 0,
          padding: "22px 24px",
          display: "flex", flexDirection: "column", gap: 20,
          minHeight: 560,
        }}>

          {/* ── Idle: no result ── */}
          {appState !== "slicing" && !result && (
            <div style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              gap: 20, padding: "32px 0",
            }}>
              <SlicerIllustration />
              {file ? (
                <>
                  <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>
                    Ready to slice
                  </div>
                  <div style={{
                    fontSize: 13, color: "var(--text-muted)", textAlign: "center",
                    maxWidth: 320, lineHeight: 1.65,
                  }}>
                    Parameters are configured on the left. Click{" "}
                    <strong style={{ color: "var(--text-primary)" }}>Slice Model</strong>{" "}
                    to generate board profiles.
                  </div>
                  <div className="glass-sm" style={{ padding: "10px 18px", display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ fontSize: 14 }}>📐</span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{file.name}</span>
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{formatBytes(file.size)}</span>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)" }}>
                    Upload a 3D model to get started
                  </div>
                  <div style={{
                    fontSize: 13, color: "var(--text-muted)", textAlign: "center",
                    maxWidth: 340, lineHeight: 1.7,
                  }}>
                    Drop a 3D mesh file in Step 1. The engine will slice it into flat
                    board profiles and generate fabrication-ready DXF files.
                  </div>
                  {/* Mini how-it-works */}
                  <div style={{
                    display: "flex", gap: 0, alignItems: "center",
                    padding: "12px 20px",
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid var(--glass-border)", borderRadius: 10,
                  }}>
                    {["Upload 3D model", "Configure", "Slice", "Export DXF"].map((s, i, a) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 0, flexShrink: 0 }}>
                        <span style={{ fontSize: 11, color: "var(--text-subtle)", padding: "0 10px" }}>{s}</span>
                        {i < a.length - 1 && (
                          <span style={{ color: "var(--text-subtle)", fontSize: 10 }}>→</span>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Slicing: board tile animation ── */}
          {appState === "slicing" && (
            <div style={{
              flex: 1, display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              gap: 28, padding: "24px 0",
            }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)", marginBottom: 6 }}>
                  Processing boards…
                </div>
                <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                  {progress
                    ? `Board ${progress.done} of ${progress.total} complete`
                    : "Initialising engine…"}
                </div>
              </div>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", maxWidth: 440 }}>
                {Array.from({ length: progress?.total || 8 }, (_, i) => {
                  const done    = i < (progress?.done ?? 0);
                  const current = i === (progress?.done ?? -1);
                  return (
                    <div key={i} style={{
                      width: 44, height: 44, borderRadius: 9,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 600,
                      fontFamily: "var(--font-geist-mono), monospace",
                      background: done
                        ? "linear-gradient(135deg, rgba(124,58,237,0.5), rgba(14,165,233,0.5))"
                        : current ? "rgba(124,58,237,0.22)" : "rgba(255,255,255,0.04)",
                      border: `1px solid ${done ? "rgba(124,58,237,0.6)" : current ? "rgba(124,58,237,0.45)" : "rgba(255,255,255,0.07)"}`,
                      color: done ? "#c4b5fd" : current ? "#a78bfa" : "var(--text-subtle)",
                      boxShadow: done ? "0 0 12px rgba(124,58,237,0.38)" : "none",
                      transition: "background 0.3s, border-color 0.3s, box-shadow 0.3s",
                      animation: current ? "pulseDot 1.1s ease-in-out infinite" : "none",
                    }}>
                      {i + 1}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Step 6: Inspect & Export ── */}
          {result && appState === "done" && (
            <>
              {/* Step 6 header row */}
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{
                  width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                  background: "linear-gradient(135deg, rgba(124,58,237,0.55), rgba(14,165,233,0.55))",
                  border: "1px solid rgba(124,58,237,0.45)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 10, fontWeight: 700, color: "#ddd6fe",
                }}>6</div>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: "var(--text-subtle)",
                  textTransform: "uppercase", letterSpacing: "0.09em",
                }}>
                  Inspect &amp; Export
                </div>
                <span className="chip chip-green" style={{ marginLeft: "auto" }}>✓ Done</span>
              </div>

              {/* Board viewer controls */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", fontFamily: "var(--font-geist-mono)" }}>
                    {result.slices[selectedBoard]?.label ?? "—"}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {selectedBoard + 1} / {result.slices.length}
                  </span>
                  {viewMode === "2d" && (
                    <span className="chip chip-violet">
                      {result.slices[selectedBoard]?.contours.length ?? 0} contour
                      {result.slices[selectedBoard]?.contours.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>

                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {/* 2D / 3D toggle */}
                  <div className="seg-control" style={{ padding: 2 }}>
                    {(["2d", "3d"] as const).map((m) => (
                      <button
                        key={m}
                        className={`seg-btn${viewMode === m ? " active" : ""}`}
                        onClick={() => setViewMode(m)}
                        type="button"
                        style={{ padding: "4px 12px", fontSize: 12 }}
                      >
                        {m.toUpperCase()}
                      </button>
                    ))}
                  </div>

                  {viewMode === "2d" && (
                    <>
                      <button className="btn-ghost"
                        onClick={() => goBoard(selectedBoard - 1)}
                        disabled={selectedBoard === 0}
                        style={{ padding: "5px 11px", fontSize: 13 }}
                        title="Previous board">←</button>
                      <button className="btn-ghost"
                        onClick={() => goBoard(selectedBoard + 1)}
                        disabled={selectedBoard >= totalBoards - 1}
                        style={{ padding: "5px 11px", fontSize: 13 }}
                        title="Next board">→</button>
                    </>
                  )}
                </div>
              </div>

              {/* Canvas */}
              {viewMode === "2d" ? (
                <div style={{ borderRadius: 12, overflow: "hidden" }}>
                  <BoardCanvas slice={result.slices[selectedBoard]} />
                </div>
              ) : (
                <Board3DViewer
                  result={result}
                  selectedBoard={selectedBoard}
                  onSelectBoard={setSelectedBoard}
                />
              )}

              {/* Board strip */}
              <div ref={boardStripRef} style={{
                display: "flex", gap: 6, overflowX: "auto",
                paddingBottom: 4, scrollbarWidth: "none",
              }}>
                {result.slices.map((sl, i) => (
                  <button
                    key={sl.index}
                    onClick={() => setSelectedBoard(i)}
                    style={{
                      flexShrink: 0, padding: "5px 10px", borderRadius: 7, cursor: "pointer",
                      border: `1px solid ${i === selectedBoard ? "rgba(124,58,237,0.55)" : "var(--glass-border)"}`,
                      background: i === selectedBoard
                        ? "linear-gradient(135deg, rgba(124,58,237,0.28), rgba(14,165,233,0.18))"
                        : "rgba(255,255,255,0.03)",
                      color: i === selectedBoard ? "#c4b5fd" : "var(--text-muted)",
                      fontSize: 11, fontWeight: 600,
                      fontFamily: "var(--font-geist-mono), monospace",
                      transition: "background 0.15s, border-color 0.15s, color 0.15s",
                    }}
                  >
                    {sl.label}
                  </button>
                ))}
              </div>

              {/* Stats */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                <StatCard label="Boards"     value={String(result.n_boards)} />
                <StatCard label="Thickness"  value={result.board_thickness.toFixed(1)} sub="mm / board" />
                <StatCard label="Span"       value={result.model_span.toFixed(0)}       sub="mm total" />
                <StatCard label="Axis"       value={result.stacking_axis.toUpperCase()} sub={result.slab_mode} />
              </div>

              {/* Export */}
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  className={exportSuccess === "combined" ? "btn-success" : "btn-glow"}
                  onClick={() => handleExport("combined")}
                  disabled={exportBusy !== null}
                  style={{ flex: 1, padding: "13px 18px", fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                >
                  {exportSuccess === "combined" ? "✓ Downloaded" : exportBusy === "combined" ? <><Spinner />Exporting…</> : "⬇  Download DXF"}
                </button>
                <button
                  className={exportSuccess === "per_board" ? "btn-success" : "btn-ghost"}
                  onClick={() => handleExport("per_board")}
                  disabled={exportBusy !== null}
                  style={{ flex: 1, padding: "13px 18px", fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                >
                  {exportSuccess === "per_board" ? "✓ Downloaded" : exportBusy === "per_board" ? <><Spinner />Exporting…</> : "⬇  Per-board ZIP"}
                </button>
              </div>

              <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 16 }}>
                <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
                  Adjust Steps 2–4 and slice again to refine.
                </span>
                <button
                  className="btn-ghost"
                  onClick={() => { setResult(null); setAppState("idle"); setProgress(null); }}
                  style={{ padding: "4px 11px", fontSize: 11, flexShrink: 0 }}
                >
                  ↺ New file
                </button>
              </div>
            </>
          )}
        </div>
        {/* end RIGHT PANEL */}

      </div>
    </div>
  );
}
