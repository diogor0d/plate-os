# Validate Retail Barcodes Before Lookup

**Date:** 2026-09-03T02:08:00+01:00

**Status:** Accepted and implemented

**Decision:** D48

## Context

The iOS ZXing fallback used its unrestricted multi-format reader while the native
BarcodeDetector path requested a narrower set. Production evidence showed the
only recent Open Food Facts lookup used `50046977`, which is absent upstream and
does not have a valid EAN-8 check digit. The production API itself successfully
resolved known Open Food Facts products, so this was a scanner false positive
rather than an upstream-connectivity failure.

Successful Open Food Facts requests also downloaded complete product documents
of roughly 150-185 KB although PlateOS uses only the name, brands, and nutriments.

## Decision

Both camera implementations accept only EAN-8, EAN-13, and UPC-A. PlateOS
independently verifies the numeric length and GTIN check digit before invoking a
lookup. Invalid detections are ignored so the camera can continue looking for a
valid product code.

Open Food Facts requests use its `fields` query parameter to request only
`product_name`, `brands`, and `nutriments`. The authoritative-hit, miss, and
upstream-error semantics remain unchanged.

## Consequences

- Code 128 and other non-retail marks can no longer become false product lookups.
- UPC-E is not camera-scanned because validating or expanding it requires its
  symbology metadata, which is not consistently exposed by both browser paths.
- Manually entered barcodes remain available for exceptional cases.
- Smaller OFF responses reduce bandwidth and parsing work without adding a cache
  or changing persistence behavior.
