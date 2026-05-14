#!/usr/bin/env python
"""Custom Effect Pool loader and validator for the Hook-based Custom Item Effect Engine."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EFFECT_POOL_FILENAME = "custom_effect_pool.json"
CUSTOM_EFFECT_MANIFEST_FILENAME = "custom_effect_manifest.json"
POOL_VERSION = 1
CUSTOM_EFFECT_MANIFEST_VERSION = 1

REQUIRED_FIELDS = {"id", "source_kind", "hook", "template", "support_status", "risk_level"}
VALID_SOURCE_KINDS = {"item", "move", "ability", "custom"}
VALID_HOOKS = {
    # Phase 1
    "end_of_round",
    "damage_calc",
    "after_damage_dealt",
    "after_move_use",
    "speed_calc",
    "on_switch_in",
    # Phase 2 — new hooks
    "damage_calc_from_target",   # DamageCalcFromTarget
    "on_being_hit",              # OnBeingHit
    "hp_heal",                   # HPHeal
    "status_cure",               # StatusCure
    "end_of_round_effect",       # EndOfRoundEffect
    "crit_calc",                 # CriticalCalcFromUser
    "accuracy_calc",             # AccuracyCalcFromUser
    "evasion_calc",              # AccuracyCalcFromTarget
    "weight_calc",               # WeightCalc
    "stat_loss_immunity",        # StatLossImmunity
    "on_being_intimidated",      # OnIntimidated
    "terrain_stat_boost",        # TerrainStatBoost
    "weather_extend",            # WeatherExtender
    "stat_restore_after_move",   # OnEndOfUsingMoveStatRestore
}
VALID_SUPPORT_STATUSES = {"supported", "partial", "advanced", "unsupported"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
CUSTOM_EFFECT_ALLOWED_TEMPLATES = {
    ("damage_calc", "damage_multiplier"),
    ("damage_calc", "damage_multiplier_conditional"),
    ("end_of_round", "heal_fraction_max_hp"),
    ("after_damage_dealt", "heal_percent_damage_dealt"),
    ("after_move_use", "raise_user_stat_stage"),
    ("end_of_round_effect", "raise_user_stat_stage_end_of_round"),
    ("speed_calc", "speed_multiplier"),
}
BUILDER_V1_CATEGORY_TYPE_MAP: dict[str, list[str]] = {
    "damage": ["damage_multiplier"],
    "healing": ["heal_holder", "drain_damage_dealt"],
    "stat": ["change_user_stat_stage", "raise_user_stat_stage"],
    "status": [],
    "speed": ["speed_multiplier"],
    "contact": [],
    "end_turn": ["heal_holder", "change_user_stat_stage", "raise_user_stat_stage"],
    "battle_field": [],
}


def effect_pool_path(game_root: "Path | str") -> Path:
    return Path(game_root) / "tools" / "custom_item" / "data" / EFFECT_POOL_FILENAME


def custom_effect_manifest_path(game_root: "Path | str") -> Path:
    return Path(game_root) / "tools" / "custom_item" / "data" / CUSTOM_EFFECT_MANIFEST_FILENAME


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_effect_id(raw: Any) -> str:
    text = str(raw or "").strip().lstrip(":").upper()
    text = re.sub(r"[^A-Z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def slug_effect_id_from_name(name: str, fallback: str = "CUSTOM_EFFECT") -> str:
    text = str(name or "").strip()
    if not text:
        return fallback
    text = text.replace("'", "")
    text = re.sub(r"(?i)\bs\b", "", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).upper()
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def _default_custom_effect_manifest() -> dict[str, Any]:
    return {
        "version": CUSTOM_EFFECT_MANIFEST_VERSION,
        "updated_at_utc": _now_utc_iso(),
        "effects": {},
    }


def load_custom_effect_manifest(game_root: "Path | str") -> dict[str, Any]:
    path = custom_effect_manifest_path(game_root)
    if not path.exists():
        return _default_custom_effect_manifest()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _default_custom_effect_manifest()
    if not isinstance(data, dict):
        return _default_custom_effect_manifest()
    if not isinstance(data.get("effects"), dict):
        effects_raw = data.get("effects", [])
        converted: dict[str, Any] = {}
        if isinstance(effects_raw, list):
            for row in effects_raw:
                if isinstance(row, dict):
                    effect_id = _normalize_effect_id(row.get("id", ""))
                    if effect_id:
                        converted[effect_id] = row
        data["effects"] = converted
    data["version"] = int(data.get("version") or CUSTOM_EFFECT_MANIFEST_VERSION)
    data.setdefault("updated_at_utc", _now_utc_iso())
    return data


def save_custom_effect_manifest(game_root: "Path | str", manifest: dict[str, Any]) -> Path:
    path = custom_effect_manifest_path(game_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["version"] = CUSTOM_EFFECT_MANIFEST_VERSION
    manifest["updated_at_utc"] = _now_utc_iso()
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return path


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _as_int(raw: Any, default: int) -> int:
    try:
        return int(float(str(raw).strip()))
    except Exception:
        return int(default)


def _as_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().casefold()
    return text in {"1", "true", "yes", "y", "on"}


def _clean_symbol(raw: Any) -> str:
    return _normalize_effect_id(raw)


def _normalize_builder_category(raw: Any) -> str:
    text = str(raw or "").strip().casefold().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    aliases = {
        "damage": "damage",
        "healing": "healing",
        "heal": "healing",
        "stat": "stat",
        "stats": "stat",
        "status": "status",
        "speed": "speed",
        "contact": "contact",
        "end turn": "end_turn",
        "end of turn": "end_turn",
        "end round": "end_turn",
        "end of round": "end_turn",
        "battle field": "battle_field",
        "field": "battle_field",
        "battlefield": "battle_field",
    }
    return aliases.get(text, text.replace(" ", "_"))


def list_builtin_pool_effect_ids(game_root: "Path | str") -> list[str]:
    """Return normalized built-in pool effect IDs (excluding custom manifest effects)."""
    base_pool = load_effect_pool(effect_pool_path(game_root))
    out: list[str] = []
    seen: set[str] = set()
    for effect in base_pool.list_all():
        if not isinstance(effect, dict):
            continue
        effect_id = _normalize_effect_id(effect.get("id", ""))
        if effect_id and effect_id not in seen:
            seen.add(effect_id)
            out.append(effect_id)
    return sorted(out)


def list_custom_effect_ids(game_root: "Path | str") -> list[str]:
    manifest = load_custom_effect_manifest(game_root)
    effects = manifest.get("effects", {})
    if not isinstance(effects, dict):
        return []
    out = [_normalize_effect_id(effect_id) for effect_id in effects.keys()]
    out = [effect_id for effect_id in out if effect_id]
    return sorted(set(out))


def compile_custom_effect_authoring(authoring: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Compile user-facing authoring fields into a normalized pool effect entry."""
    errors: list[str] = []
    effect_id = _normalize_effect_id(authoring.get("id", ""))
    name = str(authoring.get("name", "") or "").strip()
    if not effect_id:
        errors.append("Effect ID is required.")
    if not name:
        errors.append("Name is required.")

    effect_type = str(authoring.get("effect_type", "") or "").strip().casefold().replace(" ", "_")
    category = str(authoring.get("category", "") or "Custom").strip() or "Custom"
    category_key = _normalize_builder_category(category)
    allowed_types = BUILDER_V1_CATEGORY_TYPE_MAP.get(category_key)
    if allowed_types is not None and not allowed_types:
        errors.append(f"{category} has no supported Builder v1 Effect Type.")
    if allowed_types is not None and allowed_types and effect_type and effect_type not in set(allowed_types):
        errors.append(f"Effect type '{effect_type}' is not valid for category '{category}'.")
    description = str(authoring.get("description", "") or "").strip()
    target = str(authoring.get("target", "") or "self").strip() or "self"
    conditions = authoring.get("conditions", {})
    values = authoring.get("values", {})
    if not isinstance(conditions, dict):
        conditions = {}
    if not isinstance(values, dict):
        values = {}

    hook = ""
    template = ""
    params: dict[str, Any] = {}
    support_status = "supported"
    risk_level = "low"

    if effect_type == "damage_multiplier":
        multiplier = _as_float(values.get("multiplier", 1.2), 1.2)
        if multiplier <= 0:
            errors.append("Multiplier must be > 0.")
            multiplier = 1.2
        require_move_type = _clean_symbol(conditions.get("move_type", ""))
        require_super = _as_bool(conditions.get("require_super_effective", False))
        hook = "damage_calc"
        if require_move_type or require_super:
            template = "damage_multiplier_conditional"
            params["multiplier"] = multiplier
            if require_move_type:
                params["require_move_type"] = require_move_type
            if require_super:
                params["require_super_effective"] = True
        else:
            template = "damage_multiplier"
            params["multiplier"] = multiplier
    elif effect_type == "heal_holder":
        numerator = _as_int(values.get("fraction_numerator", 1), 1)
        denominator = _as_int(values.get("fraction_denominator", 16), 16)
        if numerator <= 0:
            errors.append("Heal fraction numerator must be > 0.")
            numerator = 1
        if denominator <= 0:
            errors.append("Heal fraction denominator must be > 0.")
            denominator = 16
        hook = "end_of_round"
        template = "heal_fraction_max_hp"
        params = {
            "fraction_numerator": numerator,
            "fraction_denominator": denominator,
        }
    elif effect_type == "drain_damage_dealt":
        percent = _as_int(values.get("percent", 75), 75)
        if percent <= 0:
            errors.append("Drain percent must be > 0.")
            percent = 75
        hook = "after_damage_dealt"
        template = "heal_percent_damage_dealt"
        params = {"percent": percent}
    elif effect_type in {"raise_user_stat_stage", "change_user_stat_stage"}:
        stats_raw = values.get("stats", values.get("stat", "ATTACK"))
        if isinstance(stats_raw, str):
            stats = [_clean_symbol(x) for x in re.split(r"[,;/]+", stats_raw) if _clean_symbol(x)]
        elif isinstance(stats_raw, list):
            stats = [_clean_symbol(x) for x in stats_raw if _clean_symbol(x)]
        else:
            stats = []
        if not stats:
            errors.append("At least one stat must be selected for stat-stage effects.")
            stats = ["ATTACK"]
        stages = _as_int(values.get("stages", 1), 1)
        if stages < 1 or stages > 6:
            errors.append("Stat stages must be in range 1..6.")
            stages = 1
        direction = str(values.get("direction", "raise") or "raise").strip().casefold()
        if direction not in {"raise", "lower"}:
            errors.append(f"Unsupported stat direction: {direction}.")
            direction = "raise"
        trigger_timing = str(values.get("trigger_timing", "after_move") or "after_move").strip().casefold()
        if trigger_timing in {"end_of_round", "end_of_turn", "end turn", "end_turn"}:
            hook = "end_of_round_effect"
            template = "raise_user_stat_stage_end_of_round"
        else:
            hook = "after_move_use"
            template = "raise_user_stat_stage"
        params = {
            "stats": stats,
            "stages": abs(stages),
            "direction": direction,
        }
        if hook == "after_move_use":
            params["trigger"] = "after_successful_move"
            params["once_per_battle"] = _as_bool(values.get("once_per_battle", True))
        else:
            params["trigger"] = "end_of_round"
    elif effect_type == "speed_multiplier":
        multiplier = _as_float(values.get("multiplier", 1.5), 1.5)
        if multiplier <= 0:
            errors.append("Speed multiplier must be > 0.")
            multiplier = 1.5
        hook = "speed_calc"
        template = "speed_multiplier"
        params = {"multiplier": multiplier}
    else:
        errors.append(f"Unsupported custom effect type: {effect_type or '<empty>'}.")

    if hook and hook not in VALID_HOOKS:
        errors.append(f"Unsupported hook: {hook}.")
    if hook and template and (hook, template) not in CUSTOM_EFFECT_ALLOWED_TEMPLATES:
        errors.append(f"Template is not allowed for Custom Effect Builder v1: {hook}/{template}.")

    if errors:
        return None, errors

    effect_def: dict[str, Any] = {
        "id": effect_id,
        "source_kind": "custom",
        "source_id": effect_id,
        "display_name": name,
        "description": description or name,
        "category": category,
        "hook": hook,
        "template": template,
        "target": target,
        "params": params,
        "support_status": support_status,
        "risk_level": risk_level,
        "notes": "User-created custom effect from custom_effect_manifest.json.",
    }
    validation_errors = _validate_effect(effect_def)
    if validation_errors:
        return None, validation_errors
    return effect_def, []


