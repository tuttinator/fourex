import * as React from "react";

import { cn } from "@/lib/utils";

export type MapFrameVariant =
  | "inset"
  | "parchment"
  | "cartographic"
  | "floating";

interface MapFrameProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: MapFrameVariant;
  /** Optional aspect ratio (e.g. 16/10). When omitted the frame fills its parent. */
  aspectRatio?: number;
}

export function MapFrame({
  variant = "inset",
  aspectRatio,
  className,
  style,
  children,
  ...props
}: MapFrameProps) {
  const wrapperStyle: React.CSSProperties = {
    ...style,
    ...(aspectRatio ? { aspectRatio: String(aspectRatio) } : null),
  };

  if (variant === "parchment") {
    return (
      <div
        className={cn("relative", className)}
        style={wrapperStyle}
        {...props}
      >
        <div
          className="absolute inset-0 rounded-md"
          style={{
            background: "var(--parchment)",
            boxShadow:
              "inset 0 0 0 1px var(--parchment-edge), 0 1px 0 rgba(0,0,0,0.04)",
            backgroundImage:
              "repeating-linear-gradient(45deg, rgba(0,0,0,0.018) 0 2px, transparent 2px 6px)",
          }}
        />
        <CornerOrnament position="tl" />
        <CornerOrnament position="tr" />
        <CornerOrnament position="bl" />
        <CornerOrnament position="br" />
        <div
          className="relative h-full w-full overflow-hidden rounded-[3px]"
          style={{
            margin: 8,
            width: "calc(100% - 16px)",
            height: "calc(100% - 16px)",
            boxShadow: "inset 0 0 0 1px var(--border-strong)",
          }}
        >
          {children}
        </div>
      </div>
    );
  }

  if (variant === "cartographic") {
    return (
      <div
        className={cn("relative", className)}
        style={wrapperStyle}
        {...props}
      >
        <div
          className="absolute inset-0 rounded-sm"
          style={{
            boxShadow:
              "inset 0 0 0 1px var(--border-strong), inset 0 0 0 4px var(--bg-subtle), inset 0 0 0 5px var(--border-strong)",
          }}
        />
        <CartographicTicks />
        <div
          className="relative h-full w-full overflow-hidden"
          style={{
            margin: 6,
            width: "calc(100% - 12px)",
            height: "calc(100% - 12px)",
          }}
        >
          {children}
        </div>
      </div>
    );
  }

  if (variant === "floating") {
    return (
      <div
        className={cn("relative overflow-hidden rounded-md", className)}
        style={{
          ...wrapperStyle,
          boxShadow:
            "inset 0 0 0 1px var(--border-strong), 0 14px 28px -18px rgba(0,0,0,0.35)",
        }}
        {...props}
      >
        {children}
      </div>
    );
  }

  // 'inset' (default)
  return (
    <div
      className={cn("relative overflow-hidden rounded-md", className)}
      style={{
        ...wrapperStyle,
        boxShadow: "inset 0 0 0 1px var(--parchment-edge)",
      }}
      {...props}
    >
      {children}
    </div>
  );
}

function CornerOrnament({
  position,
}: {
  position: "tl" | "tr" | "bl" | "br";
}) {
  // Small heraldic L-shaped corner ornament.
  const positionStyle: React.CSSProperties = {
    position: "absolute",
    width: 14,
    height: 14,
    pointerEvents: "none",
  };
  if (position === "tl") {
    positionStyle.top = 2;
    positionStyle.left = 2;
  } else if (position === "tr") {
    positionStyle.top = 2;
    positionStyle.right = 2;
    positionStyle.transform = "scaleX(-1)";
  } else if (position === "bl") {
    positionStyle.bottom = 2;
    positionStyle.left = 2;
    positionStyle.transform = "scaleY(-1)";
  } else {
    positionStyle.bottom = 2;
    positionStyle.right = 2;
    positionStyle.transform = "scale(-1, -1)";
  }
  return (
    <svg
      viewBox="0 0 14 14"
      style={positionStyle}
      aria-hidden
    >
      <path
        d="M1 1 H8 V2 H2 V8 H1 Z"
        fill="var(--ink-muted)"
        fillOpacity="0.5"
      />
      <circle cx="2" cy="2" r="1" fill="var(--accent)" fillOpacity="0.7" />
    </svg>
  );
}

function CartographicTicks() {
  // Ruled tick marks along the inside of the frame, four sides.
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full"
      preserveAspectRatio="none"
      aria-hidden
    >
      <g stroke="var(--ink-muted)" strokeOpacity="0.35" strokeWidth="0.5">
        {Array.from({ length: 24 }).map((_, i) => {
          const t = (i + 1) / 25;
          return (
            <g key={i}>
              <line x1={`${t * 100}%`} y1="6" x2={`${t * 100}%`} y2="10" />
              <line
                x1={`${t * 100}%`}
                y1="calc(100% - 10px)"
                x2={`${t * 100}%`}
                y2="calc(100% - 6px)"
              />
              <line x1="6" y1={`${t * 100}%`} x2="10" y2={`${t * 100}%`} />
              <line
                x1="calc(100% - 10px)"
                y1={`${t * 100}%`}
                x2="calc(100% - 6px)"
                y2={`${t * 100}%`}
              />
            </g>
          );
        })}
      </g>
    </svg>
  );
}
