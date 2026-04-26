import * as React from "react";
import { cn } from "@/lib/utils";

type BadgeColor = "neutral" | "live" | "buffering" | "scheduled" | "done" | "failed";

const palette: Record<BadgeColor, string> = {
  neutral: "bg-surface-3 text-ink-dim",
  live: "bg-red-500/15 text-red-400",
  buffering: "bg-sage/15 text-sage",
  scheduled: "bg-mauve/15 text-mauve",
  done: "bg-amber/15 text-amber",
  failed: "bg-red-500/15 text-red-400",
};

export function Badge({
  color = "neutral",
  className,
  children,
}: {
  color?: BadgeColor;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-block rounded px-2 py-0.5 text-[10px] uppercase tracking-wider",
        palette[color],
        className,
      )}
    >
      {children}
    </span>
  );
}
