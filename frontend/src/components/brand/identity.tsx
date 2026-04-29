// Identity treatments for human players and AI agents. Same prominence,
// different visual language so a human seat doesn't outrank an agent one
// (or vice versa). HumanAvatar = initial on a tinted disc. AgentAvatar =
// deterministic 3x3 dot pattern keyed off the agent id.

import { type CSSProperties } from "react";

export type IdentityKind = "human" | "agent";

interface HumanAvatarProps {
  name?: string;
  color: string;
  size?: number;
}

export function HumanAvatar({ name, color, size = 28 }: HumanAvatarProps) {
  const initial = (name ?? "?").trim().slice(0, 1).toUpperCase();
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        color: "white",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "var(--font-ui)",
        fontWeight: 600,
        fontSize: size * 0.42,
        letterSpacing: "0.02em",
        boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,.15)",
        flexShrink: 0,
      }}
    >
      {initial}
    </span>
  );
}

function hashStr(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

interface AgentAvatarProps {
  id?: string;
  color: string;
  size?: number;
}

export function AgentAvatar({ id, color, size = 28 }: AgentAvatarProps) {
  const h = hashStr(id ?? "agent");
  const cells: boolean[] = [];
  for (let i = 0; i < 9; i++) {
    cells.push(((h >> i) & 1) === 1 || i === 4);
  }
  // Mirror left↔right for symmetry (heraldic feel)
  for (let r = 0; r < 3; r++) {
    cells[r * 3 + 2] = cells[r * 3 + 0];
    cells[r * 3 + 1] = cells[r * 3 + 1] || ((h >> (10 + r)) & 1) === 1;
  }
  const dot = size / 5.5;
  const gap = (size - dot * 3) / 4;
  return (
    <span
      style={{
        width: size,
        height: size,
        borderRadius: 5,
        background: color,
        display: "inline-grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gridTemplateRows: "repeat(3, 1fr)",
        gap,
        padding: gap,
        boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,.20)",
        flexShrink: 0,
      }}
    >
      {cells.map((on, i) => (
        <span
          key={i}
          style={{
            background: on ? "rgba(255,255,255,.95)" : "transparent",
            borderRadius: 1,
          }}
        />
      ))}
    </span>
  );
}

interface IdentityProps {
  kind: IdentityKind;
  name?: string;
  id?: string;
  color: string;
  size?: number;
  showLabel?: boolean;
  label?: string;
  style?: CSSProperties;
}

export function Identity({
  kind,
  name,
  id,
  color,
  size = 28,
  showLabel = false,
  label,
  style,
}: IdentityProps) {
  return (
    <span
      style={{ display: "inline-flex", alignItems: "center", gap: 8, ...style }}
    >
      {kind === "agent" ? (
        <AgentAvatar id={id ?? name} color={color} size={size} />
      ) : (
        <HumanAvatar name={name} color={color} size={size} />
      )}
      {showLabel && (
        <span
          style={{
            display: "inline-flex",
            flexDirection: "column",
            lineHeight: 1.15,
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-ui)",
              fontSize: 13,
              fontWeight: 600,
              color: "var(--ink)",
            }}
          >
            {name}
          </span>
          {label && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10.5,
                color: "var(--ink-muted)",
                letterSpacing: "0.02em",
                textTransform: "uppercase",
              }}
            >
              {label}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
