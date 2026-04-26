import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PosterCard } from "@/components/PosterCard";
import { usePublishedSegments } from "@/lib/query";

export default function LibraryPage() {
  const { data, isLoading } = usePublishedSegments();
  const [filter, setFilter] = useState("");

  const visible = (data ?? []).filter((s) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return s.artist.toLowerCase().includes(q) || (s.title ?? "").toLowerCase().includes(q);
  });

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-lg font-semibold">Library</h2>
        <span className="flex-1" />
        <Input
          className="max-w-sm"
          placeholder="Filter by artist or title…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {isLoading && <p className="text-ink-dim text-xs">Loading…</p>}
      {!isLoading && visible.length === 0 && (
        <Card className="text-center py-8 text-ink-dim text-xs">
          No published segments yet. Open a recording in the Timeline editor to publish one.
        </Card>
      )}
      <div className="grid grid-cols-5 gap-4">
        {visible.map((seg) => (
          <PosterCard key={seg.id} segment={seg} />
        ))}
      </div>
    </div>
  );
}