def validate_custom_effect_authoring(authoring: dict[str, Any]) -> list[str]:
    _compiled, errors = compile_custom_effect_authoring(authoring)
    return errors


def upsert_custom_effect(game_root: "Path | str", authoring: dict[str, Any]) -> dict[str, Any]:
    manifest = load_custom_effect_manifest(game_root)
    effects = manifest.get("effects", {})
    if not isinstance(effects, dict):
        effects = {}
        manifest["effects"] = effects
    requested_id = _normalize_effect_id(authoring.get("id", ""))
    editing_id = _normalize_effect_id(authoring.get("editing_id", ""))
    if requested_id:
        if requested_id in effects and requested_id != editing_id:
            raise ValueError(f"Effect ID already exists in custom effect manifest: {requested_id}.")
        builtin_ids = set(list_builtin_pool_effect_ids(game_root))
        if requested_id in builtin_ids:
            raise ValueError(f"Effect ID collides with built-in effect pool entry: {requested_id}.")
    compiled, errors = compile_custom_effect_authoring(authoring)
    if compiled is None:
        raise ValueError("; ".join(errors) or "Invalid custom effect.")
    effect_id = str(compiled["id"])
    entry = dict(authoring)
    entry["id"] = effect_id
    entry["name"] = str(entry.get("name", "") or compiled.get("display_name", "")).strip()
    entry["description"] = str(entry.get("description", "") or compiled.get("description", "")).strip()
    entry["compiled"] = {
        "hook": compiled["hook"],
        "template": compiled["template"],
        "params": compiled.get("params", {}),
        "target": compiled.get("target", "self"),
    }
    entry["support_status"] = compiled.get("support_status", "supported")
    entry["risk_level"] = compiled.get("risk_level", "low")
    entry["updated_at_utc"] = _now_utc_iso()
    effects[effect_id] = entry
    path = save_custom_effect_manifest(game_root, manifest)
    return {
        "id": effect_id,
        "path": str(path),
        "compiled": compiled,
    }


