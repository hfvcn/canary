import { describe, expect, it, vi } from "vitest";

import {
  TERMINAL_FONT_SIZE,
  TERMINAL_LETTER_SPACING,
  TERMINAL_LINE_HEIGHT,
  relayoutTerminalAfterFontsReady,
} from "./terminalRendering";

describe("terminalRendering", () => {
  it("pins terminal cell metrics to stable defaults", () => {
    expect(TERMINAL_FONT_SIZE).toBe(13);
    expect(TERMINAL_LINE_HEIGHT).toBe(1);
    expect(TERMINAL_LETTER_SPACING).toBe(0);
  });

  it("relayouts once fonts are ready", async () => {
    let resolveReady: (() => void) | null = null;
    const ready = new Promise<void>((resolve) => {
      resolveReady = resolve;
    });
    const clearTextureAtlas = vi.fn();
    const fit = vi.fn();

    relayoutTerminalAfterFontsReady(
      { fonts: { ready } },
      { clearTextureAtlas },
      { fit },
      () => true,
    );

    resolveReady?.();
    await ready;
    await Promise.resolve();

    expect(clearTextureAtlas).toHaveBeenCalledTimes(1);
    expect(fit).toHaveBeenCalledTimes(1);
  });

  it("does nothing after cleanup", async () => {
    let resolveReady: (() => void) | null = null;
    const ready = new Promise<void>((resolve) => {
      resolveReady = resolve;
    });
    const clearTextureAtlas = vi.fn();
    const fit = vi.fn();

    const cleanup = relayoutTerminalAfterFontsReady(
      { fonts: { ready } },
      { clearTextureAtlas },
      { fit },
      () => true,
    );

    cleanup();
    resolveReady?.();
    await ready;
    await Promise.resolve();

    expect(clearTextureAtlas).not.toHaveBeenCalled();
    expect(fit).not.toHaveBeenCalled();
  });
});
