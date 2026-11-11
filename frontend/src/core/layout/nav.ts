import {
  Accessibility,
  ChartColumn,
  CircleQuestionMark,
  FileCheck,
  LayoutDashboard,
  ListChecks,
  ListTree,
  Palette,
  Settings,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  flag?: string;
}

// The primary navigation is fixed. Add new functionality inside an existing
// domain instead of adding entries here.
export const PRIMARY_NAV: NavItem[] = [
  { to: "/oversikt", label: "Oversikt", icon: LayoutDashboard },
  { to: "/universell-utforming", label: "Universell utforming", icon: Accessibility },
  { to: "/innholdskvalitet", label: "Innholdskvalitet", icon: FileCheck },
  { to: "/emnestruktur", label: "Emnestruktur", icon: ListTree },
  { to: "/quizassistent", label: "Quizassistent", icon: ListChecks, flag: "quiz_assistant" },
  { to: "/emnedesign", label: "Emnedesign", icon: Palette, flag: "course_design" },
  { to: "/canvas-verktoy", label: "Canvas-verktøy", icon: Wrench },
  { to: "/rapporter", label: "Rapporter", icon: ChartColumn },
];

export const SECONDARY_NAV: NavItem[] = [
  { to: "/innstillinger", label: "Innstillinger", icon: Settings },
  { to: "/hjelp", label: "Hjelp", icon: CircleQuestionMark },
];