def delete_custom_effect(game_root: "Path | str", effect_id: str) -> dict[str, Any]:
    manifest = load_custom_effect_manifest(game_root)
    effects = manifest.get("effects", {})
    if not isinstance(effects, dict):
        effects = {}
        manifest["effects"] = effects
    eid = _normalize_effect_id(effect_id)
    existed = eid in effects
    if existed:
        del effects[eid]
        path = save_custom_effect_manifest(game_root, manifest)
    else:
        path = custom_effect_manifest_path(game_root)
    return {"id": eid, "deleted": existed, "path": str(path)}


def list_custom_effects(game_root: "Path | str") -> list[dict[str, Any]]:
    manifest = load_custom_effect_manifest(game_root)
    effects = manifest.get("effects", {})
    if not isinstance(effects, dict):
        return []
    rows: list[dict[str, Any]] = []
    for raw_id, entry in effects.items():
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["id"] = _normalize_effect_id(row.get("id", raw_id))
        compiled, errors = compile_custom_effect_authoring(row)
        if compiled is not None:
            row["compiled_pool_effect"] = compiled
            row["validation_errors"] = []
        else:
            row["validation_errors"] = errors
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("id", "")).casefold())
    return rows


def _custom_manifest_pool_effects(game_root: "Path | str") -> list[dict[str, Any]]:
    effects: list[dict[str, Any]] = []
    for row in list_custom_effects(game_root):
        compiled = row.get("compiled_pool_effect")
        if isinstance(compiled, dict):
            effects.append(compiled)
    return effects


