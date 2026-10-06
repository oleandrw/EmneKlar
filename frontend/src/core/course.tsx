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

export function courseLabel(course: Course | null | undefined): string {
  if (!course) return "Velg emne";
  return course.course_code ? `${course.course_code}` : course.name;
}
