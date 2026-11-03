// Icons for finding categories, shared by every list of findings. Decorative: the category is always
// written out next to the icon.
import {
  AppWindow,
  CalendarClock,
  CircleDot,
  Code,
  Contrast,
  Copy,
  EyeOff,
  FileText,
  Heading,
  Image,
  KeyRound,
  Languages,
  Layers,
  Link2,
  List,
  ListChecks,
  Network,
  Table2,
  Type,
  Video,
  type LucideIcon,
} from "lucide-react";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  // universell utforming
  images: Image,
  headings: Heading,
  links: Link2,
  tables: Table2,
  lists: List,
  language: Languages,
  contrast: Contrast,
  iframes: AppWindow,
  media: Video,
  documents: FileText,
  markup: Code,
  // innholdskvalitet
  html: Code,
  content: FileText,
  // emnestruktur
  placement: Network,
  modules: Layers,
  naming: Type,
  progression: CalendarClock,
  duplicates: Copy,
  publishing: EyeOff,
  // quiz
  key: KeyRound,
  options: ListChecks,
  wording: Type,
};

export function CategoryIcon({ category }: { category: string }) {
  const Icon = CATEGORY_ICONS[category] ?? CircleDot;
  return <Icon aria-hidden="true" />;
}