def _validate_effect(effect: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not effect.get(field):
            errors.append(f"Missing required field: {field}")
    sk = effect.get("source_kind", "")
    if sk and sk not in VALID_SOURCE_KINDS:
        errors.append(f"Invalid source_kind: {sk!r}")
    hook = effect.get("hook", "")
    if hook and hook not in VALID_HOOKS:
        errors.append(f"Invalid hook: {hook!r}")
    status = effect.get("support_status", "")
    if status and status not in VALID_SUPPORT_STATUSES:
        errors.append(f"Invalid support_status: {status!r}")
    risk = effect.get("risk_level", "")
    if risk and risk not in VALID_RISK_LEVELS:
        errors.append(f"Invalid risk_level: {risk!r}")
    return errors


class EffectPool:
    """In-memory representation of the normalized custom effect pool."""

    def __init__(self, effects: list[dict[str, Any]], path: str = ""):
        self._effects: dict[str, dict[str, Any]] = {}
        for e in effects:
            if isinstance(e, dict) and e.get("id"):
                self._effects[str(e["id"])] = e
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def get_by_id(self, effect_id: str) -> dict[str, Any] | None:
        return self._effects.get(str(effect_id).strip())

    def get_by_hook(self, hook: str) -> list[dict[str, Any]]:
        return [e for e in self._effects.values() if e.get("hook") == hook]

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._effects.values())

    def ids(self) -> list[str]:
        return list(self._effects.keys())

    def __len__(self) -> int:
        return len(self._effects)

    def __contains__(self, effect_id: str) -> bool:
        return str(effect_id) in self._effects

    def __bool__(self) -> bool:
        return bool(self._effects)


