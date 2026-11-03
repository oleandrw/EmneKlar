// Contextual help: a link from a complex feature to its section in Hjelp → Brukerveiledninger.
import { CircleQuestionMark } from "lucide-react";
import { Link } from "react-router";

export function HelpLink({ topic, label = "Hjelp" }: { topic: string; label?: string }) {
  return (
    <Link to={`/hjelp/brukerveiledninger#${topic}`} className="ek-btn ek-btn--ghost ek-btn--sm">
      <CircleQuestionMark aria-hidden="true" />
      {label}
      <span className="ek-visually-hidden"> om denne siden</span>
    </Link>
  );
}
