import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Finding } from "../../core/api/types";
import { ToastProvider } from "../../design-system";
import { ChangeSetDrawer } from "../changes/ChangeSetDrawer";
import { resetAiConsentMemory } from "./AiSuggestion";
import { FindingDetail } from "./FindingDetail";

vi.mock("../../core/session", () => ({
  useSession: () => ({
    canvas: { token_configured: true, base_url: "https://canvas.test", identity: null },
    current_course_id: "101",
    ai: { providers_enabled: ["anthropic"], external_allowed: true, confirm_before_send: true },
    flags: {},
    general: { page_size: 25 },
  }),
}));
vi.mock("../../core/course", () => ({ useCurrentCourse: () => ({ courseId: "101", course: null, loading: false }) }));

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

type Handler = (url: string, init?: RequestInit) => unknown;

function stubFetch(handler: Handler) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const data = handler(url, init);
    return new Response(JSON.stringify(data ?? {}), { status: 200 });
  }));
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetAiConsentMemory();
});

const image: Finding = {
  id: 7, run_id: 1, course_id: "101", domain: "accessibility", rule_id: "UU-IMG-MISSING-ALT", ruleset_version: "1",
  category: "images", classification: "violation", test_method: "deterministic", severity: "serious", confidence: "high",
  title: "Bilde mangler alternativ tekst", message: "Bildet «diagram.png» har ikke alt-attributt.",
  object_type: "page", object_id: "bildeformater", object_title: "Bildeformater",
  object_url: "https://canvas.test/courses/101/pages/bildeformater",
  location: { module: "Modul 2", module_item_id: "1010", snippet: "<img src=\"/courses/101/files/9004/preview\">" },
  evidence: {
    src: "/courses/101/files/9004/preview", alt: null,
    image_context: { heading: "Raster og vektor", before: "Raster består av punkter.", after: "Vektor består av former." },
  },
  remediation: "Legg inn alt-tekst.", status: "open", created_at: "2026-11-06T10:00:00+00:00",
  fix: { type: "set_alt", label: "Legg inn alt-tekst eller merk som dekorativt", params: {} },
  canvas: {
    view: "https://canvas.test/courses/101/pages/bildeformater", edit: "https://canvas.test/courses/101/pages/bildeformater/edit",
    module_item: "https://canvas.test/courses/101/modules/items/1010", highlight: null,
  },
  image: true,
  alt_suggestion: { status: "ready", suggestion: "Raster- og vektorgrafikk side om side", decorative: false, model: "Test" },
  ready: "suggestion",
};

const preview = {
  kind: "page.update_body", before_display: "<p>før</p>", after_display: "<p>etter</p>", preview_html: "<p>etter</p>",
  risk: "low", existing_change_id: null, targeted: true, count: 1, occurrences: 0, related: [],
  changes: [{ before: "<img src=\"/courses/101/files/9004/preview\">", after: "<img src=\"/courses/101/files/9004/preview\" alt=\"x\">" }],
  where: { course_id: "101", course_name: "Emne", role: "course", locked: false, parent: null, associated_course_count: null,
    sync_needed: false, message: "Endringen gjøres bare i dette emnet." },
};

