"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

interface ThemeToggleProps {
  /** Compact icon-only toggle. Defaults to icon size. */
  size?: "sm" | "md";
}

export function ThemeToggle({ size = "sm" }: ThemeToggleProps) {
  // Avoid an SSR/CSR mismatch — `next-themes` reads localStorage on
  // mount, so the resolved theme isn't known until then. The
  // mount-via-effect dance is the documented next-themes pattern.
  const [mounted, setMounted] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- documented next-themes hydration guard
    setMounted(true);
  }, []);

  const isDark = mounted ? resolvedTheme === "dark" : true;
  const next = isDark ? "light" : "dark";
  const label = `Switch to ${next} mode`;

  return (
    <Button
      type="button"
      variant="ghost"
      size={size === "sm" ? "icon" : "default"}
      aria-label={label}
      title={label}
      onClick={() => setTheme(next)}
      className="text-ink-soft hover:text-ink"
      disabled={!mounted}
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
