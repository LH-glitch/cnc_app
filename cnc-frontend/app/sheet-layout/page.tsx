"use client";

import { useState, useCallback } from "react";
import { FadeInGroup, FadeInItem } from "@/app/components/FadeIn";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Part {
  id: string;
  label: string;
  width: number;
  height: number;
  qty: number;
}

interface PlacedRect {
  label: string;
  x: number; y: number;
  width: number; height: number;
  sheet: number;
}

interface PackResult {
  placed: PlacedRect[];
  n_sheets: number;
  n_placed: number;
  n_failed: number;
  efficiency_pct: number;
  sheet_width: number;
  sheet_height: number;
}

// ── Palette for parts ─────────────────────────────────────────────────────────

const COLORS = [
  "rgba(124,58,237,0.55)", "rgba(14,165,233,0.55)", "rgba(236,72,153,0.55)",
  "rgba(16,185,129,0.55)", "rgba(245,158,11,0.55)", "rgba(239,68,68,0.55)",
  "rgba(99,102,241,0.55)", "rgba(6,182,212,0.55)",
];
const BORDER_COLORS = [
  "#7c3aed","#0ea5e9","#ec4899","#10b981","#f59e0b","#ef4444","#6366f1","#06b6d4",
];

// ── Sheet canvas preview ──────────────────────────────────────────────────────

function SheetCanvas({ result, sheetIdx }: { result: PackResult; sheetIdx: number }) {
  const VW = 480, VH = 360, PAD = 16;
  const sw = result.sheet_width, sh = result.sheet_height;
  const scale = Math.min((VW - PAD * 2) / sw, (VH - PAD * 2) / sh);
  const ox = (VW - sw * scale) / 2, oy = (VH - sh * scale) / 2;

  const placed = result.placed.filter(p => p.sheet === sheetIdx);
  const labelSet = Array.from(new Set(result.placed.map(p => p.label)));
  const colorMap = Object.fromEntries(labelSet.map((l, i) => [l, i % COLORS.length]));

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} style={{ width: "100%", height: "auto", display: "block" }}>
      <defs>
        <pattern id="sg" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="0.5"/>
        </pattern>
      </defs>
      <rect width={VW} height={VH} fill="url(#sg)" />

      {/* Sheet border */}
      <rect x={ox} y={oy} width={sw * scale} height={sh * scale}
        fill="rgba(255,255,255,0.02)" stroke="rgba(255,255,255,0.2)" strokeWidth={1.5} strokeDasharray="6 3" />

      {/* Placed parts */}
      {placed.map((p, i) => {
        const ci = colorMap[p.label] ?? 0;
        return (
          <g key={i}>
            <rect x={ox + p.x * scale} y={oy + p.y * scale}
              width={p.width * scale} height={p.height * scale}
              fill={COLORS[ci]} stroke={BORDER_COLORS[ci]} strokeWidth={1} rx={2} />
            {p.width * scale > 24 && p.height * scale > 14 && (
              <text
                x={ox + (p.x + p.width / 2) * scale}
                y={oy + (p.y + p.height / 2) * scale}
                textAnchor="middle" dominantBaseline="middle"
                fontSize={Math.min(11, p.height * scale * 0.35)}
                fill="rgba(255,255,255,0.85)" fontWeight="600">
                {p.label}
              </text>
            )}
          </g>
        );
      })}

      {/* Dimension labels */}
      <text x={ox + sw * scale / 2} y={oy - 6} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.3)">
        {sw} mm
      </text>
      <text x={ox - 6} y={oy + sh * scale / 2} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.3)"
        transform={`rotate(-90, ${ox - 6}, ${oy + sh * scale / 2})`}>
        {sh} mm
      </text>
    </svg>
  );
}

// ── Row/input helpers ─────────────────────────────────────────────────────────

