# Add Official Generic-Food Catalogues

**Date:** 2026-09-12T00:20:00+01:00

**Status:** Accepted and implemented

**Decision:** D52

## Context

Open Food Facts is useful for packaged products with retail barcodes but does not
provide dependable coverage for generic ingredients. PlateOS needs broader food
search useful to a household in Portugal without credentials, paid API plans,
undocumented scraping, or ambiguous reuse rights. External results must remain
proposals and must not bypass reviewed-product or meal confirmation boundaries.

## Decision

Add explicit generic-food search backed by compact snapshots of two official open
datasets:

- Anses Ciqual 2025 (`2025-11-19`), under Licence Ouverte / Etalab 2.0.
- Livsmedelsverkets Livsmedelsdatabas (`2026-07-01`), under CC BY 4.0.

The standard-library generator consumes official bulk releases, keeps official
record identifiers, embeds input SHA-256 checksums and attribution metadata, and
emits only English/French or English/Swedish names plus the five PlateOS nutrients.
Qualified, missing, negative, or out-of-contract values are excluded rather than
imputed, clamped, or silently treated as zero. The resulting snapshots contain
2,855 Ciqual and 2,605 Swedish records.

`GET /api/food-items/candidates/search` searches one explicitly selected source
at a time. Search is local and read-only; it does not run automatically after a
local-library miss. Results receive the same short-lived account-bound HMAC proof
as barcode and vision candidates and enter the existing editable review and
Proposal Card flow.

Migration `0007` adds nullable `nutrition_source_id` and
`nutrition_source_version` fields to accepted products and aligns product density
storage with the four-decimal candidate and meal-snapshot contract. Official catalogue
candidates require both fields, and the proof binds them with source, name,
nutrition, barcode, brand, and serving unit. Editing a candidate before acceptance
downgrades it to manual provenance. Meal acquisition source remains `manual` for
generic catalogue products; product-level provenance remains available through
the linked `food_item_id` without expanding analytics source semantics.
Editing an accepted external product downgrades it to manual provenance so changed
values cannot continue to claim an exact official record.

## Consequences

- Generic-food search works without runtime third-party credentials or provider
  availability and adds roughly 1 MB to the API image.
- Dataset refreshes are intentional code changes with reviewable checksums and
  record diffs rather than unbounded live upstream behavior.
- Accepted products retain the exact upstream record and release identifiers.
- Agency attribution and licenses are visible in the review/library UI and
  documented in `docs/data-sources.md`.
- Source updates require regeneration, tests, application deployment, and a new
  migration only if the persisted provenance contract itself changes.

## Rejected Alternatives

- Runtime Swedish API fan-out was rejected because name search requires fetching
  the full list and nutrient details are one request per food.
- Undocumented Ciqual website endpoints and third-party mirrors were rejected in
  favor of the official versioned bulk release.
- Automatically merging source values or falling back after a barcode miss was
  rejected because conflicts would become silent and provenance ambiguous.
- Importing source rows directly into the accepted product library was rejected;
  every external candidate still requires explicit review.
- PortFIR was not added because suitable machine-readable reuse permission was
  not established.
