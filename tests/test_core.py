"""Pure-logic unit tests for EDRavenColonialAgent.

No EDMC / tkinter / network imports, so this runs in headless CI. Exercises the needs
model (rca_colony), the Market.json reader (rca_market), and the overlay layout
(rca_overlay.build_lines). Run:  python tests/test_core.py
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(os.path.dirname(HERE), "EDRavenColonialAgent")
sys.path.insert(0, PLUGIN_DIR)

import rca_colony as colony
import rca_market as market
import rca_overlay as overlay


def test_needs_from_depot():
    depot = {"ResourcesRequired": [
        {"Name": "$aluminium_name;", "RequiredAmount": 100, "ProvidedAmount": 40},
        {"Name": "$steel_name;", "RequiredAmount": 50, "ProvidedAmount": 50},
        {"Name": "$liquidoxygen_name;", "RequiredAmount": 30, "ProvidedAmount": 0},
    ]}
    n = colony.needs_from_depot(depot)
    assert n.commodities == {"aluminium": 60, "liquidoxygen": 30}, n.commodities
    assert n.total_remaining() == 90


def test_needs_from_projects_and_assignments():
    projs = [
        {"buildName": "P1", "commodities": {"aluminium": 10, "water": 5},
         "commanders": {"Me": ["aluminium"], "Bob": ["water"]}},
        {"buildName": "P2", "commodities": {"aluminium": 7}, "complete": False},
        {"buildName": "Done", "commodities": {"steel": 999}, "complete": True},
    ]
    n = colony.needs_from_projects(projs, cmdr="me")
    assert n.commodities == {"aluminium": 17, "water": 5}, n.commodities
    assert n.assigned_me == {"aluminium"}
    assert n.assigned_others == {"water"}


def test_names_and_categories():
    assert colony.display_name("aluminium") == "Aluminium"
    assert colony.display_name("heliostaticfurnaces") == "Microbial Furnaces"
    assert colony.display_name("totally_unknown") == "Totally Unknown"
    assert colony.category("water") == "Chemicals"
    assert colony.category("unknownthing") == "Other"
    assert colony.normalize_name("$aluminium_name;") == "aluminium"


def test_construction_site_detection():
    assert colony.is_construction_site("Orbital Construction Site: Foo")
    assert colony.is_construction_site("$EXT_PANEL_ColonisationShip;")
    assert not colony.is_construction_site("Jameson Memorial")
    assert colony.is_construction_site("Planetary Construction Site: X",
                                       ["colonisationcontribution", "dock"])
    assert not colony.is_construction_site("Planetary Construction Site: X", ["dock"])
    assert colony.default_project_name("Orbital Construction Site: Hera Port") == "Hera Port"


def test_grouped_and_sorted():
    n = colony.Needs(commodities={"aluminium": 60, "steel": 100, "liquidoxygen": 30, "water": 0})
    grouped = colony.grouped_needs(n)
    cats = [c for c, _ in grouped]
    assert cats == ["Chemicals", "Metals"], cats  # alphabetical; water (0) omitted
    assert colony.sorted_needs(n) == [("aluminium", 60), ("liquidoxygen", 30), ("steel", 100)]


def test_market_reader():
    d = tempfile.mkdtemp(prefix="edrca_test_")
    with open(os.path.join(d, "Market.json"), "w", encoding="utf-8") as f:
        json.dump({"MarketID": 42, "Items": [
            {"Name": "$aluminium_name;", "Stock": 120},
            {"Name": "$steel_name;", "Stock": 0},
            {"Name": "$liquidoxygen_name;", "Stock": 7},
        ]}, f)
    avail = market.load_market_availability(market_id=42, journal_dir=d)
    assert avail == {"aluminium", "liquidoxygen"}, avail
    assert market.load_market_availability(market_id=999, journal_dir=d) == set()


def _name_color(rows, prefix):
    """Find the (name_text, color) of the first row whose name starts with `prefix`."""
    for r in rows:
        text, color = r.cells[overlay.COL_NAME]
        if text.startswith(prefix):
            return text, color
    raise AssertionError(f"no row starting with {prefix!r}")


def test_overlay_layout_colors():
    needs = colony.Needs(commodities={"aluminium": 60, "steel": 100, "liquidoxygen": 30})
    ctx = overlay.OverlayContext(
        header="Hera Port (orbis)", docked_at_site=False,
        cargo={"aluminium": 60}, market_available={"aluminium", "liquidoxygen"},
        market_valid=True, cargo_capacity=720,
    )
    rows = overlay.build_rows(needs, ctx)
    # ship has enough aluminium -> surplus green (text gets a check mark appended)
    _, alu_color = _name_color(rows, "Aluminium")
    assert alu_color == overlay.COL_SURPLUS
    # steel needed but not sold at this market -> dimmed
    assert _name_color(rows, "Steel") == ("Steel", overlay.COL_DARK)
    # liquid oxygen sold here, not enough on ship -> normal item color
    assert _name_color(rows, "Liquid oxygen") == ("Liquid oxygen", overlay.COL_ITEM)
    assert any("remaining" in r.cells[overlay.COL_NAME][0] for r in rows)

    # the renderable form is a handful of multi-line column blocks (not 1 line per row)
    lines = overlay.build_lines(needs, ctx)
    assert lines and all("\n" in ln.text or ln.text for ln in lines)
    assert all(ln.id.startswith(overlay.OVERLAY_ID_PREFIX) for ln in lines)
    # the dimmed steel must appear inside a COL_DARK-colored block
    assert any(ln.color == overlay.COL_DARK and "Steel" in ln.text for ln in lines)


def test_overlay_column_offsets_move_columns():
    """Regression: per-column x must equal anchor_x + the configured offsets, and
    changing the offsets must move the Need/Ship columns (the bug that motivated
    ungrouping from EDMCModernOverlay's position-normalising group transform)."""
    needs = colony.Needs(commodities={"aluminium": 60, "steel": 100})
    ctx = overlay.OverlayContext(header="P", docked_at_site=True,
                                 cargo={"aluminium": 80}, cargo_capacity=720)

    g1 = overlay.OverlayGeometry(anchor_x=20, need_x=300, have_x=520)
    lines1 = overlay.build_lines(needs, ctx, g1)
    xs1 = {ln.x for ln in lines1}
    assert 20 in xs1 and 20 + 300 in xs1 and 20 + 520 in xs1, xs1

    g2 = overlay.OverlayGeometry(anchor_x=20, need_x=400, have_x=650)
    lines2 = overlay.build_lines(needs, ctx, g2)
    xs2 = {ln.x for ln in lines2}
    assert 20 + 400 in xs2 and 20 + 650 in xs2, xs2
    assert xs1 != xs2  # offsets actually changed the layout


def test_overlay_normalize_geometry():
    """Only correction is keeping Need left of Ship; position is honoured exactly so
    ultra-wide users can place the panel anywhere (no canvas clamp)."""
    # inverted offsets get swapped (Need must be left of Ship)
    _, _, ndx, hvx = overlay.normalize_geometry(
        overlay.OverlayGeometry(anchor_x=20, need_x=700, have_x=370))
    assert (ndx, hvx) == (370, 700)
    # a far-right anchor on an ultra-wide is honoured exactly (NOT clamped back)
    ax, _, ndx, hvx = overlay.normalize_geometry(
        overlay.OverlayGeometry(anchor_x=1600, need_x=160, have_x=290))
    assert ax == 1600 and (ndx, hvx) == (160, 290)


def test_overlay_background_follows_columns_offcanvas():
    """The background box must extend to the rightmost column even when it sits past the
    1280 base canvas (the user's ultra-wide 'box doesn't reach the Need column' bug)."""
    needs = colony.Needs(commodities={"aluminium": 60, "steel": 100})
    ctx = overlay.OverlayContext(header="P", docked_at_site=True, cargo_capacity=720)
    g = overlay.OverlayGeometry(anchor_x=1400, need_x=300, have_x=520)
    lines = overlay.build_lines(needs, ctx, g)
    x, y, w, h = overlay.background_rect(lines, g)
    rightmost_col = max(ln.x for ln in lines)        # = 1400 + 520 = 1920, well past 1280
    assert x + w > rightmost_col, (x, w, rightmost_col)  # box reaches the Need column


def test_overlay_background_rect():
    """background_rect encloses the block: left/top of anchor (minus pad), positive size,
    and height grows with bg_row_h."""
    needs = colony.Needs(commodities={"aluminium": 60, "steel": 100, "liquidoxygen": 30})
    ctx = overlay.OverlayContext(header="Hera Port", docked_at_site=True, cargo_capacity=720)
    g = overlay.OverlayGeometry(anchor_x=20, anchor_y=180, bg_row_h=34)
    lines = overlay.build_lines(needs, ctx, g)
    rect = overlay.background_rect(lines, g)
    assert rect is not None
    x, y, w, h = rect
    assert x == 20 - g.bg_pad and y == 180 - g.bg_pad
    assert w > 0 and h > 0
    # taller rows -> taller box
    g2 = overlay.OverlayGeometry(anchor_x=20, anchor_y=180, bg_row_h=50)
    _, _, _, h2 = overlay.background_rect(overlay.build_lines(needs, ctx, g2), g2)
    assert h2 > h
    # bg_width_pct stretches the box width (compensates FILL-mode rect squish), same left edge
    gw = overlay.OverlayGeometry(anchor_x=20, anchor_y=180, bg_row_h=34, bg_width_pct=250)
    xw, _, ww, _ = overlay.background_rect(overlay.build_lines(needs, ctx, gw), gw)
    assert xw == x and ww > w * 2          # left unchanged, width ~2.5x
    assert overlay.background_rect([], g) is None


def test_overlay_construction_complete():
    needs = colony.Needs()
    ctx = overlay.OverlayContext(header="Done", construction_complete=True)
    rows = overlay.build_rows(needs, ctx)
    assert any("complete" in r.cells[overlay.COL_NAME][0].lower() for r in rows)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"ALL {len(tests)} TESTS PASSED")


if __name__ == "__main__":
    main()