describe("alt text review", () => {
  it("shows the image beside its context, pre-fills the KI-forslag and approves with the teacher's text", async () => {
    const calls = stubFetch((url) => {
      if (url.includes("/alt-text/status")) return { items: { "7": image.alt_suggestion }, queue: { queued: 0, running: 0, job_id: null, consented: true } };
      if (url.includes("/alt-text/prioritize")) return { added: 0, allowed: true, queue: {} };
      if (url.includes("/fix/preview")) return preview;
      if (url.includes("/fix/approve")) return { id: 1, status: "approved", also_staged: [], errors: [] };
      return {};
    });
    const onNext = vi.fn();
    render(wrap(<FindingDetail finding={image} open onClose={() => {}} nav={{ index: 0, total: 3, onNext, upcoming: [8, 9] }} />));
    const dialog = screen.getByRole("dialog", { name: image.title });
    const img = within(dialog).getByRole("img", { name: /Bildet som vurderes/ });
    expect(img).toHaveAttribute("src", "/api/findings/7/image");
    expect(within(dialog).getByText(/Raster og vektor/)).toBeInTheDocument();
    expect(within(dialog).getByText("Raster består av punkter.")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Åpne i Canvas/ })).toHaveAttribute("href", image.canvas!.view);
    expect(within(dialog).getByRole("link", { name: /Rediger i Canvas/ })).toHaveAttribute("target", "_blank");

    const field = await within(dialog).findByLabelText("Alternativ tekst");
    await waitFor(() => expect(field).toHaveValue("Raster- og vektorgrafikk side om side"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("/alt-text/prioritize") &&
      JSON.stringify(c.body).includes("[7,8,9]"))).toBe(true));
    await userEvent.clear(field);
    await userEvent.type(field, "Min tekst");
    const approve = within(dialog).getByRole("button", { name: "Godkjenn og gå til neste" });
    await waitFor(() => expect(approve).toBeEnabled(), { timeout: 3000 });
    expect(within(dialog).getByText("Bare dette elementet endres")).toBeInTheDocument();
    await userEvent.click(approve);
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    const approved = calls.find((c) => c.url.includes("/fix/approve"));
    expect(approved?.body).toMatchObject({ text: "Min tekst", decorative: false });
  });

  it("steps to the next finding with Alt+N and back with Alt+P", async () => {
    stubFetch(() => ({}));
    const onNext = vi.fn();
    const onPrev = vi.fn();
    render(wrap(<FindingDetail finding={{ ...image, fix: null }} open onClose={() => {}} nav={{ index: 1, total: 3, onNext, onPrev }} />));
    expect(screen.getByText("Funn 2 av 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Forrige" }));
    expect(onPrev).toHaveBeenCalledTimes(1);
    screen.getByRole("button", { name: "Neste" }).focus();
    await userEvent.keyboard("{Alt>}n{/Alt}");
    expect(onNext).toHaveBeenCalledTimes(1);
  });
});

const iframe: Finding = {
  ...image, id: 21, rule_id: "UU-IFRAME-NO-TITLE", category: "iframes", title: "Innebygd innhold (iframe) mangler tittel",
  message: "Iframe som viser www.youtube.com mangler tittel.", object_id: "greenscreen", object_title: "8.5.2 Greenscreen-programvare",
  location: { module: "Modul 9", snippet: "<iframe src=\"https://www.youtube.com/embed/E6X4JAzvq80\">" },
  evidence: { src: "https://www.youtube.com/embed/E6X4JAzvq80" }, image: false, alt_suggestion: undefined, ready: undefined,
  fix: { type: "set_iframe_title", label: "Legg til en beskrivende tittel", params: { path: "iframe:nth-of-type(1)", suggestion: "Video: " } },
};
const REF = { object_type: "page", object_id: "greenscreen", object_title: "8.5.2 Greenscreen-programvare", video_id: "E6X4JAzvq80", occurrence: 0 };

