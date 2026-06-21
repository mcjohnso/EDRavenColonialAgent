# EDRavenColonialAgent

[![Test](https://github.com/mcjohnso/EDRavenColonialAgent/actions/workflows/test.yml/badge.svg)](https://github.com/mcjohnso/EDRavenColonialAgent/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/mcjohnso/EDRavenColonialAgent)](https://github.com/mcjohnso/EDRavenColonialAgent/releases/latest)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](EDRavenColonialAgent/LICENSE)

An [EDMarketConnector](https://github.com/EDCD/EDMarketConnector) (EDMC) plugin for Elite
Dangerous **colonization**. It integrates with the [Raven Colonial](https://ravencolonial.com)
community service **and** draws an in-game overlay showing the commodities (and quantities) still
needed for your active construction project(s) — including which of them are for sale at the
station you're currently docked at.

It merges two existing projects:

- the Raven Colonial API integration from the **EDMC-Ravencolonial** plugin (detect construction
  depots, create projects, auto-report contributions, detect completion), and
- the "Colonise" commodities-needed overlay from
  **[SrvSurvey](https://github.com/njthomson/SrvSurvey)** (`PlotBuildCommodities`), re-implemented
  for EDMC's overlay.

## Features

- **Live "still needed" overlay** — every commodity still required for your construction
  project(s), with how many you're carrying and a ✓ once you have enough.
- **Market-aware dimming** — when docked, commodities the station's market doesn't sell are greyed
  out, so you can see at a glance what's worth buying here.
- **On-site and off-site views** — an alphabetical list at the construction site, or your active
  projects' combined needs grouped by category when you're elsewhere, with a totals/trips footer.
- **Raven Colonial integration** — per-commander API key, project detection/creation, automatic
  contribution reporting, and completion detection.
- **Works without an overlay** — falls back to a panel inside the EDMC window if no overlay plugin
  is installed.

## Installation

1. Download **`EDRavenColonialAgent-vX.Y.Z.zip`** from the
   [latest release](https://github.com/mcjohnso/EDRavenColonialAgent/releases/latest).
2. Extract it into EDMC's `plugins` folder so you get `…/plugins/EDRavenColonialAgent/load.py`:
   - **Windows:** `%LOCALAPPDATA%\EDMarketConnector\plugins`
   - **macOS:** `~/Library/Application Support/EDMarketConnector/plugins`
   - **Linux:** `~/.local/share/EDMarketConnector/plugins`
3. Restart EDMC.

For the in-game overlay, also install
[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) (recommended) or the
original [EDMCOverlay](https://github.com/inorton/EDMCOverlay). It's optional — without it the
needs show in the EDMC window instead.

Full usage, the API-key setup, and all settings are documented in the plugin's own
[README](EDRavenColonialAgent/README.md).

## License

**GPL-3.0** (see [LICENSE](EDRavenColonialAgent/LICENSE)). This plugin ports overlay design/logic
and commodity data from [SrvSurvey](https://github.com/njthomson/SrvSurvey) (GPL-3.0), so this
derivative work is licensed under the same terms.
