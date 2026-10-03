#!/usr/bin/env python3
"""BioCriteria rules engine — Linux port of Windows BioPredictor / BioCriteria.

Loads ``SrvSurvey/bio-criteria/*.json`` (same published ruleset). Not ML —
clause trees evaluate body Scan signals (gravity, temp, atmosphere, stars,
materials, guardian bubble, regions). Rewards come from ``codex_ref``.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from journal import FssBodyEntry, SurveyState

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CRITERIA = _REPO_ROOT / "SrvSurvey" / "bio-criteria"
_ENG_VER = 4
_MATS_MIN = 0.25

_PROP_MAP = {
    "body": "PlanetClass",
    "gravity": "SurfaceGravity",
    "temp": "SurfaceTemperature",
    "pressure": "SurfacePressure",
    "atmosphere": "Atmosphere",
    "atmosType": "AtmosphereType",
    "atmosComp": "AtmosphereComposition",
    "matsComp": "Materials",
    "dist": "DistanceFromArrivalLS",
    "volcanism": "Volcanism",
    "mats": "Materials",
    "regions": "Region",
    "star": "Star",
    "parentStar": "ParentStar",
    "primaryStar": "PrimaryStar",
    "nebulae": "Nebulae",
    "guardian": "Guardian",
}

_VALUE_MAP = {
    "Icy": "Icy body",
    "Rocky": "Rocky body",
    "RockyIce": "Rocky ice ",
    "HMC": "High metal content ",
    "MRB": "Metal rich body",
}

# Arm / batch names → region IDs (GalacticRegions.mapArmRegions)
_ARM_REGIONS: dict[str, tuple[int, ...]] = {
    "Orion-CygnusArm": (7, 8, 16, 17, 18, 35),
    "OuterArm": (5, 6, 13, 14, 27, 29, 31, 41, 37),
    "Scutum-CentaurusArm": (9, 10, 11, 12, 24, 25, 26, 42, 28),
    "PerseusArm": (15, 30, 32, 33, 34, 36, 38, 39),
    "Sagittarius-CarinaArm": (9, 18, 19, 20, 21, 22, 23, 40),
    "CentreLeft": (1, 4),
    "CentreTop": (1, 3, 7),
    "CentreRight": (1, 2),
    "AmphoraBatch": (10, 19, 20, 21, 22),
    "AnemoneBatch": (7, 8, 9, 13, 14, 15, 16, 17, 18, 27, 31),
    "BarkMoundBatch": (
        4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 25, 32, 33, 34,
    ),
    "BrainTreeBatch": (2, 9, 10, 17, 18, 35),
    "TubersBatch": (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19),
    "ShardBatch": (
        14, 21, 22, 23, 24, 25, 26, 27, 28, 29, 31, 34, 36, 37, 38, 39, 40, 41, 42,
    ),
}

# Guardian bubbles (CodexRef.isWithinGuardianBubble) — (x,y,z), radius_ly
_GUARDIAN_BIG = (
    ((1099.21875, -146.6875, -133.59375), 750.0),  # Gamma Velorum
    ((-840.65625, -561.15625, 13361.8125), 750.0),  # Hen 2-333
)
_GUARDIAN_SMALL = (
    (-9298.6875, -419.40625, 7911.15625),  # Prai Hypoo OK-I b0
    (-5479.28125, -574.84375, 10468.96875),  # Prua Phoe US-B d58
    (1228.1875, -694.5625, 12341.65625),  # Blaa Hypai EK-C c14-1
    (4961.1875, 158.09375, 20642.65625),  # Eorl Auwsy SY-Z d13-3643
    (14602.75, -237.90625, 3561.875),  # NGC 3199
    (8649.125, -154.71875, 2686.03125),  # Eta Carina
)

_CLAUSE_RE = re.compile(r"\s*(\w+)\s*[&!]?\[(.+)\]")
_COMPO_RE = re.compile(r"([\w\s]+)(>=)\s*([\.\d]+)")

_lock = threading.Lock()
_criteria: list["BioCriteria"] = []
_criteria_folder: Path | None = None


class Op(str, Enum):
    Is = "Is"
    All = "All"
    Not = "Not"
    Range = "Range"
    Composition = "Composition"
    Comment = "Comment"


@dataclass
class Clause:
    raw: str
    property: str
    op: Op
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None
    compositions: dict[str, float] | None = None


@dataclass
class BioCriteria:
    genus: str | None = None
    species: str | None = None
    variant: str | None = None
    query: list[Clause] = field(default_factory=list)
    children: list["BioCriteria"] = field(default_factory=list)
    use_common_children: bool = False
    common_children: list["BioCriteria"] | None = None


@dataclass(frozen=True)
class BioPredictionRow:
    name: str
    genus: str
    species: str
    variant: str
    reward: int = 0
    note: str = ""


def flatten_star_type(star_type: str | None) -> str | None:
    if not star_type:
        return None
    if star_type[0] in "DWC":
        return star_type[0]
    if len(star_type) > 1 and star_type[1] == "_":
        return star_type[0]
    return star_type


def _normalize_region_value(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value
    key = value.replace(" ", "")
    ids = _ARM_REGIONS.get(key) or _ARM_REGIONS.get(value)
    if ids:
        return ",".join(str(i) for i in sorted(ids))
    return value


def parse_clause(txt: str) -> Clause | None:
    raw = (txt or "").strip()
    if not raw or raw.startswith("#"):
        return None
    m = _CLAUSE_RE.match(raw)
    if not m:
        raise ValueError(f"Bad criteria: {txt}")
    prop = m.group(1)
    val_txt = m.group(2)
    if "~" in val_txt:
        parts = [p.strip() for p in val_txt.split("~", 1)]
        lo = float(parts[0]) if parts[0] else None
        hi = float(parts[1]) if len(parts) > 1 and parts[1] else None
        return Clause(raw=raw, property=prop, op=Op.Range, min=lo, max=hi)
    if ">=" in val_txt:
        compositions: dict[str, float] = {}
        for part in val_txt.split("|"):
            cm = _COMPO_RE.match(part.strip())
            if not cm:
                raise ValueError(f"Bad Composition clause: {part}")
            compositions[cm.group(1).strip()] = float(cm.group(3))
        return Clause(
            raw=raw, property=prop, op=Op.Composition, compositions=compositions
        )
    if "![" in raw:
        op = Op.Not
    elif "&[" in raw:
        op = Op.All
    else:
        op = Op.Is
    values: list[str] = []
    for v in val_txt.split(","):
        v = v.strip()
        if not v:
            continue
        if v in _VALUE_MAP:
            v = _VALUE_MAP[v]
        if prop == "regions":
            v = _normalize_region_value(v)
        values.append(v)
    return Clause(raw=raw, property=prop, op=op, values=values)


def _load_node(obj: dict[str, Any]) -> BioCriteria:
    query: list[Clause] = []
    for item in obj.get("query") or []:
        if isinstance(item, str):
            clause = parse_clause(item)
            if clause is not None:
                query.append(clause)
    children = [
        _load_node(c) for c in (obj.get("children") or []) if isinstance(c, dict)
    ]
    common_raw = obj.get("commonChildren")
    common: list[BioCriteria] | None = None
    if isinstance(common_raw, list):
        common = [_load_node(c) for c in common_raw if isinstance(c, dict)]
    return BioCriteria(
        genus=obj.get("genus") if isinstance(obj.get("genus"), str) else None,
        species=obj.get("species") if isinstance(obj.get("species"), str) else None,
        variant=obj.get("variant") if isinstance(obj.get("variant"), str) else None,
        query=query,
        children=children,
        use_common_children=bool(obj.get("useCommonChildren")),
        common_children=common,
    )


def reset_criteria_cache() -> None:
    global _criteria, _criteria_folder
    with _lock:
        _criteria = []
        _criteria_folder = None


def read_criteria(folder: Path | None = None, *, force: bool = False) -> int:
    """Load all genus JSON files. Returns criteria root count."""
    global _criteria, _criteria_folder
    target = folder if folder is not None else _DEFAULT_CRITERIA
    with _lock:
        if not force and _criteria and _criteria_folder == target:
            return len(_criteria)
        loaded: list[BioCriteria] = []
        if target.is_dir():
            for path in sorted(target.glob("*.json")):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(raw, dict):
                    loaded.append(_load_node(raw))
        _criteria = loaded
        _criteria_folder = target
        return len(loaded)


def _dist3(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def within_guardian_bubble(star_pos: tuple[float, float, float] | None) -> bool:
    if star_pos is None:
        return False
    for center, radius in _GUARDIAN_BIG:
        if _dist3(star_pos, center) < radius:
            return True
    for center in _GUARDIAN_SMALL:
        if _dist3(star_pos, center) < 100.0:
            return True
    return False


def _as_float_dict(pairs: tuple[tuple[str, float], ...] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if not pairs:
        return out
    for name, pct in pairs:
        out[str(name)] = float(pct)
    return out


def body_props_from_fss(
    body: FssBodyEntry,
    survey: SurveyState,
    *,
    region_id: int | None = None,
) -> dict[str, Any] | None:
    """Build BioPredictor bodyProps dict from journal FSS/Scan fields."""
    if not body.landable and body.body_type != "LandableBody":
        if not body.planet_class:
            return None
    atmo_comp = _as_float_dict(body.atmosphere_composition)
    if len(atmo_comp) == 1:
        key = next(iter(atmo_comp))
        atmo_comp[key] = 100.0
    mats = _as_float_dict(body.materials)

    primary = ""
    parent_stars: list[str] = []
    for star in survey.fss_bodies:
        if not star.star_type:
            continue
        flat = flatten_star_type(star.star_type)
        if not flat:
            continue
        if star.is_main_star or star.distance_from_arrival_ls == 0.0:
            primary = flat
        if star.distance_from_arrival_ls <= body.distance_from_arrival_ls + 0.01:
            parent_stars.append(flat)
    if not parent_stars and primary:
        parent_stars = [primary]
    if not parent_stars:
        # No star context — cannot predict colour variants reliably
        return None
    if not primary:
        primary = parent_stars[0]

    atmos = (body.atmosphere or "").replace(" atmosphere", "")
    volc = body.volcanism if body.volcanism else "None"
    if region_id is None and survey.star_pos is not None:
        try:
            from galactic_region import find_region

            found = find_region(*survey.star_pos)
            if found is not None:
                region_id = found[0]
        except Exception:
            region_id = None
    region = str(region_id) if region_id is not None else ""
    guardian = within_guardian_bubble(survey.star_pos)
    try:
        from galactic_region import closest_nebula_ly

        nebula = closest_nebula_ly(survey.star_pos)
    except Exception:
        nebula = 99999.0

    return {
        "PlanetClass": body.planet_class or "",
        "SurfaceGravity": float(body.surface_gravity) / 10.0,
        "SurfaceTemperature": float(body.surface_temperature),
        "SurfacePressure": float(body.surface_pressure) / 100_000.0,
        "Atmosphere": atmos,
        "AtmosphereType": body.atmosphere_type or "None",
        "AtmosphereComposition": atmo_comp,
        "DistanceFromArrivalLS": float(body.distance_from_arrival_ls),
        "Volcanism": volc or "None",
        "Materials": mats,
        "Region": region,
        "Star": list(dict.fromkeys(parent_stars)),
        "PrimaryStar": primary,
        "Nebulae": nebula,
        "Guardian": str(guardian),
    }


def _region_ids_from_values(values: list[str]) -> set[int]:
    out: set[int] = set()
    for region_string in values:
        for part in region_string.split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
    return out


class _Predictor:
    def __init__(
        self,
        body_name: str,
        body_props: dict[str, Any],
        *,
        known_genus: list[str] | None = None,
        known_species: dict[str, str] | None = None,
        all_genus_known: bool = False,
        target_variant: str | None = None,
    ) -> None:
        self.body_name = body_name
        self.body_props = body_props
        self.known_genus = known_genus or []
        self.known_species = known_species or {}
        self.all_genus_known = all_genus_known
        self.target_variant = target_variant
        self.predictions: set[str] = set()

    def run(self, criteria_list: list[BioCriteria]) -> None:
        for criteria in criteria_list:
            self._predict(criteria, None, None, None, None)

    def _predict(
        self,
        criteria: BioCriteria,
        genus: str | None,
        species: str | None,
        variant: str | None,
        common_children: list[BioCriteria] | None,
    ) -> bool:
        common_children = criteria.common_children or common_children
        genus = criteria.genus if criteria.genus is not None else genus
        species = criteria.species if criteria.species is not None else species
        variant = criteria.variant if criteria.variant is not None else variant

        if self.target_variant is None:
            if (
                genus
                and self.all_genus_known
                and self.known_genus
                and genus not in self.known_genus
            ):
                return False
            if genus and species and genus in self.known_species:
                return False

        current_name = (
            species if variant == "" else f"{genus} {species} - {variant}"
        ).strip() if (genus or species or variant is not None) else ""
        failures = self._test_query(criteria.query, f"{genus} {species} {variant}".strip())
        target_match = False

        if (
            not failures
            and genus is not None
            and species is not None
            and variant is not None
        ):
            target_match = self.target_variant == current_name
            if self.target_variant is None or self.target_variant == current_name:
                self.predictions.add(current_name)

        children = (
            common_children if criteria.use_common_children else criteria.children
        )
        if children and not failures:
            for child in children:
                self._predict(child, genus, species, variant, common_children)
        return target_match

    def _test_query(self, query: list[Clause], current_name: str) -> list[str]:
        failures: list[str] = []
        for clause in query:
            prop_name = _PROP_MAP.get(clause.property, clause.property)
            if prop_name not in self.body_props:
                failures.append(f"missing prop {prop_name}")
                continue
            body_value = self.body_props.get(prop_name)
            if clause.op == Op.Is:
                self._test_is(clause, body_value, failures)
            elif clause.op == Op.All:
                self._test_all(clause, body_value, failures)
            elif clause.op == Op.Not:
                self._test_not(clause, body_value, failures)
            elif clause.op == Op.Range:
                self._test_range(clause, body_value, failures)
            elif clause.op == Op.Composition:
                self._test_composition(clause, body_value, failures)
        return failures

    def _test_is(self, clause: Clause, body_value: Any, failures: list[str]) -> None:
        values = clause.values or []
        if clause.property == "mats" and isinstance(body_value, dict):
            if not any(
                any(
                    str(k).lower() == v.lower() and float(pct) > _MATS_MIN
                    for k, pct in body_value.items()
                )
                for v in values
            ):
                failures.append("No mats multi match")
            return
        if clause.property == "regions" and isinstance(body_value, str):
            if body_value.isdigit():
                allowed = _region_ids_from_values(values)
                if allowed and int(body_value) not in allowed:
                    failures.append("No region match")
            return
        body_values: list[str] | None = None
        if isinstance(body_value, list):
            body_values = [str(x) for x in body_value]
        elif isinstance(body_value, dict):
            body_values = [str(k) for k in body_value.keys()]
        if body_values is not None:
            if not any(
                any(bv.lower() == v.lower() for bv in body_values) for v in values
            ):
                failures.append("No multi match")
            return
        if isinstance(body_value, str):
            if clause.property == "body":
                if not any(
                    body_value.lower().startswith(v.lower()) for v in values
                ):
                    failures.append("No startsWith match body")
            elif clause.property == "volcanism":
                if values and values[0] == "Any":
                    if body_value == "None":
                        failures.append("No match Volcanism Some vs None")
                elif not any(v.lower() in body_value.lower() for v in values):
                    failures.append("No match Volcanism parts")
            elif not any(body_value.lower() == v.lower() for v in values):
                failures.append("No single match")

    def _test_all(self, clause: Clause, body_value: Any, failures: list[str]) -> None:
        values = clause.values or []
        if isinstance(body_value, str):
            body_value = [body_value]
        body_values: list[str] | None = None
        if isinstance(body_value, list):
            body_values = [str(x) for x in body_value]
        elif isinstance(body_value, dict):
            body_values = [str(k) for k in body_value.keys()]
        if body_values is None:
            failures.append("Unexpected All body value")
            return
        if not all(
            any(bv.lower() == v.lower() for bv in body_values) for v in values
        ):
            failures.append("Not ALL found")

    def _test_not(self, clause: Clause, body_value: Any, failures: list[str]) -> None:
        values = clause.values or []
        if clause.property == "regions" and isinstance(body_value, str):
            if body_value.isdigit():
                disallowed = _region_ids_from_values(values)
                if int(body_value) in disallowed:
                    failures.append("Match with disallowed region")
            return
        if isinstance(body_value, str):
            body_value = [body_value]
        body_values: list[str] | None = None
        if isinstance(body_value, list):
            body_values = [str(x) for x in body_value]
        elif isinstance(body_value, dict):
            body_values = [str(k) for k in body_value.keys()]
        if body_values is None:
            return
        if any(any(bv.lower() == v.lower() for bv in body_values) for v in values):
            failures.append("Must NOT have")

    def _test_range(
        self, clause: Clause, body_value: Any, failures: list[str]
    ) -> None:
        try:
            num = float(body_value)
        except (TypeError, ValueError):
            failures.append("Non-numeric range")
            return
        if clause.min is not None and num < clause.min:
            failures.append("Below min")
        if clause.max is not None and num > clause.max:
            failures.append("Above max")

    def _test_composition(
        self, clause: Clause, body_value: Any, failures: list[str]
    ) -> None:
        if not isinstance(body_value, dict) or not clause.compositions:
            return
        local = 0
        for key, need in clause.compositions.items():
            if key not in body_value:
                local += 1
            elif float(body_value[key]) < need:
                local += 1
        if local == len(clause.compositions):
            failures.append("Composition OR all failed")


def predict(
    body_props: dict[str, Any],
    *,
    body_name: str = "",
    known_genus: list[str] | None = None,
    known_species: dict[str, str] | None = None,
    all_genus_known: bool = False,
    criteria_folder: Path | None = None,
) -> list[str]:
    """Return predicted display names like ``Aleoida Arcus - Emerald``."""
    read_criteria(criteria_folder)
    with _lock:
        roots = list(_criteria)
    if not roots:
        return []
    pred = _Predictor(
        body_name,
        body_props,
        known_genus=known_genus,
        known_species=known_species,
        all_genus_known=all_genus_known,
    )
    pred.run(roots)
    return sorted(pred.predictions)


def _reward_for_name(name: str) -> int:
    try:
        from codex_ref import reward_for_species

        return int(reward_for_species(name) or 0)
    except Exception:
        return 0


def _split_prediction_name(name: str) -> tuple[str, str, str]:
    if " - " in name:
        left, variant = name.rsplit(" - ", 1)
        parts = left.split(None, 1)
        if len(parts) == 2:
            return parts[0], parts[1], variant
        return left, "", variant
    # Brain Trees / legacy: species is the full name
    parts = name.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return name, name, ""


def enrich_predictions(names: list[str]) -> list[BioPredictionRow]:
    rows: list[BioPredictionRow] = []
    for name in names:
        genus, species, variant = _split_prediction_name(name)
        rows.append(
            BioPredictionRow(
                name=name,
                genus=genus,
                species=species or name,
                variant=variant,
                reward=_reward_for_name(name),
                note="BioCriteria",
            )
        )
    rows.sort(key=lambda r: (-r.reward, r.name))
    return rows


def predict_body(
    body: FssBodyEntry,
    survey: SurveyState,
    *,
    region_id: int | None = None,
    known_genus: list[str] | None = None,
) -> list[BioPredictionRow]:
    props = body_props_from_fss(body, survey, region_id=region_id)
    if props is None:
        return []
    names = predict(
        props,
        body_name=body.body_name,
        known_genus=known_genus,
        all_genus_known=bool(known_genus)
        and len(known_genus) >= max(1, body.bio_signal_count),
    )
    # Prefer predictions matching known genus list when present
    if known_genus:
        filtered = [
            n
            for n in names
            if any(g.lower() in n.lower() for g in known_genus)
        ]
        if filtered:
            names = filtered
    return enrich_predictions(names)


def predict_for_survey(
    survey: SurveyState,
    *,
    body_name: str | None = None,
    limit: int = 48,
    region_id: int | None = None,
) -> list[BioPredictionRow]:
    """Predict species/variants for landable bio bodies in the survey."""
    read_criteria()
    rows: list[BioPredictionRow] = []
    seen: set[str] = set()

    bodies = [
        b
        for b in survey.fss_bodies
        if b.landable or b.body_type == "LandableBody" or b.planet_class
    ]
    if body_name:
        bodies = [b for b in bodies if b.body_name == body_name]

    # Fall back: any body with bio signals even if Scan incomplete
    if not bodies:
        for sig in survey.body_signals:
            if body_name and sig.body_name != body_name:
                continue
            if sig.bio_count <= 0 and not sig.genuses:
                continue
            for genus in sig.genuses:
                key = f"genus:{genus}"
                if key in seen:
                    continue
                seen.add(key)
                try:
                    from codex_ref import max_reward_for_genus

                    reward = max_reward_for_genus(genus)
                except Exception:
                    reward = 0
                rows.append(
                    BioPredictionRow(
                        name=genus,
                        genus=genus,
                        species="",
                        variant="",
                        reward=int(reward or 0),
                        note="journal genus (Scan props incomplete)",
                    )
                )
            if not sig.genuses and sig.bio_count > 0:
                rows.append(
                    BioPredictionRow(
                        name=f"(unresolved ×{sig.bio_count})",
                        genus="",
                        species="",
                        variant="",
                        reward=0,
                        note="bio signals; need Detailed Scan for BioCriteria",
                    )
                )
        return rows[:limit]

    for body in bodies:
        if body_name and body.body_name != body_name:
            continue
        known: list[str] = []
        for sig in survey.body_signals:
            if sig.body_name == body.body_name:
                known = list(sig.genuses)
                break
        if body.bio_signal_count <= 0 and not known:
            continue
        for row in predict_body(
            body, survey, region_id=region_id, known_genus=known or None
        ):
            if row.name in seen:
                continue
            seen.add(row.name)
            rows.append(row)

    rows.sort(key=lambda r: (-r.reward, r.name))
    return rows[:limit]


def format_prediction_lines(
    survey: SurveyState,
    *,
    body_name: str | None = None,
    limit: int = 16,
) -> list[str]:
    rows = predict_for_survey(survey, body_name=body_name, limit=limit)
    lines: list[str] = []
    for row in rows:
        if row.reward > 0:
            lines.append(f"{row.name} · {row.reward:,} cr")
        elif row.note:
            lines.append(f"{row.name} · {row.note}" if row.name else row.note)
        else:
            lines.append(row.name)
    return lines


def survey_from_journal_folder(journal_folder: str | Path) -> SurveyState | None:
    """Best-effort: parse latest journal in folder into SurveyState."""
    from journal import latest_journal_file, read_session_file

    folder = Path(journal_folder)
    path = latest_journal_file(folder) if folder.is_dir() else None
    if path is None or not path.is_file():
        return None
    try:
        return read_session_file(path).survey
    except OSError:
        return None


def predictions_json_for_journal(
    journal_folder: str | None,
    *,
    limit: int = 64,
) -> str:
    """CLI helper for Avalonia PredictionsWindow — JSON list of rows."""
    if not journal_folder:
        return "[]"
    survey = survey_from_journal_folder(journal_folder)
    if survey is None:
        return "[]"
    rows = predict_for_survey(survey, limit=limit)
    payload = [
        {
            "name": r.name,
            "genus": r.genus,
            "species": r.species,
            "variant": r.variant,
            "reward": r.reward,
            "note": r.note,
        }
        for r in rows
    ]
    return json.dumps(payload)


if __name__ == "__main__":
    import sys

    folder = sys.argv[1] if len(sys.argv) > 1 else ""
    print(predictions_json_for_journal(folder or None))