describe("title for a YouTube iframe", () => {
  it("fills in the video's title from YouTube and says where it came from", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/findings/21/video-title")) {
        return { available: true, title: "Video: Greenscreen i OBS", source: "youtube_metadata", source_label: "YouTube-metadata",
          hint: "Videoens egen tittel hos YouTube. Kontroller at den sier hva videoen handler om.", metadata_message: null,
          ai_possible: false, ref: REF };
      }
      if (url.includes("/fix/preview")) return preview;
      if (url.includes("/fix/approve")) return { id: 1, status: "approved", also_staged: [], errors: [] };
      return {};
    });
    const onNext = vi.fn();
    render(wrap(<FindingDetail finding={iframe} open onClose={() => {}} nav={{ index: 0, total: 24, onNext, upcoming: [] }} />));
    const dialog = screen.getByRole("dialog", { name: iframe.title });
    const field = within(dialog).getByLabelText("Tittel på innebygd innhold");
    await waitFor(() => expect(field).toHaveValue("Video: Greenscreen i OBS"));
    expect(within(dialog).getByText("Kilde: YouTube-metadata.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Foreslå tittel med KI" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Se hva KI foreslår" }), "KI is an optional comparison").toBeInTheDocument();
    const approve = within(dialog).getByRole("button", { name: "Godkjenn og gå til neste" });
    await waitFor(() => expect(approve).toBeEnabled(), { timeout: 3000 });
    await userEvent.click(approve);
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(calls.find((c) => c.url.includes("/fix/approve"))?.body).toMatchObject({ text: "Video: Greenscreen i OBS" });
    expect(calls.some((c) => c.url.includes("title-suggestion")), "no KI unless the teacher asks").toBe(false);
  });

  it("can compare the YouTube title with a KI-forslag and go back to it", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/findings/21/video-title")) {
        return { available: true, title: "Video: Greenscreen i iMovie", source: "youtube_metadata", source_label: "YouTube-metadata",
          hint: "Videoens egen tittel hos YouTube.", metadata_message: null, ai_possible: false, ref: REF };
      }
      if (url.endsWith("/videos/title-suggestion/prepare")) {
        return { available: true, reason: null, payload_summary: "YouTube-tittelen og teksten rundt videoen sendes.",
          needs_confirmation: true, external: true, route: { provider: "openai", model: "test", reason: "billigst" } };
      }
      if (url.endsWith("/videos/title-suggestion")) return { title: "Video: Greenscreen-effekt i iMovie, steg for steg", source_label: "KI-forslag" };
      if (url.includes("/fix/preview")) return preview;
      return {};
    });
    render(wrap(<FindingDetail finding={iframe} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: iframe.title });
    const field = within(dialog).getByLabelText("Tittel på innebygd innhold");
    await waitFor(() => expect(field).toHaveValue("Video: Greenscreen i iMovie"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Se hva KI foreslår" }));
    expect(await within(dialog).findByText("YouTube-tittelen og teksten rundt videoen sendes.")).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/title-suggestion/prepare"))?.body).toEqual({ ...REF, even_with_title: true });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send og lag forslag" }));
    await waitFor(() => expect(field).toHaveValue("Video: Greenscreen-effekt i iMovie, steg for steg"));
    expect(within(dialog).getByText("KI-forslag – må vurderes")).toBeInTheDocument();
    expect(within(dialog).getByText(/Forslaget var «Video: Greenscreen i iMovie» \(YouTube-metadata\)/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Bruk forslaget" }));
    expect(field).toHaveValue("Video: Greenscreen i iMovie");
  });

  it("asks KI only on request, after showing what is sent, and marks the suggestion", async () => {
    const calls = stubFetch((url) => {
      if (url.endsWith("/api/findings/21/video-title")) {
        return { available: true, title: "Video: 8.5.2 Greenscreen-programvare", source: "page_context", source_label: "Canvas-kontekst",
          hint: "Laget ut fra sidetittelen og overskriften rundt videoen – må vurderes.",
          metadata_message: "Videoen er privat eller kan ikke bygges inn. Title må vurderes manuelt.", ai_possible: true, ref: REF };
      }
      if (url.endsWith("/videos/title-suggestion/prepare")) {
        return { available: true, reason: null, payload_summary: "Sidetittelen og teksten rundt videoen sendes.", needs_confirmation: true,
          external: true, route: { provider: "anthropic", model: "test", reason: "billigst" } };
      }
      if (url.endsWith("/videos/title-suggestion")) return { title: "Video: Slik bruker du greenscreen", source_label: "KI-forslag" };
      if (url.includes("/fix/preview")) return preview;
      return {};
    });
    render(wrap(<FindingDetail finding={iframe} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: iframe.title });
    const field = within(dialog).getByLabelText("Tittel på innebygd innhold");
    await waitFor(() => expect(field).toHaveValue("Video: 8.5.2 Greenscreen-programvare"));
    expect(within(dialog).getByText(/Videoen er privat/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Foreslå tittel med KI" }));
    expect(await within(dialog).findByText("Sidetittelen og teksten rundt videoen sendes.")).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/videos/title-suggestion")), "nothing is sent before consent").toBe(false);
    expect(calls.find((c) => c.url.endsWith("/title-suggestion/prepare"))?.body).toEqual({ ...REF, even_with_title: true });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send og lag forslag" }));
    await waitFor(() => expect(field).toHaveValue("Video: Slik bruker du greenscreen"));
    expect(within(dialog).getByText("KI-forslag – må vurderes")).toBeInTheDocument();
    expect(calls.find((c) => c.url.endsWith("/videos/title-suggestion"))?.body).toEqual({ ...REF, even_with_title: true, confirmed: true });
  });

  it("never replaces what the teacher has written", async () => {
    let answer: (value: unknown) => void = () => {};
    const pending = new Promise((resolve) => { answer = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/api/findings/21/video-title")) {
        await pending;
        return new Response(JSON.stringify({ available: true, title: "Video: Greenscreen i OBS", source: "youtube_metadata",
          source_label: "YouTube-metadata", hint: "", metadata_message: null, ai_possible: false, ref: REF }), { status: 200 });
      }
      return new Response(JSON.stringify(url.includes("/fix/preview") ? preview : {}), { status: 200 });
    }));
    render(wrap(<FindingDetail finding={iframe} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: iframe.title });
    const field = within(dialog).getByLabelText("Tittel på innebygd innhold");
    await userEvent.type(field, "Min egen tittel");
    answer(null);
    expect(await within(dialog).findByRole("button", { name: "Bruk forslaget" })).toBeInTheDocument();
    expect(field).toHaveValue("Video: Min egen tittel");
  });
});

