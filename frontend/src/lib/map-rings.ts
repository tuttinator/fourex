/**
 * Map highlight ring palette.
 *
 * The Pixi renderer draws selection / valid-move / queued-order /
 * valid-attack rings using numeric colors. We expose them as CSS
 * variables so the brand theme owns the values; this resolver reads
 * the variable from the document root at render time and converts
 * the resulting hex string to the integer Pixi expects. The fallback
 * matches the light-mode default so SSR and the very first paint
 * still render with sensible colors before getComputedStyle resolves.
 */

export type RingKey =
  | "accent"
  | "success"
  | "warning"
  | "info"
  | "destructive";

const FALLBACK_HEX: Record<RingKey, string> = {
  accent: "#fbbf24",
  success: "#22c55e",
  warning: "#f59e0b",
  info: "#3b82f6",
  destructive: "#ef4444",
};

const CSS_VAR: Record<RingKey, string> = {
  accent: "--ring-accent",
  success: "--ring-success",
  warning: "--ring-warning",
  info: "--ring-info",
  destructive: "--ring-destructive",
};

function hexToNumber(hex: string): number {
  const cleaned = hex.replace("#", "").trim();
  if (cleaned.length === 3) {
    const r = cleaned[0];
    const g = cleaned[1];
    const b = cleaned[2];
    return parseInt(`${r}${r}${g}${g}${b}${b}`, 16);
  }
  return parseInt(cleaned.slice(0, 6), 16);
}

export interface RingPalette {
  accent: number;
  success: number;
  warning: number;
  info: number;
  destructive: number;
}

export function resolveRingPalette(): RingPalette {
  if (typeof window === "undefined") {
    return {
      accent: hexToNumber(FALLBACK_HEX.accent),
      success: hexToNumber(FALLBACK_HEX.success),
      warning: hexToNumber(FALLBACK_HEX.warning),
      info: hexToNumber(FALLBACK_HEX.info),
      destructive: hexToNumber(FALLBACK_HEX.destructive),
    };
  }

  const styles = window.getComputedStyle(document.documentElement);
  const read = (key: RingKey): number => {
    const raw = styles.getPropertyValue(CSS_VAR[key]).trim();
    if (raw.startsWith("#")) return hexToNumber(raw);
    return hexToNumber(FALLBACK_HEX[key]);
  };

  return {
    accent: read("accent"),
    success: read("success"),
    warning: read("warning"),
    info: read("info"),
    destructive: read("destructive"),
  };
}
