#!/usr/bin/env python
"""EV unlock patch helper for RPG Maker Pokemon games.

Supports two script layouts:
1) `Data/Scripts.rxdata` (classic packed scripts).
2) `Data/Scripts/**/*.rb` (folder-based scripts used by some fan games).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pokemon_indigo_save_editor as core


TARGET_EV_LIMIT = 1512
MANIFEST_VERSION = 1
MANIFEST_FILENAME = "ev_patch_state.json"
BACKUP_ROOT_DIRNAME = "ev_patch_backups"
POKEMON_SCRIPT_NAME = "Pokemon"
EV_LIMIT_ASSIGN_RE = re.compile(r"(^\s*EV_LIMIT\s*=\s*)(\d+)", flags=re.MULTILINE)
EV_GUARD_CLAMP_ASSIGN_RE = re.compile(
    r"^([ \t]*)([A-Za-z_]\w*)\s*=\s*(.+?)\.clamp\(0,\s*(.+?)\)\s*$",
    flags=re.MULTILINE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _resolve_game_root(game_root: Path | str) -> Path:
    root = Path(game_root).expanduser().resolve()
    if not (root / "Data").is_dir():
        raise ValueError(f"Invalid game root (missing Data folder): {root}")
    return root


def scripts_path(game_root: Path | str) -> Path:
    return _resolve_game_root(game_root) / "Data" / "Scripts.rxdata"


def manifest_path(game_root: Path | str) -> Path:
    return _resolve_game_root(game_root) / "tools" / MANIFEST_FILENAME


def _backup_root(game_root: Path | str) -> Path:
    return _resolve_game_root(game_root) / "tools" / BACKUP_ROOT_DIRNAME


def _relative_to_root(root: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except Exception:
        return Path("_external") / path.name


def _build_backup_path(root: Path, target_path: Path, kind: str, stamp: str) -> Path:
    rel = _relative_to_root(root, target_path)
    out_dir = _backup_root(root) / kind / rel.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{target_path.name}.{stamp}.bak"


def _copy_to_backup(root: Path, target_path: Path, kind: str, stamp: str) -> Path:
    backup = _build_backup_path(root, target_path, kind=kind, stamp=stamp)
    shutil.copy2(target_path, backup)
    return backup


def _resolve_existing_backup_path(root: Path, backup_hint: str) -> Path:
    hint = Path(backup_hint).expanduser()
    if hint.exists():
        return hint.resolve()
    name = hint.name
    if not name:
        return hint.resolve()
    matches = [p for p in _backup_root(root).rglob(name) if p.is_file()]
    if matches:
        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return matches[0]
    return hint.resolve()


def _latest_backup_for_target(root: Path, target_path: Path) -> Path | None:
    candidates: list[Path] = []
    rel = _relative_to_root(root, target_path)
    backup_root = _backup_root(root)
    for folder in ("pre-ev-unlock", "pre-ev-rollback", "legacy-inplace"):
        base = backup_root / folder / rel.parent
        if not base.is_dir():
            continue
        candidates.extend([p for p in base.glob(f"{target_path.name}*.bak") if p.is_file()])
    # Legacy fallback (older builds backed up next to target script file).
    candidates.extend([p for p in target_path.parent.glob(f"{target_path.name}.pre-ev-unlock-*.bak") if p.is_file()])
    candidates.extend([p for p in target_path.parent.glob(f"{target_path.name}.pre-ev-rollback-*.bak") if p.is_file()])
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _quarantine_legacy_script_backups(root: Path) -> list[dict[str, str]]:
    scripts_dir = root / "Data" / "Scripts"
    if not scripts_dir.is_dir():
        return []
    moved: list[dict[str, str]] = []
    stamp = _now_stamp()
    patterns = ("*.pre-ev-unlock-*.bak", "*.pre-ev-rollback-*.bak")
    for pattern in patterns:
        for src in scripts_dir.rglob(pattern):
            if not src.is_file():
                continue
            rel = _relative_to_root(root, src)
            dst_dir = _backup_root(root) / "legacy-inplace" / rel.parent
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / src.name
            if dst.exists():
                dst = dst_dir / f"{src.name}.{stamp}.moved.bak"
            shutil.move(str(src), str(dst))
            moved.append({"from": str(src), "to": str(dst)})
    return moved


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _decode_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def _save_manifest(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_scripts_object(path: Path) -> list[Any]:
    obj = core.load_save(path)
    if not isinstance(obj, list):
        raise ValueError(f"Unexpected Scripts.rxdata payload type: {type(obj).__name__}")
    return obj


def _write_scripts_object(path: Path, scripts_obj: list[Any]):
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("wb") as f:
        core.marshal_write(f, scripts_obj, cls=core.SaveWriter)
    tmp.replace(path)


def _decode_script_source(blob: bytes) -> tuple[str, str]:
    raw = zlib.decompress(blob)
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _encode_script_source(text: str, encoding: str) -> bytes:
    try:
        return zlib.compress(text.encode(encoding), level=9)
    except Exception:
        return zlib.compress(text.encode("utf-8"), level=9)


def _find_pokemon_script_entry(scripts_obj: list[Any]) -> tuple[int, list[Any]]:
    for idx, entry in enumerate(scripts_obj):
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        if _decode_text(entry[1]) != POKEMON_SCRIPT_NAME:
            continue
        if not isinstance(entry[2], (bytes, bytearray)):
            raise ValueError("Pokemon script payload is not compressed bytes.")
        return idx, entry
    raise ValueError("Could not find 'Pokemon' script inside Scripts.rxdata.")


def _extract_ev_limit(script_source: str) -> int | None:
    m = EV_LIMIT_ASSIGN_RE.search(script_source)
    if not m:
        return None
    try:
        return int(m.group(2))
    except (TypeError, ValueError):
        return None


def _read_text_with_encoding(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _write_text_with_encoding(path: Path, text: str, encoding: str):
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        blob = text.encode(encoding)
    except Exception:
        blob = text.encode("utf-8")
    tmp.write_bytes(blob)
    tmp.replace(path)


def _patch_ev_limit_source(source: str, target_ev_limit: int) -> tuple[str, int]:
    return EV_LIMIT_ASSIGN_RE.subn(rf"\g<1>{int(target_ev_limit)}", source, count=1)


def _patch_ev_guard_clamps_source(source: str) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        indent, lhs, value_expr, upper_expr = match.group(1), match.group(2), match.group(3), match.group(4)
        upper = upper_expr.strip()
        if "Pokemon::EV_LIMIT" not in upper and "Pokemon::EV_STAT_LIMIT" not in upper:
            return match.group(0)
        count += 1
        # Avoid Ruby clamp edge errors when upper bound is <= 0.
        # Equivalent to clamp(0, upper) for positive upper, and hard-zero otherwise.
        return f"{indent}{lhs} = [{value_expr.strip()}, [({upper}), 0].max].min"

    patched = EV_GUARD_CLAMP_ASSIGN_RE.sub(repl, source)
    return patched, count


def _restore_patched_files(entries: list[dict[str, Any]]):
    for entry in reversed(entries):
        path = Path(str(entry.get("path", "") or "")).expanduser()
        backup = Path(str(entry.get("backup_path", "") or "")).expanduser()
        if not path.exists() or not backup.exists():
            continue
        shutil.copy2(backup, path)


def _apply_rb_ev_guard_patches(game_root: Path, stamp: str) -> list[dict[str, Any]]:
    scripts_dir = game_root / "Data" / "Scripts"
    if not scripts_dir.is_dir():
        return []
    changed: list[dict[str, Any]] = []
    try:
        for path in scripts_dir.rglob("*.rb"):
            try:
                source, encoding = _read_text_with_encoding(path)
            except Exception:
                continue
            patched, replacements = _patch_ev_guard_clamps_source(source)
            if replacements <= 0 or patched == source:
                continue
            backup = _copy_to_backup(game_root, path, kind="pre-ev-unlock", stamp=stamp)
            before_hash = _sha256_file(path)
            _write_text_with_encoding(path, patched, encoding)
            after_hash = _sha256_file(path)
            changed.append(
                {
                    "kind": "ev_guard",
                    "path": str(path),
                    "backup_path": str(backup),
                    "before_sha256": before_hash,
                    "after_sha256": after_hash,
                    "replacements": int(replacements),
                }
            )
    except Exception:
        _restore_patched_files(changed)
        raise
    return changed


def _discover_rxdata_target(game_root: Path) -> dict[str, Any] | None:
    scripts_file = scripts_path(game_root)
    if not scripts_file.exists():
        return None
    scripts_obj = _load_scripts_object(scripts_file)
    idx, pokemon_entry = _find_pokemon_script_entry(scripts_obj)
    source, encoding = _decode_script_source(bytes(pokemon_entry[2]))
    current = _extract_ev_limit(source)
    if current is None:
        return None
    return {
        "source_type": "rxdata",
        "target_path": scripts_file,
        "current_ev_limit": current,
        "scripts_obj": scripts_obj,
        "entry_index": idx,
        "entry": pokemon_entry,
        "source_text": source,
        "source_encoding": encoding,
    }


def _rb_candidate_score(path: Path, source: str) -> int:
    score = 0
    if re.search(r"^\s*class\s+Pokemon\b", source, flags=re.MULTILINE):
        score += 6
    if "EV_STAT_LIMIT" in source:
        score += 4
    if "IV_STAT_LIMIT" in source:
        score += 2
    if "class << self" in source:
        score += 1
    if "pokemon" in path.name.lower():
        score += 2
    if "014_Pokemon" in str(path).replace("\\", "/"):
        score += 2
    return score


def _discover_rb_target(game_root: Path) -> dict[str, Any] | None:
    scripts_dir = game_root / "Data" / "Scripts"
    if not scripts_dir.is_dir():
        return None
    candidates: list[tuple[int, Path, str, str, int]] = []
    for path in scripts_dir.rglob("*.rb"):
        try:
            source, encoding = _read_text_with_encoding(path)
        except Exception:
            continue
        current = _extract_ev_limit(source)
        if current is None:
            continue
        score = _rb_candidate_score(path, source)
        candidates.append((score, path, source, encoding, current))
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            -row[0],
            len(str(row[1])),
            str(row[1]).casefold(),
        )
    )
    score, path, source, encoding, current = candidates[0]
    return {
        "source_type": "rb_file",
        "target_path": path,
        "current_ev_limit": current,
        "source_text": source,
        "source_encoding": encoding,
        "match_score": score,
    }


def _discover_patch_target(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    errors: list[str] = []
    try:
        rxdata_target = _discover_rxdata_target(root)
    except Exception as exc:  # noqa: BLE001
        rxdata_target = None
        errors.append(f"rxdata: {exc}")
    if rxdata_target is not None:
        rxdata_target["game_root"] = str(root)
        return rxdata_target

    try:
        rb_target = _discover_rb_target(root)
    except Exception as exc:  # noqa: BLE001
        rb_target = None
        errors.append(f"rb: {exc}")
    if rb_target is not None:
        rb_target["game_root"] = str(root)
        return rb_target

    detail = "; ".join(errors) if errors else "No compatible script source found."
    raise ValueError(
        "Could not locate EV limit definition in Scripts.rxdata or Data/Scripts/*.rb. "
        f"Detail: {detail}"
    )


def inspect_patch_status(game_root: Path | str, target_ev_limit: int = TARGET_EV_LIMIT) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    state_file = manifest_path(root)
    out: dict[str, Any] = {
        "game_root": str(root),
        "manifest_path": str(state_file),
        "target_ev_limit": int(target_ev_limit),
        "current_ev_limit": None,
        "is_target_applied": False,
        "source_type": "",
        "target_path": "",
        "state": _load_manifest(state_file),
        "latest_backup_path": "",
    }
    try:
        target = _discover_patch_target(root)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
        return out
    current = target.get("current_ev_limit")
    target_path = Path(str(target.get("target_path", ""))) if target.get("target_path") else None
    out["current_ev_limit"] = current
    out["source_type"] = str(target.get("source_type", ""))
    out["target_path"] = str(target_path) if target_path else ""
    out["is_target_applied"] = bool(current is not None and int(current) == int(target_ev_limit))
    if target_path is not None:
        out["latest_backup_path"] = str(_latest_backup_for_target(root, target_path) or "")
    if out["source_type"] == "rxdata":
        out["scripts_path"] = out["target_path"]
        out["source_script_name"] = POKEMON_SCRIPT_NAME
        out["source_script_index"] = int(target.get("entry_index", -1))
    return out


def apply_ev_patch(game_root: Path | str, target_ev_limit: int = TARGET_EV_LIMIT) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    state_file = manifest_path(root)
    target_info = _discover_patch_target(root)
    target_path = Path(str(target_info.get("target_path", "")))
    source_type = str(target_info.get("source_type", ""))
    if not target_path.exists():
        raise FileNotFoundError(f"Missing patch target file: {target_path}")
    old_limit = target_info.get("current_ev_limit")
    if old_limit is None:
        raise ValueError("Could not parse EV_LIMIT assignment in discovered patch target.")

    target = int(target_ev_limit)
    stamp = _now_stamp()
    changed_entries: list[dict[str, Any]] = []
    target_backup_path = ""
    quarantined_backups: list[dict[str, str]] = []

    if source_type == "rb_file":
        quarantined_backups = _quarantine_legacy_script_backups(root)

    if old_limit != target:
        backup = _copy_to_backup(root, target_path, kind="pre-ev-unlock", stamp=stamp)
        target_backup_path = str(backup)
        before_hash = _sha256_file(target_path)
        patched_source, count = _patch_ev_limit_source(str(target_info.get("source_text", "")), target)
        if count != 1:
            raise RuntimeError("EV patch failed: could not update EV_LIMIT assignment.")
        try:
            if source_type == "rxdata":
                scripts_obj = target_info["scripts_obj"]
                idx = int(target_info["entry_index"])
                pokemon_entry = target_info["entry"]
                encoding = str(target_info.get("source_encoding", "utf-8"))
                pokemon_entry[2] = _encode_script_source(patched_source, encoding)
                scripts_obj[idx] = pokemon_entry
                _write_scripts_object(target_path, scripts_obj)
            elif source_type == "rb_file":
                encoding = str(target_info.get("source_encoding", "utf-8"))
                _write_text_with_encoding(target_path, patched_source, encoding)
            else:
                raise RuntimeError(f"Unsupported patch source type: {source_type}")
        except Exception:
            shutil.copy2(backup, target_path)
            raise
        after_hash = _sha256_file(target_path)
        changed_entries.append(
            {
                "kind": "ev_limit",
                "path": str(target_path),
                "backup_path": str(backup),
                "before_sha256": before_hash,
                "after_sha256": after_hash,
            }
        )

    if source_type == "rb_file":
        try:
            guard_changes = _apply_rb_ev_guard_patches(root, stamp)
            changed_entries.extend(guard_changes)
        except Exception:
            _restore_patched_files(changed_entries)
            raise

    if not changed_entries and not quarantined_backups:
        status = inspect_patch_status(root, target_ev_limit=target)
        status["status"] = "already_patched"
        status["changed"] = False
        return status

    if not changed_entries and quarantined_backups:
        status = inspect_patch_status(root, target_ev_limit=target)
        status["status"] = "cleaned_backups"
        status["changed"] = True
        status["quarantined_legacy_backup_count"] = int(len(quarantined_backups))
        status["quarantined_legacy_backups"] = quarantined_backups
        return status

    status = inspect_patch_status(root, target_ev_limit=target)
    verified_limit = int(status.get("current_ev_limit") or -1)
    verified_target = Path(str(status.get("target_path", "") or "")).resolve()
    if verified_limit != target or verified_target != target_path.resolve():
        _restore_patched_files(changed_entries)
        raise RuntimeError("Patch verification failed; restored original file.")
    backup_for_manifest = target_backup_path
    if not backup_for_manifest and changed_entries:
        backup_for_manifest = str(changed_entries[0].get("backup_path", "") or "")
    manifest = {
        "version": MANIFEST_VERSION,
        "active": True,
        "applied_at": _now_iso(),
        "source_type": source_type,
        "target_path": str(target_path),
        "backup_path": backup_for_manifest,
        "from_ev_limit": int(old_limit),
        "to_ev_limit": int(target),
        "patched_files": changed_entries,
        "quarantined_legacy_backups": quarantined_backups,
    }
    _save_manifest(state_file, manifest)
    status["status"] = "patched"
    status["changed"] = True
    status["backup_path"] = backup_for_manifest
    status["patched_file_count"] = int(len(changed_entries))
    status["quarantined_legacy_backup_count"] = int(len(quarantined_backups))
    return status


def rollback_ev_patch(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    state_file = manifest_path(root)
    state = _load_manifest(state_file) or {}
    patched_files_state = state.get("patched_files")
    if isinstance(patched_files_state, list) and patched_files_state:
        rollback_stamp = _now_stamp()
        restored_paths: list[str] = []
        rollback_snapshots: list[str] = []
        for entry in patched_files_state:
            if not isinstance(entry, dict):
                continue
            path_text = str(entry.get("path", "") or "").strip()
            backup_text = str(entry.get("backup_path", "") or "").strip()
            if not path_text or not backup_text:
                continue
            target_path = Path(path_text).expanduser().resolve()
            source_backup = _resolve_existing_backup_path(root, backup_text)
            if not target_path.exists() or not source_backup.exists():
                continue
            rollback_backup = _copy_to_backup(root, target_path, kind="pre-ev-rollback", stamp=rollback_stamp)
            shutil.copy2(source_backup, target_path)
            restored_paths.append(str(target_path))
            rollback_snapshots.append(str(rollback_backup))
        if not restored_paths:
            raise FileNotFoundError("No rollback backup found for patched files in manifest.")
        current_status = inspect_patch_status(root)
        state.update(
            {
                "version": MANIFEST_VERSION,
                "active": False,
                "rolled_back_at": _now_iso(),
                "restored_files": restored_paths,
                "rollback_backup_paths": rollback_snapshots,
                "current_ev_limit_after_rollback": current_status.get("current_ev_limit"),
            }
        )
        _save_manifest(state_file, state)
        current_status["status"] = "rolled_back"
        current_status["changed"] = True
        current_status["restored_files"] = restored_paths
        current_status["rollback_backup_paths"] = rollback_snapshots
        return current_status

    state_target = str(state.get("target_path", "")).strip()
    if state_target:
        target_path = Path(state_target).expanduser().resolve()
    else:
        discovered = _discover_patch_target(root)
        target_path = Path(str(discovered.get("target_path", ""))).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"Missing file: {target_path}")

    candidates: list[Path] = []
    state_backup = str(state.get("backup_path", "")).strip()
    if state_backup:
        candidates.append(_resolve_existing_backup_path(root, state_backup))
    latest = _latest_backup_for_target(root, target_path)
    if latest is not None:
        candidates.append(latest)
    dedup: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(path)
    source_backup = next((p for p in dedup if p.exists() and p.is_file()), None)
    if source_backup is None:
        raise FileNotFoundError(
            f"No rollback backup found for target: {target_path.name}"
        )

    rollback_backup = _copy_to_backup(root, target_path, kind="pre-ev-rollback", stamp=_now_stamp())
    shutil.copy2(source_backup, target_path)
    current_status = inspect_patch_status(root)

    state.update(
        {
            "version": MANIFEST_VERSION,
            "active": False,
            "rolled_back_at": _now_iso(),
            "target_path": str(target_path),
            "restored_from_backup": str(source_backup),
            "rollback_backup_path": str(rollback_backup),
            "current_ev_limit_after_rollback": current_status.get("current_ev_limit"),
        }
    )
    _save_manifest(state_file, state)
    current_status["status"] = "rolled_back"
    current_status["changed"] = True
    current_status["restored_from_backup"] = str(source_backup)
    current_status["rollback_backup_path"] = str(rollback_backup)
    return current_status