describe("dead link editor", () => {
  it("offers replace / unlink / remove and one occurrence, the page or the whole course", async () => {
    const link: Finding = {
      ...image, id: 9, domain: "content_quality", rule_id: "CQ-LINK-DEAD", title: "Død lenke", image: false,
      alt_suggestion: null, ready: null, message: "«artikkel»: Siden finnes ikke (404).",
      evidence: { href: "https://www.example.org/missing", link_text: "artikkel", occurrences: 2, http_status: 404 },
      fix: { type: "replace_link_href", label: "Rett lenken", params: { suggestion: "", allow_unlink: true, text: "artikkel" } },
    };
    const calls = stubFetch((url) => (url.includes("/fix/preview") ? {
      ...preview, occurrences: 2,
      related: [{ finding_id: 10, object_type: "page", object_id: "andre", object_title: "Andre side" }],
    } : {}));
    render(wrap(<FindingDetail finding={link} open onClose={() => {}} />));
    expect(screen.getByText("https://www.example.org/missing")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Fjern lenken, behold teksten/ }));
    const coursewide = await screen.findByRole("radio", { name: /Alle steder i emnet \(2 her \+ 1 annet innhold\)/ });
    expect(screen.getByRole("radio", { name: /Alle forekomster i «Bildeformater» \(2\)/ })).toBeEnabled();
    await waitFor(() => expect(coursewide).toBeEnabled());
    await userEvent.click(coursewide);
    await waitFor(() => expect(calls.some((c) => c.url.includes("/fix/preview") &&
      (c.body as Record<string, unknown>).scope === "course" && (c.body as Record<string, unknown>).link_action === "unlink")).toBe(true));
    expect(screen.getByText(/sletter aldri lenker automatisk/)).toBeInTheDocument();
  });
});

