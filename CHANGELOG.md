# Changes

## 0.3.0

- Search Home Assistant entities by name or ID, fill unambiguous selections and test unsaved connection settings.
- Poll and broadcast external state changes; report missing entities, rejected tokens, malformed responses, TLS and network errors.
- Replace GET side effects with authenticated, permission-checked POST controls. Legacy GET mutation callers must migrate.
- Add independent additional entities, configurable navbar icons and live brightness/colour menus.
- Add optional turn-on appearance, print status colours and native short error flashes.
- Add opt-in `@OCTOLIGHT` host commands for OctoDash/G-code.
- Fix completion timers across new prints, manual controls, reconfiguration, shutdown and stale callbacks.
- Remove token logging; mask and restrict stored credentials. Enable TLS verification for new configurations while migrating existing preferences.
- Bound HTTP calls, batch polling and keep event/serial callbacks independent of network I/O.
- Migrate to isolated Python packaging, Python 3.9+ metadata, fork-owned updates and autoescaped templates.
- Add backend, Chromium, installed-package integration tests and an OctoPrint 1/2 CI matrix.

Validation uses OctoPrint 1.11.8 and 2.0.0rc7. No physical printer or Home Assistant device validation is implied.
