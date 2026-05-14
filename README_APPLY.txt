Dragon Soul selected-effects fix patch
======================================

Copy the files in this zip into your game/tool root, preserving paths.

Important:
- Copying these source/data files is not enough by itself.
- Open the save editor and re-run Apply Custom Item / regenerate the Custom Item runtime patch for DRAGONSOUL so Data/Scripts.rxdata gets a new ZZ_CustomItemPatch.
- Then retest in battle.

Target test case:
- Items: Leftovers, Big Root
- Moves: Draining Kiss, Fake Out, Nasty Plot, Swords Dance
- Ability: Speed Boost

Expected behavior after re-apply:
1. Leftovers: end-of-round HP heal.
2. Draining Kiss + Big Root: drain heal should be ~75% * 1.3 = 97.5% of damage dealt.
3. Swords Dance: Attack +2 once per battle after using a move.
4. Nasty Plot: Special Attack +2 once per battle after using a move.
5. Speed Boost: Speed +1 at end of round.
6. Fake Out: remains on legacy bridge because user reported it was already working.

Compile check run in this environment:
python3 -S -m py_compile tools/custom_item/patcher.py tools/custom_item/effect_pool.py tools/custom_item/hook_compiler.py

Full Windows EXE rebuild was not run here because the uploaded package does not include the full Windows build context.
