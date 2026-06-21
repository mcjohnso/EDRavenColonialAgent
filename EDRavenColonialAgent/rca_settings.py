"""
Settings tab for the EDRavenColonialAgent plugin.

Priority field: the per-commander Raven Colonial **API key** (sent as the ``rcc-key``
header). Validated live against ``GET /api/cmdr/`` which returns the linked commander's
display name. Users generate the key at https://ravencolonial.com/user.

Also exposes overlay options (enable, window fallback, off-site view, anchor x/y).

EDMC calls plugin_prefs(parent, cmdr, is_beta) -> our build(); prefs_changed() -> our save().
Network validation runs on the plugin's worker thread and hops back to the Tk thread via
event_generate (the only thread-safe Tk call off-thread).
"""

import logging
import tkinter as tk
import webbrowser

import myNotebook as nb

logger = logging.getLogger(__name__)

# EDMC's themed entry widget is `EntryMenu` in current versions and `Entry` in older
# ones; fall back to a plain tk.Entry if neither is present.
_Entry = getattr(nb, "Entry", None) or getattr(nb, "EntryMenu", None) or tk.Entry


def _set_fg(widget, color):
    """Set a label's text color. EDMC's nb widgets are ttk-based and reject the classic
    'fg' alias, so use 'foreground' and never let a theming quirk break the flow."""
    try:
        widget.configure(foreground=color)
    except Exception:
        pass

KEY_USER_URL = "https://ravencolonial.com/user"
VALIDATED_EVENT = "<<EdrcaKeyValidated>>"

# Module-level handles so prefs_changed -> save() can read the widgets.
_vars = {}
_plugin = None
_cmdr_label = None
_api_entry = None
_validation = {"key": None, "cmdr": None}  # last validation result


