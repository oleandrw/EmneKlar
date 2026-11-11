// The global course context: one selected course drives every feature.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api/client";
import type { Course } from "./api/types";
import { useSession } from "./session";

export interface CourseList {
  courses: Course[];
  fetched_at: string | null;
  from_cache: boolean;
}

export function useCourses(enabled = true) {
  return useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseList>("/api/courses"),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useCurrentCourse(): { courseId: string | null; course: Course | null; loading: boolean } {
  const session = useSession();
  const courses = useCourses(Boolean(session.canvas.token_configured));
  const courseId = session.current_course_id;
  const course = courses.data?.courses.find((c) => c.id === courseId) ?? null;
  return { courseId, course, loading: courses.isPending };
}

export function useSelectCourse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (courseId: string) => api.put<{ current_course_id: string }>("/api/context/course", { course_id: courseId }),
    onSuccess: async () => {
      // Every feature query is keyed by course id; refreshing the session switches context everywhere.
      await client.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

/** Mark or unmark a course as a favourite (stored in EmneKlar – Canvas' own favourites are not changed). The list is
 * updated at once and corrected from the server if saving fails. */
export function useFavoriteCourse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ courseId, favorite }: { courseId: string; favorite: boolean }) =>
      api.put<{ favorite_course_ids: string[] }>(`/api/courses/${courseId}/favorite`, { favorite }),
    onMutate: ({ courseId, favorite }) => {
      client.setQueryData<CourseList>(["courses"], (data) =>
        data ? { ...data, courses: data.courses.map((c) => (c.id === courseId ? { ...c, favorite } : c)) } : data);
    },
    onError: () => void client.invalidateQueries({ queryKey: ["courses"] }),
  });
}

/** The search text as typed – or the course id from a pasted Canvas address (…/courses/547/pages/…). */
export function courseQuery(query: string): string {
  const q = query.trim().toLowerCase();
  return q.match(/\/courses\/(\d+)/)?.[1] ?? q;
}

/** Courses matching the search: course id (the number in the Canvas address), code, name or term. An exact course id
 * comes first. */
export function matchCourses(all: Course[], query: string): Course[] {
  const q = courseQuery(query);
  if (!q) return all;
  const hits = all.filter((c) => `${c.id} ${c.name} ${c.course_code ?? ""} ${c.term_name ?? ""}`.toLowerCase().includes(q));
  return [...hits].sort((a, b) => Number(b.id === q) - Number(a.id === q));
}

export function courseLabel(course: Course | null | undefined): string {
  if (!course) return "Velg emne";
  return course.course_code ? `${course.course_code}` : course.name;
}
