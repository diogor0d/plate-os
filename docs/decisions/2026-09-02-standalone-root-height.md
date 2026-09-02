# Standalone Root Height

**Date:** 2026-09-02T23:33:18+01:00  
**Status:** Accepted and implemented  
**Decision:** D45, refining D44

## Context

D44 stabilized the installed iOS PWA navigation by using a mobile flex shell and
removing viewport-fixed positioning. On physical iPhones, `100dvh` still left a
stable blank region below that shell matching Safari's toolbar allowance, even
though standalone mode has no browser toolbar. The same build filled the viewport
correctly inside Safari.

## Decision

The mobile shell continues to use `100dvh` in browser mode. Under
`display-mode: standalone`, it uses `height: 100%` from the existing full-height
`html`, `body`, and `#root` chain instead. Safe-area padding remains on the
navigation for the home indicator.

## Consequences

- Standalone mode fills the actual root surface rather than a stale
  toolbar-adjusted dynamic viewport.
- Safari retains dynamic viewport behavior as its browser chrome expands and
  collapses.
- The home-indicator safe area is intentionally preserved and is not considered
  browser-toolbar whitespace.
