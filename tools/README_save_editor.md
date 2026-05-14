# Pokemon Indigo Save Editor

Tool file: `tools/pokemon_indigo_save_editor.py`
GUI app: `tools/pokemon_indigo_save_editor_gui.py`
Mapper/Probe: `tools/pokemon_indigo_probe_mapper.py`

## Install dependency

```powershell
python -m pip install rubymarshal
```

## Quick start

List saves found in `%APPDATA%\Pokemon Anil`:

```powershell
python tools/pokemon_indigo_save_editor.py saves
```

Validate save integrity:

```powershell
python tools/pokemon_indigo_save_editor.py validate
```

Repair save from latest valid backup (auto-picks newest good `*.preedit-*.bak`):

```powershell
python tools/pokemon_indigo_save_editor.py repair
```

Show summary of newest save:

```powershell
python tools/pokemon_indigo_save_editor.py summary
```

Show summary of a specific save:

```powershell
python tools/pokemon_indigo_save_editor.py summary --save "C:\Users\Admin\AppData\Roaming\Pokemon Anil\Partida 1.rxdata"
```

## GUI app (recommended)

Run:

```powershell
python tools/pokemon_indigo_save_editor_gui.py
```

GUI features included:
- Load/browse save files.
- Trainer editor (name, money, BP, badges, etc.).
- Party editor (species, level, EXP, HP, nature, item, ability, moves).
- Bag editor (add/update/remove items per pocket).
- Bag pocket selector now shows labeled pockets (from game settings), not just numeric indexes.
- Bag item dropdown is filtered to items valid for the selected pocket.
- Switch/Variable editor.
- Advanced path editor (`get/set/list`) for deep manual edits.
- Legality tab: checks unknown IDs (species/move/item/ability) + basic level/PP/structure issues.
- Item/species/move/ability fields accept either internal ID or common display names (e.g. `Full Restore`).
- Startup/load/save now validates an adapter profile lock (`tools/editor_profile.lock.json`).
- Use `Map Game Data` button in GUI (or CLI below) to create/update the profile lock.

## Mapper/Probe (for game-save mapping lock)

Create/refresh profile lock:

```powershell
python tools/pokemon_indigo_probe_mapper.py --save "C:\Users\Admin\AppData\Roaming\Pokemon Anil\Partida 1.rxdata"
```

Verify existing profile lock:

```powershell
python tools/pokemon_indigo_probe_mapper.py --verify --save "C:\Users\Admin\AppData\Roaming\Pokemon Anil\Partida 1.rxdata"
```

You can also run remap/verify directly from the GUI entry script (same flow used in EXE):

```powershell
python tools/pokemon_indigo_save_editor_gui.py --probe --save "C:\Users\Admin\AppData\Roaming\Pokemon Anil\Partida 1.rxdata"
python tools/pokemon_indigo_save_editor_gui.py --verify-profile --save "C:\Users\Admin\AppData\Roaming\Pokemon Anil\Partida 1.rxdata"
```

Startup check without opening window:

```powershell
python tools/pokemon_indigo_save_editor_gui.py --self-test
```

## Build EXE (no Python needed on target machine)

Build one-file EXE:

```powershell
tools\build_save_editor_exe.bat
```

Output:
- `tools\PokemonIndigoSaveEditor.exe` (ready to share)
- `tools\dist\PokemonIndigoSaveEditor.exe`

Remap is already integrated in the same EXE UI:
- Open `tools\PokemonIndigoSaveEditor.exe`
- Click `Map Game Data` on the top bar.

EV patch (backup + rollback) is also integrated in GUI:
- `Apply EV Patch`: patches `Data/Scripts.rxdata` (`EV_LIMIT` -> `1512`), creates backup file:
  - `Data/Scripts.rxdata.pre-ev-unlock-YYYYMMDD-HHMMSS.bak`
- `Rollback EV Patch`: restores `Scripts.rxdata` from backup.
- After apply/rollback, run `Map Game Data` again (game data fingerprint changed).

## Build Installer (PA1 - install outside game folder)

Prerequisite:
- Inno Setup 6 (`ISCC.exe`) installed.

Build setup:

```powershell
tools\installer\build_installer.bat
```

Output:
- `tools\installer\dist\PokemonSaveEditor_Setup.exe`

Installer flow:
1. Choose install location for the editor app (separate from game folder).
2. Choose game root folder (must contain `PBS` and `Data`).
3. Choose save file for first-time mapping.
4. Installer runs first-time remap automatically, then launches the app.

Notes:
- The same setup can be used for multiple similar games, but each install/run must point to a valid game root + matching save.
- You can change game root later from the app button `Game Folder...`, then run `Map Game Data` again.

One-command release build (EXE + Setup):

```powershell
tools\build_release.bat
```

## Read values

Read money:

```powershell
python tools/pokemon_indigo_save_editor.py get --path player.@money
```

Read first party Pokemon level:

```powershell
python tools/pokemon_indigo_save_editor.py get --path player.@party.0.@level
```

List available fields under player:

```powershell
python tools/pokemon_indigo_save_editor.py list --path player
```

## Edit values

Set money:

```powershell
python tools/pokemon_indigo_save_editor.py set --path player.@money --value 999999 --type int
```

Set battle points:

```powershell
python tools/pokemon_indigo_save_editor.py set --path player.@battle_points --value 9999 --type int
```

Set first party Pokemon level:

```powershell
python tools/pokemon_indigo_save_editor.py set --path player.@party.0.@level --value 100 --type int
```

Set species (symbol type):

```powershell
python tools/pokemon_indigo_save_editor.py set --path player.@party.0.@species --value CHARIZARD --type symbol
```

## Notes

- Every `set` creates a backup next to the save (`*.preedit-YYYYMMDD-HHMMSS.bak`) unless `--no-backup` is used.
- `set` also runs a sanity check after writing. If check fails, file is automatically restored from backup.
- GUI Save does the same sanity check + automatic rollback on failure.
- Path syntax supports:
  - dot segments (`player.@money`)
  - list indexes (`player.@party.0`)
  - bracket indexes (`player.@party[0].@level`)
- If a value type is unclear, use `--type auto` (default) or set an explicit type.
