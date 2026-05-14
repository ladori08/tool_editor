# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['pokemon_indigo_save_editor_gui.py'],
    pathex=['tools'],
    binaries=[],
    datas=[],
    hiddenimports=['pokemon_indigo_probe_mapper', 'pokemon_indigo_game_data', 'pokemon_indigo_ev_patcher', 'pokemon_indigo_patch_capability', 'pokemon_indigo_custom_item_patcher'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PokemonIndigoSaveEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:\\Games\\Rom games\\Pokemon Indigo 4.0.2 EN-5\\tools\\assets\\masterball.ico'],
)
