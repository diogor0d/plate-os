# Label Package Quantity and Barcode Enrichment

**Date:** 2026-09-03T01:52:48+01:00

**Status:** Accepted and implemented

**Decision:** D47

## Context

Vision label parsing normalized nutrition density to per 100 g/ml but discarded
printed serving and package quantities, so every resulting proposal defaulted to
100. Small single-unit products such as yogurt therefore required avoidable
manual quantity edits. A label-derived draft also allowed barcode text entry but
could not invoke the camera scanner without clearing the extracted values; manual
barcode edits intentionally invalidated the candidate proof.

## Decision

The vision contract extracts the printed nutrition reference unit and optional
net package number/unit. It does not convert units or calculate multipack totals.
`backend/app/services/nutrition.py` converts `kg/L` to the app's shared `g/ml`
quantity scale and falls back to an explicit serving size when net quantity is
absent. The resulting non-persistent `suggested_quantity_g` initializes the
editable Proposal Card; confirmation remains mandatory.

Label-derived drafts expose a barcode scan control. A dedicated authenticated
endpoint verifies the original short-lived candidate proof and returns a new
proof bound to the detected barcode. It does not query Open Food Facts or persist
a product or meal. If the draft changes while binding is in flight, the client
discards the stale result.

## Constraints

- Net mass units are accepted only with gram-based nutrition density; net volume
  units are accepted only with milliliter-based density.
- Converted package quantity must remain within the existing 10,000 g/ml proposal
  limit.
- Multipack multiplication remains user-reviewed rather than model-computed.
- Photos can leave the host when the configured vision provider is remote.

## Consequences

- A 125 g yogurt label can open at 125 g while retaining per-100 nutrition.
- A per-100 ml product keeps `ml` in the editable quantity control.
- Barcode enrichment preserves vision provenance without a second LLM request.
- The API surface gains `POST /api/food-items/candidates/bind-barcode`.
