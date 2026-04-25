import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...rest }, ref) => (
    <input
      ref={ref}
      className={cn(
        "w-full rounded border border-border-strong bg-surface-0 px-2.5 py-1.5",
        "text-xs text-ink placeholder:text-ink-faint",
        "focus:outline-none focus:border-terracotta",
        className,
      )}
      {...rest}
    />
  ),
);
Input.displayName = "Input";
