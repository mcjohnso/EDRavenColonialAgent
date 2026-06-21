"""Stub-EDMC smoke test for EDRavenColonialAgent.

Fakes EDMC's runtime modules (config, myNotebook, theme, l10n, plug, edmcoverlay,
ttkHyperlinkLabel) and a fake in-game overlay, then imports the plugin and drives its
callbacks the way EDMC would. The API client is monkeypatched so no network is hit.

Run locally (needs a display for tkinter):

    python smoke_test.py
"""

import json
import os
import sys
import tempfile
import types
import tkinter as tk
from tkinter import ttk
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN_DIR = ROOT / "EDRavenColonialAgent"
sys.path.insert(0, str(PLUGIN_DIR))

# --- a temp journal dir with a Market.json (station sells aluminium + liquid oxygen) -----
JOURNAL_DIR = tempfile.mkdtemp(prefix="edrca_journal_")
MARKET_ID = 3700123
with open(os.path.join(JOURNAL_DIR, "Market.json"), "w", encoding="utf-8") as f:
    json.dump({
        "event": "Market", "MarketID": MARKET_ID, "StationName": "Test Hub",
        "Items": [
            {"Name": "$aluminium_name;", "Stock": 500, "Demand": 0},
            {"Name": "$liquidoxygen_name;", "Stock": 50, "Demand": 0},
            {"Name": "$steel_name;", "Stock": 0, "Demand": 99},
        ],
    }, f)

# --- fake `config` -----------------------------------------------------------------------
config_mod = types.ModuleType("config")
config_mod.appname = "EDMarketConnector"
config_mod.appversion = "6.1.2"


