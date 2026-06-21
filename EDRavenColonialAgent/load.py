"""
EDRavenColonialAgent — EDMC plugin

Tracks Elite Dangerous colonization activities and integrates with Raven Colonial
(ravencolonial.com), and renders an in-game "commodities still needed" overlay ported
from SrvSurvey. Raven Colonial API by grinning2001.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import myNotebook as nb
from config import appname, config
from typing import Optional, Dict, Any, List
from threading import Thread
import queue
import logging
import os
import functools
import l10n
import plug
import create_project_dialog
import webbrowser

# Import new modular components (top-level, plugin-prefixed to avoid EDMC's shared sys.path collisions)
from rca_api import RavencolonialAPIClient
from rca_journal import JournalEventHandler
from rca_ui import UIManager
from rca_models import ProjectData, SystemSite, ConstructionDepotData, CargoContribution
from rca_config import PluginConfig
import rca_colony
import rca_market
import rca_agent
import construction_completion

# Plugin metadata
plugin_name = os.path.basename(os.path.dirname(__file__))
__version__ = "0.1.0"
plugin_version = __version__

# Setup logging using config module
logger = PluginConfig.setup_logging()

# Setup localization
plugin_tl = functools.partial(l10n.translations.tl, context=__file__)

# Set translation function for dialog module
create_project_dialog.set_translation_function(plugin_tl)

# Global state
this = None


class RavencolonialPlugin:
    """Main plugin class to track colonization data"""
    
    def __init__(self):
        # Initialize API client (per-commander API key is applied later via apply_api_key)
        self.api_base = PluginConfig.get_api_base()
        self.api_client = RavencolonialAPIClient(
            api_base=self.api_base,
            user_agent=PluginConfig.get_user_agent(),
            api_key=None,
        )

        # Initialize journal event handler
        self.journal_handler = JournalEventHandler(self)

        # Initialize UI manager
        self.ui_manager = UIManager(self)

        # Plugin state
        self.cmdr_name: Optional[str] = None
        self.current_system: Optional[str] = None
        self.current_station: Optional[str] = None
        self.current_market_id: Optional[int] = None
        self.current_system_address: Optional[int] = None
        self.star_pos: Optional[List[float]] = None
        self.body_num: Optional[int] = None
        self.body_name: Optional[str] = None
        self.station_type: Optional[str] = None
        self.faction_name: Optional[str] = None
        self.cargo: Dict[str, int] = {}
        self.last_cargo: Dict[str, int] = {}
        self.construction_depot_data: Optional[Dict[str, Any]] = None  # Full ColonisationConstructionDepot event
        self.last_depot_state: Dict[str, int] = {}  # Track previous depot state for diff calculation
        self.is_construction_ship = False
        self.is_docked = False
        self._bodies_fetched = False

        # Colony-needs overlay state
        self.active_projects: List[Dict] = []        # the cmdr's active Raven Colonial projects
        self.primary_build_id: Optional[str] = None
        self.market_available: set = set()           # commodities (Stock>0) at the docked market
        self.market_market_id: Optional[int] = None  # which MarketID market_available is for
        self.gui_focus: int = 0                       # Status.json GuiFocus (5 == Station Services)
        self.cargo_capacity: int = 0                  # current ship cargo capacity (for trip count)
        self.last_station_name: Optional[str] = None
        self.last_station_services: Optional[List[str]] = None
        self._loaded_cmdr: Optional[str] = None       # cmdr we last applied key / fetched for

        # Queue for async API calls
        self.api_queue = queue.Queue()
        self.worker_thread = Thread(target=self._api_worker, daemon=True)
        self.worker_thread.start()
        
        # UI elements are now managed by UIManager
        # These references are kept for backward compatibility
        self.status_label = None
        self.frame = None
        self.create_button = None
        self.project_link_label = None
        self.current_build_id = None
        
        # Build types cache
        self.build_types: List[Dict] = []
        
        # Construction completion handler
        self.completion_handler = construction_completion.ConstructionCompletionHandler(self)

        # Colony-needs overlay coordinator
        self.agent = rca_agent.OverlayAgent(self)

    # --- API key (per-commander) --------------------------------------------------------

    def get_api_keys(self) -> Dict[str, str]:
        """Load the per-commander API key map from EDMC config ({cmdr: key})."""
        import json as _json
        try:
            raw = config.get_str("edrca_api_keys")
            return _json.loads(raw) if raw else {}
        except Exception:
            return {}

    def apply_api_key(self):
        """Push the active commander's stored API key into the API client."""
        key = self.get_api_keys().get(self.cmdr_name or "")
        self.api_client.set_api_key(key)

    def on_cmdr_known(self, cmdr: Optional[str]):
        """Called when the active commander becomes known/changes: set key + fetch projects."""
        if not cmdr or cmdr == self._loaded_cmdr:
            return
        self._loaded_cmdr = cmdr
        self.apply_api_key()
        self.agent.fetch_active_projects_async()

    def _api_worker(self):
        """Background worker thread for API calls"""
        while True:
            try:
                task = self.api_queue.get()
                if task is None:
                    break
                    
                func, args, kwargs = task
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"API call failed: {e}", exc_info=True)
                    # Show error in EDMC status bar asynchronously
                    error_msg = plugin_tl("Ravencolonial API error:") + f" {str(e)}"
                    plug.show_error(error_msg)
                finally:
                    self.api_queue.task_done()
            except Exception as e:
                logger.error(f"Worker thread error: {e}", exc_info=True)
    
    def queue_api_call(self, func, *args, **kwargs):
        """Queue an API call to be executed in background thread"""
        self.api_queue.put((func, args, kwargs))
    
    def get_project(self, system_address: int, market_id: int) -> Optional[Dict]:
        """Get project details for a specific system/station"""
        return self.api_client.get_project(system_address, market_id)
    
    def contribute_cargo(self, build_id: str, cmdr: str, cargo_diff: Dict[str, int]):
        """Submit cargo contribution to Ravencolonial"""
        return self.api_client.contribute_cargo(build_id, cmdr, cargo_diff)
    
    def update_project_supply(self, build_id: str, payload: Dict):
        """Update project supply totals"""
        return self.api_client.update_project_supply(build_id, payload)
    
    def get_commander_projects(self, cmdr: str) -> list:
        """Get all projects for a commander"""
        return self.api_client.get_commander_projects(cmdr)
    
    def get_system_sites(self, system_name: str) -> List[Dict]:
        """Get available construction sites in a system"""
        # We need the system address (ID64) for the v2 API
        if not self.current_system_address:
            logger.debug("No system address available, trying to get from journal")
            self.current_system_address = self.get_system_address_from_journal()
        
        if not self.current_system_address:
            logger.error("Cannot get system sites - no system address available")
            return []
        
        return self.api_client.get_system_sites(self.current_system_address)
    
    def get_system_bodies(self, system_address: int) -> List[Dict]:
        """Get bodies in a system from Ravencolonial using SystemAddress"""
        return self.api_client.get_system_bodies(system_address)
    
    def get_system_architect(self, system_address: int) -> Optional[str]:
        """Get the architect name for a system if any projects exist"""
        return self.api_client.get_system_architect(system_address)
    
    def check_existing_project(self, system_address: int, market_id: int) -> Optional[Dict]:
        """Check if a project already exists at this location"""
        logger.debug(f"Checking for existing project at system: {system_address}, market: {market_id}")
        # Use the existing get_project method which has the correct endpoint
        return self.get_project(system_address, market_id)
    
    def create_project(self, project_data: Dict[str, Any]) -> Optional[Dict]:
        """Create a new colonization project"""
        return self.api_client.create_project(project_data)
    
    def handle_cargo_depot(self, entry: Dict[str, Any]):
        """Handle CargoDepot journal event"""
        return self.journal_handler.handle_cargo_depot(entry)
    
    def handle_colonisation_construction_depot(self, entry: Dict[str, Any]):
        """Handle ColonisationConstructionDepot journal event"""
        return self.journal_handler.handle_colonisation_construction_depot(entry)
    
    def handle_colonisation_contribution(self, entry: Dict[str, Any]):
        """Handle ColonisationContribution journal event"""
        return self.journal_handler.handle_colonisation_contribution(entry)
    
    def handle_market(self, entry: Dict[str, Any]):
        """Handle Market journal event"""
        return self.journal_handler.handle_market(entry)
    
    def update_status(self, message: str):
        """Update the UI status label"""
        return self.ui_manager.update_status(message)
    
    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        return self.ui_manager.update_create_button()
    
    def get_system_address_from_journal(self) -> Optional[int]:
        """Get SystemAddress and other data from the most recent Docked event in the journal"""
        logger.debug("get_system_address_from_journal() called")
        try:
            import config
            
            import os
            import glob
            import json
            
            # Get journal directory from EDMC config
            journal_dir = None
            
            # Try different config methods
            try:
                journal_dir = config.get_str('journaldir')
                logger.debug(f"Got journal directory from config: {journal_dir}")
            except Exception as e:
                logger.debug(f"Error with config.get_str('journaldir'): {e}")
            
            # If that didn't work, try the default Elite Dangerous location
            if not journal_dir:
                try:
                    default_journal_dir = os.path.join(
                        os.path.expanduser('~'),
                        'Saved Games',
                        'Frontier Developments',
                        'Elite Dangerous'
                    )
                    logger.debug(f"Trying default journal location: {default_journal_dir}")
                    if os.path.exists(default_journal_dir):
                        journal_dir = default_journal_dir
                        logger.debug(f"Using default journal directory: {journal_dir}")
                    else:
                        logger.debug("Default journal directory doesn't exist")
                except Exception as e:
                    logger.debug(f"Error checking default location: {e}")
            
            if not journal_dir or not os.path.exists(journal_dir):
                logger.debug("No valid journal directory found")
                return None
            
            logger.debug(f"Using journal directory: {journal_dir}")
            
            # Find the most recent journal file
            journal_files = glob.glob(os.path.join(journal_dir, 'Journal.*.log'))
            logger.debug(f"Found {len(journal_files)} journal files")
            
            if not journal_files:
                logger.debug("No journal files found")
                return None
            
            # Sort by modification time, most recent first
            journal_files.sort(key=os.path.getmtime, reverse=True)
            
            # Search through up to the 3 most recent journal files
            max_files_to_check = 3
            files_to_check = journal_files[:max_files_to_check]
            logger.debug(f"Will check {len(files_to_check)} journal file(s)")
            
            for file_index, journal_file in enumerate(files_to_check):
                logger.debug(f"Reading journal file {file_index + 1}/{len(files_to_check)}")
                
                try:
                    # Read the file backwards looking for the most recent Docked event
                    with open(journal_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    
                    logger.debug(f"Read {len(lines)} lines from journal file {file_index + 1}")
                    
                    # Search backwards through the lines
                    docked_events_found = 0
                    for line in reversed(lines):
                        try:
                            entry = json.loads(line.strip())
                            if entry.get('event') == 'Docked':
                                docked_events_found += 1
                                
                                system_address = entry.get('SystemAddress')
                                system_name = entry.get('StarSystem')
                                star_pos = entry.get('StarPos')
                                
                                logger.debug(f"Found Docked event in file {file_index + 1}: SystemAddress={system_address}, StarSystem={system_name}")
                                
                                if system_address:
                                    logger.debug(f"Using SystemAddress from journal: {system_address}")
                                    
                                    # Also store system name and star position if available
                                    if system_name and not self.current_system:
                                        logger.debug(f"Storing StarSystem from journal: {system_name}")
                                        self.current_system = system_name
                                    
                                    if star_pos and not self.star_pos:
                                        logger.debug(f"Storing StarPos from journal: {star_pos}")
                                        self.star_pos = star_pos
                                    
                                    return system_address
                        except json.JSONDecodeError:
                            continue
                    
                    logger.debug(f"No valid Docked event in file {file_index + 1} (checked {docked_events_found} Docked events)")
                
                except Exception as e:
                    logger.debug(f"Error reading journal file {file_index + 1}: {e}")
                    continue
            
            logger.debug(f"No valid Docked event with SystemAddress found in any of the {len(files_to_check)} journal files checked")
            return None
        except Exception as e:
            logger.error(f"Exception in get_system_address_from_journal: {type(e).__name__}: {e}", exc_info=True)
            return None


def plugin_start3(plugin_dir: str) -> str:
    """
    Load the plugin.
    
    :param plugin_dir: The plugin directory
    :return: Plugin name
    """
    global this
    this = RavencolonialPlugin()
    logger.info(f"{PluginConfig.NAME} v{PluginConfig.VERSION} loaded")
    return PluginConfig.NAME


def plugin_stop() -> None:
    """
    Unload the plugin.
    """
    global this
    if this:
        # Remove our overlay messages from the game screen
        try:
            this.agent.overlay.clear()
        except Exception:
            pass
        # Signal worker thread to stop
        this.api_queue.put(None)
        # Wait for worker thread to finish (recommended by EDMC docs)
        if this.worker_thread and this.worker_thread.is_alive():
            this.worker_thread.join(timeout=5)  # 5 second timeout to avoid hanging
        logger.info(f"{PluginConfig.NAME} stopped")


def plugin_prefs(parent, cmdr: str, is_beta: bool):
    """Build the Settings tab (API key entry/validation + overlay options)."""
    global this
    import rca_settings
    return rca_settings.build(parent, this, cmdr, plugin_tl)


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """
    Handle preference changes. Called when user changes settings.
    Refresh UI elements if language changed.
    
    :param cmdr: Current commander name
    :param is_beta: Whether game is in beta
    """
    global this
    if this:
        # Persist settings-page values (API key, overlay options)
        try:
            import rca_settings
            rca_settings.save(this)
        except Exception:
            logger.exception("Failed to save settings")
        # Update button text in case language changed
        this.update_create_button()
        # Re-apply API key + overlay settings and redraw
        this.apply_api_key()
        this.agent.apply_settings()
        this.agent.refresh()


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """
    Create a frame for the main EDMC window.
    
    :param parent: The parent frame
    :return: A tk.Frame for display in main window
    """
    global this
    
    if not this:
        return tk.Frame(parent)
    
    # Use the UI manager to create the plugin frame
    frame = this.ui_manager.create_plugin_frame(parent)

    # Allow worker-thread fetches to request a main-thread redraw safely
    frame.bind(rca_agent.REDRAW_EVENT, lambda e: this.agent.refresh())

    # Keep the overlay alive even when EDMC isn't sending updates (Status.json can be
    # static while docked/idle, so dashboard_entry stops firing and the ttl lapses).
    _start_overlay_heartbeat(frame)

    return frame


# How often (ms) to re-send the overlay so it never times out while idle.
OVERLAY_HEARTBEAT_MS = 3000


def _start_overlay_heartbeat(widget: tk.Widget) -> None:
    """Self-rescheduling Tk timer that re-evaluates + re-sends the overlay.

    Runs regardless of journal/dashboard activity, so the overlay both persists while
    idle and stays consistent with the current docked/project state.
    """
    def beat():
        try:
            if config.shutting_down:
                return
        except Exception:
            pass
        if this:
            this.agent.refresh()
        try:
            widget.after(OVERLAY_HEARTBEAT_MS, beat)
        except Exception:
            pass

    try:
        widget.after(OVERLAY_HEARTBEAT_MS, beat)
    except Exception:
        pass


# Status.json Flags bit 0 == Docked (https://...the journal/status manual)
STATUS_FLAG_DOCKED = 1


def dashboard_entry(cmdr: str, is_beta: bool, entry: Dict[str, Any]) -> Optional[str]:
    """Handle a Status.json update (~1/s).

    This is also our reliable source of commander + docked state, because EDMC calls it
    on startup (even when the game is already docked, where no fresh journal Docked event
    is delivered). Flags bit 0 is the authoritative "docked" indicator.
    """
    global this
    if not this:
        return None

    # Commander becomes known here too -> triggers the active-projects fetch
    if cmdr:
        this.cmdr_name = cmdr
        this.on_cmdr_known(cmdr)

    # Authoritative docked state from Status.json flags
    flags = entry.get('Flags', 0) or 0
    this.is_docked = bool(flags & STATUS_FLAG_DOCKED)
    this.gui_focus = entry.get('GuiFocus', this.gui_focus)

    this.agent.refresh()
    return None


def journal_entry(
    cmdr: str, is_beta: bool, system: str, station: str, entry: Dict[str, Any], state: Dict[str, Any]
) -> Optional[str]:
    """
    Handle journal entry events.
    
    :param cmdr: Commander name
    :param is_beta: Whether in beta
    :param system: Current system
    :param station: Current station
    :param entry: The journal entry
    :param state: Current game state
    :return: Optional status message
    """
    global this
    
    if not this:
        return None
    
    # Update commander and location
    this.cmdr_name = cmdr
    this.current_system = system
    this.current_station = station

    # Ship cargo from EDMC's accumulated state (authoritative); keys are lowercase names.
    if state.get('Cargo') is not None:
        this.cargo = dict(state.get('Cargo') or {})
    if state.get('CargoCapacity'):
        this.cargo_capacity = state.get('CargoCapacity')

    # Per-commander API key + active-project fetch when the commander becomes known
    this.on_cmdr_known(cmdr)

    logger.debug(f"Journal entry - cmdr: {cmdr}, system: {system}, station: {station}")

    event = entry.get('event')
    
    # Handle different events
    if event == 'Docked':
        logger.info(f"Docked at {station}, MarketID: {entry.get('MarketID')}")
        this.current_market_id = entry.get('MarketID')
        this.current_system_address = entry.get('SystemAddress')
        this.star_pos = entry.get('StarPos')
        this.body_num = entry.get('BodyID')
        this.body_name = entry.get('Body')
        this.station_type = entry.get('StationType')
        this.faction_name = entry.get('StationFaction', {}).get('Name')
        this.is_docked = True
        # Check if this is a colonization ship - they appear as SurfaceStation but have ColonisationShip in the name
        station_name = entry.get('StationName', '')
        this.last_station_name = station_name
        this.last_station_services = entry.get('StationServices')
        this.is_construction_ship = 'ColonisationShip' in station_name
        logger.debug(f"Docked details - StationType: {this.station_type}, is_construction_ship: {this.is_construction_ship}")
        this.update_status(f"Docked at {station}")
        this.update_create_button()
        # Best-effort: if Market.json is already current for this station, learn what it
        # sells now so unavailable commodities grey out immediately (guarded by MarketID so
        # a stale file from a previous station is ignored — a Market event refreshes it).
        mid = entry.get('MarketID')
        if mid is not None:
            avail = rca_market.load_market_availability(market_id=mid)
            if avail:
                this.market_available = avail
                this.market_market_id = mid
        # Refresh active projects for this commander, then redraw the needs overlay
        this.agent.fetch_active_projects_async()
        this.agent.refresh()

    elif event == 'Undocked':
        logger.info(f"Undocked from {station}")
        this.is_docked = False
        this.is_construction_ship = False
        this.current_market_id = None
        this.last_station_name = None
        this.last_station_services = None
        this.market_available = set()
        this.market_market_id = None
        this._bodies_fetched = False  # Reset flag for next docking
        this.last_depot_state = {}  # Reset depot state for next docking
        this.update_status(f"Undocked from {station}")
        this.update_create_button()
        this.agent.refresh()

    elif event == 'Location':
        logger.info(f"Location event - system: {system}, station: {station}")
        this.current_system_address = entry.get('SystemAddress')
        this.star_pos = entry.get('StarPos')
        if entry.get('Docked'):
            this.current_market_id = entry.get('MarketID')
            this.body_num = entry.get('BodyID')
            this.body_name = entry.get('Body')
            this.station_type = entry.get('StationType')
            this.is_docked = True
            # Check if this is a colonization ship - they appear as SurfaceStation but have ColonisationShip in the name
            station_name = entry.get('StationName', '')
            this.last_station_name = station_name
            this.last_station_services = entry.get('StationServices')
            this.is_construction_ship = 'ColonisationShip' in station_name
            logger.info(f"Location event - docked at {station}, StationType: {this.station_type}, StationName: {station_name}, is_construction_ship: {this.is_construction_ship}")
            this.update_create_button()
        else:
            this.is_docked = False
            this.is_construction_ship = False
            this.current_market_id = None
            this.last_station_name = None
            this.last_station_services = None
            this.update_create_button()
        this.agent.fetch_active_projects_async()
        this.agent.refresh()

    elif event == 'CargoDepot':
        this.handle_cargo_depot(entry)

    elif event == 'Market':
        this.handle_market(entry)
        # Read Market.json to learn which commodities are sold here (Stock>0)
        market_id = entry.get('MarketID')
        this.market_available = rca_market.load_market_availability(market_id=market_id)
        this.market_market_id = market_id
        logger.info(f"Market {market_id}: {len(this.market_available)} commodities for sale "
                    f"(unavailable colony commodities will be greyed)")
        this.agent.refresh()

    elif event == 'Loadout':
        # Capture cargo capacity for the "trips" estimate in the overlay footer
        if entry.get('CargoCapacity') is not None:
            this.cargo_capacity = entry.get('CargoCapacity')

    elif event == 'Cargo':
        # Update cargo manifest (fallback; state['Cargo'] is preferred and set above)
        inventory = entry.get('Inventory')
        if inventory is not None:
            this.cargo = {rca_colony.normalize_name(item['Name']): item['Count'] for item in inventory}
        this.agent.refresh()

    elif event == 'ColonisationConstructionDepot':
        logger.debug("ColonisationConstructionDepot event received")
        this.handle_colonisation_construction_depot(entry)
        this.agent.refresh()

    elif event == 'ColonisationContribution':
        logger.debug("ColonisationContribution event received")
        this.handle_colonisation_contribution(entry)
        this.agent.refresh()

    return None


def open_url(url: str):
    """Open URL in browser"""
    webbrowser.open(url)


def open_project_link():
    """Open the existing project in browser"""
    global this
    if this and this.current_build_id:
        url = f"https://ravencolonial.com/#build={this.current_build_id}"
        logger.info(f"Opening project page: {url}")
        open_url(url)


def open_create_dialog(parent):
    """Open the Create Project dialog"""
    global this
    if this:
        try:
            dialog = create_project_dialog.CreateProjectDialog(parent, this)
        except Exception as e:
            logger.error(f"Failed to open create dialog: {e}", exc_info=True)
            messagebox.showerror(plugin_tl("Error"), plugin_tl("Failed to open dialog:") + f" {str(e)}")
