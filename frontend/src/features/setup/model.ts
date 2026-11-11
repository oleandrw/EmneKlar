// The setup wizard's logic, kept apart from the page so it can be tested: the four steps, where an interrupted setup
// continues, how the Canvas address is read, and how the permission check is put into words.
import type { SessionData } from "../../core/api/types";

export type StepId = "connect" | "confirm" | "start" | "done";

export const STEPS: { id: StepId; label: string; title: string }[] = [
  { id: "connect", label: "Tilkobling", title: "Koble til Canvas" },
  { id: "confirm", label: "Bekreftelse", title: "Bekreft tilkoblingen" },
  { id: "start", label: "Emne og regelverk", title: "Velg emne og regelverk" },
  { id: "done", label: "Ferdig", title: "Klar til bruk" },
];

export interface Capability {
  key: string;
  label: string;
  granted: number;
  checked: number;
  /** The checked courses (by course code) where this permission is missing. */
  missing_in?: string[];
}

export interface Access {
  teaching_courses: number;
  checked_courses: number;
  /** The courses that were checked, and those whose check failed (unknown – not «missing»). */
  checked_in?: string[];
  failed_in?: string[];
  capabilities: Capability[];
}

export interface CourseBrief {
  id: string;
  name: string;
  course_code: string | null;
  term_name: string | null;
}

export interface TestResult {
  ok: boolean;
  base_url: string;
  identity: { id: string; name: string };
  teaching_courses: number;
  /** The teaching courses (name, code, term) – shown by name, as in the course list of step 3. */
  courses?: CourseBrief[];
  access?: Access;
}

/** The name each course is shown by: its name, as in step 3; the course code is added only where two courses have the
 * same name (and stands in when a course has no name). Ids of unknown courses fall back to the id. */
export function courseNames(courses: CourseBrief[] | undefined): (id: string) => string {
  const list = courses ?? [];
  const key = (c: CourseBrief) => c.name.trim().toLowerCase();
  const seen = new Map<string, number>();
  for (const c of list) if (c.name.trim()) seen.set(key(c), (seen.get(key(c)) ?? 0) + 1);
  const byId = new Map(list.map((c) => {
    const name = c.name.trim();
    if (!name) return [c.id, c.course_code || c.id];
    return [c.id, (seen.get(key(c)) ?? 0) > 1 && c.course_code ? `${name} (${c.course_code})` : name];
  }));
  return (id) => byId.get(id) ?? id;
}

/**
 * Where the setup starts. Nothing about the wizard's progress is stored except what each step saves: the connection
 * (saved when it is confirmed – step 5 of 9 in the old wizard, step 2 of 4 now) and «setup completed». So a setup
 * that was interrupted after the connection was saved, also one from the old nine-step wizard, continues at
 * «Utgangspunkt»; anything earlier starts at «Tilkobling» (with the saved address filled in). A completed setup is
 * never shown again unless /oppsett is opened on purpose.
 */
export function initialStep(session: Pick<SessionData, "setup_completed" | "canvas">): StepId {
  const c = session.canvas;
  return !session.setup_completed && c.base_url && c.token_configured && c.identity ? "start" : "connect";
}

