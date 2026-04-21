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
| `unit-scout.svg`       | Scout unit              | 32×32 |
| `unit-worker.svg`      | Worker unit             | 32×32 |
| `unit-soldier.svg`     | Soldier unit            | 32×32 |
| `unit-archer.svg`      | Archer unit             | 32×32 |
| `unit-banner.svg`      | Per-player tint frame for units (white; tinted at render) | 32×32 |
| `city-outpost.svg`     | City variant — frontier outpost (0–1 buildings, no walls) | 32×32 |
| `city-town.svg`        | City variant — two-building town (no walls)               | 32×32 |
| `city-fortress.svg`    | City variant — walled fortress (walls ∈ buildings)        | 32×32 |
| `city-banner.svg`      | Per-player tint frame for cities (white; tinted at render) | 32×32 |
| `building-granary.svg` | Granary indicator                                         | 10×10 |
| `building-barracks.svg`| Barracks indicator                                        | 10×10 |
| `building-walls.svg`   | Walls indicator                                           | 10×10 |
| `building-monument.svg`| Monument indicator                                        | 10×10 |
| `building-library.svg` | Library indicator                                         | 10×10 |
| `building-temple.svg`  | Temple indicator                                          | 10×10 |
| `improvement-farm.svg` | Farm worker improvement                                   | 20×20 |
| `improvement-mine.svg` | Mine worker improvement                                   | 20×20 |
| `improvement-lumber-mill.svg`       | Lumber-mill worker improvement               | 20×20 |
| `improvement-crystal-extractor.svg` | Crystal-extractor worker improvement         | 20×20 |

## Swapping in a different pack

The sprite-resolver module
(`frontend/src/lib/sprite-atlas.ts`) maps each
`Terrain` / `Resource` enum value to an asset URL, so a drop-in swap
only requires replacing the files here and updating those URLs — no
render-layer changes needed. If the replacement pack is Kenney.nl
(CC0) or a similar CC-BY source, retain their `LICENSE.txt` verbatim
alongside this file and extend the table above.
