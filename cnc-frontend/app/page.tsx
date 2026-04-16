"use client";

import {
  useRef,
  useState,
  useCallback,
  useEffect,
  DragEvent,
  ChangeEvent,
} from "react";
import dynamic from "next/dynamic";
import {
  sliceModel,
  exportDXF,
  exportDXFPerBoard,
  checkHealth,
  SliceResult,
  SliceParams,
  SliceProgress,
} from "@/lib/api";
import BoardCanvas from "./components/BoardCanvas";

// 3-D viewer is loaded only on the client — Three.js has no SSR support
const Board3DViewer = dynamic(() => import("./components/Board3DViewer"), {
  ssr: false,
  loading: () => (
    <div
      style={{
        width: "100%",
        height: 380,
        background: "rgba(2,2,12,0.6)",
        borderRadius: 12,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--text-subtle)",
        fontSize: 13,
      }}
    >
      Loading 3D viewer…
    </div>
  ),
});

// ── Types ─────────────────────────────────────────────────────────────────────

type SliceMode = "thickness" | "count";
type Axis = "x" | "y" | "z";
type Quality = "accurate" | "fast";
type SlabMode = "envelope" | "best_sample";
type AppState = "idle" | "slicing" | "done" | "error";
type NHoles = 2 | 3 | 4;

// ── Tiny shared components ─────────────────────────────────────────────────────

