import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../design-system";
import { courseQuery, matchCourses } from "../course";
import type { Course } from "../api/types";
import { CourseSelector } from "./HeaderControls";

vi.mock("../session", () => ({
  useSession: () => ({ canvas: { token_configured: true }, current_course_id: "101" }),
}));

const course = (id: string, code: string, name: string, favorite = false): Course => ({
  id, name, course_code: code, term_name: "Høst 2026", workflow_state: "available", is_blueprint: false,
  default_view: null, roles: ["teacher"], favorite,
});
const COURSES = [
  course("101", "LA101", "Digital kompetanse"),
  course("547", "BP_LA102IKT", "Vurdering og digitale tester", true),
  course("1547", "MA1547", "Matematikk"),
];

afterEach(() => vi.unstubAllGlobals());

describe("course search", () => {
  it("finds a course by its id, also from a pasted Canvas address, exact id first", () => {
    expect(courseQuery("https://hiof.instructure.com/courses/547/pages/3-dot-5-2")).toBe("547");
    expect(matchCourses(COURSES, "547").map((c) => c.id)).toEqual(["547", "1547"]);
    expect(matchCourses(COURSES, "hiof.instructure.com/courses/547/pages/x").map((c) => c.id)[0]).toBe("547");
    expect(matchCourses(COURSES, "digital").map((c) => c.id)).toEqual(["101", "547"]);
  });
});

describe("CourseSelector", () => {
  it("shows favourites first, the course id in each row, and stars a course", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const data = url.includes("/favorite") ? { favorite_course_ids: ["547", "101"] } : { courses: COURSES, fetched_at: null, from_cache: true };
      return new Response(JSON.stringify(data), { status: 200 });
    }));
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><ToastProvider><CourseSelector /></ToastProvider></MemoryRouter>
      </QueryClientProvider>,
    );
    await user.click(await screen.findByRole("button", { name: /Valgt emne/ }));
    const favorites = await screen.findByRole("list", { name: "Favoritter" });
    expect(within(favorites).getByText("BP_LA102IKT")).toBeInTheDocument();
    expect(within(favorites).getByText(/ID 547/)).toBeInTheDocument();
    const others = screen.getByRole("list", { name: "Andre emner" });
    const star = within(others).getByRole("button", { name: "Favoritt: LA101" });
    expect(star).toHaveAttribute("aria-pressed", "false");

    await user.click(star);
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Favoritter" })).getByText("LA101")).toBeInTheDocument());
    expect(calls.find((c) => c.url.endsWith("/api/courses/101/favorite"))?.body).toEqual({ favorite: true });
    expect(screen.getByRole("button", { name: "Favoritt: LA101" })).toHaveAttribute("aria-pressed", "true");

    await user.type(screen.getByLabelText(/Søk etter emne/), "547");
    const shown = screen.getAllByRole("button", { name: /^(BP_LA102IKT|MA1547)/ }).map((b) => b.textContent);
    expect(shown[0]).toContain("BP_LA102IKT");
    expect(screen.getByText("2 av 3 emner")).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/Søk etter emne/));
    await user.type(screen.getByLabelText(/Søk etter emne/), "999");
    expect(screen.getByText(/Fant ikke emne-ID 999 blant emnene dine/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hent emnelisten på nytt fra Canvas" })).toBeInTheDocument();
  });

  it("opens by itself after the setup without a start course (…?velg-emne=1), once", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ courses: COURSES, fetched_at: null, from_cache: true }), { status: 200 })));
    function Where() {
      return <p data-testid="where">{useLocation().search}</p>;
    }
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/oversikt?velg-emne=1"]}>
          <ToastProvider><CourseSelector /><Where /></ToastProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("dialog", { name: "Velg emne" })).toBeInTheDocument();
    expect(screen.getByTestId("where"), "the parameter is removed, so a reload does not open it again").toHaveTextContent(/^$/);
  });
});
