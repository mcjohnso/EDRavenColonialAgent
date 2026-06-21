"""
In-game overlay renderer for the "commodities still needed" panel.

Ports the visual design of SrvSurvey's PlotBuildCommodities to the EDMCOverlay /
EDMCModernOverlay text API (`edmcoverlay`). That overlay plugin is provided at runtime by
the user and may be absent, so everything here degrades gracefully: a failed/absent
overlay never raises, and `available` lets load.py fall back to the EDMC-window panel.

The layout (`build_lines`) is a pure function of a Needs model + context, so it is
unit-testable without `edmcoverlay`. The Overlay class is a thin, resilient wrapper that
sends those lines and keeps them alive.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import rca_colony as colony

# Log through EDMC's plugin-logger namespace so these lines actually appear in
# EDMarketConnector.log; fall back to the module logger under tests (no `config`).
try:
    from config import appname as _appname
    logger = logging.getLogger(f"{_appname}.EDRavenColonialAgent")
except Exception:
    logger = logging.getLogger(__name__)

# --- palette (approximates SrvSurvey's C.Colonise.* using overlay-safe hex) --------------
COL_TITLE = "#ffffff"      # project title
COL_HEADER = "#ff8c00"     # column / category headers (orange)
COL_ITEM = "#ffa500"       # default commodity (orange)
COL_SURPLUS = "#44dd44"    # have enough (green)            -> C.Colonise.surplus
COL_DARK = "#7a7a7a"       # needed but not sold here (dim) -> C.Colonise.itemDark
COL_PENDING = "#00d7d7"    # updating (cyan)                -> C.cyan
COL_WARN = "#ffd700"       # warnings (yellow)

CHECK = "✓"           # ✓  have-enough marker (broad font coverage)

# Message-id prefix for everything we send. Deliberately NOT "edrca_": EDMCModernOverlay
# applies a position-normalising group transform to any message whose id matches a
# registered plugin group, and a stale "edrca_" group entry persists in its
# overlay_groupings.json. Using an unmatched prefix keeps our messages UNGROUPED, so the
# x/y we send are honoured directly (group transforms were silently absorbing our column
# offsets). We draw our own background instead (see Overlay._send_background).
OVERLAY_ID_PREFIX = "rcaov_"

# Translucent near-black background (#AARRGGBB, alpha first). EDMCModernOverlay draws a SOLID
# filled rect behind a "plugin group" (sized to the group's measured bounds) — the only way to
# get a gap-free fill (a self-drawn rect mis-scales/clamps; tiled glyphs leave stripes). To get
# that fill WITHOUT subjecting the real text to the group's position transform, we put a single
# invisible spaces-only marker in a SEPARATE group (BG_ID_PREFIX); the text keeps its own
# ungrouped prefix (OVERLAY_ID_PREFIX) and is untouched.
BG_FILL = "#C8000010"
BG_ID_PREFIX = "rcabg_"

MAX_ROWS = 60              # safety cap on commodity rows sent to the overlay
REFRESH_SECS = 2           # min seconds between overlay re-sends (keep-alive throttle)
TTL = 8                    # message ttl (> heartbeat interval so it never flickers out)


@dataclass
class OverlayGeometry:
    anchor_x: int = 20
    anchor_y: int = 180
    # line_height is retained for settings compatibility but no longer drives layout:
    # rows are emitted as multi-line messages so the overlay's own font metrics control
    # vertical spacing (the only DPI-safe option — see build_lines).
    line_height: int = 14
    name_indent: int = 4
    # Column x-offsets (relative to anchor_x), in the overlay's 1280-wide virtual space.
    # They're spaced generously because text *width* scales by viewport×device_ratio while
    # these offsets scale by viewport only — so on a HiDPI/scaled display the rendered text
    # is wider than the offsets imply. Wide gaps + bounded names absorb that, and a wider
    # overall panel reads better than a cramped one.
    need_x: int = 160          # x of the "Need" column (room for ~22-char names before it)
    have_x: int = 290          # x of the "Ship/Have" column (gap clears a 6+ digit need)
    name_max_chars: int = 22   # truncate data-row names so they don't reach the Need column
    # Self-drawn background box geometry (virtual px). Generous on purpose: text renders
    # wider/taller than these virtual units (font scales by device_ratio, the rect doesn't),
    # so the box must over-reach to stay *around* the text. bg_row_h is the tunable height
    # knob; if the box is too short/tall, adjust it in settings.
    bg_pad: int = 12           # margin around the text block
    bg_num_w: int = 100        # extra width past the rightmost column for its numbers
    bg_char_w: int = 12        # est. virtual width per character (for the name column width)
    bg_row_h: int = 22         # virtual height per row (drives box height; tune to taste)
    # EDMCModernOverlay renders a plugin rect's *width* compressed relative to scaled text in
    # FILL scaling mode (the inverse-group-scale path), so on a wide/FILL display the box comes
    # out too narrow. bg_width_pct lets the user stretch the box width to compensate
    # (100 = no change; ~250-300 typical on an ultra-wide in FILL mode).
    bg_width_pct: int = 100


@dataclass
class OverlayContext:
    """Everything (besides Needs) required to render the panel."""
    header: str = ""
    project_names: List[str] = field(default_factory=list)  # used when >1 project
    docked_at_site: bool = False
    construction_complete: bool = False
    untracked_site: bool = False
    cargo: Dict[str, int] = field(default_factory=dict)       # ship cargo by internal name
    market_available: Set[str] = field(default_factory=set)   # names sold at docked market
    market_valid: bool = False                                # market_available is current
    cargo_capacity: int = 0


@dataclass
class _Line:
    id: str
    text: str
    color: str
    x: int
    y: int
    size: str = "normal"


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


# A logical table cell: its text and color (("", None) means "blank in this row").
_Cell = "tuple"  # (str, Optional[str])

# Column indices into a row's cells.
COL_NAME = 0
COL_NEED = 1
COL_SHIP = 2


@dataclass
class _Row:
    """One logical table row: name / need / ship cells, each (text, color)."""
    cells: List[tuple]  # exactly 3: [(name,color), (need,color), (ship,color)]


def build_rows(needs: colony.Needs, ctx: OverlayContext,
               geom: Optional[OverlayGeometry] = None) -> List[_Row]:
    """Pure layout model: turn a Needs model + context into logical table rows.

    This is the unit-testable core (no overlay coordinates). `build_lines` transposes
    these rows into the multi-line column messages actually sent to the overlay.
    """
    g = geom or OverlayGeometry()
    rows: List[_Row] = []

    def row(name=("", None), need=("", None), ship=("", None)):
        rows.append(_Row([name, need, ship]))

    # --- title --------------------------------------------------------------------------
    row(name=(ctx.header or "Colony needs", COL_TITLE))

    if ctx.construction_complete:
        row(name=("Construction complete " + CHECK, COL_SURPLUS))
        return rows

    # multi-project listing
    if len(ctx.project_names) > 1:
        for name in ctx.project_names[:8]:
            row(name=("> " + _truncate(name, g.name_max_chars + 8), COL_ITEM))

    if ctx.untracked_site:
        row(name=("! Untracked project", COL_WARN))

    data = _collect_rows(needs, ctx)
    if not data:
        row(name=("Nothing needed", COL_ITEM))
        return rows

    show_have = any(have > 0 for _, _, have in data)

    # column header row
    row(name=("Commodity", COL_HEADER),
        need=("Need", COL_HEADER),
        ship=("Ship", COL_HEADER) if show_have else ("", None))

    # Alpha list when docked at the construction site; grouped-by-category otherwise.
    if ctx.docked_at_site:
        groups = [("", colony.sorted_needs(needs))]
    else:
        groups = colony.grouped_needs(needs)

    emitted = 0
    for cat, items in groups:
        if cat:
            row(name=(cat, COL_HEADER))
        for name, need in items:
            if emitted >= MAX_ROWS:
                break
            have = ctx.cargo.get(name, 0)
            color = _row_color(name, need, have, ctx)
            disp = colony.display_name(name)
            check = (" " + CHECK) if have >= need and need > 0 else ""
            row(name=(_truncate(disp, g.name_max_chars) + check, color),
                need=(f"{need:,}", color),
                ship=(f"{have:,}", color) if (show_have and have > 0) else ("", None))
            emitted += 1

    # --- footer -------------------------------------------------------------------------
    total = needs.total_remaining()
    footer = f"{total:,} remaining"
    if ctx.cargo_capacity > 0:
        import math
        trips = math.ceil(total / ctx.cargo_capacity)
        footer += f"  ·  {trips:,} trips"
    row(name=(footer, COL_ITEM))

    return rows


def _column_blocks(rows: List[_Row], col: int, x: int, y: int, start_id: int) -> List[_Line]:
    """Transpose one column into multi-line messages, one per color.

    Each message is a `\\n`-joined string spanning the rows (blank where that row isn't
    this color), so overlaying the per-color messages reproduces a per-row-colored
    column. Crucially, the overlay paints each line at `baseline + lineSpacing*idx` using
    its *own* font metrics, so vertical spacing is always correct regardless of display
    DPI/scaling (a fixed pixel line-height can't be — the font scales by device_ratio but
    a hand-computed y does not).
    """
    # Preserve first-seen color order for stable message ids across redraws.
    colors: List[str] = []
    for r in rows:
        text, color = r.cells[col]
        if text and color and color not in colors:
            colors.append(color)

    blocks: List[_Line] = []
    for i, color in enumerate(colors):
        last = -1
        for idx, r in enumerate(rows):
            text, c = r.cells[col]
            if text and c == color:
                last = idx
        if last < 0:
            continue
        parts = []
        for idx in range(last + 1):
            text, c = rows[idx].cells[col]
            parts.append(text if (text and c == color) else "")
        blocks.append(_Line(f"{OVERLAY_ID_PREFIX}{start_id + i}", "\n".join(parts), color, x, y))
    return blocks


def normalize_geometry(geom: OverlayGeometry):
    """Return (anchor_x, anchor_y, need_x, have_x).

    The only correction is keeping the Need column left of Ship (swap if a user inverted
    the offsets). Position is otherwise honoured exactly — the panel can be placed
    anywhere, including past the 1280 base canvas on ultra-wide displays whose usable
    overlay width is wider than 1280.
    """
    need_x, have_x = geom.need_x, geom.have_x
    if need_x > have_x:                       # Need must be left of Ship
        need_x, have_x = have_x, need_x
    return geom.anchor_x, geom.anchor_y, need_x, have_x


def build_lines(needs: colony.Needs, ctx: OverlayContext,
                geom: Optional[OverlayGeometry] = None) -> List[_Line]:
    """Renderable overlay messages: multi-line column blocks at fixed x, shared top y.

    All blocks share the same top `y` (anchor_y); the overlay stacks lines within each
    block by its font's line spacing, keeping columns row-aligned and overlap-free.
    """
    g = geom or OverlayGeometry()
    rows = build_rows(needs, ctx, g)
    anchor_x, y, need_x, have_x = normalize_geometry(g)
    columns = [
        (COL_NAME, anchor_x),
        (COL_NEED, anchor_x + need_x),
        (COL_SHIP, anchor_x + have_x),
    ]
    # Reserve a fixed id band per column so a block's id is stable across redraws even
    # when the set of colors present changes (keeps the overlay's id bookkeeping clean).
    ID_BAND = 16
    lines: List[_Line] = []
    for col, x in columns:
        lines.extend(_column_blocks(rows, col, x, y, col * ID_BAND))
    return lines


def background_rect(lines: List[_Line], geom: Optional[OverlayGeometry] = None):
    """Return (x, y, w, h) for a translucent box that encloses the column blocks.

    Sized in the same virtual space as the text. Because the box must enclose text that
    renders wider/taller than virtual units (font scales by device_ratio, the rect does
    not), the right edge is the larger of (rightmost column + number allowance) and (an
    estimate of the name column's own width), and the height is row_count * bg_row_h.
    Returns None when there's nothing to draw.
    """
    if not lines:
        return None
    g = geom or OverlayGeometry()
    row_count = max((ln.text.count("\n") + 1 for ln in lines), default=0)
    if row_count <= 0:
        return None
    # Derive bounds from the actual (already canvas-normalized) line positions, not from
    # geom.anchor_x, so the box follows whatever build_lines positioned.
    min_x = min(ln.x for ln in lines)
    max_x = max(ln.x for ln in lines)
    top_y = min(ln.y for ln in lines)
    max_line_len = max((len(s) for ln in lines for s in ln.text.split("\n")), default=0)
    right_cols = max_x + g.bg_num_w
    right_names = min_x + max_line_len * g.bg_char_w
    left = min_x - g.bg_pad
    top = top_y - g.bg_pad
    right = max(right_cols, right_names) + g.bg_pad   # follow the columns, wherever they are
    bottom = top_y + row_count * g.bg_row_h + g.bg_pad
    width = int((right - left) * max(1, g.bg_width_pct) / 100)   # compensate FILL-mode rect squish
    return (left, top, width, bottom - top)


def _collect_rows(needs: colony.Needs, ctx: OverlayContext):
    """[(name, need, have), ...] for every still-needed commodity (order not important)."""
    rows = []
    for name, need in needs.commodities.items():
        if need > 0:
            rows.append((name, need, ctx.cargo.get(name, 0)))
    return rows


def _row_color(name: str, need: int, have: int, ctx: OverlayContext) -> str:
    if have >= need and need > 0:
        return COL_SURPLUS
    if ctx.market_valid and ctx.market_available and name not in ctx.market_available:
        # needed here, but this station's market does not sell it -> dim
        return COL_DARK
    return COL_ITEM


class Overlay:
    """Resilient wrapper around the runtime-provided edmcoverlay plugin."""

    def __init__(self, geometry: Optional[OverlayGeometry] = None):
        self.geometry = geometry or OverlayGeometry()
        self.enabled = True
        self.available = False
        self._ov = None
        self._last_lines: List[_Line] = []
        self._used_ids: Set[str] = set()
        self._visible = False
        self._last_send = 0.0
        self._bg_id = BG_ID_PREFIX + "box"       # invisible marker the overlay fills behind
        self._logged_geom = None                 # last geometry tuple we logged
        self._group_registered = False           # EDMCModernOverlay bg group set up
        self._group_unavailable = False           # not EDMCModernOverlay -> no solid bg

    # -- background ----------------------------------------------------------------------
    def _register_bg_group(self) -> None:
        """Ask EDMCModernOverlay to fill a solid translucent rect behind our bg marker.

        Best-effort: a no-op on plain EDMCOverlay (no such API). anchor=nw + no offset means
        zero repositioning; the rect is sized to the marker's measured bounds.
        """
        if self._group_registered or self._group_unavailable:
            return
        try:
            from overlay_plugin.overlay_api import define_plugin_group  # EDMCModernOverlay
        except Exception:
            self._group_unavailable = True
            return
        try:
            define_plugin_group(
                plugin_name="EDRavenColonialAgent",
                plugin_matching_prefixes=[BG_ID_PREFIX],
                plugin_group_name="needs-bg",
                plugin_group_prefixes=(BG_ID_PREFIX,),
                plugin_group_anchor="nw",
                payload_justification="left",
                plugin_group_background_color=BG_FILL,
            )
            self._group_registered = True
            logger.info("Registered EDMCModernOverlay background group")
        except Exception as e:
            logger.debug(f"bg group not ready: {e}")

    def _send_background(self, lines: List[_Line]) -> None:
        """Place one invisible spaces-only marker spanning the panel; the overlay fills a
        solid translucent rect behind it (the marker is in its own group, so the real text
        — a different, ungrouped prefix — is never transformed).

        Sent before the text each render so the fill paints underneath.
        """
        if not self._ov or not lines:
            return
        self._register_bg_group()
        if not self._group_registered:
            return   # plain EDMCOverlay: no solid-fill API, skip the background
        g = self.geometry
        rect = background_rect(lines, g)
        if rect is None:
            return
        left, _, width, _ = rect
        top_y = min(ln.y for ln in lines)
        row_count = max((ln.text.count("\n") + 1 for ln in lines), default=0)
        n = max(1, round(width / max(1, g.bg_char_w)))   # spaces to span the panel width
        spaces = " " * n
        text = "\n".join([spaces] * row_count)           # invisible: defines the fill bounds
        try:
            self._ov.send_message(self._bg_id, text, BG_FILL, left, top_y, ttl=TTL, size="normal")
        except Exception as e:
            logger.debug(f"overlay background send failed: {e}")
            self._drop()

    # -- connection ----------------------------------------------------------------------
    def _connect(self) -> bool:
        """Lazily import + connect; never raise. Returns True if usable."""
        if self._ov is not None:
            return True
        try:
            from edmcoverlay import Overlay as _EdmcOverlay  # provided at runtime
            ov = _EdmcOverlay()
            connect = getattr(ov, "connect", None)
            if callable(connect):
                try:
                    connect()
                except Exception:
                    pass  # some forks connect lazily on first send
            self._ov = ov
            self.available = True
            return True
        except Exception as e:
            logger.debug(f"edmcoverlay not available: {e}")
            self._ov = None
            self.available = False
            return False

    def _drop(self):
        self._ov = None
        self.available = False

    def _send(self, line: _Line) -> bool:
        if not self._connect():
            return False
        try:
            self._ov.send_message(line.id, line.text, line.color, line.x, line.y,
                                  ttl=TTL, size=line.size)
            return True
        except Exception as e:
            logger.debug(f"overlay send failed, will reconnect: {e}")
            self._drop()
            return False

    # -- public API ----------------------------------------------------------------------
    def update_geometry(self, anchor_x: Optional[int] = None,
                        anchor_y: Optional[int] = None,
                        line_height: Optional[int] = None,
                        need_x: Optional[int] = None,
                        have_x: Optional[int] = None,
                        name_max_chars: Optional[int] = None,
                        bg_row_h: Optional[int] = None,
                        bg_width_pct: Optional[int] = None):
        if anchor_x is not None:
            self.geometry.anchor_x = anchor_x
        if anchor_y is not None:
            self.geometry.anchor_y = anchor_y
        if line_height is not None:
            self.geometry.line_height = line_height
        if need_x is not None:
            self.geometry.need_x = need_x
        if have_x is not None:
            self.geometry.have_x = have_x
        if name_max_chars is not None:
            self.geometry.name_max_chars = name_max_chars
        if bg_row_h is not None:
            self.geometry.bg_row_h = bg_row_h
        if bg_width_pct is not None:
            self.geometry.bg_width_pct = bg_width_pct

    def draw(self, needs: colony.Needs, ctx: OverlayContext):
        """Render the panel. No-op (and clears) when disabled."""
        if not self.enabled:
            self.clear()
            return
        lines = build_lines(needs, ctx, self.geometry)
        self._render(lines)

    def _render(self, lines: List[_Line]):
        if not self._connect():
            self._last_lines = lines  # remember so a later tick can try again
            return
        self._log_geometry(lines)
        self._send_background(lines)             # behind the text (sent first)
        new_ids = {ln.id for ln in lines} | {self._bg_id}
        for ln in lines:
            self._send(ln)
        # blank out ids that were used last time but not now
        for stale in self._used_ids - new_ids:
            self._blank(stale)
        self._used_ids = new_ids
        self._last_lines = lines
        self._visible = True
        self._last_send = time.time()

    def _log_geometry(self, lines: List[_Line]) -> None:
        """Log effective geometry + bg rect once per change, so tuning is observable."""
        g = self.geometry
        rect = background_rect(lines, g)
        col_x = sorted({ln.x for ln in lines})
        key = (g.anchor_x, g.anchor_y, g.need_x, g.have_x, g.name_max_chars, g.bg_row_h,
               tuple(col_x), rect)
        if key == self._logged_geom:
            return
        self._logged_geom = key
        logger.info(
            "overlay geometry: settings anchor=(%s,%s) need_x=%s have_x=%s name_max=%s "
            "bg_row_h=%s bg_width_pct=%s -> effective column_x=%s bg_rect=%s",
            g.anchor_x, g.anchor_y, g.need_x, g.have_x, g.name_max_chars, g.bg_row_h,
            g.bg_width_pct, col_x, rect)

    def _blank(self, msgid: str):
        try:
            if self._ov:
                self._ov.send_message(msgid, "", COL_ITEM, 0, 0, ttl=1)
        except Exception:
            self._drop()

    def tick(self):
        """Keep the panel alive: re-send if visible and the ttl is about to lapse.

        Call from dashboard_entry (~1/s). Cheap: only re-sends every REFRESH_SECS.
        """
        if not self._visible or not self.enabled or not self._last_lines:
            return
        if time.time() - self._last_send >= REFRESH_SECS:
            self._render(self._last_lines)

    def clear(self):
        """Remove all of our messages from the overlay, including the background rect.

        The background id lives in `_used_ids` (added each render), so blanking that set
        removes it along with the text.
        """
        for msgid in list(self._used_ids):
            self._blank(msgid)
        self._used_ids = set()
        self._last_lines = []
        self._visible = False
