# Five-batch integration report

## Baseline and result

- Base `main`: `f377f1c0b9605c36f98706662d9fd987bd6fdacb`
- Working branch: `agent/integrate-five-asset-batches`
- Repository bytes before / after: 90476367 / 655430362
- Previous asset count: 410
- Final asset count: 3604
- Final index count: 3604
- Final checksum count: 3604

## Batch results

| Batch | Supplied | Accepted | Rejected | Integrated bytes |
| --- | ---: | ---: | ---: | ---: |
| architecture-002 | 991 | 991 | 0 | 177365282 |
| movement-001 | 74 | 74 | 0 | 48989652 |
| lighting-001 | 656 | 656 | 0 | 248080632 |
| uiux-001 | 835 | 835 | 0 | 14536917 |
| vfx-001 | 638 | 638 | 0 | 70998906 |

Final category totals: architecture 1401, movement 74, lighting 656, UI/UX 835, VFX 638.

## Audit and repair

- Duplicate IDs: 0
- Exact duplicate logical assets removed: 0
- Exact duplicate shared binaries removed: 15 (24886414 bytes)
- Logical duplicates against current TKRS removed: 0
- Missing/broken dependency references repaired: 280
- Missing or empty source dependencies recovered from official CC0 sources: 29
- Near-duplicate groups reviewed: 3; retained as useful opposite exposure variants and white/black input-prompt families
- Missing dependencies after repair: 0
- Malformed metadata JSON: 0
- Metadata schema errors: 0
- Unlicensed accepted assets: 0
- Accepted executables/installers: 0
- Symlinks/path traversal: 0
- Empty accepted files: 0
- Files over 100 MB: 0
- Inert licensed code-reference files: 25; none were executed

## Largest files

| Path | Bytes |
| --- | ---: |
| `assets/lighting/street/fix-khronos-lantern/Lantern.glb` | 9564264 |
| `assets/architecture/exteriors/arch_exteriors_32kda-warehouse_001/model.glb` | 6468896 |
| `assets/movement/climb/mov-m2m-human-addon/human-addon-animations.glb` | 5292804 |
| `assets/movement/special/mov-kaykit-skeleton-warrior-library/Skeleton_Warrior.glb` | 4863620 |
| `textures/quaternius-medieval-village-megakit-standard/t-plaster-normal-8b9617b561466cce.png` | 4607606 |

## Gates

- `python tools/validate_repository.py`: PASS
- `python -m unittest discover -s tests -v`: PASS (10 tests)
- Representative category searches: PASS
- Index count equals accepted asset directory count: PASS
