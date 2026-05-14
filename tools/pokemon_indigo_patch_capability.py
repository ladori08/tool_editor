#!/usr/bin/env python
"""Patch capability probe + adapter builder for Pokemon Indigo save editor."""

from __future__ import annotations

import json
import os
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from rubymarshal.reader import load as marshal_load
except Exception:  # noqa: BLE001
    marshal_load = None

import pokemon_indigo_ev_patcher as ev_patcher


PROFILE_VERSION = 1
ADAPTER_VERSION = 1
CAPABILITY_FILENAME = "patch_capability.profile.json"
ADAPTER_FILENAME = "patch_adapter.lock.json"


_ITEM_HANDLERS_CALL = re.compile(r"ItemHandlers::([A-Za-z0-9_]+)\.(?:add|copy|addIf)\s*\(")
_BATTLE_ITEM_EFFECTS_CALL = re.compile(r"Battle::ItemEffects::([A-Za-z0-9_]+)\.(?:add|copy)\s*\(")
_BATTLE_ABILITY_EFFECTS_CALL = re.compile(r"Battle::AbilityEffects::([A-Za-z0-9_]+)\.(?:add|copy)\s*\(")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_game_root(game_root: Path | str) -> Path:
    return Path(game_root).expanduser().resolve()


def default_capability_path(game_root: Path | str) -> Path:
    return (_resolve_game_root(game_root) / "tools" / CAPABILITY_FILENAME).resolve()


