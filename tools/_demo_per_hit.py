#!/usr/bin/env python3
import json
import os
import pprint
import sys

# Ensure workspace root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import importlib.util

# Load effect_pool and hook_compiler directly from file to avoid importing the
# package-level __init__ which pulls in heavy optional deps like rubymarshal.
def _load_mod(name: str, rel_path: str):
    base = os.path.dirname(__file__)
    path = os.path.join(base, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

effect_pool = _load_mod("demo_effect_pool", os.path.join("custom_item", "effect_pool.py"))
hook_compiler = _load_mod("demo_hook_compiler", os.path.join("custom_item", "hook_compiler.py"))

authoring = {
    "id": "demo_per_hit",
    "name": "Demo Per-Hit Raise",
    "description": "Demo effect: raise ATTACK by 1 per hit (multi-hit moves)",
    "category": "Stat",
    "effect_type": "change_user_stat_stage",
    "target": "holder",
    "conditions": {"move_type": "", "require_super_effective": False},
    "values": {
        "stats": ["ATTACK"],
        "stages": "1",
        "direction": "Raise",
        "trigger_timing": "After holder uses a move",
        "once_per_battle": True,
        "per_hit": True,
    },
}

pprint.pprint({"authoring": authoring})
compiled, errors = effect_pool.compile_custom_effect_authoring(authoring)
print("\n=== COMPILED ===")
if compiled is None:
    print("Compilation failed with errors:")
    pprint.pprint(errors)
    sys.exit(2)
else:
    pprint.pprint(compiled)

# Write compiled JSON for inspection
out_json = os.path.join(os.path.dirname(__file__), "_demo_per_hit_compiled.json")
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(compiled, f, ensure_ascii=False, indent=2, sort_keys=True)
print(f"Wrote compiled JSON to: {out_json}")

# Generate Ruby lines using hook_compiler
item_pool = {"DEMO_ITEM": [compiled]}
ruby_lines = hook_compiler.compile_pool_effects(item_pool)
out_rb = os.path.join(os.path.dirname(__file__), "_demo_per_hit_output.rb")
with open(out_rb, "w", encoding="utf-8") as f:
    f.write("\n".join(ruby_lines))
print(f"Wrote Ruby output to: {out_rb}")

print("\n=== RUBY PREVIEW (first 200 lines) ===")
for i, line in enumerate(ruby_lines[:200]):
    print(line)

print("\nDemo script complete.")
