# Changelog

All notable changes to EDRavenColonialAgent are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-21

Initial release — a merge of the **EDMC-Ravencolonial** plugin and the "Colonise" overlay from
**SrvSurvey**, re-implemented for EDMC.

### Added
- In-game **commodities-needed overlay** (via EDMCOverlay / EDMCModernOverlay) showing every
  commodity still required for the active construction project(s), the amount carried in your ship,
  and a ✓ when you already have enough.
- **On-site** alphabetical view (from the `ColonisationConstructionDepot` event) and an **off-site**
  view that aggregates the commander's active Raven Colonial projects, grouped by commodity category.
- **Market-aware dimming** — when docked, commodities the station's market doesn't sell are greyed.
- **Totals/trips footer** (remaining units and trips for your current cargo capacity).
- **EDMC-window fallback panel** when no overlay plugin is installed.
- Raven Colonial integration: per-commander **API key** (`rcc-key`) with live validation, active
  project fetch, and completion detection / project-name cleanup.
- Settings tab: overlay enable, window panel, overlay position, and column/background layout tuning
  (name length, Need/Ship column offsets, background width).
- Packaging (`package.py`), CI (`test.yml`), pure-logic unit tests, and a `smoke_test.py` harness.

### Notes
- Overlay rendering is tuned for **EDMCModernOverlay**: text is sent ungrouped so column offsets are
  honoured, and the translucent background is drawn as a solid group fill behind an invisible marker.