describe("empty link with a broken address", () => {
  it("explains the address, pre-selects removal and needs text to keep the link", async () => {
    const empty: Finding = {
      ...image, id: 11, rule_id: "UU-LINK-EMPTY", title: "Lenke uten tekst", image: false, alt_suggestion: null, ready: null,
      message: "Lenken til http://PDF-versjon%20https har ikke noe tilgjengelig navn. Adressen er heller ikke gyldig.",
      evidence: { href: "http://PDF-versjon%20https", blueprint: { locked: true, master_content: true, child_content: false } },
      href_problem: "Adressen er ikke gyldig: «PDF-versjon https» inneholder mellomrom og er ikke et nettstedsnavn.",
      fix: { type: "replace_link_href", label: "Rett den tomme lenken",
        params: { empty: true, text: "", suggestion: "", default_action: "remove" } },
    };
    const calls = stubFetch((url) => (url.includes("/fix/preview") ? { ...preview,
      changes: [{ before: "<a title=\"\" href=\"http://PDF-versjon%20https\" target=\"\"></a>", after: "" }] } : {}));
    render(wrap(<FindingDetail finding={empty} open onClose={() => {}} />));
    const dialog = screen.getByRole("dialog", { name: "Lenke uten tekst" });
    expect(within(dialog).getByText("Adressen er ugyldig")).toBeInTheDocument();
    expect(within(dialog).getByText(/PDF-versjon https/, { selector: "div" })).toBeInTheDocument();
    // In the Blueprint course itself the content is not «locked here».
    expect(within(dialog).queryByText("Låst av Blueprint")).not.toBeInTheDocument();
    expect(within(dialog).getByText(/låst i de tilknyttede emnene/)).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /Fjern den tomme lenken/ })).toBeChecked();
    expect(within(dialog).queryByRole("radio", { name: /behold teksten/ })).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.includes("/fix/preview") &&
      (c.body as Record<string, unknown>).link_action === "remove")).toBe(true));

    await userEvent.click(within(dialog).getByRole("radio", { name: /Gi lenken tekst og riktig adresse/ }));
    await userEvent.type(within(dialog).getByLabelText(/^Adresse/), "https://www.uio.no/pensum.pdf");
    expect(within(dialog).getByText(/Skriv lenketekst og adresse/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/^Lenketekst/), "Pensumliste (PDF)");
    await waitFor(() => expect(calls.some((c) => (c.body as Record<string, unknown> | undefined)?.link_text === "Pensumliste (PDF)"))
      .toBe(true));
  });
});

describe("change queue", () => {
  it("publishes approved changes across courses after a short confirmation", async () => {
    const change = (id: number, course: string, name: string, status: string) => ({
      id, course_id: course, course_name: name, domain: "accessibility", kind: "page.update_body", kind_label: "Oppdater sideinnhold",
      title: `Side ${id}: universell utforming`, target: { object_type: "page", object_id: `s${id}`, title: `Side ${id}` },
      before: {}, proposed: {}, rationale: "", risk: "low", undo_capability: "full", undo_note: "", conflict_status: "not_checked",
      status, requires_confirmation: false, editable: false, ai_generated: false, source: {}, fix_count: 1, rebuildable: true,
      result: status === "failed" ? { error_category: "blueprint" } : {}, error: status === "failed" ? "Låst av Blueprint" : null,
      created_at: "2026-11-06T10:00:00Z", updated_at: null, applied_at: null,
    });
    const items = [change(1, "101", "Digital kompetanse", "approved"), change(2, "104", "Kull 2026", "approved"),
      change(3, "104", "Kull 2026", "failed"), change(4, "101", "Digital kompetanse", "staged")];
    const calls = stubFetch((url) => {
      if (url === "/api/changes") return {
        items, groups: [{ domain: "accessibility", label: "UU-rettinger", count: 4 }],
        courses: [{ course_id: "101", name: "Digital kompetanse", count: 2, approved: 1, problems: 0 },
          { course_id: "104", name: "Kull 2026", count: 2, approved: 1, problems: 1 }],
        summary: { pending: 3, approved: 2, problems: 1, courses: 2, by_domain: {}, by_status: {} }, publishing_job: null,
      };
      if (url === "/api/changes/apply") return { id: "job-1", status: "queued", progress: { done: 0, total: 2 }, result: {} };
      return { status: "running", progress: { done: 0, total: 2, types: {} }, result: {} };
    });
    render(wrap(<ChangeSetDrawer open onClose={() => {}} />));
    const publish = await screen.findByRole("button", { name: "Publiser til Canvas (2)" });
    expect(screen.getByRole("heading", { name: /Digital kompetanse/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Kull 2026/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Godkjenn alle (2)" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Rett i Blueprint-emnet/ })).toBeInTheDocument();
    await userEvent.click(publish);
    const confirm = screen.getByRole("dialog", { name: "Publiser til Canvas" });
    expect(within(confirm).getByText("Digital kompetanse")).toBeInTheDocument();
    expect(within(confirm).getByText("Kull 2026")).toBeInTheDocument();
    await userEvent.click(within(confirm).getByRole("button", { name: "Publiser 2 endringer" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/api/changes/apply")?.body).toEqual({ ids: [1, 2], confirm_high_risk: false }));
  });
});
