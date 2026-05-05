"use client";

import { useState, useCallback } from "react";
import { FadeInGroup, FadeInItem } from "@/app/components/FadeIn";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

type Shape = "rectangle" | "circle" | "rounded_rect" | "slot" | "l_bracket" | "t_bracket";

interface Params {
  shape: Shape;
  width: number; height: number; radius: number;
  slot_length: number; slot_width: number;
  flange_w: number; flange_h: number;
  thickness: number;
  hole: boolean; hole_radius: number; hole_x: number; hole_y: number;
  kerf: number;
}

const DEFAULTS: Params = {
  shape: "rectangle",
  width: 100, height: 80, radius: 10,
  slot_length: 60, slot_width: 15,
  flange_w: 40, flange_h: 20, thickness: 3,
  hole: false, hole_radius: 5, hole_x: 0, hole_y: 0,
  kerf: 0,
};

const SHAPES: { id: Shape; icon: string; label: string }[] = [
  { id: "rectangle",    icon: "▭", label: "Rectangle" },
  { id: "circle",       icon: "◯", label: "Circle" },
  { id: "rounded_rect", icon: "▢", label: "Rounded Rect" },
  { id: "slot",         icon: "⊏", label: "Slot" },
  { id: "l_bracket",    icon: "⌐", label: "L-Bracket" },
  { id: "t_bracket",    icon: "⊤", label: "T-Bracket" },
];

// ── Preview SVG ───────────────────────────────────────────────────────────────

