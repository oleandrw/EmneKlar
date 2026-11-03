import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  DataTable,
  Dialog,
  PageHeader,
  RadioGroup,
  SelectField,
  Switch,
  Tabs,
  TextField,
} from ".";

async function axeViolations(container: Element) {
  // jsdom has no layout engine, so colour contrast is checked in the Playwright/axe run instead.
  const result = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

describe("Tabs", () => {
  function Example() {
    const [tab, setTab] = useState<"a" | "b" | "c">("a");
    return (
      <Tabs label="Eksempel" selected={tab} onSelect={setTab}
        tabs={[{ id: "a", label: "Første" }, { id: "b", label: "Andre" }, { id: "c", label: "Tredje" }]}>
        <p>Innhold {tab}</p>
      </Tabs>
    );
  }

  it("follows the WAI-ARIA tabs pattern with arrow keys, Home and End", async () => {
    const user = userEvent.setup();
    render(<Example />);
    const tabs = screen.getAllByRole("tab");
    expect(screen.getByRole("tablist", { name: "Eksempel" })).toBeInTheDocument();
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs[1]).toHaveAttribute("tabindex", "-1");
    tabs[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Andre" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Andre" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Tredje" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Første" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Innhold a");
  });
});

describe("DataTable", () => {
  it("renders a captioned table with column headers and sort state", async () => {
    const onSort = vi.fn();
    render(
      <DataTable caption="Lenker" rows={[{ id: 1, url: "https://example.org" }]} rowKey={(r) => r.id}
        sort={{ key: "url", direction: "ascending" }} onSort={onSort}
        columns={[{ key: "url", header: "Adresse", sortable: true, rowHeader: true, cell: (r) => r.url }]} />,
    );
    const table = screen.getByRole("table", { name: "Lenker" });
    const header = within(table).getByRole("columnheader", { name: /Adresse/ });
    expect(header).toHaveAttribute("scope", "col");
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(within(table).getByRole("rowheader")).toHaveTextContent("https://example.org");
    await userEvent.click(within(header).getByRole("button"));
    expect(onSort).toHaveBeenCalledWith("url");
  });

  it("shows an empty message instead of an empty body", () => {
    render(<DataTable caption="Tom" rows={[]} rowKey={() => 1} empty="Ingen rader." columns={[{ key: "x", header: "X", cell: () => null }]} />);
    expect(screen.getByText("Ingen rader.")).toBeInTheDocument();
  });
});

describe("Dialog", () => {
  it("is labelled by its title and closes with the close button", async () => {
    const onClose = vi.fn();
    render(<Dialog open onClose={onClose} title="Bekreft" description="Les dette først.">Innhold</Dialog>);
    const dialog = screen.getByRole("dialog", { name: "Bekreft" });
    expect(dialog).toHaveAccessibleDescription("Les dette først.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Lukk" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("cannot be dismissed while a write is running", () => {
    render(<Dialog open onClose={() => {}} title="Lagrer" dismissible={false}>…</Dialog>);
    expect(screen.getByRole("button", { name: "Lukk" })).toBeDisabled();
  });
});

describe("Form fields", () => {
  it("associates labels, hints and errors with the control", () => {
    render(<TextField label="Canvas-adresse" hint="For eksempel https://hiof.instructure.com" error="Ugyldig adresse" />);
    const input = screen.getByLabelText("Canvas-adresse");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/Ugyldig adresse/);
    expect(input).toHaveAccessibleDescription(/hiof\.instructure\.com/);
  });

  it("exposes switches with their state", async () => {
    function Example() {
      const [on, setOn] = useState(false);
      return <Switch label="Dry run" checked={on} onChange={setOn} />;
    }
    render(<Example />);
    const toggle = screen.getByRole("switch", { name: /Dry run/ });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });
});

describe("Accessibility of composed components", () => {
  it("has no axe violations", async () => {
    const { container } = render(
      <MemoryRouter>
        <main>
          <PageHeader title="Innstillinger" description="Beskrivelse" actions={<Button variant="primary">Lagre</Button>} />
          <Alert tone="warning" title="Merk">Dette er viktig.</Alert>
          <Card title="Skjema">
            <form>
              <TextField label="Navn" />
              <SelectField label="Tema" options={[{ value: "light", label: "Lyst" }, { value: "dark", label: "Mørkt" }]} />
              <Checkbox label="Understrek lenker" hint="Gjør lenker lettere å se." />
              <RadioGroup legend="Strategi" name="s" value="auto" onChange={() => {}}
                options={[{ value: "auto", label: "Automatisk" }, { value: "manual", label: "Manuell" }]} />
              <Switch label="Bekreft før sending" checked onChange={() => {}} />
            </form>
            <Badge tone="success">Virker</Badge>
          </Card>
          <DataTable caption="Rapporter" rows={[{ id: 1 }]} rowKey={(r) => r.id} columns={[{ key: "a", header: "Rapport", cell: () => "Full" }]} />
        </main>
      </MemoryRouter>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
