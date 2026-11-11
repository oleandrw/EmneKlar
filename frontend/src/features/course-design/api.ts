// Emnedesign: profiles, the course's design choice, the inventory of content in a scope, previews, structure
// suggestions and approval to the change queue (nothing is published from here).
import { useQuery } from "@tanstack/react-query";

import { api, qs } from "../../core/api/client";

export type DesignMode = "keep" | "structure";
export type ContentKind = "front_page" | "syllabus" | "module_intro" | "page" | "assignment" | "quiz";

export interface DesignProfile {
  id: string;
  version: string;
  label: string;
  description: string;
  default: boolean;
  tokens: Record<string, string>;
  /** The same sample content with the structure kept / with suggested sections (sanitised, for the sandboxed preview). */
  sample_keep: string;
  sample_structure: string;
  /** The top of a sample page for the small example: its title (shown by Canvas) and a short designed body. */
  sample_title?: string;
  sample_compact?: string;
}

export interface SavedDesign {
  profile_id: string;
  profile_version: string;
  mode: DesignMode;
  illustrations: boolean;
  updated_at: string | null;
}

export interface InventoryItem {
  key: string;
  object_type: string;
  object_id: string;
  title: string;
  kind: ContentKind;
  kind_label: string;
  modules: string[];
  /** The same content is used in more than one module – a change affects it everywhere. */
  shared: boolean;
  locked: boolean;
  published: boolean | null;
  /** «profile@version» of an existing Emnedesign, «ukjent», or null. */
  design: string | null;
  empty: boolean;
  /** «Behold eksisterende design». */
  excluded: boolean;
  url: string | null;
}

export interface InventoryModule {
  id: string;
  name: string;
  /** Place in the course (Canvas' order) and whether the module is published. */
  position?: number;
  published?: boolean | null;
  /** Content a design can be applied to (pages, assignments, classic quizzes). */
  count?: number;
  /** Everything in the module except text headers (files, links … included). */
  total?: number;
}

/** Blueprint for the selection as a whole (null in an ordinary course). */
export interface BlueprintSelection {
  role: "blueprint" | "associated";
  summary: string;
  limitation: string | null;
  details: string[];
  locked: number;
  total: number;
}

export interface Inventory {
  modules: InventoryModule[];
  blueprint?: BlueprintSelection | null;
  items: InventoryItem[];
  not_included: { label: string; reason: string }[];
  where: { role: string; message: string; locked?: boolean };
  course: { name: string | null };
}

export interface StructurePlan {
  sections: { role: string; label: string | null; blocks: string[] }[];
}

export interface PreviewItem {
  key: string;
  error?: string;
  content_hash?: string;
  before?: string;
  after?: string;
  notes?: string[];
  structure_changes?: string[];
  problems?: string[];
  unchanged?: boolean;
  structured?: boolean;
}

export interface ApproveResult {
  key: string;
  status: "approved" | "changed" | "refused" | "unchanged" | "error";
  change_id?: number;
  message?: string;
}

export function useDesignProfiles() {
  return useQuery({
    queryKey: ["course-design", "profiles"],
    queryFn: () => api.get<{ profiles: DesignProfile[]; default: string }>("/api/course-design/profiles"),
    staleTime: 10 * 60_000,
  });
}

export function useSavedDesign(courseId: string | null) {
  return useQuery({
    queryKey: ["course-design", courseId, "saved"],
    queryFn: () => api.get<{ design: SavedDesign | null; excluded: string[] }>(`/api/courses/${courseId}/course-design`),
    enabled: Boolean(courseId),
  });
}

export function useInventory(courseId: string | null, moduleId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["course-design", courseId, "inventory", moduleId],
    queryFn: () => api.get<Inventory>(`/api/courses/${courseId}/course-design/inventory${qs({ module_id: moduleId })}`),
    enabled: Boolean(courseId) && enabled,
  });
}

export const MAX_PREVIEW = 40;

/** Previews in batches (the API reads each item live from Canvas). */
export async function previewItems(courseId: string, profileId: string, items: InventoryItem[],
  plans: Record<string, StructurePlan>): Promise<PreviewItem[]> {
  const out: PreviewItem[] = [];
  for (let i = 0; i < items.length; i += MAX_PREVIEW) {
    const batch = items.slice(i, i + MAX_PREVIEW);
    const result = await api.post<{ items: PreviewItem[] }>(`/api/courses/${courseId}/course-design/preview`, {
      profile_id: profileId,
      items: batch.map((item) => item.key),
      kinds: Object.fromEntries(batch.map((item) => [item.key, item.kind])),
      plans: Object.fromEntries(batch.filter((item) => plans[item.key]).map((item) => [item.key, plans[item.key]])),
    });
    out.push(...result.items);
  }
  return out;
}