function ShapePreview({ p }: { p: Params }) {
  const VW = 340, VH = 260, PAD = 30;

  function scaleToFit(natW: number, natH: number) {
    const s = Math.min((VW - PAD * 2) / natW, (VH - PAD * 2) / natH);
    const sw = natW * s, sh = natH * s;
    const ox = (VW - sw) / 2, oy = (VH - sh) / 2;
    return { s, sw, sh, ox, oy };
  }

  function renderShape() {
    const { shape, width, height, radius, slot_length, slot_width,
            flange_w, flange_h, hole, hole_radius, hole_x, hole_y } = p;
    const k = p.kerf / 2;

    if (shape === "circle") {
      const { s, ox, oy } = scaleToFit(radius * 2, radius * 2);
      const r = (radius - k) * s, cx = ox + r, cy = oy + r;
      return (
        <>
          <circle cx={cx} cy={cy} r={r} fill="rgba(124,58,237,0.12)" stroke="#7c3aed" strokeWidth={1.5} />
          {hole && <circle cx={cx + hole_x * s} cy={cy - hole_y * s} r={hole_radius * s} fill="rgba(0,0,0,0.4)" stroke="#0ea5e9" strokeWidth={1} />}
        </>
      );
    }

    if (shape === "slot") {
      const sl = slot_length - 2 * k, sw2 = slot_width - 2 * k;
      const { s, ox, oy } = scaleToFit(sl, sw2);
      const W = sl * s, H = sw2 * s, R = H / 2;
      const x0 = ox, y0 = oy;
      return <rect x={x0} y={y0} width={W} height={H} rx={R} fill="rgba(124,58,237,0.12)" stroke="#7c3aed" strokeWidth={1.5} />;
    }

    if (shape === "l_bracket") {
      const w = (width - 2 * k), h = (height - 2 * k), fw = flange_w, fh = flange_h;
      const { s, ox, oy } = scaleToFit(w, h);
      const pts = [[0,0],[w,0],[w,fh],[fw,fh],[fw,h],[0,h]].map(([x, y]) => `${ox + x*s},${oy + y*s}`).join(" ");
      return <polygon points={pts} fill="rgba(124,58,237,0.12)" stroke="#7c3aed" strokeWidth={1.5} />;
    }

    if (shape === "t_bracket") {
      const w = width - 2 * k, h = height - 2 * k, fw = flange_w, fh = flange_h, cx = w / 2;
      const { s, ox, oy } = scaleToFit(w, h);
      const pts = [[0,0],[w,0],[w,fh],[cx+fw/2,fh],[cx+fw/2,h],[cx-fw/2,h],[cx-fw/2,fh],[0,fh]]
        .map(([x, y]) => `${ox + x*s},${oy + y*s}`).join(" ");
      return <polygon points={pts} fill="rgba(124,58,237,0.12)" stroke="#7c3aed" strokeWidth={1.5} />;
    }

    // rectangle / rounded_rect
    const w = width - 2 * k, h = height - 2 * k;
    const { s, ox, oy } = scaleToFit(w, h);
    const W = w * s, H = h * s, R = shape === "rounded_rect" ? Math.min(radius, w/2, h/2) * s : 0;
    return (
      <>
        <rect x={ox} y={oy} width={W} height={H} rx={R} fill="rgba(124,58,237,0.12)" stroke="#7c3aed" strokeWidth={1.5} />
        {hole && (
          <circle cx={ox + W/2 + hole_x * s} cy={oy + H/2 - hole_y * s} r={hole_radius * s}
            fill="rgba(0,0,0,0.4)" stroke="#0ea5e9" strokeWidth={1} />
        )}
      </>
    );
  }

  // Dimension labels
  function dimW() {
    return p.shape === "slot" ? p.slot_length : p.shape === "circle" ? p.radius * 2 : p.width;
  }
  function dimH() {
    return p.shape === "slot" ? p.slot_width : p.shape === "circle" ? p.radius * 2 : p.height;
  }

  return (
    <svg viewBox={`0 0 ${VW} ${VH}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {/* Grid */}
      <defs>
        <pattern id="g" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width={VW} height={VH} fill="url(#g)" />
      {renderShape()}
      {/* Dimension text */}
      <text x={VW / 2} y={VH - 8} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.3)">
        {dimW().toFixed(1)} × {dimH().toFixed(1)} mm
      </text>
    </svg>
  );
}

// ── Shared primitives ─────────────────────────────────────────────────────────

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
      <div style={{ width: 90, flexShrink: 0, fontSize: 11, color: "var(--text-muted)" }}>{label}</div>
      {children}
    </div>
  );
}

function NumInput({ value, onChange, min, max, step = 1 }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number;
}) {
  return (
    <input type="number" className="input-dark" value={value} min={min} max={max} step={step}
      onChange={e => onChange(parseFloat(e.target.value) || 0)}
      style={{ width: 80, padding: "5px 8px", fontSize: 12 }} />
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DxfGeneratorPage() {
  const [p, setP] = useState<Params>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState(false);
  const [err, setErr] = useState("");

  const set = useCallback(<K extends keyof Params>(k: K, v: Params[K]) =>
    setP(prev => ({ ...prev, [k]: v })), []);

  async function handleExport() {
    setBusy(true); setOk(false); setErr("");
    try {
      const resp = await fetch(`${BASE}/dxf-generator/export`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...p, filename: `${p.shape}.dxf` }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${p.shape}.dxf`; a.click();
      URL.revokeObjectURL(url);
      setOk(true); setTimeout(() => setOk(false), 2500);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const showHW = p.shape !== "circle" && p.shape !== "slot";
  const showR  = p.shape === "circle" || p.shape === "rounded_rect";
  const showSlot = p.shape === "slot";
  const showFlange = p.shape === "l_bracket" || p.shape === "t_bracket";

  return (
    <main style={{ padding: "40px 32px 80px", maxWidth: 1000, margin: "0 auto" }}>
      <FadeInGroup>
      {/* Header */}
      <FadeInItem><div style={{ marginBottom: 32 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-subtle)" }}>
          DXF Generator
        </span>
        <h1 style={{ fontSize: 28, fontWeight: 800, margin: "6px 0 8px", letterSpacing: "-0.02em" }}>
          Parametric{" "}
          <span style={{ background: "linear-gradient(135deg,#10b981,#06b6d4)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
            shape generator
          </span>
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>
          Configure dimensions and export a cut-ready DXF instantly.
        </p>
      </div></FadeInItem>

      <FadeInItem><div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start" }}>

        {/* Left — controls */}
        <div className="glass" style={{ padding: 22, flex: "0 0 300px", minWidth: 260 }}>
          {/* Shape selector */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 10 }}>
              Shape
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6 }}>
              {SHAPES.map(s => (
                <button key={s.id} onClick={() => set("shape", s.id)}
                  style={{
                    padding: "8px 4px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 11,
                    fontWeight: 600, display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
                    background: p.shape === s.id ? "linear-gradient(135deg,#10b981,#06b6d4)" : "rgba(255,255,255,0.05)",
                    color: p.shape === s.id ? "#fff" : "var(--text-muted)",
                    transition: "all 0.15s",
                  }}>
                  <span style={{ fontSize: 16 }}>{s.icon}</span>
                  <span>{s.label}</span>
                </button>
              ))}
            </div>
          </div>

          <div style={{ height: 1, background: "var(--glass-border)", marginBottom: 16 }} />

          {/* Dimensions */}
          <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--text-subtle)", marginBottom: 12 }}>
            Dimensions (mm)
          </div>

          {showHW && <>
            <Row label="Width"><NumInput value={p.width} min={1} onChange={v => set("width", v)} /></Row>
            <Row label="Height"><NumInput value={p.height} min={1} onChange={v => set("height", v)} /></Row>
          </>}
          {showR && <Row label={p.shape === "circle" ? "Radius" : "Corner R"}><NumInput value={p.radius} min={0} onChange={v => set("radius", v)} /></Row>}
          {showSlot && <>
            <Row label="Length"><NumInput value={p.slot_length} min={1} onChange={v => set("slot_length", v)} /></Row>
            <Row label="Width"><NumInput value={p.slot_width} min={1} onChange={v => set("slot_width", v)} /></Row>
          </>}
          {showFlange && <>
            <Row label="Flange W"><NumInput value={p.flange_w} min={1} onChange={v => set("flange_w", v)} /></Row>
            <Row label="Flange H"><NumInput value={p.flange_h} min={1} onChange={v => set("flange_h", v)} /></Row>
          </>}

          <div style={{ height: 1, background: "var(--glass-border)", margin: "12px 0 14px" }} />

          {/* Hole */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <input type="checkbox" checked={p.hole} onChange={e => set("hole", e.target.checked)}
              style={{ width: 14, height: 14, cursor: "pointer" }} />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>Centre hole</span>
          </div>
          {p.hole && p.shape !== "slot" && p.shape !== "l_bracket" && p.shape !== "t_bracket" && (
            <Row label="Hole R"><NumInput value={p.hole_radius} min={0.5} step={0.5} onChange={v => set("hole_radius", v)} /></Row>
          )}

          <div style={{ height: 1, background: "var(--glass-border)", margin: "12px 0 14px" }} />

          <Row label="Kerf (mm)">
            <NumInput value={p.kerf} min={0} max={5} step={0.1} onChange={v => set("kerf", v)} />
          </Row>

          <button className={ok ? "btn-success" : "btn-glow"} onClick={handleExport} disabled={busy}
            style={{ width: "100%", padding: "11px 0", fontSize: 13, marginTop: 18 }}>
            {busy ? "Generating…" : ok ? "✓ Downloaded" : "◇ Export DXF"}
          </button>
          {err && <div style={{ marginTop: 8, fontSize: 11, color: "#fca5a5" }}>{err}</div>}
        </div>

        {/* Right — live preview */}
        <div style={{ flex: 1, minWidth: 280 }}>
          <div className="glass" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--glass-border)", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)" }}>Live Preview</span>
              <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text-subtle)" }}>
                {SHAPES.find(s => s.id === p.shape)?.label}
              </span>
            </div>
            <ShapePreview p={p} />
          </div>

          {/* Info chips */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
            {[
              { label: "Width", val: p.shape === "slot" ? `${p.slot_length} mm` : p.shape === "circle" ? `${p.radius*2} mm` : `${p.width} mm` },
              { label: "Height", val: p.shape === "slot" ? `${p.slot_width} mm` : p.shape === "circle" ? `${p.radius*2} mm` : `${p.height} mm` },
              { label: "Kerf", val: `${p.kerf} mm` },
            ].map(c => (
              <div key={c.label} className="glass-sm" style={{ padding: "6px 12px" }}>
                <div style={{ fontSize: 9, color: "var(--text-subtle)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{c.label}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", marginTop: 2 }}>{c.val}</div>
              </div>
            ))}
          </div>
        </div>

      </div></FadeInItem>
      </FadeInGroup>
    </main>
  );
}
