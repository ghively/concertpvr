import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { authApi, type ApiError } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();
  const qc = useQueryClient();

  const submit = async () => {
    if (!password) return;
    setSubmitting(true);
    setError(null);
    try {
      await authApi.login(password);
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
      nav("/", { replace: true });
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 401 ? "Invalid password." : err.message);
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-0 p-4">
      <Card className="w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-xl font-semibold">
            <span className="text-terracotta">◉</span> concertpvr
          </h1>
          <CardLabel className="mt-2">Sign in</CardLabel>
        </div>
        <Input
          autoFocus
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
        {error && <p className="text-xs text-red-400">{error}</p>}
        <Button variant="primary" onClick={submit} disabled={submitting} className="w-full justify-center">
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </Card>
    </div>
  );
}
