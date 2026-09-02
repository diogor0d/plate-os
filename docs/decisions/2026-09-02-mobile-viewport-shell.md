# Mobile Viewport Shell

**Date:** 2026-09-02T23:11:08+01:00  
**Status:** Accepted and implemented  
**Decision:** D44

## Context

The mobile bottom navigation used `position: fixed`. In an installed iOS PWA,
switching among pages of different heights moved the entire bar vertically even
though the same pages rendered correctly in a Safari tab. Resetting document
scroll before switching tabs did not resolve the standalone visual-viewport
behavior.

## Decision

Below the desktop breakpoint, PlateOS uses a `100dvh` flex app shell with
overflow hidden. The content pane is the only vertically scrolling region, and
the bottom navigation is a non-scrolling, normal-flow sibling with safe-area
padding. Desktop keeps natural document scrolling.

Sticky mobile controls use the bottom of the content pane because the navigation
now occupies its own layout row rather than overlaying content.

## Consequences

- Page content height and retained scroll offsets cannot change the navbar row's
  position.
- Mobile components that need sticky positioning must target the content pane,
  not compensate for a viewport-fixed navbar.
- The shell uses dynamic viewport units so the usable height follows iOS viewport
  changes, including the on-screen keyboard.

## Rejected Alternatives

- Additional per-page or per-icon offsets treat symptoms and cannot stabilize the
  whole bar.
- Keeping viewport-fixed navigation with scroll resets still depends on iOS's
  standalone fixed-position behavior.
