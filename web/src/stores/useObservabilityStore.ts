// Global observability settings store (developer mode + terminal buffers).
import { create } from "zustand";
import * as apiClient from "../services/api";
import type { Observability } from "../services/api";
import { DEFAULT_TERMINAL_FONT_FAMILY } from "../components/terminalFontFamily";
import {
  TERMINAL_FONT_SIZE,
  TERMINAL_LETTER_SPACING,
  TERMINAL_LINE_HEIGHT,
} from "../components/terminalRendering";

const DEFAULT_SCROLLBACK_LINES = 8000;
const DEFAULT_PTY_BACKLOG_MIB = 10;

interface ObservabilityState {
  loaded: boolean;
  developerMode: boolean;
  logLevel: "INFO" | "DEBUG";
  terminalBacklogMiB: number;
  terminalScrollbackLines: number;
  terminalFontFamily: string;
  terminalFontSize: number;
  terminalLineHeight: number;
  terminalLetterSpacing: number;

  setFromObs: (obs: Observability) => void;
  load: () => Promise<void>;
}

export const deriveObservabilityState = (obs: Observability) => {
  const lvl = String(obs.log_level || "INFO").toUpperCase();
  const perActorBytes = Number(obs.terminal_transcript?.per_actor_bytes || 0);
  const scrollbackLines = Number(obs.terminal_ui?.scrollback_lines || 0);
  const fontFamily = String(obs.terminal_ui?.font_family || "").trim();
  const fontSize = Number(obs.terminal_ui?.font_size || 0);
  const lineHeight = Number(obs.terminal_ui?.line_height || 0);
  const letterSpacing = Number(obs.terminal_ui?.letter_spacing);
  return {
    loaded: true,
    developerMode: Boolean(obs.developer_mode),
    logLevel: (lvl === "DEBUG" ? "DEBUG" : "INFO") as "INFO" | "DEBUG",
    terminalBacklogMiB: Number.isFinite(perActorBytes) && perActorBytes > 0
      ? Math.max(1, Math.round(perActorBytes / (1024 * 1024)))
      : DEFAULT_PTY_BACKLOG_MIB,
    terminalScrollbackLines: Number.isFinite(scrollbackLines) && scrollbackLines > 0
      ? Math.max(1000, Math.round(scrollbackLines))
      : DEFAULT_SCROLLBACK_LINES,
    terminalFontFamily: fontFamily || DEFAULT_TERMINAL_FONT_FAMILY,
    terminalFontSize: Number.isFinite(fontSize) && fontSize > 0
      ? Math.max(8, Math.min(32, Math.round(fontSize)))
      : TERMINAL_FONT_SIZE,
    terminalLineHeight: Number.isFinite(lineHeight) && lineHeight > 0
      ? Math.max(0.8, Math.min(2, lineHeight))
      : TERMINAL_LINE_HEIGHT,
    terminalLetterSpacing: Number.isFinite(letterSpacing)
      ? Math.max(-2, Math.min(5, Math.round(letterSpacing)))
      : TERMINAL_LETTER_SPACING,
  };
};

export const useObservabilityStore = create<ObservabilityState>((set) => ({
  loaded: false,
  developerMode: false,
  logLevel: "INFO",
  terminalBacklogMiB: DEFAULT_PTY_BACKLOG_MIB,
  terminalScrollbackLines: DEFAULT_SCROLLBACK_LINES,
  terminalFontFamily: DEFAULT_TERMINAL_FONT_FAMILY,
  terminalFontSize: TERMINAL_FONT_SIZE,
  terminalLineHeight: TERMINAL_LINE_HEIGHT,
  terminalLetterSpacing: TERMINAL_LETTER_SPACING,

  setFromObs: (obs) => {
    set(deriveObservabilityState(obs));
  },

  load: async () => {
    try {
      const resp = await apiClient.fetchObservability();
      if (resp.ok && resp.result?.observability) {
        set(deriveObservabilityState(resp.result.observability));
        return;
      }
      if (resp.error?.code !== "permission_denied") {
        console.error(
          "Failed to load observability settings:",
          resp.error?.message || resp.error?.code || "unknown error"
        );
      }
    } catch (e) {
      console.error("Failed to load observability settings:", e);
    }
    set({ loaded: true });
  },
}));