function SegControl<T extends string>({
  options,
  value,
  onChange,
  small,
}: {
  options: { label: string; value: T }[];
  value: T;
  onChange: (v: T) => void;
  small?: boolean;
}) {
  return (
    <div className="seg-control" style={small ? { fontSize: 12 } : undefined}>
      {options.map((o) => (
        <button
          key={o.value}
          className={`seg-btn${value === o.value ? " active" : ""}`}
          onClick={() => onChange(o.value)}
          type="button"
          style={small ? { padding: "5px 10px", fontSize: 12 } : undefined}
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
  sub,
}: {
  label: string;
  children: React.ReactNode;
  sub?: string;
}) {
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

function Divider() {
  return <hr style={{ border: "none", borderTop: "1px solid var(--glass-border)", margin: "4px 0" }} />;
}

function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        border: `${size <= 14 ? 2 : 3}px solid rgba(255,255,255,0.25)`,
        borderTopColor: "#fff",
        borderRadius: "50%",
        animation: "spin 0.7s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="glass-sm" style={{ padding: "12px 14px", textAlign: "center" }}>
      <div
        style={{
          fontSize: 20,
          fontWeight: 700,
          background: "linear-gradient(135deg, #a78bfa, #38bdf8)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          lineHeight: 1.2,
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      {sub && <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

function PanelTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
      {children}
    </div>
  );
}

// Isometric STL placeholder illustration
function STLIllustration() {
  return (
    <svg viewBox="0 0 200 155" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width: 180, opacity: 0.65 }}>
      {/* Top face */}
      <polygon points="100,18 158,48 100,78 42,48" fill="rgba(124,58,237,0.10)" stroke="rgba(124,58,237,0.45)" strokeWidth="1.5" strokeLinejoin="round" />
      {/* Right face */}
      <polygon points="158,48 158,108 100,138 100,78" fill="rgba(14,165,233,0.07)" stroke="rgba(14,165,233,0.38)" strokeWidth="1.5" strokeLinejoin="round" />
      {/* Left face */}
      <polygon points="42,48 42,108 100,138 100,78" fill="rgba(124,58,237,0.05)" stroke="rgba(124,58,237,0.32)" strokeWidth="1.5" strokeLinejoin="round" />
      {/* Slice lines — right face */}
      <line x1="158" y1="68" x2="100" y2="98" stroke="rgba(14,165,233,0.6)" strokeWidth="1.2" strokeDasharray="4,3" />
      <line x1="158" y1="88" x2="100" y2="118" stroke="rgba(14,165,233,0.6)" strokeWidth="1.2" strokeDasharray="4,3" />
      {/* Slice lines — left face */}
      <line x1="42" y1="68" x2="100" y2="98" stroke="rgba(124,58,237,0.55)" strokeWidth="1.2" strokeDasharray="4,3" />
      <line x1="42" y1="88" x2="100" y2="118" stroke="rgba(124,58,237,0.55)" strokeWidth="1.2" strokeDasharray="4,3" />
      {/* Arrow hinting the slicing direction */}
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

export default function Home() {
  // ── File
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // ── Params
  const [axis, setAxis] = useState<Axis>("y");
  const [sliceMode, setSliceMode] = useState<SliceMode>("thickness");
  const [thickness, setThickness] = useState("20");
  const [nBoards, setNBoards] = useState("8");
  const [slabMode, setSlabMode] = useState<SlabMode>("envelope");
  const [quality, setQuality] = useState<Quality>("accurate");
  const [addAlignment, setAddAlignment] = useState(true);
  const [nHoles, setNHoles] = useState<NHoles>(4);

  // ── App state
  const [appState, setAppState] = useState<AppState>("idle");
  const [progress, setProgress] = useState<SliceProgress | null>(null);
  const [result, setResult] = useState<SliceResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [exportBusy, setExportBusy] = useState<"combined" | "per_board" | null>(null);

  // ── Board viewer
  const [selectedBoard, setSelectedBoard] = useState(0);
  const [viewMode, setViewMode] = useState<"2d" | "3d">("2d");
  const boardStripRef = useRef<HTMLDivElement>(null);

  // ── Backend health
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  useEffect(() => {
    checkHealth().then(setBackendOk);
  }, []);

  // ── Drag & drop
  const onDragOver = useCallback((e: DragEvent) => { e.preventDefault(); setDragging(true); }, []);
  const onDragLeave = useCallback(() => setDragging(false), []);
  const onDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) acceptFile(f);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) acceptFile(f);
  };
  function acceptFile(f: File) {
    setFile(f);
    setResult(null);
    setErrorMsg("");
    setAppState("idle");
    setProgress(null);
    setSelectedBoard(0);
  }

  // ── Slice
  async function handleSlice() {
    if (!file) return;
    setAppState("slicing");
    setProgress(null);
    setResult(null);
    setErrorMsg("");
    setSelectedBoard(0);

    const params: SliceParams = {
      axis,
      slab_mode: slabMode,
      quality,
      slice_mode: sliceMode,
      thickness: parseFloat(thickness) || 20,
      n_boards: parseInt(nBoards) || 8,
      add_alignment: addAlignment,
      n_holes: nHoles,
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

  // ── Export
  async function handleExport(mode: "combined" | "per_board") {
    if (!result) return;
    setExportBusy(mode);
    try {
      if (mode === "combined") {
        await exportDXF(result, { filename: "boards.dxf" });
      } else {
        await exportDXFPerBoard(result, { filename: "boards.zip" });
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setExportBusy(null);
    }
  }

  // ── Board navigation
  const totalBoards = result?.slices.length ?? 0;
  const goBoard = (i: number) => setSelectedBoard(Math.max(0, Math.min(i, totalBoards - 1)));

  // Scroll selected board pill into view
  useEffect(() => {
    const el = boardStripRef.current?.children[selectedBoard] as HTMLElement | undefined;
    el?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [selectedBoard]);

  // ── Progress %
  const progressPct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", padding: "28px 20px 64px" }}>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header style={{ width: "100%", maxWidth: 1100, display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 38, height: 38, borderRadius: 10, flexShrink: 0,
            background: "linear-gradient(135deg, #7c3aed, #0ea5e9)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 19, boxShadow: "0 0 18px rgba(124,58,237,0.55)",
          }}>◈</div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, letterSpacing: "-0.01em", color: "var(--text-primary)" }}>
              CNC DXF Generator
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              STL → board profiles → fabrication DXF
            </div>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {/* Backend health indicator */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 10px", borderRadius: 9999, border: "1px solid var(--glass-border)", background: "var(--glass-bg)" }}>
            <span style={{
              width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
              background: backendOk === null ? "#6b7280" : backendOk ? "#22c55e" : "#ef4444",
              boxShadow: backendOk === null ? "none" : backendOk ? "0 0 6px #22c55e" : "0 0 6px #ef4444",
              animation: backendOk === null ? "pulseDot 1.5s ease-in-out infinite" : "none",
            }} />
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {backendOk === null ? "Connecting…" : backendOk ? "Backend online" : "Backend offline"}
            </span>
          </div>
          <span className="chip chip-violet">Beta</span>
        </div>
      </header>

      {/* ── Two-column layout ───────────────────────────────────────────────── */}
      <div style={{ width: "100%", maxWidth: 1100, display: "flex", gap: 20, alignItems: "flex-start" }}>

        {/* ── LEFT PANEL — Controls ──────────────────────────────────────────── */}
        <div className="glass" style={{ width: 368, flexShrink: 0, padding: "24px 24px", display: "flex", flexDirection: "column", gap: 20 }}>

          {/* Upload */}
          <section>
            <PanelTitle>Upload</PanelTitle>
            <div
              className={`dropzone${dragging ? " over" : ""}`}
              style={{ padding: file ? "14px 16px" : "32px 16px", display: "flex", flexDirection: "column", alignItems: "center", gap: 8, cursor: "pointer" }}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
            >
              <input ref={fileRef} type="file" accept=".stl,.STL" style={{ display: "none" }} onChange={onFileChange} />
              {file ? (
                <div style={{ display: "flex", alignItems: "center", gap: 12, width: "100%" }}>
                  <div style={{ width: 38, height: 38, borderRadius: 9, background: "rgba(124,58,237,0.18)", border: "1px solid rgba(124,58,237,0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>
                    📐
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-primary)" }}>
                      {file.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                      {formatBytes(file.size)} · click to replace
                    </div>
                  </div>
                  <span className="chip chip-green">Ready</span>
                </div>
              ) : (
                <>
                  <div style={{ fontSize: 28, opacity: 0.45, lineHeight: 1 }}>⬆</div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-muted)", textAlign: "center" }}>
                    Drop STL file or click to browse
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-subtle)" }}>ASCII and binary STL supported</div>
                </>
              )}
            </div>
          </section>

          <Divider />

          {/* Parameters */}
          <section>
            <PanelTitle>Parameters</PanelTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>

              <FieldRow label="Stacking axis">
                <SegControl
                  options={[
                    { label: "X", value: "x" as Axis },
                    { label: "Y", value: "y" as Axis },
                    { label: "Z", value: "z" as Axis },
                  ]}
                  value={axis}
                  onChange={setAxis}
                  small
                />
              </FieldRow>

              <FieldRow label="Board profile">
                <SegControl
                  options={[
                    { label: "Envelope", value: "envelope" as SlabMode },
                    { label: "Best sample", value: "best_sample" as SlabMode },
                  ]}
                  value={slabMode}
                  onChange={setSlabMode}
                  small
                />
              </FieldRow>

              <FieldRow label="Slice by">
                <SegControl
                  options={[
                    { label: "Thickness", value: "thickness" as SliceMode },
                    { label: "Count", value: "count" as SliceMode },
                  ]}
                  value={sliceMode}
                  onChange={setSliceMode}
                  small
                />
              </FieldRow>

              {sliceMode === "thickness" ? (
                <FieldRow label="Board thickness" sub="mm">
                  <input
                    type="number" min={1} max={200} step={0.5}
                    value={thickness}
                    onChange={(e) => setThickness(e.target.value)}
                    className="input-dark"
                    style={{ width: 80, padding: "6px 10px", fontSize: 14, textAlign: "right" }}
                  />
                </FieldRow>
              ) : (
                <FieldRow label="Number of boards">
                  <input
                    type="number" min={1} max={100} step={1}
                    value={nBoards}
                    onChange={(e) => setNBoards(e.target.value)}
                    className="input-dark"
                    style={{ width: 80, padding: "6px 10px", fontSize: 14, textAlign: "right" }}
                  />
                </FieldRow>
              )}

              <FieldRow label="Quality">
                <SegControl
                  options={[
                    { label: "Accurate", value: "accurate" as Quality },
                    { label: "Fast", value: "fast" as Quality },
                  ]}
                  value={quality}
                  onChange={setQuality}
                  small
                />
              </FieldRow>

            </div>
          </section>

          <Divider />

          {/* Alignment */}
          <section>
            <PanelTitle>Alignment Holes</PanelTitle>
            <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>

              <FieldRow label="Enable">
                {/* Toggle switch */}
                <button
                  type="button"
                  onClick={() => setAddAlignment((v) => !v)}
                  style={{
                    width: 44, height: 24, borderRadius: 9999, border: "none", cursor: "pointer",
                    position: "relative", flexShrink: 0, transition: "background 0.2s",
                    background: addAlignment ? "linear-gradient(135deg, #7c3aed, #0ea5e9)" : "rgba(255,255,255,0.1)",
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
                <FieldRow label="Pattern">
                  <SegControl
                    options={[
                      { label: "2", value: 2 as unknown as string },
                      { label: "3", value: 3 as unknown as string },
                      { label: "4", value: 4 as unknown as string },
                    ]}
                    value={String(nHoles)}
                    onChange={(v) => setNHoles(parseInt(v) as NHoles)}
                    small
                  />
                </FieldRow>
              )}

            </div>
          </section>

          <Divider />

          {/* Slice action */}
          <section>
            <button
              className="btn-glow"
              onClick={handleSlice}
              disabled={!file || appState === "slicing"}
              style={{ padding: "13px 20px", fontSize: 14, width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}
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
              <div style={{ marginTop: 12 }}>
                <div className="progress-track" style={{ height: 5 }}>
                  <div className="progress-fill" style={{ width: `${progressPct}%` }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5, fontSize: 11, color: "var(--text-muted)" }}>
                  <span>{progress ? `Board ${progress.done} of ${progress.total}` : "Starting…"}</span>
                  <span>{progressPct}%</span>
                </div>
              </div>
            )}

            {appState === "error" && (
              <div className="glass-sm" style={{ marginTop: 12, padding: "11px 14px", display: "flex", gap: 9, alignItems: "flex-start", borderColor: "rgba(248,113,113,0.25)" }}>
                <span style={{ fontSize: 14, flexShrink: 0, marginTop: 1 }}>⚠</span>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "#fca5a5" }}>Slicing failed</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{errorMsg}</div>
                </div>
              </div>
            )}
          </section>

        </div>
        {/* end LEFT PANEL */}

        {/* ── RIGHT PANEL — Preview / Results ───────────────────────────────── */}
        <div className="glass" style={{ flex: 1, minWidth: 0, padding: "24px 24px", display: "flex", flexDirection: "column", gap: 20, minHeight: 480 }}>

          {/* ── Idle: no result ── */}
          {appState !== "slicing" && !result && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20, padding: "32px 0" }}>
              <STLIllustration />
              {file ? (
                <>
                  <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)" }}>
                    Ready to slice
                  </div>
                  <div style={{ fontSize: 13, color: "var(--text-muted)", textAlign: "center", maxWidth: 320 }}>
                    Configure your parameters on the left, then click <strong style={{ color: "var(--text-primary)" }}>Slice Model</strong> to generate board profiles.
                  </div>
                  <div className="glass-sm" style={{ padding: "10px 18px", display: "flex", gap: 8, alignItems: "center" }}>
                    <span style={{ fontSize: 14 }}>📐</span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{file.name}</span>
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{formatBytes(file.size)}</span>
                  </div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)" }}>
                    Upload an STL to get started
                  </div>
                  <div style={{ fontSize: 13, color: "var(--text-muted)", textAlign: "center", maxWidth: 320, lineHeight: 1.6 }}>
                    Drop a 3D mesh file on the left. The engine will slice it into CNC-ready board profiles and generate fabrication DXF files.
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Slicing animation ── */}
          {appState === "slicing" && (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24, padding: "24px 0" }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-primary)", marginBottom: 6 }}>
                  Processing boards…
                </div>
                <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
                  {progress ? `Board ${progress.done} of ${progress.total}` : "Initialising engine…"}
                </div>
              </div>
              {/* Board tile grid */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", maxWidth: 420 }}>
                {Array.from({ length: progress?.total || 8 }, (_, i) => {
                  const done = i < (progress?.done ?? 0);
                  const current = i === (progress?.done ?? -1);
                  return (
                    <div
                      key={i}
                      style={{
                        width: 42,
                        height: 42,
                        borderRadius: 8,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 11,
                        fontWeight: 600,
                        fontFamily: "var(--font-geist-mono), monospace",
                        background: done
                          ? "linear-gradient(135deg, rgba(124,58,237,0.45), rgba(14,165,233,0.45))"
                          : current
                          ? "rgba(124,58,237,0.22)"
                          : "rgba(255,255,255,0.04)",
                        border: `1px solid ${done ? "rgba(124,58,237,0.55)" : current ? "rgba(124,58,237,0.45)" : "rgba(255,255,255,0.07)"}`,
                        color: done ? "#c4b5fd" : current ? "#a78bfa" : "var(--text-subtle)",
                        boxShadow: done ? "0 0 12px rgba(124,58,237,0.35)" : "none",
                        transition: "background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease",
                        animation: current ? "pulseDot 1.1s ease-in-out infinite" : "none",
                      }}
                    >
                      {i + 1}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Results ── */}
          {result && appState === "done" && (
            <>
              {/* Board viewer header */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                {/* Left: board label + meta */}
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", fontFamily: "var(--font-geist-mono)" }}>
                    {result.slices[selectedBoard]?.label ?? "—"}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {selectedBoard + 1} / {result.slices.length}
                  </span>
                  {viewMode === "2d" && (
                    <span className="chip chip-violet">
                      {result.slices[selectedBoard]?.contours.length ?? 0} contour{result.slices[selectedBoard]?.contours.length !== 1 ? "s" : ""}
                    </span>
                  )}
                </div>

                {/* Right: 2D/3D toggle + prev/next (2D only) */}
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  {/* 2D / 3D pill toggle */}
                  <div className="seg-control" style={{ padding: 2 }}>
                    <button
                      className={`seg-btn${viewMode === "2d" ? " active" : ""}`}
                      onClick={() => setViewMode("2d")}
                      type="button"
                      style={{ padding: "4px 12px", fontSize: 12 }}
                    >
                      2D
                    </button>
                    <button
                      className={`seg-btn${viewMode === "3d" ? " active" : ""}`}
                      onClick={() => setViewMode("3d")}
                      type="button"
                      style={{ padding: "4px 12px", fontSize: 12 }}
                    >
                      3D
                    </button>
                  </div>

                  {/* Prev / Next — only meaningful in 2D */}
                  {viewMode === "2d" && (
                    <>
                      <button
                        className="btn-ghost"
                        onClick={() => goBoard(selectedBoard - 1)}
                        disabled={selectedBoard === 0}
                        style={{ padding: "5px 11px", fontSize: 13 }}
                        title="Previous board"
                      >←</button>
                      <button
                        className="btn-ghost"
                        onClick={() => goBoard(selectedBoard + 1)}
                        disabled={selectedBoard >= totalBoards - 1}
                        style={{ padding: "5px 11px", fontSize: 13 }}
                        title="Next board"
                      >→</button>
                    </>
                  )}
                </div>
              </div>

              {/* Board canvas — 2D SVG or 3D Three.js */}
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

              {/* Board selector strip */}
              <div
                ref={boardStripRef}
                style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4, scrollbarWidth: "none" }}
              >
                {result.slices.map((sl, i) => (
                  <button
                    key={sl.index}
                    onClick={() => setSelectedBoard(i)}
                    style={{
                      flexShrink: 0,
                      padding: "5px 10px",
                      borderRadius: 7,
                      border: `1px solid ${i === selectedBoard ? "rgba(124,58,237,0.55)" : "var(--glass-border)"}`,
                      background: i === selectedBoard
                        ? "linear-gradient(135deg, rgba(124,58,237,0.3), rgba(14,165,233,0.2))"
                        : "rgba(255,255,255,0.03)",
                      color: i === selectedBoard ? "#c4b5fd" : "var(--text-muted)",
                      fontSize: 11,
                      fontWeight: 600,
                      fontFamily: "var(--font-geist-mono), monospace",
                      cursor: "pointer",
                      transition: "background 0.15s, border-color 0.15s, color 0.15s",
                    }}
                  >
                    {sl.label}
                  </button>
                ))}
              </div>

              <Divider />

              {/* Stats row */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
                <StatCard label="Boards" value={String(result.n_boards)} />
                <StatCard label="Thickness" value={result.board_thickness.toFixed(1)} sub="mm / board" />
                <StatCard label="Span" value={result.model_span.toFixed(0)} sub="mm" />
                <StatCard label="Axis" value={result.stacking_axis.toUpperCase()} sub={result.slab_mode} />
              </div>

              {/* Export buttons */}
              <div style={{ display: "flex", gap: 10 }}>
                <button
                  className="btn-glow"
                  onClick={() => handleExport("combined")}
                  disabled={exportBusy !== null}
                  style={{ flex: 1, padding: "12px 18px", fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                >
                  {exportBusy === "combined" ? <><Spinner />Exporting…</> : "⬇  Download DXF"}
                </button>
                <button
                  className="btn-ghost"
                  onClick={() => handleExport("per_board")}
                  disabled={exportBusy !== null}
                  style={{ flex: 1, padding: "12px 18px", fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
                >
                  {exportBusy === "per_board" ? <><Spinner />Exporting…</> : "⬇  Per-board ZIP"}
                </button>
              </div>

              {/* Slice again hint */}
              <div style={{ textAlign: "center" }}>
                <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
                  Adjust parameters and click Slice Model again to re-process.
                </span>
              </div>
            </>
          )}

        </div>
        {/* end RIGHT PANEL */}

      </div>
      {/* end two-column layout */}

      {/* ── Floating Editor button ─────────────────────────────────────────── */}
      <a
        href="/editor"
        style={{
          position: "fixed", bottom: 24, right: 24, zIndex: 50,
          display: "flex", alignItems: "center", gap: 7,
          padding: "10px 18px", borderRadius: 12,
          background: "rgba(6,6,18,0.88)",
          border: "1px solid rgba(255,255,255,0.11)",
          backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
          color: "var(--text-primary)", fontSize: 13, fontWeight: 600,
          textDecoration: "none", boxShadow: "0 4px 20px rgba(0,0,0,0.5)",
          transition: "border-color 0.2s, box-shadow 0.2s, transform 0.12s",
        }}
        onMouseEnter={(e) => {
          const el = e.currentTarget as HTMLAnchorElement;
          el.style.borderColor = "rgba(124,58,237,0.5)";
          el.style.boxShadow = "0 4px 20px rgba(0,0,0,0.5), 0 0 16px rgba(124,58,237,0.28)";
          el.style.transform = "translateY(-1px)";
        }}
        onMouseLeave={(e) => {
          const el = e.currentTarget as HTMLAnchorElement;
          el.style.borderColor = "rgba(255,255,255,0.11)";
          el.style.boxShadow = "0 4px 20px rgba(0,0,0,0.5)";
          el.style.transform = "translateY(0)";
        }}
      >
        <span style={{ fontSize: 14 }}>✏</span>
        Open Editor
      </a>

    </main>
  );
}
