import { useEffect, useRef, useState } from "react";

export function useWebSocket<T = unknown>(path: string, enabled: boolean = true) {
  const [last, setLast] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let retryDelay = 1000;
    let retryTimer: number | null = null;

    const connect = () => {
      if (cancelled) return;
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${location.host}${path}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        retryDelay = 1000;
      };
      ws.onmessage = (e) => {
        try {
          setLast(JSON.parse(e.data) as T);
        } catch {
          /* malformed payload — ignore */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (cancelled) return;
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
      ws.onerror = () => {
        ws.close();
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, [path, enabled]);

  return { last, connected };
}
