import { describe, expect, it } from "vitest";

import { deriveObservabilityState } from "./useObservabilityStore";

describe("deriveObservabilityState", () => {
  it("maps terminal UI font preferences from observability settings", () => {
    const state = deriveObservabilityState({
      developer_mode: true,
      log_level: "debug",
      terminal_transcript: {
        per_actor_bytes: 6 * 1024 * 1024,
      },
      terminal_ui: {
        scrollback_lines: 12000,
        font_family: 'ui-monospace, "SF Mono", monospace',
        font_size: 15,
        line_height: 1.1,
        letter_spacing: 1,
      },
    });

    expect(state.terminalScrollbackLines).toBe(12000);
    expect(state.terminalFontFamily).toBe('ui-monospace, "SF Mono", monospace');
    expect(state.terminalFontSize).toBe(15);
    expect(state.terminalLineHeight).toBe(1.1);
    expect(state.terminalLetterSpacing).toBe(1);
  });
});
