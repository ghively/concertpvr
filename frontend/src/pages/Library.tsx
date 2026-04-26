import { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PosterCard } from "@/components/PosterCard";
import { api } from "@/lib/api";
import type { Segment } from "@/lib/api";

export default function LibraryPage() {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const recordings = await api.get<{ id: number }[]>("/api/recordings");
        const all: Segment[] = [];
        for (const rec of recordings) {
          const segs = await api.get<Segment[]>(`/api/segments?recording_id=${rec.id}`);
          all.push(...segs);
        }
        if (!cancelled) setSegments(all.filter((s) => s.status === "published"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const visible = segments.filter((s) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return (
      s.artist.toLowerCase().includes(q) || (s.title ?? "").toLowerCase().includes(q)
    );
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

      {loading && <p className="text-ink-dim text-xs">Loading…</p>}
      {!loading && visible.length === 0 && (
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
