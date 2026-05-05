"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { checkHealth } from "@/lib/api";

// ── Tool registry ─────────────────────────────────────────────────────────────

type Status = "live" | "beta" | "soon";

const TOOLS: {
  href: string;
  label: string;
  icon: string;
  desc: string;
  status: Status;
}[] = [
  { href: "/slicer",        label: "Stacked Slicer",  icon: "≡", desc: "STL → board profiles",    status: "live" },
  { href: "/photo-to-dxf",  label: "Photo → DXF",     icon: "⊙", desc: "Vectorize images",        status: "live" },
  { href: "/dxf-generator", label: "DXF Generator",   icon: "◇", desc: "Parametric shapes",       status: "live" },
  { href: "/sheet-layout",  label: "Sheet Layout",     icon: "⊞", desc: "Nesting & optimization",  status: "live" },
  { href: "/panels",        label: "3D Panels",        icon: "⬡", desc: "Panel design & paths",    status: "beta" },
  { href: "/editor",        label: "DXF Editor",       icon: "✎", desc: "Inspect geometry",        status: "beta" },
  { href: "/alucobond",     label: "Alucobond Facade", icon: "⬡", desc: "Cladding skin + DXF",     status: "live" },
  { href: "/folded-board",  label: "Folded Board",     icon: "◈", desc: "Triangle fold test",       status: "beta" },
  { href: "/corner-test",    label: "Corner Test",      icon: "⌐", desc: "Two-wall corner cladding", status: "beta" },
];

const STATUS: Record<Status, { bg: string; color: string; border: string; label: string }> = {
  live: { bg: "rgba(34,197,94,0.12)",   color: "#86efac", border: "rgba(34,197,94,0.22)",  label: "Live"  },
  beta: { bg: "rgba(251,191,36,0.12)",  color: "#fde68a", border: "rgba(251,191,36,0.22)", label: "Beta"  },
  soon: { bg: "rgba(255,255,255,0.05)", color: "rgba(255,255,255,0.28)", border: "rgba(255,255,255,0.09)", label: "Soon" },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth().then(setHealth);
  }, []);

  // "/dashboard" is the home — no tool is active; individual hrefs activate their item
  const active = (href: string) => pathname === href;

  return (
    <nav
      style={{
        width: 220,
        flexShrink: 0,
        minHeight: "100vh",
        background: "rgba(3,3,12,0.96)",
        borderRight: "1px solid var(--glass-border)",
        display: "flex",
        flexDirection: "column",
        position: "sticky",
        top: 0,
        overflowY: "auto",
      }}
    >
      {/* Brand */}
      <Link
        href="/dashboard"
        style={{ textDecoration: "none", padding: "22px 18px 16px", display: "block" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 32, height: 32, borderRadius: 9, flexShrink: 0,
              background: "linear-gradient(135deg, #7c3aed, #0ea5e9)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 16, boxShadow: "0 0 14px rgba(124,58,237,0.5)",
            }}
          >
            ◈
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
              CNC Platform
            </div>
            <div style={{ fontSize: 10, color: "var(--text-subtle)", letterSpacing: "0.03em" }}>
              Fabrication Suite
            </div>
          </div>
        </div>
      </Link>

      <div style={{ height: 1, background: "var(--glass-border)", margin: "0 14px" }} />

      {/* Tool list */}
      <motion.div
        style={{ padding: "14px 10px", flex: 1 }}
        initial="hidden"
        animate="show"
        variants={{ hidden: {}, show: { transition: { staggerChildren: 0.12, delayChildren: 0.2 } } }}
      >
        <div
          style={{
            fontSize: 9, fontWeight: 700, color: "var(--text-subtle)",
            textTransform: "uppercase", letterSpacing: "0.1em",
            padding: "0 8px 10px",
          }}
        >
          Tools
        </div>

        {TOOLS.map((tool) => {
          const isActive = active(tool.href);
          const st = STATUS[tool.status];
          return (
            <motion.div
              key={tool.href}
              variants={{
                hidden: { opacity: 0, x: -40 },
                show:   { opacity: 1, x: 0, transition: { duration: 0.8, ease: [0.25, 0.46, 0.45, 0.94] } },
              }}
              whileHover={{ x: 3 }}
              transition={{ type: "spring", stiffness: 400, damping: 32 }}
              style={{ marginBottom: 2 }}
            >
              <Link
                href={tool.href}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 8px",
                  borderRadius: 8,
                  textDecoration: "none",
                  borderLeft: `2px solid ${isActive ? "#7c3aed" : "transparent"}`,
                  background: isActive ? "rgba(124,58,237,0.13)" : "transparent",
                  transition: "background 0.15s, border-color 0.15s",
                }}
              >
                {/* Icon box */}
                <div
                  style={{
                    width: 28, height: 28, borderRadius: 7, flexShrink: 0,
                    background: isActive ? "rgba(124,58,237,0.22)" : "rgba(255,255,255,0.05)",
                    border: `1px solid ${isActive ? "rgba(124,58,237,0.35)" : "rgba(255,255,255,0.08)"}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 13,
                    color: isActive ? "#c4b5fd" : "var(--text-muted)",
                    transition: "background 0.15s, border-color 0.15s",
                  }}
                >
                  {tool.icon}
                </div>

                {/* Label + description */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 12, fontWeight: isActive ? 600 : 500,
                      color: isActive ? "var(--text-primary)" : "var(--text-muted)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                    }}
                  >
                    {tool.label}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-subtle)", marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {tool.desc}
                  </div>
                </div>

                {/* Status chip — only for non-live */}
                {tool.status !== "live" && (
                  <div
                    style={{
                      fontSize: 9, fontWeight: 700, padding: "2px 5px", borderRadius: 4,
                      background: st.bg, color: st.color, border: `1px solid ${st.border}`,
                      flexShrink: 0, letterSpacing: "0.04em", textTransform: "uppercase",
                    }}
                  >
                    {st.label}
                  </div>
                )}
              </Link>
            </motion.div>
          );
        })}
      </motion.div>

      {/* Footer — health + version */}
      <div style={{ borderTop: "1px solid var(--glass-border)", padding: "14px 18px 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
          <span
            style={{
              width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
              background: health === null ? "#6b7280" : health ? "#22c55e" : "#ef4444",
              boxShadow: health === null ? "none" : health ? "0 0 6px rgba(34,197,94,0.8)" : "0 0 6px rgba(239,68,68,0.8)",
              animation: health === null ? "pulseDot 1.5s ease-in-out infinite" : "none",
            }}
          />
          <span style={{ fontSize: 11, color: "var(--text-subtle)" }}>
            {health === null ? "Connecting…" : health ? "API online" : "API offline"}
          </span>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-subtle)", opacity: 0.6 }}>
          CNC Platform · v1.0
        </div>
      </div>
    </nav>
  );
}
