# Phase 14 – UI Redesign Foundation

Starts the larger product UI redesign path without risky backend changes.

## Added

- Product shell improvements: richer header subtitle, nav items with primary/secondary labels, product hero, and improved workflow guide cards.
- Design-system foundation in CSS: radius/shadow/focus tokens, glassy header/nav treatment, stronger product gradient, and better card/table/modal styling.
- Server tab starts moving toward an interactive builder: renamed to **Proxy Server Builder** with preset explanation strip.

## Scope

This is intentionally Phase 1 of the UI redesign, not the full rewrite. It keeps existing IDs/functions intact so existing JS and tests continue to work.

## Next UI redesign steps

- Convert server creation into a real multi-step wizard.
- Create a dashboard overview tab / cockpit.
- Reduce inline styles in `main.html` into reusable CSS classes.
- Redesign Proxy Inventory table controls and empty states.
