// 8-player heraldic palette — picked for max discriminability on
// green/blue/gray/sand terrain and pairwise CB safety. Each entry has
// an `ink` pair for text on swatches and a `soft` pair for badges.

export interface PlayerColor {
  id: string;
  name: string;
  hue: number;
  hex: string;
}

export const PLAYER_PALETTE: readonly PlayerColor[] = [
  { id: "crimson", name: "Crimson", hue: 22, hex: "#B5302E" },
  { id: "indigo", name: "Indigo", hue: 265, hex: "#3D3F8F" },
  { id: "ochre", name: "Ochre", hue: 78, hex: "#C49A2C" },
  { id: "forest", name: "Forest", hue: 155, hex: "#2E6E4D" },
  { id: "plum", name: "Plum", hue: 340, hex: "#7E2D52" },
  { id: "teal", name: "Teal", hue: 200, hex: "#1F6F87" },
  { id: "slate", name: "Slate", hue: 250, hex: "#4A5568" },
  { id: "ember", name: "Ember", hue: 38, hex: "#C7541C" },
] as const;

export function playerColorByIndex(i: number): PlayerColor {
  return PLAYER_PALETTE[i % PLAYER_PALETTE.length];
}

export function playerColorById(id: string): PlayerColor | undefined {
  return PLAYER_PALETTE.find((p) => p.id === id);
}
