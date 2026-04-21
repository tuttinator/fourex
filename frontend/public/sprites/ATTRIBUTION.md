# Sprite Attribution

All sprite assets in this directory are original hand-drawn SVG pixel art
created for the Parley (fourex) project and released under the
[Creative Commons CC0 1.0 Universal (Public Domain Dedication)](LICENSE.txt)
licence. Attribution is not required.

## Current contents

| File | Subject | Size |
| --- | --- | --- |
| `terrain-plains.svg`   | Plains terrain tile     | 32×32 |
| `terrain-forest.svg`   | Forest terrain tile     | 32×32 |
| `terrain-mountain.svg` | Mountain terrain tile   | 32×32 |
| `terrain-water.svg`    | Water terrain tile      | 32×32 |
| `resource-food.svg`    | Food resource indicator | 16×16 |
| `resource-wood.svg`    | Wood resource indicator | 16×16 |
| `resource-ore.svg`     | Ore resource indicator  | 16×16 |
| `resource-crystal.svg` | Crystal resource icon   | 16×16 |

## Swapping in a different pack

The sprite-resolver module
(`frontend/src/lib/sprite-atlas.ts`) maps each
`Terrain` / `Resource` enum value to an asset URL, so a drop-in swap
only requires replacing the files here and updating those URLs — no
render-layer changes needed. If the replacement pack is Kenney.nl
(CC0) or a similar CC-BY source, retain their `LICENSE.txt` verbatim
alongside this file and extend the table above.
