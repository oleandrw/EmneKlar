import { FileCheck, Film, Link2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router";

import { usePageTitle } from "../../core/usePageTitle";
import { PageHeader, Tabs } from "../../design-system";
import { FindingsView } from "../findings/FindingsView";
import { LinksPanel } from "./LinksPanel";
import { VideoStandardiser } from "./VideoStandardiser";

/** The link states as the overview groups them (re-exported for other views). */
export { CATEGORY as LINK_CATEGORY } from "./LinksPanel";

type Tab = "findings" | "links" | "media";
/** ``?fane=lenker`` (e.g. from Oversikt → «Se døde lenker») opens that tab. */
const TAB_PARAM: Record<string, Tab> = { funn: "findings", lenker: "links", media: "media" };

export function ContentQualityPage() {
  usePageTitle("Innholdskvalitet");
  const [search] = useSearchParams();
  const [tab, setTab] = useState<Tab>(() => TAB_PARAM[search.get("fane") ?? ""] ?? "findings");
  return (
    <>
      <PageHeader
        title="Innholdskvalitet"
        description="Tekniske kvalitetsproblemer: lenker som ikke virker, medier som er borte og unødvendig kode. Dette er ikke en vurdering av faglig kvalitet."
      />
      <Tabs
        label="Innholdskvalitet"
        selected={tab}
        onSelect={setTab}
        tabs={[
          { id: "findings", label: "Funn", icon: <FileCheck aria-hidden="true" /> },
          { id: "links", label: "Lenker", icon: <Link2 aria-hidden="true" /> },
          { id: "media", label: "Media", icon: <Film aria-hidden="true" /> },
        ]}
      >
        <div className="ek-mt-6">
          {tab === "findings" ? (
            <FindingsView
              domain="content_quality"
              emptyText="Start med «Analyser innholdskvalitet» øverst til høyre. Analysen kontrollerer lenker, medier og HTML-kode og leser bare fra Canvas."
            />
          ) : tab === "links" ? (
            <LinksPanel />
          ) : (
            <VideoStandardiser />
          )}
        </div>
      </Tabs>
    </>
  );
}