/** The Canvas address as Canvas wants it (scheme + host), or a message saying what is wrong with it. */
export function readCanvasUrl(input: string): { url: string } | { error: string } {
  const raw = input.trim();
  if (!raw) return { error: "Skriv inn adressen til Canvas." };
  if (/\s/.test(raw)) return { error: "Adressen kan ikke inneholde mellomrom." };
  let parsed: URL;
  try {
    parsed = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`);
  } catch {
    return { error: "Det ser ikke ut som en nettadresse. Skriv for eksempel https://hiof.instructure.com." };
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return { error: "Adressen må begynne med https://." };
  }
  if (parsed.username || parsed.password) return { error: "Adressen kan ikke inneholde brukernavn eller passord." };
  if (!parsed.hostname.includes(".") && parsed.hostname !== "localhost") {
    return { error: "Skriv hele adressen, for eksempel https://hiof.instructure.com." };
  }
  // A pasted course address (…/courses/123) is fine – only the scheme and host are used.
  return { url: parsed.origin };
}

export const hostOf = (url: string | null | undefined): string => {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
};

/* «kontrollerte» is said only when the check did not cover every teaching course (a sample, or a check that failed):
 * `whole` – every teaching course was checked – drops it, so the text is short when it can be and never claims more
 * than was checked when it cannot. A permission is never presented as general when it was only seen in some courses. */

/** «i det kontrollerte emnet» / «i begge kontrollerte emner» / «i alle 5 kontrollerte emner» – or, `whole`, «i emnet» /
 * «i begge emnene» / «i alle 5 emnene». */
function inAllChecked(checked: number, whole = false): string {
  if (whole) return checked === 1 ? "i emnet" : checked === 2 ? "i begge emnene" : `i alle ${checked} emnene`;
  if (checked === 1) return "i det kontrollerte emnet";
  return checked === 2 ? "i begge kontrollerte emner" : `i alle ${checked} kontrollerte emner`;
}

/** «i ingen av de to kontrollerte emnene» – or, `whole`, «i ingen av de to emnene» – and so on. */
function inNoneChecked(checked: number, whole = false): string {
  if (checked === 1) return whole ? "ikke i emnet" : "ikke i det kontrollerte emnet";
  const which = whole ? "emnene" : "kontrollerte emnene";
  return checked === 2 ? `i ingen av de to ${which}` : `i ingen av de ${checked} ${which}`;
}

/** «i 3 av 5 kontrollerte emner» – or, `whole`, «i 3 av 5 emner». */
function inSomeChecked(granted: number, checked: number, whole = false): string {
  return `i ${granted} av ${checked} ${whole ? "emner" : "kontrollerte emner"}`;
}

/** Where a permission was granted; pass `teachingCourses` to leave out «kontrollerte» when this permission was checked
 * in every teaching course. */
export function grantedIn(cap: Pick<Capability, "granted" | "checked">, teachingCourses?: number): string {
  if (cap.checked === 0) return "ikke kontrollert";
  const whole = cap.checked === teachingCourses;
  if (cap.granted === cap.checked) return inAllChecked(cap.checked, whole);
  if (cap.granted === 0) return inNoneChecked(cap.checked, whole);
  return inSomeChecked(cap.granted, cap.checked, whole);
}

export type AccessLevel = "all" | "some" | "none" | "unknown";

/** «A», «A og B», «A, B og C» – and «A, B, C og 2 til» for longer lists. */
export function courseList(names: string[]): string {
  if (names.length > 3) return `${names.slice(0, 3).join(", ")} og ${names.length - 3} til`;
  return names.length <= 1 ? names.join("") : `${names.slice(0, -1).join(", ")} og ${names[names.length - 1]}`;
}

/** At most this many course names in a sentence; with more, a short summary and the names behind «Vis emnene». */
export const NAMES_IN_SENTENCE = 3;

const byId = (id: string) => id;

/** The one sentence over the list in «Se alle tilganger». Everything granted: «Alle kontrollerte tilganger er innvilget
 * i A og B.» (the courses by name; with many, a short sentence and the names on request). Otherwise only how many
 * were granted in every course checked – «6 av 7 tilganger er innvilget i begge emnene.» – and the rows below say
 * what is missing, varies or is unknown. `courses` holds the names to show on request. */
export function accessHeadline(access: Access, name: (id: string) => string = byId): { text: string; courses: string[] } {
  const n = access.checked_courses;
  if (n === 0) return { text: "Tilgangene kunne ikke kontrolleres.", courses: [] };
  const checked = (access.checked_in ?? []).map(name);
  const allChecked = n === access.teaching_courses;
  const caps = access.capabilities;
  const everywhere = caps.filter((c) => c.checked === n && c.granted === n).length;
  if (everywhere === caps.length) {
    const few = checked.length > 0 && checked.length <= NAMES_IN_SENTENCE;
    const many = allChecked ? `i alle ${n} emnene` : `i de ${n} kontrollerte emnene`;
    const where = few ? `i ${courseList(checked)}` : n > NAMES_IN_SENTENCE ? many : inAllChecked(n, allChecked);
    return { text: `Alle kontrollerte tilganger er innvilget ${where}.`, courses: few ? [] : checked };
  }
  // Not named in the sentence: offer the names when they are not all the teaching courses, or when there are many.
  const courses = !allChecked || n > NAMES_IN_SENTENCE ? checked : [];
  return { text: `${everywhere} av ${caps.length} tilganger er innvilget ${inAllChecked(n, allChecked)}.`, courses };
}

/** The status box at the top of «Bekreftelse»: the connection works either way – missing or unknown permissions are
 * said in words (and with a warning icon), never treated as a failed connection or as blocking what can be done. */
export function connectionStatus(access: Access | undefined): { tone: "success" | "warning"; title: string } {
  if (!access || access.teaching_courses === 0) return { tone: "success", title: "Tilkoblingen virker." };
  const n = access.checked_courses;
  const missing = access.capabilities.some((c) => c.checked > 0 && c.granted < c.checked);
  const unknown = n === 0 || (access.failed_in?.length ?? 0) > 0 || access.capabilities.some((c) => c.checked < n);
  if (missing && unknown) {
    return { tone: "warning", title: "Tilkoblingen virker, men noen tilganger mangler, og enkelte kunne ikke kontrolleres." };
  }
  if (missing) return { tone: "warning", title: "Tilkoblingen virker, men noen tilganger mangler." };
  if (unknown) return { tone: "warning", title: "Tilkoblingen virker, men enkelte tilganger kunne ikke kontrolleres." };
  return { tone: "success", title: "Tilkoblingen virker." };
}

/** What the sentence leaves out: courses that could not be checked (unknown, not missing), and that the check was a
 * sample when there are more teaching courses. */
export function accessNotes(access: Access, name: (id: string) => string = byId): string[] {
  const lines: string[] = [];
  const failed = access.failed_in ?? [];
  if (failed.length) lines.push(`Kunne ikke kontrolleres i ${courseList(failed.map(name))}.`);
  const tried = access.checked_courses + failed.length;
  if (tried > 0 && tried < access.teaching_courses) {
    lines.push(`Kontrollen gjelder et utvalg på ${tried} av ${access.teaching_courses} emner.`);
  }
  return lines;
}

/** One row in «Se alle tilganger»: a note only when the permission is missing, varies between the courses or is
 * unknown – and the status in words for screen readers either way (the icon is decorative). With `teachingCourses`,
 * «kontrollerte» is left out when this permission was checked in every teaching course. */
export function capabilityRow(
  cap: Capability, name: (id: string) => string = byId, checkedCourses = 1, teachingCourses?: number,
): { level: AccessLevel; note: string | null; spoken: string } {
  const level = levelOf(cap);
  const missing = (cap.missing_in ?? []).map(name);
  const whole = cap.checked === teachingCourses;
  if (level === "all") return { level, note: null, spoken: "innvilget" };
  if (level === "unknown") {
    // When nothing could be checked, the sentence above says so once – no note on every row.
    return { level, note: checkedCourses === 0 ? null : "Kunne ikke kontrolleres", spoken: "kunne ikke kontrolleres" };
  }
  if (level === "none") {
    const note = cap.checked === 1 && missing.length === 1
      ? `Mangler i ${missing[0]}` : `Mangler ${inAllChecked(cap.checked, whole)}`;
    return { level, note, spoken: note };
  }
  const note = `Innvilget ${inSomeChecked(cap.granted, cap.checked, whole)}.`
    + (missing.length ? ` Mangler i ${courseList(missing)}.` : "");
  return { level, note, spoken: note };
}

/** «2 emner med lærer-, assistent- eller designertilgang», with the right number. */
export function teachingCourses(n: number): string {
  const what = "med lærer-, assistent- eller designertilgang";
  if (n === 0) return `Ingen emner ${what}`;
  return `${n} ${n === 1 ? "emne" : "emner"} ${what}`;
}

/** The second line under a course name: course code and term («LA101IKT14-1 26H · Høst 2026»), or "". */
/** Code and term for the smaller line under a course name. The code is left out where it only repeats the name. */
export function courseMeta(course: { name?: string | null; course_code: string | null; term_name: string | null }): string {
  const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();
  const code = course.course_code && !(course.name && same(course.course_code, course.name)) ? course.course_code : null;
  return [code, course.term_name].filter(Boolean).join(" · ");
}

export function levelOf(cap: Capability | undefined): AccessLevel {
  if (!cap || cap.checked === 0) return "unknown";
  if (cap.granted === cap.checked) return "all";
  return cap.granted === 0 ? "none" : "some";
}

/** The short summary on «Bekreftelse», read from the permissions that were actually checked: reading (analysis) and
 * editing pages – page editing is never presented as write access to every kind of content (that is under «Se
 * tilganger»), and missing write access never blocks what can be done with read access. Granted everywhere: no text
 * (the check mark says it); otherwise where it is missing, and what that means. */
export function accessSummary(access: Access | undefined): { key: string; level: AccessLevel; title: string; text: string }[] {
  if (!access || access.checked_courses === 0) {
    return [{
      key: "unknown", level: "unknown", title: "Tilganger",
      text: access && access.teaching_courses === 0
        ? "ingen emner å kontrollere ennå. Tilgang kontrolleres i hvert emne før endringer."
        : "kunne ikke kontrolleres nå. Tilgang kontrolleres i hvert emne før endringer.",
    }];
  }
  const cap = (key: string) => access.capabilities.find((c) => c.key === key);
  const read = cap("read");
  const pages = cap("pages");
  const readLevel = levelOf(read);
  const writeLevel = levelOf(pages);
  return [
    {
      key: "analyse", level: readLevel, title: "Lese og analysere",
      text: readLevel === "all" ? "" : readLevel === "unknown" ? "ikke kontrollert."
        : `full lesetilgang ${grantedIn(read!, access.teaching_courses)}. Uten den kan upublisert innhold mangle i analysen.`,
    },
    {
      key: "pages", level: writeLevel, title: "Redigere sider",
      text: writeLevel === "all" ? "" : writeLevel === "unknown" ? "ikke kontrollert."
        : `${grantedIn(pages!, access.teaching_courses)}. Du kan fortsatt analysere der det mangler.`,
    },
  ];
}
