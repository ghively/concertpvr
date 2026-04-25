import * as React from "react";
import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...rest }, ref) => (
    <div
      ref={ref}
      className={cn("rounded-md border border-border bg-surface-1 p-4", className)}
      {...rest}
    />
  ),
);
Card.displayName = "Card";

export const CardLabel = ({ children, className }: { children: React.ReactNode; className?: string }) => (
  <div className={cn("text-[10px] uppercase tracking-wider text-ink-faint", className)}>
    {children}
  </div>
);
