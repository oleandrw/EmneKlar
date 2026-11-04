// Detail view of one illustration: large preview with the page context, the pedagogical plan, the review, and
// everything the teacher can change (alt text, caption, placement, prompt, style, version, decision).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Palette, RefreshCw, SkipForward, X } from "lucide-react";
import { useEffect, useState } from "react";

import { AiBadge } from "../../../core/ai";
import { api } from "../../../core/api/client";
import type { Job } from "../../../core/api/types";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Dialog,
  Disclosure,
  ImageFrame,
  KeyValue,
  SelectField,
  TextArea,
  useToast,
} from "../../../design-system";
import { ILLUSTRATION_TONE, type Anchor, type Catalog, type Illustration } from "./api";

const RISK: Record<string, string> = { low: "Lav", medium: "Middels", high: "Høy" };
const SCORES: [keyof Illustration["review"], string][] = [
  ["relevance", "Faglig relevans"], ["content_alignment", "Samsvar med sideinnholdet"], ["visual_quality", "Visuell kvalitet"],
  ["style_consistency", "Konsistens med emnets stil"], ["supports_learning_goal", "Støtter læringsmålet"],
];

export function IllustrationDetail({ item, catalog, onClose, onJob }: {
  item: Illustration;
  catalog: Catalog;
  onClose: () => void;
  onJob: (jobId: string) => void;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const [alt, setAlt] = useState(item.alt_text);
  const [decorative, setDecorative] = useState(item.decorative);
  const [caption, setCaption] = useState(item.caption);
  const [captionOn, setCaptionOn] = useState(item.caption_enabled);
  const [prompt, setPrompt] = useState(item.prompt);
  const [style, setStyle] = useState(item.style_override ?? "");
  const [anchorKey, setAnchorKey] = useState<string>("");
  const [showPrompt, setShowPrompt] = useState(false);
  useEffect(() => {
    setAlt(item.alt_text);
    setDecorative(item.decorative);
    setCaption(item.caption);
    setCaptionOn(item.caption_enabled);
    setPrompt(item.prompt);
    setStyle(item.style_override ?? "");
  }, [item.id, item.alt_text, item.decorative, item.caption, item.caption_enabled, item.prompt, item.style_override]);

  const refresh = () => client.invalidateQueries({ queryKey: ["illustrations"] });
  const locked = ["generating", "queued"].includes(item.status);
  const anchors = useQuery({
    queryKey: ["illustrations", "anchors", item.id],
    queryFn: () => api.get<{ anchors: Anchor[]; page_changed: boolean }>(`/api/illustrations/${item.id}/anchors`),
  });
  const fullPrompt = useQuery({
    queryKey: ["illustrations", "prompt", item.id, item.prompt, item.style_override],
    queryFn: () => api.get<{ prompt: string }>(`/api/illustrations/${item.id}/prompt-preview`),
    enabled: showPrompt,
  });
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch<Illustration>(`/api/illustrations/${item.id}`, body),
    onSuccess: async () => {
      await refresh();
      toast.show({ tone: "success", title: "Lagret" });
    },
  });
  const regenerate = useMutation({
    mutationFn: () => api.post<Job>(`/api/illustrations/${item.id}/regenerate`, { prompt, style_override: style, confirmed: true }),
    onSuccess: async (job) => {
      onJob(job.id);
      await refresh();
      onClose();
    },
  });
  const reference = useMutation({
    mutationFn: () => api.post(`/api/illustrations/${item.id}/reference`),
    onSuccess: async () => {
      await refresh();
      toast.show({ tone: "success", title: "Bildet brukes nå som stilreferanse for emnet" });
    },
  });

  const anchorOptions = (anchors.data?.anchors ?? []).map((a) => ({
    value: `${a.placement}|${a.block_index}`,
    label: `${a.placement_label}${a.section_title ? ` – «${a.section_title}»` : ""}${a.block_text ? `: «${a.block_text.slice(0, 60)}…»` : ""}`,
  }));
  const chosenAnchor = anchors.data?.anchors.find((a) => `${a.placement}|${a.block_index}` === anchorKey);
  const textChanged = alt !== item.alt_text || decorative !== item.decorative || caption !== item.caption || captionOn !== item.caption_enabled;
  const error = patch.error ?? regenerate.error ?? reference.error;
  const plan = item.plan;
  const review = item.review;

  return (
    <Dialog open onClose={onClose} variant="drawer" size="xl" title={item.plan.concept ?? "Illustrasjon"}
      description={`${item.module_name ?? ""} › ${item.page_title}`}
      footer={
        <div className="ek-cluster" data-gap="2">
          <Button variant="primary" icon={<Check aria-hidden="true" />} disabled={locked || !item.asset_id}
            onClick={() => patch.mutate({ alt_text: alt, decorative, caption, caption_enabled: captionOn, status: "approved" })} loading={patch.isPending}>
            Godkjenn
          </Button>
          <Button icon={<X aria-hidden="true" />} disabled={locked || item.status === "published"} onClick={() => patch.mutate({ status: "rejected" })}>Forkast</Button>
          <Button icon={<SkipForward aria-hidden="true" />} disabled={locked || item.status === "published"} onClick={() => patch.mutate({ status: "skipped" })}>Hopp over</Button>
          <Button variant="ghost" onClick={onClose}>Lukk</Button>
        </div>
      }>
      <div className="ek-stack" data-gap="6">
        <div className="ek-cluster" data-gap="2">
          <Badge tone={ILLUSTRATION_TONE[item.status] ?? "neutral"}>{item.status_label}</Badge>
          <AiBadge />
          {item.manual_check ? <Badge tone="warning">Manuell kontroll anbefales</Badge> : null}
        </div>
        {item.manual_check ? (
          <Alert tone="warning" title="Kontroller bildet faglig">
            {review.manual_check_reason || "Kvalitetskontrollen kunne ikke bekrefte at bildet er faglig riktig."} KI kan ikke garantere faglig korrekthet.
          </Alert>
        ) : null}
        {item.status === "staged" ? (
          <Alert tone="info">Illustrasjonen ligger i endringskøen. Endrer, forkaster eller lager du den på nytt, tas sideendringen ut av køen, og siden må publiseres på nytt.</Alert>
        ) : null}
        {item.status === "published" ? (
          <Alert tone="info">Publisert. Endrer du alt-tekst, bildetekst, plassering eller bilde, må illustrasjonen publiseres på nytt – den gamle figuren erstattes da.</Alert>
        ) : null}
        {item.error ? <Alert tone="danger">{item.error}</Alert> : null}
        {plan.skip_reason ? <Alert tone="info">{plan.skip_reason}</Alert> : null}
        {error ? <Alert tone="danger">{error.message}</Alert> : null}
        <div className="ek-split" data-align="start">
          <div className="ek-stack" data-gap="3">
            <ImageFrame src={item.image_url} alt={decorative ? "" : alt || "Generert illustrasjon"} placeholder="Ikke generert ennå"
              caption={captionOn && caption && !decorative ? caption : undefined} />
            {item.versions.length > 1 ? (
              <SelectField label="Versjon" value={item.asset_id ?? ""} disabled={locked}
                onChange={(e) => patch.mutate({ asset_id: e.target.value })}
                options={item.versions.map((v) => ({ value: v.asset_id, label: `Forsøk ${v.attempt}: ${v.verdict === "pass" ? "godkjent av kontrollen" : v.verdict}` }))} />
            ) : null}
            {item.asset_id ? (
              <div>
                <Button size="sm" icon={<Palette aria-hidden="true" />} onClick={() => reference.mutate()} loading={reference.isPending}>Bruk som stilreferanse</Button>
              </div>
            ) : null}
          </div>
          <div className="ek-stack" data-gap="3">
            <h3>Fra siden</h3>
            <p className="ek-small ek-muted">{item.placement_label}{item.section.title ? ` i «${item.section.title}»` : ""}</p>
            {item.section.before?.title ? <p className="ek-small ek-muted">Før: {item.section.before.title}</p> : null}
            <blockquote className="ek-quote">{item.section.text || "(ingen tekst)"}</blockquote>
            {item.section.after?.title ? <p className="ek-small ek-muted">Etter: {item.section.after.title}</p> : null}
            {anchors.data?.page_changed ? <Alert tone="info">Siden er endret i Canvas etter analysen. Kontroller plasseringen før publisering.</Alert> : null}
          </div>
        </div>
        <KeyValue items={[
          ["Pedagogisk formål", plan.pedagogical_purpose ?? ""],
          ["Begrep bildet skal forklare", plan.concept ?? ""],
          ["Læringsmål", plan.learning_goal ?? ""],
          ["Motiv og komposisjon", `${plan.motif ?? ""}${plan.composition ? ` – ${plan.composition}` : ""}`],
          ["Må vise", (plan.must_show ?? []).join("; ")],
          ["Må ikke fremstilles", (plan.must_not_show ?? []).join("; ")],
          ["Risiko for faglige feil", `${RISK[plan.accuracy_risk ?? "low"] ?? plan.accuracy_risk}${plan.accuracy_notes ? ` – ${plan.accuracy_notes}` : ""}`],
          ["Hva bildet tilfører", plan.adds_value ?? ""],
          ["Hvorfor her", plan.placement_reason ?? ""],
        ]} />
        {review.verdict ? (
          <Disclosure summary="Kvalitetskontroll">
            <div className="ek-stack" data-gap="2">
              <KeyValue items={[
                ...SCORES.map(([key, label]) => [label, review[key] ? `${review[key]} av 5` : "–"] as [string, string]),
                ["Tekst i bildet", review.text_in_image === "none" ? "Ingen" : review.text_in_image ?? "–"],
              ]} />
              {[...(review.incorrect_details ?? []), ...(review.issues ?? [])].length ? (
                <ul className="ek-stack" data-gap="1">
                  {[...(review.incorrect_details ?? []), ...(review.issues ?? [])].map((i) => <li key={i} className="ek-small">{i}</li>)}
                </ul>
              ) : null}
            </div>
          </Disclosure>
        ) : null}
        <div className="ek-stack" data-gap="3">
          <h3>Alternativ tekst og bildetekst</h3>
          <TextArea label="Alternativ tekst" rows={2} value={alt} disabled={decorative || locked} onChange={(e) => setAlt(e.target.value)}
            hint="Beskriver det bildet faktisk viser, kort og konkret. Gjentar ikke bildeteksten." />
          <Checkbox label="Dekorativt bilde (tom alternativ tekst, ingen bildetekst)" checked={decorative} disabled={locked}
            onChange={(e) => setDecorative(e.target.checked)} />
          <TextArea label="Bildetekst" rows={2} value={caption} disabled={!captionOn || decorative || locked} onChange={(e) => setCaption(e.target.value)}
            hint="Forklarer hvordan bildet henger sammen med fagstoffet." />
          <Checkbox label="Vis bildetekst under bildet" checked={captionOn} disabled={decorative || locked} onChange={(e) => setCaptionOn(e.target.checked)} />
          <div>
            <Button size="sm" disabled={!textChanged || locked} loading={patch.isPending}
              onClick={() => patch.mutate({ alt_text: alt, decorative, caption, caption_enabled: captionOn })}>Lagre tekstene</Button>
          </div>
        </div>
        <div className="ek-stack" data-gap="3">
          <h3>Plassering</h3>
          {anchors.isPending ? <p className="ek-small ek-muted">Henter siden …</p> : (
            <SelectField label="Endre plassering" value={anchorKey} onChange={(e) => setAnchorKey(e.target.value)} placeholder={`Nå: ${item.placement_label}`}
              options={anchorOptions} disabled={locked} />
          )}
          {chosenAnchor?.warning ? <p className="ek-small">{chosenAnchor.warning}</p> : null}
          <div>
            <Button size="sm" disabled={!chosenAnchor || locked} onClick={() => chosenAnchor && patch.mutate({ anchor: chosenAnchor })}>Bruk plasseringen</Button>
          </div>
        </div>
        <div className="ek-stack" data-gap="3">
          <h3>Bildeprompt og stil</h3>
          <TextArea label="Bildeprompt (engelsk, til bildemodellen)" rows={5} value={prompt} disabled={locked} onChange={(e) => setPrompt(e.target.value)}
            hint="Emnets designprofil, den faglige konteksten og regelen om at bildet skal være uten tekst legges til automatisk." />
          <SelectField label="Bildestil for dette bildet" value={style} disabled={locked} onChange={(e) => setStyle(e.target.value)}
            options={[{ value: "", label: "Emnets designprofil" }, ...catalog.styles.filter((s) => s.key !== "custom").map((s) => ({ value: s.key, label: s.label }))]} />
          <div className="ek-cluster" data-gap="2">
            <Button icon={<RefreshCw aria-hidden="true" />} disabled={locked} loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
              Generer på nytt
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setShowPrompt((v) => !v)}>{showPrompt ? "Skjul hele prompten" : "Vis hele prompten"}</Button>
          </div>
          <p className="ek-small ek-muted">«Generer på nytt» sender bildeprompten til bildemodellen og det nye bildet til kvalitetskontrollen, som ved første generering.</p>
          {showPrompt && fullPrompt.data ? <pre className="ek-code-block">{fullPrompt.data.prompt}</pre> : null}
        </div>
      </div>
    </Dialog>
  );
}
