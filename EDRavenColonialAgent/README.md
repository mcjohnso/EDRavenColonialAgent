# EDRavenColonialAgent

An [EDMarketConnector](https://github.com/EDCD/EDMarketConnector) (EDMC) plugin for Elite
Dangerous **colonization**. It integrates with the [Raven Colonial](https://ravencolonial.com)
community service **and** draws an in-game overlay showing the commodities (and quantities)
still needed for your active construction project(s) — including which of them are for sale at
the station you're currently docked at.

It merges two things:

- the Raven Colonial API integration from the **EDMC-Ravencolonial** plugin (detect construction
  depots, create projects, auto-report contributions, detect completion), and
- the "Colonise" commodities-needed overlay from **[SrvSurvey](https://github.com/njthomson/SrvSurvey)**
  (`PlotBuildCommodities`), re-implemented for EDMC's overlay.

## What it shows

- **Docked at a construction site** — an alphabetical list of every commodity still required
  (`RequiredAmount − ProvidedAmount`), with the amount in your **ship** and a ✓ when you already
  have enough.
- **Anywhere else (e.g. buying at a commodity market)** — your active Raven Colonial projects'
  remaining needs, grouped by commodity category. Commodities **sold at the current station** are
  shown normally; ones it doesn't sell are **dimmed**, so you can see at a glance what's worth
  buying here.
- A footer with the total remaining and how many **trips** your current ship would take.

The panel appears when you're docked at a construction site or when you open **Station Services**
with active projects (configurable).

## Requirements

- **EDMC** with Python 3.11 (what EDMC bundles).
- For the in-game overlay: an overlay plugin —
  **[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)** (recommended) or the
  original [EDMCOverlay](https://github.com/inorton/EDMCOverlay). This is **optional**: without it,
  the needs are shown in a panel inside the EDMC window instead.
- A **Raven Colonial API key** (see below) — required for write operations (contributions,
  creating/updating projects).

## Install

1. Download `EDRavenColonialAgent-v<version>.zip` from the Releases page.
2. Extract it into EDMC's plugins folder so you get `…/plugins/EDRavenColonialAgent/load.py`:
   - **Windows:** `%LOCALAPPDATA%\EDMarketConnector\plugins`
   - **macOS:** `~/Library/Application Support/EDMarketConnector/plugins`
   - **Linux:** `~/.local/share/EDMarketConnector/plugins`
3. Restart EDMC.

## API key

Raven Colonial authenticates with a **per-commander API key**, sent as the `rcc-key` HTTP header.

1. Generate your key at **https://ravencolonial.com/user**.
2. In EDMC: **File → Settings → EDRavenColonialAgent**, paste it into **API key**, and click
   **Validate** — it should resolve to your commander name.

The key is stored per-commander in EDMC's config (plaintext on disk, the same trust model as
SrvSurvey's settings).

## Settings

| Setting | Default | Effect |
| --- | --- | --- |
| Show colony commodities needed | on | Master switch for the needs panel/overlay |
| Draw in-game overlay | on | Use EDMCOverlay/EDMCModernOverlay (falls back to the window panel if absent) |
| Also show needs panel in this window | off | Show the in-window panel even when the overlay is active |
| Overlay position x / y | 20 / 180 | Anchor of the overlay panel (virtual overlay pixels; x can go past 1280 on ultra-wide) |
| Max name length (chars) | 22 | Truncate long commodity names so they don't reach the Need column |
| Need column offset / Ship column offset | 160 / 290 | x of the Need / Ship number columns, relative to the anchor |
| Background row height | 22 | Inert (kept for compatibility) — the background box height is automatic |
| Background width % | 100 | Stretch the translucent background box rightward (bump on a wide/FILL-mode overlay) |

## Development

Pure logic lives in EDMC-free, unit-testable modules:

- `rca_colony.py` — needs model + commodity name/category data (ported from SrvSurvey's `ColonyData`)
- `rca_market.py` — `Market.json` reader for station availability
- `rca_overlay.py` — overlay layout (`build_lines`) + resilient `edmcoverlay` wrapper
- `rca_agent.py` — coordinator that turns plugin state into a view and drives overlay + window panel
- `rca_api.py` — Raven Colonial API client (`rcc-key` auth, project/cmdr endpoints)
- `rca_settings.py` — Settings tab (API key entry + validation, overlay options)

```bash
python tests/test_core.py     # pure-logic unit tests (no EDMC needed)
python smoke_test.py          # stubs EDMC + a fake overlay and drives the callbacks
python package.py             # build dist/EDRavenColonialAgent-v<version>.zip
```

`rca_commodities.json` (commodity display names + categories) is generated from SrvSurvey's
resources by `tools/extract_commodities.py`.

## Credits

- Raven Colonial service and API by **grinning2001**.
- The commodities-needed overlay design is ported from **SrvSurvey** by **njthomson**.
- Builds on the **EDMC-Ravencolonial** plugin for the Raven Colonial API integration.

## License

**GPL-3.0** (see [LICENSE](LICENSE)). This plugin ports the "Colonise" overlay design/logic and
commodity data from [SrvSurvey](https://github.com/njthomson/SrvSurvey), which is GPL-3.0, so this
derivative work is licensed under the same terms.
