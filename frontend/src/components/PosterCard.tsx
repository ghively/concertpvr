import type { Segment } from "@/lib/api";
import { cn } from "@/lib/utils";

const GRADIENTS = [
  "from-purple-900 to-indigo-950",
  "from-emerald-900 to-teal-950",
  "from-amber-900 to-stone-950",
  "from-rose-900 to-fuchsia-950",
  "from-sky-900 to-slate-950",
];

function fmtDuration(s: number): string {
  const m = Math.round(s / 60);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}h ${m % 60}m` : `${m}m`;
}

export function PosterCard({ segment }: { segment: Segment }) {
  const colorClass = GRADIENTS[segment.id % GRADIENTS.length];
  const duration = segment.end_s - segment.start_s;
  return (
    <div className="cursor-pointer">
      <div
        className={cn(
          "aspect-[2/3] rounded relative overflow-hidden mb-2 bg-gradient-to-br",
          colorClass,
        )}
      >
        <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/85" />
        <span className="absolute top-1.5 right-1.5 px-1.5 py-0.5 text-[9px] font-mono bg-black/60 rounded">
          {fmtDuration(duration)}
        </span>
        <div className="absolute bottom-2 left-2 right-2">
          <div className="text-sm font-semibold text-white truncate">{segment.artist}</div>
          {segment.title && (
            <div className="text-[10px] text-white/70 truncate">{segment.title}</div>
          )}
        </div>
      </div>
    </div>
  );
}
