import { useEffect } from "react";

/** Sets a unique, descriptive document title (WCAG 2.4.2). */
export function usePageTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} – EmneKlar` : "EmneKlar";
  }, [title]);
}