function NumInput({ value, onChange, min = 0, max, step = 1, style }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; style?: React.CSSProperties;
}) {
  return (
    <input type="number" className="input-dark" value={value} min={min} max={max} step={step}
      onChange={e => onChange(parseFloat(e.target.value) || 0)}
      style={{ padding: "5px 8px", fontSize: 12, ...style }} />
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

let nextId = 1;
function makeId() { return String(nextId++); }

export default function SheetLayoutPage() {
  const [sheetW,   setSheetW]   = useState(1220);
  const [sheetH,   setSheetH]   = useState(2440);
  const [spacing,  setSpacing]  = useState(5);
  const [parts,    setParts]    = useState<Part[]>([
    { id: makeId(), label: "Side Panel", width: 300, height: 200, qty: 2 },
    { id: makeId(), label: "Top",        width: 400, height: 250, qty: 1 },
    { id: makeId(), label: "Shelf",      width: 360, height: 180, qty: 3 },
  ]);
  const [result,    setResult]   = useState<PackResult | null>(null);
  const [sheetIdx,  setSheetIdx] = useState(0);
  const [packing,   setPacking]  = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportOk,  setExportOk] = useState(false);
  const [err, setErr] = useState("");

  function addPart() {
    setParts(prev => [...prev, { id: makeId(), label: `Part ${prev.length + 1}`, width: 200, height: 150, qty: 1 }]);
  }
  function removePart(id: string) { setParts(prev => prev.filter(p => p.id !== id)); }
  function updatePart(id: string, field: keyof Part, value: string | number) {
    setParts(prev => prev.map(p => p.id === id ? { ...p, [field]: value } : p));
  }

  async function handlePack() {
    setPacking(true); setResult(null); setErr(""); setSheetIdx(0);
    try {
      const resp = await fetch(`${BASE}/sheet-layout/pack`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sheet_width: sheetW, sheet_height: sheetH, spacing, parts }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const data = await resp.json();
      setResult(data);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setPacking(false); }
  }

  async function handleExport() {
    setExporting(true); setExportOk(false);
    try {
      const resp = await fetch(`${BASE}/sheet-layout/export`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sheet_width: sheetW, sheet_height: sheetH, spacing, parts, filename: "layout.dxf" }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "layout.dxf"; a.click();
      URL.revokeObjectURL(url);
      setExportOk(true); setTimeout(() => setExportOk(false), 2500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setExporting(false); }
  }

  return (
    <main style={{ padding: "40px 32px 80px", maxWidth: 1080, margin: "0 auto" }}>
      <FadeInGroup>
      {/* Header */}
      <FadeInItem><div style={{ marginBottom: 32 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-subtle)" }}>
          Sheet Layout
        </span>
        <h1 style={{ fontSize: 28, fontWeight: 800, margin: "6px 0 8px", letterSpacing: "-0.02em" }}>
          Part{" "}
          <span style={{ background: "linear-gradient(135deg,#6366f1,#8b5cf6)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
            nesting & layout
          </span>
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>
          Pack cut parts onto sheets and export the layout as DXF.
        </p>
      </div></FadeInItem>

      <FadeInItem><div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>

        {/* Left column — controls */}
        <div style={{ flex: "0 0 300px", minWidth: 260, display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Sheet config */}
          <div className="glass" style={{ padding: 18 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 12 }}>
              Sheet
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
              <NumInput value={sheetW} min={100} onChange={setSheetW} style={{ flex: 1 }} />
              <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>×</span>
              <NumInput value={sheetH} min={100} onChange={setSheetH} style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: "var(--text-subtle)", whiteSpace: "nowrap" }}>mm</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, color: "var(--text-muted)", width: 70 }}>Spacing</span>
              <NumInput value={spacing} min={0} max={50} onChange={setSpacing} style={{ width: 70 }} />
              <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>mm</span>
            </div>
          </div>

          {/* Parts list */}
          <div className="glass" style={{ padding: 18 }}>
            <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)" }}>
                Parts
              </span>
              <button onClick={addPart} style={{
                marginLeft: "auto", fontSize: 11, padding: "3px 10px", borderRadius: 6, border: "none",
                background: "rgba(99,102,241,0.18)", color: "#a5b4fc", cursor: "pointer",
              }}>+ Add</button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {parts.map((part, pi) => (
                <div key={part.id} style={{
                  background: "rgba(0,0,0,0.25)", borderRadius: 8, padding: "10px 10px 8px",
                  border: `1px solid ${BORDER_COLORS[pi % BORDER_COLORS.length]}33`,
                }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                    <div style={{ width: 8, height: 8, borderRadius: 2, background: BORDER_COLORS[pi % BORDER_COLORS.length], flexShrink: 0 }} />
                    <input value={part.label} onChange={e => updatePart(part.id, "label", e.target.value)}
                      className="input-dark" style={{ flex: 1, padding: "3px 7px", fontSize: 11 }} />
                    <button onClick={() => removePart(part.id)} style={{
                      background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer", fontSize: 14, lineHeight: 1, padding: "0 2px",
                    }}>×</button>
                  </div>
                  <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                    <NumInput value={part.width}  min={1} onChange={v => updatePart(part.id, "width",  v)} style={{ width: 58 }} />
                    <span style={{ fontSize: 10, color: "var(--text-subtle)" }}>×</span>
                    <NumInput value={part.height} min={1} onChange={v => updatePart(part.id, "height", v)} style={{ width: 58 }} />
                    <span style={{ fontSize: 10, color: "var(--text-subtle)", flexShrink: 0 }}>mm qty</span>
                    <NumInput value={part.qty}    min={1} max={99} onChange={v => updatePart(part.id, "qty", Math.round(v))} style={{ width: 44 }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Actions */}
          <button className="btn-glow" onClick={handlePack} disabled={packing || parts.length === 0}
            style={{ padding: "11px 0", fontSize: 13 }}>
            {packing ? "Packing…" : "⊞ Pack Parts"}
          </button>
          {result && (
            <button className={exportOk ? "btn-success" : "btn-ghost"} onClick={handleExport} disabled={exporting}
              style={{ padding: "10px 0", fontSize: 13 }}>
              {exporting ? "Exporting…" : exportOk ? "✓ Downloaded" : "◇ Export DXF"}
            </button>
          )}
          {err && <div style={{ fontSize: 11, color: "#fca5a5" }}>{err}</div>}
        </div>

        {/* Right — preview */}
        <div style={{ flex: 1, minWidth: 300 }}>
          {result ? (
            <>
              {/* Stats */}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
                {[
                  { label: "Sheets",     val: result.n_sheets,        color: "var(--text-primary)" },
                  { label: "Placed",     val: result.n_placed,        color: "#86efac" },
                  { label: "Failed",     val: result.n_failed,        color: result.n_failed > 0 ? "#fca5a5" : "var(--text-subtle)" },
                  { label: "Efficiency", val: `${result.efficiency_pct}%`, color: result.efficiency_pct > 70 ? "#86efac" : "#fde68a" },
                ].map(s => (
                  <div key={s.label} className="glass-sm" style={{ padding: "8px 14px" }}>
                    <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{s.label}</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: s.color, marginTop: 2 }}>{s.val}</div>
                  </div>
                ))}
              </div>

              {/* Sheet tabs */}
              {result.n_sheets > 1 && (
                <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
                  {Array.from({ length: result.n_sheets }, (_, i) => (
                    <button key={i} onClick={() => setSheetIdx(i)}
                      style={{
                        padding: "5px 14px", borderRadius: 7, fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
                        background: sheetIdx === i ? "linear-gradient(135deg,#6366f1,#8b5cf6)" : "rgba(255,255,255,0.06)",
                        color: sheetIdx === i ? "#fff" : "var(--text-muted)",
                      }}>
                      Sheet {i + 1}
                    </button>
                  ))}
                </div>
              )}

              <div className="glass" style={{ padding: 0, overflow: "hidden" }}>
                <SheetCanvas result={result} sheetIdx={sheetIdx} />
              </div>
            </>
          ) : (
            <div className="glass" style={{ padding: 40, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 300, gap: 12 }}>
              <span style={{ fontSize: 48, opacity: 0.15 }}>⊞</span>
              <p style={{ fontSize: 13, color: "var(--text-subtle)", margin: 0, textAlign: "center" }}>
                Add parts and click <strong style={{ color: "var(--text-muted)" }}>Pack Parts</strong> to see the layout
              </p>
            </div>
          )}
        </div>

      </div></FadeInItem>
      </FadeInGroup>
    </main>
  );
}
