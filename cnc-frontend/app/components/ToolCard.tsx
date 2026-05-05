"use client";

import Link from "next/link";
import { motion } from "framer-motion";

// ── Shared types (re-exported so page.tsx can import them) ────────────────────

export type Status = "live" | "beta" | "soon";

export interface Tool {
  href: string;
  icon: string;
  name: string;
  tagline: string;
  description: string;
  capabilities: string[];
  status: Status;
  accentFrom: string;
  accentTo: string;
}

// ── Status badge styles ───────────────────────────────────────────────────────

const STATUS_BADGE: Record<Status, { bg: string; color: string; border: string; label: string }> = {
  live: { bg: "rgba(34,197,94,0.13)",   color: "#86efac",               border: "rgba(34,197,94,0.25)",   label: "Live"         },
  beta: { bg: "rgba(251,191,36,0.13)",  color: "#fde68a",               border: "rgba(251,191,36,0.25)",  label: "Beta"         },
  soon: { bg: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.35)", border: "rgba(255,255,255,0.10)", label: "Coming soon"  },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function ToolCard({ tool }: { tool: Tool }) {
  const st = STATUS_BADGE[tool.status];
  const isAvailable = tool.status === "live" || tool.status === "beta";

  const defaultBorder = isAvailable ? "rgba(255,255,255,0.09)" : "rgba(255,255,255,0.05)";

  return (
    <Link href={tool.href} style={{ textDecoration: "none", display: "block", height: "100%" }}>
      <motion.div
        className="glass"
        whileHover={isAvailable ? { y: -18, scale: 1.06 } : undefined}
        whileTap={isAvailable  ? { scale: 0.94 }          : undefined}
        transition={{ type: "spring", stiffness: 200, damping: 18 }}
        style={{
          height: "100%",
          padding: "28px 28px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          cursor: isAvailable ? "pointer" : "default",
          // Framer handles transforms; keep CSS transitions only for border/shadow.
          transition: "border-color 0.20s ease, box-shadow 0.20s ease",
          borderColor: defaultBorder,
        }}
        onMouseEnter={(e) => {
          if (!isAvailable) return;
          const el = e.currentTarget as HTMLDivElement;
          el.style.borderColor = `${tool.accentFrom}55`;
          el.style.boxShadow  = `0 12px 40px rgba(0,0,0,0.32), 0 0 0 1px ${tool.accentFrom}28`;
        }}
        onMouseLeave={(e) => {
          const el = e.currentTarget as HTMLDivElement;
          el.style.borderColor = defaultBorder;
          el.style.boxShadow  = "";
        }}
      >
        {/* Icon + status badge */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div
            style={{
              width: 48, height: 48, borderRadius: 13, flexShrink: 0,
              background: `linear-gradient(135deg, ${tool.accentFrom}22, ${tool.accentTo}18)`,
              border: `1px solid ${tool.accentFrom}33`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 22,
              boxShadow: `0 0 20px ${tool.accentFrom}28`,
            }}
          >
            {tool.icon}
          </div>
          <div
            style={{
              fontSize: 10, fontWeight: 700, padding: "3px 9px", borderRadius: 9999,
              background: st.bg, color: st.color, border: `1px solid ${st.border}`,
              letterSpacing: "0.05em", textTransform: "uppercase",
            }}
          >
            {st.label}
          </div>
        </div>

        {/* Name + tagline */}
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em", marginBottom: 5 }}>
            {tool.name}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {tool.tagline}
          </div>
        </div>

        {/* Description */}
        <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0, lineHeight: 1.65, flex: 1, opacity: isAvailable ? 1 : 0.65 }}>
          {tool.description}
        </p>

        {/* Capability bullets */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {tool.capabilities.map((cap, i) => (
            <div
              key={i}
              style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: isAvailable ? "var(--text-muted)" : "var(--text-subtle)" }}
            >
              <div
                style={{
                  width: 4, height: 4, borderRadius: "50%", flexShrink: 0,
                  background: isAvailable ? tool.accentFrom : "rgba(255,255,255,0.18)",
                }}
              />
              {cap}
            </div>
          ))}
        </div>

        {/* CTA */}
        <div
          style={{
            marginTop: 4,
            display: "inline-flex", alignItems: "center", gap: 6,
            fontSize: 13, fontWeight: 600,
            color: isAvailable ? tool.accentFrom : "var(--text-subtle)",
          }}
        >
          {isAvailable ? `Open ${tool.name} →` : "Notify me when available →"}
        </div>
      </motion.div>
    </Link>
  );
}
