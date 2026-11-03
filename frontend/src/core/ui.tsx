// App-wide UI state: the global analysis dialog and the change-set drawer can
// be opened from anywhere (header, overview cards, feature pages).
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export interface AnalysisPreset {
  domains?: ("accessibility" | "content_quality" | "structure" | "quiz")[];
  scope?: "course" | "modules" | "items";
}

interface UiState {
  analysisOpen: boolean;
  analysisPreset: AnalysisPreset | null;
  openAnalysis: (preset?: AnalysisPreset) => void;
  closeAnalysis: () => void;
  changesOpen: boolean;
  openChanges: () => void;
  closeChanges: () => void;
  watchedJobId: string | null;
  watchJob: (jobId: string | null) => void;
}

const UiContext = createContext<UiState | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const [analysisOpen, setAnalysisOpen] = useState(false);
  const [analysisPreset, setAnalysisPreset] = useState<AnalysisPreset | null>(null);
  const [changesOpen, setChangesOpen] = useState(false);
  const [watchedJobId, setWatchedJobId] = useState<string | null>(null);

  const openAnalysis = useCallback((preset?: AnalysisPreset) => {
    setAnalysisPreset(preset ?? null);
    setAnalysisOpen(true);
  }, []);
  const value = useMemo<UiState>(
    () => ({
      analysisOpen,
      analysisPreset,
      openAnalysis,
      closeAnalysis: () => setAnalysisOpen(false),
      changesOpen,
      openChanges: () => setChangesOpen(true),
      closeChanges: () => setChangesOpen(false),
      watchedJobId,
      watchJob: setWatchedJobId,
    }),
    [analysisOpen, analysisPreset, openAnalysis, changesOpen, watchedJobId],
  );
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}

export function useUi(): UiState {
  const value = useContext(UiContext);
  if (!value) throw new Error("useUi must be used inside <UiProvider>");
  return value;
}
