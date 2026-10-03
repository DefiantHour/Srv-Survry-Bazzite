#!/usr/bin/env python3
"""Offline PNG preview of PlotBuildCommodities — no X11, no Elite."""

from __future__ import annotations

from pathlib import Path

from colony import BuildListModel, ConstructionDepot, DepotNeed
from panel_build import render_build_commodities_bitmap


def sample_model() -> BuildListModel:
    """Match Windows screenshot Commercial Port (fc_loading) list + deltas."""
    needs = (
        DepotNeed("liquidoxygen", "Liquid oxygen", 1792, 1792, 0),
        DepotNeed("water", "Water", 741, 741, 0),
        DepotNeed("foodcartridges", "Food Cartridges", 250, 350, 0),
        DepotNeed("fruitandvegetables", "Fruit and Vegetables", 200, 200, 0),
        DepotNeed("ceramiccomposites", "Ceramic Composites", 521, 521, 0),
        DepotNeed("cmmcomposite", "CMM Composite", 4508, 4508, 0),
        DepotNeed("insulatingmembrane", "Insulating Membrane", 347, 347, 0),
        DepotNeed("polymers", "Polymers", 521, 521, 0),
        DepotNeed("semiconductors", "Semiconductors", 68, 68, 0),
        DepotNeed("superconductors", "Superconductors", 112, 112, 0),
        DepotNeed("buildingfabricators", "Building Fabricators", 120, 120, 0),
        DepotNeed("powergenerators", "Power Generators", 80, 80, 0),
        DepotNeed("aluminium", "Aluminium", 150, 150, 0),
        DepotNeed("steel", "Steel", 100, 100, 0),
        DepotNeed("computercomponents", "Computer Components", 82, 82, 0),
        DepotNeed("nonlethalweapons", "Non-Lethal Weapons", 49, 49, 0),
    )
    # Screenshot FC deltas
    fc = {
        "liquidoxygen": 1792 + 1205,
        "water": 0,
        "ceramiccomposites": 0,
        "cmmcomposite": 4508 + 420,
        "insulatingmembrane": 347 + 347,
        "polymers": 521 + 521,
        "semiconductors": 68 + 58,
        "superconductors": 112 + 112,
        "foodcartridges": 9999,
        "fruitandvegetables": 9999,
        "buildingfabricators": 9999,
        "powergenerators": 9999,
        "aluminium": 9999,
        "steel": 9999,
        "computercomponents": 9999,
        "nonlethalweapons": 9999,
    }
    depot = ConstructionDepot(
        market_id=1,
        progress=0.4,
        complete=False,
        failed=False,
        needs=needs,
        title="Commercial Port",
    )
    return BuildListModel(
        header="Commercial Port (fc_loading)",
        depot=depot,
        ship_cargo={},
        fc_cargo=fc,
        fc_count=1,
        cargo_capacity=1205,
        build_id="WNF-L9X",
    )


def main() -> int:
    rgba, width, height = render_build_commodities_bitmap(sample_model())
    out = Path(__file__).resolve().parent / "preview-build-list.png"
    from PIL import Image

    Image.frombytes("RGBA", (width, height), rgba).save(out)
    print(f"wrote {out} ({width}x{height})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
