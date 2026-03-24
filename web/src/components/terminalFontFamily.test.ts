import { describe, expect, it } from "vitest";

import { DEFAULT_TERMINAL_FONT_FAMILY } from "./terminalFontFamily";

describe("DEFAULT_TERMINAL_FONT_FAMILY", () => {
  it("prefers patched Nerd Font families before plain coding fonts", () => {
    expect(DEFAULT_TERMINAL_FONT_FAMILY).toContain('"JetBrainsMono Nerd Font Mono"');
    expect(DEFAULT_TERMINAL_FONT_FAMILY).toContain('"JetBrains Mono"');
    expect(
      DEFAULT_TERMINAL_FONT_FAMILY.indexOf('"JetBrainsMono Nerd Font Mono"'),
    ).toBeLessThan(DEFAULT_TERMINAL_FONT_FAMILY.indexOf('"JetBrains Mono"'));
  });

  it("includes fallback families for prompt symbols and safe generic monospace", () => {
    expect(DEFAULT_TERMINAL_FONT_FAMILY).toContain('"Symbols Nerd Font Mono"');
    expect(DEFAULT_TERMINAL_FONT_FAMILY).toContain('"PowerlineSymbols"');
    expect(DEFAULT_TERMINAL_FONT_FAMILY.endsWith("monospace")).toBe(true);
  });
});
