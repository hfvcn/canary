const TERMINAL_FONT_FAMILIES = [
  '"JetBrainsMono Nerd Font Mono"',
  '"JetBrainsMono Nerd Font"',
  '"FiraCode Nerd Font Mono"',
  '"FiraCode Nerd Font"',
  '"MesloLGS NF"',
  '"Hack Nerd Font Mono"',
  '"CaskaydiaMono Nerd Font"',
  '"CaskaydiaCove Nerd Font Mono"',
  '"SauceCodePro Nerd Font Mono"',
  '"JetBrains Mono"',
  '"Fira Code"',
  '"SF Mono"',
  "Menlo",
  "Monaco",
  '"DejaVu Sans Mono"',
  '"Liberation Mono"',
  '"Noto Sans Mono"',
  '"Symbols Nerd Font Mono"',
  '"Symbols Nerd Font"',
  '"PowerlineSymbols"',
  "monospace",
];

// Prompts rendered in browser PTYs often use Nerd Font / Powerline glyphs from the
// private use area. Keep patched mono fonts ahead of plain coding fonts, then fall
// back to symbol fonts before the generic monospace family.
export const DEFAULT_TERMINAL_FONT_FAMILY = TERMINAL_FONT_FAMILIES.join(", ");
