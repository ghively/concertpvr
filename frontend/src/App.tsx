import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";

export default function App() {
  return (
    <div className="p-8 space-y-4">
      <h1 className="text-xl font-semibold text-terracotta">◉ concertpvr</h1>
      <p className="text-ink-dim">Phase 1 — foundation booting.</p>
      <div className="flex gap-2">
        <Button variant="primary">Primary</Button>
        <Button>Default</Button>
        <Button variant="ghost">Ghost</Button>
      </div>
      <Card>
        <CardLabel>Sample Card</CardLabel>
        <div className="text-sm mt-1">If this renders in editorial colors, shadcn setup works.</div>
      </Card>
    </div>
  );
}
