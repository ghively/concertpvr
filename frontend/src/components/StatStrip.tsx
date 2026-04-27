import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatStrip({
  items,
}: {
  items: { label: string; value: number | string; color?: "terra" | "sage" | "amber" | "mauve" }[];
}) {
  const colorMap = {
    terra: "text-terracotta",
    sage: "text-sage",
    amber: "text-amber",
    mauve: "text-mauve",
  } as const;

  return (
    <div className="grid gap-2 mb-4" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      {items.map((item) => (
        <Card key={item.label} className="p-3">
          <div
            className={cn(
              "font-mono text-xl font-semibold",
              item.color ? colorMap[item.color] : "text-ink",
            )}
          >
            {item.value}
          </div>
          <div className="text-[10px] uppercase tracking-wider text-ink-faint mt-0.5">
            {item.label}
          </div>
        </Card>
      ))}
    </div>
  );
}