def build(parent, plugin, cmdr, tl):
    """Build and return the settings frame."""
    global _vars, _plugin, _cmdr_label, _api_entry
    _plugin = plugin
    _vars = {}

    from config import config

    frame = nb.Frame(parent)
    frame.columnconfigure(1, weight=1)
    row = 0

    nb.Label(frame, text="Raven Colonial integration").grid(
        row=row, column=0, columnspan=3, padx=8, pady=(8, 2), sticky=tk.W)
    row += 1

    # --- API key -------------------------------------------------------------------------
    nb.Label(frame, text="API key:").grid(row=row, column=0, padx=8, pady=2, sticky=tk.W)

    keys = plugin.get_api_keys() if plugin else {}
    current_key = keys.get((plugin.cmdr_name if plugin else None) or cmdr or "", "")
    _vars["api_key"] = tk.StringVar(master=frame, value=current_key)
    _api_entry = _Entry(frame, textvariable=_vars["api_key"])
    _api_entry.grid(row=row, column=1, padx=8, pady=2, sticky=tk.EW)
    _api_entry.bind("<FocusOut>", lambda e: _validate(plugin))
    nb.Button(frame, text="Validate", command=lambda: _validate(plugin)).grid(
        row=row, column=2, padx=8, pady=2, sticky=tk.W)
    row += 1

    # validation result (linked commander or error)
    _cmdr_label = nb.Label(frame, text="")
    _cmdr_label.grid(row=row, column=1, columnspan=2, padx=8, pady=(0, 2), sticky=tk.W)
    _cmdr_label.bind(VALIDATED_EVENT, lambda e: _show_validation())
    row += 1

    try:
        from ttkHyperlinkLabel import HyperlinkLabel
        HyperlinkLabel(frame, text="Get your API key (ravencolonial.com/user)",
                       url=KEY_USER_URL).grid(
            row=row, column=1, columnspan=2, padx=8, pady=(0, 8), sticky=tk.W)
    except Exception:
        link = nb.Label(frame, text=KEY_USER_URL, cursor="hand2")
        _set_fg(link, "blue")
        link.grid(row=row, column=1, columnspan=2, padx=8, pady=(0, 8), sticky=tk.W)
        link.bind("<Button-1>", lambda e: webbrowser.open(KEY_USER_URL))
    row += 1

    # --- overlay options -----------------------------------------------------------------
    nb.Label(frame, text="Commodities overlay").grid(
        row=row, column=0, columnspan=3, padx=8, pady=(8, 2), sticky=tk.W)
    row += 1

    _vars["enabled"] = tk.BooleanVar(master=frame, value=config.get_bool("edrca_enabled", default=True))
    nb.Checkbutton(frame, text="Show colony commodities needed",
                   variable=_vars["enabled"]).grid(row=row, column=0, columnspan=3, padx=8, sticky=tk.W)
    row += 1

    _vars["overlay_enabled"] = tk.BooleanVar(master=frame, value=config.get_bool("edrca_overlay_enabled", default=True))
    nb.Checkbutton(frame, text="Draw in-game overlay (needs EDMCOverlay / EDMCModernOverlay)",
                   variable=_vars["overlay_enabled"]).grid(row=row, column=0, columnspan=3, padx=8, sticky=tk.W)
    row += 1

    _vars["window_panel"] = tk.BooleanVar(master=frame, value=config.get_bool("edrca_window_panel", default=False))
    nb.Checkbutton(frame, text="Also show needs panel in this window",
                   variable=_vars["window_panel"]).grid(row=row, column=0, columnspan=3, padx=8, sticky=tk.W)
    row += 1

    # Grid-only layout: EDMC's nb.Frame already manages internal children with grid,
    # so mixing pack() anywhere inside this dialog raises a TclError.
    nb.Label(frame, text="Overlay position  x:").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_x"] = tk.IntVar(master=frame, value=config.get_int("edrca_overlay_x") or 20)
    _Entry(frame, textvariable=_vars["overlay_x"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1
    nb.Label(frame, text="Overlay position  y:").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_y"] = tk.IntVar(master=frame, value=config.get_int("edrca_overlay_y") or 180)
    _Entry(frame, textvariable=_vars["overlay_y"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1
    # Column layout (overlay virtual px / chars). Bigger = wider overlay; bump these if the
    # Need/Ship columns look cramped on a high-DPI or scaled display.
    nb.Label(frame, text="Max name length (chars):").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_name_chars"] = tk.IntVar(
        master=frame, value=config.get_int("edrca_overlay_name_chars") or 22)
    _Entry(frame, textvariable=_vars["overlay_name_chars"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1
    nb.Label(frame, text="Need column offset:").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_need_x"] = tk.IntVar(
        master=frame, value=config.get_int("edrca_overlay_need_x") or 160)
    _Entry(frame, textvariable=_vars["overlay_need_x"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1
    nb.Label(frame, text="Ship column offset:").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_have_x"] = tk.IntVar(
        master=frame, value=config.get_int("edrca_overlay_have_x") or 290)
    _Entry(frame, textvariable=_vars["overlay_have_x"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1
    nb.Label(frame, text="Background row height:").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_bg_row_h"] = tk.IntVar(
        master=frame, value=config.get_int("edrca_overlay_bg_row_h") or 22)
    _Entry(frame, textvariable=_vars["overlay_bg_row_h"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1
    nb.Label(frame, text="Background width %:").grid(
        row=row, column=0, padx=8, pady=2, sticky=tk.W)
    _vars["overlay_bg_width_pct"] = tk.IntVar(
        master=frame, value=config.get_int("edrca_overlay_bg_width_pct") or 100)
    _Entry(frame, textvariable=_vars["overlay_bg_width_pct"], width=6).grid(
        row=row, column=1, padx=8, pady=2, sticky=tk.W)
    row += 1

    # validate any pre-existing key on open
    if current_key:
        _validate(plugin)

    return frame


def _validate(plugin):
    """Kick off background validation of the currently entered key."""
    if not _api_entry or not plugin:
        return
    key = _vars["api_key"].get().strip()
    if not key:
        _validation.update(key=None, cmdr=None)
        _show_validation()
        return
    if _cmdr_label:
        _cmdr_label['text'] = "Checking…"
        _set_fg(_cmdr_label, "gray")

    def work():
        cmdr = plugin.api_client.get_cmdr_by_api_key(key)
        _validation.update(key=key, cmdr=cmdr)
        # hop back to the Tk thread to update the label
        try:
            if _cmdr_label is not None:
                _cmdr_label.event_generate(VALIDATED_EVENT, when="tail")
        except Exception:
            pass

    plugin.queue_api_call(work)


def _show_validation():
    """Update the result label from the latest validation (runs on the Tk thread)."""
    if not _cmdr_label:
        return
    key = _vars["api_key"].get().strip() if "api_key" in _vars else ""
    if not key:
        _cmdr_label['text'] = ""
        return
    if _validation.get("key") != key:
        return  # stale result for an older key
    cmdr = _validation.get("cmdr")
    if cmdr:
        _cmdr_label['text'] = f"✓ Linked: {cmdr}"
        _set_fg(_cmdr_label, "green")
    else:
        _cmdr_label['text'] = "(invalid key)"
        _set_fg(_cmdr_label, "red")


def save(plugin):
    """Persist settings-page values to EDMC config (called from prefs_changed)."""
    if not _vars or not plugin:
        return
    import json
    from config import config

    # API key -> per-commander map
    key = _vars["api_key"].get().strip()
    cmdr = plugin.cmdr_name or ""
    keys = plugin.get_api_keys()
    if key:
        keys[cmdr] = key
    else:
        keys.pop(cmdr, None)
    config.set("edrca_api_keys", json.dumps(keys))

    config.set("edrca_enabled", _vars["enabled"].get())
    config.set("edrca_overlay_enabled", _vars["overlay_enabled"].get())
    config.set("edrca_window_panel", _vars["window_panel"].get())
    try:
        config.set("edrca_overlay_x", int(_vars["overlay_x"].get()))
        config.set("edrca_overlay_y", int(_vars["overlay_y"].get()))
        config.set("edrca_overlay_name_chars", int(_vars["overlay_name_chars"].get()))
        config.set("edrca_overlay_need_x", int(_vars["overlay_need_x"].get()))
        config.set("edrca_overlay_have_x", int(_vars["overlay_have_x"].get()))
        config.set("edrca_overlay_bg_row_h", int(_vars["overlay_bg_row_h"].get()))
        config.set("edrca_overlay_bg_width_pct", int(_vars["overlay_bg_width_pct"].get()))
    except (tk.TclError, ValueError):
        pass
