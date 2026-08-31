# Decision Record — Desktop Navigation Shell

- **Occurred:** 2026-08-31 (desktop experience review)
- **Documented:** 2026-08-31 (Europe/Lisbon)
- **Verified:** 2026-08-31 — see [Evidence](#evidence)
- **Status:** Implemented; supersedes the desktop navigation-rail portion of D36
- **Recall tags:** PlateOS, desktop, responsive navigation, header, D37

## D37 — Horizontal desktop control deck, mobile-only bottom navigation

**Context.** D36 added a desktop navigation rail but left `BottomNav` visible at
desktop breakpoints. Wide screens therefore rendered two navigation systems and
still felt like an enlarged phone interface. The fixed-height desktop shell also
made the content area depend on panel-style overflow instead of normal document
scrolling.

**Decision.** At `md` and wider, PlateOS uses a sticky horizontal application
header with brand/date context, primary task navigation, queue/connectivity
status, and account/logout controls. A one-pixel progress signal beneath the
header reflects today's calorie-target consumption. The work area uses normal
document scrolling and a `max-w-7xl` canvas; the Today view retains its wide
two-column log-and-budget layout. `BottomNav` is explicitly mobile-only and
retains safe-area padding for installed iOS use. The graphite/emerald visual
system and existing feature components remain unchanged.

**Rejected.** Keeping the rail and only hiding the duplicate bottom bar (fixes
the bug but not the desktop information hierarchy); a collapsible sidebar
(additional state and interaction cost for five destinations); desktop route
tabs below a separate account header (two stacked navigation bands waste
vertical space).

## Evidence

| Check | Result |
| --- | --- |
| Frontend tests | 8 passed |
| TypeScript | `tsc --noEmit` clean |
| Production/PWA build | Clean; main chunk 390.14 kB, camera and analytics remain lazy-loaded |
| Responsive boundary | `BottomNav` has `md:hidden`; `DesktopHeader` has `hidden md:block` |
