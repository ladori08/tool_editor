#!/usr/bin/env python
"""Analyze and autofill runtime effect mappings for custom-item patcher."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from . import patcher as custom_item_patcher
except Exception:  # noqa: BLE001
    import sys

    parent = Path(__file__).resolve().parents[1]
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    from custom_item import patcher as custom_item_patcher


def _resolve_game_root(raw: str) -> Path:
    value = str(raw or ".").strip()
    path = Path(value).expanduser().resolve()
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Scan game data + scripts to detect missing runtime mappings and "
            "autofill supported template mappings."
        )
    )
    parser.add_argument(
        "--game-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Game root directory (default: parent of this tools folder).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and propose changes without writing custom_item_effect_templates.json.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional output JSON report path.",
    )
    args = parser.parse_args()

    game_root = _resolve_game_root(args.game_root)
    before = custom_item_patcher.analyze_effect_template_coverage(game_root)
    autofill = custom_item_patcher.autofill_effect_template_catalog(
        game_root,
        persist=not args.dry_run,
        include_script_ability_scan=True,
    )
    after = autofill.get("coverage", {})

    payload = {
        "game_root": str(game_root),
        "dry_run": bool(args.dry_run),
        "before": before,
        "autofill": autofill,
        "after": after,
    }

    report_path = Path(str(args.report or "").strip()).expanduser() if args.report else None
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"game_root={game_root}")
    print(f"catalog={autofill.get('catalog_path', '')}")
    print(
        "ability_runtime_added="
        f"{autofill.get('added_ability_runtime_count', 0)} "
        f"(runtime_scan={before.get('runtime_ability_scan_count', 0)} "
        f"missing_before={before.get('runtime_ability_missing_count', 0)} "
        f"missing_after={after.get('runtime_ability_missing_count', 0)})"
    )
    print(
        "move_function_templates_added="
        f"{autofill.get('added_move_function_template_count', 0)}"
    )
    print(
        "coverage_ability="
        f"{after.get('ability_supported', 0)}/{after.get('ability_total', 0)} "
        "coverage_move="
        f"{after.get('move_supported', 0)}/{after.get('move_total', 0)}"
    )
    print(
        "runtime_move_missing="
        f"{after.get('runtime_move_missing_count', 0)} "
        "missing_function_codes="
        f"{after.get('runtime_move_missing_function_code_count', 0)}"
    )
    if report_path:
        print(f"report={report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
