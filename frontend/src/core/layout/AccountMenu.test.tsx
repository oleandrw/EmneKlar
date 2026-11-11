import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { AccountMenu } from "./AccountMenu";

// «Avslutt EmneKlar» sends a request, so the menu lives inside the app's query client.
const wrap = (children: ReactNode) => (
  <QueryClientProvider client={new QueryClient()}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>
);

const NAME = "Kari Nordmann-Langnavnsen fra Institutt for svært lange avdelingsnavn";

vi.mock("../session", () => ({
  useSession: () => ({
    canvas: { token_configured: true, base_url: "https://hiof.instructure.com", identity: { id: "7", name: NAME } },
  }),
}));

describe("AccountMenu", () => {
  it("shows only the signed-in name and an arrow; the menu has the Canvas address and the connection settings", async () => {
    const user = userEvent.setup();
    const { container } = render(wrap(<AccountMenu />));
    const button = screen.getByRole("button", { name: `${NAME} – konto` });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button.textContent).toContain(NAME);
    expect(screen.getByText(/hiof.instructure.com/), "the address is only in the open menu").not.toBeVisible();
    expect(container.querySelector("img, .ek-user__avatar")).toBeNull();

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Innlogget i Canvas på hiof.instructure.com")).toBeVisible();
    const settings = screen.getByRole("link", { name: "Canvas-tilkobling" });
    expect(settings).toHaveAttribute("href", "/innstillinger/canvas-tilkobling");

    await user.tab();
    expect(settings).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    expect(screen.queryByRole("link", { name: "Canvas-tilkobling" })).toBeNull();

    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.click(document.body);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("is where EmneKlar is stopped: «Avslutt EmneKlar» asks before anything happens", async () => {
    const user = userEvent.setup();
    render(wrap(<AccountMenu />));
    await user.click(screen.getByRole("button", { name: `${NAME} – konto` }));
    const quit = screen.getByRole("button", { name: "Avslutt EmneKlar" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(quit);
    expect(screen.getByRole("button", { name: `${NAME} – konto` })).toHaveAttribute("aria-expanded", "false");
    const dialog = screen.getByRole("dialog", { name: "Avslutte EmneKlar?" });
    expect(dialog).toHaveTextContent("EmneKlar stopper på denne maskinen");
    await user.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
