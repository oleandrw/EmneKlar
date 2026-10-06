/*
 * Toast notifications rendered into a polite live region, so screen-reader
 * users hear them without losing their place. Toasts never contain the only
 * copy of important information (it is always also visible in the page).
 */
import { TriangleAlert, CircleCheck, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { IconButton } from "./primitives";

type ToastTone = "success" | "info" | "warning" | "danger";
interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
}

interface ToastApi {
  show: (toast: Omit<ToastItem, "id">) => void;
}

const ToastContext = createContext<ToastApi>({ show: () => {} });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const ICONS: Record<ToastTone, ReactNode> = {
  success: <CircleCheck aria-hidden="true" size={18} />,
  info: <Info aria-hidden="true" size={18} />,
  warning: <TriangleAlert aria-hidden="true" size={18} />,
  danger: <TriangleAlert aria-hidden="true" size={18} />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);
  const show = useCallback(
    (toast: Omit<ToastItem, "id">) => {
      const id = Date.now() + Math.random();
      setToasts((all) => [...all.slice(-3), { ...toast, id }]);
      // Long enough to be read (WCAG 2.2.1); dismissable at any time.
      window.setTimeout(() => dismiss(id), toast.tone === "danger" ? 20_000 : 9_000);
    },
    [dismiss],
  );
  const api = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="ek-toasts" role="status" aria-live="polite" aria-relevant="additions">
        {toasts.map((toast) => (
          <div key={toast.id} className="ek-toast" data-tone={toast.tone}>
            <span className="ek-toast__icon">{ICONS[toast.tone]}</span>
            <div className="ek-toast__body">
              <p className="ek-strong">{toast.title}</p>
              {toast.body ? <p className="ek-muted">{toast.body}</p> : null}
            </div>
            <IconButton label="Lukk melding" size="sm" onClick={() => dismiss(toast.id)}>
              <X aria-hidden="true" />
            </IconButton>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
