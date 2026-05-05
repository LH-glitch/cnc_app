"use client";

import { useState, useEffect, useCallback } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

type Pattern = "diamond" | "hexagon" | "chevron" | "brick";

interface Params {
  pattern: Pattern;
  panel_w: number;
  panel_h: number;
  cols: number;
  rows: number;
  gap: number;
  bevel: number;
  tab_w: number;
  tab_h: number;
  add_tabs: boolean;
}

interface PanelData {
  id: number; row: number; col: number;
  ox: number; oy: number;
  vertices: [number, number][];
}

interface GenerateResult {
  panels: PanelData[];
  n_panels: number;
  pattern: string;
  panel_w: number; panel_h: number;
  total_w: number; total_h: number;
}

const DEFAULTS: Params = {
  pattern: "diamond", panel_w: 120, panel_h: 80,
  cols: 5, rows: 4, gap: 4, bevel: 10,
  tab_w: 8, tab_h: 5, add_tabs: false,
};

const PATTERNS: { id: Pattern; icon: string; label: string }[] = [
  { id: "diamond", icon: "◇", label: "Diamond" },
  { id: "hexagon", icon: "⬡", label: "Hexagon" },
  { id: "chevron", icon: "⌄", label: "Chevron" },
  { id: "brick",   icon: "⊞", label: "Brick" },
];

// ── SVG Preview ───────────────────────────────────────────────────────────────

