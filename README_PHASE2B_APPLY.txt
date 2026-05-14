Custom Item Phase 2B patch

What changed:
1. Newly applied custom items are now merged into live item dropdowns without restarting the tool.
   Affected dropdowns:
   - Party held item
   - Team Builder held item
   - Team card inline item
   - Damage tab item selectors
   - Bag item selector, based on pocket

2. Phase 2B ability pool expansion added safe/medium ability-style effects:
   - Swift Swim, Sand Rush, Slush Rush
   - Rain Dish, Ice Body, Poison Heal
   - Huge Power, Pure Power, Technician, Adaptability, Guts (partial approximations)
   - Filter, Solid Rock, Thick Fat Fire/Ice branches (partial)
   - Advanced markers: Intimidate, Moxie, Magic Guard, Wonder Guard, Prankster

Apply flow:
1. Copy this patch into the project/game root, preserving paths.
2. Rebuild EXE or run the GUI from source.
3. Open the tool.
4. Apply Custom Item.
5. Newly-applied custom items should appear in item assignment dropdowns immediately without restarting.

Verification run here:
python3 -S -m py_compile tools/pokemon_indigo_save_editor_gui.py tools/custom_item/patcher.py tools/custom_item/effect_pool.py tools/custom_item/hook_compiler.py

Full Windows EXE rebuild was not run here because this environment does not have your full Windows build/runtime context.
