import { useState, createContext, useContext, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";

type ConfirmFn = (opts: {
  title?: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
}) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<{
    open: boolean;
    title?: string;
    message: string;
    confirmLabel?: string;
    destructive?: boolean;
  } | null>(null);
  const resolverRef = useRef<((v: boolean) => void) | null>(null);

  const confirm: ConfirmFn = (opts) =>
    new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setState({ open: true, ...opts });
    });

  const close = (result: boolean) => {
    resolverRef.current?.(result);
    resolverRef.current = null;
    setState((s) => (s ? { ...s, open: false } : null));
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <Dialog open={state.open} onOpenChange={(o) => { if (!o) close(false); }}>
          {state.title && <DialogHeader>{state.title}</DialogHeader>}
          <DialogBody>
            <p className="text-sm text-ink">{state.message}</p>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => close(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => close(true)}>
              {state.confirmLabel ?? "Confirm"}
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const c = useContext(ConfirmContext);
  if (!c) throw new Error("useConfirm must be used inside ConfirmProvider");
  return c;
}
