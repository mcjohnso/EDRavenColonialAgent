"""
Overlay coordinator: turns the plugin's live state into a Needs model + OverlayContext
and drives both the in-game overlay (rca_overlay) and the EDMC-window fallback panel
(rca_ui). Keeps load.py thin.

Threading: refresh()/tick()/clear() must run on the main Tk thread. Background fetches
hop back via request_redraw() -> frame.event_generate (the only Tk-safe call off-thread).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import rca_colony as colony
import rca_overlay

# Log through EDMC's plugin-logger namespace so these lines appear in EDMarketConnector.log
# (a bare getLogger(__name__) -> "rca_agent" is outside EDMC's handler and stays invisible).
try:
    from config import appname as _appname
    logger = logging.getLogger(f"{_appname}.EDRavenColonialAgent")
except Exception:
    logger = logging.getLogger(__name__)

REDRAW_EVENT = "<<EdrcaRedraw>>"
GUI_FOCUS_STATION_SERVICES = 5  # Status.json GuiFocus value for Station Services


def _project_label(project: Dict) -> str:
    name = project.get("buildName") or "Project"
    build_type = project.get("buildType")
    return f"{name} ({build_type})" if build_type else name


class OverlayAgent:
    def __init__(self, plugin):
        self.plugin = plugin
        self.overlay = rca_overlay.Overlay()
        # settings (loaded/refreshed via apply_settings)
        self.feature_enabled = True
        self.show_window_panel = False
        self.apply_settings()

    # -- settings ------------------------------------------------------------------------
    def apply_settings(self):
        """(Re)load settings from EDMC config; safe if config is unavailable."""
        try:
            from config import config
            self.feature_enabled = config.get_bool("edrca_enabled", default=True)
            self.overlay.enabled = config.get_bool("edrca_overlay_enabled", default=True)
            self.show_window_panel = config.get_bool("edrca_window_panel", default=False)
            ax = config.get_int("edrca_overlay_x")
            ay = config.get_int("edrca_overlay_y")
            lh = config.get_int("edrca_overlay_line_height")
            ndx = config.get_int("edrca_overlay_need_x")
            hvx = config.get_int("edrca_overlay_have_x")
            nmc = config.get_int("edrca_overlay_name_chars")
            brh = config.get_int("edrca_overlay_bg_row_h")
            bwp = config.get_int("edrca_overlay_bg_width_pct")
            self.overlay.update_geometry(anchor_x=ax or None, anchor_y=ay or None,
                                         line_height=lh or None,
                                         need_x=ndx or None, have_x=hvx or None,
                                         name_max_chars=nmc or None, bg_row_h=brh or None,
                                         bg_width_pct=bwp or None)
        except Exception:
            logger.exception("apply_settings failed")

    # -- visibility (ported from PlotBuildCommodities.allowed) ----------------------------
    def _has_active_projects(self) -> bool:
        return any(not p.get("complete") for p in (self.plugin.active_projects or []))

    def _docked_at_site(self) -> bool:
        p = self.plugin
        return bool(p.is_docked) and colony.is_construction_site(
            p.last_station_name, p.last_station_services
        )

    def should_show(self) -> bool:
        """Show iff docked at a station AND there's an active colony project.

        (Being docked at a construction depot is itself an active project, even when
        it isn't tracked in Raven Colonial yet.)
        """
        p = self.plugin
        if not self.feature_enabled or not p.cmdr_name:
            return False
        if not p.is_docked:
            return False
        if self._has_active_projects():
            return True
        if self._docked_at_site() and p.construction_depot_data is not None:
            return True
        return False

    # -- view-model assembly -------------------------------------------------------------
    def _find_project(self, system_address, market_id) -> Optional[Dict]:
        for pr in self.plugin.active_projects or []:
            if pr.get("systemAddress") == system_address and pr.get("marketId") == market_id:
                return pr
        return None

    def _market_available_now(self) -> set:
        """Commodities sold at the *currently docked* station (Stock>0), or empty.

        Guarded by market id so a stale Market.json from a previous station is ignored.
        Empty when the station has no commodity market (or it hasn't been opened yet), in
        which case nothing dims.
        """
        p = self.plugin
        if p.market_market_id is not None and p.market_market_id == p.current_market_id:
            return set(p.market_available or set())
        return set()

    def compute(self) -> Tuple[Optional[colony.Needs], Optional[rca_overlay.OverlayContext]]:
        p = self.plugin
        cargo = dict(p.cargo or {})
        cargo_capacity = int(p.cargo_capacity or 0)
        # Dim commodities not sold at the docked station — in BOTH the at-site and off-site
        # views. Self-suppressing: empty set (no market / market not opened) dims nothing.
        market_available = self._market_available_now()

        if self._docked_at_site() and p.construction_depot_data:
            depot = p.construction_depot_data
            needs = colony.needs_from_depot(depot)
            proj = self._find_project(p.current_system_address, p.current_market_id)
            header = _project_label(proj) if proj else colony.default_project_name(p.last_station_name)
            ctx = rca_overlay.OverlayContext(
                header=header,
                project_names=[],
                docked_at_site=True,
                construction_complete=bool(depot.get("ConstructionComplete")),
                untracked_site=proj is None,
                cargo=cargo,
                market_available=market_available,
                market_valid=bool(market_available),
                cargo_capacity=cargo_capacity,
            )
            return needs, ctx

        # Off-site: aggregate the commander's active projects.
        projs = [pr for pr in (p.active_projects or []) if not pr.get("complete")]
        needs = colony.needs_from_projects(projs, p.cmdr_name)
        names: List[str] = []
        if len(projs) == 1:
            header = _project_label(projs[0])
        elif len(projs) > 1:
            header = f"{len(projs)} Projects:"
            names = sorted(_project_label(pr) for pr in projs)
        else:
            return None, None

        ctx = rca_overlay.OverlayContext(
            header=header,
            project_names=names,
            docked_at_site=False,
            cargo=cargo,
            market_available=market_available,
            market_valid=bool(market_available),
            cargo_capacity=cargo_capacity,
        )
        return needs, ctx

    # -- rendering (main thread only) ----------------------------------------------------
    def refresh(self):
        try:
            from config import config
            if getattr(config, "shutting_down", False):
                return
        except Exception:
            pass

        try:
            if not self.should_show():
                self.clear()
                return
            needs, ctx = self.compute()
            if needs is None or ctx is None:
                self.clear()
                return

            if self.overlay.enabled:
                self.overlay.draw(needs, ctx)
            else:
                self.overlay.clear()

            want_panel = (
                self.show_window_panel
                or not self.overlay.enabled
                or not self.overlay.available
            )
            self.plugin.ui_manager.update_needs_panel(needs, ctx, want_panel)
        except Exception:
            logger.exception("OverlayAgent.refresh failed")

    def tick(self):
        """Keep-alive from dashboard_entry (~1/s)."""
        try:
            self.overlay.tick()
        except Exception:
            logger.exception("OverlayAgent.tick failed")

    def clear(self):
        try:
            self.overlay.clear()
            self.plugin.ui_manager.update_needs_panel(None, None, False)
        except Exception:
            logger.exception("OverlayAgent.clear failed")

    # -- background fetch ----------------------------------------------------------------
    def fetch_active_projects_async(self):
        p = self.plugin
        if not p.cmdr_name:
            return

        cmdr = p.cmdr_name

        def work():
            projects = p.api_client.get_commander_active(cmdr)
            p.active_projects = projects or []
            p.primary_build_id = p.api_client.get_primary(cmdr)
            logger.info(f"Fetched {len(p.active_projects)} active project(s) for {cmdr}")
            self.request_redraw()

        p.queue_api_call(work)

    def request_redraw(self):
        """Ask the main thread to refresh (safe to call from the worker thread)."""
        try:
            from config import config
            if getattr(config, "shutting_down", False):
                return
        except Exception:
            pass
        frame = getattr(self.plugin, "frame", None)
        if frame is not None:
            try:
                frame.event_generate(REDRAW_EVENT, when="tail")
            except Exception:
                pass
