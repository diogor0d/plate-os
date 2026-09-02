# Standalone Large Viewport

**Date:** 2026-09-02T23:45:46+01:00  
**Status:** Accepted and implemented  
**Decision:** D46, superseding D45's standalone height value

## Context

D45 changed the installed mobile shell from `100dvh` to the root's `100%`
height. A physical-device screenshot from the identified `8c3357e` release
showed that the root inherited the same toolbar-shortened viewport: the stable
navigation row ended approximately one Safari-toolbar height above the physical
bottom. Safe-area padding then correctly reserved the separate home-indicator
inset inside the row.

## Decision

Browser mode continues to use `100dvh`, where dynamic browser chrome matters.
Installed standalone mode uses `100lvh`, representing the toolbar-free large
viewport. The bottom safe-area inset remains unchanged.

## Consequences

- The installed shell includes the area iOS otherwise reserves for Safari's
  absent toolbar.
- Navigation still remains a normal-flow shell row and cannot move with page
  height.
- The legitimate home-indicator clearance remains inside the navigation row.
