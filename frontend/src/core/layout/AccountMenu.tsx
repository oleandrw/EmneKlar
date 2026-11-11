// The signed-in Canvas user, at the bottom of the side panel: the name and a small arrow; the account menu (Canvas
// address, the Canvas connection settings and «Avslutt EmneKlar») opens upwards. A disclosure button (aria-expanded/aria-controls): Enter
// or Space opens it, Tab moves through it, Escape closes it and returns focus to the button. When there is no room
// above (low window, enlarged text), the menu opens in the flow below the button, so the side panel can scroll to it.
import { ChevronUp } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { NavLink } from "react-router";

import { QuitDialog } from "../quit";
import { useSession } from "../session";

function canvasHost(baseUrl: string | null): string | null {
  if (!baseUrl) return null;
  try {
    return new URL(baseUrl).host;
  } catch {
    return null;
  }
}

export function AccountMenu({ onNavigate }: { onNavigate?: () => void }) {
  const session = useSession();
  const identity = session.canvas.identity;
  const [open, setOpen] = useState(false);
  const [quitting, setQuitting] = useState(false);
  const [placement, setPlacement] = useState<"up" | "inline">("up");
  const wrapperRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  // Open upwards when the panel fits above the button; otherwise in the flow (reachable by scrolling).
  useLayoutEffect(() => {
    if (!open || placement !== "up") return;
    const panel = panelRef.current;
    if (panel && panel.getBoundingClientRect().top < 0) setPlacement("inline");
  }, [open, placement]);

  // A click outside closes the menu (focus stays where the click put it).
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  if (!identity) return null;
  const host = canvasHost(session.canvas.base_url);

  const toggle = () => {
    setPlacement("up");
    setOpen((value) => !value);
  };
  const close = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && open) {
      // Only the menu closes – not the navigation drawer around it on small screens.
      event.preventDefault();
      event.stopPropagation();
      close(true);
    }
  };

  return (
    <div className="ek-account" ref={wrapperRef} onKeyDown={onKeyDown}
      onBlur={(event) => {
        if (open && !wrapperRef.current?.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}>
      {/* The accessible name starts with the visible name (WCAG 2.5.3) and says what the button is for. */}
      <button ref={buttonRef} type="button" className="ek-account__button" aria-expanded={open} aria-controls={panelId}
        aria-label={`${identity.name} – konto`} onClick={toggle}>
        <span className="ek-account__name">{identity.name}</span>
        <ChevronUp className="ek-account__chevron" aria-hidden="true" />
      </button>
      <div id={panelId} ref={panelRef} className="ek-account__panel" data-placement={placement} hidden={!open}>
        <p className="ek-account__who">
          <span className="ek-account__who-name">{identity.name}</span>
          <span className="ek-account__who-sub">Innlogget i Canvas{host ? ` på ${host}` : ""}</span>
        </p>
        <ul className="ek-account__actions">
          <li>
            <NavLink to="/innstillinger/canvas-tilkobling" className="ek-account__action"
              onClick={() => {
                setOpen(false);
                onNavigate?.();
              }}>
              Canvas-tilkobling
            </NavLink>
          </li>
          <li>
            {/* EmneKlar has no window of its own to close: this is where the program is stopped. */}
            <button type="button" className="ek-account__action"
              onClick={() => {
                setOpen(false);
                setQuitting(true);
              }}>
              Avslutt EmneKlar
            </button>
          </li>
        </ul>
      </div>
      <QuitDialog open={quitting} onClose={() => setQuitting(false)} />
    </div>
  );
}
