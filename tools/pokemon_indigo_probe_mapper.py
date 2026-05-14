#!/usr/bin/env python
"""Game probe + profile lock for the Pokemon Indigo save editor.

This tool scans game data files plus one save file, then writes a profile lock
that the GUI can validate before allowing edits/saves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pokemon_indigo_save_editor as core  # noqa: E402
from pokemon_indigo_game_data import GameCatalogs  # noqa: E402


PROFILE_VERSION = 1
DEFAULT_PROFILE_FILENAME = "editor_profile.lock.json"

TRACKED_EXACT_FILES = [
    "Game.ini",
    "mkxp.json",
    "preload.rb",
    "Data/Scripts.rxdata",
    "Data/PluginScripts.rxdata",
    "Data/messages_core.dat",
    "Data/messages_game.dat",
    "Data/messages_english_game.dat",
]

TRACKED_PATTERN_FILES = [
    ("Data", "*.dat"),
    ("PBS", "*.txt"),
    ("Data/data_for_showdown", "*.txt"),
]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _name_of(value: Any) -> str:
    if isinstance(value, core.Symbol):
        return value.name
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="replace")
    return str(value)


def _node_kind(value: Any) -> str:
    if isinstance(value, core.RubyObject):
        return value.ruby_class_name
    if isinstance(value, dict):
        return "Hash"
    if isinstance(value, list):
        return "Array"
    if isinstance(value, core.Symbol):
        return "Symbol"
    if value is None:
        return "NilClass"
    return type(value).__name__


def default_profile_path(game_root: Path) -> Path:
    return (Path(game_root).resolve() / "tools" / DEFAULT_PROFILE_FILENAME).resolve()


def load_profile(path: Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def write_profile(profile: dict[str, Any], path: Path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def _collect_tracked_files(game_root: Path) -> list[tuple[str, Path]]:
    root = Path(game_root).resolve()
    found: dict[str, Path] = {}

    for rel in TRACKED_EXACT_FILES:
        path = root / rel
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path

    for subdir, pattern in TRACKED_PATTERN_FILES:
        base = root / subdir
        if not base.exists():
            continue
        for path in base.rglob(pattern):
            if path.is_file():
                found[path.relative_to(root).as_posix()] = path

    return sorted(found.items(), key=lambda row: row[0].casefold())


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def build_game_probe(game_root: Path, include_content_hashes: bool) -> dict[str, Any]:
    root = Path(game_root).resolve()
    tracked = _collect_tracked_files(root)
    manifest: list[dict[str, Any]] = []

    fast_hasher = hashlib.sha256()
    deep_hasher = hashlib.sha256()

    for rel, path in tracked:
        st = path.stat()
        row: dict[str, Any] = {
            "path": rel,
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }
        fast_hasher.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}\n".encode("utf-8"))
        if include_content_hashes:
            content_hash = _sha256_file(path)
            row["sha256"] = content_hash
            deep_hasher.update(f"{rel}|{content_hash}\n".encode("utf-8"))
        manifest.append(row)

    return {
        "tracked_file_count": len(manifest),
        "tracked_files": manifest,
        "fast_fingerprint": fast_hasher.hexdigest(),
        "deep_fingerprint": deep_hasher.hexdigest() if include_content_hashes else "",
        "tracked_exact_files": TRACKED_EXACT_FILES,
        "tracked_patterns": [{"base": base, "pattern": pattern} for base, pattern in TRACKED_PATTERN_FILES],
    }


def _extract_attr_keys(value: Any) -> list[str]:
    if not isinstance(value, core.RubyObject):
        return []
    attrs = value.attributes if isinstance(value.attributes, dict) else {}
    return sorted({_name_of(key) for key in attrs.keys()})


def _pokemon_attr_union(player_obj: Any, storage_obj: Any, sample_limit: int = 24) -> list[str]:
    keys: set[str] = set()
    samples = 0

    def push_pokemon(candidate: Any):
        nonlocal samples
        if samples >= sample_limit:
            return
        if not isinstance(candidate, core.RubyObject):
            return
        attrs = candidate.attributes if isinstance(candidate.attributes, dict) else {}
        keys.update(_name_of(k) for k in attrs.keys())
        samples += 1

    if isinstance(player_obj, core.RubyObject):
        party = core.read_attr(player_obj, "@party", [])
        if isinstance(party, list):
            for mon in party:
                push_pokemon(mon)
                if samples >= sample_limit:
                    break

    if samples < sample_limit and isinstance(storage_obj, core.RubyObject):
        boxes = core.read_attr(storage_obj, "@boxes", [])
        if isinstance(boxes, list):
            for box in boxes:
                if samples >= sample_limit:
                    break
                if not isinstance(box, core.RubyObject):
                    continue
                arr = core.read_attr(box, "@pokemon", [])
                if not isinstance(arr, list):
                    continue
                for mon in arr:
                    push_pokemon(mon)
                    if samples >= sample_limit:
                        break

    return sorted(keys)


def probe_save_schema(save_path: Path) -> dict[str, Any]:
    save_file = Path(save_path).resolve()
    data = core.load_save(save_file)
    if not isinstance(data, dict):
        raise ValueError("Top-level save payload is not a Hash/dict.")

    root_keys = sorted(_name_of(k) for k in data.keys())
    root_kinds = {k: _node_kind(v) for k, v in sorted((_name_of(k), v) for k, v in data.items())}

    player = core.read_root_key(data, "player")
    storage = core.read_root_key(data, "storage_system")
    bag = core.read_attr(player, "@bag", None) if isinstance(player, core.RubyObject) else None

    party_len = 0
    if isinstance(player, core.RubyObject):
        party = core.read_attr(player, "@party", [])
        if isinstance(party, list):
            party_len = len(party)

    box_count = 0
    box_slot_size = 0
    if isinstance(storage, core.RubyObject):
        boxes = core.read_attr(storage, "@boxes", [])
        if isinstance(boxes, list):
            box_count = len(boxes)
            for box in boxes:
                if not isinstance(box, core.RubyObject):
                    continue
                slots = core.read_attr(box, "@pokemon", [])
                if isinstance(slots, list):
                    box_slot_size = max(box_slot_size, len(slots))

    schema_basis = {
        "root_keys": root_keys,
        "root_kinds": root_kinds,
        "player_attr_keys": _extract_attr_keys(player),
        "storage_attr_keys": _extract_attr_keys(storage),
        "bag_attr_keys": _extract_attr_keys(bag),
        "pokemon_attr_keys": _pokemon_attr_union(player, storage),
    }
    schema_hash = hashlib.sha256(
        json.dumps(schema_basis, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    st = save_file.stat()
    return {
        "path": str(save_file),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
        "party_size": party_len,
        "box_count": box_count,
        "max_box_size_seen": box_slot_size,
        "schema_basis": schema_basis,
        "schema_hash": schema_hash,
    }


def _catalog_summary(game_root: Path) -> dict[str, Any]:
    try:
        catalogs = GameCatalogs.load(Path(game_root).resolve())
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {
        "species_count": len(catalogs.species_by_id),
        "moves_count": len(catalogs.moves_by_id),
        "items_count": len(catalogs.items_by_id),
        "abilities_count": len(catalogs.abilities_by_id),
        "species_form_profiles_count": len(catalogs.species_form_profiles),
        "growth_rate_tables_count": len(catalogs.growth_rate_exp_tables),
        "pocket_names": list(catalogs.pocket_names),
    }


def build_profile(game_root: Path, save_path: Path) -> dict[str, Any]:
    game_root = Path(game_root).resolve()
    save_path = Path(save_path).resolve()
    game_probe = build_game_probe(game_root, include_content_hashes=True)
    save_probe = probe_save_schema(save_path)
    return {
        "profile_version": PROFILE_VERSION,
        "created_at_utc": _now_utc_iso(),
        "game_root": str(game_root),
        "save_path": str(save_path),
        "game_probe": game_probe,
        "save_probe": save_probe,
        "catalog_summary": _catalog_summary(game_root),
    }


def run_probe(game_root: Path, save_path: Path, profile_path: Path | None = None) -> dict[str, Any]:
    profile = build_profile(game_root, save_path)
    if profile_path is not None:
        write_profile(profile, profile_path)
    return profile


def _compare_schema(profile_save_probe: dict[str, Any], current_save_probe: dict[str, Any]) -> str | None:
    expected = profile_save_probe.get("schema_basis", {})
    current = current_save_probe.get("schema_basis", {})
    if not isinstance(expected, dict) or not isinstance(current, dict):
        return "Profile save schema is malformed."

    def as_set(obj: Any, key: str) -> set[str]:
        values = obj.get(key, [])
        if not isinstance(values, list):
            return set()
        return {str(v) for v in values}

    for key in ("root_keys", "player_attr_keys", "storage_attr_keys", "bag_attr_keys"):
        exp = as_set(expected, key)
        cur = as_set(current, key)
        if exp != cur:
            missing = sorted(exp - cur)
            extra = sorted(cur - exp)
            parts = []
            if missing:
                parts.append(f"missing={', '.join(missing[:6])}")
            if extra:
                parts.append(f"extra={', '.join(extra[:6])}")
            return f"Save schema mismatch at {key}: {'; '.join(parts)}"

    exp_pkmn = as_set(expected, "pokemon_attr_keys")
    cur_pkmn = as_set(current, "pokemon_attr_keys")
    if exp_pkmn and cur_pkmn:
        overlap = len(exp_pkmn & cur_pkmn)
        ratio = overlap / max(1, len(exp_pkmn))
        if ratio < 0.7:
            return "Save Pokemon structure differs too much from mapped profile."

    return None


def verify_profile_data(
    profile_data: dict[str, Any] | None,
    game_root: Path,
    save_path: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    details: dict[str, Any] = {}
    if not profile_data:
        return False, "Profile lock not found. Run mapper/probe first.", details

    version = int(profile_data.get("profile_version", 0))
    if version != PROFILE_VERSION:
        return (
            False,
            f"Profile version mismatch (have {version}, expected {PROFILE_VERSION}). Re-run mapper/probe.",
            details,
        )

    profile_game = profile_data.get("game_probe", {})
    if not isinstance(profile_game, dict):
        return False, "Profile lock is invalid (missing game_probe).", details

    current_game = build_game_probe(Path(game_root).resolve(), include_content_hashes=False)
    details["expected_fast_fingerprint"] = profile_game.get("fast_fingerprint", "")
    details["current_fast_fingerprint"] = current_game["fast_fingerprint"]
    details["expected_file_count"] = profile_game.get("tracked_file_count", 0)
    details["current_file_count"] = current_game["tracked_file_count"]

    if str(profile_game.get("fast_fingerprint", "")) != current_game["fast_fingerprint"]:
        return (
            False,
            "Game data fingerprint changed. Re-run mapper/probe before editing saves.",
            details,
        )

    if save_path is not None:
        profile_save = profile_data.get("save_probe", {})
        if not isinstance(profile_save, dict):
            return False, "Profile lock is invalid (missing save_probe).", details
        current_save = probe_save_schema(Path(save_path).resolve())
        details["expected_save_schema_hash"] = profile_save.get("schema_hash", "")
        details["current_save_schema_hash"] = current_save.get("schema_hash", "")
        schema_issue = _compare_schema(profile_save, current_save)
        if schema_issue:
            return False, f"{schema_issue} Re-run mapper/probe.", details

    return True, "Profile check passed.", details


def verify_profile_path(
    profile_path: Path,
    game_root: Path,
    save_path: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    return verify_profile_data(load_profile(profile_path), game_root, save_path)


def _resolve_save_path_from_args(value: str | None) -> Path:
    if value:
        p = Path(value).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Save file not found: {p}")
        return p
    return core.resolve_save_path(None)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pokemon Indigo game probe/profile mapper")
    parser.add_argument("--game-root", default=str(HERE.parent), help="Path to game root folder.")
    parser.add_argument("--save", help="Path to save file (.rxdata).")
    parser.add_argument(
        "--profile",
        help="Output profile lock path. Default: <game_root>/tools/editor_profile.lock.json",
    )
    parser.add_argument("--verify", action="store_true", help="Verify an existing profile lock instead of rebuilding.")
    args = parser.parse_args(argv)

    game_root = Path(args.game_root).expanduser().resolve()
    profile_path = Path(args.profile).expanduser().resolve() if args.profile else default_profile_path(game_root)

    try:
        save_path = _resolve_save_path_from_args(args.save)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.verify:
        ok, reason, details = verify_profile_path(profile_path, game_root, save_path=save_path)
        print(reason)
        print(json.dumps(details, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    try:
        profile = run_probe(game_root, save_path, profile_path=profile_path)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Profile written: {profile_path}")
    print(f"Game root: {game_root}")
    print(f"Save: {save_path}")
    print(f"Tracked files: {profile['game_probe'].get('tracked_file_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
