// «Tittel på innebygd innhold» for a YouTube video: the title comes in the same order as in «Standardiser
// videoavspillere» – the video's own title from YouTube, then the page around the video – and a KI-forslag only when
// the teacher asks for it (after seeing what is sent). When YouTube or the page already gives a title, KI is an
// optional comparison («Se hva KI foreslår»), never the default. The text field stays the teacher's: a suggestion only fills it
// while it still holds the starting text.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";

import { api } from "../../core/api/client";
import type { Finding } from "../../core/api/types";
import { useCurrentCourse } from "../../core/course";
import { Button, Spinner } from "../../design-system";
import { AiSuggestion, type AiTextPlan } from "./AiSuggestion";

interface VideoRef {
  object_type: string;
  object_id: string;
  object_title: string;
  video_id: string;
  occurrence: number;
}

export interface VideoTitle {
  available: boolean;
  reason?: string;
  title?: string | null;
  source?: "existing" | "youtube_metadata" | "page_context" | null;
  source_label?: string | null;
  hint?: string | null;
  metadata_message?: string | null;
  ai_possible?: boolean;
  /** Not a YouTube video: the general «Foreslå tittel med KI» is used instead. */
  not_video?: boolean;
  ref?: VideoRef;
}

interface AiTitle {
  title: string;
  source_label: string;
  provider?: string;
  model?: string;
}

const PROVIDER_NAMES: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic", azure: "Azure OpenAI", local: "lokal modell" };

export function VideoTitleSuggestion({ finding, text, setText, initial, onAiText, fallback }: {
  finding: Finding;
  text: string;
  setText: (value: string) => void;
  /** The text the field started with – a suggestion only replaces that, never what the teacher wrote. */
  initial: string;
  onAiText?: (text: string) => void;
  /** Shown instead for embedded content that is not a YouTube video. */
  fallback?: ReactNode;
}) {
  const { courseId: current } = useCurrentCourse();
  const courseId = finding.course_id ?? current;
  const suggestion = useQuery({
    queryKey: ["finding-video-title", finding.id],
    queryFn: () => api.get<VideoTitle>(`/api/findings/${finding.id}/video-title`),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const filled = useRef(false);

  useEffect(() => {
    const title = suggestion.data?.title;
    if (title && !filled.current && text === initial) {
      filled.current = true;
      setText(title);
    }
  }, [suggestion.data, text, initial, setText]);

  if (suggestion.isPending) return <Spinner label="Henter videoens tittel fra YouTube …" />;
  if (suggestion.error) return <>{fallback}</>;
  const data = suggestion.data;
  if (!data.available) {
    if (data.not_video) return <>{fallback}</>;
    return data.reason ? <p className="ek-small ek-muted">{data.reason}</p> : null;
  }
  const ref = data.ref;
  // The teacher asks explicitly, so a good title from YouTube does not block the comparison.
  const aiRef = ref ? { ...ref, even_with_title: true } : undefined;
  const showsSuggestion = Boolean(data.title) && text === data.title;
  return (
    <div className="ek-stack" data-gap="2">
      {showsSuggestion ? (
        <p className="ek-small"><span className="ek-strong">Kilde: {data.source_label}.</span> {data.hint}</p>
      ) : data.title ? (
        <p className="ek-small ek-muted">Forslaget var «{data.title}» ({data.source_label}).{" "}
          <Button variant="link" size="sm" onClick={() => setText(data.title!)}>Bruk forslaget</Button>
        </p>
      ) : null}
      {data.metadata_message ? <p className="ek-small ek-muted">{data.metadata_message}</p> : null}
      {aiRef ? (
        <AiSuggestion label={data.ai_possible ? "Foreslå tittel med KI" : "Se hva KI foreslår"} findingId={finding.id}
          text={text} setText={setText} initial={[initial, ...(data.title ? [data.title] : [])]} onSuggested={onAiText}
          prepare={async () => ({
            ...(await api.post<AiTextPlan>(`/api/courses/${courseId}/videos/title-suggestion/prepare`, aiRef)),
            task: "video_title",
            basis: "Grunnlag: YouTube-tittelen (hvis kjent), sidetittelen og teksten rundt videoen.",
          })}
          run={async (confirmed) => {
            const answer = await api.post<AiTitle>(`/api/courses/${courseId}/videos/title-suggestion`, { ...aiRef, confirmed });
            return { text: answer.title, model: answer.model, provider: answer.provider,
              provider_name: answer.provider ? PROVIDER_NAMES[answer.provider] ?? answer.provider : undefined,
              basis: "Grunnlag: YouTube-tittelen (hvis kjent), sidetittelen og teksten rundt videoen." };
          }} />
      ) : null}
    </div>
  );
}
