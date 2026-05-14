#!/usr/bin/env python
"""One-shot bootstrap/controller for Custom Item compatibility workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import patcher

try:
    import pokemon_indigo_patch_capability as patch_capability
except Exception:  # noqa: BLE001
    patch_capability = None

try:
    import pokemon_indigo_probe_mapper as probe_mapper
except Exception:  # noqa: BLE001
    probe_mapper = None


def _resolve_path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def bootstrap_custom_item_environment(
    game_root: Path | str,
    save_path: Path | str | None = None,
    profile_path: Path | str | None = None,
    run_runtime_autofill: bool = True,
) -> dict[str, Any]:
    root = _resolve_path(game_root)
    out: dict[str, Any] = {
        "game_root": str(root),
        "warnings": [],
    }

    workspace = patcher.ensure_custom_item_workspace(root)
    out["custom_item_workspace"] = workspace

    cap_profile: dict[str, Any] | None = None
    if patch_capability is None:
        out["warnings"].append("patch_capability module is unavailable.")
    else:
        cap_profile = patch_capability.probe_patch_capability(root)
        out["patch_capability"] = cap_profile
        out["patch_adapter"] = patch_capability.rebuild_patch_adapter(root, capability_data=cap_profile)

    if save_path is not None:
        save_file = _resolve_path(save_path)
        if not save_file.exists():
            raise FileNotFoundError(f"Save file not found: {save_file}")
        if probe_mapper is None:
            out["warnings"].append("probe_mapper module is unavailable; profile lock was not updated.")
        else:
            target_profile = (
                _resolve_path(profile_path)
                if profile_path is not None
                else probe_mapper.default_profile_path(root)
            )
            out["profile_lock"] = probe_mapper.run_probe(
                game_root=root,
                save_path=save_file,
                profile_path=target_profile,
            )
            out["profile_path"] = str(target_profile)
            out["save_path"] = str(save_file)

    if run_runtime_autofill:
        before = patcher.analyze_effect_template_coverage(root)
        autofill = patcher.autofill_effect_template_catalog(
            root,
            persist=True,
            include_script_ability_scan=True,
        )
        after = autofill.get("coverage", {})
        out["runtime_mapping"] = {
            "before": before,
            "autofill": autofill,
            "after": after,
        }

    levels = ((cap_profile or {}).get("patch_levels", {}) if isinstance(cap_profile, dict) else {})
    out["ready_for_custom_item_patch"] = bool(
        levels.get("A_metadata_item_data")
        and levels.get("B_clone_existing_effects")
        and levels.get("C_ruby_injection")
    )
    return out

