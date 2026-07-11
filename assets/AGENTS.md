# assets

## Purpose

Reproducible Irigate brand assets derived from the visual language of the sibling Talaria project.

## Ownership

- `build_logo.py` is the single source of truth for glyph geometry, colors, lockup composition, and raster export.
- `logo.svg` is the horizontal Iris-gate mark and IRIGATE wordmark lockup.
- `logo-mark.svg` is the standalone project glyph.
- `logo-{256,512,1024}.png` are derived transparent lockup exports.

## Local Contracts

- The glyph combines a six-petal Greek iris with an arched negative-space gate, representing Iris as messenger and Irigate as a local MCP gateway.
- The mark is distinct from Talaria's winged-sandal silhouette while retaining its visual family: smooth vector paths, bold Georgia serif wordmark, transparent background, gold `#ffc72c`, and amber `#f9a23a` lower band.
- The amber band is a clipped overlay of the glyph and wordmark geometry, never an unclipped background rectangle; transparent gaps between and within shapes remain transparent.
- Source SVGs and PNGs are generated artifacts; do not hand-edit them.
- Raster exports must preserve transparency and the lockup aspect ratio.

## Work Guidance

- Change geometry or composition only in `build_logo.py`.
- Keep exact text out of generated imagery except for the IRIGATE wordmark and accessible SVG title/description.

## Verification

- Run `python3 assets/build_logo.py` from the repository root.
- Run the generator twice and confirm all generated asset hashes are unchanged.
- Visually inspect `logo-1024.png`: the full wordmark must be visible, the amber bands must align without appearing in transparent gaps, and the glyph must read as an Iris flower with a gate opening.

## Child DOX Index

None.
