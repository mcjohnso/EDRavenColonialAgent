"""
UI Manager for the EDRavenColonialAgent plugin.

Handles the EDMC-window strip (status, project link, Create button) and the in-window
"commodities still needed" fallback panel shown when no in-game overlay is available.
"""

import tkinter as tk
from tkinter import ttk
import logging
from typing import Optional

import rca_colony as colony

logger = logging.getLogger(__name__)

# Foreground colors for the fallback panel rows (mirror the overlay palette)
_FG_TITLE = "#ffffff"
_FG_HEADER = "#ff8c00"
_FG_ITEM = "#cc8800"
_FG_SURPLUS = "#2faf2f"
_FG_DARK = "#888888"


class UIManager:
    """Manages UI elements and state for the Ravencolonial plugin"""
    
    def __init__(self, plugin_instance):
        """
        Initialize the UI manager
        
        :param plugin_instance: The main plugin instance
        """
        self.plugin = plugin_instance
        self.status_label: Optional[tk.Label] = None
        self.create_button: Optional[tk.Button] = None
        self.project_link_label: Optional[tk.Label] = None
        # fallback needs panel
        self.needs_frame: Optional[tk.Frame] = None
        self.needs_title: Optional[tk.Label] = None
        self.needs_body: Optional[tk.Label] = None
        self.needs_footer: Optional[tk.Label] = None
        self._needs_visible = False

    def create_plugin_frame(self, parent: tk.Frame) -> tk.Frame:
        """
        Create the main plugin frame for EDMC

        :param parent: The parent frame
        :return: The created frame
        """
        frame = tk.Frame(parent)
        self.plugin.frame = frame

        # Top row: status + project link + Create button
        top = tk.Frame(frame)
        top.pack(side=tk.TOP, fill=tk.X)

        self.status_label = tk.Label(top, text="Ravencolonial: Ready")
        self.status_label.pack(side=tk.LEFT, padx=5)
        self.plugin.status_label = self.status_label

        # Project link label (shows when project exists)
        self.project_link_label = tk.Label(top, text="", cursor="hand2", fg='blue')
        self.project_link_label.pack(side=tk.LEFT, padx=5)
        self.project_link_label.bind("<Button-1>", lambda e: self._open_project_link())
        self.plugin.project_link_label = self.project_link_label
        self.plugin.current_build_id = None

        # Create project button
        self.create_button = tk.Button(
            top,
            text="Create Project (Dock First)",
            command=lambda: self._open_create_dialog(parent),
            state=tk.DISABLED
        )
        self.create_button.pack(side=tk.LEFT, padx=5)
        self.plugin.create_button = self.create_button

        # Fallback needs panel (packed/unpacked on demand by update_needs_panel)
        self.needs_frame = tk.Frame(frame)
        self.needs_title = tk.Label(self.needs_frame, anchor=tk.W, justify=tk.LEFT,
                                    fg=_FG_TITLE, font=("TkDefaultFont", 9, "bold"))
        self.needs_title.pack(side=tk.TOP, fill=tk.X, padx=5)
        self.needs_body = tk.Label(self.needs_frame, anchor=tk.W, justify=tk.LEFT,
                                   font=("TkFixedFont", 8))
        self.needs_body.pack(side=tk.TOP, fill=tk.X, padx=5)
        self.needs_footer = tk.Label(self.needs_frame, anchor=tk.W, justify=tk.LEFT,
                                     fg=_FG_ITEM, font=("TkDefaultFont", 8))
        self.needs_footer.pack(side=tk.TOP, fill=tk.X, padx=5)

        return frame

    def update_needs_panel(self, needs, ctx, visible: bool):
        """Render (or hide) the in-window fallback needs panel.

        A single monospace Label shows the rows; per-row color isn't possible in one
        Label, so we color the body by the most-constrained state and keep the layout
        readable. The in-game overlay remains the rich, color-coded surface.
        """
        if not self.needs_frame:
            return

        if not visible or needs is None or ctx is None:
            if self._needs_visible:
                self.needs_frame.pack_forget()
                self._needs_visible = False
            return

        # title
        title = ctx.header or "Colony needs"
        if getattr(ctx, "construction_complete", False):
            self.needs_title['text'] = title
            self.needs_body['text'] = "Construction complete ✓"
            self.needs_footer['text'] = ""
        else:
            self.needs_title['text'] = title
            self.needs_body['text'] = self._format_rows(needs, ctx)
            total = needs.total_remaining()
            footer = f"{total:,} remaining"
            if ctx.cargo_capacity:
                import math
                footer += f"   {math.ceil(total / ctx.cargo_capacity):,} trips"
            self.needs_footer['text'] = footer

        if not self._needs_visible:
            self.needs_frame.pack(side=tk.TOP, fill=tk.X)
            self._needs_visible = True

    def _format_rows(self, needs, ctx) -> str:
        """Build the monospace body text for the fallback panel."""
        lines = []
        if ctx.docked_at_site:
            groups = [("", colony.sorted_needs(needs))]
        else:
            groups = colony.grouped_needs(needs)
        for cat, items in groups:
            if cat:
                lines.append(cat)
            for name, need in items:
                have = (ctx.cargo or {}).get(name, 0)
                mark = " ✓" if have >= need and need > 0 else ""
                disp = colony.display_name(name)
                have_txt = f"  ({have})" if have > 0 else ""
                lines.append(f"  {disp[:20]:<20} {need:>6}{have_txt}{mark}")
        return "\n".join(lines) if lines else "Nothing needed"

    def update_status(self, message: str):
        """
        Update the UI status label
        
        :param message: The status message to display
        """
        if self.status_label:
            self.status_label['text'] = message
            logger.info(message)
    
    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        logger.debug(f"update_create_button - is_docked: {self.plugin.is_docked}, market_id: {self.plugin.current_market_id}, is_construction_ship: {self.plugin.is_construction_ship}")
        
        if not self.create_button:
            return
        
        # Check if we're at a construction ship
        if self.plugin.is_docked and self.plugin.current_market_id and self.plugin.is_construction_ship:
            # Get system address if we don't have it
            if not self.plugin.current_system_address:
                logger.debug("No system_address, fetching from journal for project check")
                self.plugin.current_system_address = self.plugin.get_system_address_from_journal()
            
            # Check for existing project
            if self.plugin.current_system_address:
                existing_project = self.plugin.check_existing_project(self.plugin.current_system_address, self.plugin.current_market_id)
            else:
                logger.warning("Could not get system_address, unable to check for existing project")
                existing_project = None
            
            if existing_project:
                # Project exists - change button to open build page
                build_id = existing_project.get('buildId', '')
                build_name = existing_project.get('buildName', 'Unknown')
                logger.info(f"Found existing project: {build_name} ({build_id})")
                
                self.create_button['state'] = tk.NORMAL
                self.create_button['text'] = "🌐 Open Build Page"
                # Change button command to open project link
                self.create_button['command'] = lambda: self._open_project_link()
                
                if self.project_link_label:
                    link_text = f"{build_name}"
                    self.project_link_label['text'] = link_text
                    self.project_link_label['fg'] = 'blue'
                    self.project_link_label['cursor'] = 'hand2'
                
                # Store build_id for click handler
                self.plugin.current_build_id = build_id
            else:
                # No project exists - fetch body data then enable button
                logger.info("No existing project found")
                
                # Clear project link
                if self.project_link_label:
                    self.project_link_label['text'] = ""
                    self.plugin.current_build_id = None
                
                # Fetch body data in background for future use
                if self.plugin.current_system and not hasattr(self.plugin, '_bodies_fetched'):
                    logger.debug("Pre-fetching body data for Create dialog")
                    # Get system address from journal if needed
                    if not self.plugin.current_system_address:
                        self.plugin.current_system_address = self.plugin.get_system_address_from_journal()
                    self.plugin._bodies_fetched = True
                
                # Enable create button and restore original command
                logger.debug("Enabling Create Project button")
                self.create_button['state'] = tk.NORMAL
                self.create_button['text'] = "🚧 Create Project"
                # Restore original command to open create dialog
                if self.plugin.frame:
                    self.create_button['command'] = lambda: self._open_create_dialog(self.plugin.frame.master)
        else:
            # Not at construction ship - disable button and restore original command
            logger.debug("Disabling Create Project button")
            self.create_button['state'] = tk.DISABLED
            
            # Restore original command to open create dialog
            if self.plugin.frame:
                self.create_button['command'] = lambda: self._open_create_dialog(self.plugin.frame.master)
            
            if self.project_link_label:
                self.project_link_label['text'] = ""
                self.plugin.current_build_id = None
            
            if not self.plugin.is_docked:
                self.create_button['text'] = "Create Project (Dock First)"
            elif not self.plugin.is_construction_ship:
                self.create_button['text'] = "Create Project (Dock at Construction Ship)"
            else:
                self.create_button['text'] = "Create Project"
    
    def _open_project_link(self):
        """Open the existing project in browser"""
        if self.plugin and self.plugin.current_build_id:
            import webbrowser
            url = f"https://ravencolonial.com/#build={self.plugin.current_build_id}"
            logger.info(f"Opening project page: {url}")
            webbrowser.open(url)
    
    def _open_create_dialog(self, parent):
        """Open the Create Project dialog"""
        if self.plugin:
            try:
                import create_project_dialog
                dialog = create_project_dialog.CreateProjectDialog(parent, self.plugin)
            except Exception as e:
                logger.error(f"Failed to open create dialog: {e}", exc_info=True)
                from tkinter import messagebox
                messagebox.showerror("Error", f"Failed to open dialog: {str(e)}")
