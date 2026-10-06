import { Menu, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router";

import { Alert, IconButton } from "../../design-system";
import { AnalysisDialog } from "../../features/analysis/AnalysisDialog";
import { ChangeSetDrawer } from "../../features/changes/ChangeSetDrawer";
import { useSession } from "../session";
import { useUi } from "../ui";
import { ChangeSetButton, CourseSelector, DryRunToggle, JobIndicator, RunAnalysisButton } from "./HeaderControls";
import { PRIMARY_NAV, SECONDARY_NAV, type NavItem } from "./nav";

function BrandMark() {
  return (
    <svg className="ek-brand__mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#1d3768" />
      <path d="M9 16.5l4.5 4.5L23 11.5" fill="none" stroke="#9ec1ff" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
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
        <div className="ek-cluster" data-justify="end" style={{ padding: "0.5rem" }}>
          <IconButton label="Lukk menyen" onClick={() => setMenuOpen(false)} style={{ color: "var(--nav-text)" }}>
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
        <span className="ek-header__spacer" />
        <div className="ek-header__group">
          <JobIndicator />
          {session.canvas.token_configured ? <RunAnalysisButton /> : null}
          <ChangeSetButton />
          <DryRunToggle />
        </div>
      </header>
      <main id="hovedinnhold" ref={mainRef} className="ek-shell__main" tabIndex={-1}>
        {session.dry_run ? (
          <div className="ek-shell__content" style={{ marginBottom: "1.5rem" }}>
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
