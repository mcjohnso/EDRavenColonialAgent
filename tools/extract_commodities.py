"""
Dev-only generator for rca_commodities.json.

Reads SrvSurvey's Properties/Commodities.resx for display names and combines it with
the colonization category map (mapCargoType, ported verbatim from
SrvSurvey/SrvSurvey/game/ColonyData.cs) to produce:

    { "<internal_lowercase_name>": { "display": "<Display Name>", "category": "<Category>" }, ... }

Internal names match Elite's journal commodity tokens once the leading "$" and trailing
"_name;" are stripped (e.g. "$aluminium_name;" -> "aluminium"), which are lowercase.

Usage (from repo root):
    python tools/extract_commodities.py \
        ../SrvSurvey/SrvSurvey/Properties/Commodities.resx \
        EDRavenColonialAgent/rca_commodities.json
"""

import json
import sys
import xml.etree.ElementTree as ET

# Ported verbatim from ColonyData.mapCargoType (SrvSurvey). Includes both historical and
# corrected commodity spellings so either form maps to a category.
MAP_CARGO_TYPE = {
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


def category_of(name_lower: str) -> str:
    for category, names in MAP_CARGO_TYPE.items():
        if name_lower in names:
            return category
    return "Other"


def parse_resx(path: str) -> dict:
    """Return {lowercase_key: display_value} for every <data> entry in a .resx file."""
    tree = ET.parse(path)
    root = tree.getroot()
    out = {}
    for data in root.findall("data"):
        key = data.get("name")
        value_el = data.find("value")
        if not key or value_el is None:
            continue
        out[key.lower()] = (value_el.text or key).strip()
    return out


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    resx_path, out_path = argv[1], argv[2]

    display_by_name = parse_resx(resx_path)

    result = {}
    # Every commodity in the resx gets a correct display name; category from the colony map.
    for name_lower, display in display_by_name.items():
        result[name_lower] = {"display": display, "category": category_of(name_lower)}

    # Ensure every colonization commodity exists even if the resx lacked it.
    for category, names in MAP_CARGO_TYPE.items():
        for name_lower in names:
            if name_lower not in result:
                result[name_lower] = {
                    "display": name_lower.title(),
                    "category": category,
                }

    result = dict(sorted(result.items()))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    colony_count = sum(len(v) for v in MAP_CARGO_TYPE.values())
    print(f"Wrote {len(result)} commodities to {out_path} "
          f"({colony_count} colonization commodities across {len(MAP_CARGO_TYPE)} categories)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
