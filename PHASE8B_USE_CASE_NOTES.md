# Phase 8B – Use-Case Presets & Capability UX

Builds on Phase 8A protocol validation. No schema changes; UI + one stats endpoint field.

## 1. Server "Use Case" preset (server profile modal)
New dropdown `Use Case Preset` above `Candidate Statuses`:
- **Web Browsing (HTTPS)** → require_web_https=Yes, require_remote_dns=No, require_telegram=No
- **Telegram (HTTPS+DNS+TG)** → all three = Yes
- **Scraping / HTTP** → all three = No (accepts plain HTTP exits)
- **Custom (manual)** → leaves the Require flags untouched

Picking a preset auto-fills the existing Require flags. Editing an existing
profile forces the dropdown to *Custom* so saved flags are preserved.

## 2. Capability quick-filters (Proxy Inventory toolbar)
New "Ready:" chips next to the Status filters: **Web / Telegram / DNS**.
Clicking a chip toggles it and filters the table via the Phase 8A
`/api/proxies?capability=web_https,remote_dns,telegram` param. Multiple chips
combine (AND). Chip numbers show live counts among alive proxies.

## 3. Capability stat cards (Stats tab)
Three cards added to the stats grid: **Web-ready**, **Telegram-ready**,
**Full-capability**. Fed by new `/api/stats` fields:
- `web_ready` = alive AND web_https_ok
- `dns_ready` = alive AND remote_dns_ok
- `telegram_ready` = alive AND web_https_ok AND telegram_ok
- `full_capability` = alive AND web_https_ok AND remote_dns_ok AND telegram_ok

## 4. Prominent "Normalize Legacy Statuses"
The Settings cleanup button is now primary-styled (⚡) with a tooltip, so the
~5413 old pre-Phase-5 `revived` rows can be reclassified and picked up by a
fresh monitor run for real Phase 8A validation.

## Files touched
- `dashboard/routes/stats.py` – capability counts in `/api/stats`
- `dashboard/templates/main.html` – use-case dropdown, capability chips, stat cards, normalize button
- `dashboard/static/js/base.js` – `toggleCapabilityFilter`, `updateCapabilityFilterUI`, `getCapabilityFilterParam`, `applyServerUseCase`; capability param in `loadProxies`; capability counts in `loadStats`

## Recommended follow-up flow
1. Apply overlay, restart dashboard.
2. Settings → **⚡ Normalize Legacy Statuses**.
3. Run a monitor over the reclassified rows to populate capability fields.
4. Use the "Ready" chips / stat cards to see真 real usable counts.
