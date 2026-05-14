#!/usr/bin/env python
"""Custom item patcher with transactional backup/rollback."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pokemon_indigo_ev_patcher as ev_patcher
import pokemon_indigo_save_editor as core
try:
    from pokemon_indigo_game_data import GameCatalogs
except Exception:  # noqa: BLE001
    GameCatalogs = None

try:
    from .effect_pool import load_effect_pool_for_game as _load_effect_pool_for_game
except Exception:  # noqa: BLE001
    _load_effect_pool_for_game = None  # type: ignore[assignment]

try:
    from . import hook_compiler as _hook_compiler_mod
except Exception:  # noqa: BLE001
    _hook_compiler_mod = None  # type: ignore[assignment]


MANIFEST_VERSION = 1
MANIFEST_FILENAME = "custom_item_manifest.json"
EFFECT_TEMPLATE_FILENAME = "custom_item_effect_templates.json"
CUSTOM_ITEM_DIRNAME = "custom_item"
CUSTOM_ITEM_DATA_DIRNAME = "data"
BACKUP_ROOT_DIRNAME = "backups"
SCRIPT_PATCH_ENTRY_NAME = "ZZ_CustomItemPatch"
ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY = "ability_active_bridge"
MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY = "move_additional_effect_bridge"
ENFORCE_PARALLEL_CUSTOM_ITEM_MODE = True
FIXED_RUNTIME_BRIDGE_VERSION = 2
CUSTOM_ITEM_RUNTIME_FILENAME = "custom_item_runtime.rb"

ABILITY_TEMPLATE_TO_ITEM = {
    # Safe transferable subset: item-clone fallback profiles.
    "ROUGHSKIN": "ROCKYHELMET",
    "IRONBARBS": "ROCKYHELMET",
}

MOVE_TEMPLATE_TO_ITEM = {
    # Safe transferable subset: item-clone fallback profiles.
    "BITE": "KINGSROCK",
    "AIRSLASH": "KINGSROCK",
    "HEADBUTT": "KINGSROCK",
    "ZENHEADBUTT": "KINGSROCK",
    "IRONHEAD": "KINGSROCK",
    "ROCKSLIDE": "KINGSROCK",
}

ABILITY_RUNTIME_TEMPLATES = {
    "CONTRARY": "ability_contrary",
    "SHEERFORCE": "ability_sheer_force",
}

MOVE_RUNTIME_TEMPLATES = {
    "DRAINPUNCH": "drain_damage_half",
    "DRAININGKISS": "drain_damage_three_quarters",
    "OBLIVIONWING": "drain_damage_three_quarters",
}

MOVE_FUNCTION_RUNTIME_TEMPLATES = {
    "HealUserByHalfOfDamageDone": "drain_damage_half",
    "HealUserByHalfOfDamageDoneIfTargetAsleep": "drain_damage_half",
    "HealUserByHalfOfDamageDoneBurnTarget": "drain_damage_half",
    "HealUserByThreeQuartersOfDamageDone": "drain_damage_three_quarters",
}

CUSTOM_GENERATED_DESCRIPTION_MARKERS = (
    "AUTO-GENERATED FROM SELECTED EFFECTS",
    "TODO: CUSTOMIZE THIS ITEM",
)


_SYMBOL_TOKEN_RE = re.compile(r":([A-Za-z0-9_]+)")
_ITEM_HANDLERS_CALL_RE = re.compile(r"ItemHandlers::([A-Za-z0-9_]+)\.(?:add|copy|addIf)\s*\(")
_BATTLE_ITEM_EFFECTS_CALL_RE = re.compile(r"Battle::ItemEffects::([A-Za-z0-9_]+)\.(?:add|copy|addIf)\s*\(")
_HAS_ACTIVE_ABILITY_CALL_RE = re.compile(
    r"\b(?:(?:pb)?hasActiveAbility\??|has_active_ability\??)\s*\((.*?)\)",
    flags=re.DOTALL,
)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _resolve_game_root(game_root: Path | str) -> Path:
    return Path(game_root).expanduser().resolve()


def _custom_item_root_dir(game_root: Path | str) -> Path:
    return _resolve_game_root(game_root) / "tools" / CUSTOM_ITEM_DIRNAME


def _custom_item_data_dir(game_root: Path | str) -> Path:
    return _custom_item_root_dir(game_root) / CUSTOM_ITEM_DATA_DIRNAME


def _legacy_manifest_path(game_root: Path | str) -> Path:
    return _resolve_game_root(game_root) / "tools" / MANIFEST_FILENAME


def _legacy_effect_template_catalog_path(game_root: Path | str) -> Path:
    return _resolve_game_root(game_root) / "tools" / EFFECT_TEMPLATE_FILENAME


def manifest_path(game_root: Path | str) -> Path:
    return _custom_item_data_dir(game_root) / MANIFEST_FILENAME


def effect_template_catalog_path(game_root: Path | str) -> Path:
    return _custom_item_data_dir(game_root) / EFFECT_TEMPLATE_FILENAME


def runtime_data_path(game_root: Path | str) -> Path:
    return _custom_item_data_dir(game_root) / CUSTOM_ITEM_RUNTIME_FILENAME


def _backup_root(game_root: Path | str) -> Path:
    return _custom_item_root_dir(game_root) / BACKUP_ROOT_DIRNAME


def _relative_to_root(root: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except Exception:
        return Path(path.name)


def _build_backup_path(root: Path, target_path: Path, kind: str, stamp: str) -> Path:
    rel = _relative_to_root(root, target_path)
    out_dir = _backup_root(root) / kind / rel.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{rel.name}.{stamp}.bak"


def _copy_to_backup(root: Path, target_path: Path, kind: str, stamp: str) -> Path:
    backup = _build_backup_path(root, target_path, kind=kind, stamp=stamp)
    shutil.copy2(target_path, backup)
    return backup


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def _load_json_with_legacy(primary_path: Path, legacy_path: Path) -> dict[str, Any] | None:
    data = _load_json(primary_path)
    if isinstance(data, dict):
        return data
    legacy = _load_json(legacy_path)
    if isinstance(legacy, dict):
        try:
            _save_json(primary_path, legacy)
        except Exception:
            pass
        return legacy
    return None


def _save_json(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize_id_map(raw: Any, value_kind: str = "id") -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        k = _normalize_item_id(key)
        if not k:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if value_kind == "item":
            v = _normalize_item_id(text)
        else:
            v = text
        if not v:
            continue
        out[k] = v
    return out


def _default_effect_template_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at_utc": _now_utc_iso(),
        "ability_item_fallback": dict(ABILITY_TEMPLATE_TO_ITEM),
        "move_item_fallback": dict(MOVE_TEMPLATE_TO_ITEM),
        "ability_runtime_templates": dict(ABILITY_RUNTIME_TEMPLATES),
        "move_runtime_templates": dict(MOVE_RUNTIME_TEMPLATES),
        "move_function_runtime_templates": dict(MOVE_FUNCTION_RUNTIME_TEMPLATES),
    }


def load_effect_template_catalog(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    path = effect_template_catalog_path(root)
    defaults = _default_effect_template_catalog()
    data = _load_json_with_legacy(path, _legacy_effect_template_catalog_path(root))
    if not isinstance(data, dict):
        _save_json(path, defaults)
        return defaults

    merged = dict(defaults)
    for key in ("ability_item_fallback", "move_item_fallback", "ability_runtime_templates", "move_runtime_templates"):
        src = data.get(key, {})
        base_map = dict(defaults.get(key, {}))
        base_map.update(_normalize_id_map(src, value_kind=("item" if key.endswith("_fallback") else "id")))
        merged[key] = base_map

    fn_map: dict[str, str] = {}
    raw_fn_map = data.get("move_function_runtime_templates", {})
    if isinstance(raw_fn_map, dict):
        for key, value in raw_fn_map.items():
            fn_key = str(key or "").strip()
            tpl_key = str(value or "").strip()
            if fn_key and tpl_key:
                fn_map[fn_key] = tpl_key
    if not fn_map:
        fn_map = dict(defaults.get("move_function_runtime_templates", {}))
    merged["move_function_runtime_templates"] = fn_map
    merged["version"] = int(data.get("version", defaults.get("version", 1)) or 1)
    merged["updated_at_utc"] = str(data.get("updated_at_utc", defaults.get("updated_at_utc", _now_utc_iso())))
    return merged


def list_effect_template_ids(game_root: Path | str) -> dict[str, list[str]]:
    catalog = load_effect_template_catalog(game_root)
    ability_ids = sorted(_normalize_id_map(catalog.get("ability_runtime_templates", {})).keys())
    move_ids = sorted(_normalize_id_map(catalog.get("move_runtime_templates", {})).keys())
    return {
        "ability_ids": ability_ids,
        "move_ids": move_ids,
    }


_GAME_CATALOG_CACHE: dict[str, Any] = {}
_SCRIPT_ABILITY_SCAN_CACHE: dict[str, list[str]] = {}


def _iter_script_sources(root: Path) -> list[str]:
    scripts_file = _scripts_path(root)
    if not scripts_file.exists():
        return []
    scripts_obj = ev_patcher._load_scripts_object(scripts_file)
    out: list[str] = []
    for entry in scripts_obj:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        try:
            source_text, _enc = ev_patcher._decode_script_source(bytes(entry[2]))
        except Exception:
            continue
        out.append(source_text)
    return out


def _scan_runtime_ability_ids(root: Path, refresh: bool = False) -> list[str]:
    cache_key = str(root.resolve())
    if not refresh:
        cached = _SCRIPT_ABILITY_SCAN_CACHE.get(cache_key)
        if isinstance(cached, list):
            return list(cached)
    catalogs = _load_game_catalogs(root)
    if catalogs is None or not hasattr(catalogs, "abilities_by_id"):
        _SCRIPT_ABILITY_SCAN_CACHE[cache_key] = []
        return []
    known_abilities = set(getattr(catalogs, "abilities_by_id", {}).keys())
    if not known_abilities:
        _SCRIPT_ABILITY_SCAN_CACHE[cache_key] = []
        return []

    found: set[str] = set()
    for source_text in _iter_script_sources(root):
        for args_blob in _HAS_ACTIVE_ABILITY_CALL_RE.findall(source_text):
            for raw_symbol in _SYMBOL_TOKEN_RE.findall(args_blob):
                ability_id = _normalize_item_id(raw_symbol)
                if ability_id and ability_id in known_abilities:
                    found.add(ability_id)
    out = sorted(found)
    _SCRIPT_ABILITY_SCAN_CACHE[cache_key] = out
    return list(out)


def analyze_effect_template_coverage(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    catalog = load_effect_template_catalog(root)
    ability_runtime = _normalize_id_map(catalog.get("ability_runtime_templates", {}), value_kind="id")
    ability_fallback = _normalize_id_map(catalog.get("ability_item_fallback", {}), value_kind="item")
    move_runtime = _normalize_id_map(catalog.get("move_runtime_templates", {}), value_kind="id")
    move_fallback = _normalize_id_map(catalog.get("move_item_fallback", {}), value_kind="item")
    move_fn_raw = catalog.get("move_function_runtime_templates", {})
    move_fn: dict[str, str] = {}
    if isinstance(move_fn_raw, dict):
        for key, value in move_fn_raw.items():
            fn_key = str(key or "").strip()
            tpl_key = str(value or "").strip()
            if fn_key and tpl_key:
                move_fn[fn_key] = tpl_key

    catalogs = _load_game_catalogs(root)
    ability_total = len(getattr(catalogs, "abilities_by_id", {})) if catalogs is not None else 0
    move_total = len(getattr(catalogs, "moves_by_id", {})) if catalogs is not None else 0

    ability_supported = sorted(set(list(ability_runtime.keys()) + list(ability_fallback.keys())))
    move_supported: set[str] = set(list(move_runtime.keys()) + list(move_fallback.keys()))
    move_supported_native: set[str] = set(list(move_runtime.keys()) + list(move_fallback.keys()))
    runtime_move_mapped_by_function_count = 0
    runtime_move_generic_bridge_count = 0
    runtime_ability_ids = _scan_runtime_ability_ids(root)
    runtime_ability_missing = [
        aid for aid in runtime_ability_ids
        if aid not in ability_runtime and aid not in ability_fallback
    ]
    runtime_move_missing_ids: list[str] = []
    runtime_move_missing_function_codes: set[str] = set()
    if catalogs is not None and hasattr(catalogs, "moves_by_id"):
        for raw_move_id, move in getattr(catalogs, "moves_by_id", {}).items():
            move_id = _normalize_item_id(raw_move_id)
            if not move_id:
                continue
            if move_id in move_supported:
                continue
            extra = move.extra if hasattr(move, "extra") and isinstance(move.extra, dict) else {}
            function_code = str(extra.get("FunctionCode", "") or "").strip()
            if not function_code:
                runtime_move_missing_ids.append(move_id)
                continue
            if function_code in move_fn:
                runtime_move_mapped_by_function_count += 1
                move_supported.add(move_id)
                move_supported_native.add(move_id)
                continue
            # Generic move additional-effect bridge provides a partial runtime path.
            # Counted separately from native support because it only replays
            # additional-effect chance and cannot handle main-effect-only moves.
            runtime_move_generic_bridge_count += 1
            move_supported.add(move_id)
            # move_supported_native intentionally excludes generic bridge moves
            continue
    runtime_move_missing_ids = sorted(set(runtime_move_missing_ids))
    runtime_move_missing_function_code_list = sorted(runtime_move_missing_function_codes)

    # Pool-based effect stats
    pool_stats: dict[str, Any] = {"total": 0, "supported": 0, "partial": 0, "advanced": 0, "unsupported": 0}
    if _load_effect_pool_for_game is not None:
        try:
            pool = _load_effect_pool_for_game(root)
            pool_stats["total"] = len(pool)
            for e in pool.list_all():
                status = str(e.get("support_status", "unsupported"))
                if status in pool_stats:
                    pool_stats[status] = pool_stats[status] + 1
        except Exception:
            pass

    return {
        "ability_total": ability_total,
        "ability_supported": len(ability_supported),
        "ability_runtime_templates": len(ability_runtime),
        "ability_item_fallback": len(ability_fallback),
        "move_total": move_total,
        "move_supported": len(move_supported),
        "move_supported_native": len(move_supported_native),
        "move_supported_via_bridge": runtime_move_generic_bridge_count,
        "move_runtime_templates": len(move_runtime),
        "move_item_fallback": len(move_fallback),
        "move_function_runtime_templates": len(move_fn),
        "runtime_move_mapped_by_function_count": runtime_move_mapped_by_function_count,
        "runtime_move_generic_bridge_count": runtime_move_generic_bridge_count,
        "runtime_move_generic_template_key": MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY,
        "runtime_ability_scan_count": len(runtime_ability_ids),
        "runtime_ability_missing_count": len(runtime_ability_missing),
        "runtime_ability_missing_ids": runtime_ability_missing,
        "runtime_move_missing_count": len(runtime_move_missing_ids),
        "runtime_move_missing_example_ids": runtime_move_missing_ids[:50],
        "runtime_move_missing_function_code_count": len(runtime_move_missing_function_code_list),
        "runtime_move_missing_function_code_examples": runtime_move_missing_function_code_list[:50],
        "pool_effect_stats": pool_stats,
    }


def autofill_effect_template_catalog(
    game_root: Path | str,
    persist: bool = True,
    include_script_ability_scan: bool = True,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    catalog = load_effect_template_catalog(root)
    ability_runtime = _normalize_id_map(catalog.get("ability_runtime_templates", {}), value_kind="id")
    ability_fallback = _normalize_id_map(catalog.get("ability_item_fallback", {}), value_kind="item")
    move_runtime = _normalize_id_map(catalog.get("move_runtime_templates", {}), value_kind="id")

    move_fn: dict[str, str] = {}
    raw_move_fn_map = catalog.get("move_function_runtime_templates", {})
    if isinstance(raw_move_fn_map, dict):
        for key, value in raw_move_fn_map.items():
            fn_key = str(key or "").strip()
            tpl_key = str(value or "").strip()
            if fn_key and tpl_key:
                move_fn[fn_key] = tpl_key

    added_ability_runtime: dict[str, str] = {}
    scanned_runtime_abilities: list[str] = []
    if include_script_ability_scan:
        scanned_runtime_abilities = _scan_runtime_ability_ids(root, refresh=False)
        for ability_id in scanned_runtime_abilities:
            if ability_id in ability_runtime or ability_id in ability_fallback:
                continue
            ability_runtime[ability_id] = ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY
            added_ability_runtime[ability_id] = ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY

    added_move_function_templates: dict[str, str] = {}
    for move_id, template_key in move_runtime.items():
        function_code = _lookup_move_function_code(root, move_id)
        if not function_code:
            continue
        if function_code in move_fn:
            continue
        move_fn[function_code] = template_key
        added_move_function_templates[function_code] = template_key

    changed = bool(added_ability_runtime or added_move_function_templates)
    updated_catalog = dict(catalog)
    updated_catalog["ability_runtime_templates"] = {
        key: ability_runtime[key]
        for key in sorted(ability_runtime.keys(), key=str.casefold)
    }
    updated_catalog["move_function_runtime_templates"] = {
        key: move_fn[key]
        for key in sorted(move_fn.keys())
    }
    if changed:
        updated_catalog["updated_at_utc"] = _now_utc_iso()
        if persist:
            _save_json(effect_template_catalog_path(root), updated_catalog)

    coverage = analyze_effect_template_coverage(root)
    return {
        "changed": changed,
        "persisted": bool(persist and changed),
        "catalog_path": str(effect_template_catalog_path(root)),
        "added_ability_runtime_count": len(added_ability_runtime),
        "added_ability_runtime_templates": added_ability_runtime,
        "scanned_runtime_ability_count": len(scanned_runtime_abilities),
        "added_move_function_template_count": len(added_move_function_templates),
        "added_move_function_templates": added_move_function_templates,
        "coverage": coverage,
    }


def _load_game_catalogs(root: Path) -> Any | None:
    if GameCatalogs is None:
        return None
    key = str(root.resolve())
    if key in _GAME_CATALOG_CACHE:
        return _GAME_CATALOG_CACHE[key]
    try:
        catalogs = GameCatalogs.load(root)
    except Exception:  # noqa: BLE001
        catalogs = None
    _GAME_CATALOG_CACHE[key] = catalogs
    return catalogs


def _lookup_move_function_code(root: Path, move_id: str) -> str:
    move_key = _normalize_item_id(move_id)
    if not move_key:
        return ""
    catalogs = _load_game_catalogs(root)
    if catalogs is None:
        return ""
    try:
        canonical = catalogs.canonical_move_id(move_key) or move_key
    except Exception:
        canonical = move_key
    move = catalogs.moves_by_id.get(canonical) if hasattr(catalogs, "moves_by_id") else None
    if not move:
        return ""
    extra = move.extra if hasattr(move, "extra") and isinstance(move.extra, dict) else {}
    return str(extra.get("FunctionCode", "") or "").strip()


def _default_manifest() -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "updated_at_utc": _now_utc_iso(),
        "items": {},
        "last_transaction": None,
    }


def load_manifest(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    data = _load_json_with_legacy(manifest_path(root), _legacy_manifest_path(root))
    if not isinstance(data, dict):
        return _default_manifest()
    if not isinstance(data.get("items"), dict):
        data["items"] = {}
    if "last_transaction" not in data:
        data["last_transaction"] = None
    if "version" not in data:
        data["version"] = MANIFEST_VERSION
    return data


def ensure_custom_item_workspace(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    manifest_file = manifest_path(root)
    catalog_file = effect_template_catalog_path(root)
    manifest_existed = manifest_file.exists()
    catalog_existed = catalog_file.exists()

    manifest_data = load_manifest(root)
    if not manifest_file.exists():
        _save_json(manifest_file, manifest_data)

    catalog_data = load_effect_template_catalog(root)
    if not catalog_file.exists():
        _save_json(catalog_file, catalog_data)

    manifest_items = manifest_data.get("items", {}) if isinstance(manifest_data, dict) else {}
    manifest_item_count = len(manifest_items) if isinstance(manifest_items, dict) else 0

    return {
        "workspace_root": str(_custom_item_root_dir(root)),
        "data_root": str(_custom_item_data_dir(root)),
        "manifest_path": str(manifest_file),
        "catalog_path": str(catalog_file),
        "backup_root": str(_backup_root(root)),
        "manifest_created": not manifest_existed and manifest_file.exists(),
        "catalog_created": not catalog_existed and catalog_file.exists(),
        "manifest_item_count": manifest_item_count,
    }


def _item_dat_path(root: Path) -> Path:
    return root / "Data" / "items.dat"


def _scripts_path(root: Path) -> Path:
    return root / "Data" / "Scripts.rxdata"


def _normalize_item_id(value: str) -> str:
    return str(value or "").strip().lstrip(":").upper()


def _coerce_int(value: Any, default: int = 0, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        out = int(str(value).strip())
    except Exception:
        out = int(default)
    if min_value is not None:
        out = max(min_value, out)
    if max_value is not None:
        out = min(max_value, out)
    return out


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_flags(value: Any) -> list[str]:
    if isinstance(value, list):
        out = []
        for x in value:
            text = str(x).strip()
            if text:
                out.append(text)
        return out
    text = str(value or "").strip()
    if not text:
        return []
    return [chunk.strip() for chunk in text.split(",") if chunk.strip()]


def _parse_id_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        chunks = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            return []
        chunks = [chunk.strip() for chunk in text.split(",")]
    out: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        item_id = _normalize_item_id(chunk)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        out.append(item_id)
    return out


def _item_key_name(key: Any) -> str:
    if isinstance(key, core.Symbol):
        return key.name
    return str(key).strip().lstrip(":")


def _find_item_key(items_map: dict[Any, Any], item_id: str) -> Any | None:
    target = _normalize_item_id(item_id)
    for key in items_map.keys():
        if _normalize_item_id(_item_key_name(key)) == target:
            return key
    return None


def _load_items_map(root: Path) -> dict[Any, Any]:
    path = _item_dat_path(root)
    if not path.exists():
        raise FileNotFoundError(f"Missing items.dat: {path}")
    obj = core.load_save(path)
    if not isinstance(obj, dict):
        raise ValueError("items.dat payload is not a Hash/dict.")
    return obj


def _save_items_map(path: Path, items_map: dict[Any, Any]):
    core.save_save(path, items_map, make_backup=False)


def _dedupe_ids(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item_id = _normalize_item_id(value)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        out.append(item_id)
    return out


def _legacy_effect_selection(effect_spec: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    selected_items = _parse_id_list(effect_spec.get("selected_item_effect_ids", []))
    selected_moves = _parse_id_list(effect_spec.get("selected_move_effect_ids", []))
    selected_abilities = _parse_id_list(effect_spec.get("selected_ability_effect_ids", []))
    if selected_items or selected_moves or selected_abilities:
        return selected_items, selected_moves, selected_abilities

    mode = str(effect_spec.get("mode", "none")).strip().lower()
    source_item = _normalize_item_id(effect_spec.get("source_item_id", ""))
    ability_id = _normalize_item_id(effect_spec.get("ability_id", ""))
    move_id = _normalize_item_id(effect_spec.get("move_id", ""))
    origin_mode = str(effect_spec.get("origin_mode", "")).strip().lower()
    origin_id = _normalize_item_id(effect_spec.get("origin_id", ""))

    if mode == "clone_item" and source_item:
        selected_items.append(source_item)
    elif mode == "ability_template":
        if source_item:
            selected_items.append(source_item)
        if ability_id:
            selected_abilities.append(ability_id)
    elif mode == "move_template":
        if source_item:
            selected_items.append(source_item)
        if move_id:
            selected_moves.append(move_id)

    if origin_mode == "ability_template" and origin_id:
        selected_abilities.append(origin_id)
    elif origin_mode == "move_template" and origin_id:
        selected_moves.append(origin_id)
    elif origin_mode == "clone_item" and origin_id:
        selected_items.append(origin_id)

    selected_items.extend(_parse_id_list(effect_spec.get("extra_source_item_ids", [])))
    selected_items.extend(_parse_id_list(effect_spec.get("resolved_source_item_ids", [])))
    selected_abilities.extend(_parse_id_list(effect_spec.get("extra_ability_ids", [])))
    selected_moves.extend(_parse_id_list(effect_spec.get("extra_move_ids", [])))
    return _dedupe_ids(selected_items), _dedupe_ids(selected_moves), _dedupe_ids(selected_abilities)


def _resolve_effect_spec(root: Path, effect_spec: dict[str, Any]) -> dict[str, Any]:
    payload = effect_spec if isinstance(effect_spec, dict) else {}
    selected_item_ids, selected_move_ids, selected_ability_ids = _legacy_effect_selection(payload)

    template_catalog = load_effect_template_catalog(root)
    ability_item_fallback = dict(ABILITY_TEMPLATE_TO_ITEM)
    ability_item_fallback.update(
        _normalize_id_map(template_catalog.get("ability_item_fallback", {}), value_kind="item")
    )
    move_item_fallback = dict(MOVE_TEMPLATE_TO_ITEM)
    move_item_fallback.update(
        _normalize_id_map(template_catalog.get("move_item_fallback", {}), value_kind="item")
    )

    ability_runtime_templates = dict(ABILITY_RUNTIME_TEMPLATES)
    ability_runtime_templates.update(
        _normalize_id_map(template_catalog.get("ability_runtime_templates", {}), value_kind="id")
    )
    move_runtime_templates = dict(MOVE_RUNTIME_TEMPLATES)
    move_runtime_templates.update(
        _normalize_id_map(template_catalog.get("move_runtime_templates", {}), value_kind="id")
    )
    move_function_runtime_templates = dict(MOVE_FUNCTION_RUNTIME_TEMPLATES)
    raw_move_fn_map = template_catalog.get("move_function_runtime_templates", {})
    if isinstance(raw_move_fn_map, dict):
        for key, value in raw_move_fn_map.items():
            fn_key = str(key or "").strip()
            tpl_key = str(value or "").strip()
            if fn_key and tpl_key:
                move_function_runtime_templates[fn_key] = tpl_key

    resolved_sources: list[str] = []
    resolved_templates: list[dict[str, Any]] = []
    unsupported_reasons: list[str] = []
    resolved_pool_effects: list[dict[str, Any]] = []

    # --- Pool-based effect resolution ---
    # Legacy UI still lets users select effects by original source bucket
    # (item/move/ability). For hook-based runtime effects, route known
    # legacy selections into normalized pool effects and skip their old
    # bridge/copy path. This keeps the current UI working while avoiding
    # wrong generic bridges for status/self-buff moves (e.g. Swords Dance).
    selected_effect_ids = _parse_id_list(payload.get("selected_effect_ids", []))
    selected_effect_params_raw = payload.get("selected_effect_params", {})
    selected_effect_params: dict[str, dict[str, Any]] = {}
    if isinstance(selected_effect_params_raw, dict):
        for key, value in selected_effect_params_raw.items():
            eid = _normalize_item_id(key)
            if eid and isinstance(value, dict):
                selected_effect_params[eid] = dict(value)
    legacy_pool_aliases: dict[tuple[str, str], list[str]] = {
        ("item", "LEFTOVERS"): ["LEFTOVERS_HEAL_1_16"],
        ("item", "BIGROOT"): ["BIG_ROOT_DRAIN_MULTIPLIER"],
        ("item", "LIFEORB"): ["LIFE_ORB_DAMAGE_BOOST"],
        ("move", "DRAININGKISS"): ["DRAINING_KISS_HEAL_75"],
        ("move", "SWORDSDANCE"): ["SWORDSDANCE_AFTER_MOVE"],
        ("move", "NASTYPLOT"): ["NASTYPLOT_AFTER_MOVE"],
        ("ability", "SPEEDBOOST"): ["SPEEDBOOST_END_OF_ROUND"],
        ("ability", "CHLOROPHYLL"): ["CHLOROPHYLL_SPEED_IN_SUN"],
        ("ability", "SHEERFORCE"): ["SHEER_FORCE_MODIFIER"],
    }
    # Phase 2A: automatically route legacy UI selections into normalized pool
    # effects whenever a supported/partial effect has the same source_kind/source_id.
    # This keeps the existing Item/Move/Ability picker usable while the runtime
    # engine is driven by hook/template/params metadata. One source can map to
    # multiple pool effects (for example BLACKSLUDGE heal + damage branches).
    if _load_effect_pool_for_game is not None:
        try:
            _alias_pool = _load_effect_pool_for_game(root)
            for _effect in _alias_pool.list_all():
                _status = str(_effect.get("support_status", "")).strip().lower()
                if _status not in {"supported", "partial"}:
                    continue
                _kind = str(_effect.get("source_kind", "")).strip().lower()
                _source = _normalize_item_id(_effect.get("source_id", ""))
                _eid = str(_effect.get("id", "")).strip()
                if _kind in {"item", "move", "ability"} and _source and _eid:
                    _key = (_kind, _source)
                    _bucket = legacy_pool_aliases.setdefault(_key, [])
                    if _eid not in _bucket:
                        _bucket.append(_eid)
        except Exception:
            pass
    aliased_item_ids: set[str] = set()
    aliased_move_ids: set[str] = set()
    aliased_ability_ids: set[str] = set()
    pool_effect_ids_to_resolve: list[str] = []

    def _append_pool_effect_id(effect_id: str):
        eid = str(effect_id or "").strip()
        if eid and eid not in pool_effect_ids_to_resolve:
            pool_effect_ids_to_resolve.append(eid)

    for eid in selected_effect_ids:
        _append_pool_effect_id(eid)
    def _append_legacy_aliases(kind: str, source_id: str) -> bool:
        aliases = legacy_pool_aliases.get((kind, _normalize_item_id(source_id)))
        if not aliases:
            return False
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases:
            _append_pool_effect_id(alias)
        return True

    for iid in selected_item_ids:
        if _append_legacy_aliases("item", iid):
            aliased_item_ids.add(_normalize_item_id(iid))
    for mid in selected_move_ids:
        if _append_legacy_aliases("move", mid):
            aliased_move_ids.add(_normalize_item_id(mid))
    for aid in selected_ability_ids:
        if _append_legacy_aliases("ability", aid):
            aliased_ability_ids.add(_normalize_item_id(aid))

    if pool_effect_ids_to_resolve and _load_effect_pool_for_game is not None:
        try:
            pool = _load_effect_pool_for_game(root)
            for eid in pool_effect_ids_to_resolve:
                effect_def = pool.get_by_id(eid)
                if effect_def is None:
                    unsupported_reasons.append(f"Pool effect not found in custom_effect_pool.json: {eid}")
                elif str(effect_def.get("support_status", "")) == "unsupported":
                    unsupported_reasons.append(
                        f"Pool effect marked unsupported: {eid} — {effect_def.get('notes', '')}"
                    )
                else:
                    resolved = dict(effect_def)
                    override_params = selected_effect_params.get(_normalize_item_id(eid))
                    if override_params is not None:
                        resolved["params"] = override_params
                    resolved_pool_effects.append(resolved)
        except Exception as exc:
            unsupported_reasons.append(f"Failed to load effect pool: {exc}")
    elif pool_effect_ids_to_resolve:
        unsupported_reasons.append("Effect pool module unavailable; selected_effect_ids could not be resolved.")

    def add_source(item_id: str):
        source = _normalize_item_id(item_id)
        if source and source not in resolved_sources:
            resolved_sources.append(source)

    for source_item_id in selected_item_ids:
        if _normalize_item_id(source_item_id) in aliased_item_ids:
            continue
        add_source(source_item_id)

    for ability_id in selected_ability_ids:
        if _normalize_item_id(ability_id) in aliased_ability_ids:
            continue
        mapped_source = _normalize_item_id(ability_item_fallback.get(ability_id, ""))
        template_key = str(ability_runtime_templates.get(ability_id, "")).strip()
        if mapped_source:
            add_source(mapped_source)
        if template_key:
            resolved_templates.append(
                {
                    "source_kind": "ability",
                    "source_id": ability_id,
                    "template_key": template_key,
                }
            )
        if not mapped_source and not template_key:
            unsupported_reasons.append(
                (
                    f"Unsupported ability mapping: {ability_id} "
                    "(no entry in ability_runtime_templates or ability_item_fallback)"
                )
            )

    for move_id in selected_move_ids:
        if _normalize_item_id(move_id) in aliased_move_ids:
            continue
        mapped_source = _normalize_item_id(move_item_fallback.get(move_id, ""))
        template_key = str(move_runtime_templates.get(move_id, "")).strip()
        function_code = ""
        if not template_key:
            function_code = _lookup_move_function_code(root, move_id)
            if function_code:
                template_key = str(move_function_runtime_templates.get(function_code, "")).strip()
            if not template_key and function_code:
                template_key = MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY
        if mapped_source:
            add_source(mapped_source)
        if template_key:
            row: dict[str, Any] = {
                "source_kind": "move",
                "source_id": move_id,
                "template_key": template_key,
            }
            if function_code:
                row["move_function_code"] = function_code
            resolved_templates.append(row)
        if not mapped_source and not template_key:
            unsupported_reasons.append(
                (
                    f"Unsupported move mapping: {move_id} "
                    "(no entry in move_runtime_templates/move_item_fallback/move_function_runtime_templates "
                    "and no usable FunctionCode for move_additional_effect_bridge)"
                )
            )

    deduped_templates: list[dict[str, Any]] = []
    seen_templates: set[tuple[str, str, str]] = set()
    for row in resolved_templates:
        key = (
            str(row.get("template_key", "")).strip(),
            str(row.get("source_kind", "")).strip(),
            _normalize_item_id(row.get("source_id", "")),
        )
        if not key[0] or key in seen_templates:
            continue
        seen_templates.add(key)
        deduped_templates.append(dict(row))

    has_effect = bool(resolved_sources or deduped_templates or resolved_pool_effects)
    mode = "composite" if has_effect else "none"
    return {
        "mode": mode,
        "source_item_id": resolved_sources[0] if resolved_sources else "",
        "resolved_source_item_ids": list(resolved_sources),
        "selected_item_effect_ids": list(selected_item_ids),
        "selected_move_effect_ids": list(selected_move_ids),
        "selected_ability_effect_ids": list(selected_ability_ids),
        "selected_effect_ids": list(pool_effect_ids_to_resolve),
        "selected_effect_params": dict(selected_effect_params),
        "resolved_templates": deduped_templates,
        "resolved_pool_effects": resolved_pool_effects,
        "unsupported_reasons": list(unsupported_reasons),
        "unsupported_reason": "; ".join(unsupported_reasons),
    }


def _effect_spec_requires_scripts(effect_spec: dict[str, Any]) -> bool:
    if not isinstance(effect_spec, dict):
        return False
    mode = str(effect_spec.get("mode", "none")).strip().lower()
    if mode == "none":
        return False
    if effect_spec.get("resolved_source_item_ids"):
        return True
    if effect_spec.get("resolved_templates"):
        return True
    if effect_spec.get("selected_item_effect_ids"):
        return True
    if effect_spec.get("selected_move_effect_ids"):
        return True
    if effect_spec.get("selected_ability_effect_ids"):
        return True
    if effect_spec.get("selected_effect_ids"):
        return True
    if effect_spec.get("resolved_pool_effects"):
        return True
    return mode in {"clone_item", "ability_template", "move_template", "composite"}


def _scan_item_effect_buckets(root: Path, source_item_id: str) -> dict[str, list[str]]:
    source = _normalize_item_id(source_item_id)
    if not source:
        return {"item_handlers": [], "battle_item_effects": []}
    scripts_file = _scripts_path(root)
    if not scripts_file.exists():
        return {"item_handlers": [], "battle_item_effects": []}
    scripts_obj = ev_patcher._load_scripts_object(scripts_file)
    item_handlers: set[str] = set()
    battle_item_effects: set[str] = set()
    for entry in scripts_obj:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        try:
            source_text, _enc = ev_patcher._decode_script_source(bytes(entry[2]))
        except Exception:
            continue
        for line in source_text.splitlines():
            symbols = {_normalize_item_id(sym) for sym in _SYMBOL_TOKEN_RE.findall(line)}
            if source not in symbols:
                continue
            m_item = _ITEM_HANDLERS_CALL_RE.search(line)
            if m_item:
                item_handlers.add(m_item.group(1))
            m_battle = _BATTLE_ITEM_EFFECTS_CALL_RE.search(line)
            if m_battle:
                battle_item_effects.add(m_battle.group(1))
    return {
        "item_handlers": sorted(item_handlers),
        "battle_item_effects": sorted(battle_item_effects),
    }


def _build_contrary_template_lines(item_ids: list[str]) -> list[str]:
    deduped = _dedupe_ids(item_ids)
    if not deduped:
        return []
    item_sym_list = ", ".join(f":{item_id}" for item_id in deduped)
    return [
        "# --- runtime template: ability_contrary ---",
        "module CustomItemPatch",
        f"  CONTRARY_ITEM_IDS = [{item_sym_list}]",
        "",
        "  def self.contrary_item?(battler)",
        "    return false if !custom_item_effect_item_active?(battler)",
        "    item = battler.item",
        "    return false if !item",
        "    item_id = item.respond_to?(:id) ? item.id : item",
        "    item_id = item_id.to_sym if !item_id.is_a?(Symbol) && item_id.respond_to?(:to_sym)",
        "    return false if !item_id",
        "    return CONTRARY_ITEM_IDS.include?(item_id)",
        "  end",
        "end",
        "",
        "class Battle::Battler",
        "  unless method_defined?(:custom_item_patch_pbCanRaiseStatStage_old)",
        "    alias custom_item_patch_pbCanRaiseStatStage_old pbCanRaiseStatStage?",
        "  end",
        "  def pbCanRaiseStatStage?(stat, user = nil, move = nil, showFailMsg = false, ignoreContrary = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbCanLowerStatStage?(stat, user, move, showFailMsg, true)",
        "    end",
        "    return custom_item_patch_pbCanRaiseStatStage_old(stat, user, move, showFailMsg, ignoreContrary)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbRaiseStatStageBasic_old)",
        "    alias custom_item_patch_pbRaiseStatStageBasic_old pbRaiseStatStageBasic",
        "  end",
        "  def pbRaiseStatStageBasic(stat, increment, ignoreContrary = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbLowerStatStageBasic(stat, increment, true)",
        "    end",
        "    return custom_item_patch_pbRaiseStatStageBasic_old(stat, increment, ignoreContrary)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbRaiseStatStage_old)",
        "    alias custom_item_patch_pbRaiseStatStage_old pbRaiseStatStage",
        "  end",
        "  def pbRaiseStatStage(stat, increment, user, showAnim = true, ignoreContrary = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbLowerStatStage(stat, increment, user, showAnim, true)",
        "    end",
        "    return custom_item_patch_pbRaiseStatStage_old(stat, increment, user, showAnim, ignoreContrary)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbRaiseStatStageByCause_old)",
        "    alias custom_item_patch_pbRaiseStatStageByCause_old pbRaiseStatStageByCause",
        "  end",
        "  def pbRaiseStatStageByCause(stat, increment, user, cause, showAnim = true, ignoreContrary = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbLowerStatStageByCause(stat, increment, user, cause, showAnim, true)",
        "    end",
        "    return custom_item_patch_pbRaiseStatStageByCause_old(stat, increment, user, cause, showAnim, ignoreContrary)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbCanLowerStatStage_old)",
        "    alias custom_item_patch_pbCanLowerStatStage_old pbCanLowerStatStage?",
        "  end",
        "  def pbCanLowerStatStage?(stat, user = nil, move = nil, showFailMsg = false, ignoreContrary = false, ignoreMirrorArmor = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbCanRaiseStatStage?(stat, user, move, showFailMsg, true)",
        "    end",
        "    return custom_item_patch_pbCanLowerStatStage_old(stat, user, move, showFailMsg, ignoreContrary, ignoreMirrorArmor)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbLowerStatStageBasic_old)",
        "    alias custom_item_patch_pbLowerStatStageBasic_old pbLowerStatStageBasic",
        "  end",
        "  def pbLowerStatStageBasic(stat, increment, ignoreContrary = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbRaiseStatStageBasic(stat, increment, true)",
        "    end",
        "    return custom_item_patch_pbLowerStatStageBasic_old(stat, increment, ignoreContrary)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbLowerStatStage_old)",
        "    alias custom_item_patch_pbLowerStatStage_old pbLowerStatStage",
        "  end",
        "  def pbLowerStatStage(stat, increment, user, showAnim = true, ignoreContrary = false, mirrorArmorSplash = 0, ignoreMirrorArmor = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbRaiseStatStage(stat, increment, user, showAnim, true)",
        "    end",
        "    return custom_item_patch_pbLowerStatStage_old(stat, increment, user, showAnim, ignoreContrary, mirrorArmorSplash, ignoreMirrorArmor)",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbLowerStatStageByCause_old)",
        "    alias custom_item_patch_pbLowerStatStageByCause_old pbLowerStatStageByCause",
        "  end",
        "  def pbLowerStatStageByCause(stat, increment, user, cause, showAnim = true, ignoreContrary = false, ignoreMirrorArmor = false)",
        "    if CustomItemPatch.contrary_item?(self) && !ignoreContrary && !@battle.moldBreaker",
        "      return pbRaiseStatStageByCause(stat, increment, user, cause, showAnim, true)",
        "    end",
        "    return custom_item_patch_pbLowerStatStageByCause_old(stat, increment, user, cause, showAnim, ignoreContrary, ignoreMirrorArmor)",
        "  end",
        "end",
        "",
    ]


def _build_sheer_force_template_lines(item_ids: list[str]) -> list[str]:
    deduped = _dedupe_ids(item_ids)
    if not deduped:
        return []
    item_sym_list = ", ".join(f":{item_id}" for item_id in deduped)
    return [
        "# --- runtime template: ability_sheer_force ---",
        "module CustomItemPatch",
        f"  SHEERFORCE_ITEM_IDS = [{item_sym_list}]",
        "",
        "  def self.sheer_force_item?(battler)",
        "    return false if !custom_item_effect_item_active?(battler)",
        "    item = battler.item",
        "    return false if !item",
        "    item_id = item.respond_to?(:id) ? item.id : item",
        "    item_id = item_id.to_sym if !item_id.is_a?(Symbol) && item_id.respond_to?(:to_sym)",
        "    return false if !item_id",
        "    return SHEERFORCE_ITEM_IDS.include?(item_id)",
        "  end",
        "end",
        "",
        "class Battle::Battler",
        "  unless method_defined?(:custom_item_patch_hasActiveAbility_old)",
        "    alias custom_item_patch_hasActiveAbility_old hasActiveAbility?",
        "  end",
        "  def hasActiveAbility?(check_ability, ignore_fainted = false)",
        "    ret = custom_item_patch_hasActiveAbility_old(check_ability, ignore_fainted)",
        "    return true if ret",
        "    return false if !CustomItemPatch.sheer_force_item?(self)",
        "    checks = check_ability.is_a?(Array) ? check_ability : [check_ability]",
        "    checks.each do |entry|",
        "      next if !entry",
        "      abil = entry.respond_to?(:id) ? entry.id : entry",
        "      abil = abil.to_sym if !abil.is_a?(Symbol) && abil.respond_to?(:to_sym)",
        "      return true if abil == :SHEERFORCE",
        "    end",
        "    return false",
        "  end",
        "end",
        "",
    ]


def _build_ability_active_bridge_template_lines(ability_item_map: dict[str, list[str]]) -> list[str]:
    normalized_map: dict[str, list[str]] = {}
    for raw_ability_id, raw_item_ids in ability_item_map.items():
        ability_id = _normalize_item_id(raw_ability_id)
        if not ability_id:
            continue
        item_ids: list[str] = []
        if isinstance(raw_item_ids, list):
            for raw_item_id in raw_item_ids:
                item_id = _normalize_item_id(raw_item_id)
                if item_id:
                    item_ids.append(item_id)
        deduped_items = _dedupe_ids(item_ids)
        if deduped_items:
            normalized_map[ability_id] = deduped_items
    if not normalized_map:
        return []

    map_rows = ["  ABILITY_ACTIVE_BRIDGE_ITEMS = {"]
    sorted_ids = sorted(normalized_map.keys(), key=str.casefold)
    for idx, ability_id in enumerate(sorted_ids):
        item_sym_list = ", ".join(f":{item_id}" for item_id in normalized_map[ability_id])
        suffix = "," if idx < len(sorted_ids) - 1 else ""
        map_rows.append(f"    :{ability_id} => [{item_sym_list}]{suffix}")
    map_rows.append("  }")

    return [
        f"# --- runtime template: {ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY} ---",
        "module CustomItemPatch",
        *map_rows,
        "",
        "  def self.ability_active_bridge_item?(battler, ability_id)",
        "    return false if !custom_item_effect_item_active?(battler)",
        "    return false if !ability_id",
        "    abil = ability_id.respond_to?(:id) ? ability_id.id : ability_id",
        "    abil = abil.to_sym if !abil.is_a?(Symbol) && abil.respond_to?(:to_sym)",
        "    return false if !abil",
        "    ability_map = ABILITY_ACTIVE_BRIDGE_ITEMS",
        "    return false if !ability_map || !ability_map.respond_to?(:[])",
        "    mapped_items = ability_map[abil]",
        "    return false if !mapped_items || mapped_items.empty?",
        "    item = battler.item",
        "    return false if !item",
        "    item_id = item.respond_to?(:id) ? item.id : item",
        "    item_id = item_id.to_sym if !item_id.is_a?(Symbol) && item_id.respond_to?(:to_sym)",
        "    return false if !item_id",
        "    return mapped_items.include?(item_id)",
        "  end",
        "",
        "  def self.ability_active_bridge_ability_ids_for(battler, ignore_fainted = false)",
        "    return [] if !custom_item_effect_item_active?(battler, ignore_fainted)",
        "    item = battler.item",
        "    return [] if !item",
        "    item_id = item.respond_to?(:id) ? item.id : item",
        "    item_id = item_id.to_sym if !item_id.is_a?(Symbol) && item_id.respond_to?(:to_sym)",
        "    return [] if !item_id",
        "    out = []",
        "    ability_map = ABILITY_ACTIVE_BRIDGE_ITEMS",
        "    return out if !ability_map || !ability_map.respond_to?(:each)",
        "    ability_map.each do |ability_id, mapped_items|",
        "      next if !mapped_items || mapped_items.empty?",
        "      out << ability_id if mapped_items.include?(item_id)",
        "    end",
        "    return out",
        "  end",
        "end",
        "",
        "class Battle::Battler",
        "  unless method_defined?(:custom_item_patch_hasActiveAbility_bridge_old)",
        "    alias custom_item_patch_hasActiveAbility_bridge_old hasActiveAbility?",
        "  end",
        "  def hasActiveAbility?(check_ability, ignore_fainted = false)",
        "    ret = custom_item_patch_hasActiveAbility_bridge_old(check_ability, ignore_fainted)",
        "    return true if ret",
        "    checks = check_ability.is_a?(Array) ? check_ability : [check_ability]",
        "    checks.each do |entry|",
        "      next if !entry",
        "      return true if CustomItemPatch.ability_active_bridge_item?(self, entry)",
        "    end",
        "    return false",
        "  end",
        "end",
        "",
        "module Battle::AbilityEffects",
        "  class << self",
        "    unless method_defined?(:custom_item_patch_triggerEndOfRoundHealing_bridge_old)",
        "      alias custom_item_patch_triggerEndOfRoundHealing_bridge_old triggerEndOfRoundHealing",
        "    end",
        "    def triggerEndOfRoundHealing(ability, battler, battle)",
        "      base_ret = custom_item_patch_triggerEndOfRoundHealing_bridge_old(ability, battler, battle)",
        "      bridge_ids = CustomItemPatch.ability_active_bridge_ability_ids_for(battler)",
        "      return base_ret if !bridge_ids || bridge_ids.empty?",
        "      current_ability = ability.respond_to?(:id) ? ability.id : ability",
        "      current_ability = current_ability.to_sym if current_ability && !current_ability.is_a?(Symbol) && current_ability.respond_to?(:to_sym)",
        "      bridge_ids.each do |bridge_ability_id|",
        "        next if !bridge_ability_id",
        "        next if current_ability && bridge_ability_id == current_ability",
        "        custom_item_patch_triggerEndOfRoundHealing_bridge_old(bridge_ability_id, battler, battle)",
        "      end",
        "      return base_ret",
        "    end",
        "  end",
        "end",
        "",
    ]


def _build_move_additional_effect_bridge_template_lines(move_item_map: dict[str, list[str]]) -> list[str]:
    normalized_map: dict[str, list[str]] = {}
    for raw_move_id, raw_item_ids in move_item_map.items():
        move_id = _normalize_item_id(raw_move_id)
        if not move_id:
            continue
        item_ids: list[str] = []
        if isinstance(raw_item_ids, list):
            for raw_item_id in raw_item_ids:
                item_id = _normalize_item_id(raw_item_id)
                if item_id:
                    item_ids.append(item_id)
        deduped_items = _dedupe_ids(item_ids)
        if deduped_items:
            normalized_map[move_id] = deduped_items
    if not normalized_map:
        return []

    map_rows = ["  MOVE_ADDITIONAL_EFFECT_BRIDGE_ITEMS = {"]
    sorted_ids = sorted(normalized_map.keys(), key=str.casefold)
    for idx, move_id in enumerate(sorted_ids):
        item_sym_list = ", ".join(f":{item_id}" for item_id in normalized_map[move_id])
        suffix = "," if idx < len(sorted_ids) - 1 else ""
        map_rows.append(f"    :{move_id} => [{item_sym_list}]{suffix}")
    map_rows.append("  }")

    return [
        f"# --- runtime template: {MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY} ---",
        "module CustomItemPatch",
        *map_rows,
        "",
        "  def self.move_additional_effect_bridge_move_ids_for(battler)",
        "    return [] if !custom_item_effect_item_active?(battler)",
        "    item = battler.item",
        "    return [] if !item",
        "    item_id = item.respond_to?(:id) ? item.id : item",
        "    item_id = item_id.to_sym if !item_id.is_a?(Symbol) && item_id.respond_to?(:to_sym)",
        "    return [] if !item_id",
        "    out = []",
        "    move_map = MOVE_ADDITIONAL_EFFECT_BRIDGE_ITEMS",
        "    return out if !move_map || !move_map.respond_to?(:each)",
        "    move_map.each do |move_id, mapped_items|",
        "      next if !mapped_items || mapped_items.empty?",
        "      out << move_id if mapped_items.include?(item_id)",
        "    end",
        "    return out",
        "  end",
        "end",
        "",
        "class Battle::Battler",
        "  unless method_defined?(:custom_item_patch_pbProcessMoveHit_old)",
        "    alias custom_item_patch_pbProcessMoveHit_old pbProcessMoveHit",
        "  end",
        "  def pbProcessMoveHit(move, user, targets, hitNum, skipAccuracyCheck)",
        "    custom_item_patch_pbProcessMoveHit_old(move, user, targets, hitNum, skipAccuracyCheck)",
        "    return if !user || user.fainted?",
        "    return if user != self",
        "    return if user.hasActiveAbility?(:SHEERFORCE)",
        "    source_move_ids = CustomItemPatch.move_additional_effect_bridge_move_ids_for(user)",
        "    return if source_move_ids.empty?",
        "    target_list = targets.is_a?(Array) ? targets : []",
        "    source_move_ids.each do |source_move_id|",
        "      source_move = nil",
        "      begin",
        "        source_move = Battle::Move.from_pokemon_move(@battle, Pokemon::Move.new(source_move_id))",
        "      rescue StandardError",
        "        source_move = nil",
        "      end",
        "      next if !source_move",
        "      target_list.each do |target|",
        "        next if !target || target.fainted?",
        "        next if !target.damageState || target.damageState.calcDamage == 0",
        "        chance = source_move.pbAdditionalEffectChance(user, target)",
        "        next if chance <= 0",
        "        source_move.pbAdditionalEffect(user, target) if @battle.pbRandom(100) < chance",
        "      end",
        "    end",
        "  end",
        "end",
        "",
    ]


def _build_item_activity_helper_lines() -> list[str]:
    return [
        "# --- runtime helper: item-activity checks without hasActiveAbility?/itemActive? recursion ---",
        "module CustomItemPatch",
        "  def self.custom_item_effect_battler_effect_value(battler, effect_key)",
        "    return nil if !battler || !battler.respond_to?(:effects)",
        "    effects = battler.effects",
        "    return nil if !effects || !effects.respond_to?(:[])",
        "    begin",
        "      return effects[effect_key]",
        "    rescue StandardError",
        "      return nil",
        "    end",
        "  end",
        "",
        "  def self.custom_item_effect_battler_ability_id(battler)",
        "    return nil if !battler",
        "    abil = nil",
        "    if battler.respond_to?(:ability_id)",
        "      abil = battler.ability_id",
        "    elsif battler.respond_to?(:ability)",
        "      ability_obj = battler.ability",
        "      abil = ability_obj.respond_to?(:id) ? ability_obj.id : ability_obj",
        "    end",
        "    abil = abil.to_sym if abil && !abil.is_a?(Symbol) && abil.respond_to?(:to_sym)",
        "    return abil",
        "  rescue StandardError",
        "    return nil",
        "  end",
        "",
        "  def self.custom_item_effect_neutralizing_gas_active?(battle, ignore_fainted = false)",
        "    return false if !battle || !battle.respond_to?(:allBattlers)",
        "    battle.allBattlers.each do |other|",
        "      next if !other",
        "      if !ignore_fainted && other.respond_to?(:fainted?)",
        "        next if other.fainted?",
        "      end",
        "      gastro = custom_item_effect_battler_effect_value(other, PBEffects::GastroAcid)",
        "      next if gastro && gastro.to_i > 0",
        "      return true if custom_item_effect_battler_ability_id(other) == :NEUTRALIZINGGAS",
        "    end",
        "    return false",
        "  rescue StandardError",
        "    return false",
        "  end",
        "",
        "  def self.custom_item_effect_item_active?(battler, ignore_fainted = false)",
        "    return false if !battler",
        "    if !ignore_fainted && battler.respond_to?(:fainted?)",
        "      return false if battler.fainted?",
        "    end",
        "    embargo = custom_item_effect_battler_effect_value(battler, PBEffects::Embargo)",
        "    return false if embargo && embargo.to_i > 0",
        "    battle = battler.respond_to?(:battle) ? battler.battle : nil",
        "    battle = battler.instance_variable_get(:@battle) if !battle",
        "    field = nil",
        "    if battle && battle.respond_to?(:field)",
        "      field = battle.field",
        "    elsif battle",
        "      field = battle.instance_variable_get(:@field) rescue nil",
        "    end",
        "    if field && field.respond_to?(:effects)",
        "      field_effects = field.effects",
        "      if field_effects && field_effects.respond_to?(:[])",
        "        magic_room = field_effects[PBEffects::MagicRoom] rescue 0",
        "        return false if magic_room.to_i > 0",
        "      end",
        "    end",
        "    if battle && battle.respond_to?(:corrosiveGas) && battler.respond_to?(:index) && battler.respond_to?(:pokemonIndex)",
        "      begin",
        "        corrosive = battle.corrosiveGas",
        "        row = corrosive[battler.index % 2] if corrosive && corrosive.respond_to?(:[])",
        "        blocked = row[battler.pokemonIndex] if row && row.respond_to?(:[])",
        "        return false if blocked",
        "      rescue StandardError",
        "      end",
        "    end",
        "    ability_id = custom_item_effect_battler_ability_id(battler)",
        "    if ability_id == :KLUTZ",
        "      gastro_self = custom_item_effect_battler_effect_value(battler, PBEffects::GastroAcid)",
        "      return true if gastro_self && gastro_self.to_i > 0",
        "      if custom_item_effect_neutralizing_gas_active?(battle, ignore_fainted)",
        "        return true",
        "      end",
        "      return false",
        "    end",
        "    return true",
        "  rescue StandardError",
        "    return false",
        "  end",
        "end",
        "",
    ]


def _build_drain_template_lines(item_id: str, heal_ratio: float) -> list[str]:
    ratio = max(0.01, min(3.0, float(heal_ratio)))
    ratio_text = f"{ratio:.4f}".rstrip("0").rstrip(".")
    return [
        f"# --- runtime template: drain ({ratio_text}) for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::AfterMoveUseFromUser.add(:{item_id},",
        "    proc { |item, user, targets, move, numHits, battle|",
        "      next if !user.canHeal?",
        "      targets.each do |target|",
        "        next if !target || !target.damageState",
        "        hp_lost = target.damageState.totalHPLost",
        "        next if hp_lost <= 0",
        f"        hp_gain = (hp_lost * {ratio_text}).round",
        "        next if hp_gain <= 0",
        "        user.pbRecoverHPFromDrain(hp_gain, target, _INTL(\"{1} regained HP with {2}!\", user.pbThis, user.itemName))",
        "      end",
        "    }",
        "  )",
        "rescue StandardError => e",
        "  echoln(\"CustomItemPatch error: #{e}\") if defined?(echoln)",
        "end",
        "",
    ]


def _build_interpreter_nil_backtrace_guard_lines() -> list[str]:
    return [
        "# --- runtime compatibility: Interpreter nil-backtrace guard ---",
        "class Interpreter",
        "  def execute_script(script)",
        "    custom_item_vowe_lock_key = nil",
        "    if script && script.include?(\"pbSingleOrDoubleWildBattle(\") && $game_temp",
        "      begin",
        "        map_id = ($game_map && $game_map.respond_to?(:map_id)) ? $game_map.map_id : nil",
        "        event_id = nil",
        "        begin",
        "          event_id = @event_id",
        "        rescue StandardError",
        "          event_id = nil",
        "        end",
        "        lock_key = [map_id, event_id]",
        "        lock_map = $game_temp.instance_variable_get(:@custom_item_patch_vowe_script_lock)",
        "        lock_map = {} if !lock_map || !lock_map.respond_to?(:[]) || !lock_map.respond_to?(:[]=)",
        "        if lock_map[lock_key]",
        "          begin",
        "            trace_path = nil",
        "            if ENV[\"APPDATA\"] && !ENV[\"APPDATA\"].empty?",
        "              trace_path = File.join(ENV[\"APPDATA\"], \"Pokemon Anil\", \"custom_item_vowe_reentry.log\")",
        "            end",
        "            if trace_path",
        "              stamp = Time.now.strftime(\"%Y-%m-%d %H:%M:%S\")",
        "              msg = stamp + \" blocked re-entry map=\" + map_id.to_s + \" event=\" + event_id.to_s",
        "              File.open(trace_path, \"a\") { |f| f.puts(msg) }",
        "            end",
        "          rescue StandardError",
        "          end",
        "          return false",
        "        end",
        "        lock_map[lock_key] = true",
        "        $game_temp.instance_variable_set(:@custom_item_patch_vowe_script_lock, lock_map)",
        "        custom_item_vowe_lock_key = lock_key",
        "      rescue StandardError",
        "        custom_item_vowe_lock_key = nil",
        "      end",
        "    end",
        "    begin",
        "      result = eval(script)",
        "      return result",
        "    rescue Exception",
        "      e = $!",
        "      raise if e.is_a?(SystemExit) || e.class.to_s == \"Reset\"",
        "      event = get_self",
        "      message = pbGetExceptionMessage(e)",
        "      if e.is_a?(SystemStackError)",
        "        begin",
        "          trace_path = nil",
        "          if ENV[\"APPDATA\"] && !ENV[\"APPDATA\"].empty?",
        "            trace_path = File.join(ENV[\"APPDATA\"], \"Pokemon Anil\", \"custom_item_system_stack_trace.log\")",
        "          end",
        "          if trace_path",
        "            File.open(trace_path, \"a\") do |f|",
        "              stamp = Time.now.strftime(\"%Y-%m-%d %H:%M:%S\")",
        "              map_id_txt = (($game_map && $game_map.respond_to?(:map_id)) ? $game_map.map_id : nil).to_s",
        "              event_id_txt = ((@event_id rescue nil) || (event && event.id)).to_s",
        "              f.puts(\"=== \" + stamp + \" ===\")",
        "              f.puts(\"map_id=\" + map_id_txt + \" event_id=\" + event_id_txt)",
        "              f.puts(\"script:\")",
        "              f.puts(script.to_s)",
        "              f.puts(\"backtrace:\")",
        "              bt_all = nil",
        "              begin",
        "                bt_all = e.backtrace",
        "              rescue StandardError",
        "                bt_all = nil",
        "              end",
        "              if bt_all && bt_all.respond_to?(:each)",
        "                bt_all.each { |row| f.puts(row) }",
        "              else",
        "                f.puts(\"(no exception backtrace; caller fallback)\")",
        "                caller(0, 400).each { |row| f.puts(row) }",
        "              end",
        "              f.puts(\"\")",
        "            end",
        "          end",
        "        rescue StandardError",
        "        end",
        "      end",
        "      backtrace_text = \"\"",
        "      if e.is_a?(SyntaxError)",
        "        script.each_line do |line|",
        "          line.gsub!(/\\s+$/, \"\")",
        "          if line[/^\\s*\\(/]",
        "            message += \"\\r\\n***La linea '#{line}' no deberia comenzar con '('.\"",
        "            message += \"Intenta poner el '(' al final de la linea anterior en su\"",
        "            message += \" lugar, o utiliza 'extendtext.exe'.\"",
        "          end",
        "        end",
        "      else",
        "        backtrace_text += \"\\r\\n\"",
        "        backtrace_text += \"Rastro de la traza:\"",
        "        bt = nil",
        "        begin",
        "          bt = e.backtrace",
        "        rescue StandardError",
        "          bt = nil",
        "        end",
        "        if bt && bt.respond_to?(:[])",
        "          begin",
        "            rows = bt[0, 50]",
        "            rows.each { |i| backtrace_text += \"\\r\\n#{i}\" } if rows && rows.respond_to?(:each)",
        "          rescue StandardError",
        "          end",
        "        end",
        "        if backtrace_text == \"\\r\\nRastro de la traza:\"",
        "          begin",
            "            caller(0, 50).each { |i| backtrace_text += \"\\r\\n#{i}\" }",
        "          rescue StandardError",
        "          end",
        "        end",
        "        backtrace_text.gsub!(/Section(\\d+)/) { $RGSS_SCRIPTS[$1.to_i][1] } rescue nil",
        "        backtrace_text += \"\\r\\n\"",
        "      end",
        "      err = \"Error de Script en el Interprete\\r\\n\"",
        "      if $game_map",
        "        map_name = ($game_map.name rescue nil) || \"???\"",
        "        if event",
        "          err = \"Error de script en el evento #{event.id} (coordenadas #{event.x},#{event.y}), en el mapa #{$game_map.map_id} (#{map_name})\\r\\n\"",
        "        else",
        "          err = \"Error de script en el Evento Comun, en el mapa #{$game_map.map_id} (#{map_name})\\r\\n\"",
        "        end",
        "      end",
        "      err += \"Excepcion: #{e.class}\\r\\n\"",
        "      err += \"Mensaje: #{message}\\r\\n\\r\\n\"",
        "      err += \"***Script completo:\\r\\n#{script}\"",
        "      err += backtrace_text",
        "      raise EventScriptError.new(err)",
        "    ensure",
        "      if custom_item_vowe_lock_key && $game_temp",
        "        begin",
        "          lock_map = $game_temp.instance_variable_get(:@custom_item_patch_vowe_script_lock)",
        "          lock_map.delete(custom_item_vowe_lock_key) if lock_map && lock_map.respond_to?(:delete)",
        "        rescue StandardError",
        "        end",
        "      end",
        "    end",
        "  end",
        "end",
        "",
    ]


def _build_system_stackerror_trace_lines() -> list[str]:
    # NOTE:
    # TracePoint(:raise) is not reliable across all RGSS runtimes used by
    # fan games; keep this section empty and use deterministic in-rescue
    # logging in Interpreter#execute_script instead.
    return []


def _build_vowe_spawn_battle_reentry_guard_lines() -> list[str]:
    return [
        "# --- runtime compatibility: VOE spawned-battle re-entry guard ---",
        "module CustomItemPatch",
        "  def self.install_vowe_spawn_battle_guard",
        "    has_source = Object.private_method_defined?(:pbSingleOrDoubleWildBattle) || Object.method_defined?(:pbSingleOrDoubleWildBattle)",
        "    return false if !has_source",
        "    already_patched = Object.private_method_defined?(:custom_item_patch_vowe_pbSingleOrDoubleWildBattle_old) ||",
        "      Object.method_defined?(:custom_item_patch_vowe_pbSingleOrDoubleWildBattle_old)",
        "    return true if already_patched",
        "    Object.class_eval do",
        "      alias custom_item_patch_vowe_pbSingleOrDoubleWildBattle_old pbSingleOrDoubleWildBattle",
        "      def pbSingleOrDoubleWildBattle(*args)",
        "        if $game_temp",
        "          lock = $game_temp.instance_variable_get(:@custom_item_patch_vowe_battle_lock)",
        "          return false if lock",
        "          $game_temp.instance_variable_set(:@custom_item_patch_vowe_battle_lock, true)",
        "        end",
        "        begin",
        "          return custom_item_patch_vowe_pbSingleOrDoubleWildBattle_old(*args)",
        "        ensure",
        "          $game_temp.instance_variable_set(:@custom_item_patch_vowe_battle_lock, false) if $game_temp",
        "        end",
        "      end",
        "      private :pbSingleOrDoubleWildBattle rescue nil",
        "      private :custom_item_patch_vowe_pbSingleOrDoubleWildBattle_old rescue nil",
        "    end",
        "    return true",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch error (VOE guard): #{e}\") if defined?(echoln)",
        "    return false",
        "  end",
        "end",
        "",
        "CustomItemPatch.install_vowe_spawn_battle_guard",
        "",
        "if defined?(PluginManager)",
        "  module PluginManager",
        "    class << self",
        "      unless method_defined?(:custom_item_patch_runPlugins_old)",
        "        alias custom_item_patch_runPlugins_old runPlugins",
        "      end",
        "      def runPlugins(*args)",
        "        ret = custom_item_patch_runPlugins_old(*args)",
        "        CustomItemPatch.install_vowe_spawn_battle_guard",
        "        return ret",
        "      end",
        "    end",
        "  end",
        "end",
        "",
        "if defined?(EventHandlers)",
        "  EventHandlers.add(:on_enter_map, :custom_item_patch_install_vowe_guard, proc { |_old_map_id|",
        "    CustomItemPatch.install_vowe_spawn_battle_guard",
        "  })",
        "end",
        "",
    ]


def _build_item_sprite_fallback_guard_lines() -> list[str]:
    return [
        "# --- runtime compatibility: missing item icon fallback guard ---",
        "module GameData",
        "  class Item",
        "    class << self",
        "      def custom_item_patch_parallel_icon_base(item)",
        "        return nil if item.nil?",
        "        raw = item.to_s",
        "        raw = raw[1..-1] if raw.start_with?(\":\")",
        "        item_id = raw.to_s.strip.upcase",
        "        return nil if item_id.empty?",
        "        base = File.join(Dir.pwd, \"tools\", \"custom_item\", \"assets\", \"items\", item_id)",
        "        return base if File.file?(base + \".png\")",
        "        return nil",
        "      rescue StandardError",
        "        return nil",
        "      end",
        "",
        "      unless method_defined?(:custom_item_patch_held_icon_filename_old)",
        "        alias custom_item_patch_held_icon_filename_old held_icon_filename",
        "      end",
        "      def held_icon_filename(item)",
        "        ret = custom_item_patch_held_icon_filename_old(item)",
        "        return ret if ret && !ret.empty?",
        "        custom_ret = custom_item_patch_parallel_icon_base(item)",
        "        return custom_ret if custom_ret && !custom_ret.empty?",
        "        return \"Graphics/UI/Party/icon_item\"",
        "      rescue StandardError",
        "        return \"Graphics/UI/Party/icon_item\"",
        "      end",
        "",
        "      unless method_defined?(:custom_item_patch_icon_filename_old)",
        "        alias custom_item_patch_icon_filename_old icon_filename",
        "      end",
        "      def icon_filename(item)",
        "        ret = custom_item_patch_icon_filename_old(item)",
        "        return ret if ret && !ret.empty?",
        "        custom_ret = custom_item_patch_parallel_icon_base(item)",
        "        return custom_ret if custom_ret && !custom_ret.empty?",
        "        return \"Graphics/Items/000\"",
        "      rescue StandardError",
        "        return \"Graphics/Items/000\"",
        "      end",
        "    end",
        "  end",
        "end",
        "",
    ]


def _ruby_symbol_name(value: str) -> str:
    text = _normalize_item_id(value)
    if not text:
        return ":UNKNOWN"
    return f":{text}"


def _ruby_string(value: Any) -> str:
    text = str(value if value is not None else "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n") + '"'


def _ruby_literal(value: Any, *, symbol_keys: bool = True) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, str):
        return _ruby_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_ruby_literal(v, symbol_keys=symbol_keys) for v in value) + "]"
    if isinstance(value, dict):
        rows: list[str] = []
        for key in sorted(value.keys(), key=lambda x: str(x)):
            raw_key = str(key)
            if symbol_keys and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw_key):
                key_text = f":{raw_key}"
            else:
                key_text = _ruby_string(raw_key)
            rows.append(f"{key_text} => {_ruby_literal(value[key], symbol_keys=symbol_keys)}")
        return "{" + ", ".join(rows) + "}"
    return _ruby_string(value)


def _runtime_item_spec(spec: dict[str, Any]) -> dict[str, Any]:
    item_id = _normalize_item_id(spec.get("id", ""))
    flags = _parse_flags(spec.get("flags", []))
    field_use = _coerce_int(spec.get("field_use", 0), default=0, min_value=0, max_value=5)
    important = ("KeyItem" in flags) or (field_use in {3, 4})
    consumable_default = not important
    return {
        "id": item_id,
        "name": str(spec.get("name", item_id) or item_id),
        "name_plural": str(spec.get("name_plural", spec.get("name", item_id)) or item_id),
        "pocket": _coerce_int(spec.get("pocket", 1), default=1, min_value=1, max_value=8),
        "price": _coerce_int(spec.get("price", 0), default=0, min_value=0, max_value=9999999),
        "sell_price": _coerce_int(spec.get("sell_price", 0), default=0, min_value=0, max_value=9999999),
        "bp_price": _coerce_int(spec.get("bp_price", 1), default=1, min_value=0, max_value=9999),
        "field_use": field_use,
        "battle_use": _coerce_int(spec.get("battle_use", 0), default=0, min_value=0, max_value=5),
        "flags": flags,
        "move_id": _normalize_item_id(spec.get("move_id", "")),
        "description": str(spec.get("description", "") or ""),
        "consumable": _coerce_bool(spec.get("consumable", consumable_default), default=consumable_default),
        "show_quantity": _coerce_bool(spec.get("show_quantity", consumable_default), default=consumable_default),
    }


def _build_custom_runtime_data(root: Path, manifest_items: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data: dict[str, Any] = {
        "version": 1,
        "bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
        "updated_at_utc": _now_utc_iso(),
        "items": {},
    }
    summary_rows: list[dict[str, Any]] = []
    bucket_cache: dict[str, dict[str, list[str]]] = {}

    for item_id in sorted(manifest_items.keys()):
        entry = manifest_items.get(item_id, {})
        if not isinstance(entry, dict):
            continue
        target_item_id = _normalize_item_id(item_id)
        if not target_item_id:
            continue
        spec = entry.get("item_spec", {})
        if not isinstance(spec, dict):
            spec = {}
        effect = entry.get("effect_spec", {})
        if not isinstance(effect, dict):
            effect = {}

        source_item_ids: list[str] = []
        raw_sources = effect.get("resolved_source_item_ids", [])
        if isinstance(raw_sources, list):
            source_item_ids.extend(_normalize_item_id(x) for x in raw_sources)
        fallback_source = _normalize_item_id(effect.get("source_item_id", ""))
        if fallback_source:
            source_item_ids.append(fallback_source)
        source_item_ids = [x for x in _dedupe_ids(source_item_ids) if x and x != target_item_id]

        clone_sources: list[dict[str, Any]] = []
        layer_rows: list[dict[str, Any]] = []
        warnings: list[str] = []
        for source_item_id in source_item_ids:
            buckets = bucket_cache.get(source_item_id)
            if buckets is None:
                buckets = _scan_item_effect_buckets(root, source_item_id)
                bucket_cache[source_item_id] = buckets
            item_handler_buckets = list(buckets.get("item_handlers", []))
            battle_buckets = list(buckets.get("battle_item_effects", []))
            clone_sources.append(
                {
                    "source_item_id": source_item_id,
                    "item_handler_buckets": item_handler_buckets,
                    "battle_item_effect_buckets": battle_buckets,
                }
            )
            row: dict[str, Any] = {
                "source_item_id": source_item_id,
                "copied_item_handler_buckets": item_handler_buckets,
                "copied_battle_item_effect_buckets": battle_buckets,
            }
            if not item_handler_buckets and not battle_buckets:
                warning = f"No transferable buckets found for source item: {source_item_id}"
                row["warning"] = warning
                warnings.append(warning)
            layer_rows.append(row)

        ability_bridge_ids: list[str] = []
        move_bridge_ids: list[str] = []
        template_rows: list[dict[str, Any]] = []
        templates = effect.get("resolved_templates", [])
        if not isinstance(templates, list):
            templates = []
        for raw_template in templates:
            if not isinstance(raw_template, dict):
                continue
            template_key = str(raw_template.get("template_key", "")).strip()
            source_kind = str(raw_template.get("source_kind", "")).strip().lower()
            source_id = _normalize_item_id(raw_template.get("source_id", ""))
            row: dict[str, Any] = {
                "template_key": template_key,
                "source_kind": source_kind,
                "source_id": source_id,
            }
            if template_key in {"ability_sheer_force", ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY}:
                bridged = source_id or ("SHEERFORCE" if template_key == "ability_sheer_force" else "")
                if bridged:
                    ability_bridge_ids.append(bridged)
                    row["status"] = "runtime_data"
                    row["bridged_ability_id"] = bridged
                else:
                    row["status"] = "unsupported"
                    row["warning"] = "Ability runtime bridge requires source ability ID."
                    warnings.append(str(row["warning"]))
            elif template_key == MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY:
                if source_id:
                    move_bridge_ids.append(source_id)
                    row["status"] = "runtime_data"
                    row["bridged_move_id"] = source_id
                else:
                    row["status"] = "unsupported"
                    row["warning"] = "Move runtime bridge requires source move ID."
                    warnings.append(str(row["warning"]))
            elif template_key in {"ability_contrary", "drain_damage_half", "drain_damage_three_quarters"}:
                row["status"] = "legacy_template_deferred"
                row["warning"] = f"Legacy template {template_key} is not part of fixed bridge v{FIXED_RUNTIME_BRIDGE_VERSION}; prefer normalized pool effects."
                warnings.append(str(row["warning"]))
            else:
                row["status"] = "unsupported"
                row["warning"] = f"Unsupported runtime template: {template_key}"
                warnings.append(str(row["warning"]))
            template_rows.append(row)

        pool_effects: list[dict[str, Any]] = []
        pool_seen: set[tuple[Any, ...]] = set()
        raw_pool_effects = effect.get("resolved_pool_effects", [])
        if isinstance(raw_pool_effects, list):
            for pe in raw_pool_effects:
                if not isinstance(pe, dict):
                    continue
                pe_template = str(pe.get("template", ""))
                pe_support = str(pe.get("support_status", "supported"))
                pe_id = str(pe.get("id", "UNKNOWN"))
                row = {
                    "template_key": f"pool:{pe_template}",
                    "source_kind": str(pe.get("source_kind", "")),
                    "source_id": _normalize_item_id(pe.get("source_id", "")),
                    "pool_effect_id": pe_id,
                    "pool_hook": str(pe.get("hook", "")),
                    "support_status": pe_support,
                    "risk_level": str(pe.get("risk_level", "low")),
                }
                if pe_template == "sheer_force_modifier":
                    ability_bridge_ids.append("SHEERFORCE")
                    row["status"] = "runtime_data"
                    row["resolved_as"] = "ability_active_bridge"
                elif pe_support == "unsupported":
                    row["status"] = "unsupported"
                    row["warning"] = f"Pool effect unsupported: {pe_id}"
                    warnings.append(str(row["warning"]))
                elif pe_support == "advanced":
                    row["status"] = "advanced_deferred"
                    row["warning"] = f"Pool effect advanced/not auto-compiled: {pe_id}"
                    warnings.append(str(row["warning"]))
                else:
                    params = pe.get("params", {}) if isinstance(pe.get("params"), dict) else {}
                    dedupe_key: tuple[Any, ...]
                    if pe_template == "heal_percent_damage_dealt":
                        dedupe_key = (str(pe.get("hook", "")), pe_template, int(params.get("percent", 75)))
                    elif pe_template == "raise_user_stat_stage":
                        stats_raw = params.get("stats")
                        if isinstance(stats_raw, str):
                            stats_key = (stats_raw.upper(),)
                        elif isinstance(stats_raw, list) and stats_raw:
                            stats_key = tuple(str(x).upper() for x in stats_raw)
                        else:
                            stats_key = (str(params.get("stat", "")).upper(),)
                        direction_key = str(params.get("direction", "raise")).strip().lower()
                        dedupe_key = (
                            str(pe.get("hook", "")),
                            pe_template,
                            stats_key,
                            int(params.get("stages", 1)),
                            bool(params.get("once_per_battle", True)),
                            direction_key,
                        )
                    elif pe_template == "drain_heal_multiplier":
                        dedupe_key = (str(pe.get("hook", "")), pe_template, float(params.get("multiplier", 1.0)))
                    elif pe_template == "flinch_target":
                        dedupe_key = (str(pe.get("hook", "")), pe_template, int(params.get("chance_percent", 100)))
                    elif pe_template == "damage_multiplier_conditional":
                        dedupe_key = (
                            str(pe.get("hook", "")),
                            pe_template,
                            float(params.get("multiplier", 1.0)),
                            bool(params.get("require_super_effective", False)),
                            str(params.get("require_move_type", "")).upper(),
                        )
                    else:
                        dedupe_key = (
                            str(pe.get("hook", "")),
                            pe_template,
                            json.dumps(params, sort_keys=True, ensure_ascii=False, default=str),
                        )
                    if dedupe_key in pool_seen:
                        row["status"] = "runtime_data_deduped"
                        template_rows.append(row)
                        continue
                    pool_seen.add(dedupe_key)
                    pool_effects.append({
                        "id": pe_id,
                        "hook": str(pe.get("hook", "")),
                        "template": pe_template,
                        "params": params,
                    })
                    row["status"] = "runtime_data"
                template_rows.append(row)

        data["items"][target_item_id] = {
            "item_spec": _runtime_item_spec({**spec, "id": target_item_id}),
            "clone_sources": clone_sources,
            "pool_effects": pool_effects,
            "ability_bridge_ids": _dedupe_ids(ability_bridge_ids),
            "move_bridge_ids": _dedupe_ids(move_bridge_ids),
        }

        summary_entry: dict[str, Any] = {
            "item_id": target_item_id,
            "source_item_ids": source_item_ids,
            "layers": layer_rows,
            "templates": template_rows,
        }
        deduped_warnings: list[str] = []
        seen_warnings: set[str] = set()
        for warning in warnings:
            text = str(warning or "").strip()
            if not text or text in seen_warnings:
                continue
            seen_warnings.add(text)
            deduped_warnings.append(text)
        if deduped_warnings:
            summary_entry["warning"] = " | ".join(deduped_warnings)
        summary_rows.append(summary_entry)

    return data, summary_rows


def _write_custom_runtime_data(root: Path, manifest_items: dict[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    data, summary_rows = _build_custom_runtime_data(root, manifest_items)
    path = runtime_data_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    source = [
        "# Auto-generated by Pokemon Indigo Save Editor CustomItem module.",
        "# Parallel runtime data only; do not edit by hand while the editor is open.",
        _ruby_literal(data),
        "",
    ]
    path.write_text("\n".join(source), encoding="utf-8")
    return path, summary_rows


def _build_fixed_runtime_bridge_source() -> str:
    lines = [
        "# Auto-generated by Pokemon Indigo Save Editor CustomItem module.",
        "# Fixed runtime bridge: reads parallel custom-item data at runtime.",
        f"# Bridge version: {FIXED_RUNTIME_BRIDGE_VERSION}",
        "",
    ]
    lines.extend(_build_system_stackerror_trace_lines())
    lines.extend(_build_interpreter_nil_backtrace_guard_lines())
    lines.extend(_build_vowe_spawn_battle_reentry_guard_lines())
    lines.extend(_build_item_activity_helper_lines())
    lines.extend([
        "# --- fixed runtime bridge: parallel custom item data reader ---",
        "module CustomItemPatch",
        f"  FIXED_RUNTIME_BRIDGE_VERSION = {FIXED_RUNTIME_BRIDGE_VERSION}",
        "  def self.runtime_data_path",
        "    return File.join(Dir.pwd, \"tools\", \"custom_item\", \"data\", \"custom_item_runtime.rb\")",
        "  end",
        "",
        "  def self.runtime_data",
        "    path = runtime_data_path",
        "    return {} if !File.file?(path)",
        "    mtime = File.mtime(path) rescue nil",
        "    if @custom_item_runtime_data && @custom_item_runtime_mtime == mtime",
        "      return @custom_item_runtime_data",
        "    end",
        "    data = eval(File.read(path), TOPLEVEL_BINDING, path)",
        "    data = {} if !data.is_a?(Hash)",
        "    @custom_item_runtime_data = data",
        "    @custom_item_runtime_mtime = mtime",
        "    @custom_item_runtime_item_cache = {}",
        "    return data",
        "  rescue Exception => e",
        "    echoln(\"CustomItemPatch runtime data error: #{e}\") if defined?(echoln)",
        "    @custom_item_runtime_data = {}",
        "    return {}",
        "  end",
        "",
        "  def self.runtime_items",
        "    data = runtime_data",
        "    items = data[:items] || data[\"items\"]",
        "    return items.is_a?(Hash) ? items : {}",
        "  end",
        "",
        "  def self.symbol_id(raw)",
        "    return nil if raw.nil?",
        "    raw = raw.id if raw.respond_to?(:id)",
        "    return raw if raw.is_a?(Symbol)",
        "    text = raw.to_s",
        "    text = text[1..-1] if text.start_with?(\":\")",
        "    text = text.strip.upcase",
        "    return nil if text.empty?",
        "    return text.to_sym",
        "  rescue StandardError",
        "    return nil",
        "  end",
        "",
        "  def self.runtime_item_entry(item)",
        "    item_id = symbol_id(item)",
        "    return nil if !item_id",
        "    return runtime_items[item_id] || runtime_items[item_id.to_s]",
        "  end",
        "",
        "  def self.runtime_item_entry_for_battler(battler)",
        "    return nil if !battler",
        "    raw = nil",
        "    raw = battler.item_id if battler.respond_to?(:item_id)",
        "    raw = battler.item if !raw && battler.respond_to?(:item)",
        "    return runtime_item_entry(raw)",
        "  rescue StandardError",
        "    return nil",
        "  end",
        "",
        "  def self.runtime_item_spec(item)",
        "    entry = runtime_item_entry(item)",
        "    return nil if !entry.is_a?(Hash)",
        "    spec = entry[:item_spec] || entry[\"item_spec\"]",
        "    return spec.is_a?(Hash) ? spec : nil",
        "  end",
        "",
        "  def self.runtime_item_name_for_battler(battler)",
        "    entry = runtime_item_entry_for_battler(battler)",
        "    spec = entry && (entry[:item_spec] || entry[\"item_spec\"])",
        "    return nil if !spec.is_a?(Hash)",
        "    return spec[:name] || spec[\"name\"]",
        "  end",
        "",
        "  def self.parallel_icon_base(item)",
        "    item_id = symbol_id(item)",
        "    return nil if !item_id",
        "    base = File.join(Dir.pwd, \"tools\", \"custom_item\", \"assets\", \"items\", item_id.to_s)",
        "    return base if File.file?(base + \".png\")",
        "    return nil",
        "  rescue StandardError",
        "    return nil",
        "  end",
        "",
        "  def self.pool_effects(entry, hook = nil, template = nil)",
        "    return [] if !entry.is_a?(Hash)",
        "    effects = entry[:pool_effects] || entry[\"pool_effects\"]",
        "    return [] if !effects.is_a?(Array)",
        "    effects.select do |eff|",
        "      next false if !eff.is_a?(Hash)",
        "      ok = true",
        "      ok &&= ((eff[:hook] || eff[\"hook\"]).to_s == hook.to_s) if hook",
        "      ok &&= ((eff[:template] || eff[\"template\"]).to_s == template.to_s) if template",
        "      ok",
        "    end",
        "  end",
        "",
        "  def self.effect_params(effect)",
        "    return {} if !effect.is_a?(Hash)",
        "    params = effect[:params] || effect[\"params\"]",
        "    return params.is_a?(Hash) ? params : {}",
        "  end",
        "",
        "  def self.stat_sym(value)",
        "    text = value.to_s.upcase",
        "    return :SPECIAL_ATTACK if [\"SPECIAL_ATTACK\", \"SPATK\", \"SP_ATK\"].include?(text)",
        "    return :SPECIAL_DEFENSE if [\"SPECIAL_DEFENSE\", \"SPDEF\", \"SP_DEF\"].include?(text)",
        "    return text.to_sym",
        "  end",
        "",
        "  def self.stat_list(params)",
        "    raw = params[:stats] || params[\"stats\"]",
        "    raw = [raw] if raw && !raw.is_a?(Array)",
        "    raw = [params[:stat] || params[\"stat\"] || \"ATTACK\"] if !raw || raw.empty?",
        "    return raw.map { |x| stat_sym(x) }.compact",
        "  rescue StandardError",
        "    return [:ATTACK]",
        "  end",
        "",
        "  def self.type_sym(value)",
        "    return nil if value.nil? || value.to_s.empty?",
        "    return value.to_s.upcase.to_sym",
        "  end",
        "",
        "  def self.weather_list(raw)",
        "    values = raw.is_a?(Array) ? raw : [raw]",
        "    values.compact.map { |v| v.to_s.to_sym }",
        "  end",
        "",
        "  def self.item_active_for_runtime?(battler)",
        "    return false if !runtime_item_entry_for_battler(battler)",
        "    return custom_item_effect_item_active?(battler)",
        "  end",
        "end",
        "",
        "# --- fixed runtime bridge: GameData::Item parallel lookup ---",
        "module GameData",
        "  class Item",
        "    class << self",
        "      unless method_defined?(:custom_item_patch_try_get_parallel_old)",
        "        alias custom_item_patch_try_get_parallel_old try_get",
        "      end",
        "      def try_get(item)",
        "        ret = custom_item_patch_try_get_parallel_old(item)",
        "        return ret if ret",
        "        item_id = CustomItemPatch.symbol_id(item)",
        "        spec = CustomItemPatch.runtime_item_spec(item_id)",
        "        return nil if !spec",
        "        @custom_item_patch_item_cache ||= {}",
        "        cached = @custom_item_patch_item_cache[item_id]",
        "        return cached if cached",
        "        flags = spec[:flags] || spec[\"flags\"] || []",
        "        flags = [] if !flags.is_a?(Array)",
        "        move_id = spec[:move_id] || spec[\"move_id\"]",
        "        move_sym = CustomItemPatch.symbol_id(move_id)",
        "        attrs = {",
        "          :id => item_id,",
        "          :real_name => (spec[:name] || spec[\"name\"] || item_id.to_s),",
        "          :real_name_plural => (spec[:name_plural] || spec[\"name_plural\"] || spec[:name] || spec[\"name\"] || item_id.to_s),",
        "          :pocket => (spec[:pocket] || spec[\"pocket\"] || 1).to_i,",
        "          :price => (spec[:price] || spec[\"price\"] || 0).to_i,",
        "          :sell_price => (spec[:sell_price] || spec[\"sell_price\"] || 0).to_i,",
        "          :bp_price => (spec[:bp_price] || spec[\"bp_price\"] || 1).to_i,",
        "          :field_use => (spec[:field_use] || spec[\"field_use\"] || 0).to_i,",
        "          :battle_use => (spec[:battle_use] || spec[\"battle_use\"] || 0).to_i,",
        "          :flags => flags,",
        "          :move => move_sym,",
        "          :description => (spec[:description] || spec[\"description\"] || \"\"),",
        "          :consumable => !!(spec.key?(:consumable) ? spec[:consumable] : spec[\"consumable\"]),",
        "          :show_quantity => !!(spec.key?(:show_quantity) ? spec[:show_quantity] : spec[\"show_quantity\"])",
        "        }",
        "        obj = GameData::Item.new(attrs)",
        "        @custom_item_patch_item_cache[item_id] = obj",
        "        return obj",
        "      rescue StandardError => e",
        "        echoln(\"CustomItemPatch GameData::Item.try_get: #{e}\") if defined?(echoln)",
        "        return nil",
        "      end",
        "",
        "      unless method_defined?(:custom_item_patch_held_icon_filename_old)",
        "        alias custom_item_patch_held_icon_filename_old held_icon_filename",
        "      end",
        "      def held_icon_filename(item)",
        "        custom_ret = CustomItemPatch.parallel_icon_base(item)",
        "        return custom_ret if custom_ret && !custom_ret.empty?",
        "        ret = custom_item_patch_held_icon_filename_old(item)",
        "        return ret if ret && !ret.empty?",
        "        return \"Graphics/UI/Party/icon_item\"",
        "      rescue StandardError",
        "        return \"Graphics/UI/Party/icon_item\"",
        "      end",
        "",
        "      unless method_defined?(:custom_item_patch_icon_filename_old)",
        "        alias custom_item_patch_icon_filename_old icon_filename",
        "      end",
        "      def icon_filename(item)",
        "        custom_ret = CustomItemPatch.parallel_icon_base(item)",
        "        return custom_ret if custom_ret && !custom_ret.empty?",
        "        ret = custom_item_patch_icon_filename_old(item)",
        "        return ret if ret && !ret.empty?",
        "        return \"Graphics/Items/000\"",
        "      rescue StandardError",
        "        return \"Graphics/Items/000\"",
        "      end",
        "    end",
        "  end",
        "end",
        "",
        "# --- fixed runtime bridge: ability/move bridge helpers ---",
        "module CustomItemPatch",
        "  def self.ability_active_bridge_item?(battler, ability_id)",
        "    return false if !item_active_for_runtime?(battler)",
        "    entry = runtime_item_entry_for_battler(battler)",
        "    ids = entry[:ability_bridge_ids] || entry[\"ability_bridge_ids\"] || []",
        "    abil = symbol_id(ability_id)",
        "    return false if !abil || !ids.is_a?(Array)",
        "    ids.any? { |x| symbol_id(x) == abil }",
        "  end",
        "",
        "  def self.ability_active_bridge_ability_ids_for(battler, ignore_fainted = false)",
        "    return [] if !custom_item_effect_item_active?(battler, ignore_fainted)",
        "    entry = runtime_item_entry_for_battler(battler)",
        "    return [] if !entry",
        "    ids = entry[:ability_bridge_ids] || entry[\"ability_bridge_ids\"] || []",
        "    return [] if !ids.is_a?(Array)",
        "    ids.map { |x| symbol_id(x) }.compact",
        "  end",
        "",
        "  def self.move_additional_effect_bridge_move_ids_for(battler)",
        "    return [] if !item_active_for_runtime?(battler)",
        "    entry = runtime_item_entry_for_battler(battler)",
        "    ids = entry[:move_bridge_ids] || entry[\"move_bridge_ids\"] || []",
        "    return [] if !ids.is_a?(Array)",
        "    ids.map { |x| symbol_id(x) }.compact",
        "  end",
        "end",
        "",
        "class Battle::Battler",
        "  unless method_defined?(:custom_item_patch_hasActiveAbility_bridge_old)",
        "    alias custom_item_patch_hasActiveAbility_bridge_old hasActiveAbility?",
        "  end",
        "  def hasActiveAbility?(check_ability, ignore_fainted = false)",
        "    ret = custom_item_patch_hasActiveAbility_bridge_old(check_ability, ignore_fainted)",
        "    return true if ret",
        "    checks = check_ability.is_a?(Array) ? check_ability : [check_ability]",
        "    checks.each do |entry|",
        "      next if !entry",
        "      return true if CustomItemPatch.ability_active_bridge_item?(self, entry)",
        "    end",
        "    return false",
        "  end",
        "",
        "  unless method_defined?(:custom_item_patch_pbProcessMoveHit_old)",
        "    alias custom_item_patch_pbProcessMoveHit_old pbProcessMoveHit",
        "  end",
        "  def pbProcessMoveHit(move, user, targets, hitNum, skipAccuracyCheck)",
        "    custom_item_patch_pbProcessMoveHit_old(move, user, targets, hitNum, skipAccuracyCheck)",
        "    return if !user || user.fainted?",
        "    return if user != self",
        "    return if user.hasActiveAbility?(:SHEERFORCE)",
        "    source_move_ids = CustomItemPatch.move_additional_effect_bridge_move_ids_for(user)",
        "    return if source_move_ids.empty?",
        "    target_list = targets.is_a?(Array) ? targets : []",
        "    source_move_ids.each do |source_move_id|",
        "      source_move = nil",
        "      begin",
        "        source_move = Battle::Move.from_pokemon_move(@battle, Pokemon::Move.new(source_move_id))",
        "      rescue StandardError",
        "        source_move = nil",
        "      end",
        "      next if !source_move",
        "      target_list.each do |target|",
        "        next if !target || target.fainted?",
        "        next if !target.damageState || target.damageState.calcDamage == 0",
        "        chance = source_move.pbAdditionalEffectChance(user, target)",
        "        next if chance <= 0",
        "        source_move.pbAdditionalEffect(user, target) if @battle.pbRandom(100) < chance",
        "      end",
        "    end",
        "  end",
        "end",
        "",
        "module Battle::AbilityEffects",
        "  class << self",
        "    unless method_defined?(:custom_item_patch_triggerEndOfRoundHealing_bridge_old)",
        "      alias custom_item_patch_triggerEndOfRoundHealing_bridge_old triggerEndOfRoundHealing",
        "    end",
        "    def triggerEndOfRoundHealing(ability, battler, battle)",
        "      base_ret = custom_item_patch_triggerEndOfRoundHealing_bridge_old(ability, battler, battle)",
        "      bridge_ids = CustomItemPatch.ability_active_bridge_ability_ids_for(battler)",
        "      return base_ret if !bridge_ids || bridge_ids.empty?",
        "      current_ability = CustomItemPatch.symbol_id(ability)",
        "      bridge_ids.each do |bridge_ability_id|",
        "        next if !bridge_ability_id",
        "        next if current_ability && bridge_ability_id == current_ability",
        "        custom_item_patch_triggerEndOfRoundHealing_bridge_old(bridge_ability_id, battler, battle)",
        "      end",
        "      return base_ret",
        "    end",
        "  end",
        "end",
        "",
        "# --- fixed runtime bridge: generic item-effect registration ---",
        "module CustomItemPatch",
        "  def self.register_clone_sources(item_id, entry)",
        "    sources = entry[:clone_sources] || entry[\"clone_sources\"] || []",
        "    return if !sources.is_a?(Array)",
        "    sources.each do |row|",
        "      next if !row.is_a?(Hash)",
        "      source_id = symbol_id(row[:source_item_id] || row[\"source_item_id\"])",
        "      next if !source_id",
        "      battles = row[:battle_item_effect_buckets] || row[\"battle_item_effect_buckets\"] || []",
        "      battles.each do |bucket|",
        "        begin",
        "          Battle::ItemEffects.const_get(bucket.to_s).copy(source_id, item_id)",
        "        rescue StandardError",
        "        end",
        "      end",
        "      handlers = row[:item_handler_buckets] || row[\"item_handler_buckets\"] || []",
        "      handlers.each do |bucket|",
        "        begin",
        "          ItemHandlers.const_get(bucket.to_s).copy(source_id, item_id)",
        "        rescue StandardError",
        "        end",
        "      end",
        "    end",
        "  end",
        "",
        "  def self.install_runtime_item_effects",
        "    items = runtime_items",
        "    return if !items || items.empty?",
        "    items.each do |raw_item_id, entry|",
        "      item_id = symbol_id(raw_item_id)",
        "      next if !item_id || !entry.is_a?(Hash)",
        "      register_clone_sources(item_id, entry)",
        "      register_end_of_round_healing(item_id)",
        "      register_after_move_use(item_id)",
        "      register_end_of_round_effect(item_id)",
        "      register_damage_calc_from_user(item_id)",
        "      register_speed_calc(item_id)",
        "    end",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch install runtime effects: #{e}\") if defined?(echoln)",
        "  end",
        "",
        "  def self.register_end_of_round_healing(item_id)",
        "    return if !defined?(Battle::ItemEffects::EndOfRoundHealing)",
        "    Battle::ItemEffects::EndOfRoundHealing.add(item_id, proc { |item, battler, battle|",
        "      next unless CustomItemPatch.item_active_for_runtime?(battler)",
        "      entry = CustomItemPatch.runtime_item_entry_for_battler(battler)",
        "      CustomItemPatch.pool_effects(entry, \"end_of_round\").each do |effect|",
        "        params = CustomItemPatch.effect_params(effect)",
        "        template = (effect[:template] || effect[\"template\"]).to_s",
        "        if template == \"heal_fraction_max_hp\"",
        "          next unless battler.canHeal?",
        "          num = (params[:fraction_numerator] || params[\"fraction_numerator\"] || 1).to_i",
        "          den = [(params[:fraction_denominator] || params[\"fraction_denominator\"] || 16).to_i, 1].max",
        "          hp = [(battler.totalhp.to_f * num / den).ceil, 1].max",
        "          battler.pbRecoverHP(hp)",
        "          battle.pbDisplay(_INTL(\"{1}'s {2} restored its HP!\", battler.pbThis, battler.itemName))",
        "        end",
        "      end",
        "    })",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch EndOfRoundHealing #{item_id}: #{e}\") if defined?(echoln)",
        "  end",
        "",
        "  def self.register_after_move_use(item_id)",
        "    return if !defined?(Battle::ItemEffects::AfterMoveUseFromUser)",
        "    Battle::ItemEffects::AfterMoveUseFromUser.add(item_id, proc { |item, user, targets, move, numHits, battle|",
        "      next unless CustomItemPatch.item_active_for_runtime?(user)",
        "      targets = [] if !targets",
        "      entry = CustomItemPatch.runtime_item_entry_for_battler(user)",
        "      effects = CustomItemPatch.pool_effects(entry).select { |eff| [\"after_damage_dealt\", \"after_move_use\"].include?((eff[:hook] || eff[\"hook\"]).to_s) }",
        "      drain_mult = 1.0",
        "      effects.each do |effect|",
        "        template = (effect[:template] || effect[\"template\"]).to_s",
        "        params = CustomItemPatch.effect_params(effect)",
        "        drain_mult *= (params[:multiplier] || params[\"multiplier\"] || 1.0).to_f if template == \"drain_heal_multiplier\"",
        "      end",
        "      effects.each do |effect|",
        "        template = (effect[:template] || effect[\"template\"]).to_s",
        "        params = CustomItemPatch.effect_params(effect)",
        "        effect_id = (effect[:id] || effect[\"id\"] || template).to_s.downcase.gsub(/[^a-z0-9_]/, \"_\")",
        "        if template == \"heal_percent_damage_dealt\"",
        "          next unless user.canHeal?",
        "          ratio = ((params[:percent] || params[\"percent\"] || 75).to_f / 100.0) * drain_mult",
        "          targets.each do |target|",
        "            next if !target || !target.damageState",
        "            hp_lost = target.damageState.totalHPLost",
        "            next if hp_lost <= 0",
        "            hp_gain = (hp_lost * ratio).round",
        "            next if hp_gain <= 0",
        "            item_name = CustomItemPatch.runtime_item_name_for_battler(user) || user.itemName",
        "            user.pbRecoverHPFromDrain(hp_gain, target, _INTL(\"{1} regained HP with {2}!\", user.pbThis, item_name))",
        "          end",
        "        elsif template == \"raise_user_stat_stage\"",
        "          stats = CustomItemPatch.stat_list(params)",
        "          stages = [(params[:stages] || params[\"stages\"] || 1).to_i, 1].max",
        "          direction = (params[:direction] || params[\"direction\"] || \"raise\").to_s.downcase",
        "          once = params.key?(:once_per_battle) ? params[:once_per_battle] : params[\"once_per_battle\"]",
        "          once = true if once.nil?",
        "          tracker = (\"@custom_item_pool_once_\" + effect_id).to_sym",
        "          next if once && user.instance_variable_defined?(tracker) && user.instance_variable_get(tracker)",
        "          any_raised = false",
        "          item_name = CustomItemPatch.runtime_item_name_for_battler(user) || user.itemName",
        "          stats.each do |stat|",
        "            if direction == \"lower\"",
        "              next unless user.pbCanLowerStatStage?(stat, user)",
        "              user.pbLowerStatStageByCause(stat, stages, user, item_name) rescue user.pbLowerStatStage(stat, stages, user)",
        "              any_raised = true",
        "            else",
        "              next unless user.pbCanRaiseStatStage?(stat, user)",
        "              user.pbRaiseStatStageByCause(stat, stages, user, item_name) rescue user.pbRaiseStatStage(stat, stages, user)",
        "              any_raised = true",
        "            end",
        "          end",
        "          user.instance_variable_set(tracker, true) if once && any_raised",
        "        elsif template == \"flinch_target\"",
        "          chance = [(params[:chance_percent] || params[\"chance_percent\"] || 100).to_i, 100].min",
        "          targets.each do |target|",
        "            next if !target || target.fainted?",
        "            next if battle.pbRandom(100) >= chance",
        "            begin",
        "              target.pbFlinch(user)",
        "            rescue StandardError",
        "              target.effects[PBEffects::Flinch] = true if defined?(PBEffects) && target.respond_to?(:effects)",
        "            end",
        "          end",
        "        end",
        "      end",
        "    })",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch AfterMoveUse #{item_id}: #{e}\") if defined?(echoln)",
        "  end",
        "",
        "  def self.register_end_of_round_effect(item_id)",
        "    return if !defined?(Battle::ItemEffects::EndOfRoundEffect)",
        "    Battle::ItemEffects::EndOfRoundEffect.add(item_id, proc { |item, battler, battle|",
        "      next unless CustomItemPatch.item_active_for_runtime?(battler)",
        "      entry = CustomItemPatch.runtime_item_entry_for_battler(battler)",
        "      CustomItemPatch.pool_effects(entry, \"end_of_round_effect\").each do |effect|",
        "        params = CustomItemPatch.effect_params(effect)",
        "        template = (effect[:template] || effect[\"template\"]).to_s",
        "        if template == \"raise_user_stat_stage_end_of_round\"",
        "          stats = CustomItemPatch.stat_list(params)",
        "          stages = [(params[:stages] || params[\"stages\"] || 1).to_i, 1].max",
        "          direction = (params[:direction] || params[\"direction\"] || \"raise\").to_s.downcase",
        "          item_name = CustomItemPatch.runtime_item_name_for_battler(battler) || battler.itemName",
        "          stats.each do |stat|",
        "            if direction == \"lower\"",
        "              next unless battler.pbCanLowerStatStage?(stat, battler)",
        "              battler.pbLowerStatStageByCause(stat, stages, battler, item_name) rescue battler.pbLowerStatStage(stat, stages, battler)",
        "            else",
        "              next unless battler.pbCanRaiseStatStage?(stat, battler)",
        "              battler.pbRaiseStatStageByCause(stat, stages, battler, item_name) rescue battler.pbRaiseStatStage(stat, stages, battler)",
        "            end",
        "          end",
        "        end",
        "      end",
        "    })",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch EndOfRoundEffect #{item_id}: #{e}\") if defined?(echoln)",
        "  end",
        "",
        "  def self.register_damage_calc_from_user(item_id)",
        "    return if !defined?(Battle::ItemEffects::DamageCalcFromUser)",
        "    Battle::ItemEffects::DamageCalcFromUser.add(item_id, proc { |item, user, target, move, mults, basePow, type|",
        "      next unless CustomItemPatch.item_active_for_runtime?(user)",
        "      entry = CustomItemPatch.runtime_item_entry_for_battler(user)",
        "      CustomItemPatch.pool_effects(entry, \"damage_calc\").each do |effect|",
        "        params = CustomItemPatch.effect_params(effect)",
        "        template = (effect[:template] || effect[\"template\"]).to_s",
        "        next unless [\"damage_multiplier\", \"damage_multiplier_conditional\"].include?(template)",
        "        multiplier = (params[:multiplier] || params[\"multiplier\"] || 1.0).to_f",
        "        if params[:require_super_effective] || params[\"require_super_effective\"]",
        "          next unless target && target.damageState && target.damageState.typeMod && target.damageState.typeMod > 4",
        "        end",
        "        req_type = CustomItemPatch.type_sym(params[:require_move_type] || params[\"require_move_type\"])",
        "        if req_type",
        "          move_type = type || (move.pbCalcType(user) rescue nil) || (move.type rescue nil)",
        "          move_type = CustomItemPatch.symbol_id(move_type)",
        "          next unless move_type == req_type",
        "        end",
        "        mults[:final_dmg_mult] = (mults[:final_dmg_mult].to_f * multiplier).round(4) if mults.respond_to?(:[]=)",
        "      end",
        "    })",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch DamageCalc #{item_id}: #{e}\") if defined?(echoln)",
        "  end",
        "",
        "  def self.register_speed_calc(item_id)",
        "    return if !defined?(Battle::ItemEffects::SpeedCalc)",
        "    Battle::ItemEffects::SpeedCalc.add(item_id, proc { |item, battler, mult|",
        "      next mult unless CustomItemPatch.item_active_for_runtime?(battler)",
        "      entry = CustomItemPatch.runtime_item_entry_for_battler(battler)",
        "      out = mult",
        "      CustomItemPatch.pool_effects(entry, \"speed_calc\").each do |effect|",
        "        params = CustomItemPatch.effect_params(effect)",
        "        template = (effect[:template] || effect[\"template\"]).to_s",
        "        multiplier = (params[:multiplier] || params[\"multiplier\"] || 1.0).to_f",
        "        if template == \"speed_multiplier_if_weather\"",
        "          weather = nil",
        "          begin",
        "            battle = battler.battle if battler.respond_to?(:battle)",
        "            weather = battle.field.weather if battle && battle.respond_to?(:field) && battle.field.respond_to?(:weather)",
        "          rescue StandardError",
        "            weather = nil",
        "          end",
        "          weathers = CustomItemPatch.weather_list(params[:weather] || params[\"weather\"] || [])",
        "          next unless weather && weathers.include?(weather)",
        "        elsif template != \"speed_multiplier\"",
        "          next",
        "        end",
        "        out = (out.to_f * multiplier).round(4)",
        "      end",
        "      next out",
        "    })",
        "  rescue StandardError => e",
        "    echoln(\"CustomItemPatch SpeedCalc #{item_id}: #{e}\") if defined?(echoln)",
        "  end",
        "end",
        "",
        "CustomItemPatch.install_runtime_item_effects",
        "",
    ])
    return "\n".join(lines)


def _build_custom_script_source(root: Path, manifest_items: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    _runtime_data, summary_rows = _build_custom_runtime_data(root, manifest_items)
    return _build_fixed_runtime_bridge_source(), summary_rows

    lines = [
        "# Auto-generated by Pokemon Indigo Save Editor CustomItem module.",
        "# Do not edit manually; it may be overwritten.",
        "",
    ]
    lines.extend(_build_system_stackerror_trace_lines())
    lines.extend(_build_interpreter_nil_backtrace_guard_lines())
    lines.extend(_build_vowe_spawn_battle_reentry_guard_lines())
    lines.extend(_build_item_sprite_fallback_guard_lines())
    lines.extend(_build_item_activity_helper_lines())
    summary_rows: list[dict[str, Any]] = []
    bucket_cache: dict[str, dict[str, list[str]]] = {}
    contrary_item_ids: list[str] = []
    ability_active_bridge_by_ability: dict[str, list[str]] = {}
    move_additional_effect_bridge_by_move: dict[str, list[str]] = {}
    drain_templates_by_item: dict[str, dict[str, Any]] = {}
    item_pool_effects_for_compiler: dict[str, list[dict[str, Any]]] = {}

    for item_id in sorted(manifest_items.keys()):
        entry = manifest_items.get(item_id, {})
        if not isinstance(entry, dict):
            continue
        effect = entry.get("effect_spec", {})
        if not isinstance(effect, dict):
            continue

        target_item_id = _normalize_item_id(item_id)
        if not target_item_id:
            continue
        source_item_ids: list[str] = []
        raw_sources = effect.get("resolved_source_item_ids", [])
        if isinstance(raw_sources, list):
            for raw_source in raw_sources:
                source_item_id = _normalize_item_id(raw_source)
                if source_item_id and source_item_id not in source_item_ids:
                    source_item_ids.append(source_item_id)
        if not source_item_ids:
            fallback_source_item = _normalize_item_id(effect.get("source_item_id", ""))
            if fallback_source_item:
                source_item_ids.append(fallback_source_item)
        source_item_ids = [source for source in source_item_ids if source != target_item_id]

        raw_templates = effect.get("resolved_templates", [])
        templates = raw_templates if isinstance(raw_templates, list) else []

        mode = str(effect.get("mode", "none")).strip().lower()
        if mode == "none" and not source_item_ids and not templates:
            continue

        unsupported_reason = str(effect.get("unsupported_reason", "")).strip()
        layer_rows: list[dict[str, Any]] = []
        template_rows: list[dict[str, Any]] = []
        warnings: list[str] = [unsupported_reason] if unsupported_reason else []

        for source_item_id in source_item_ids:
            buckets = bucket_cache.get(source_item_id)
            if buckets is None:
                buckets = _scan_item_effect_buckets(root, source_item_id)
                bucket_cache[source_item_id] = buckets

            item_handler_buckets = list(buckets.get("item_handlers", []))
            battle_buckets = list(buckets.get("battle_item_effects", []))
            if not item_handler_buckets and not battle_buckets:
                warning = f"No transferable buckets found for source item: {source_item_id}"
                warnings.append(warning)
                layer_rows.append(
                    {
                        "source_item_id": source_item_id,
                        "copied_item_handler_buckets": [],
                        "copied_battle_item_effect_buckets": [],
                        "warning": warning,
                    }
                )
                continue

            lines.append(f"# --- {target_item_id} <= {source_item_id} ---")
            lines.append("begin")
            for bucket in battle_buckets:
                lines.append(f"  Battle::ItemEffects::{bucket}.copy(:{source_item_id}, :{target_item_id})")
            for bucket in item_handler_buckets:
                lines.append(f"  ItemHandlers::{bucket}.copy(:{source_item_id}, :{target_item_id})")
            lines.append("rescue StandardError => e")
            lines.append('  echoln("CustomItemPatch error: #{e}") if defined?(echoln)')
            lines.append("end")
            lines.append("")
            layer_rows.append(
                {
                    "source_item_id": source_item_id,
                    "copied_item_handler_buckets": item_handler_buckets,
                    "copied_battle_item_effect_buckets": battle_buckets,
                }
            )

        for raw_template in templates:
            if not isinstance(raw_template, dict):
                continue
            template_key = str(raw_template.get("template_key", "")).strip()
            if not template_key:
                continue
            source_kind = str(raw_template.get("source_kind", "")).strip().lower()
            source_id = _normalize_item_id(raw_template.get("source_id", ""))
            row: dict[str, Any] = {
                "template_key": template_key,
                "source_kind": source_kind,
                "source_id": source_id,
            }
            if template_key == "ability_contrary":
                contrary_item_ids.append(target_item_id)
                row["status"] = "applied"
            elif template_key in {"ability_sheer_force", ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY}:
                bridged_ability_id = _normalize_item_id(source_id)
                if not bridged_ability_id and template_key == "ability_sheer_force":
                    bridged_ability_id = "SHEERFORCE"
                if not bridged_ability_id:
                    warning = (
                        "Ability runtime bridge requires source ability ID, "
                        f"but template '{template_key}' has empty source."
                    )
                    warnings.append(warning)
                    row["status"] = "unsupported"
                    row["warning"] = warning
                else:
                    mapped = ability_active_bridge_by_ability.setdefault(bridged_ability_id, [])
                    if target_item_id not in mapped:
                        mapped.append(target_item_id)
                    row["status"] = "applied"
                    row["resolved_template_key"] = ABILITY_ACTIVE_BRIDGE_TEMPLATE_KEY
                    row["bridged_ability_id"] = bridged_ability_id
            elif template_key == MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY:
                bridged_move_id = _normalize_item_id(source_id)
                if not bridged_move_id:
                    warning = (
                        "Move runtime bridge requires source move ID, "
                        f"but template '{template_key}' has empty source."
                    )
                    warnings.append(warning)
                    row["status"] = "unsupported"
                    row["warning"] = warning
                else:
                    mapped = move_additional_effect_bridge_by_move.setdefault(bridged_move_id, [])
                    if target_item_id not in mapped:
                        mapped.append(target_item_id)
                    row["status"] = "applied"
                    row["resolved_template_key"] = MOVE_ADDITIONAL_EFFECT_BRIDGE_TEMPLATE_KEY
                    row["bridged_move_id"] = bridged_move_id
            elif template_key == "drain_damage_half":
                prev = drain_templates_by_item.get(target_item_id)
                heal_ratio = 0.5
                if prev is None or float(prev.get("heal_ratio", 0.0)) < heal_ratio:
                    drain_templates_by_item[target_item_id] = {
                        "template_key": template_key,
                        "source_kind": source_kind,
                        "source_id": source_id,
                        "heal_ratio": heal_ratio,
                    }
                row["status"] = "applied"
                row["heal_ratio"] = heal_ratio
            elif template_key == "drain_damage_three_quarters":
                prev = drain_templates_by_item.get(target_item_id)
                heal_ratio = 0.75
                if prev is None or float(prev.get("heal_ratio", 0.0)) < heal_ratio:
                    drain_templates_by_item[target_item_id] = {
                        "template_key": template_key,
                        "source_kind": source_kind,
                        "source_id": source_id,
                        "heal_ratio": heal_ratio,
                    }
                row["status"] = "applied"
                row["heal_ratio"] = heal_ratio
            else:
                warning = f"Unsupported runtime template: {template_key}"
                warnings.append(warning)
                row["status"] = "unsupported"
                row["warning"] = warning
            template_rows.append(row)

        # --- Pool-based effect processing ---
        pool_effects_raw = effect.get("resolved_pool_effects", [])
        if isinstance(pool_effects_raw, list) and pool_effects_raw:
            compiler_effects: list[dict[str, Any]] = []
            for pe in pool_effects_raw:
                if not isinstance(pe, dict):
                    continue
                pe_template = str(pe.get("template", ""))
                pe_id = str(pe.get("id", "UNKNOWN"))
                pe_hook = str(pe.get("hook", ""))
                pe_support = str(pe.get("support_status", "supported"))
                pe_risk = str(pe.get("risk_level", "low"))
                row: dict[str, Any] = {
                    "template_key": f"pool:{pe_template}",
                    "source_kind": str(pe.get("source_kind", "")),
                    "source_id": _normalize_item_id(pe.get("source_id", "")),
                    "pool_effect_id": pe_id,
                    "pool_hook": pe_hook,
                    "support_status": pe_support,
                    "risk_level": pe_risk,
                }
                if pe_template == "sheer_force_modifier":
                    # Route through ability_active_bridge so all hasActiveAbility?
                    # overrides share a single alias chain.
                    mapped = ability_active_bridge_by_ability.setdefault("SHEERFORCE", [])
                    if target_item_id not in mapped:
                        mapped.append(target_item_id)
                    row["status"] = "applied"
                    row["resolved_as"] = "ability_active_bridge"
                elif pe_support == "unsupported":
                    warning = f"Pool effect unsupported: {pe_id}"
                    warnings.append(warning)
                    row["status"] = "unsupported"
                    row["warning"] = warning
                elif pe_support == "advanced":
                    warning = f"Pool effect advanced/not auto-compiled in Phase 2A: {pe_id}"
                    warnings.append(warning)
                    row["status"] = "advanced_deferred"
                    row["warning"] = warning
                else:
                    compiler_effects.append(pe)
                    row["status"] = "queued_for_compiler"
                template_rows.append(row)
            if compiler_effects:
                item_pool_effects_for_compiler[target_item_id] = compiler_effects

        summary_entry: dict[str, Any] = {
            "item_id": target_item_id,
            "source_item_ids": source_item_ids,
            "layers": layer_rows,
            "templates": template_rows,
        }
        if warnings:
            deduped_warnings: list[str] = []
            seen: set[str] = set()
            for warning in warnings:
                text = str(warning or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                deduped_warnings.append(text)
            if deduped_warnings:
                summary_entry["warning"] = " | ".join(deduped_warnings)
        summary_rows.append(summary_entry)

    contrary_lines = _build_contrary_template_lines(contrary_item_ids)
    if contrary_lines:
        lines.extend(contrary_lines)
    ability_active_bridge_lines = _build_ability_active_bridge_template_lines(ability_active_bridge_by_ability)
    if ability_active_bridge_lines:
        lines.extend(ability_active_bridge_lines)
    move_additional_effect_bridge_lines = _build_move_additional_effect_bridge_template_lines(
        move_additional_effect_bridge_by_move
    )
    if move_additional_effect_bridge_lines:
        lines.extend(move_additional_effect_bridge_lines)
    for item_id in sorted(drain_templates_by_item.keys()):
        row = drain_templates_by_item[item_id]
        heal_ratio = float(row.get("heal_ratio", 0.5))
        lines.extend(_build_drain_template_lines(item_id, heal_ratio))

    if item_pool_effects_for_compiler and _hook_compiler_mod is not None:
        try:
            pool_lines = _hook_compiler_mod.compile_pool_effects(item_pool_effects_for_compiler)
            if pool_lines:
                lines.extend(pool_lines)
        except Exception as exc:
            lines.append(f"# CustomItemPatch pool compiler error: {exc}")
            lines.append("")

    if len(lines) <= 3:
        lines.append("# No custom effect entries are currently active.")
        lines.append("")
    return "\n".join(lines), summary_rows


def _entry_name(raw: Any) -> str:
    if isinstance(raw, bytes):
        try:
            return raw.decode("utf-8")
        except Exception:
            return raw.decode("latin-1", errors="replace")
    return str(raw)


def _find_main_script_index(scripts_obj: list[Any]) -> int:
    for idx, entry in enumerate(scripts_obj):
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        if _entry_name(entry[1]).strip().lower() == "main":
            return idx
    return -1


def _find_script_patch_entry_index(scripts_obj: list[Any]) -> int:
    for idx, entry in enumerate(scripts_obj):
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        if _entry_name(entry[1]).strip() == SCRIPT_PATCH_ENTRY_NAME:
            return idx
    return -1


def _decode_script_entry_source(entry: Any) -> str:
    if not isinstance(entry, list) or len(entry) < 3:
        return ""
    try:
        source, _enc = ev_patcher._decode_script_source(bytes(entry[2]))
    except Exception:
        return ""
    return str(source or "")


def _static_inspect_ruby_source(source: str) -> dict[str, Any]:
    text = str(source or "").replace("\r\n", "\n")
    lines = text.splitlines()
    issues: list[str] = []
    stack: list[tuple[str, int]] = []
    block_open_re = re.compile(
        r"^\s*(class|module|def|if|unless|case|begin|for|while|until)\b|(^|[^.:@\w])do(\s*\|.*?\|)?\s*$"
    )
    block_close_re = re.compile(r"^\s*end\s*(#.*)?$")

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.split("#", 1)[0]
        quote: str | None = None
        escaped = False
        stripped_chars: list[str] = []
        for col, char in enumerate(line, start=1):
            if quote:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == quote:
                    quote = None
                    continue
                continue
            if char in {"'", '"'}:
                quote = char
                continue
            stripped_chars.append(char)
        stripped = "".join(stripped_chars).strip()
        if not stripped:
            continue
        if block_close_re.match(stripped):
            if stack:
                stack.pop()
            else:
                issues.append(f"Line {lineno}: unmatched 'end'.")
            continue
        if block_open_re.search(stripped):
            token = "do" if re.search(r"(^|[^.:@\w])do\b", stripped) else stripped.split(None, 1)[0]
            stack.append((token, lineno))

    for token, lineno in stack[-10:]:
        issues.append(f"Line {lineno}: '{token}' has no matching 'end'.")

    return {
        "status": "ok" if not issues else "warning",
        "line_count": len(lines),
        "issues": issues,
    }


def _script_patch_source_matches(root: Path, script_source: str) -> bool:
    scripts_file = _scripts_path(root)
    if not scripts_file.exists():
        return False
    try:
        scripts_obj = ev_patcher._load_scripts_object(scripts_file)
    except Exception:
        return False
    expected = str(script_source or "").replace("\r\n", "\n").strip()
    for entry in scripts_obj:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        if _entry_name(entry[1]).strip() != SCRIPT_PATCH_ENTRY_NAME:
            continue
        try:
            current, _enc = ev_patcher._decode_script_source(bytes(entry[2]))
        except Exception:
            return False
        return current.replace("\r\n", "\n").strip() == expected
    return False


def inspect_custom_item_runtime_patch(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    manifest = load_manifest(root)
    manifest_items = manifest.get("items", {}) if isinstance(manifest, dict) else {}
    if not isinstance(manifest_items, dict):
        manifest_items = {}
    script_source, script_summary = _build_custom_script_source(root, manifest_items)
    scripts_file = _scripts_path(root)
    runtime_file = runtime_data_path(root)
    report: dict[str, Any] = {
        "status": "ok",
        "game_root": str(root),
        "scripts_path": str(scripts_file),
        "scripts_exists": scripts_file.exists(),
        "runtime_data_path": str(runtime_file),
        "runtime_data_exists": runtime_file.exists(),
        "manifest_path": str(manifest_path(root)),
        "manifest_item_count": len(manifest_items),
        "fixed_runtime_bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
        "script_required_by_manifest": any(
            _effect_spec_requires_scripts(entry.get("effect_spec", {}) if isinstance(entry, dict) else {})
            for entry in manifest_items.values()
        ),
        "script_entry_present": False,
        "script_entry_index": -1,
        "main_script_index": -1,
        "script_entry_before_main": False,
        "script_source_matches_expected": False,
        "script_summary": script_summary,
        "expected_source_static_inspection": _static_inspect_ruby_source(script_source),
        "installed_source_static_inspection": {"status": "not_installed", "line_count": 0, "issues": []},
        "warnings": [],
    }
    warnings = report["warnings"]
    if not scripts_file.exists():
        if report["script_required_by_manifest"]:
            warnings.append("Scripts.rxdata is missing, but at least one manifest item requires runtime scripts.")
            report["status"] = "warning"
        return report
    try:
        scripts_obj = ev_patcher._load_scripts_object(scripts_file)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        warnings.append(f"Could not read Scripts.rxdata: {exc}")
        return report
    main_index = _find_main_script_index(scripts_obj)
    patch_index = _find_script_patch_entry_index(scripts_obj)
    report["main_script_index"] = main_index
    report["script_entry_index"] = patch_index
    report["script_entry_present"] = patch_index >= 0
    report["script_entry_before_main"] = bool(patch_index >= 0 and (main_index < 0 or patch_index < main_index))
    if patch_index >= 0:
        installed_source = _decode_script_entry_source(scripts_obj[patch_index])
        report["script_source_matches_expected"] = installed_source.replace("\r\n", "\n").strip() == script_source.replace("\r\n", "\n").strip()
        report["installed_source_static_inspection"] = _static_inspect_ruby_source(installed_source)
        version_match = re.search(r"Bridge version:\s*(\d+)", installed_source)
        if version_match:
            report["installed_bridge_version"] = int(version_match.group(1))
        else:
            report["installed_bridge_version"] = None
            warnings.append("Installed custom-item patch does not declare a bridge version.")
        if not report["script_entry_before_main"]:
            warnings.append("Custom-item runtime patch is not before Main; it may load too late.")
        if not report["script_source_matches_expected"]:
            warnings.append("Installed custom-item runtime patch differs from current generated source.")
    elif report["script_required_by_manifest"]:
        warnings.append("Custom-item runtime patch is missing, but manifest effects require it.")
    if not runtime_file.exists() and manifest_items:
        warnings.append("Runtime data file is missing while manifest contains custom items.")
    if warnings and report["status"] == "ok":
        report["status"] = "warning"
    return report


def _remove_script_patch_entry(root: Path) -> bool:
    scripts_file = _scripts_path(root)
    if not scripts_file.exists():
        raise FileNotFoundError(f"Missing Scripts.rxdata: {scripts_file}")
    scripts_obj = ev_patcher._load_scripts_object(scripts_file)
    patch_index = _find_script_patch_entry_index(scripts_obj)
    if patch_index < 0:
        return False
    scripts_obj.pop(patch_index)
    ev_patcher._write_scripts_object(scripts_file, scripts_obj)
    return True


def remove_custom_item_runtime_patch(
    game_root: Path | str,
    *,
    remove_runtime_data: bool = False,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    status_before = inspect_custom_item_runtime_patch(root)
    if not status_before.get("script_entry_present") and not (remove_runtime_data and runtime_data_path(root).exists()):
        return {
            "status": "no_changes",
            "changed": False,
            "runtime_data_removed": False,
            "status_before": status_before,
            "status_after": status_before,
            "patched_files": [],
        }

    stamp = _now_stamp()
    snapshots = _snapshot_targets(
        root,
        stamp=stamp,
        include_scripts=bool(status_before.get("script_entry_present")),
        include_items=False,
        include_runtime_data=bool(remove_runtime_data),
    )
    runtime_removed = False
    try:
        changed_scripts = False
        if status_before.get("script_entry_present"):
            changed_scripts = _remove_script_patch_entry(root)
        if remove_runtime_data and runtime_data_path(root).exists():
            runtime_data_path(root).unlink()
            runtime_removed = True
        manifest = load_manifest(root)
        manifest["last_transaction"] = {
            "stamp": stamp,
            "kind": "remove_runtime_patch",
            "remove_runtime_data": bool(remove_runtime_data),
            "fixed_runtime_bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
            "scripts_updated": bool(changed_scripts),
            "runtime_data_removed": bool(runtime_removed),
            "patched_files": snapshots,
        }
        _write_manifest(root, manifest)
    except Exception:
        _restore_backups(snapshots)
        raise

    status_after = inspect_custom_item_runtime_patch(root)
    return {
        "status": "removed",
        "changed": True,
        "runtime_data_removed": bool(runtime_removed),
        "status_before": status_before,
        "status_after": status_after,
        "patched_files": snapshots,
        "manifest_path": str(manifest_path(root)),
    }


def format_custom_item_patch_report(status: dict[str, Any]) -> str:
    lines = [
        "Custom Item Runtime Patch",
        f"Status: {status.get('status', 'unknown')}",
        f"Scripts.rxdata: {status.get('scripts_path', '')}",
        f"Runtime data: {status.get('runtime_data_path', '')}",
        f"Manifest: {status.get('manifest_path', '')}",
        "",
        f"Manifest items: {status.get('manifest_item_count', 0)}",
        f"Runtime data exists: {'yes' if status.get('runtime_data_exists') else 'no'}",
        f"Patch installed: {'yes' if status.get('script_entry_present') else 'no'}",
        f"Patch index: {status.get('script_entry_index', -1)}",
        f"Main index: {status.get('main_script_index', -1)}",
        f"Patch before Main: {'yes' if status.get('script_entry_before_main') else 'no'}",
        f"Bridge version expected: {status.get('fixed_runtime_bridge_version', FIXED_RUNTIME_BRIDGE_VERSION)}",
        f"Bridge version installed: {status.get('installed_bridge_version', 'n/a')}",
        f"Installed source current: {'yes' if status.get('script_source_matches_expected') else 'no'}",
        f"Script required by manifest: {'yes' if status.get('script_required_by_manifest') else 'no'}",
        "",
    ]
    for label, key in (
        ("Expected Ruby static inspection", "expected_source_static_inspection"),
        ("Installed Ruby static inspection", "installed_source_static_inspection"),
    ):
        inspect = status.get(key, {})
        if not isinstance(inspect, dict):
            inspect = {}
        lines.append(f"{label}: {inspect.get('status', 'unknown')} ({inspect.get('line_count', 0)} lines)")
        issues = inspect.get("issues", [])
        if isinstance(issues, list) and issues:
            for issue in issues[:12]:
                lines.append(f"- {issue}")
        lines.append("")
    summary = status.get("script_summary", [])
    if isinstance(summary, list) and summary:
        lines.append("Compiled manifest effects:")
        for row in summary:
            if not isinstance(row, dict):
                continue
            item_id = str(row.get("item_id", "") or "")
            layers = row.get("layers", [])
            templates = row.get("templates", [])
            warning = str(row.get("warning", "") or "")
            lines.append(f"- {item_id}: {len(layers) if isinstance(layers, list) else 0} layer(s), {len(templates) if isinstance(templates, list) else 0} template(s)")
            if warning:
                lines.append(f"  warning: {warning}")
        lines.append("")
    warnings = status.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("Warnings: none")
    return "\n".join(lines)


def _upsert_script_patch_entry(root: Path, script_source: str):
    scripts_file = _scripts_path(root)
    if not scripts_file.exists():
        raise FileNotFoundError(f"Missing Scripts.rxdata: {scripts_file}")
    scripts_obj = ev_patcher._load_scripts_object(scripts_file)
    patch_blob = ev_patcher._encode_script_source(script_source, "utf-8")
    target_index = _find_script_patch_entry_index(scripts_obj)
    patch_id: Any = None
    patch_extras: list[Any] = []
    if target_index >= 0:
        current = scripts_obj.pop(target_index)
        if isinstance(current, list) and current:
            patch_id = current[0]
            if len(current) > 3:
                patch_extras = list(current[3:])
    if patch_id is None:
        next_id = 0
        for entry in scripts_obj:
            if not isinstance(entry, list) or not entry:
                continue
            try:
                next_id = max(next_id, int(entry[0]))
            except Exception:
                continue
        patch_id = next_id + 1
    patch_entry = [patch_id, SCRIPT_PATCH_ENTRY_NAME, patch_blob]
    if patch_extras:
        patch_entry.extend(patch_extras)
    main_index = _find_main_script_index(scripts_obj)
    if main_index >= 0:
        scripts_obj.insert(main_index, patch_entry)
    else:
        scripts_obj.append(patch_entry)
    ev_patcher._write_scripts_object(scripts_file, scripts_obj)


def _make_item_object(items_map: dict[Any, Any], spec: dict[str, Any]) -> core.RubyObject:
    template_obj = None
    for value in items_map.values():
        if isinstance(value, core.RubyObject) and value.ruby_class_name == "GameData::Item":
            template_obj = value
            break
    attrs: dict[Any, Any] = {}
    if isinstance(template_obj, core.RubyObject) and isinstance(template_obj.attributes, dict):
        for key, value in template_obj.attributes.items():
            if isinstance(value, list):
                attrs[key] = list(value)
            elif isinstance(value, dict):
                attrs[key] = dict(value)
            else:
                attrs[key] = value

    item_id = _normalize_item_id(spec.get("id", ""))
    if not item_id:
        raise ValueError("Item ID is required.")

    name = str(spec.get("name", "")).strip() or item_id
    name_plural = str(spec.get("name_plural", "")).strip() or name
    description = str(spec.get("description", "")).strip() or "???"
    move_id = _normalize_item_id(spec.get("move_id", ""))
    flags = _parse_flags(spec.get("flags", []))

    pocket = _coerce_int(spec.get("pocket", 1), default=1, min_value=1, max_value=8)
    price = _coerce_int(spec.get("price", 0), default=0, min_value=0, max_value=9999999)
    sell_price = _coerce_int(spec.get("sell_price", price // 4), default=price // 4, min_value=0, max_value=9999999)
    bp_price = _coerce_int(spec.get("bp_price", 1), default=1, min_value=0, max_value=9999)
    field_use = _coerce_int(spec.get("field_use", 0), default=0, min_value=0, max_value=5)
    battle_use = _coerce_int(spec.get("battle_use", 0), default=0, min_value=0, max_value=5)

    important = ("KeyItem" in flags) or (field_use in {3, 4})
    consumable_default = not important
    consumable = _coerce_bool(spec.get("consumable", consumable_default), default=consumable_default)
    show_quantity = _coerce_bool(spec.get("show_quantity", consumable_default), default=consumable_default)

    attrs["@id"] = core.Symbol(item_id)
    attrs["@real_name"] = name
    attrs["@real_name_plural"] = name_plural
    attrs["@real_portion_name"] = None
    attrs["@real_portion_name_plural"] = None
    attrs["@pocket"] = pocket
    attrs["@price"] = price
    attrs["@sell_price"] = sell_price
    attrs["@bp_price"] = bp_price
    attrs["@field_use"] = field_use
    attrs["@battle_use"] = battle_use
    attrs["@flags"] = list(flags)
    attrs["@consumable"] = consumable
    attrs["@show_quantity"] = show_quantity
    attrs["@move"] = core.Symbol(move_id) if move_id else None
    attrs["@real_description"] = description
    attrs["@pbs_file_suffix"] = ""
    return core.RubyObject("GameData::Item", attrs)


def _symbol_value_to_id(value: Any) -> str:
    if isinstance(value, core.Symbol):
        return _normalize_item_id(value.name)
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.lower() in {"none", "nil"}:
        return ""
    return _normalize_item_id(text)


def _item_object_to_spec(item_id: str, item_obj: core.RubyObject) -> dict[str, Any]:
    if not isinstance(item_obj, core.RubyObject) or item_obj.ruby_class_name != "GameData::Item":
        raise TypeError("Item payload is not a GameData::Item object.")
    attrs = item_obj.attributes if isinstance(item_obj.attributes, dict) else {}
    flags = _parse_flags(attrs.get("@flags", []))
    field_use = _coerce_int(attrs.get("@field_use", 0), default=0, min_value=0, max_value=5)
    important = ("KeyItem" in flags) or (field_use in {3, 4})
    consumable_default = not important
    return {
        "id": _normalize_item_id(item_id),
        "name": str(attrs.get("@real_name", item_id) or item_id),
        "name_plural": str(attrs.get("@real_name_plural", attrs.get("@real_name", item_id)) or item_id),
        "pocket": _coerce_int(attrs.get("@pocket", 1), default=1, min_value=1, max_value=8),
        "price": _coerce_int(attrs.get("@price", 0), default=0, min_value=0, max_value=9999999),
        "sell_price": _coerce_int(attrs.get("@sell_price", 0), default=0, min_value=0, max_value=9999999),
        "bp_price": _coerce_int(attrs.get("@bp_price", 1), default=1, min_value=0, max_value=9999),
        "field_use": field_use,
        "battle_use": _coerce_int(attrs.get("@battle_use", 0), default=0, min_value=0, max_value=5),
        "flags": flags,
        "move_id": _symbol_value_to_id(attrs.get("@move", None)),
        "description": str(attrs.get("@real_description", "") or ""),
        "consumable": _coerce_bool(attrs.get("@consumable", consumable_default), default=consumable_default),
        "show_quantity": _coerce_bool(attrs.get("@show_quantity", consumable_default), default=consumable_default),
    }


def read_item_spec(game_root: Path | str, item_id: str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    target_id = _normalize_item_id(item_id)
    if not target_id:
        raise ValueError("Item ID is required.")
    items_map = _load_items_map(root)
    item_key = _find_item_key(items_map, target_id)
    if item_key is None:
        raise ValueError(f"Item not found in items.dat: {target_id}")
    item_obj = items_map.get(item_key)
    if not isinstance(item_obj, core.RubyObject):
        raise TypeError(f"Item payload is not a RubyObject: {target_id}")
    return _item_object_to_spec(target_id, item_obj)


def _custom_marker_reasons(item_id: str, spec: dict[str, Any], manifest_item_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    iid = _normalize_item_id(item_id)
    if iid in manifest_item_ids:
        reasons.append("id_in_manifest")
    if iid.endswith("_CUSTOM") or iid.startswith("CUSTOM_") or "CUSTOM" in iid:
        reasons.append("custom_like_id")
    name = str(spec.get("name", "") or "").strip()
    desc = str(spec.get("description", "") or "").strip()
    text_upper = f"{name}\n{desc}".upper()
    for marker in CUSTOM_GENERATED_DESCRIPTION_MARKERS:
        if marker in text_upper:
            reasons.append(f"marker:{marker}")
    return reasons


def detect_baked_custom_items(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    manifest = load_manifest(root)
    manifest_items = manifest.get("items", {}) if isinstance(manifest, dict) else {}
    manifest_item_ids = {
        _normalize_item_id(x)
        for x in (manifest_items.keys() if isinstance(manifest_items, dict) else [])
        if _normalize_item_id(x)
    }

    report: dict[str, Any] = {
        "items_dat_path": str(_item_dat_path(root)),
        "manifest_item_ids": sorted(manifest_item_ids),
        "baked_manifest_item_ids": [],
        "orphan_baked_item_ids": [],
        "detected_custom_item_ids": [],
        "details": [],
        "warning": "",
    }
    try:
        items_map = _load_items_map(root)
    except Exception as exc:
        report["warning"] = f"Could not read items.dat: {exc}"
        return report

    baked_manifest: set[str] = set()
    orphan_baked: set[str] = set()
    detected: set[str] = set()
    details: list[dict[str, Any]] = []

    for key, value in items_map.items():
        item_id = _normalize_item_id(_item_key_name(key))
        if not item_id or not isinstance(value, core.RubyObject):
            continue
        try:
            spec = _item_object_to_spec(item_id, value)
        except Exception:
            continue
        reasons = _custom_marker_reasons(item_id, spec, manifest_item_ids)
        if not reasons:
            continue
        detail = {
            "id": item_id,
            "name": str(spec.get("name", "") or ""),
            "description_preview": str(spec.get("description", "") or "")[:180],
            "reasons": list(dict.fromkeys(reasons)),
        }
        details.append(detail)
        detected.add(item_id)
        if item_id in manifest_item_ids:
            baked_manifest.add(item_id)
        else:
            orphan_baked.add(item_id)

    report["baked_manifest_item_ids"] = sorted(baked_manifest)
    report["orphan_baked_item_ids"] = sorted(orphan_baked)
    report["detected_custom_item_ids"] = sorted(detected)
    report["details"] = sorted(details, key=lambda row: str(row.get("id", "")).casefold())
    if orphan_baked:
        report["warning"] = (
            "Detected orphan baked custom items in items.dat: "
            + ", ".join(sorted(orphan_baked))
        )
    return report


def cleanup_baked_custom_items(
    game_root: Path | str,
    *,
    item_ids: list[str] | None = None,
    remove_orphans: bool = True,
    remove_manifest_linked: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    detection = detect_baked_custom_items(root)
    detected = detection.get("detected_custom_item_ids", []) if isinstance(detection, dict) else []
    orphan_ids = detection.get("orphan_baked_item_ids", []) if isinstance(detection, dict) else []
    manifest_ids = detection.get("baked_manifest_item_ids", []) if isinstance(detection, dict) else []

    candidates: list[str] = []
    if isinstance(item_ids, list) and item_ids:
        candidates = [_normalize_item_id(x) for x in item_ids if _normalize_item_id(x)]
    else:
        if remove_orphans:
            candidates.extend(_normalize_item_id(x) for x in orphan_ids)
        if remove_manifest_linked:
            candidates.extend(_normalize_item_id(x) for x in manifest_ids)
    candidates = _dedupe_ids(candidates)
    candidates = [x for x in candidates if x in {_normalize_item_id(y) for y in detected}]

    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "applied",
        "items_dat_path": str(_item_dat_path(root)),
        "candidates": list(candidates),
        "removed_ids": [],
        "backup_path": "",
        "warning": "",
    }
    if not candidates:
        result["status"] = "no_changes"
        result["warning"] = "No baked custom items matched cleanup criteria."
        return result
    if dry_run:
        return result

    items_map = _load_items_map(root)
    item_path = _item_dat_path(root)
    stamp = _now_stamp()
    backup = _copy_to_backup(root, item_path, kind="pre-custom-item-cleanup", stamp=stamp)
    removed: list[str] = []
    for item_id in candidates:
        key = _find_item_key(items_map, item_id)
        if key is None:
            continue
        del items_map[key]
        removed.append(item_id)
    _save_items_map(item_path, items_map)
    result["removed_ids"] = removed
    result["backup_path"] = str(backup)
    if not removed:
        result["status"] = "no_changes"
        result["warning"] = "No matching baked items were removed from items.dat."
    return result


def default_item_spec(item_id: str = "NEWCUSTOMITEM") -> dict[str, Any]:
    target_id = _normalize_item_id(item_id) or "NEWCUSTOMITEM"
    title = "New Custom Item"
    return {
        "id": target_id,
        "name": title,
        "name_plural": f"{title}s",
        "pocket": 1,
        "price": 0,
        "sell_price": 0,
        "bp_price": 1,
        "field_use": 0,
        "battle_use": 0,
        "flags": [],
        "move_id": "",
        "description": "TODO: customize this item (name/flags/effect mapping).",
        "consumable": True,
        "show_quantity": True,
    }


def _restore_backups(patch_rows: list[dict[str, str]]):
    for row in patch_rows:
        path = Path(str(row.get("path", "")).strip())
        backup = Path(str(row.get("backup_path", "")).strip())
        if row.get("missing_before") == "1":
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
            continue
        if not path.exists() or not backup.exists():
            continue
        shutil.copy2(backup, path)


def _snapshot_targets(
    root: Path,
    stamp: str,
    *,
    include_scripts: bool,
    include_items: bool,
    include_runtime_data: bool = False,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if include_items:
        item_path = _item_dat_path(root)
        rows.append(
            {
                "path": str(item_path),
                "backup_path": str(_copy_to_backup(root, item_path, kind="pre-custom-item", stamp=stamp)),
            }
        )
    if include_scripts:
        scripts_file = _scripts_path(root)
        if scripts_file.exists():
            rows.append(
                {
                    "path": str(scripts_file),
                    "backup_path": str(_copy_to_backup(root, scripts_file, kind="pre-custom-item", stamp=stamp)),
                }
            )
    if include_runtime_data:
        runtime_file = runtime_data_path(root)
        if runtime_file.exists():
            rows.append(
                {
                    "path": str(runtime_file),
                    "backup_path": str(_copy_to_backup(root, runtime_file, kind="pre-custom-item", stamp=stamp)),
                }
            )
        else:
            rows.append(
                {
                    "path": str(runtime_file),
                    "backup_path": "",
                    "missing_before": "1",
                }
            )
    manifest_file = manifest_path(root)
    if manifest_file.exists():
        rows.append(
            {
                "path": str(manifest_file),
                "backup_path": str(_copy_to_backup(root, manifest_file, kind="pre-custom-item", stamp=stamp)),
            }
        )
    else:
        rows.append(
            {
                "path": str(manifest_file),
                "backup_path": "",
                "missing_before": "1",
            }
        )
    return rows


def _write_manifest(root: Path, manifest: dict[str, Any]):
    manifest["version"] = MANIFEST_VERSION
    manifest["updated_at_utc"] = _now_utc_iso()
    _save_json(manifest_path(root), manifest)


def list_custom_items(game_root: Path | str) -> list[dict[str, Any]]:
    manifest = load_manifest(game_root)
    out: list[dict[str, Any]] = []
    for item_id in sorted(manifest.get("items", {}).keys()):
        entry = manifest["items"].get(item_id, {})
        if not isinstance(entry, dict):
            continue
        spec = entry.get("item_spec", {})
        if not isinstance(spec, dict):
            spec = {}
        effect = entry.get("effect_spec", {})
        if not isinstance(effect, dict):
            effect = {}
        selected_item_effects = _parse_id_list(effect.get("selected_item_effect_ids", []))
        selected_move_effects = _parse_id_list(effect.get("selected_move_effect_ids", []))
        selected_ability_effects = _parse_id_list(effect.get("selected_ability_effect_ids", []))
        selected_pool_effects = _parse_id_list(effect.get("selected_effect_ids", []))
        if not selected_item_effects and not selected_move_effects and not selected_ability_effects and not selected_pool_effects:
            selected_item_effects, selected_move_effects, selected_ability_effects = _legacy_effect_selection(effect)
        effect_count = len(selected_item_effects) + len(selected_move_effects) + len(selected_ability_effects) + len(selected_pool_effects)
        out.append(
            {
                "id": item_id,
                "name": str(spec.get("name", item_id)),
                "pocket": int(_coerce_int(spec.get("pocket", 1), default=1, min_value=1, max_value=8)),
                "effect_mode": str(effect.get("mode", "none")),
                "effect_source_item_id": str(effect.get("source_item_id", "")),
                "effect_count": effect_count,
                "updated_at_utc": str(entry.get("updated_at_utc", "")),
            }
        )
    return out


def upsert_custom_item(
    game_root: Path | str,
    item_spec: dict[str, Any],
    effect_spec: dict[str, Any] | None = None,
    *,
    bake_to_items_dat: bool = False,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    effect_spec = effect_spec if isinstance(effect_spec, dict) else {}
    item_id = _normalize_item_id(item_spec.get("id", ""))
    if not item_id:
        raise ValueError("Item ID is required.")

    manifest = load_manifest(root)
    manifest_items = manifest.get("items", {})
    if not isinstance(manifest_items, dict):
        manifest_items = {}
        manifest["items"] = manifest_items

    final_item_spec = dict(item_spec)
    final_item_spec["id"] = item_id
    if bake_to_items_dat and ENFORCE_PARALLEL_CUSTOM_ITEM_MODE:
        raise ValueError(
            "Parallel-only mode is enforced: writing custom items into Data/items.dat is disabled."
        )

    items_map: dict[Any, Any] | None = None
    if bake_to_items_dat:
        items_map = _load_items_map(root)
        item_key = _find_item_key(items_map, item_id)
        if item_key is not None:
            del items_map[item_key]
        item_obj = _make_item_object(items_map, final_item_spec)
        items_map[core.Symbol(item_id)] = item_obj

    # Keep runtime template catalog aligned with current game script checks so
    # newly selected ability effects can resolve without manual mapping edits.
    try:
        autofill_effect_template_catalog(root, persist=True, include_script_ability_scan=True)
    except Exception:
        pass

    resolved_effect = _resolve_effect_spec(root, effect_spec)

    manifest_items[item_id] = {
        "item_spec": final_item_spec,
        "effect_spec": resolved_effect,
        "updated_at_utc": _now_utc_iso(),
    }

    script_source, script_summary = _build_custom_script_source(root, manifest_items)
    scripts_exists = _scripts_path(root).exists()
    script_needs_update = bool(scripts_exists) and not _script_patch_source_matches(root, script_source)
    include_scripts = bool(script_needs_update)
    if not scripts_exists:
        needs_script = any(
            _effect_spec_requires_scripts(entry.get("effect_spec", {}) if isinstance(entry, dict) else {})
            for entry in manifest_items.values()
        )
        if needs_script:
            raise FileNotFoundError("Scripts.rxdata is required for custom item effects.")

    stamp = _now_stamp()
    snapshots = _snapshot_targets(
        root,
        stamp=stamp,
        include_scripts=include_scripts,
        include_items=bool(bake_to_items_dat),
        include_runtime_data=True,
    )
    try:
        if bake_to_items_dat and items_map is not None:
            _save_items_map(_item_dat_path(root), items_map)
        runtime_file, _runtime_summary = _write_custom_runtime_data(root, manifest_items)
        if include_scripts:
            _upsert_script_patch_entry(root, script_source)
        manifest["last_transaction"] = {
            "stamp": stamp,
            "kind": "upsert",
            "item_id": item_id,
            "bake_to_items_dat": bool(bake_to_items_dat),
            "fixed_runtime_bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
            "runtime_data_path": str(runtime_file),
            "scripts_updated": bool(include_scripts),
            "patched_files": snapshots,
        }
        _write_manifest(root, manifest)
    except Exception:
        _restore_backups(snapshots)
        raise

    return {
        "status": "upserted",
        "item_id": item_id,
        "manifest_path": str(manifest_path(root)),
        "patched_files": snapshots,
        "bake_to_items_dat": bool(bake_to_items_dat),
        "fixed_runtime_bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
        "scripts_updated": bool(include_scripts),
        "runtime_data_path": str(runtime_data_path(root)),
        "effect_spec": resolved_effect,
        "script_summary": script_summary,
    }


def upsert_custom_item_baked(
    game_root: Path | str,
    item_spec: dict[str, Any],
    effect_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if ENFORCE_PARALLEL_CUSTOM_ITEM_MODE:
        raise ValueError(
            "Parallel-only mode is enforced: legacy baked custom item mode is disabled."
        )
    result = upsert_custom_item(
        game_root,
        item_spec=item_spec,
        effect_spec=effect_spec,
        bake_to_items_dat=True,
    )
    result["warning"] = (
        "Legacy bake mode wrote custom item into Data/items.dat. "
        "Default recommended mode is manifest-only."
    )
    return result


def delete_custom_item(
    game_root: Path | str,
    item_id: str,
    *,
    remove_from_items_dat: bool = False,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    target_id = _normalize_item_id(item_id)
    if not target_id:
        raise ValueError("Item ID is required.")

    manifest = load_manifest(root)
    manifest_items = manifest.get("items", {})
    if not isinstance(manifest_items, dict):
        manifest_items = {}
        manifest["items"] = manifest_items

    if target_id not in manifest_items:
        raise ValueError(f"Custom item not found: {target_id}")
    if remove_from_items_dat and ENFORCE_PARALLEL_CUSTOM_ITEM_MODE:
        raise ValueError(
            "Parallel-only mode is enforced: removing custom items from Data/items.dat is disabled."
        )
    items_map: dict[Any, Any] | None = None
    if remove_from_items_dat:
        items_map = _load_items_map(root)
        item_key = _find_item_key(items_map, target_id)
        if item_key is not None:
            del items_map[item_key]
    if target_id in manifest_items:
        del manifest_items[target_id]

    script_source, script_summary = _build_custom_script_source(root, manifest_items)
    scripts_exists = _scripts_path(root).exists()
    script_needs_update = bool(scripts_exists) and not _script_patch_source_matches(root, script_source)
    include_scripts = bool(script_needs_update)

    stamp = _now_stamp()
    snapshots = _snapshot_targets(
        root,
        stamp=stamp,
        include_scripts=include_scripts,
        include_items=bool(remove_from_items_dat),
        include_runtime_data=True,
    )
    try:
        if remove_from_items_dat and items_map is not None:
            _save_items_map(_item_dat_path(root), items_map)
        runtime_file, _runtime_summary = _write_custom_runtime_data(root, manifest_items)
        if include_scripts:
            _upsert_script_patch_entry(root, script_source)
        manifest["last_transaction"] = {
            "stamp": stamp,
            "kind": "delete",
            "item_id": target_id,
            "remove_from_items_dat": bool(remove_from_items_dat),
            "fixed_runtime_bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
            "runtime_data_path": str(runtime_file),
            "scripts_updated": bool(include_scripts),
            "patched_files": snapshots,
        }
        _write_manifest(root, manifest)
    except Exception:
        _restore_backups(snapshots)
        raise

    return {
        "status": "deleted",
        "item_id": target_id,
        "manifest_path": str(manifest_path(root)),
        "patched_files": snapshots,
        "remove_from_items_dat": bool(remove_from_items_dat),
        "fixed_runtime_bridge_version": FIXED_RUNTIME_BRIDGE_VERSION,
        "scripts_updated": bool(include_scripts),
        "runtime_data_path": str(runtime_data_path(root)),
        "script_summary": script_summary,
    }


def delete_custom_item_baked(game_root: Path | str, item_id: str) -> dict[str, Any]:
    if ENFORCE_PARALLEL_CUSTOM_ITEM_MODE:
        raise ValueError(
            "Parallel-only mode is enforced: legacy baked delete mode is disabled."
        )
    result = delete_custom_item(
        game_root,
        item_id,
        remove_from_items_dat=True,
    )
    result["warning"] = (
        "Legacy bake cleanup removed the item from Data/items.dat. "
        "Default recommended mode is manifest-only."
    )
    return result


def rollback_last_custom_item_transaction(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    manifest = load_manifest(root)
    tx = manifest.get("last_transaction")
    if not isinstance(tx, dict):
        raise ValueError("No custom item transaction found.")
    rows = tx.get("patched_files", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("No patch snapshots found for rollback.")

    restored: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        target = Path(str(row.get("path", "")).strip())
        backup = Path(str(row.get("backup_path", "")).strip())
        missing_before = str(row.get("missing_before", "")).strip() == "1"
        if missing_before and not str(row.get("backup_path", "")).strip():
            if target.exists():
                target.unlink()
                restored.append(str(target))
            continue
        if not target.exists() or not backup.exists():
            continue
        shutil.copy2(backup, target)
        restored.append(str(target))

    if not restored:
        raise FileNotFoundError("Rollback failed: no backup snapshot could be restored.")

    # Reload manifest (it may have been restored by backup copy).
    manifest2 = load_manifest(root)
    manifest2["last_rollback"] = {
        "rolled_back_at_utc": _now_utc_iso(),
        "restored_files": restored,
        "from_transaction_stamp": str(tx.get("stamp", "")),
        "from_transaction_kind": str(tx.get("kind", "")),
        "from_item_id": str(tx.get("item_id", "")),
    }
    _write_manifest(root, manifest2)
    return {
        "status": "rolled_back",
        "restored_files": restored,
        "manifest_path": str(manifest_path(root)),
    }
