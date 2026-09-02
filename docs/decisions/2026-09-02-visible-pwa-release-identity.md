# Visible PWA Release Identity

**Date:** 2026-09-02T22:54:55+01:00  
**Status:** Accepted and implemented

## Context

iOS can keep an installed PWA shell active after the server has deployed newer
assets. Without visible build metadata, device reports cannot distinguish a
current rendering defect from an older service-worker-controlled shell.

## Decision

The production web image passes the existing immutable `PLATEOS_IMAGE_TAG` build
value into Vite as `VITE_PLATEOS_VERSION`. The mobile header displays the first
seven characters and exposes the full value as its title. Workstation builds
without an image tag display `dev`.

This value is public release metadata, not runtime configuration or a secret.

## Consequences

- Device screenshots identify the active application release directly.
- A missing badge or an older value proves that the installed PWA has not
  activated the current shell.
- Every production web image must continue to be built with the immutable image
  tag already required by the deployment runbook.

## Rejected Alternatives

- A manually maintained package version can drift from the deployed source.
- An API-reported version identifies the server but not the cached frontend shell.
