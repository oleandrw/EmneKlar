// «Forhåndsvis løsning» → diff + preview → «Legg endring til kø». Never writes to Canvas directly.
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import type { Finding } from "../../core/api/types";
import { RISK } from "../../core/labels";
import { useSession } from "../../core/session";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  DiffView,
  HtmlPreview,
  SelectField,
  TextField,
  useToast,
  type PreviewDevice,
} from "../../design-system";
import { AltTextSuggestion } from "./AltTextSuggestion";
import { fixPreview, fixStage, useFindingActions, type FixParams, type FixPreview } from "./api";

const LANGS = [
  { value: "en", label: "Engelsk (en)" },
  { value: "nb", label: "Norsk bokmål (nb)" },
  { value: "nn", label: "Norsk nynorsk (nn)" },
  { value: "se", label: "Nordsamisk (se)" },
  { value: "sv", label: "Svensk (sv)" },
  { value: "da", label: "Dansk (da)" },
  { value: "de", label: "Tysk (de)" },
  { value: "fr", label: "Fransk (fr)" },
  { value: "es", label: "Spansk (es)" },
];

export function FixPanel({ finding, onStaged }: { finding: Finding; onStaged: () => void }) {
  const fix = finding.fix!;
  const session = useSession();
  const toast = useToast();
  const actions = useFindingActions();
  const fixParams = (fix.params ?? {}) as Record<string, unknown>;
  const [text, setText] = useState<string>(String(fixParams.suggestion ?? ""));
  const [decorative, setDecorative] = useState(false);
  const [level, setLevel] = useState<string>(String(fixParams.level ?? 2));
  const [lang, setLang] = useState<string>(String(fixParams.lang ?? "en"));
  const [device, setDevice] = useState<PreviewDevice>("desktop");
  const [preview, setPreview] = useState<FixPreview | null>(null);

  const needsText = ["set_alt", "set_link_text", "set_iframe_title", "table_caption"].includes(fix.type);
  const needsLevel = ["change_heading_level", "convert_to_heading"].includes(fix.type);
  const params: FixParams = {
    text: needsText && !decorative ? text : undefined,
    decorative: fix.type === "set_alt" ? decorative : undefined,
    level: needsLevel ? Number(level) : undefined,
    lang: fix.type === "set_lang" ? lang : undefined,
  };
  const textLabel: Record<string, string> = {
    set_alt: "Alternativ tekst",
    set_link_text: "Lenketekst",
    set_iframe_title: "Tittel på innebygd innhold",
    table_caption: "Tabelltittel",
  };

  const previewMutation = useMutation({ mutationFn: () => fixPreview(finding.id, params), onSuccess: setPreview });
  const stageMutation = useMutation({
    mutationFn: () => fixStage(finding.id, params),
    onSuccess: () => {
      actions.refresh();
      toast.show({
        tone: "success",
        title: "Endringen er lagt i endringskøen",
        body: session.dry_run
          ? "Dry run er på – endringen sendes ikke til Canvas før du slår det av."
          : "Godkjenn og gjennomfør den fra endringskøen.",
      });
      onStaged();
    },
  });

  return (
    <div className="ek-stack">
      <h3>{fix.label}</h3>
      {fix.type === "set_alt" ? (
        <Checkbox
          label="Bildet er dekorativt (tom alt-tekst)"
          hint="Velg dette bare når bildet ikke formidler noe som ikke står i teksten."
          checked={decorative}
          onChange={(e) => {
            setDecorative(e.target.checked);
            setPreview(null);
          }}
        />
      ) : null}
      {needsText && !decorative ? (
        <>
          <TextField
            label={textLabel[fix.type] ?? "Tekst"}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setPreview(null);
            }}
            hint={fix.type === "set_alt" ? "Beskriv det bildet formidler i denne sammenhengen – ikke utseendet alene." : undefined}
            maxLength={500}
          />
          {fix.type === "set_alt" ? <AltTextSuggestion finding={finding} onUse={(v) => setText(v)} /> : null}
        </>
      ) : null}
      {needsLevel ? (
        <SelectField
          label="Overskriftsnivå"
          value={level}
          onChange={(e) => {
            setLevel(e.target.value);
            setPreview(null);
          }}
          options={[2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `Overskrift ${n}` }))}
        />
      ) : null}
      {fix.type === "set_lang" ? (
        <SelectField label="Språk" value={lang} onChange={(e) => setLang(e.target.value)} options={LANGS} />
      ) : null}

      {previewMutation.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke lage forhåndsvisning">
          {(previewMutation.error as Error).message}
        </Alert>
      ) : null}
      {stageMutation.error ? (
        <Alert tone="danger" role="alert" title="Kunne ikke legge endringen i kø">
          {(stageMutation.error as Error).message}
        </Alert>
      ) : null}

      <div className="ek-cluster">
        <Button onClick={() => previewMutation.mutate()} loading={previewMutation.isPending}>
          Forhåndsvis løsning
        </Button>
        <Button
          variant="primary"
          onClick={() => stageMutation.mutate()}
          loading={stageMutation.isPending}
          disabled={!preview}
          title={preview ? undefined : "Forhåndsvis løsningen først"}
        >
          Legg endring til kø
        </Button>
      </div>

      {preview ? (
        <div className="ek-stack">
          <div className="ek-cluster">
            <Badge tone={RISK[preview.risk]?.tone}>{RISK[preview.risk]?.label}</Badge>
            {preview.existing_change_id ? (
              <Badge tone="info">Slås sammen med en annen endring på samme side</Badge>
            ) : null}
          </div>
          <DiffView before={preview.before_display} after={preview.after_display} />
          <div className="ek-cluster" role="group" aria-label="Visning">
            {(["desktop", "tablet", "mobile"] as PreviewDevice[]).map((d) => (
              <Button key={d} size="sm" variant={device === d ? "primary" : "secondary"} aria-pressed={device === d}
                onClick={() => setDevice(d)}>
                {{ desktop: "PC", tablet: "Nettbrett", mobile: "Mobil" }[d]}
              </Button>
            ))}
          </div>
          <HtmlPreview html={preview.preview_html} title={`Forhåndsvisning av ${finding.object_title}`} device={device} />
        </div>
      ) : null}
    </div>
  );
}
