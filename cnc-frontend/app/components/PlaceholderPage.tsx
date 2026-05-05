import Link from "next/link";

// Server component — no hooks, pure display

type Status = "planned" | "in-dev" | "beta";

export interface PlaceholderProps {
  icon: string;
  name: string;
  tagline: string;
  description: string;
  features: { icon: string; label: string }[];
  status?: Status;
  eta?: string;
}

const STATUS_STYLES: Record<Status, { bg: string; color: string; label: string }> = {
  planned: { bg: "rgba(255,255,255,0.06)", color: "rgba(255,255,255,0.38)", label: "Planned"        },
  "in-dev": { bg: "rgba(251,191,36,0.12)", color: "#fde68a",               label: "In Development" },
  beta:     { bg: "rgba(34,197,94,0.12)",  color: "#86efac",               label: "Beta"           },
};

export default function PlaceholderPage({
  icon,
  name,
  tagline,
  description,
  features,
  status = "planned",
  eta,
}: PlaceholderProps) {
  const st = STATUS_STYLES[status];

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 32px",
        position: "relative",
      }}
    >
      {/* Ambient glow behind card */}
      <div style={{
        position: "absolute",
        width: 480, height: 480,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(124,58,237,0.12) 0%, transparent 70%)",
        pointerEvents: "none",
        zIndex: 0,
      }} />

      <div
        className="glass"
        style={{
          maxWidth: 540,
          width: "100%",
          padding: "48px 44px",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
          textAlign: "center",
          position: "relative",
          zIndex: 1,
        }}
      >
        {/* Tool icon */}
        <div
          style={{
            width: 76, height: 76, borderRadius: 20, flexShrink: 0,
            background: "rgba(124,58,237,0.10)",
            border: "1px solid rgba(124,58,237,0.22)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 36,
            boxShadow: "0 0 32px rgba(124,58,237,0.18)",
          }}
        >
          {icon}
        </div>

        {/* Status badge */}
        <div
          style={{
            fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
            textTransform: "uppercase", padding: "4px 14px", borderRadius: 9999,
            background: st.bg, color: st.color,
            border: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          {st.label}
        </div>

        {/* Name + tagline */}
        <div>
          <h1
            style={{
              fontSize: 26, fontWeight: 700, color: "var(--text-primary)",
              margin: "0 0 10px", letterSpacing: "-0.02em",
            }}
          >
            {name}
          </h1>
          <p style={{ fontSize: 15, color: "var(--text-muted)", margin: 0, lineHeight: 1.55 }}>
            {tagline}
          </p>
        </div>

        {/* Description */}
        <p
          style={{
            fontSize: 13, color: "var(--text-muted)", margin: 0,
            lineHeight: 1.75, maxWidth: 420,
          }}
        >
          {description}
        </p>

        {/* Feature rows */}
        <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 8 }}>
          {features.map((f, i) => (
            <div
              key={i}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 16px", textAlign: "left",
                background: "rgba(255,255,255,0.03)",
                borderRadius: 10, border: "1px solid var(--glass-border)",
              }}
            >
              <span style={{ fontSize: 16, flexShrink: 0 }}>{f.icon}</span>
              <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{f.label}</span>
            </div>
          ))}
        </div>

        {/* ETA */}
        {eta && (
          <p
            style={{
              fontSize: 12, color: "var(--text-subtle)", margin: 0,
              padding: "8px 18px", borderRadius: 8,
              background: "rgba(255,255,255,0.03)", border: "1px solid var(--glass-border)",
            }}
          >
            Estimated: <strong style={{ color: "var(--text-muted)" }}>{eta}</strong>
          </p>
        )}

        {/* Back link */}
        <Link
          href="/"
          style={{
            fontSize: 13, color: "var(--text-muted)", textDecoration: "none",
            padding: "8px 20px", borderRadius: 8,
            border: "1px solid var(--glass-border)",
            background: "rgba(255,255,255,0.03)",
            transition: "background 0.15s, border-color 0.15s",
          }}
        >
          ← Back to platform
        </Link>
      </div>
    </main>
  );
}
