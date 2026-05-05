"use client";

import { useState, useRef, useCallback, useEffect, MouseEvent } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Contour {
  id: number;
  points: [number, number][];
  visible: boolean;
  color: string;
}

interface ViewState {
  x: number; y: number; scale: number;
}

const PALETTE = [
  "#7c3aed","#0ea5e9","#ec4899","#10b981","#f59e0b",
  "#ef4444","#6366f1","#06b6d4","#a855f7","#14b8a6",
];

// ── DXF parser (minimal — reads LINE and LWPOLYLINE entities) ─────────────────

function parseDxf(text: string): Contour[] {
  const contours: Contour[] = [];
  const lines = text.split(/\r?\n/);
  let i = 0;
  let id = 0;

  function next() { return lines[i++]?.trim() ?? ""; }

  while (i < lines.length) {
    const code = next();
    const val  = next();
    if (code === "0" && val === "LWPOLYLINE") {
      const pts: [number, number][] = [];
      let cx = 0, cy = 0;
      while (i < lines.length) {
        const c = next(), v = next();
        if (c === "0") { i -= 2; break; }
        if (c === "10") cx = parseFloat(v);
        if (c === "20") { cy = parseFloat(v); pts.push([cx, cy]); }
      }
      if (pts.length >= 2) {
        contours.push({ id: id++, points: pts, visible: true, color: PALETTE[id % PALETTE.length] });
      }
    } else if (code === "0" && val === "LINE") {
      let x1 = 0, y1 = 0, x2 = 0, y2 = 0;
      while (i < lines.length) {
        const c = next(), v = next();
        if (c === "0") { i -= 2; break; }
        if (c === "10") x1 = parseFloat(v);
        if (c === "20") y1 = parseFloat(v);
        if (c === "11") x2 = parseFloat(v);
        if (c === "21") y2 = parseFloat(v);
      }
      contours.push({ id: id++, points: [[x1, y1], [x2, y2]], visible: true, color: PALETTE[id % PALETTE.length] });
    }
  }
  return contours;
}

// ── Canvas viewer ─────────────────────────────────────────────────────────────

function EditorCanvas({ contours, view, onView }: {
  contours: Contour[];
  view: ViewState;
  onView: (v: ViewState) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);
  const dragStart = useRef({ mx: 0, my: 0, vx: 0, vy: 0 });
  const [hover, setHover] = useState<number | null>(null);

  const viewRef = useRef(view);
  useEffect(() => { viewRef.current = view; });

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const handleWheel = (e: Event) => {
      const we = e as WheelEvent;
      we.preventDefault();
      const factor = we.deltaY < 0 ? 1.12 : 0.89;
      const rect = el.getBoundingClientRect();
      const mx = we.clientX - rect.left, my = we.clientY - rect.top;
      const v = viewRef.current;
      onView({
        scale: v.scale * factor,
        x: mx - (mx - v.x) * factor,
        y: my - (my - v.y) * factor,
      });
    };
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [onView]);

  function onMouseDown(e: MouseEvent) {
    dragging.current = true;
    dragStart.current = { mx: e.clientX, my: e.clientY, vx: view.x, vy: view.y };
  }
  function onMouseMove(e: MouseEvent) {
    if (!dragging.current) return;
    const dx = e.clientX - dragStart.current.mx, dy = e.clientY - dragStart.current.my;
    onView({ ...view, x: dragStart.current.vx + dx, y: dragStart.current.vy + dy });
  }
  function onMouseUp() { dragging.current = false; }

  const visible = contours.filter(c => c.visible);

  // Compute world bounds for fit
  function fitAll() {
    if (!visible.length || !svgRef.current) return;
    const all = visible.flatMap(c => c.points);
    const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const w = maxX - minX || 1, h = maxY - minY || 1;
    const rect = svgRef.current.getBoundingClientRect();
    const s = Math.min((rect.width - 80) / w, (rect.height - 80) / h) * 0.9;
    onView({
      scale: s,
      x: (rect.width  - w * s) / 2 - minX * s,
      y: (rect.height - h * s) / 2 - minY * s,
    });
  }

  return (
    <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
      <svg ref={svgRef} style={{ width: "100%", height: "100%", cursor: "grab", display: "block", userSelect: "none" }}
        onMouseDown={onMouseDown} onMouseMove={onMouseMove}
        onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
        <defs>
          <pattern id="eg" width="40" height="40" patternUnits="userSpaceOnUse"
            patternTransform={`translate(${view.x % 40},${view.y % 40})`}>
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#eg)" />

        {/* Origin cross */}
        <line x1={view.x - 12} y1={view.y} x2={view.x + 12} y2={view.y} stroke="rgba(255,255,255,0.12)" strokeWidth={1} />
        <line x1={view.x} y1={view.y - 12} x2={view.x} y2={view.y + 12} stroke="rgba(255,255,255,0.12)" strokeWidth={1} />

        {visible.map(c => {
          const pts = c.points.map(([x, y]) => `${view.x + x * view.scale},${view.y - y * view.scale}`).join(" ");
          const isHov = hover === c.id;
          return (
            <polyline key={c.id} points={pts} fill="none"
              stroke={isHov ? "#fff" : c.color}
              strokeWidth={isHov ? 2 : 1.2}
              opacity={isHov ? 1 : 0.8}
              onMouseEnter={() => setHover(c.id)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "pointer" }}
            />
          );
        })}
      </svg>

      {/* Fit button */}
      <button onClick={fitAll}
        style={{
          position: "absolute", bottom: 12, right: 12,
          padding: "6px 12px", borderRadius: 7, fontSize: 11, fontWeight: 600,
          background: "rgba(0,0,0,0.5)", border: "1px solid var(--glass-border)",
          color: "var(--text-muted)", cursor: "pointer",
        }}>
        Fit ⊡
      </button>

      {/* Zoom indicator */}
      <div style={{ position: "absolute", bottom: 12, left: 12, fontSize: 10, color: "var(--text-subtle)" }}>
        {(view.scale * 100).toFixed(0)}%
      </div>
    </div>
  );
}

