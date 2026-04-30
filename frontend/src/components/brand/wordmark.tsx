import { type CSSProperties } from "react";

export type WordmarkVariant = "flag" | "monogram" | "stamp" | "plain";

interface WordmarkProps {
  variant?: WordmarkVariant;
  size?: number;
  mono?: boolean;
  color?: string;
  className?: string;
}

function WordmarkFlag({ size = 32, mono = false, color, className }: WordmarkProps) {
  const c = color ?? "var(--ink)";
  const accent = mono ? c : "var(--accent)";
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: size * 0.32,
        fontFamily: "var(--font-display)",
        fontWeight: 600,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.015em",
        color: c,
      }}
    >
      <svg
        width={size * 0.92}
        height={size * 1.05}
        viewBox="0 0 24 28"
        fill="none"
        aria-hidden
      >
        <rect x="3.4" y="1" width="1.2" height="26" rx="0.5" fill={c} />
        <path d="M 5 2 L 22 5.5 L 5 9 Z" fill={accent} />
        <rect x="2" y="25.5" width="4" height="1.5" rx="0.5" fill={c} />
      </svg>
      <span>Parley</span>
    </span>
  );
}

function WordmarkMonogram({ size = 32, mono = false, color, className }: WordmarkProps) {
  const c = color ?? "var(--ink)";
  const accent = mono ? c : "var(--accent)";
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: size * 0.36,
        fontFamily: "var(--font-display)",
        fontWeight: 600,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.015em",
        color: c,
      }}
    >
      <svg width={size * 1.05} height={size * 1.05} viewBox="0 0 32 32" aria-hidden>
        <rect x="0.5" y="0.5" width="31" height="31" rx="6" fill={accent} />
        <text
          x="16"
          y="23.5"
          textAnchor="middle"
          fontFamily="var(--font-display)"
          fontWeight={700}
          fontSize={22}
          fill="var(--accent-ink)"
        >
          P
        </text>
      </svg>
      <span>Parley</span>
    </span>
  );
}

function WordmarkStamp({ size = 32, color, className }: WordmarkProps) {
  const c = color ?? "var(--ink)";
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        fontFamily: "var(--font-display)",
        fontWeight: 600,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "0.01em",
        color: c,
        position: "relative",
        padding: `${size * 0.22}px ${size * 0.55}px`,
        border: `1px solid ${c}`,
        borderRadius: 2,
      }}
    >
      <span
        style={{
          position: "absolute",
          inset: `${size * 0.1}px`,
          border: `1px solid ${c}`,
          borderRadius: 1,
          opacity: 0.45,
          pointerEvents: "none",
        }}
      />
      <span style={{ fontVariant: "small-caps", letterSpacing: "0.06em" }}>
        Parley
      </span>
    </span>
  );
}

function WordmarkPlain({ size = 32, color, className }: WordmarkProps) {
  const c = color ?? "var(--ink)";
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        gap: 2,
        fontFamily: "var(--font-display)",
        fontWeight: 700,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.025em",
        color: c,
      }}
    >
      <span>Parley</span>
      <span
        style={{
          color: "var(--accent)",
          fontSize: size * 0.55,
          transform: `translateY(-${size * 0.3}px)`,
          marginLeft: 1,
        }}
      >
        ·
      </span>
    </span>
  );
}

export function Wordmark({ variant = "flag", ...rest }: WordmarkProps) {
  if (variant === "monogram") return <WordmarkMonogram {...rest} />;
  if (variant === "stamp") return <WordmarkStamp {...rest} />;
  if (variant === "plain") return <WordmarkPlain {...rest} />;
  return <WordmarkFlag {...rest} />;
}

interface SquareMarkProps {
  size?: number;
  color?: string;
  style?: CSSProperties;
}

export function SquareMark({ size = 32, color, style }: SquareMarkProps) {
  const c = color ?? "var(--accent)";
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden style={style}>
      <rect x="0" y="0" width="32" height="32" rx="6" fill={c} />
      <path
        d="M 11 7 L 11 25 M 11 8 L 21 11.5 L 11 15"
        stroke="var(--accent-ink)"
        strokeWidth="2.4"
        strokeLinecap="square"
        fill="none"
      />
    </svg>
  );
}
