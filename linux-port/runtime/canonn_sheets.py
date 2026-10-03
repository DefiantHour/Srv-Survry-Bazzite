#!/usr/bin/env python3
"""Canonn SpreadsheetML import — Windows Canonn.readXmlSheetRuins / readXmlSheetStructures.

The Windows methods load a hardcoded drive path and ignore the argument.
This uses the file you pass. It does not replace SrvSurvey/allRuins.json.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_SS = "{urn:schemas-microsoft-com:office:spreadsheet}"


def _local(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _cells(row: ET.Element) -> list[str]:
    values: list[str] = []
    for cell in row:
        if _local(cell.tag) != "Cell":
            continue
        index = cell.attrib.get(_SS + "Index")
        if index:
            try:
                target = int(index) - 1
            except ValueError:
                target = len(values)
            while len(values) < target:
                values.append("")
        values.append("".join(cell.itertext()).strip())
    return values


def _rows(path: Path, sheet: str) -> list[list[str]]:
    root = ET.parse(path).getroot()
    found: list[list[str]] = []
    for worksheet in root.iter():
        if _local(worksheet.tag) != "Worksheet":
            continue
        name = worksheet.attrib.get(_SS + "Name") or worksheet.attrib.get("Name") or ""
        if name != sheet:
            continue
        for row in worksheet.iter():
            if _local(row.tag) != "Row":
                continue
            found.append(_cells(row))
        break
    return found[1:]


def _site_type(token: str) -> str:
    if token == "α":
        return "Alpha"
    if token == "β":
        return "Beta"
    return "Gamma"


def _star_pos(cells: list[str]) -> list[float] | None:
    if len(cells) < 20:
        return None
    try:
        return [float(cells[17]), float(cells[18]), float(cells[19])]
    except ValueError:
        return None


def read_ruins_sheet(path: Path) -> list[dict[str, Any]]:
    """One summary per site type token on a Ruins row. Duplicates are skipped."""
    summaries: list[dict[str, Any]] = []
    for cells in _rows(path, "Ruins"):
        if len(cells) < 5:
            continue
        system_name = cells[0]
        body_name = cells[2]
        star_pos = _star_pos(cells)
        if not system_name or not body_name or star_pos is None:
            continue
        for index, token in enumerate(cells[4].split(" ")):
            if not token:
                continue
            summary = {
                "systemName": system_name,
                "bodyName": body_name,
                "starPos": star_pos,
                "idx": index + 1,
                "siteType": _site_type(token),
                "siteID": -1,
                "bodyId": -1,
                "distanceToArrival": -1,
                "systemAddress": -1,
                "latitude": None,
                "longitude": None,
            }
            duplicate = any(
                row["systemName"].lower() == system_name.lower()
                and row["bodyName"].lower() == body_name.lower()
                and row["idx"] == summary["idx"]
                for row in summaries
            )
            if not duplicate:
                summaries.append(summary)
    return summaries


def read_structures_sheet(path: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for cells in _rows(path, "Structures"):
        if len(cells) < 5:
            continue
        system_name = cells[0]
        body_name = cells[2]
        star_pos = _star_pos(cells)
        if not system_name or not body_name or star_pos is None:
            continue
        summaries.append(
            {
                "systemName": system_name,
                "bodyName": body_name,
                "starPos": star_pos,
                "siteType": cells[4],
                "distanceToArrival": -1,
                "systemAddress": -1,
            }
        )
    return summaries


def import_catalog_xml(path: Path, dest_dir: Path) -> dict[str, int]:
    """Write ruins-from-sheet.json and structures-from-sheet.json beside the caller."""
    ruins = read_ruins_sheet(path)
    structures = read_structures_sheet(path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("ruins-from-sheet.json", ruins), ("structures-from-sheet.json", structures)):
        target = dest_dir / name
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        temp.replace(target)
    return {"ruins": len(ruins), "structures": len(structures)}
