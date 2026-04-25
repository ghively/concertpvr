import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "primary" | "ghost";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const base =
  "inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors " +
  "border disabled:opacity-50 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  default: "bg-surface-3 border-border-strong text-ink hover:border-ink-faint",
  primary: "bg-terracotta hover:bg-terracotta-dim border-terracotta-dim text-white",
  ghost: "bg-transparent border-transparent text-ink-dim hover:text-ink",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "default", className, ...rest }, ref) => (
    <button ref={ref} className={cn(base, variants[variant], className)} {...rest} />
  ),
);
Button.displayName = "Button";
