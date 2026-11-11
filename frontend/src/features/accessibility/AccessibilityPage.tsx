import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "../../core/api/client";
import { usePageTitle } from "../../core/usePageTitle";
import { Alert, PageHeader } from "../../design-system";
import { FindingsView } from "../findings/FindingsView";

interface ProfilesResponse {
  selected: string;
  profiles: { id: string; title: string; criteria_count: number; document_criteria_count: number; is_legal_requirement: boolean; verified_at: string; version: string }[];
}

export function AccessibilityPage() {
  usePageTitle("Universell utforming");
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<ProfilesResponse>("/api/accessibility/profiles") });
  const profile = profiles.data?.profiles.find((p) => p.id === profiles.data?.selected);

  return (
    <>
      <PageHeader
        title="Universell utforming"
        description="Kontroll av bilder, overskrifter, lenker, tabeller, lister, språk, kontrast, innebygd innhold, video og dokumenter."
      />
      <div className="ek-stack" data-gap="6">
        <Alert tone="info" title="Automatisk kontroll er ikke en sertifisering">
          EmneKlar finner mange vanlige feil, men automatiske kontroller kan ikke bevise at et emne er universelt utformet.
          Funn merket «Manuell kontroll» og innhold i eksterne verktøy må vurderes av et menneske.{" "}
          {profile ? (
            <>
              Juridisk status vises etter profilen <strong>{profile.title}</strong> ({profile.criteria_count} suksesskriterier
              {profile.document_criteria_count !== profile.criteria_count ? `, ${profile.document_criteria_count} for dokumenter` : ""}
              , kontrollert {profile.verified_at}). <Link to="/innstillinger/analyse">Bytt profil</Link>
            </>
          ) : null}
        </Alert>
        <FindingsView
          domain="accessibility"
          emptyText="Start med «Analyser universell utforming» øverst til høyre. Analysen leser bare fra Canvas – ingenting endres."
        />
      </div>
    </>
  );
}
