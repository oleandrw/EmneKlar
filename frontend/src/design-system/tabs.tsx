/*
 * Tabs following the WAI-ARIA tabs pattern: roving tabindex, arrow keys,
 * Home/End, automatic activation. For route-based sections use <NavTabs>,
 * which renders ordinary links with aria-current (no tab roles).
 */
import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { Link, NavLink } from "react-router";

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  /** Decorative icon before the label (mark it aria-hidden). */
  icon?: ReactNode;
  badge?: ReactNode;
}

export function Tabs<T extends string>({
  tabs,
  selected,
  onSelect,
  label,
  children,
}: {
  tabs: TabItem<T>[];
  selected: T;
  onSelect: (id: T) => void;
  label: string;
  children: ReactNode;
}) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(0, tabs.findIndex((t) => t.id === selected));

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    onSelect(tabs[next].id);
    refs.current[next]?.focus();
  };

  return (
    <div>
      <div className="ek-tabs__list" role="tablist" aria-label={label}>
        {tabs.map((tab, i) => (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`${base}-tab-${tab.id}`}
            aria-selected={tab.id === selected}
            aria-controls={`${base}-panel`}
            tabIndex={tab.id === selected ? 0 : -1}
            className="ek-tabs__tab"
            onClick={() => onSelect(tab.id)}
            onKeyDown={onKeyDown}
          >
            {tab.icon}
            {tab.label}
            {tab.badge ? <> {tab.badge}</> : null}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-tab-${selected}`} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}

export function NavTabs({
  items,
  label,
}: {
  /** `current` overrides route matching, e.g. to keep a tab current on its sub-pages. */
  items: { to: string; label: ReactNode; icon?: ReactNode; end?: boolean; current?: boolean }[];
  label: string;
}) {
  return (
    <nav aria-label={label}>
      <div className="ek-tabs__list">
        {items.map((item) =>
          item.current === undefined ? (
            <NavLink key={item.to} to={item.to} end={item.end} className="ek-tabs__tab">
              {item.icon}
              {item.label}
            </NavLink>
          ) : (
            <Link key={item.to} to={item.to} className="ek-tabs__tab" aria-current={item.current ? "page" : undefined}>
              {item.icon}
              {item.label}
            </Link>
          ),
        )}
      </div>
    </nav>
  );
}
