export const TERMINAL_FONT_SIZE = 13;
export const TERMINAL_LINE_HEIGHT = 1;
export const TERMINAL_LETTER_SPACING = 0;

type FontReadyDocumentLike = {
  fonts?: {
    ready?: Promise<unknown>;
  };
};

type TextureAtlasTerminalLike = {
  clearTextureAtlas?: () => void;
};

type FitAddonLike = {
  fit: () => void;
};

// xterm.js caches cell metrics early. If the preferred font finishes loading later,
// trigger one extra atlas/layout refresh so the terminal re-measures with final glyph metrics.
export function relayoutTerminalAfterFontsReady(
  doc: FontReadyDocumentLike | null | undefined,
  term: TextureAtlasTerminalLike,
  fitAddon: FitAddonLike,
  canFit: () => boolean,
): () => void {
  let cancelled = false;
  const ready = doc?.fonts?.ready;
  if (!ready || typeof (ready as Promise<unknown>).then !== "function") {
    return () => {
      cancelled = true;
    };
  }

  void ready.then(() => {
    if (cancelled || !canFit()) return;
    try {
      term.clearTextureAtlas?.();
    } catch {
      // Ignore best-effort renderer refresh failures and still attempt a layout fit.
    }
    fitAddon.fit();
  }).catch(() => {
    // Ignore font-loading failures and keep the initial terminal metrics.
  });

  return () => {
    cancelled = true;
  };
}
