#!/usr/bin/env python
"""CLI entry for one-shot custom-item environment bootstrap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from custom_item import controller


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap custom-item patch environment for a game root.")
    parser.add_argument("--game-root", required=True, help="Game root directory.")
    parser.add_argument("--save", default="", help="Optional save file (.rxdata) for profile lock mapping.")
    parser.add_argument("--profile", default="", help="Optional output profile lock path.")
    parser.add_argument("--report", default="", help="Optional JSON report output path.")
    args = parser.parse_args()

    game_root = Path(args.game_root).expanduser().resolve()
    save_path = Path(args.save).expanduser().resolve() if str(args.save).strip() else None
    profile_path = Path(args.profile).expanduser().resolve() if str(args.profile).strip() else None

    result = controller.bootstrap_custom_item_environment(
        game_root=game_root,
        save_path=save_path,
        profile_path=profile_path,
        run_runtime_autofill=True,
    )

    report_path = Path(args.report).expanduser().resolve() if str(args.report).strip() else None
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report={report_path}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

