import { createContext, useCallback, useContext, useState } from "react";
import "./Toast.css";

type Tone = "ok" | "warn" | "info";
type Show = (message: string, tone?: Tone) => void;

const ToastContext = createContext<Show>(() => {});

/** Short confirmations after an action ("Basket ready", "Swapped in Brown Rice"). */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<{ id: number; message: string; tone: Tone }[]>([]);

  const show = useCallback<Show>((message, tone = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, message, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3800);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
            <span className="toast-mark" aria-hidden="true">
              {t.tone === "ok" ? "✓" : t.tone === "warn" ? "!" : "i"}
            </span>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
