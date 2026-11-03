import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import {
  ActionList,
  ActionRow,
  ActivityList,
  BarChart,
  Button,
  FeatureCard,
  FilterChips,
  KeyFigure,
  KeyFigureList,
  MetricCard,
  niceTicks,
  PageHeader,
  StatList,
  StatTile,
  StatusCard,
  ToggleChips,
} from ".";

async function axeViolations(container: Element) {
  // jsdom has no layout engine, so colour contrast is checked in the Playwright/axe run instead.
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

const inRouter = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("StatusCard", () => {
  it("is one link with a heading and the key figures", async () => {
    const { container } = inRouter(
      <StatusCard title="Universell utforming" icon={<svg />} tone="violet" to="/universell-utforming"
        metrics={[{ value: 16, label: "avvik / sannsynlige avvik", tone: "critical" }, { value: 11, label: "bør vurderes" }]}
        footnote="7 krever manuell kontroll" />,
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/universell-utforming");
    expect(within(link).getByRole("heading", { level: 3, name: "Universell utforming" })).toBeInTheDocument();
    expect(link).toHaveTextContent("16 avvik / sannsynlige avvik");
    expect(link).toHaveTextContent("11 bør vurderes");
    expect(container.querySelector('[data-value-tone="critical"]')).toHaveTextContent("16");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when an area is not analysed instead of showing zeros", () => {
    inRouter(<StatusCard title="Quiz" icon={<svg />} tone="orange" to="/quizassistent" metrics={[{ value: 0, label: "x" }]}
      empty="Ikke analysert ennå" />);
    expect(screen.getByRole("link")).toHaveTextContent("Ikke analysert ennå");
    expect(screen.getByRole("link")).not.toHaveTextContent("0");
  });
});

describe("MetricCard", () => {
  it("is static by default and a toggle button when it filters", async () => {
    const onClick = vi.fn();
    const { rerender } = render(<MetricCard icon={<svg />} value={12} label="Bør vurderes" description="Kan være et problem." />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("12")).toBeInTheDocument();
    rerender(<MetricCard icon={<svg />} value={12} label="Bør vurderes" onClick={onClick} pressed />);
    const button = screen.getByRole("button", { name: /12 Bør vurderes/ });
    expect(button).toHaveAttribute("aria-pressed", "true");
    await userEvent.setup().click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("uses a smaller figure for text values such as dates", () => {
    const { container } = render(<MetricCard icon={<svg />} value="7. okt. 2026" label="Siste analyse" />);
    expect(container.querySelector(".ek-metric-card")).toHaveAttribute("data-value-kind", "text");
  });
});

describe("ActionRow", () => {
  it("describes its call to action with the row title", async () => {
    const onClick = vi.fn();
    const { container } = inRouter(
      <ActionList label="Anbefalte steg">
        <ActionRow icon={<svg />} tone="danger" title="4 kritiske UU-funn bør gjennomgås" description="Kan påvirke studenter."
          actionLabel="Gå til UU" to="/universell-utforming" />
        <ActionRow icon={<svg />} tone="success" title="2 endringer venter" actionLabel="Åpne endringskøen" onClick={onClick} />
      </ActionList>,
    );
    const link = screen.getByRole("link", { name: "Gå til UU" });
    expect(link).toHaveAccessibleDescription("4 kritiske UU-funn bør gjennomgås");
    expect(link).toHaveAttribute("data-tone", "danger");
    await userEvent.setup().click(screen.getByRole("button", { name: "Åpne endringskøen" }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.getByRole("list", { name: "Anbefalte steg" }).children).toHaveLength(2);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("FeatureCard", () => {
  it("is a labelled section with one clear action", async () => {
    const { container } = inRouter(
      <FeatureCard icon={<svg />} tone="info" title="Blueprint-låsing" description="Lås innhold." to="blueprint" actionLabel="Åpne" />,
    );
    expect(screen.getByRole("region", { name: "Blueprint-låsing" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Åpne" })).toHaveAccessibleDescription("Blueprint-låsing");
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Filter chips", () => {
  it("FilterChips keeps exactly one choice pressed; ToggleChips toggles each", async () => {
    const user = userEvent.setup();
    function Example() {
      const [one, setOne] = useState("alle");
      const [many, setMany] = useState<string[]>([]);
      return (
        <>
          <FilterChips label="Kategori" showLabel value={one} onChange={setOne}
            options={[{ value: "alle", label: "Alle", count: 5 }, { value: "bilder", label: "Bilder", count: 2 }]} />
          <ToggleChips label="Klassifisering" values={many}
            onToggle={(v) => setMany((list) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]))}
            options={[{ value: "avvik", label: "Avvik" }, { value: "forbedring", label: "Forbedringsforslag" }]} />
        </>
      );
    }
    const { container } = render(<Example />);
    expect(screen.getByRole("group", { name: "Kategori" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alle (5)" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Bilder (2)" }));
    expect(screen.getByRole("button", { name: "Bilder (2)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Alle (5)" })).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "Avvik" }));
    await user.click(screen.getByRole("button", { name: "Forbedringsforslag" }));
    expect(screen.getByRole("button", { name: "Avvik" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Forbedringsforslag" })).toHaveAttribute("aria-pressed", "true");
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Stats and activity", () => {
  it("lists counts and activity with readable text", async () => {
    const { container } = render(
      <>
        <StatList label="Innhold i emnet">
          <StatTile icon={<svg />} value={1284} label="Sider" />
        </StatList>
        <KeyFigureList label="Lenkestatus">
          <KeyFigure icon={<svg />} value={5} label="Død" description="Siden finnes ikke." />
        </KeyFigureList>
        <ActivityList label="Siste handlinger"
          items={[{ key: "1", icon: <svg />, tone: "success", title: "Velkommen", meta: "Gjennomført", date: "7. okt. 2026", time: "12:59" }]} />
      </>,
    );
    expect(within(screen.getByRole("list", { name: "Innhold i emnet" })).getByRole("listitem")).toHaveTextContent(/1\s284\s*Sider/);
    expect(screen.getByRole("list", { name: "Lenkestatus" })).toHaveTextContent("5 Død");
    expect(screen.getByRole("list", { name: "Siste handlinger" })).toHaveTextContent("Velkommen");
    expect(screen.getByRole("list", { name: "Siste handlinger" })).toHaveTextContent("12:59");
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("BarChart", () => {
  const categories = [
    { key: "uu", label: "Universell utforming", shortLabel: "UU" },
    { key: "quiz", label: "Quiz" },
  ];
  const series = [
    { key: "violation", label: "Avvik", color: "red", values: [16, 0] },
    { key: "review", label: "Bør vurderes", color: "orange", values: [11, 3] },
  ];

  it("has a legend, values per area for screen readers, and a table view", async () => {
    const user = userEvent.setup();
    const { container } = render(<BarChart label="Åpne funn per område" categoryHeader="Område" categories={categories} series={series} />);
    expect(within(screen.getByRole("list", { name: "Forklaring" })).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("img", { name: "Universell utforming: Avvik 16, Bør vurderes 11" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Quiz: Avvik 0, Bør vurderes 3" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vis som tabell" }));
    const table = screen.getByRole("table", { name: "Åpne funn per område" });
    expect(within(table).getByRole("columnheader", { name: "Område" })).toBeInTheDocument();
    expect(within(table).getByRole("rowheader", { name: "Quiz" })).toBeInTheDocument();
    expect(within(table).getAllByRole("cell").map((c) => c.textContent)).toEqual(["16", "11", "0", "3"]);
    expect(screen.getByRole("button", { name: "Vis diagram" })).toHaveAttribute("aria-pressed", "true");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows a message instead of an empty chart", () => {
    render(<BarChart label="x" categoryHeader="Område" categories={categories} emptyText="Ingen åpne funn."
      series={series.map((s) => ({ ...s, values: [0, 0] }))} />);
    expect(screen.getByText("Ingen åpne funn.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("uses clean whole-number ticks", () => {
    expect(niceTicks(16)).toEqual([0, 5, 10, 15, 20]);
    expect(niceTicks(3)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(0)).toEqual([0, 1]);
  });
});

describe("PageHeader and buttons", () => {
  it("shows quiet meta text and toned soft buttons", () => {
    render(
      <PageHeader title="Emneoversikt" description="Samlet status." meta="Sist analysert: 7. okt. 2026, 12:59"
        actions={<Button variant="soft" tone="success">Åpne</Button>} />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Emneoversikt" })).toBeInTheDocument();
    expect(screen.getByText("Sist analysert: 7. okt. 2026, 12:59")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Åpne" })).toHaveAttribute("data-tone", "success");
  });
});