def default_adapter_path(game_root: Path | str) -> Path:
    return (_resolve_game_root(game_root) / "tools" / ADAPTER_FILENAME).resolve()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def _save_json(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _decode_bytes(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _iter_scripts_rxdata_sources(game_root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    path = game_root / "Data" / "Scripts.rxdata"
    if not path.exists():
        return out
    try:
        scripts_obj = ev_patcher._load_scripts_object(path)
    except Exception:
        return out
    for idx, entry in enumerate(scripts_obj):
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        name = str(entry[1])
        try:
            source, _encoding = ev_patcher._decode_script_source(bytes(entry[2]))
        except Exception:
            continue
        out.append((f"scripts_rxdata:{idx}:{name}", source))
    return out


def _iter_plugin_scripts_sources(game_root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    path = game_root / "Data" / "PluginScripts.rxdata"
    if not path.exists() or marshal_load is None:
        return out
    try:
        with path.open("rb") as f:
            plugins = marshal_load(f)
    except Exception:
        return out
    if not isinstance(plugins, list):
        return out
    for pidx, plugin in enumerate(plugins):
        if not isinstance(plugin, list) or len(plugin) < 3:
            continue
        plugin_name = str(plugin[0])
        rows = plugin[2]
        if not isinstance(rows, list):
            continue
        for ridx, row in enumerate(rows):
            if not isinstance(row, list) or len(row) < 2:
                continue
            file_name = str(row[0])
            blob = row[1]
            if not isinstance(blob, (bytes, bytearray)):
                continue
            text = ""
            raw = bytes(blob)
            try:
                text = _decode_bytes(zlib.decompress(raw))
            except Exception:
                try:
                    text = _decode_bytes(raw)
                except Exception:
                    text = ""
            if text:
                out.append((f"plugin_rxdata:{pidx}:{ridx}:{plugin_name}:{file_name}", text))
    return out


def _iter_rb_sources(game_root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    scripts_dir = game_root / "Data" / "Scripts"
    if not scripts_dir.is_dir():
        return out
    for path in scripts_dir.rglob("*.rb"):
        try:
            raw = path.read_bytes()
            source = _decode_bytes(raw)
        except Exception:
            continue
        rel = path.relative_to(game_root).as_posix()
        out.append((f"rb:{rel}", source))
    return out


def _scan_sources(script_sources: list[tuple[str, str]]) -> dict[str, Any]:
    has_item_handlers = False
    has_battle_item_effects = False
    has_battle_ability_effects = False
    has_handler_hash = False
    has_game_data_item = False
    has_game_data_ability = False
    has_game_data_move = False

    item_buckets: set[str] = set()
    battle_item_buckets: set[str] = set()
    battle_ability_buckets: set[str] = set()

    for _source_id, source in script_sources:
        if not has_item_handlers and "module ItemHandlers" in source:
            has_item_handlers = True
        if not has_battle_item_effects and "module Battle::ItemEffects" in source:
            has_battle_item_effects = True
        if not has_battle_ability_effects and "module Battle::AbilityEffects" in source:
            has_battle_ability_effects = True
        if not has_handler_hash and "class HandlerHashSymbol" in source:
            has_handler_hash = True
        if not has_game_data_item and "module GameData" in source and "class Item" in source:
            has_game_data_item = True
        if not has_game_data_ability and "module GameData" in source and "class Ability" in source:
            has_game_data_ability = True
        if not has_game_data_move and "module GameData" in source and "class Move" in source:
            has_game_data_move = True

        for line in source.splitlines():
            m_item = _ITEM_HANDLERS_CALL.search(line)
            if m_item:
                item_buckets.add(m_item.group(1))
            m_bi = _BATTLE_ITEM_EFFECTS_CALL.search(line)
            if m_bi:
                battle_item_buckets.add(m_bi.group(1))
            m_ba = _BATTLE_ABILITY_EFFECTS_CALL.search(line)
            if m_ba:
                battle_ability_buckets.add(m_ba.group(1))

    return {
        "registries": {
            "item_handlers": has_item_handlers,
            "battle_item_effects": has_battle_item_effects,
            "battle_ability_effects": has_battle_ability_effects,
        },
        "schemas": {
            "game_data_item": has_game_data_item,
            "game_data_ability": has_game_data_ability,
            "game_data_move": has_game_data_move,
            "handler_hash_symbol": has_handler_hash,
        },
        "buckets": {
            "item_handlers": sorted(item_buckets),
            "battle_item_effects": sorted(battle_item_buckets),
            "battle_ability_effects": sorted(battle_ability_buckets),
        },
    }


def probe_patch_capability(
    game_root: Path | str,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    scripts_rxdata = (root / "Data" / "Scripts.rxdata").is_file()
    plugin_rxdata = (root / "Data" / "PluginScripts.rxdata").is_file()
    rb_scripts = (root / "Data" / "Scripts").is_dir()
    items_dat = (root / "Data" / "items.dat")
    abilities_dat = (root / "Data" / "abilities.dat")
    moves_dat = (root / "Data" / "moves.dat")

    script_sources = []
    script_sources.extend(_iter_scripts_rxdata_sources(root))
    script_sources.extend(_iter_plugin_scripts_sources(root))
    script_sources.extend(_iter_rb_sources(root))

    scan = _scan_sources(script_sources)

    can_metadata_patch = items_dat.is_file() and os.access(items_dat, os.W_OK)
    can_clone_effects = bool(
        scan["registries"]["item_handlers"]
        and scan["registries"]["battle_item_effects"]
        and scan["schemas"]["handler_hash_symbol"]
    )
    can_ruby_inject = bool(
        can_clone_effects
        and (
            scripts_rxdata
            or rb_scripts
            or plugin_rxdata
        )
    )

    ev_patch_status: dict[str, Any] = {}
    try:
        ev_patch_status = ev_patcher.inspect_patch_status(root)
    except Exception as exc:  # noqa: BLE001
        ev_patch_status = {"error": str(exc)}

    out = {
        "profile_version": PROFILE_VERSION,
        "created_at_utc": _now_utc_iso(),
        "game_root": str(root),
        "script_sources": {
            "scripts_rxdata": scripts_rxdata,
            "plugin_scripts_rxdata": plugin_rxdata,
            "data_scripts_rb": rb_scripts,
            "loaded_source_count": len(script_sources),
        },
        "data_files": {
            "items_dat": items_dat.is_file(),
            "abilities_dat": abilities_dat.is_file(),
            "moves_dat": moves_dat.is_file(),
        },
        "scan": scan,
        "patch_levels": {
            "A_metadata_item_data": can_metadata_patch,
            "B_clone_existing_effects": can_clone_effects,
            "C_ruby_injection": can_ruby_inject,
        },
        "ev_patch_target": ev_patch_status,
    }
    target = Path(output_path).expanduser().resolve() if output_path else default_capability_path(root)
    _save_json(target, out)
    out["profile_path"] = str(target)
    return out


def load_capability(path: Path | str) -> dict[str, Any] | None:
    return _load_json(Path(path).expanduser().resolve())


def rebuild_patch_adapter(
    game_root: Path | str,
    capability_data: dict[str, Any] | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    profile_path = default_capability_path(root)
    profile = capability_data
    if not isinstance(profile, dict):
        profile = _load_json(profile_path)
    if not isinstance(profile, dict):
        profile = probe_patch_capability(root, output_path=profile_path)

    script_sources = profile.get("script_sources", {})
    levels = profile.get("patch_levels", {})
    scan = profile.get("scan", {})
    buckets = scan.get("buckets", {})

    if bool(script_sources.get("scripts_rxdata")):
        adapter_id = "essentials_packed_rxdata"
        script_target = "Data/Scripts.rxdata"
        script_mode = "rxdata_script_entry_patch"
    elif bool(script_sources.get("data_scripts_rb")):
        adapter_id = "essentials_unpacked_rb"
        script_target = "Data/Scripts/*.rb"
        script_mode = "rb_file_patch"
    elif bool(script_sources.get("plugin_scripts_rxdata")):
        adapter_id = "essentials_plugin_rxdata"
        script_target = "Data/PluginScripts.rxdata"
        script_mode = "plugin_rxdata_patch"
    else:
        adapter_id = "unknown"
        script_target = ""
        script_mode = "unsupported"

    adapter = {
        "adapter_version": ADAPTER_VERSION,
        "generated_at_utc": _now_utc_iso(),
        "game_root": str(root),
        "adapter_id": adapter_id,
        "capability_profile_path": str(profile_path),
        "levels": {
            "A_metadata_item_data": bool(levels.get("A_metadata_item_data")),
            "B_clone_existing_effects": bool(levels.get("B_clone_existing_effects")),
            "C_ruby_injection": bool(levels.get("C_ruby_injection")),
        },
        "strategies": {
            "metadata_patch": {
                "enabled": bool(levels.get("A_metadata_item_data")),
                "target": "Data/items.dat",
                "transactional": True,
            },
            "effect_clone": {
                "enabled": bool(levels.get("B_clone_existing_effects")),
                "item_handlers_registry": bool(scan.get("registries", {}).get("item_handlers")),
                "battle_item_effects_registry": bool(scan.get("registries", {}).get("battle_item_effects")),
                "item_handler_buckets": list(buckets.get("item_handlers", [])),
                "battle_item_effect_buckets": list(buckets.get("battle_item_effects", [])),
            },
            "ruby_injection": {
                "enabled": bool(levels.get("C_ruby_injection")),
                "target": script_target,
                "mode": script_mode,
            },
            "custom_item_manifest": {
                "path": "tools/custom_item/data/custom_item_manifest.json",
                "backup_root": "tools/custom_item/backups",
            },
        },
    }

    target = Path(output_path).expanduser().resolve() if output_path else default_adapter_path(root)
    _save_json(target, adapter)
    adapter["adapter_path"] = str(target)
    return adapter
