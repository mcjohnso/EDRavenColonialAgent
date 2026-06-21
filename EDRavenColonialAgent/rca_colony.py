"""
Colony needs model — ported from SrvSurvey's ColonyData / PlotBuildCommodities logic.

Pure logic only: no tkinter / EDMC imports, so it is unit-testable and usable from
smoke_test.py. It computes, per commodity, how much is still needed for the active
colony construction project(s), grouped/sorted the way the SrvSurvey overlay shows them.

Internal commodity names are Elite's lowercase journal tokens with the leading "$" and
trailing "_name;" stripped (e.g. "$aluminium_name;" -> "aluminium").
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# --- station-name markers (ported from ColonyData.cs) -----------------------------------

PLANETARY_CONSTRUCTION_SITE = "Planetary Construction Site:"
ORBITAL_CONSTRUCTION_SITE = "Orbital Construction Site:"
EXT_PANEL_COLONISATION_SHIP = "$EXT_PANEL_ColonisationShip"
SYSTEM_COLONISATION_SHIP = "System Colonisation Ship"

# --- commodity name / category data -----------------------------------------------------

# Category -> commodity internal names. Ported verbatim from ColonyData.mapCargoType;
# also lives in tools/extract_commodities.py (the generator for rca_commodities.json).
MAP_CARGO_TYPE: Dict[str, List[str]] = {
    "Chemicals": ["liquidoxygen", "pesticides", "surfacestabilisers", "water"],
    "Consumer Items": ["evacuationshelter", "survivalequipment"],
    "Foods": ["animalmeat", "coffee", "fish", "foodcartridges", "fruitandvegetables", "grain", "tea"],
    "Industrial Materials": ["ceramiccomposites", "cmmcomposite", "insulatingmembrane", "polymers", "semiconductors", "superconductors"],
    "Legal Drugs": ["beer", "liquor", "wine"],
    "Machinery": ["buildingfabricators", "cropharvesters", "emergencypowercells", "geologicalequipment", "microbialfurnaces", "heliostaticfurnaces", "mineralextractors", "powergenerators", "thermalcoolingunits", "waterpurifiers"],
    "Medicines": ["agriculturalmedicines", "basicmedicines", "combatstabilisers", "combatstabilizers"],
    "Metals": ["aluminium", "copper", "steel", "titanium"],
    "Technology": ["advancedcatalysers", "autofabricators", "bioreducinglichen", "computercomponents", "hazardousenvironmentsuits", "landenrichmentsystems", "terrainenrichmentsystems", "medicaldiagnosticequipment", "microcontrollers", "muonimager", "mutomimager", "resonatingseparators", "robotics", "structuralregulators"],
    "Textiles": ["militarygradefabrics"],
    "Waste": ["biowaste"],
    "Weapons": ["battleweapons", "nonlethalweapons", "reactivearmour"],
}

OTHER_CATEGORY = "Other"

# name -> category, derived from MAP_CARGO_TYPE for O(1) lookup
_CATEGORY_BY_NAME: Dict[str, str] = {
    name: category for category, names in MAP_CARGO_TYPE.items() for name in names
}


def _load_commodity_data() -> Dict[str, Dict[str, str]]:
    path = os.path.join(os.path.dirname(__file__), "rca_commodities.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_COMMODITY_DATA = _load_commodity_data()


def normalize_name(raw: str) -> str:
    """Strip Elite's '$'/'_name;' decoration and lowercase. Safe on already-clean names."""
    if not raw:
        return ""
    name = raw.strip()
    if name.startswith("$"):
        name = name[1:]
    name = name.replace("_name;", "").replace("_name", "")
    return name.lower()


def display_name(name: str) -> str:
    """Human display name for an internal commodity name; title-cases unknowns."""
    entry = _COMMODITY_DATA.get(name)
    if entry and entry.get("display"):
        return entry["display"]
    return name.replace("_", " ").title()


def category(name: str) -> str:
    """Category for an internal commodity name; 'Other' for unknowns."""
    entry = _COMMODITY_DATA.get(name)
    if entry and entry.get("category"):
        return entry["category"]
    return _CATEGORY_BY_NAME.get(name, OTHER_CATEGORY)


# --- construction-site detection (ported from ColonyData.isConstructionSite) -------------