class _Config:
    def __init__(self):
        self.store = {"journaldir": JOURNAL_DIR}

    def get_str(self, k, *, default=""):
        return self.store.get(k, default)

    def get_int(self, k, *, default=0):
        try:
            return int(self.store.get(k, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, k, *, default=False):
        return bool(self.store.get(k, default))

    def get_list(self, k, *, default=None):
        return self.store.get(k, default if default is not None else [])

    def set(self, k, v):
        self.store[k] = v

    def delete(self, k, *, suppress=False):
        self.store.pop(k, None)

    shutting_down = False


config_mod.config = _Config()
config_mod.default_journal_dir = JOURNAL_DIR
sys.modules["config"] = config_mod

# --- fake `requests` (EDMC bundles it; not needed since API calls are monkeypatched) -----
requests_mod = types.ModuleType("requests")


class _Session:
    def __init__(self):
        self.headers = {}

    def mount(self, *a, **k):
        pass

    def _blocked(self, *a, **k):
        raise RuntimeError("network disabled in smoke test")

    get = post = put = patch = _blocked


requests_mod.Session = _Session
sys.modules["requests"] = requests_mod

# requests.adapters.HTTPAdapter + urllib3.util.retry.Retry (used by rca_api retry config)
adapters_mod = types.ModuleType("requests.adapters")
adapters_mod.HTTPAdapter = lambda *a, **k: object()
requests_mod.adapters = adapters_mod
sys.modules["requests.adapters"] = adapters_mod

urllib3_mod = types.ModuleType("urllib3")
urllib3_util_mod = types.ModuleType("urllib3.util")
urllib3_retry_mod = types.ModuleType("urllib3.util.retry")
urllib3_retry_mod.Retry = lambda *a, **k: object()
urllib3_util_mod.retry = urllib3_retry_mod
urllib3_mod.util = urllib3_util_mod
sys.modules["urllib3"] = urllib3_mod
sys.modules["urllib3.util"] = urllib3_util_mod
sys.modules["urllib3.util.retry"] = urllib3_retry_mod

# --- fake themed/EDMC modules ------------------------------------------------------------
# EDMC's myNotebook widgets are ttk-based, so they reject classic tk options like `fg`.
# Using ttk here (not tk) makes the stub catch those mismatches.
nb = types.ModuleType("myNotebook")


class _NbFrame(ttk.Frame):
    """Mimics EDMC's myNotebook.Frame: it already manages internal children with
    grid, so calling .pack() on anything inside it raises a TclError. This makes the
    stub catch pack/grid mix-ups that a bare frame would silently allow."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        ttk.Frame(self).grid(row=0, column=0)  # puts the frame in grid mode


nb.Frame = _NbFrame
nb.Label = ttk.Label
nb.EntryMenu = ttk.Entry   # current EDMC exposes EntryMenu, NOT Entry
nb.Checkbutton = ttk.Checkbutton
nb.Button = ttk.Button
nb.Notebook = ttk.Frame
sys.modules["myNotebook"] = nb

theme_mod = types.ModuleType("theme")
theme_mod.theme = types.SimpleNamespace(update=lambda w: None)
sys.modules["theme"] = theme_mod

l10n_mod = types.ModuleType("l10n")
l10n_mod.translations = types.SimpleNamespace(tl=lambda s, context=None: s)
sys.modules["l10n"] = l10n_mod

plug_mod = types.ModuleType("plug")
plug_mod.show_error = lambda *a, **k: None
sys.modules["plug"] = plug_mod

hyperlink_mod = types.ModuleType("ttkHyperlinkLabel")


class _HyperlinkLabel(ttk.Label):
    def __init__(self, master, url=None, **kw):
        super().__init__(master, **kw)


hyperlink_mod.HyperlinkLabel = _HyperlinkLabel
sys.modules["ttkHyperlinkLabel"] = hyperlink_mod

# --- fake `edmcoverlay` (capture what the plugin draws) ----------------------------------
overlay_mod = types.ModuleType("edmcoverlay")
SENT = {"messages": [], "shapes": []}


class Overlay:
    def __init__(self, *a, **k):
        pass

    def connect(self):
        pass

    def send_message(self, msgid, text, color, x, y, ttl=4, size="normal"):
        SENT["messages"].append((msgid, text, color))

    def send_shape(self, shapeid, shape, color, fill, x, y, w, h, ttl):
        SENT["shapes"].append((shapeid, shape, fill, w, h))

    def send_raw(self, msg):
        pass


overlay_mod.Overlay = Overlay
sys.modules["edmcoverlay"] = overlay_mod

# Stub EDMCModernOverlay's grouping API so we can assert the plugin NEVER registers a
# group (grouping triggers the position-normalising transform we deliberately avoid).
GROUP_CALLS = []
_overlay_plugin_pkg = types.ModuleType("overlay_plugin")
_overlay_api_mod = types.ModuleType("overlay_plugin.overlay_api")


def _define_plugin_group(*a, **k):
    GROUP_CALLS.append((a, k))
    return True


_overlay_api_mod.define_plugin_group = _define_plugin_group
_overlay_plugin_pkg.overlay_api = _overlay_api_mod
sys.modules["overlay_plugin"] = _overlay_plugin_pkg
sys.modules["overlay_plugin.overlay_api"] = _overlay_api_mod


def texts():
    return [t for _, t, _ in SENT["messages"]]


def assert_contains(needle):
    assert any(needle in t for t in texts()), \
        f"expected a message containing {needle!r}; got {texts()}"


# --- import + start ----------------------------------------------------------------------
root = tk.Tk()
root.withdraw()

import load  # noqa: E402

print("plugin_start3 ->", load.plugin_start3(str(PLUGIN_DIR)))
load.plugin_app(root)
print("plugin_app OK")

# Monkeypatch the API client so nothing hits the network.
ACTIVE_PROJECTS = [
    {
        "buildId": "b1", "buildName": "Hera Port", "buildType": "orbis",
        "systemAddress": 111, "marketId": MARKET_ID, "systemName": "Sol",
        "complete": False,
        "commodities": {"aluminium": 60, "steel": 100, "liquidoxygen": 30},
        "commanders": {"CMDR Test": ["aluminium"]},
    },
]
api = load.this.api_client
api.get_commander_active = lambda cmdr: list(ACTIVE_PROJECTS)
api.get_primary = lambda cmdr: "b1"
api.get_cmdr_by_api_key = lambda key: ("CMDR Test" if key == "good" else None)
api.get_project = lambda sa, mid: None
api.contribute_cargo = lambda *a, **k: True
api.update_project_supply = lambda *a, **k: True

# --- settings page round-trip ------------------------------------------------------------
load.plugin_prefs(root, "CMDR Test", False)
load.prefs_changed("CMDR Test", False)
print("plugin_prefs / prefs_changed OK")

# Exercise API-key validation end-to-end (sets 'Checking…' + colors the result label).
import rca_settings  # noqa: E402
rca_settings._vars["api_key"].set("good")
rca_settings._validate(load.this)          # queues worker call; colors label "gray"
load.this.api_queue.join()                 # worker runs get_cmdr_by_api_key
rca_settings._show_validation()            # the event handler; colors label green
assert rca_settings._validation["cmdr"] == "CMDR Test", rca_settings._validation
assert "CMDR Test" in rca_settings._cmdr_label.cget("text"), rca_settings._cmdr_label.cget("text")
rca_settings._vars["api_key"].set("bad")
rca_settings._validate(load.this)
load.this.api_queue.join()
rca_settings._show_validation()
assert "invalid" in rca_settings._cmdr_label.cget("text").lower()
print("API key validation OK")

# --- scenario A: docked at a construction site (alpha layout from depot event) -----------
SENT["messages"].clear()
load.journal_entry("CMDR Test", False, "Sol", "Orbital Construction Site: Hera",
                   {"event": "Docked", "MarketID": MARKET_ID, "SystemAddress": 111,
                    "StationName": "Orbital Construction Site: Hera",
                    "StationServices": ["dock", "colonisationcontribution"]},
                   {"Cargo": {"aluminium": 60, "steel": 10}})
load.journal_entry("CMDR Test", False, "Sol", "Orbital Construction Site: Hera",
                   {"event": "ColonisationConstructionDepot", "MarketID": MARKET_ID,
                    "SystemAddress": 111, "ConstructionComplete": False,
                    "ResourcesRequired": [
                        {"Name": "$aluminium_name;", "RequiredAmount": 100, "ProvidedAmount": 40},
                        {"Name": "$steel_name;", "RequiredAmount": 100, "ProvidedAmount": 0},
                        {"Name": "$liquidoxygen_name;", "RequiredAmount": 30, "ProvidedAmount": 30},
                    ]},
                   {"Cargo": {"aluminium": 60, "steel": 10}})
load.this.api_queue.join()         # let the async active-projects fetch finish
SENT["messages"].clear()
SENT["shapes"].clear()
load.this.agent.refresh()          # deterministic render with projects populated
assert_contains("Hera Port")       # header (project resolved from active projects)
assert_contains("Aluminium")       # 100-40 = 60 needed
assert_contains("Steel")           # 100 needed
assert "Liquid oxygen" not in " ".join(texts()), "fully-provided item should be omitted"
assert_contains("remaining")       # footer

# Background = a solid fill the overlay draws behind one invisible spaces marker in a SEPARATE
# group (rcabg_); the real text stays ungrouped (rcaov_) so its columns are never transformed.
ov = load.rca_agent.rca_overlay
assert GROUP_CALLS, "expected a background group registration (define_plugin_group)"
gkw = GROUP_CALLS[0][1]
assert gkw.get("plugin_group_background_color") == ov.BG_FILL, gkw
assert ov.BG_ID_PREFIX in (gkw.get("plugin_matching_prefixes") or []), gkw
bg_ids = [mid for mid, _, _ in SENT["messages"] if mid.startswith(ov.BG_ID_PREFIX)]
text_ids = [mid for mid, _, _ in SENT["messages"] if mid.startswith(ov.OVERLAY_ID_PREFIX)]
assert bg_ids, f"expected a background marker message ({ov.BG_ID_PREFIX}…); got {SENT['messages']}"
assert text_ids, "expected ungrouped text messages (rcaov_…)"
# the bg group must NOT capture the text prefix (text must stay ungrouped)
assert ov.OVERLAY_ID_PREFIX not in (gkw.get("plugin_matching_prefixes") or []), gkw
assert not SENT["shapes"], f"plugin must NOT send_shape rects; got {SENT['shapes']}"
print(f"scenario A (docked at site) OK; {len(text_ids)} text msgs + {len(bg_ids)} bg marker")

# market dimming WHEN DOCKED: commodities the station doesn't sell are greyed (COL_DARK),
# now in the at-site view too (previously suppressed). Station sells aluminium, not steel.
load.this.market_available = {"aluminium"}
load.this.market_market_id = MARKET_ID          # matches the docked station's MarketID
SENT["messages"].clear()
load.this.agent.refresh()
steel_dark = [t for _, t, c in SENT["messages"] if c == ov.COL_DARK and "Steel" in t]
assert steel_dark, \
    f"Steel (not sold here) should be greyed when docked; got {[(t, c) for _, t, c in SENT['messages']]}"
load.this.market_available = set()              # reset so later scenarios are unaffected
load.this.market_market_id = None
print("market dimming when docked at site OK")

# keep-alive: tick() must re-send the overlay when the ttl is going stale (the heartbeat)
load.this.agent.overlay._last_send = 0.0   # force "stale"
SENT["messages"].clear()
load.this.agent.tick()
assert len(SENT["messages"]) > 0, "tick() should re-send the overlay while visible"
print("keep-alive tick() re-send OK")

# --- scenario B: off-site at a market with active projects (grouped layout) --------------
SENT["messages"].clear()
load.journal_entry("CMDR Test", False, "Sol", "Test Hub",
                   {"event": "Docked", "MarketID": MARKET_ID, "SystemAddress": 999,
                    "StationName": "Test Hub", "StationServices": ["dock", "commodities"]},
                   {"Cargo": {}})
load.journal_entry("CMDR Test", False, "Sol", "Test Hub",
                   {"event": "Market", "MarketID": MARKET_ID},
                   {"Cargo": {}})
load.this.api_queue.join()
load.dashboard_entry("CMDR Test", False, {"GuiFocus": 5, "Flags": 1})  # docked (bit 0)
SENT["messages"].clear()
load.this.agent.refresh()
joined = " ".join(texts())
assert_contains("Metals")          # category header in grouped layout
assert_contains("Aluminium")
# steel is needed but NOT sold at this market -> dimmed color. Rows are emitted as
# multi-line per-color column blocks, so look for "Steel" inside a COL_DARK message.
COL_DARK = load.rca_agent.rca_overlay.COL_DARK
steel_dark = [t for _, t, c in SENT["messages"] if c == COL_DARK and "Steel" in t]
assert steel_dark, \
    f"steel should be dimmed (not in market); got { [(t, c) for _, t, c in SENT['messages']] }"
print(f"scenario B (off-site grouped) OK; {len(SENT['messages'])} overlay messages")

# --- scenario E: started while docked — dashboard_entry alone drives cmdr + docked + fetch
load.this._loaded_cmdr = None                # force a fresh commander detection
load.this.active_projects = []
load.this.last_station_name = None           # no journal Docked event was delivered
load.this.last_station_services = None
load.this.construction_depot_data = None
SENT["messages"].clear()
load.dashboard_entry("CMDR Test", False, {"Flags": 1})   # docked, no journal events at all
load.this.api_queue.join()                   # the fetch it triggered runs
assert load.this.active_projects, "dashboard_entry should have triggered the active-projects fetch"
load.this.agent.refresh()
assert len(SENT["messages"]) > 0, "overlay should show when docked (Flags) with active projects"
assert load.this.is_docked is True
print("scenario E (startup-while-docked via dashboard) OK")

# --- scenario C: graceful degradation when no overlay plugin is installed ----------------
sys.modules.pop("edmcoverlay", None)
ov = load.this.agent.overlay
ov._ov = None          # force a reconnect attempt
ov.available = False
load.this.agent.refresh()  # must not raise even though edmcoverlay import now fails
assert ov.available is False, "overlay should report unavailable without edmcoverlay"
print("scenario C (no overlay -> graceful) OK")

# --- scenario D: construction completion strips the site prefix + marks complete --------
calls = {"renamed": None, "completed": None}
api.get_project = lambda sa, mid: {"buildId": "b1",
                                   "buildName": "Orbital Construction Site: Hera Port"}
api.update_project_name = lambda bid, name: calls.__setitem__("renamed", (bid, name)) or True
api.mark_project_complete = lambda bid: calls.__setitem__("completed", bid) or True
load.journal_entry("CMDR Test", False, "Sol", "Orbital Construction Site: Hera",
                   {"event": "Docked", "MarketID": MARKET_ID, "SystemAddress": 111,
                    "StationName": "Orbital Construction Site: Hera",
                    "StationServices": ["dock", "colonisationcontribution"]},
                   {"Cargo": {}})
load.journal_entry("CMDR Test", False, "Sol", "Orbital Construction Site: Hera",
                   {"event": "ColonisationConstructionDepot", "MarketID": MARKET_ID,
                    "SystemAddress": 111, "ConstructionComplete": True,
                    "ResourcesRequired": []},
                   {"Cargo": {}})
load.this.api_queue.join()
assert calls["renamed"] == ("b1", "Hera Port"), calls["renamed"]
assert calls["completed"] == "b1", calls["completed"]
print("scenario D (completion rename + mark complete) OK")

load.plugin_stop()
root.destroy()
print("SMOKE TEST: OK")