def load_effect_pool(path: "Path | str") -> EffectPool:
    """Load and validate the effect pool from a JSON file path."""
    p = Path(path)
    if not p.exists():
        return EffectPool([], str(p))
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return EffectPool([], str(p))
    effects_raw = data.get("effects", []) if isinstance(data, dict) else []
    effects: list[dict[str, Any]] = []
    for item in effects_raw:
        if not isinstance(item, dict):
            continue
        errors = _validate_effect(item)
        if not errors:
            effects.append(item)
    return EffectPool(effects, str(p))


def load_effect_pool_for_game(game_root: "Path | str") -> EffectPool:
    """Load the effect pool for a given game root directory."""
    base_pool = load_effect_pool(effect_pool_path(game_root))
    effects = base_pool.list_all()
    seen = {str(effect.get("id", "")).strip().upper() for effect in effects if isinstance(effect, dict)}
    for effect in _custom_manifest_pool_effects(game_root):
        effect_id = str(effect.get("id", "") or "").strip().upper()
        if not effect_id or effect_id in seen:
            continue
        errors = _validate_effect(effect)
        if errors:
            continue
        effects.append(effect)
        seen.add(effect_id)
    return EffectPool(effects, base_pool.path)


def pool_effect_summary(pool: EffectPool) -> dict[str, Any]:
    """Summarize the pool contents grouped by hook, support_status, and risk_level."""
    all_effects = pool.list_all()
    by_hook: dict[str, list[str]] = {}
    by_status: dict[str, list[str]] = {}
    by_risk: dict[str, list[str]] = {}
    for e in all_effects:
        hook = str(e.get("hook", "unknown"))
        status = str(e.get("support_status", "unknown"))
        risk = str(e.get("risk_level", "unknown"))
        by_hook.setdefault(hook, []).append(str(e["id"]))
        by_status.setdefault(status, []).append(str(e["id"]))
        by_risk.setdefault(risk, []).append(str(e["id"]))
    return {
        "total": len(all_effects),
        "by_hook": by_hook,
        "by_support_status": by_status,
        "by_risk_level": by_risk,
    }
