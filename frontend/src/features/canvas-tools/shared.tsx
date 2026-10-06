import { ArrowLeft } from "lucide-react";

import { ButtonLink } from "../../design-system";

export function BackToTools() {
  return (
    <div>
      <ButtonLink to="/canvas-verktoy" variant="link" icon={<ArrowLeft aria-hidden="true" />}>
        Canvas-verktøy
      </ButtonLink>
    </div>
  );
}

export interface ContentIndex {
  modules: { id: string; name: string; items_count: number }[];
  partial: boolean;
}