def is_construction_site(station_name: Optional[str],
                         station_services: Optional[Sequence[str]] = None) -> bool:
    """True if the station name looks like a colony construction site.

    When station_services is provided, also require the 'colonisationcontribution'
    service (mirrors the stricter SrvSurvey overload).
    """
    if not station_name:
        return False
    name = station_name
    looks_like = (
        name.lower().startswith(PLANETARY_CONSTRUCTION_SITE.lower())
        or name.lower().startswith(ORBITAL_CONSTRUCTION_SITE.lower())
        or name.lower().startswith(EXT_PANEL_COLONISATION_SHIP.lower())
        or name == SYSTEM_COLONISATION_SHIP
    )
    if not looks_like:
        return False
    if station_services is not None:
        return "colonisationcontribution" in [s.lower() for s in station_services]
    return True


def default_project_name(station_name: Optional[str]) -> str:
    """Header name for an untracked site (ported from ColonyData.getDefaultProjectName)."""
    if not station_name:
        return ""
    if station_name.lower().startswith(EXT_PANEL_COLONISATION_SHIP.lower()) \
            or station_name == SYSTEM_COLONISATION_SHIP:
        return "Primary port"
    return (
        station_name
        .replace(EXT_PANEL_COLONISATION_SHIP + "; ", "")
        .replace(PLANETARY_CONSTRUCTION_SITE, "")
        .replace(ORBITAL_CONSTRUCTION_SITE, "")
        .strip()
    )


# --- needs model ------------------------------------------------------------------------

@dataclass
class Needs:
    """Aggregated remaining commodity needs (ported from ColonyData.Needs)."""
    commodities: Dict[str, int] = field(default_factory=dict)
    assigned_me: Set[str] = field(default_factory=set)
    assigned_others: Set[str] = field(default_factory=set)

    def total_remaining(self) -> int:
        return sum(v for v in self.commodities.values() if v > 0)


def needs_from_depot(depot_event: Dict[str, Any]) -> Needs:
    """Needs from a single ColonisationConstructionDepot journal event.

    Per commodity remaining = RequiredAmount - ProvidedAmount.
    """
    needs = Needs()
    for r in depot_event.get("ResourcesRequired", []) or []:
        name = normalize_name(r.get("Name", ""))
        if not name:
            continue
        remaining = int(r.get("RequiredAmount", 0)) - int(r.get("ProvidedAmount", 0))
        if remaining != 0:
            needs.commodities[name] = needs.commodities.get(name, 0) + remaining
    return needs


def needs_from_projects(projects: Sequence[Dict[str, Any]],
                        cmdr: Optional[str] = None) -> Needs:
    """Aggregate remaining needs across active projects (ported from ColonyData.getNeeds).

    Each project's ``commodities`` dict holds the remaining-needed quantity per commodity.
    ``commanders`` maps a commander name to the list of commodities assigned to them.
    """
    needs = Needs()
    cmdr_lower = cmdr.lower() if cmdr else None
    for project in projects:
        if project.get("complete"):
            continue
        commodities = project.get("commodities") or {}
        commanders = project.get("commanders") or {}
        for commodity, need in commodities.items():
            name = normalize_name(commodity)
            needs.commodities[name] = needs.commodities.get(name, 0) + int(need)

            # assignments
            assigned_to = [
                who for who, items in commanders.items()
                if commodity in (items or [])
            ]
            if cmdr_lower and any(who.lower() == cmdr_lower for who in assigned_to):
                needs.assigned_me.add(name)
            elif assigned_to:
                needs.assigned_others.add(name)
    return needs


# --- layout helpers (drive the overlay's two layouts) -----------------------------------

def sorted_needs(needs: Needs) -> List[Tuple[str, int]]:
    """Alpha layout: every still-needed commodity sorted by display name."""
    items = [(n, q) for n, q in needs.commodities.items() if q > 0]
    items.sort(key=lambda nq: display_name(nq[0]).lower())
    return items


def grouped_needs(needs: Needs) -> List[Tuple[str, List[Tuple[str, int]]]]:
    """Grouped layout: (category, [(name, qty), ...]) ordered like the SrvSurvey overlay.

    Categories are ordered by name; commodities within a category by display name.
    Empty categories and zero/negative quantities are omitted. Commodities not in any
    known category fall under 'Other'.
    """
    by_category: Dict[str, List[Tuple[str, int]]] = {}
    for name, qty in needs.commodities.items():
        if qty <= 0:
            continue
        by_category.setdefault(category(name), []).append((name, qty))

    ordered: List[Tuple[str, List[Tuple[str, int]]]] = []
    # known categories first (alphabetical), then 'Other' last
    known = sorted(c for c in by_category if c != OTHER_CATEGORY)
    for cat in known + ([OTHER_CATEGORY] if OTHER_CATEGORY in by_category else []):
        rows = by_category[cat]
        rows.sort(key=lambda nq: display_name(nq[0]).lower())
        ordered.append((cat, rows))
    return ordered