// ── Layer panel ───────────────────────────────────────────────────────────────

function LayerPanel({ contours, onToggle, onColor, selected, onSelect }: {
  contours: Contour[];
  onToggle: (id: number) => void;
  onColor: (id: number, c: string) => void;
  selected: number | null;
  onSelect: (id: number | null) => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, overflowY: "auto", maxHeight: 380 }}>
      {contours.map(c => (
        <div key={c.id} onClick={() => onSelect(selected === c.id ? null : c.id)}
          style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 8px",
            borderRadius: 7, cursor: "pointer", transition: "background 0.12s",
            background: selected === c.id ? "rgba(124,58,237,0.15)" : "transparent",
            border: `1px solid ${selected === c.id ? "rgba(124,58,237,0.3)" : "transparent"}`,
          }}>
          {/* Visibility toggle */}
          <button onClick={e => { e.stopPropagation(); onToggle(c.id); }}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 0,
              fontSize: 13, color: c.visible ? "var(--text-primary)" : "var(--text-subtle)", lineHeight: 1 }}>
            {c.visible ? "◉" : "○"}
          </button>
          {/* Colour dot */}
          <div style={{ width: 8, height: 8, borderRadius: 2, background: c.color, flexShrink: 0 }} />
          {/* Label */}
          <span style={{ fontSize: 11, color: c.visible ? "var(--text-primary)" : "var(--text-subtle)", flex: 1 }}>
            Contour {c.id + 1}
          </span>
          <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>{c.points.length}pts</span>
        </div>
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function EditorPage() {
  const [contours, setContours] = useState<Contour[]>([]);
  const [view, setView] = useState<ViewState>({ x: 200, y: 300, scale: 1 });
  const [selected, setSelected] = useState<number | null>(null);
  const [draggingFile, setDraggingFile] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function loadFile(f: File) {
    const reader = new FileReader();
    reader.onload = e => {
      const text = e.target?.result as string;
      const parsed = parseDxf(text);
      setContours(parsed);
      setSelected(null);
    };
    reader.readAsText(f);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault(); setDraggingFile(false);
    const f = e.dataTransfer.files[0];
    if (f) loadFile(f);
  }

  function toggleVisible(id: number) {
    setContours(prev => prev.map(c => c.id === id ? { ...c, visible: !c.visible } : c));
  }

  function setColor(id: number, color: string) {
    setContours(prev => prev.map(c => c.id === id ? { ...c, color } : c));
  }

  const sel = selected !== null ? contours.find(c => c.id === selected) ?? null : null;

  // Compute bounding box for selected
  const selBounds = sel ? (() => {
    const xs = sel.points.map(p => p[0]), ys = sel.points.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    return { w: (maxX - minX).toFixed(2), h: (maxY - minY).toFixed(2), pts: sel.points.length };
  })() : null;

  const hasContours = contours.length > 0;

  return (
    <main style={{ padding: "40px 32px 0", maxWidth: "100%", height: "calc(100vh - 0px)", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{ marginBottom: 20, flexShrink: 0 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-subtle)" }}>
          DXF Editor
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 4 }}>
          <h1 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: "-0.02em" }}>
            Geometry{" "}
            <span style={{ background: "linear-gradient(135deg,#f59e0b,#ef4444)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
              inspector
            </span>
          </h1>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <input ref={fileRef} type="file" accept=".dxf" style={{ display: "none" }}
              onChange={e => { const f = e.target.files?.[0]; if (f) loadFile(f); }} />
            <button className="btn-ghost" onClick={() => fileRef.current?.click()}
              style={{ padding: "7px 14px", fontSize: 12 }}>
              ↑ Load DXF
            </button>
            {hasContours && (
              <button className="btn-ghost" onClick={() => { setContours([]); setSelected(null); }}
                style={{ padding: "7px 14px", fontSize: 12 }}>
                ✕ Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main area */}
      {!hasContours ? (
        /* Drop zone */
        <div
          className={`dropzone${draggingFile ? " over" : ""}`}
          style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, marginBottom: 32 }}
          onDragOver={e => { e.preventDefault(); setDraggingFile(true); }}
          onDragLeave={() => setDraggingFile(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
        >
          <span style={{ fontSize: 56, opacity: 0.12 }}>✎</span>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text-muted)", marginBottom: 6 }}>
              Drop a DXF file here
            </div>
            <div style={{ fontSize: 12, color: "var(--text-subtle)" }}>
              or click to browse — LINE and LWPOLYLINE entities will be loaded
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: "flex", gap: 16, minHeight: 0, marginBottom: 32 }}>

          {/* Layer sidebar */}
          <div className="glass" style={{ width: 220, flexShrink: 0, padding: 16, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 10 }}>
              Layers ({contours.length})
            </div>
            <LayerPanel contours={contours} onToggle={toggleVisible} onColor={setColor}
              selected={selected} onSelect={setSelected} />

            {/* Inspector */}
            {sel && selBounds && (
              <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--glass-border)" }}>
                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 10 }}>
                  Inspector
                </div>
                {[
                  { label: "Width",  val: `${selBounds.w} mm` },
                  { label: "Height", val: `${selBounds.h} mm` },
                  { label: "Points", val: selBounds.pts },
                ].map(row => (
                  <div key={row.label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>{row.label}</span>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-primary)" }}>{row.val}</span>
                  </div>
                ))}
                {/* Colour picker */}
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 10, color: "var(--text-subtle)", marginBottom: 6 }}>Colour</div>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                    {PALETTE.map(col => (
                      <div key={col} onClick={() => setColor(sel.id, col)}
                        style={{ width: 16, height: 16, borderRadius: 3, background: col, cursor: "pointer",
                          boxShadow: sel.color === col ? `0 0 0 2px #fff` : "none", transition: "box-shadow 0.1s" }} />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {!sel && (
              <div style={{ marginTop: "auto", paddingTop: 14, fontSize: 11, color: "var(--text-subtle)", lineHeight: 1.5 }}>
                Click a contour in the layer list or on canvas to inspect it.
              </div>
            )}
          </div>

          {/* Canvas */}
          <div className="glass" style={{ flex: 1, padding: 0, overflow: "hidden", display: "flex" }}>
            <EditorCanvas contours={contours} view={view} onView={setView} />
          </div>

        </div>
      )}
    </main>
  );
}
