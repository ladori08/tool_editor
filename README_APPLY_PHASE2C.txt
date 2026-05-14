Custom Item Effect Engine - Phase 2C Patch

Contents:
- tools/custom_item/patcher.py
- tools/custom_item/effect_pool.py
- tools/custom_item/hook_compiler.py
- tools/custom_item/__init__.py
- tools/custom_item/data/custom_effect_pool.json
- tools/custom_item/data/custom_item_manifest.json
- WORKLOG.md
- TASKS.md

After copying into the project/game root:
1. Rebuild PokemonIndigoSaveEditor.exe or run the GUI from Python source.
2. Open the tool.
3. Select/apply the target custom item again.
4. Confirm Data/Scripts.rxdata timestamp changes.
5. Test in game.

Compile check run in this environment:
python3 -m py_compile patcher.py effect_pool.py hook_compiler.py pokemon_indigo_save_editor_gui.py

Full Windows EXE rebuild was not run here because this environment does not have the full Windows build/runtime context.