function PanelPreview({ data, params }: { data: GenerateResult; params: Params }) {
  const VW = 500, VH = 380, PAD = 20;
  const scale = Math.min((VW - PAD * 2) / data.total_w, (VH - PAD * 2) / data.total_h);
  const ox = (VW - data.total_w * scale) / 2;
  const oy = (VH - data.total_h * scale) / 2;

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} style={{ width: "100%", height: "auto", display: "block" }}>
      <defs>
        <pattern id="pg" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="0.5"/>
        </pattern>
        <linearGradient id="pfill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="rgba(6,182,212,0.18)" />
          <stop offset="100%" stopColor="rgba(99,102,241,0.18)" />
        </linearGradient>
      </defs>
      <rect width={VW} height={VH} fill="url(#pg)" />

      {data.panels.map(panel => {
        const pts = panel.vertices.map(([x, y]) =>
          `${ox + (panel.ox + x) * scale},${oy + (panel.oy + y) * scale}`
        ).join(" ");

        // Bevel inset for diamond
        const bevelPts = params.pattern === "diamond" && params.bevel > 0 ? (() => {
          const b = params.bevel, pw = params.panel_w, ph = params.panel_h;
          return [
            [pw / 2, b], [pw - b, ph / 2], [pw / 2, ph - b], [b, ph / 2],
          ].map(([x, y]) => `${ox + (panel.ox + x) * scale},${oy + (panel.oy + y) * scale}`).join(" ");
        })() : null;

        const hue = (panel.row + panel.col) % 2 === 0 ? "rgba(6,182,212,0.18)" : "rgba(99,102,241,0.22)";

        return (
          <g key={panel.id}>
            <polygon points={pts} fill={hue} stroke="#06b6d4" strokeWidth={1} />
            {bevelPts && (
              <polygon points={bevelPts} fill="none" stroke="rgba(6,182,212,0.4)" strokeWidth={0.7} strokeDasharray="3 2" />
            )}
            {/* Panel number */}
            {params.panel_w * scale > 28 && params.panel_h * scale > 18 && (
              <text
                x={ox + (panel.ox + params.panel_w / 2) * scale}
                y={oy + (panel.oy + params.panel_h / 2) * scale}
                textAnchor="middle" dominantBaseline="middle"
                fontSize={Math.min(10, params.panel_w * scale * 0.16)}
                fill="rgba(255,255,255,0.4)" fontWeight="600">
                {panel.id + 1}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Controls ──────────────────────────────────────────────────────────────────

function SliderRow({ label, value, min, max, step = 1, onChange, unit = "" }: {
  label: string; value: number; min: number; max: number; step?: number;
  onChange: (v: number) => void; unit?: string;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{label}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-primary)" }}>{value}{unit}</span>
      </div>
      <input type="range" className="range-dark" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))} />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PanelsPage() {
  const [p, setP] = useState<Params>(DEFAULTS);
  const [data, setData] = useState<GenerateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportOk, setExportOk] = useState(false);
  const [err, setErr] = useState("");

  const set = useCallback(<K extends keyof Params>(k: K, v: Params[K]) =>
    setP(prev => ({ ...prev, [k]: v })), []);

  async function generate(params: Params) {
    setLoading(true); setErr("");
    try {
      const resp = await fetch(`${BASE}/panels/generate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setData(await resp.json());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setLoading(false); }
  }

  // Regenerate on param change (debounced via effect)
  useEffect(() => {
    const t = setTimeout(() => generate(p), 300);
    return () => clearTimeout(t);
  }, [p]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleExport() {
    setExporting(true); setExportOk(false);
    try {
      const resp = await fetch(`${BASE}/panels/export`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...p, filename: "panels.dxf" }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "panels.dxf"; a.click();
      URL.revokeObjectURL(url);
      setExportOk(true); setTimeout(() => setExportOk(false), 2500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setExporting(false); }
  }

  return (
    <main style={{ padding: "40px 32px 80px", maxWidth: 1060, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-subtle)" }}>
          3D Panels
        </span>
        <h1 style={{ fontSize: 28, fontWeight: 800, margin: "6px 0 8px", letterSpacing: "-0.02em" }}>
          Flat-cut{" "}
          <span style={{ background: "linear-gradient(135deg,#06b6d4,#6366f1)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
            panel systems
          </span>
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>
          Generate parametric panel grids for furniture, walls, and installations. Export as DXF.
        </p>
      </div>

      <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>

        {/* Controls */}
        <div className="glass" style={{ padding: 22, flex: "0 0 280px", minWidth: 240 }}>

          {/* Pattern */}
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 10 }}>
            Pattern
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 6, marginBottom: 18 }}>
            {PATTERNS.map(pat => (
              <button key={pat.id} onClick={() => set("pattern", pat.id)}
                style={{
                  padding: "8px 6px", borderRadius: 8, border: "none", cursor: "pointer",
                  display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
                  fontSize: 11, fontWeight: 600,
                  background: p.pattern === pat.id ? "linear-gradient(135deg,#06b6d4,#6366f1)" : "rgba(255,255,255,0.05)",
                  color: p.pattern === pat.id ? "#fff" : "var(--text-muted)",
                  transition: "all 0.15s",
                }}>
                <span style={{ fontSize: 18 }}>{pat.icon}</span>
                {pat.label}
              </button>
            ))}
          </div>

          <div style={{ height: 1, background: "var(--glass-border)", marginBottom: 16 }} />

          <SliderRow label="Panel Width"  value={p.panel_w} min={40}  max={300} step={5}  onChange={v => set("panel_w", v)} unit=" mm" />
          <SliderRow label="Panel Height" value={p.panel_h} min={30}  max={300} step={5}  onChange={v => set("panel_h", v)} unit=" mm" />
          <SliderRow label="Columns"      value={p.cols}    min={1}   max={12}  step={1}  onChange={v => set("cols", v)} />
          <SliderRow label="Rows"         value={p.rows}    min={1}   max={10}  step={1}  onChange={v => set("rows", v)} />
          <SliderRow label="Gap"          value={p.gap}     min={0}   max={30}  step={1}  onChange={v => set("gap", v)} unit=" mm" />
          <SliderRow label="Bevel"        value={p.bevel}   min={0}   max={30}  step={1}  onChange={v => set("bevel", v)} unit=" mm" />

          <div style={{ height: 1, background: "var(--glass-border)", margin: "10px 0 14px" }} />

          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: p.add_tabs ? 12 : 0 }}>
            <input type="checkbox" checked={p.add_tabs} onChange={e => set("add_tabs", e.target.checked)}
              style={{ width: 14, height: 14, cursor: "pointer" }} />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Assembly tabs</span>
          </div>
          {p.add_tabs && (
            <>
              <SliderRow label="Tab Width"  value={p.tab_w} min={3} max={30} step={1} onChange={v => set("tab_w", v)} unit=" mm" />
              <SliderRow label="Tab Height" value={p.tab_h} min={2} max={20} step={1} onChange={v => set("tab_h", v)} unit=" mm" />
            </>
          )}

          <button className={exportOk ? "btn-success" : "btn-glow"} onClick={handleExport} disabled={exporting || !data}
            style={{ width: "100%", padding: "11px 0", fontSize: 13, marginTop: 18,
              background: "linear-gradient(135deg,#06b6d4,#6366f1)" }}>
            {exporting ? "Exporting…" : exportOk ? "✓ Downloaded" : "◇ Export DXF"}
          </button>
          {err && <div style={{ marginTop: 8, fontSize: 11, color: "#fca5a5" }}>{err}</div>}
        </div>

        {/* Preview */}
        <div style={{ flex: 1, minWidth: 300 }}>
          {data && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
              {[
                { label: "Panels",   val: data.n_panels },
                { label: "Width",    val: `${data.total_w.toFixed(0)} mm` },
                { label: "Height",   val: `${data.total_h.toFixed(0)} mm` },
                { label: "Pattern",  val: data.pattern },
              ].map(s => (
                <div key={s.label} className="glass-sm" style={{ padding: "7px 12px" }}>
                  <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)", marginTop: 2 }}>{s.val}</div>
                </div>
              ))}
            </div>
          )}

          <div className="glass" style={{ padding: 0, overflow: "hidden", position: "relative" }}>
            {loading && (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(4,4,15,0.6)", zIndex: 2 }}>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Generating…</span>
              </div>
            )}
            {data
              ? <PanelPreview data={data} params={p} />
              : (
                <div style={{ height: 300, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <span style={{ fontSize: 48, opacity: 0.12 }}>⬡</span>
                </div>
              )}
          </div>
        </div>

      </div>
    </main>
  );
}
