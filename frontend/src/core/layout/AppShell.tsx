import { Menu, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";

import { Alert, IconButton } from "../../design-system";
import { AnalysisDialog } from "../../features/analysis/AnalysisDialog";
import { ChangeSetDrawer } from "../../features/changes/ChangeSetDrawer";
import { useSession } from "../session";
import { useUi } from "../ui";
import {
  ChangeSetButton,
  CourseSelector,
  DryRunToggle,
  HelpButton,
  JobIndicator,
  RunAnalysisButton,
  UserChip,
} from "./HeaderControls";
import { PRIMARY_NAV, SECONDARY_NAV, type NavItem } from "./nav";

/** An open book with a check mark – the course, made clear. */
function BrandMark() {
  return (
    <svg className="ek-brand__mark" viewBox="0 0 36 36" aria-hidden="true">
      <path d="M3.5 10.2c4.9-2 9.8-1.7 14.5 1.1v18.4c-4.7-2.8-9.6-3.1-14.5-1.1z" fill="#34d399" />
      <path d="M32.5 10.2c-4.9-2-9.8-1.7-14.5 1.1v18.4c4.7-2.8 9.6-3.1 14.5-1.1z" fill="#60a5fa" />
      <path d="M6.5 7.6c3.9-1.3 7.8-1 11.5 1.3 3.7-2.3 7.6-2.6 11.5-1.3" fill="none" stroke="#fbbf24" strokeWidth="2.2"
        strokeLinecap="round" />
      <path d="M21.3 19.6l2.7 2.7 4.6-5.3" fill="none" stroke="#0f2342" strokeWidth="2.4" strokeLinecap="round"
        strokeLinejoin="round" />
    </svg>
  );
}

function NavList({ items, flags, onNavigate, bottom }: {
  items: NavItem[];
  flags: Record<string, boolean>;
  onNavigate?: () => void;
  bottom?: boolean;
}) {
  return (
    <ul className={bottom ? "ek-nav__list ek-nav__list--bottom" : "ek-nav__list"}>
      {items.map((item) => {
        const Icon = item.icon;
        const off = item.flag ? flags[item.flag] === false : false;
        return (
          <li key={item.to}>
            <NavLink to={item.to} className="ek-nav__link" onClick={onNavigate}>
              <Icon aria-hidden="true" />
              <span>{item.label}</span>
              {off ? <span className="ek-nav__badge">Av</span> : null}
            </NavLink>
          </li>
        );
      })}
    </ul>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const session = useSession();
  return (
    <>
      <NavLink to="/oversikt" className="ek-brand" onClick={onNavigate}>
        <BrandMark />
        <span>EmneKlar</span>
      </NavLink>
      <nav className="ek-nav" aria-label="Hovedmeny">
        <NavList items={PRIMARY_NAV} flags={session.flags} onNavigate={onNavigate} />
        <NavList items={SECONDARY_NAV} flags={session.flags} onNavigate={onNavigate} bottom />
      </nav>
    </>
  );
}

/** Moves focus to the page heading after client-side navigation (not on first load). */
function useRouteFocus(mainRef: React.RefObject<HTMLElement | null>) {
  const location = useLocation();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const handle = window.setTimeout(() => {
      const heading = mainRef.current?.querySelector<HTMLElement>("[data-page-heading]");
      (heading ?? mainRef.current)?.focus();
    }, 0);
    return () => window.clearTimeout(handle);
  }, [location.pathname, mainRef]);
}

export function AppShell({ children }: { children: ReactNode }) {
  const session = useSession();
  const ui = useUi();
  const mainRef = useRef<HTMLElement>(null);
  const drawerRef = useRef<HTMLDialogElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  useRouteFocus(mainRef);

  useEffect(() => {
    const drawer = drawerRef.current;
    if (!drawer) return;
    if (menuOpen && !drawer.open) drawer.showModal();
    if (!menuOpen && drawer.open) drawer.close();
  }, [menuOpen]);

  return (
    <div className="ek-shell">
      <a className="ek-skip-link" href="#hovedinnhold">
        Hopp til hovedinnhold
      </a>
      <aside className="ek-shell__nav">
        <Navigation />
      </aside>
      <dialog
        ref={drawerRef}
        className="ek-nav-drawer"
        aria-label="Hovedmeny"
        onClose={() => setMenuOpen(false)}
        onCancel={() => setMenuOpen(false)}
      >
        <div className="ek-cluster ek-nav-drawer__top" data-justify="end">
          <IconButton label="Lukk menyen" onClick={() => setMenuOpen(false)}>
            <X aria-hidden="true" />
          </IconButton>
        </div>
        {menuOpen ? <Navigation onNavigate={() => setMenuOpen(false)} /> : null}
      </dialog>
      <header className="ek-shell__header">
        <IconButton
          label="Åpne menyen"
          className="ek-shell__menu-button"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(true)}
        >
          <Menu aria-hidden="true" />
        </IconButton>
        <CourseSelector />
        <ChangeSetButton />
        <span className="ek-header__spacer" />
        <div className="ek-header__group">
          <JobIndicator />
          <DryRunToggle />
          <span className="ek-header__divider" aria-hidden="true" />
          <HelpButton />
          <UserChip />
          {session.canvas.token_configured ? <RunAnalysisButton /> : null}
        </div>
      </header>
      <main id="hovedinnhold" ref={mainRef} className="ek-shell__main" tabIndex={-1}>
        {session.dry_run ? (
          <div className="ek-shell__content ek-shell__notice">
            <Alert tone="warning" title="Dry run er slått på">
              EmneKlar analyserer, forhåndsviser og legger endringer i kø som vanlig, men sender ingen endringer til
              Canvas.
            </Alert>
          </div>
        ) : null}
        <div className="ek-shell__content">{children}</div>
      </main>
      <AnalysisDialog open={ui.analysisOpen} onClose={ui.closeAnalysis} />
      <ChangeSetDrawer open={ui.changesOpen} onClose={ui.closeChanges} />
    </div>
  );
}
