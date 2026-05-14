#!/usr/bin/env python
"""Pokemon Indigo Save Editor GUI (PKHeX-like lite).

Desktop editor for Pokemon Indigo / Pokemon Anil save files.
Uses the cycle-aware Ruby Marshal core from pokemon_indigo_save_editor.py.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from fractions import Fraction
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk


def _runtime_tools_dir() -> Path:
    # In PyInstaller-frozen mode, __file__ points to bundle internals; use exe directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _looks_like_game_root(path: Path) -> bool:
    p = Path(path).resolve()
    if not (p / "Data").is_dir():
        return False
    if (p / "PBS").is_dir():
        return True
    if (p / "Game.exe").is_file() or (p / "Game.ini").is_file() or (p / "mkxp.json").is_file():
        return True
    if (p / "Graphics").is_dir() and (p / "Audio").is_dir():
        return True
    return False


def _detect_default_game_root(tools_dir: Path) -> Path:
    env_root = os.environ.get("POKEMON_EDITOR_GAME_ROOT", "").strip()
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        if _looks_like_game_root(env_path):
            return env_path
    candidates: list[Path] = []
    if str(tools_dir.name).casefold() == "tools":
        candidates.append(tools_dir.parent)
    candidates.append(tools_dir)
    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if _looks_like_game_root(candidate):
            return candidate
    return tools_dir.parent if str(tools_dir.name).casefold() == "tools" else tools_dir


HERE = _runtime_tools_dir()
DEFAULT_GAME_ROOT = _detect_default_game_root(HERE)
APP_CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "PokemonSaveEditor"
APP_CONFIG_PATH = APP_CONFIG_DIR / "editor_settings.json"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _load_app_settings() -> dict[str, Any]:
    try:
        if APP_CONFIG_PATH.exists():
            with APP_CONFIG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_app_settings(data: dict[str, Any]):
    try:
        APP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with APP_CONFIG_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

import pokemon_indigo_save_editor as core  # noqa: E402
from pokemon_indigo_game_data import GameCatalogs, parse_pbs_sections  # noqa: E402
try:
    import pokemon_indigo_probe_mapper as probe_mapper  # noqa: E402
except Exception:  # noqa: BLE001
    probe_mapper = None
try:
    import pokemon_indigo_ev_patcher as ev_patcher  # noqa: E402
except Exception:  # noqa: BLE001
    ev_patcher = None
try:
    import pokemon_indigo_patch_capability as patch_capability  # noqa: E402
except Exception:  # noqa: BLE001
    patch_capability = None
try:
    import battle_overlay_patcher  # noqa: E402
except Exception:  # noqa: BLE001
    battle_overlay_patcher = None
try:
    from custom_item import patcher as custom_item_patcher  # noqa: E402
except Exception:  # noqa: BLE001
    try:
        import pokemon_indigo_custom_item_patcher as custom_item_patcher  # noqa: E402
    except Exception:  # noqa: BLE001
        custom_item_patcher = None
try:
    from custom_item import controller as custom_item_controller  # noqa: E402
except Exception:  # noqa: BLE001
    custom_item_controller = None
try:
    from custom_item import effect_pool as custom_item_effect_pool  # noqa: E402
    custom_item_load_effect_pool = custom_item_effect_pool.load_effect_pool_for_game
except Exception:  # noqa: BLE001
    custom_item_effect_pool = None
    custom_item_load_effect_pool = None

EN_POCKET_NAMES = {
    0: "Unused",
    1: "Items",
    2: "Medicine",
    3: "Poke Balls",
    4: "TMs & HMs",
    5: "Berries",
    6: "Mega Stones",
    7: "Battle Items",
    8: "Key Items",
}

DEX_CATEGORY_LABEL_TO_KEY = {
    "Pokédex": "Species",
    "Moves dex": "Moves",
    "Items dex": "Items",
    "Abilities dex": "Abilities",
    "Natures dex": "Natures",
    "Types dex": "Types",
}
DEX_CATEGORY_KEY_TO_LABEL = {value: key for key, value in DEX_CATEGORY_LABEL_TO_KEY.items()}
DEX_CATEGORY_LABELS = list(DEX_CATEGORY_LABEL_TO_KEY.keys())

STAT_ORDER = [
    ("HP", "HP"),
    ("ATTACK", "Atk"),
    ("DEFENSE", "Def"),
    ("SPECIAL_ATTACK", "SpA"),
    ("SPECIAL_DEFENSE", "SpD"),
    ("SPEED", "Spe"),
]
STAT_SHORT_LABELS = {sid: short for sid, short in STAT_ORDER}

TYPE_COLOR_HEX = {
    "NORMAL": "#A8A77A",
    "FIRE": "#EE8130",
    "WATER": "#6390F0",
    "ELECTRIC": "#F7D02C",
    "GRASS": "#7AC74C",
    "ICE": "#96D9D6",
    "FIGHTING": "#C22E28",
    "POISON": "#A33EA1",
    "GROUND": "#E2BF65",
    "FLYING": "#A98FF3",
    "PSYCHIC": "#F95587",
    "BUG": "#A6B91A",
    "ROCK": "#B6A136",
    "GHOST": "#735797",
    "DRAGON": "#6F35FC",
    "DARK": "#705746",
    "STEEL": "#B7B7CE",
    "FAIRY": "#D685AD",
}
TYPE_LIGHT_BG_IDS = {"NORMAL", "ELECTRIC", "GROUND", "ICE", "STEEL", "FAIRY"}
TYPE_SHORT_LABELS = {
    "NORMAL": "NRM",
    "FIRE": "FIR",
    "WATER": "WAT",
    "ELECTRIC": "ELE",
    "GRASS": "GRS",
    "ICE": "ICE",
    "FIGHTING": "FIG",
    "POISON": "PSN",
    "GROUND": "GRD",
    "FLYING": "FLY",
    "PSYCHIC": "PSY",
    "BUG": "BUG",
    "ROCK": "RCK",
    "GHOST": "GST",
    "DRAGON": "DRG",
    "DARK": "DRK",
    "STEEL": "STL",
    "FAIRY": "FRY",
}
TYPE_CHIP_FIXED_WIDTH = 10
TYPE_CHIP_COMPACT_WIDTH = max(4, TYPE_CHIP_FIXED_WIDTH // 2)
LOW_QUALITY_DESC_TOKENS = {"he", "she", "it", "none", "n/a", "na", "null", "undefined"}
PARTY_ICON_CACHE_LIMIT = 1200
PARTY_GRID_ICON_CACHE_LIMIT = 1200
PARTY_PREVIEW_ICON_CACHE_LIMIT = 500
PARTY_ITEM_ICON_CACHE_LIMIT = 900
PARTY_EVO_SCALED_ICON_CACHE_LIMIT = 1500
PC_BOX_SLOT_CAPACITY = 30
PARTY_FIELD_STATUS_OPTIONS: list[tuple[str, str, int]] = [
    ("None", "NONE", 0),
    ("Sleep", "SLEEP", 2),
    ("Poison", "POISON", 0),
    ("Toxic (Bad Poison)", "POISON", 1),
    ("Burn", "BURN", 0),
    ("Paralysis", "PARALYSIS", 0),
    ("Freeze", "FROZEN", 0),
    ("Frostbite", "FROSTBITE", 0),
]
PARTY_FIELD_STATUS_DEFAULT_LABEL = "None"

NATURE_EFFECTS = {
    "LONELY": ("ATTACK", "DEFENSE"),
    "BRAVE": ("ATTACK", "SPEED"),
    "ADAMANT": ("ATTACK", "SPECIAL_ATTACK"),
    "NAUGHTY": ("ATTACK", "SPECIAL_DEFENSE"),
    "BOLD": ("DEFENSE", "ATTACK"),
    "RELAXED": ("DEFENSE", "SPEED"),
    "IMPISH": ("DEFENSE", "SPECIAL_ATTACK"),
    "LAX": ("DEFENSE", "SPECIAL_DEFENSE"),
    "TIMID": ("SPEED", "ATTACK"),
    "HASTY": ("SPEED", "DEFENSE"),
    "JOLLY": ("SPEED", "SPECIAL_ATTACK"),
    "NAIVE": ("SPEED", "SPECIAL_DEFENSE"),
    "MODEST": ("SPECIAL_ATTACK", "ATTACK"),
    "MILD": ("SPECIAL_ATTACK", "DEFENSE"),
    "QUIET": ("SPECIAL_ATTACK", "SPEED"),
    "RASH": ("SPECIAL_ATTACK", "SPECIAL_DEFENSE"),
    "CALM": ("SPECIAL_DEFENSE", "ATTACK"),
    "GENTLE": ("SPECIAL_DEFENSE", "DEFENSE"),
    "SASSY": ("SPECIAL_DEFENSE", "SPEED"),
    "CAREFUL": ("SPECIAL_DEFENSE", "SPECIAL_ATTACK"),
}

MOVE_FUNCTION_EXACT_HINTS = {
    "StartHealUserEachTurn": "Heals user by 1/16 max HP at end of each turn.",
    "StartHealUserEachTurnTrapUserInBattle": "Heals user by 1/16 max HP each turn and traps user in battle.",
    "HealUserHalfOfTotalHP": "Heals user by 1/2 max HP.",
    "HealTargetHalfOfTotalHP": "Heals target by 1/2 max HP.",
    "HealUserAndAlliesQuarterOfTotalHP": "Heals user and allies by 1/4 max HP.",
    "HealUserAndAlliesQuarterOfTotalHPCureStatus": "Heals user and allies by 1/4 max HP and cures status.",
    "HealUserByHalfOfDamageDone": "Recovers HP equal to 1/2 of damage dealt.",
    "HealUserByHalfOfDamageDoneBurnTarget": "Recovers HP equal to 1/2 of damage dealt.",
    "HealUserByThreeQuartersOfDamageDone": "Recovers HP equal to 3/4 of damage dealt.",
    "MaxUserAttackLoseHalfOfTotalHP": "Sets Attack to +6 and costs 1/2 max HP.",
    "UserLosesHalfOfTotalHP": "User loses 1/2 max HP.",
    "UserLosesHalfOfTotalHPExplosive": "User loses 1/2 max HP.",
    "RecoilHalfOfDamageDealt": "User takes recoil equal to 1/2 of damage dealt.",
    "RecoilThirdOfDamageDealt": "User takes recoil equal to 1/3 of damage dealt.",
    "RecoilThirdOfDamageDealtBurnTarget": "User takes recoil equal to 1/3 of damage dealt.",
    "RecoilThirdOfDamageDealtParalyzeTarget": "User takes recoil equal to 1/3 of damage dealt.",
    "RecoilQuarterOfDamageDealt": "User takes recoil equal to 1/4 of damage dealt.",
    "RecoilHalfOfTotalHP": "User takes recoil equal to 1/2 max HP.",
    "FixedDamageHalfTargetHP": "Deals damage equal to 1/2 of target's current HP.",
    "StartLeechSeedTarget": "Leech Seed drains 1/8 max HP from target each turn.",
}

ITEM_NUMERIC_HINTS = {
    "LEFTOVERS": "Heals holder by 1/16 max HP at end of each turn.",
    "BLACKSLUDGE": "Poison-type holders heal 1/16 max HP per turn; other holders lose 1/8 max HP per turn.",
    "LIFEORB": "Moves deal 1.3x damage; user loses 1/10 max HP after a damaging hit.",
    "EVIOLITE": "If holder can still evolve, Defense and Sp. Def are multiplied by 1.5x.",
    "BIGROOT": "Drain/healing-from-damage effects are multiplied by 1.3x.",
    "CHOICEBAND": "Attack is multiplied by 1.5x; holder is locked into the first selected move.",
    "CHOICESPECS": "Sp. Atk is multiplied by 1.5x; holder is locked into the first selected move.",
    "CHOICESCARF": "Speed is multiplied by 1.5x; holder is locked into the first selected move.",
    "EXPERTBELT": "Super-effective moves deal 1.2x damage.",
    "MUSCLEBAND": "Physical move damage is multiplied by 1.1x.",
    "WISEGLASSES": "Special move damage is multiplied by 1.1x.",
    "ASSAULTVEST": "Sp. Def is multiplied by 1.5x; status moves cannot be selected.",
    "SHELLBELL": "Holder heals by 1/8 of damage dealt.",
    "ROCKYHELMET": "Contact attackers lose 1/6 max HP.",
    "FOCUSSASH": "From full HP, holder survives an otherwise fatal hit at 1 HP.",
}

ABILITY_NUMERIC_HINTS = {
    "INTIMIDATE": "On switch-in, lowers adjacent foes' Attack by 1 stage.",
    "STEADFAST": "If flinched, raises user's Speed by 1 stage.",
    "JUSTIFIED": "When hit by a Dark-type move, raises user's Attack by 1 stage.",
    "SOLARPOWER": "In sun, Sp. Atk is multiplied by 1.5x and user loses 1/8 max HP each turn.",
    "THICKFAT": "Fire- and Ice-type damage taken is halved (0.5x).",
    "HUGEPOWER": "Attack is doubled (2.0x).",
    "PUREPOWER": "Attack is doubled (2.0x).",
    "GUTS": "With a major status, Attack is multiplied by 1.5x.",
    "MARVELSCALE": "With a major status, Defense is multiplied by 1.5x.",
    "SWIFTSWIM": "In rain, Speed is doubled (2.0x).",
    "CHLOROPHYLL": "In sun, Speed is doubled (2.0x).",
    "SANDRUSH": "In sandstorm, Speed is doubled (2.0x).",
    "SLUSHRUSH": "In snow/hail, Speed is doubled (2.0x).",
    "SPEEDBOOST": "At end of each turn, raises Speed by 1 stage.",
    "QUICKFEET": "With a major status, Speed is multiplied by 1.5x.",
    "LIGHTNINGROD": "Draws Electric moves and grants +1 Sp. Atk when triggered.",
}

FUNCTION_STAT_TOKEN_LABELS = (
    ("CriticalHitRate", "critical-hit rate"),
    ("MainStats", "all main stats"),
    ("SpAtk", "Sp. Atk"),
    ("SpDef", "Sp. Def"),
    ("Attack", "Attack"),
    ("Defense", "Defense"),
    ("Accuracy", "Accuracy"),
    ("Evasion", "Evasion"),
    ("Speed", "Speed"),
    ("Atk", "Attack"),
    ("Def", "Defense"),
    ("Spd", "Speed"),
    ("Acc", "Accuracy"),
)


def symbol_name(value: Any) -> str:
    if isinstance(value, core.Symbol):
        return value.name
    if isinstance(value, core.RubyString):
        return str(value)
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="replace")
    return str(value)


def to_symbol_or_none(text: str):
    clean = text.strip()
    if not clean:
        return None
    return core.Symbol(clean.lstrip(":"))


def parse_int(text: str, field_name: str) -> int:
    try:
        return int(text.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def extract_internal_id(text: str) -> str:
    raw = text.strip()
    if "|" in raw:
        raw = raw.split("|", 1)[0].strip()
    return raw


class SaveEditorApp:
    def __init__(self, root: tk.Tk, initial_game_root: Path | None = None):
        self.root = root
        self._base_window_title = "Pokemon Indigo Save Editor"
        self.root.title(self._base_window_title)
        self.root.geometry("1180x760")
        self.root.minsize(980, 660)

        self.app_settings: dict[str, Any] = _load_app_settings()
        self.game_root = self._resolve_initial_game_root(initial_game_root)
        self.save_path: Path | None = None
        self.save_data: Any = None
        self.modified = False
        self.status_var = tk.StringVar(value="Ready.")
        self._status_title_timeout_ms = 20_000
        self._status_title_visible_until = 0.0
        self._status_title_poll_after_id: str | None = None
        self.advanced_mode_var = tk.BooleanVar(value=bool(self.app_settings.get("advanced_mode", False)))
        self.catalogs: GameCatalogs | None = None
        self.catalog_error: str | None = None
        self.profile_lock_path = (
            probe_mapper.default_profile_path(self.game_root)
            if probe_mapper is not None
            else (self.game_root / "tools" / "editor_profile.lock.json")
        )
        self.profile_lock_data: dict[str, Any] | None = None
        self.profile_lock_warning: str | None = None
        self._translated_desc_cache: dict[str, str] = {}
        self._translated_desc_miss_cache: set[str] = set()
        self._resolved_entity_desc_cache: dict[tuple[str, str, str, tuple[str, ...]], tuple[str, tuple[str, ...]]] = {}
        self._desc_widget_context: dict[str, tuple[str, str, int | None]] = {}
        self._desc_lock: dict[str, tuple[str, int | None] | None] = {"party": None, "bag": None}
        self._dex_type_chart_defense: dict[str, dict[str, float]] | None = None
        self._dex_type_order: list[str] = []
        self._dex_spawn_index: dict[str, list[dict[str, Any]]] | None = None
        self._dex_item_shop_index: dict[str, list[dict[str, Any]]] | None = None
        self._dex_move_tm_map: dict[str, list[str]] | None = None
        self._dex_wheel_bound_widgets: set[str] = set()
        self._dex_global_wheel_enabled = False
        self._dex_tooltip_window: tk.Toplevel | None = None
        self._dex_tooltip_label: tk.Label | None = None
        self._dex_tooltip_move_cache: dict[str, str] = {}
        self._dex_tooltip_ability_cache: dict[str, str] = {}
        self._dex_wheel_accum_steps = 0
        self._dex_wheel_flush_job: str | None = None
        self._dex_wheel_canvas: tk.Canvas | None = None
        self._party_tooltip_window: tk.Toplevel | None = None
        self._party_tooltip_label: tk.Label | None = None
        self._party_last_description_text = ""
        self._party_last_description_key: tuple[str, int | None, str, int] | None = None
        self._party_wheel_bound_widgets: set[str] = set()
        self._dex_map_names: dict[int, str] = {}
        self._dex_detail_sections: list[ttk.LabelFrame] = []
        self._dex_split_max_left_width = 0
        self._dex_split_min_left_width = 180
        self._dex_split_initialized = False
        self._party_evo_rendering = False
        self._party_evo_update_scheduled = False
        self._party_evo_last_render_key: tuple[str, int, int] | None = None
        self._team_slots: list[dict[str, Any]] = []
        self._team_selected_slot = 0
        self._team_syncing = False
        self._team_layout_mode = ""
        self._team_cards_cols = 0
        self._team_editor_single_col = False
        self._team_type_chart_popup: tk.Toplevel | None = None
        self._team_type_chart_body: ttk.Frame | None = None
        self._team_type_chart_canvas: tk.Canvas | None = None
        self._team_avatar_context_menu: tk.Menu | None = None
        self._team_box_picker_popup: tk.Toplevel | None = None
        self._team_box_picker_icon_refs: list[tk.PhotoImage] = []
        self._damage_state_by_side: dict[str, dict[str, Any]] = {}
        self._damage_icon_cache: dict[str, tk.PhotoImage] = {}
        self._damage_preview_update_job: str | None = None
        self._damage_calc_update_job: str | None = None
        self._damage_events_bound = False
        self._damage_syncing = False
        self._damage_last_preview_size: tuple[int, int] = (0, 0)
        self._app_icon_image: tk.PhotoImage | None = None
        self._custom_item_tab_visible = False
        self._custom_item_wheel_bound_widgets: set[str] = set()
        self._custom_item_label_to_id: dict[str, str] = {}
        self._custom_item_manifest: dict[str, Any] = {}
        self._custom_baked_item_report: dict[str, Any] = {}
        self._custom_orphan_baked_item_ids: set[str] = set()
        self._custom_base_dropdown_blocked_ids: set[str] = set()
        self._custom_item_pending_icon_source: Path | None = None
        self._custom_item_preview_image: tk.PhotoImage | None = None
        self._custom_item_icon_target_size: tuple[int, int] = (48, 48)
        self._custom_effect_combo_kind_by_name: dict[str, str] = {}
        self._custom_effect_tooltip_window: tk.Toplevel | None = None
        self._custom_effect_tooltip_label: tk.Label | None = None
        self._custom_effect_desc_cache: dict[tuple[str, str], str] = {}
        self._combo_tooltip_context_by_name: dict[str, dict[str, Any]] = {}
        self._combo_tooltip_poll_after_id: str | None = None
        self._combo_tooltip_poll_combo: ttk.Combobox | None = None
        self._combo_tooltip_last_key: tuple[str, str] | None = None
        self._combo_popdown_tcl_tooltip_bound: set[tuple[str, str]] = set()
        self._combo_popdown_tcl_tooltip_scripts: dict[tuple[str, str], tuple[str, str]] = {}
        self._combo_popdown_tcl_tooltip_commands: list[str] = []
        self._combo_tooltip_popup: tk.Toplevel | None = None
        self._combo_tooltip_popup_combo: ttk.Combobox | None = None
        self._combo_tooltip_popup_listbox: tk.Listbox | None = None
        self._combo_tooltip_popup_detail_label: tk.Label | None = None
        self._combo_tooltip_popup_values: list[str] = []
        self._combo_tooltip_text_cache: dict[tuple[str, str], tuple[str, str]] = {}
        self._combo_popup_fast_tooltip_cache: dict[tuple[str, str], str] = {}

        try:
            self.catalogs = GameCatalogs.load(self.game_root)
        except Exception as exc:  # noqa: BLE001
            self.catalogs = None
            self.catalog_error = str(exc)

        self._set_app_window_icon()
        self._reload_profile_lock()
        self._build_ui()
        self._install_click_out_commit_behavior()
        self._schedule_status_title_poll()
        self.refresh_save_list()

    # ------------------------- UI setup -------------------------
    def _resolve_initial_game_root(self, initial_game_root: Path | None) -> Path:
        if initial_game_root is not None:
            try:
                candidate = Path(initial_game_root).expanduser().resolve()
                if _looks_like_game_root(candidate):
                    return candidate
            except Exception:
                pass
        saved_root = str(self.app_settings.get("game_root", "")).strip()
        if saved_root:
            try:
                candidate = Path(saved_root).expanduser().resolve()
                if _looks_like_game_root(candidate):
                    return candidate
            except Exception:
                pass
        return DEFAULT_GAME_ROOT

    def _save_app_settings(self):
        _save_app_settings(self.app_settings)

    def _remember_current_game_root(self):
        self.app_settings["game_root"] = str(self.game_root)
        self._save_app_settings()

    def _remember_last_save_path(self, save_path: Path):
        self.app_settings["last_save_path"] = str(Path(save_path).resolve())
        self._save_app_settings()

    def _set_app_window_icon(self):
        # Try ICO first for native taskbar/title handling on Windows.
        ico_candidates = [
            HERE / "assets" / "masterball.ico",
            self.game_root / "tools" / "assets" / "masterball.ico",
            self.game_root / "tools" / "masterball.ico",
        ]
        for ico in ico_candidates:
            if not ico.exists():
                continue
            try:
                self.root.iconbitmap(default=str(ico))
                break
            except Exception:
                continue
        # Also set iconphoto from game assets so it works even without external .ico.
        png_candidates = [
            self.game_root / "Graphics" / "Items" / "MASTERBALL.png",
            HERE / "assets" / "masterball.png",
        ]
        for png in png_candidates:
            if not png.exists():
                continue
            try:
                img = tk.PhotoImage(file=str(png))
                self._app_icon_image = img
                self.root.iconphoto(True, img)
                break
            except Exception:
                continue

    def _set_game_root(self, game_root: Path):
        target = Path(game_root).expanduser().resolve()
        if not _looks_like_game_root(target):
            raise ValueError("Selected folder is not a valid game root (missing required Data folder).")
        self.game_root = target
        self.profile_lock_path = (
            probe_mapper.default_profile_path(self.game_root)
            if probe_mapper is not None
            else (self.game_root / "tools" / "editor_profile.lock.json")
        )
        try:
            self.catalogs = GameCatalogs.load(self.game_root)
            self.catalog_error = None
        except Exception as exc:  # noqa: BLE001
            self.catalogs = None
            self.catalog_error = str(exc)
        self._dex_type_chart_defense = None
        self._dex_type_order = []
        self._custom_effect_desc_cache.clear()
        self._set_app_window_icon()
        self._reload_profile_lock()
        self._remember_current_game_root()
        if hasattr(self, "custom_item_tab"):
            self._custom_reload_manifest()
        self.set_status(f"Game root set: {self.game_root}")

    def choose_game_root(self):
        picked = filedialog.askdirectory(
            title="Select Game Root Folder",
            initialdir=str(self.game_root),
            mustexist=True,
        )
        if not picked:
            return
        target = Path(picked).resolve()
        if target == self.game_root:
            return
        if self.save_data is not None:
            proceed = messagebox.askyesno(
                "Switch Game Root",
                (
                    "A save is currently loaded.\n\n"
                    "Switching game root may make current loaded data inconsistent.\n"
                    "You should reload save data after switching.\n\n"
                    "Continue?"
                ),
            )
            if not proceed:
                return
        try:
            self._set_game_root(target)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid Game Root", str(exc))
            return
        self.refresh_save_list()
        try:
            self.refresh_team_tab()
        except Exception:
            pass

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        top.columnconfigure(0, weight=1)

        save_row = ttk.Frame(top)
        save_row.grid(row=0, column=0, sticky="ew")
        save_row.columnconfigure(1, weight=1)

        self.save_file_label = ttk.Label(save_row, text="Save File:")
        self.save_file_label.grid(row=0, column=0, sticky="w")
        self.save_file_label.bind("<Double-Button-1>", self._toggle_advanced_mode, add="+")
        self.save_var = tk.StringVar()
        self.save_combo = ttk.Combobox(save_row, textvariable=self.save_var, width=72, state="readonly")
        self.save_combo.grid(row=0, column=1, sticky="ew", padx=(6, 6))

        save_row_btns = ttk.Frame(save_row)
        save_row_btns.grid(row=0, column=2, sticky="e")
        ttk.Button(save_row_btns, text="Refresh", command=self.refresh_save_list).pack(side="left", padx=2)
        ttk.Button(save_row_btns, text="Browse...", command=self.browse_save).pack(side="left", padx=2)
        ttk.Button(save_row_btns, text="Load", command=self.load_selected_save).pack(side="left", padx=2)

        action_row = ttk.Frame(top)
        action_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        action_row.columnconfigure(0, weight=1)

        action_left = ttk.Frame(action_row)
        action_left.grid(row=0, column=0, sticky="w")
        ttk.Button(action_left, text="Game Folder...", command=self.choose_game_root).pack(side="left", padx=2)
        self.map_game_data_btn = ttk.Button(action_left, text="Map Game Data", command=self.run_game_probe_wizard)
        self.map_game_data_btn.pack(side="left", padx=2)
        self.apply_ev_patch_btn = ttk.Button(action_left, text="Apply EV Patch", command=self.apply_ev_unlock_patch)
        self.apply_ev_patch_btn.pack(side="left", padx=2)
        self.rollback_ev_patch_btn = ttk.Button(
            action_left,
            text="Rollback EV Patch",
            command=self.rollback_ev_unlock_patch,
        )
        self.rollback_ev_patch_btn.pack(side="left", padx=2)
        self.probe_patch_capability_btn = ttk.Button(
            action_left,
            text="Probe Patch Capability",
            command=self.probe_patch_capability,
        )
        self.probe_patch_capability_btn.pack(side="left", padx=2)
        self.rebuild_patch_adapter_btn = ttk.Button(
            action_left,
            text="Rebuild Patch Adapter",
            command=self.rebuild_patch_adapter,
        )
        self.rebuild_patch_adapter_btn.pack(side="left", padx=2)
        self.battle_overlay_btn = ttk.Button(
            action_left,
            text="Battle Overlay...",
            command=self.manage_battle_overlay,
        )
        self.battle_overlay_btn.pack(side="left", padx=2)
        self.legality_check_btn = ttk.Button(
            action_left,
            text="Legality Check...",
            command=self.run_legality_check,
        )
        self.legality_check_btn.pack(side="left", padx=2)

        self.save_btn = ttk.Button(action_row, text="Save Changes", command=self.write_save, state="disabled")
        self.save_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

        try:
            style = ttk.Style(self.root)
            style.configure("TNotebook.Tab", padding=(14, 2))
        except Exception:
            pass
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._build_trainer_tab()
        self._build_party_tab()
        self._build_team_tab()
        self._build_damage_tab()
        self._build_bag_tab()
        self._build_dex_tab()
        self._build_custom_item_tab()
        self._apply_advanced_mode_ui(update_status=False)

    def _install_click_out_commit_behavior(self):
        self.root.bind_all("<Button-1>", self._on_global_click_commit, add="+")

    def _on_global_click_commit(self, event):
        popup = self._combo_tooltip_popup
        if popup is not None:
            clicked = getattr(event, "widget", None)
            if self._is_widget_inside_combo_tooltip_popup(clicked):
                return
            self._hide_combo_tooltip_popup()
        # When a combobox popdown is open, do not force commit/focus shifts.
        # This prevents click-selection in filtered dropdown lists from being interrupted.
        if self._find_active_combo_popdown_listbox() is not None:
            self._sync_description_lock_from_clicked_widget(event.widget)
            return
        focused = self.root.focus_get()
        if focused is None:
            self._sync_description_lock_from_clicked_widget(event.widget)
            return
        clicked = event.widget
        slot_idx = self._team_slot_index_from_widget(clicked)
        if slot_idx is not None:
            self._team_select_slot(slot_idx)
        self._sync_description_lock_from_clicked_widget(clicked)
        if focused == clicked:
            return
        focused_name = str(focused).lower()
        clicked_name = str(clicked).lower()
        if "popdown" in focused_name or "popdown" in clicked_name:
            return
        # Force handlers bound to <FocusOut> to run even when clicking
        # on non-focusable widgets (labels/frames/empty area).
        try:
            focused.event_generate("<FocusOut>")
        except tk.TclError:
            pass

        def ensure_focus_shift():
            current = self.root.focus_get()
            if current is not focused:
                return
            try:
                clicked.focus_set()
            except tk.TclError:
                try:
                    self.root.focus_set()
                except tk.TclError:
                    pass

        self.root.after_idle(ensure_focus_shift)

    def _team_slot_index_from_widget(self, widget) -> int | None:
        slot_ui = getattr(self, "_team_slot_ui", None)
        if not isinstance(slot_ui, list) or not slot_ui:
            return None
        current = widget
        visited: set[str] = set()
        while current is not None:
            try:
                current_name = str(current)
            except Exception:
                current_name = ""
            if current_name in visited:
                break
            visited.add(current_name)
            for idx, ui in enumerate(slot_ui):
                if current is ui.get("card") or current is ui.get("canvas"):
                    return idx
            try:
                parent_name = current.winfo_parent()
            except Exception:
                break
            if not parent_name:
                break
            try:
                current = current.nametowidget(parent_name)
            except Exception:
                break
        return None

    def _build_trainer_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Trainer")
        tab.columnconfigure(0, weight=1)

        form = ttk.Frame(tab)
        form.pack(fill="x", expand=True)
        for col in (1, 3):
            form.columnconfigure(col, weight=1)

        self.trainer_name_var = tk.StringVar()
        self.trainer_id_var = tk.StringVar()
        self.trainer_type_var = tk.StringVar()
        self.money_var = tk.StringVar()
        self.coins_var = tk.StringVar()
        self.bp_var = tk.StringVar()
        self.save_slot_var = tk.StringVar()

        row = 0
        self._add_labeled_entry(form, "Name", self.trainer_name_var, row, 0)
        self._add_labeled_entry(form, "Trainer ID", self.trainer_id_var, row, 2, readonly=True)
        row += 1
        self._add_labeled_entry(form, "Trainer Type", self.trainer_type_var, row, 0)
        self._add_labeled_entry(form, "Save Slot", self.save_slot_var, row, 2)
        row += 1
        self._add_labeled_entry(form, "Money", self.money_var, row, 0)
        self._add_labeled_entry(form, "Coins", self.coins_var, row, 2)
        row += 1
        self._add_labeled_entry(form, "Battle Points", self.bp_var, row, 0)

        badges_frame = ttk.LabelFrame(tab, text="Badges", padding=8)
        badges_frame.pack(fill="x", pady=(12, 4))
        for col in range(4):
            badges_frame.columnconfigure(col, weight=1)
        self.badge_vars: list[tk.BooleanVar] = []
        self.badge_checks: list[ttk.Checkbutton] = []
        for i in range(8):
            v = tk.BooleanVar(value=False)
            c = ttk.Checkbutton(badges_frame, text=f"Badge {i + 1}", variable=v)
            c.grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=2)
            self.badge_vars.append(v)
            self.badge_checks.append(c)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Apply Trainer Changes", command=self.apply_trainer_changes).pack(side="left")

    def _build_party_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Party")
        tab.columnconfigure(0, weight=7, minsize=520)
        tab.columnconfigure(1, weight=3, minsize=220)
        tab.rowconfigure(0, weight=1)

        self.pk_species_var = tk.StringVar()
        self.pk_form_var = tk.StringVar()
        self.pk_level_var = tk.StringVar()
        self.pk_exp_var = tk.StringVar()
        self.pk_hp_var = tk.StringVar()
        self.pk_totalhp_var = tk.StringVar()
        self.pk_happiness_var = tk.StringVar()
        self.pk_nature_var = tk.StringVar()
        self.pk_item_var = tk.StringVar()
        self.pk_ability_var = tk.StringVar()
        self.pk_field_status_var = tk.StringVar(value=PARTY_FIELD_STATUS_DEFAULT_LABEL)
        self.pk_gender_var = tk.StringVar()
        self.pk_name_var = tk.StringVar()
        self.pk_shiny_var = tk.BooleanVar(value=False)
        self.pk_super_shiny_var = tk.BooleanVar(value=False)
        self.pk_attack_var = tk.StringVar()
        self.pk_defense_var = tk.StringVar()
        self.pk_spatk_var = tk.StringVar()
        self.pk_spdef_var = tk.StringVar()
        self.pk_speed_var = tk.StringVar()
        self.pk_obtain_level_var = tk.StringVar()
        self.pk_obtain_map_var = tk.StringVar()
        self.pk_obtain_method_var = tk.StringVar()
        self.pk_obtain_text_var = tk.StringVar()
        self.pk_hatched_map_var = tk.StringVar()
        self.pk_ability_index_var = tk.StringVar()
        self.pk_personal_id_var = tk.StringVar()
        self.pk_forced_form_var = tk.StringVar()
        self.pk_legacy_var = tk.StringVar()
        self.party_ev_mode_var = tk.StringVar(value="Basic")
        self.party_ev_note_var = tk.StringVar()
        self.party_evs_left_var = tk.StringVar(value="510")

        self._party_selected_mode: str | None = None
        self._party_selected_index: int | None = None
        self._party_selected_box_index: int | None = None

        self._party_ability_label_to_id: dict[str, str] = {}
        self._party_ability_id_to_label: dict[str, str] = {}
        self._party_nature_label_to_id: dict[str, str] = {}
        self._party_nature_id_to_label: dict[str, str] = {}
        self._party_move_label_to_id: dict[str, str] = {}
        self._party_move_id_to_label: dict[str, str] = {}
        self._party_relearn_label_to_id: dict[str, str] = {}
        self._party_relearn_id_to_label: dict[str, str] = {}
        self._party_status_label_to_spec = {
            label: (status_id, status_count)
            for label, status_id, status_count in PARTY_FIELD_STATUS_OPTIONS
        }
        self._party_status_id_to_label: dict[str, str] = {}
        for label, status_id, status_count in PARTY_FIELD_STATUS_OPTIONS:
            if status_count == 0:
                self._party_status_id_to_label.setdefault(status_id, label)
        self._party_hidden_abilities: set[str] = set()
        self._party_icon_cache: dict[str, tk.PhotoImage] = {}
        self._party_grid_icon_cache: dict[str, tk.PhotoImage] = {}
        self._party_preview_icon_cache: dict[str, tk.PhotoImage] = {}
        self._party_item_icon_cache: dict[str, tk.PhotoImage] = {}
        self._party_evo_scaled_icon_cache: dict[str, tk.PhotoImage] = {}
        self._party_evo_canvas_image_refs: list[tk.PhotoImage] = []
        self._evo_canvas_image_refs: dict[str, list[tk.PhotoImage]] = {}
        self._evo_chart_show_all_conditions = False
        self._party_grid_icon_scale = 2
        self._party_template_pokemon: core.RubyObject | None = None
        self._combo_all_values: dict[str, list[str]] = {}
        self._combo_nav_index: dict[str, int] = {}
        self._combo_popdown_bound: set[str] = set()
        self._combo_search_widgets: dict[str, ttk.Combobox] = {}
        self._team_wheel_bound_widgets: set[str] = set()

        editor_shell = ttk.Frame(tab)
        editor_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        editor_shell.columnconfigure(0, weight=0, minsize=96)
        editor_shell.columnconfigure(1, weight=1)
        editor_shell.rowconfigure(0, weight=1)

        nav = ttk.Frame(editor_shell)
        nav.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        ttk.Label(nav, text="Editor", font=("", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self.party_editor_section_var = tk.StringVar(value="Main")
        self.party_editor_sections: dict[str, ttk.Frame] = {}
        self.party_editor_order = ["Main", "Met", "Stats", "Moves", "Cosmetic", "OT/Misc"]
        for section in self.party_editor_order:
            tk.Radiobutton(
                nav,
                text=section,
                variable=self.party_editor_section_var,
                value=section,
                indicatoron=0,
                width=12,
                anchor="w",
                padx=8,
                pady=6,
                command=self._on_party_editor_section_changed,
            ).pack(fill="x", pady=(0, 2))

        content_shell = ttk.Frame(editor_shell, relief="groove", borderwidth=1)
        content_shell.grid(row=0, column=1, sticky="nsew")
        content_shell.columnconfigure(0, weight=1)
        content_shell.rowconfigure(0, weight=1)

        self.party_content_canvas = tk.Canvas(content_shell, borderwidth=0, highlightthickness=0)
        self.party_content_canvas.grid(row=0, column=0, sticky="nsew")
        self.party_content_vscroll = ttk.Scrollbar(
            content_shell, orient="vertical", command=self.party_content_canvas.yview
        )
        self.party_content_vscroll.grid(row=0, column=1, sticky="ns")
        self.party_content_canvas.configure(yscrollcommand=self.party_content_vscroll.set)
        self.party_content_canvas.bind("<MouseWheel>", self._on_party_content_mousewheel, add="+")
        self.party_content_canvas.bind("<Button-4>", self._on_party_content_mousewheel, add="+")
        self.party_content_canvas.bind("<Button-5>", self._on_party_content_mousewheel, add="+")
        self._party_wheel_bound_widgets = set()

        content = ttk.Frame(self.party_content_canvas, padding=8)
        self._party_content_window = self.party_content_canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            self._on_party_content_frame_configure,
            add="+",
        )
        self.party_content_canvas.bind(
            "<Configure>",
            self._on_party_content_canvas_configure,
            add="+",
        )
        content.columnconfigure(0, weight=1)
        # Keep editor controls (top section) prioritized; evolution chart adapts to remaining height.
        content.rowconfigure(0, weight=1, minsize=260)
        content.rowconfigure(1, weight=0)

        for section in self.party_editor_order:
            frame = ttk.Frame(content)
            frame.grid(row=0, column=0, sticky="nsew")
            self.party_editor_sections[section] = frame

        species_values: list[str] = []
        item_values: list[str] = []
        if self.catalogs:
            base_species = self.catalogs.base_species_choices()
            if base_species:
                species_values = [item.internal_id for item in base_species]
            else:
                species_values = [item.internal_id for item in self.catalogs.species_by_id.values()]
            species_values.sort(key=str.casefold)
            self._custom_load_manifest_cache_silent()
            self.detect_baked_custom_items()
            item_values = self.get_merged_held_item_options(include_key_items=False)

        self._build_party_main_section(self.party_editor_sections["Main"], species_values, item_values)
        self._build_party_met_section(self.party_editor_sections["Met"])
        self._build_party_stats_section(self.party_editor_sections["Stats"])
        self._build_party_moves_section(self.party_editor_sections["Moves"])
        self._build_party_cosmetic_section(self.party_editor_sections["Cosmetic"])
        self._build_party_ot_misc_section(self.party_editor_sections["OT/Misc"])
        self._build_party_evolution_section(content)
        self._bind_party_content_mousewheel_recursive(content)
        self._on_party_editor_section_changed()
        self._apply_party_ev_mode_ui()

        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)

        self._build_party_side_preview(right)

        slots_shell = ttk.LabelFrame(right, text="Box / Party Slots", padding=6)
        slots_shell.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        slots_shell.columnconfigure(0, weight=1)
        slots_shell.rowconfigure(2, weight=1)

        mode_row = ttk.Frame(slots_shell)
        mode_row.grid(row=0, column=0, sticky="w")
        self.party_view_mode_var = tk.StringVar(value="Party")
        ttk.Radiobutton(
            mode_row,
            text="Box",
            value="Box",
            variable=self.party_view_mode_var,
            command=self._on_party_mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row,
            text="Party",
            value="Party",
            variable=self.party_view_mode_var,
            command=self._on_party_mode_changed,
        ).pack(side="left", padx=(6, 0))

        select_row = ttk.Frame(slots_shell)
        select_row.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        select_row.columnconfigure(2, weight=1)
        ttk.Button(select_row, text="Refresh", command=self.refresh_party_tab).grid(row=0, column=0, padx=(0, 6))
        self.party_prev_box_btn = ttk.Button(select_row, text="<", width=3, command=self.party_prev_box)
        self.party_prev_box_btn.grid(row=0, column=1, padx=2)
        self.party_box_var = tk.StringVar()
        self.party_box_option_to_index: dict[str, int] = {}
        self.party_box_combo = ttk.Combobox(select_row, textvariable=self.party_box_var, state="readonly", width=24)
        self.party_box_combo.grid(row=0, column=2, sticky="ew", padx=2)
        self.party_box_combo.bind("<<ComboboxSelected>>", self.on_party_box_selected)
        self.party_next_box_btn = ttk.Button(select_row, text=">", width=3, command=self.party_next_box)
        self.party_next_box_btn.grid(row=0, column=3, padx=2)
        self.party_slot_status_var = tk.StringVar(value="Right-click a slot for View/Set.")
        ttk.Label(select_row, textvariable=self.party_slot_status_var).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )

        grid_host = ttk.Frame(slots_shell)
        grid_host.grid(row=2, column=0, sticky="nsew")
        grid_host.columnconfigure(0, weight=1)
        grid_host.rowconfigure(0, weight=1)
        self.party_grid_frame = ttk.Frame(grid_host, borderwidth=1, relief="solid", padding=2)
        self.party_grid_frame.grid(row=0, column=0, sticky="nsew")

        self.party_slot_context_menu = tk.Menu(self.root, tearoff=0)

        self._refresh_party_box_controls()
        self._on_party_mode_changed()
        self.refresh_party_legality_dropdowns(reset_invalid=False)
        self.update_party_editor_preview()
        self.update_party_evolution_chart()

    def _build_party_main_section(self, frame: ttk.Frame, species_values: list[str], item_values: list[str]):
        for col in (1, 3):
            frame.columnconfigure(col, weight=1)

        row = 0
        ttk.Label(frame, text="Species").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
        self.pk_species_combo = ttk.Combobox(
            frame, textvariable=self.pk_species_var, width=28
        )
        self.pk_species_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=4)
        self._set_combo_values(self.pk_species_combo, species_values)
        self._enable_combo_search(self.pk_species_combo)
        self._register_combo_tooltip_context(self.pk_species_combo, kind="species", resolver=self.resolve_species_id)
        self._register_description_widget(self.pk_species_combo, "party", "species")
        self.pk_species_combo.bind("<<ComboboxSelected>>", self.on_species_or_form_changed)
        self.pk_species_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_party_description("species"), add="+")
        self.pk_species_combo.bind("<Enter>", lambda _e: self.update_party_description("species"), add="+")
        level_entry = self._add_labeled_entry(frame, "Level", self.pk_level_var, row, 2)
        level_entry.bind("<FocusOut>", lambda _e: self._refresh_stats_from_editor_inputs())
        self.pk_shiny_star_check = tk.Checkbutton(
            frame,
            text="★",
            variable=self.pk_shiny_var,
            command=self.on_shiny_changed,
            fg="#cc8a00",
            width=2,
        )
        self.pk_shiny_star_check.grid(row=row, column=4, sticky="w", padx=(4, 0), pady=4)
        row += 1

        form_entry = self._add_labeled_entry(frame, "Form", self.pk_form_var, row, 0)
        form_entry.bind("<FocusOut>", self.on_species_or_form_changed)
        self._add_labeled_entry(frame, "EXP", self.pk_exp_var, row, 2)
        row += 1

        ttk.Label(frame, text="Nature").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
        self.pk_nature_combo = ttk.Combobox(
            frame,
            textvariable=self.pk_nature_var,
            width=28,
        )
        self.pk_nature_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=4)
        self._refresh_nature_choices()
        self._enable_combo_search(self.pk_nature_combo)
        self._register_combo_tooltip_context(self.pk_nature_combo, kind="nature", resolver=self.resolve_selected_nature_id)
        self._register_description_widget(self.pk_nature_combo, "party", "nature")
        self.pk_nature_combo.bind("<<ComboboxSelected>>", self.on_nature_changed)
        self.pk_nature_combo.bind("<FocusOut>", self.on_nature_changed)
        self.pk_nature_combo.bind("<Enter>", lambda _e: self.update_party_description("nature"), add="+")
        gender_entry = self._add_labeled_entry(frame, "Gender", self.pk_gender_var, row, 2)
        gender_entry.bind("<FocusOut>", lambda _e: self.update_party_editor_preview(), add="+")
        row += 1
        ttk.Label(frame, text="Nature effect").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=(0, 4))
        self.pk_nature_effect_var = tk.StringVar(value="")
        self.pk_nature_up_var = tk.StringVar(value="")
        self.pk_nature_sep_var = tk.StringVar(value="")
        self.pk_nature_down_var = tk.StringVar(value="")
        self.pk_nature_neutral_var = tk.StringVar(value="")
        nature_effect_frame = ttk.Frame(frame)
        nature_effect_frame.grid(row=row, column=1, columnspan=3, sticky="w", pady=(0, 4))
        ttk.Label(nature_effect_frame, textvariable=self.pk_nature_neutral_var, foreground="#606060").pack(side="left")
        ttk.Label(nature_effect_frame, textvariable=self.pk_nature_up_var, foreground="#c03535").pack(side="left")
        ttk.Label(nature_effect_frame, textvariable=self.pk_nature_sep_var).pack(side="left")
        ttk.Label(nature_effect_frame, textvariable=self.pk_nature_down_var, foreground="#2b5fc9").pack(side="left")
        row += 1

        ttk.Label(frame, text="Held Item").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
        self.pk_item_combo = ttk.Combobox(frame, textvariable=self.pk_item_var, width=28)
        self.pk_item_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=4)
        item_labels, self._party_item_label_to_id, self._party_item_id_to_label = self._party_item_choice_data(item_values)
        self._set_combo_values(self.pk_item_combo, item_labels)
        self._enable_combo_search(self.pk_item_combo)
        self._register_combo_tooltip_context(self.pk_item_combo, kind="item", resolver=self.resolve_selected_party_item_id)
        self._register_description_widget(self.pk_item_combo, "party", "item")
        self.pk_item_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_party_description("item"), add="+")
        self.pk_item_combo.bind("<FocusOut>", lambda _e: self.update_party_description("item"), add="+")
        self.pk_item_combo.bind("<Enter>", lambda _e: self.update_party_description("item"), add="+")
        self.pk_item_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_party_editor_preview(), add="+")
        self.pk_item_combo.bind("<FocusOut>", lambda _e: self.update_party_editor_preview(), add="+")
        ttk.Label(frame, text="Ability").grid(row=row, column=2, sticky="w", padx=(0, 6), pady=4)
        self.pk_ability_combo = ttk.Combobox(frame, textvariable=self.pk_ability_var, width=28)
        self.pk_ability_combo.grid(row=row, column=3, sticky="ew", padx=(0, 16), pady=4)
        self._enable_combo_search(self.pk_ability_combo)
        self._register_combo_tooltip_context(self.pk_ability_combo, kind="ability", resolver=self.resolve_selected_ability_id)
        self._register_description_widget(self.pk_ability_combo, "party", "ability")
        self.pk_ability_combo.bind("<<ComboboxSelected>>", self.on_ability_changed, add="+")
        self.pk_ability_combo.bind("<FocusOut>", self.on_ability_changed, add="+")
        self.pk_ability_combo.bind("<Enter>", lambda _e: self.update_party_description("ability"), add="+")
        row += 1

        self._add_labeled_entry(frame, "Friendship", self.pk_happiness_var, row, 0)
        self._add_labeled_entry(frame, "Nickname", self.pk_name_var, row, 2)
        row += 1

        ttk.Label(frame, text="Field Status").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
        self.pk_field_status_combo = ttk.Combobox(
            frame,
            textvariable=self.pk_field_status_var,
            width=28,
            state="readonly",
            values=[label for label, _sid, _count in PARTY_FIELD_STATUS_OPTIONS],
        )
        self.pk_field_status_combo.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=4)
        self.pk_field_status_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_party_editor_preview(), add="+")
        hp_entry = self._add_labeled_entry(frame, "Current HP", self.pk_hp_var, row, 2)
        hp_entry.bind("<FocusOut>", self._on_party_hp_entry_focus_out, add="+")
        row += 1

        self._add_labeled_entry(frame, "Max HP", self.pk_totalhp_var, row, 0, readonly=True)
        ttk.Label(frame, text="(Drag HP bar in Preview to adjust)").grid(
            row=row,
            column=2,
            columnspan=2,
            sticky="w",
            padx=(0, 6),
            pady=4,
        )
        row += 1

        ttk.Button(frame, text="Load Species Defaults", command=self.load_species_defaults_into_editor).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

    def _build_party_evolution_section(self, parent: ttk.Frame):
        evo_frame = ttk.LabelFrame(parent, text="Evolution Chart", padding=6)
        self.party_evo_frame = evo_frame
        evo_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        evo_frame.columnconfigure(0, weight=1)
        evo_frame.rowconfigure(0, weight=1)
        self.party_evo_canvas = tk.Canvas(
            evo_frame,
            height=210,
            bg="#fbfbfb",
            highlightthickness=1,
            highlightbackground="#cccccc",
        )
        self.party_evo_canvas.grid(row=0, column=0, sticky="nsew")

    def _run_scheduled_party_evo_update(self):
        self._party_evo_update_scheduled = False
        self.update_party_evolution_chart()

    def _on_party_content_frame_configure(self, _event=None):
        if not hasattr(self, "party_content_canvas"):
            return
        try:
            self.party_content_canvas.configure(scrollregion=self.party_content_canvas.bbox("all"))
        except Exception:
            pass

    def _on_party_content_canvas_configure(self, event):
        if not hasattr(self, "party_content_canvas"):
            return
        try:
            self.party_content_canvas.itemconfigure(self._party_content_window, width=event.width)
        except Exception:
            pass
        if self._party_evo_update_scheduled:
            return
        self._party_evo_update_scheduled = True
        try:
            self.root.after_idle(self._run_scheduled_party_evo_update)
        except Exception:
            self._party_evo_update_scheduled = False

    def _bind_party_content_mousewheel_recursive(self, widget):
        if widget is None:
            return
        key = str(widget)
        if key not in self._party_wheel_bound_widgets:
            try:
                widget.bind("<MouseWheel>", self._on_party_content_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_party_content_mousewheel, add="+")
                widget.bind("<Button-5>", self._on_party_content_mousewheel, add="+")
                self._party_wheel_bound_widgets.add(key)
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._bind_party_content_mousewheel_recursive(child)

    def _on_party_content_mousewheel(self, event):
        if not hasattr(self, "party_content_canvas"):
            return
        canvas = self.party_content_canvas
        target = getattr(event, "widget", None)

        if not self._is_widget_descendant(target, canvas):
            try:
                hovered = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
            except Exception:
                hovered = None
            if not self._is_widget_descendant(hovered, canvas):
                return
        return self._scroll_canvas_mousewheel(canvas, event)

    @staticmethod
    def _mousewheel_steps(event) -> int:
        if getattr(event, "delta", 0):
            steps = int(-event.delta / 120)
            if steps == 0:
                steps = -1 if event.delta > 0 else 1
            return steps
        num = int(getattr(event, "num", 0))
        return -1 if num == 4 else 1

    @staticmethod
    def _scroll_canvas_mousewheel(canvas: tk.Canvas, event):
        try:
            x0, y0, x1, y1 = [int(float(v)) for v in str(canvas.cget("scrollregion")).split()]
        except Exception:
            return
        if (y1 - y0) <= canvas.winfo_height():
            return
        steps = SaveEditorApp._mousewheel_steps(event)
        canvas.yview_scroll(steps, "units")
        return "break"

    def _on_custom_item_workspace_configure(self, _event=None):
        canvas = getattr(self, "custom_item_scroll_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            return

    def _on_custom_item_canvas_configure(self, event):
        canvas = getattr(self, "custom_item_scroll_canvas", None)
        window_id = getattr(self, "_custom_item_scroll_window", None)
        if canvas is None or window_id is None:
            return
        try:
            canvas.itemconfigure(window_id, width=max(1, int(event.width)))
        except Exception:
            return
        self._on_custom_item_workspace_configure()

    def _bind_custom_item_mousewheel_recursive(self, widget):
        if widget is None:
            return
        key = str(widget)
        if key not in self._custom_item_wheel_bound_widgets:
            try:
                widget.bind("<MouseWheel>", self._on_custom_item_tab_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_custom_item_tab_mousewheel, add="+")
                widget.bind("<Button-5>", self._on_custom_item_tab_mousewheel, add="+")
                self._custom_item_wheel_bound_widgets.add(key)
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._bind_custom_item_mousewheel_recursive(child)

    @staticmethod
    def _widget_supports_local_wheel_scroll(widget) -> bool:
        if widget is None:
            return False
        try:
            cls_name = str(widget.winfo_class() or "")
        except Exception:
            cls_name = ""
        return cls_name in {"Listbox", "Text", "Scrollbar", "TScrollbar"}

    def _on_custom_item_tab_mousewheel(self, event):
        canvas = getattr(self, "custom_item_scroll_canvas", None)
        custom_tab = getattr(self, "custom_item_tab", None)
        if canvas is None or custom_tab is None or not hasattr(self, "nb"):
            return
        try:
            selected_tab = self.nb.nametowidget(self.nb.select())
        except Exception:
            selected_tab = None
        if str(selected_tab) != str(custom_tab):
            return
        active_popdown_listbox = self._find_active_combo_popdown_listbox()
        if active_popdown_listbox is not None:
            return self._on_combo_popdown_listbox_wheel(event, active_popdown_listbox)
        target = getattr(event, "widget", None)
        try:
            hovered = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except Exception:
            hovered = None
        if hovered is not None:
            if not self._is_widget_descendant(hovered, canvas):
                return
        elif not self._is_widget_descendant(target, canvas):
            return
        candidate = hovered if hovered is not None else target
        if self._widget_supports_local_wheel_scroll(candidate) or self._widget_supports_local_wheel_scroll(target):
            return
        return self._scroll_canvas_mousewheel(canvas, event)

    @staticmethod
    def _estimate_party_evolution_height(
        root_branch_count: int,
        viewport_height: int,
    ) -> int:
        if root_branch_count <= 4:
            return viewport_height
        cluster_count = (root_branch_count + 3) // 4
        cols = min(3, max(1, cluster_count))
        rows = (cluster_count + cols - 1) // cols
        # Reserve enough per cluster row so lower rows stay visible with scrolling.
        needed = 44 + (rows * 268)
        return max(viewport_height, needed)

    @staticmethod
    def _prune_dict_cache(cache: dict[str, Any], max_size: int):
        over = len(cache) - int(max_size)
        if over <= 0:
            return
        for _ in range(over):
            try:
                cache.pop(next(iter(cache)))
            except Exception:
                break

    @staticmethod
    def _split_chart_columns_for_width(cluster_count: int, width: int, node_half: int) -> int:
        if cluster_count <= 0:
            return 1
        side_pad = max(8, node_half + 10)
        usable_w = max(120, int(width) - (2 * side_pad))
        # Keep cluster cell wide enough; when viewport is narrow, wrap clusters to next row.
        min_cell_width = 340
        cols_by_width = max(1, usable_w // min_cell_width)
        return max(1, min(3, cluster_count, cols_by_width))

    def _build_party_side_preview(self, parent: ttk.Frame):
        preview = ttk.LabelFrame(parent, text="Preview", padding=8)
        preview.grid(row=0, column=0, sticky="ew")
        preview.columnconfigure(1, weight=1)

        left = ttk.Frame(preview)
        left.grid(row=0, column=0, sticky="nw")
        right = ttk.Frame(preview)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)

        self.party_preview_sprite_label = tk.Label(
            left,
            text="(No Pokemon)",
            bg="#f6f6f6",
            relief="solid",
            bd=1,
            anchor="center",
            justify="center",
        )
        self.party_preview_sprite_placeholder = tk.PhotoImage(width=96, height=96)
        self.party_preview_sprite_label.configure(image=self.party_preview_sprite_placeholder, compound="center")
        self.party_preview_sprite_label.image = self.party_preview_sprite_placeholder
        self.party_preview_sprite_label.pack(anchor="nw")

        item_row = ttk.Frame(left)
        item_row.pack(anchor="w", pady=(6, 0))
        self.party_preview_item_icon_label = tk.Label(
            item_row, bg="#f6f6f6", relief="solid", bd=1, padx=2, pady=2
        )
        self.party_preview_item_placeholder = tk.PhotoImage(width=32, height=32)
        self.party_preview_item_icon_label.configure(image=self.party_preview_item_placeholder)
        self.party_preview_item_icon_label.image = self.party_preview_item_placeholder
        self.party_preview_item_icon_label.pack(side="left")
        self.party_preview_item_name_var = tk.StringVar(value="(No item)")
        ttk.Label(item_row, textvariable=self.party_preview_item_name_var).pack(side="left", padx=(6, 0))

        self.party_preview_species_var = tk.StringVar(value="-")
        ttk.Label(right, textvariable=self.party_preview_species_var, font=("", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.party_preview_lv_gender_var = tk.StringVar(value="Lv 1 | Gender: -")
        ttk.Label(right, textvariable=self.party_preview_lv_gender_var).grid(row=1, column=0, sticky="w", pady=(2, 0))
        type_row = ttk.Frame(right)
        type_row.grid(row=2, column=0, sticky="w", pady=(2, 0))
        ttk.Label(type_row, text="Type:").pack(side="left")
        self.party_preview_type_chip_host = ttk.Frame(type_row)
        self.party_preview_type_chip_host.pack(side="left", padx=(6, 0))
        self._render_type_chip_row(self.party_preview_type_chip_host, [], short=False, empty_text="-")

        self.party_preview_hp_bar_width = 180
        self.party_preview_hp_bar_height = 12
        self.party_preview_hp_canvas = tk.Canvas(
            right,
            width=self.party_preview_hp_bar_width,
            height=self.party_preview_hp_bar_height,
            highlightthickness=1,
            highlightbackground="#7a7a7a",
            bg="#2d2d2d",
        )
        self.party_preview_hp_canvas.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.party_preview_hp_fill_rect = self.party_preview_hp_canvas.create_rectangle(
            1, 1, 1, self.party_preview_hp_bar_height - 1, fill="#59c441", outline=""
        )
        self.party_preview_hp_text_var = tk.StringVar(value="HP: 0/0")
        ttk.Label(right, textvariable=self.party_preview_hp_text_var).grid(row=4, column=0, sticky="w", pady=(3, 0))
        self.party_preview_hp_canvas.bind("<Configure>", lambda _e: self.update_party_editor_preview(), add="+")
        self.party_preview_hp_canvas.bind("<Button-1>", self._on_party_preview_hp_drag, add="+")
        self.party_preview_hp_canvas.bind("<B1-Motion>", self._on_party_preview_hp_drag, add="+")

    def _build_party_met_section(self, frame: ttk.Frame):
        for col in (1, 3):
            frame.columnconfigure(col, weight=1)
        row = 0
        self._add_labeled_entry(frame, "Obtain Level", self.pk_obtain_level_var, row, 0)
        self._add_labeled_entry(frame, "Obtain Method", self.pk_obtain_method_var, row, 2)
        row += 1
        self._add_labeled_entry(frame, "Obtain Map", self.pk_obtain_map_var, row, 0)
        self._add_labeled_entry(frame, "Hatched Map", self.pk_hatched_map_var, row, 2)
        row += 1
        self._add_labeled_entry(frame, "Obtain Text", self.pk_obtain_text_var, row, 0, width=56)

    def _build_party_stats_section(self, frame: ttk.Frame):
        for c in range(5):
            frame.columnconfigure(c, weight=0)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(4, weight=1)

        ttk.Label(frame, text=" ").grid(row=0, column=0, padx=(0, 4), pady=(0, 4))
        ttk.Label(frame, text="Base").grid(row=0, column=1, padx=4, pady=(0, 4))
        ttk.Label(frame, text="IVs").grid(row=0, column=2, padx=4, pady=(0, 4))
        ttk.Label(frame, text="EVs").grid(row=0, column=3, padx=4, pady=(0, 4))
        ttk.Label(frame, text="Stats").grid(row=0, column=4, padx=4, pady=(0, 4))

        self.party_stat_name_labels: dict[str, tk.Label] = {}
        self.party_base_stat_vars: dict[str, tk.StringVar] = {}
        self.party_iv_vars: dict[str, tk.StringVar] = {}
        self.party_ev_vars: dict[str, tk.StringVar] = {}
        self.party_final_stat_vars: dict[str, tk.StringVar] = {}

        for row, (stat_id, stat_label) in enumerate(STAT_ORDER, start=1):
            name_lbl = tk.Label(frame, text=f"{stat_label}:", width=6, anchor="e")
            name_lbl.grid(row=row, column=0, sticky="e", padx=(0, 4), pady=2)
            self.party_stat_name_labels[stat_id] = name_lbl

            base_var = tk.StringVar(value="0")
            self.party_base_stat_vars[stat_id] = base_var
            ttk.Label(frame, textvariable=base_var, width=6, anchor="center").grid(
                row=row, column=1, padx=4, pady=2
            )

            iv_var = tk.StringVar(value="0")
            self.party_iv_vars[stat_id] = iv_var
            iv_entry = ttk.Entry(frame, textvariable=iv_var, width=6)
            iv_entry.grid(row=row, column=2, padx=4, pady=2)
            iv_entry.bind("<FocusOut>", lambda _e, sid=stat_id: self.on_iv_ev_focus_out("iv", sid))

            ev_var = tk.StringVar(value="0")
            self.party_ev_vars[stat_id] = ev_var
            ev_entry = ttk.Entry(frame, textvariable=ev_var, width=6)
            ev_entry.grid(row=row, column=3, padx=4, pady=2)
            ev_entry.bind("<FocusOut>", lambda _e, sid=stat_id: self.on_iv_ev_focus_out("ev", sid))

            final_var = tk.StringVar(value="0")
            self.party_final_stat_vars[stat_id] = final_var
            ttk.Label(frame, textvariable=final_var, width=8, anchor="center").grid(
                row=row, column=4, padx=4, pady=2
            )

        self.party_hidden_power_var = tk.StringVar(value="Unknown")
        self.party_hidden_power_label = ttk.Label(frame, text="Hidden Power Type:")
        self.party_hidden_power_label.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self.party_hidden_power_chip_host = ttk.Frame(frame)
        self.party_hidden_power_chip_host.grid(row=8, column=2, sticky="w", pady=(8, 2))
        self._render_type_chip_row(self.party_hidden_power_chip_host, [], short=False, empty_text="Unknown")
        self.party_max_evs_btn = ttk.Button(frame, text="Max EVs", command=self.set_all_evs_max)
        self.party_max_evs_btn.grid(
            row=8, column=3, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 2)
        )
        self.party_evs_left_wrap = ttk.Frame(frame)
        self.party_evs_left_wrap.grid(row=8, column=3, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 2))
        ev_badge_bg = ttk.Style().lookup("TFrame", "background") or self.root.cget("bg")
        self.party_evs_left_title_label = tk.Label(
            self.party_evs_left_wrap,
            text="EVs:",
            font=("", 10, "bold"),
            borderwidth=0,
            highlightthickness=0,
            bg=ev_badge_bg,
        )
        self.party_evs_left_title_label.pack(side="left", padx=(0, 4))
        self.party_evs_left_value_label = tk.Label(
            self.party_evs_left_wrap,
            textvariable=self.party_evs_left_var,
            font=("", 10, "bold"),
            borderwidth=0,
            highlightthickness=0,
            bg=ev_badge_bg,
            fg="#2e7d32",
        )
        self.party_evs_left_value_label.pack(side="left")

        self.party_ev_note_label = ttk.Label(frame, textvariable=self.party_ev_note_var)
        self.party_ev_note_label.grid(row=9, column=0, columnspan=5, sticky="w", pady=(6, 0))

    def _build_party_moves_section(self, frame: ttk.Frame):
        current = ttk.LabelFrame(frame, text="Current Moves", padding=8)
        current.pack(fill="x")
        current.columnconfigure(1, weight=1)
        self.move_id_vars = []
        self.move_pp_vars = []
        self.move_ppup_vars = []
        self.move_id_combos: list[ttk.Combobox] = []
        self.move_pp_entries: list[ttk.Entry] = []
        self.move_ppup_entries: list[ttk.Entry] = []
        for i in range(4):
            move_var = tk.StringVar()
            pp_var = tk.StringVar()
            ppup_var = tk.StringVar()
            self.move_id_vars.append(move_var)
            self.move_pp_vars.append(pp_var)
            self.move_ppup_vars.append(ppup_var)
            ttk.Label(current, text=f"Move {i + 1}").grid(row=i, column=0, sticky="w", padx=(0, 6), pady=2)
            move_combo = ttk.Combobox(current, textvariable=move_var, width=26)
            move_combo.grid(row=i, column=1, sticky="ew", padx=(0, 6), pady=2)
            self._enable_combo_search(move_combo)
            self._register_combo_tooltip_context(move_combo, kind="move", resolver=self.resolve_selected_move_id)
            self._register_description_widget(move_combo, "party", "move", i)
            move_combo.bind("<<ComboboxSelected>>", lambda _e, idx=i: self.on_move_combo_changed(idx), add="+")
            move_combo.bind("<FocusOut>", lambda _e, idx=i: self.on_move_combo_changed(idx, force_pp=False), add="+")
            move_combo.bind("<Enter>", lambda _e, idx=i: self.update_party_description("move", idx), add="+")
            self.move_id_combos.append(move_combo)
            ttk.Label(current, text="PP").grid(row=i, column=2, sticky="w", padx=(6, 2))
            pp_entry = ttk.Entry(current, textvariable=pp_var, width=6)
            pp_entry.grid(row=i, column=3, sticky="w", padx=2, pady=2)
            pp_entry.bind("<FocusOut>", lambda _e, idx=i: self.on_move_pp_focus_out(idx), add="+")
            self.move_pp_entries.append(pp_entry)
            ttk.Label(current, text="PPUp").grid(row=i, column=4, sticky="w", padx=(6, 2))
            ppup_entry = ttk.Entry(current, textvariable=ppup_var, width=6)
            ppup_entry.grid(row=i, column=5, sticky="w", padx=2, pady=2)
            ppup_entry.bind("<FocusOut>", lambda _e, idx=i: self.on_move_ppup_changed(idx), add="+")
            self.move_ppup_entries.append(ppup_entry)

        relearn = ttk.LabelFrame(frame, text="Relearn Moves", padding=8)
        relearn.pack(fill="x", pady=(10, 0))
        relearn.columnconfigure(1, weight=1)
        self.relearn_move_vars: list[tk.StringVar] = []
        self.relearn_move_combos: list[ttk.Combobox] = []
        for i in range(4):
            rv = tk.StringVar(value="(None)")
            self.relearn_move_vars.append(rv)
            ttk.Label(relearn, text=f"Relearn {i + 1}").grid(row=i, column=0, sticky="w", padx=(0, 6), pady=2)
            combo = ttk.Combobox(relearn, textvariable=rv, width=30)
            combo.grid(row=i, column=1, sticky="ew", pady=2)
            self._set_combo_values(combo, ["(None)"])
            self._enable_combo_search(combo)
            self._register_combo_tooltip_context(combo, kind="relearn", resolver=self.resolve_selected_relearn_move_id)
            self._register_description_widget(combo, "party", "relearn", i)
            combo.bind("<<ComboboxSelected>>", lambda _e, idx=i: self.update_party_description("relearn", idx), add="+")
            combo.bind("<FocusOut>", lambda _e, idx=i: self.update_party_description("relearn", idx), add="+")
            combo.bind("<Enter>", lambda _e, idx=i: self.update_party_description("relearn", idx), add="+")
            self.relearn_move_combos.append(combo)

    def _build_party_cosmetic_section(self, frame: ttk.Frame):
        ttk.Checkbutton(frame, text="Super Shiny", variable=self.pk_super_shiny_var).grid(
            row=0, column=0, sticky="w", pady=4
        )

    def _build_party_ot_misc_section(self, frame: ttk.Frame):
        for col in (1, 3):
            frame.columnconfigure(col, weight=1)
        row = 0
        ability_index_entry = self._add_labeled_entry(frame, "Ability Index", self.pk_ability_index_var, row, 0)
        ability_index_entry.bind("<FocusOut>", self.on_ability_index_focus_out, add="+")
        self._add_labeled_entry(frame, "Personal ID", self.pk_personal_id_var, row, 2)
        row += 1
        forced_form_entry = self._add_labeled_entry(frame, "Forced Form", self.pk_forced_form_var, row, 0)
        forced_form_entry.bind("<FocusOut>", self.on_forced_form_focus_out, add="+")
        self._add_labeled_entry(frame, "Legacy Data", self.pk_legacy_var, row, 2)

    def _on_party_editor_section_changed(self):
        selected = self.party_editor_section_var.get()
        for section, frame in self.party_editor_sections.items():
            if section == selected:
                frame.tkraise()

    def _on_party_mode_changed(self):
        is_box = self.party_view_mode_var.get() == "Box"
        if is_box:
            self.party_box_combo.state(["!disabled"])
            self.party_prev_box_btn.state(["!disabled"])
            self.party_next_box_btn.state(["!disabled"])
        else:
            self.party_box_combo.state(["disabled"])
            self.party_prev_box_btn.state(["disabled"])
            self.party_next_box_btn.state(["disabled"])
        self._party_selected_mode = None
        self._party_selected_index = None
        self._party_selected_box_index = None
        self.party_slot_status_var.set("Right-click a slot for View/Set.")
        self._render_party_slot_grid()

    def _get_storage_boxes(self) -> list:
        storage = self.get_root_key("storage_system")
        if not isinstance(storage, core.RubyObject):
            return []
        boxes = core.read_attr(storage, "@boxes", [])
        if not isinstance(boxes, list):
            return []
        return boxes

    def _get_box_pokemon_list(self, box_obj: Any) -> list:
        if not isinstance(box_obj, core.RubyObject):
            return []
        data = core.read_attr(box_obj, "@pokemon", [])
        if not isinstance(data, list):
            return []
        return data

    def _box_display_name(self, box_obj: Any, index: int) -> str:
        base = f"Box {index + 1}"
        if not isinstance(box_obj, core.RubyObject):
            return base
        raw = symbol_name(core.read_attr(box_obj, "@name", "")).strip()
        return f"{base} - {raw}" if raw else base

    def _selected_box_index(self) -> int:
        raw = self.party_box_var.get().strip()
        return self.party_box_option_to_index.get(raw, 0)

    def _refresh_party_box_controls(self):
        self.party_box_option_to_index = {}
        if self.save_data is None:
            self.party_box_combo["values"] = []
            self.party_box_var.set("")
            return
        boxes = self._get_storage_boxes()
        values: list[str] = []
        for i, box in enumerate(boxes):
            label = self._box_display_name(box, i)
            values.append(label)
            self.party_box_option_to_index[label] = i
        self.party_box_combo["values"] = values
        if not values:
            self.party_box_var.set("")
            return
        storage = self.get_root_key("storage_system")
        current = core.read_attr(storage, "@currentBox", 0) if isinstance(storage, core.RubyObject) else 0
        try:
            current_index = int(current)
        except (TypeError, ValueError):
            current_index = 0
        if current_index < 0 or current_index >= len(values):
            current_index = 0
        self.party_box_var.set(values[current_index])

    def on_party_box_selected(self, _event=None):
        storage = self.get_root_key("storage_system")
        if isinstance(storage, core.RubyObject):
            storage.attributes["@currentBox"] = self._selected_box_index()
        self._party_selected_mode = None
        self._party_selected_index = None
        self._party_selected_box_index = None
        self.party_slot_status_var.set("Right-click a slot for View/Set.")
        self._render_party_slot_grid()

    def party_prev_box(self):
        values = list(self.party_box_combo["values"])
        if not values:
            return
        idx = self._selected_box_index() - 1
        if idx < 0:
            idx = len(values) - 1
        self.party_box_var.set(values[idx])
        self.on_party_box_selected()

    def party_next_box(self):
        values = list(self.party_box_combo["values"])
        if not values:
            return
        idx = self._selected_box_index() + 1
        if idx >= len(values):
            idx = 0
        self.party_box_var.set(values[idx])
        self.on_party_box_selected()

    def _party_slot_cells(self) -> tuple[list[Any], int, int, str, int | None]:
        if self.save_data is None:
            return [], 2, 3, "party", None
        if self.party_view_mode_var.get() == "Box":
            boxes = self._get_storage_boxes()
            box_idx = self._selected_box_index()
            if box_idx < 0 or box_idx >= len(boxes):
                return [], 5, 6, "box", None
            return self._get_box_pokemon_list(boxes[box_idx]), 5, 6, "box", box_idx
        player = self.get_root_key("player")
        party = core.read_attr(player, "@party", []) if isinstance(player, core.RubyObject) else []
        if not isinstance(party, list):
            party = []
        return party, 2, 3, "party", None

    def _slot_display_label(self, entry: Any, idx: int) -> str:
        if isinstance(entry, core.RubyObject):
            species_id = symbol_name(core.read_attr(entry, "@species", ""))
            species = self.catalogs.canonical_species_id(species_id) if self.catalogs else species_id
            species = species or species_id
            level = core.read_attr(entry, "@level", "?")
            return f"#{idx + 1}\n{species}\nLv {level}"
        return f"#{idx + 1}\n(empty)"

    def _pokemon_icon_candidates_from_fields(self, species_id: str, form: int = 0) -> list[str]:
        species_raw = str(species_id or "").strip().lstrip(":")
        if not species_raw:
            return []
        species = self.catalogs.canonical_species_id(species_raw) if self.catalogs else species_raw
        species = species or species_raw
        try:
            form_int = int(form)
        except (TypeError, ValueError):
            form_int = 0
        out: list[str] = []
        if form_int > 0:
            out.append(f"{species}_{form_int}")
        out.append(species)
        return out

    def _pokemon_icon_candidates(self, pkmn: core.RubyObject) -> list[str]:
        species_raw = symbol_name(core.read_attr(pkmn, "@species", "")).strip()
        form = core.read_attr(pkmn, "@form", 0)
        return self._pokemon_icon_candidates_from_fields(species_raw, form=form)

    def _get_party_icon_image_for_fields(self, species_id: str, form: int, shiny: bool) -> tk.PhotoImage | None:
        subdir = "Icons shiny" if shiny else "Icons"
        root_dir = self.game_root / "Graphics" / "Pokemon" / subdir
        for stem in self._pokemon_icon_candidates_from_fields(species_id, form=form):
            cache_key = f"{subdir}:{stem}"
            if cache_key in self._party_icon_cache:
                return self._party_icon_cache[cache_key]
            path = root_dir / f"{stem}.png"
            if not path.exists():
                continue
            try:
                img = tk.PhotoImage(file=str(path))
                img = self._normalize_icon_frame(img)
            except Exception:
                continue
            self._party_icon_cache[cache_key] = img
            self._prune_dict_cache(self._party_icon_cache, PARTY_ICON_CACHE_LIMIT)
            return img
        return None

    def _get_party_icon_image(self, pkmn: Any) -> tk.PhotoImage | None:
        if not isinstance(pkmn, core.RubyObject):
            return None
        shiny = bool(core.read_attr(pkmn, "@shiny", False))
        species_raw = symbol_name(core.read_attr(pkmn, "@species", "")).strip()
        form = core.read_attr(pkmn, "@form", 0)
        scale = max(1, int(getattr(self, "_party_grid_icon_scale", 1)))
        cache_key = f"grid:{species_raw}:{form}:{int(shiny)}:{scale}"
        cached = self._party_grid_icon_cache.get(cache_key)
        if cached is not None:
            return cached
        base = self._get_party_icon_image_for_fields(species_raw, form=form, shiny=shiny)
        if base is None:
            return None
        if scale <= 1:
            scaled = base
        else:
            try:
                scaled = base.subsample(scale, scale)
            except Exception:
                scaled = base
        self._party_grid_icon_cache[cache_key] = scaled
        self._prune_dict_cache(self._party_grid_icon_cache, PARTY_GRID_ICON_CACHE_LIMIT)
        return scaled

    def _get_party_preview_icon_image(self, species_id: str, form: int, shiny: bool) -> tk.PhotoImage | None:
        key = f"preview:{species_id}:{form}:{int(shiny)}"
        if key in self._party_preview_icon_cache:
            return self._party_preview_icon_cache[key]
        base = self._get_party_icon_image_for_fields(species_id, form=form, shiny=shiny)
        if base is None:
            return None
        try:
            if base.width() <= 48:
                scaled = base.zoom(2, 2)
            elif base.width() > 96:
                scaled = base.subsample(2, 2)
            else:
                scaled = base
        except Exception:
            scaled = base
        self._party_preview_icon_cache[key] = scaled
        self._prune_dict_cache(self._party_preview_icon_cache, PARTY_PREVIEW_ICON_CACHE_LIMIT)
        return scaled

    def _get_item_icon_image(self, item_id: str) -> tk.PhotoImage | None:
        raw = str(item_id or "").strip().lstrip(":")
        if not raw:
            return None
        canonical = self.catalogs.canonical_item_id(raw) if self.catalogs else raw
        item_key = canonical or raw
        cache_key = f"item:{item_key}"
        if cache_key in self._party_item_icon_cache:
            return self._party_item_icon_cache[cache_key]
        parallel_root = self.game_root / "tools" / "custom_item" / "assets" / "items"
        root = self.game_root / "Graphics" / "Items"
        candidates = [
            parallel_root / f"{item_key}.png",
            root / f"{item_key}.png",
            root / "Key items" / f"{item_key}_key.png",
            root / "000.png",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                img = tk.PhotoImage(file=str(path))
            except Exception:
                continue
            self._party_item_icon_cache[cache_key] = img
            self._prune_dict_cache(self._party_item_icon_cache, PARTY_ITEM_ICON_CACHE_LIMIT)
            return img
        return None

    @staticmethod
    def _gender_label_from_value(value: int) -> str:
        if value == 0:
            return "Male"
        if value == 1:
            return "Female"
        if value == 2:
            return "Genderless"
        return "Unknown"

    def _party_status_label_from_fields(self, status_value: Any, status_count_value: Any) -> str:
        status_id = symbol_name(status_value).strip().lstrip(":").upper()
        if not status_id or status_id in {"NONE", "NIL", "NULL"}:
            return PARTY_FIELD_STATUS_DEFAULT_LABEL
        status_count = self._clamp_int(str(status_count_value), 0, 99, 0)
        if status_id == "POISON" and status_count > 0:
            return "Toxic (Bad Poison)"
        return self._party_status_id_to_label.get(status_id, status_id)

    def _resolve_party_field_status_spec(self, raw_text: str) -> tuple[str, int]:
        raw = str(raw_text or "").strip()
        if not raw:
            return "NONE", 0
        if raw in self._party_status_label_to_spec:
            return self._party_status_label_to_spec[raw]
        token = extract_internal_id(raw).strip().lstrip(":").upper()
        if not token or token in {"NONE", "NIL", "NULL"}:
            return "NONE", 0
        if token == "TOXIC":
            return "POISON", 1
        if token in {"SLEEP", "POISON", "BURN", "PARALYSIS", "FROZEN", "FROSTBITE"}:
            if token == "SLEEP":
                return token, 2
            return token, 0
        return "NONE", 0

    def _on_party_hp_entry_focus_out(self, _event=None):
        total_hp = self._clamp_int(self.pk_totalhp_var.get(), 0, 9999, 0)
        if total_hp <= 0:
            total_hp = max(1, self._clamp_int(self.pk_hp_var.get(), 0, 9999, 1))
            self.pk_totalhp_var.set(str(total_hp))
        current_hp = self._clamp_int(self.pk_hp_var.get(), 0, total_hp, total_hp)
        self.pk_hp_var.set(str(current_hp))
        self.update_party_editor_preview()

    def _on_party_preview_hp_drag(self, event):
        if event is None:
            return "break"
        total_hp = self._clamp_int(self.pk_totalhp_var.get(), 0, 9999, 0)
        if total_hp <= 0:
            total_hp = max(1, self._clamp_int(self.pk_hp_var.get(), 0, 9999, 1))
            self.pk_totalhp_var.set(str(total_hp))
        bar_width = self.party_preview_hp_canvas.winfo_width()
        if bar_width <= 2:
            bar_width = self.party_preview_hp_bar_width
        usable_width = max(1, bar_width - 2)
        x = max(1, min(bar_width - 1, int(event.x)))
        ratio = (x - 1) / usable_width
        current_hp = int(round(ratio * total_hp))
        current_hp = max(0, min(total_hp, current_hp))
        self.pk_hp_var.set(str(current_hp))
        self.update_party_editor_preview()
        return "break"

    def update_party_editor_preview(self):
        if not hasattr(self, "party_preview_sprite_label"):
            return
        species_raw = self.pk_species_var.get().strip()
        species_id = ""
        if species_raw:
            try:
                species_id = self.resolve_species_id(species_raw)
            except Exception:
                species_id = extract_internal_id(species_raw).strip().lstrip(":")
        form = self._clamp_int(self.pk_form_var.get(), 0, 999, 0)
        shiny = bool(self.pk_shiny_var.get())

        preview_img = self._get_party_preview_icon_image(species_id, form=form, shiny=shiny) if species_id else None
        if preview_img is None:
            preview_img = self.party_preview_sprite_placeholder
        self.party_preview_sprite_label.configure(
            image=preview_img,
            text="" if species_id else "(No Pokemon)",
        )
        self.party_preview_sprite_label.image = preview_img

        item_id = ""
        item_label = "(No item)"
        if self.pk_item_var.get().strip():
            try:
                item_id = self.resolve_selected_party_item_id(self.pk_item_var.get())
                item_label = self._english_item_name_for_id(item_id)
            except Exception:
                item_id = ""
                item_label = self.pk_item_var.get().strip()
        item_img = self._get_item_icon_image(item_id) if item_id else None
        if item_img is None:
            item_img = self.party_preview_item_placeholder
        self.party_preview_item_icon_label.configure(image=item_img)
        self.party_preview_item_icon_label.image = item_img
        self.party_preview_item_name_var.set(item_label)

        species_label = self._english_species_name_for_id(species_id) if species_id else "(No species)"
        level = self._clamp_int(self.pk_level_var.get(), 1, 100, 1)
        gender = self._clamp_int(self.pk_gender_var.get(), 0, 2, 0)
        status_id, status_count = self._resolve_party_field_status_spec(self.pk_field_status_var.get())
        if status_id == "POISON" and status_count > 0:
            preview_status = "Toxic"
        elif status_id in {"NONE", "", "NIL", "NULL"}:
            preview_status = "None"
        else:
            preview_status = self._party_status_id_to_label.get(status_id, status_id.title())
        self.party_preview_species_var.set(species_label)
        self.party_preview_lv_gender_var.set(
            f"Lv {level} | Gender: {self._gender_label_from_value(gender)} | Status: {preview_status}"
        )
        type_ids: list[str] = []
        if species_id and self.catalogs:
            type_ids = self._dex_species_type_ids(species_id, form=form)
        if hasattr(self, "party_preview_type_chip_host"):
            self._render_type_chip_row(
                self.party_preview_type_chip_host,
                type_ids,
                short=False,
                empty_text="-",
            )

        total_hp = self._clamp_int(self.pk_totalhp_var.get(), 0, 9999, 0)
        cur_hp = self._clamp_int(self.pk_hp_var.get(), 0, 9999, total_hp)
        if total_hp <= 0:
            total_hp = max(cur_hp, 1)
        cur_hp = max(0, min(cur_hp, total_hp))
        ratio = cur_hp / total_hp if total_hp > 0 else 0.0
        actual_bar_w = self.party_preview_hp_canvas.winfo_width()
        if actual_bar_w <= 2:
            actual_bar_w = self.party_preview_hp_bar_width
        self.party_preview_hp_bar_width = max(120, actual_bar_w)
        fill_w = int((self.party_preview_hp_bar_width - 2) * ratio)
        if cur_hp > 0:
            fill_w = max(1, fill_w)
        fill_w = max(0, min(self.party_preview_hp_bar_width - 2, fill_w))
        if ratio > 0.5:
            bar_color = "#59c441"
        elif ratio > 0.2:
            bar_color = "#d4b146"
        else:
            bar_color = "#cf4a4a"
        self.party_preview_hp_canvas.coords(
            self.party_preview_hp_fill_rect,
            1,
            1,
            1 + fill_w,
            self.party_preview_hp_bar_height - 1,
        )
        self.party_preview_hp_canvas.itemconfig(self.party_preview_hp_fill_rect, fill=bar_color)
        self.party_preview_hp_text_var.set(f"HP: {cur_hp}/{total_hp}")

    @staticmethod
    def _normalize_icon_frame(img: tk.PhotoImage) -> tk.PhotoImage:
        width, height = img.width(), img.height()
        if width <= height:
            return img
        frame_w = height
        try:
            return img.copy(from_coords=(0, 0, frame_w, height))
        except Exception:
            cropped = tk.PhotoImage(width=frame_w, height=height)
            try:
                cropped.tk.call(str(cropped), "copy", str(img), "-from", 0, 0, frame_w, height, "-to", 0, 0)
                return cropped
            except Exception:
                return img

    def _render_party_slot_grid(self):
        for widget in self.party_grid_frame.winfo_children():
            widget.destroy()

        entries, rows, cols, mode, box_idx = self._party_slot_cells()
        total = rows * cols
        wrap_len = 64 if cols <= 3 else 52
        for r in range(rows):
            self.party_grid_frame.rowconfigure(r, weight=1)
        for c in range(cols):
            self.party_grid_frame.columnconfigure(c, weight=1)

        for i in range(total):
            entry = entries[i] if i < len(entries) else None
            label = self._slot_display_label(entry, i)
            selected = (
                self._party_selected_mode == mode
                and self._party_selected_index == i
                and (mode != "box" or self._party_selected_box_index == box_idx)
            )
            btn = tk.Button(
                self.party_grid_frame,
                text=label,
                image=self._get_party_icon_image(entry),
                compound="top",
                justify="center",
                wraplength=wrap_len,
                font=("", 8),
                relief="solid",
                bd=1,
                padx=2,
                pady=2,
                bg="#ffe7a8" if selected else "#dff3dc",
                activebackground="#f6d584" if selected else "#cde9c8",
                command=lambda idx=i: self.select_party_slot(idx),
            )
            btn.bind("<Button-3>", lambda event, idx=i: self._on_party_slot_right_click(event, idx), add="+")
            btn.bind("<Control-Button-1>", lambda event, idx=i: self._on_party_slot_right_click(event, idx), add="+")
            btn.grid(row=i // cols, column=i % cols, sticky="nsew", padx=1, pady=1)

    # ------------------------- Team Builder tab -------------------------
    @staticmethod
    def _team_default_ivs() -> dict[str, int]:
        return {sid: 31 for sid, _label in STAT_ORDER}

    @staticmethod
    def _team_default_evs() -> dict[str, int]:
        return {sid: 0 for sid, _label in STAT_ORDER}

    @staticmethod
    def _team_default_slot_data() -> dict[str, Any]:
        return {
            "species_id": "",
            "form": 0,
            "level": 50,
            "shiny": False,
            "nature_id": "HARDY",
            "ability_id": "",
            "item_id": "",
            "moves": ["", "", "", ""],
            "ivs": SaveEditorApp._team_default_ivs(),
            "evs": SaveEditorApp._team_default_evs(),
        }

    def _team_move_label_for_id(self, move_id: str) -> str:
        return self._move_display_name_for_id(move_id)

    def _team_nature_choice_labels(self) -> list[str]:
        self._team_nature_label_to_id: dict[str, str] = {}
        self._team_nature_id_to_label: dict[str, str] = {}
        if self.catalogs:
            nature_ids = sorted(
                (self._nature_choice(n) for n in self.catalogs.natures if str(n).strip()),
                key=str.casefold,
            )
        else:
            nature_ids = sorted(
                {
                    "HARDY", "LONELY", "BRAVE", "ADAMANT", "NAUGHTY",
                    "BOLD", "DOCILE", "RELAXED", "IMPISH", "LAX",
                    "TIMID", "HASTY", "SERIOUS", "JOLLY", "NAIVE",
                    "MODEST", "MILD", "QUIET", "BASHFUL", "RASH",
                    "CALM", "GENTLE", "SASSY", "CAREFUL", "QUIRKY",
                },
                key=str.casefold,
            )
        labels: list[str] = []
        for nature_id in nature_ids:
            label = self._nature_label_for_id(nature_id)
            if label in self._team_nature_label_to_id:
                label = f"{label} [{nature_id}]"
            self._team_nature_label_to_id[label] = nature_id
            self._team_nature_id_to_label.setdefault(nature_id, label)
            labels.append(label)
        return labels

    def _team_item_choice_labels(self) -> list[str]:
        self._team_item_label_to_id: dict[str, str] = {"(None)": ""}
        self._team_item_id_to_label: dict[str, str] = {"": "(None)"}
        if not self.catalogs:
            return ["(None)"]
        pairs: list[tuple[str, str]] = []
        for item_id in self.get_merged_held_item_options(include_key_items=False):
            label = self._english_item_name_for_id(item_id)
            if any(existing == label for existing, _iid in pairs):
                label = f"{label} [{item_id}]"
            pairs.append((label, item_id))
        pairs.sort(key=lambda row: row[0].casefold())
        for label, item_id in pairs:
            self._team_item_label_to_id[label] = item_id
            self._team_item_id_to_label.setdefault(item_id, label)
        return ["(None)"] + [label for label, _iid in pairs]

    @staticmethod
    def _team_allow_item_in_card(pocket_idx: int | None) -> bool:
        # Card editor should not show balls, TMs/HMs, or key items.
        if pocket_idx in {3, 4, 8}:
            return False
        return True

    def _team_card_item_choice_data(self) -> tuple[list[str], dict[str, str], dict[str, str]]:
        label_to_id: dict[str, str] = {"Item": "", "(None)": ""}
        id_to_label: dict[str, str] = {"": "Item"}
        if not self.catalogs:
            return ["Item"], label_to_id, id_to_label
        pairs: list[tuple[str, str]] = []
        for item_id in self.get_merged_held_item_options(include_key_items=False):
            item = self.catalogs.items_by_id.get(item_id)
            pocket_idx = self._parse_pocket_value(item.extra.get("Pocket", "")) if item else self._custom_manifest_item_pocket(item_id)
            if not self._team_allow_item_in_card(pocket_idx):
                continue
            label = self._english_item_name_for_id(item_id)
            if any(existing == label for existing, _iid in pairs):
                label = f"{label} [{item_id}]"
            pairs.append((label, item_id))
        pairs.sort(key=lambda row: row[0].casefold())
        labels = ["Item"]
        for label, item_id in pairs:
            labels.append(label)
            label_to_id[label] = item_id
            id_to_label.setdefault(item_id, label)
        return labels, label_to_id, id_to_label

    def _team_card_move_choice_data(
        self,
        species_id: str,
        form: int,
    ) -> tuple[list[str], dict[str, str], dict[str, str]]:
        label_to_id: dict[str, str] = {"(None)": ""}
        id_to_label: dict[str, str] = {"": "(None)"}
        if not self.catalogs or not species_id:
            return ["(None)"], label_to_id, id_to_label
        move_ids = self.catalogs.valid_moves_for_species(species_id, form=form, include_pre_evolutions=True)
        if not move_ids:
            move_ids = sorted(self.catalogs.moves_by_id.keys(), key=str.casefold)
        pairs: list[tuple[str, str]] = []
        for move_id in move_ids:
            label = self._team_move_label_for_id(move_id)
            if any(existing == label for existing, _mid in pairs):
                label = f"{label} [{move_id}]"
            pairs.append((label, move_id))
        pairs.sort(key=lambda row: row[0].casefold())
        labels = ["(None)"]
        for label, move_id in pairs:
            labels.append(label)
            label_to_id[label] = move_id
            id_to_label.setdefault(move_id, label)
        return labels, label_to_id, id_to_label

    def _team_species_picker_choice_data(self) -> tuple[list[str], dict[str, str], dict[str, str]]:
        values = self._damage_species_choice_values()
        label_to_id: dict[str, str] = {}
        id_to_label: dict[str, str] = {}
        labels: list[str] = []
        for species_id in values:
            sid = str(species_id or "").strip()
            if not sid:
                continue
            label = self._english_species_name_for_id(sid)
            if label in label_to_id:
                label = f"{label} [{sid}]"
            labels.append(label)
            label_to_id[label] = sid
            id_to_label.setdefault(sid, label)
        return labels, label_to_id, id_to_label

    def _team_card_ability_choice_data(
        self,
        species_id: str,
        form: int,
    ) -> tuple[list[str], dict[str, str], dict[str, str]]:
        label_to_id: dict[str, str] = {"Ability": ""}
        id_to_label: dict[str, str] = {"": "Ability"}
        if not self.catalogs or not species_id:
            return ["Ability"], label_to_id, id_to_label
        ability_ids, hidden_ids = self.catalogs.valid_abilities_for_species(species_id, form=form)
        if not ability_ids:
            ability_ids = sorted(self.catalogs.abilities_by_id.keys(), key=str.casefold)
            hidden_ids = set()
        pairs: list[tuple[str, str]] = []
        for ability_id in ability_ids:
            label = self._ability_label_for_id(ability_id, set(hidden_ids))
            if any(existing == label for existing, _aid in pairs):
                label = f"{label} [{ability_id}]"
            pairs.append((label, ability_id))
        pairs.sort(key=lambda row: row[0].casefold())
        labels: list[str] = []
        for label, ability_id in pairs:
            labels.append(label)
            label_to_id[label] = ability_id
            id_to_label.setdefault(ability_id, label)
        if not labels:
            return ["Ability"], label_to_id, id_to_label
        return labels, label_to_id, id_to_label

    def _build_team_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Team Builder")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.team_tab = tab

        team_scroll_shell = ttk.Frame(tab)
        team_scroll_shell.grid(row=0, column=0, sticky="nsew")
        team_scroll_shell.columnconfigure(0, weight=1)
        team_scroll_shell.rowconfigure(0, weight=1)

        self.team_scroll_canvas = tk.Canvas(team_scroll_shell, highlightthickness=0)
        self.team_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.team_scrollbar = ttk.Scrollbar(team_scroll_shell, orient="vertical", command=self.team_scroll_canvas.yview)
        self.team_scrollbar.grid(row=0, column=1, sticky="ns")
        self.team_scroll_canvas.configure(yscrollcommand=self.team_scrollbar.set)

        workspace = ttk.Frame(self.team_scroll_canvas)
        self.team_scroll_window = self.team_scroll_canvas.create_window((0, 0), window=workspace, anchor="nw")
        workspace.columnconfigure(0, weight=3, minsize=420)
        workspace.columnconfigure(1, weight=2, minsize=360)
        workspace.rowconfigure(0, weight=1)
        self.team_top_shell = workspace

        slots_shell = ttk.LabelFrame(workspace, text="Team Slots", padding=8)
        slots_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        slots_shell.columnconfigure(0, weight=1)
        slots_shell.rowconfigure(2, weight=1)
        self.team_slots_shell = slots_shell

        self.team_active_slot_var = tk.StringVar(value="Editing Slot 1")
        ttk.Label(slots_shell, textvariable=self.team_active_slot_var, font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Label(
            slots_shell,
            text="Left-click a slot card to edit that Pokemon.",
            foreground="#666666",
        ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        cards_grid = ttk.Frame(slots_shell)
        cards_grid.grid(row=2, column=0, sticky="nsew")
        try:
            cards_grid.grid_anchor("nw")
        except Exception:
            pass
        self.team_cards_grid = cards_grid

        self._team_slot_ui: list[dict[str, Any]] = []
        if not self._team_slots or len(self._team_slots) != 6:
            self._team_slots = [self._team_default_slot_data() for _ in range(6)]
        for idx in range(6):
            self._build_team_slot_card(cards_grid, idx)

        actions = ttk.Frame(slots_shell)
        actions.grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Button(actions, text="Load Party", command=self._team_load_from_party).pack(side="left")
        ttk.Button(actions, text="Clear Team", command=self._team_clear_slots).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Add All to Party", command=self._team_add_all_to_party).pack(side="left", padx=(6, 0))

        right_shell = ttk.LabelFrame(workspace, text="Selected Pokemon", padding=8)
        right_shell.grid(row=0, column=1, sticky="nsew")
        right_shell.columnconfigure(0, weight=1)
        right_shell.rowconfigure(0, weight=0)
        right_shell.rowconfigure(1, weight=1)
        right_shell.rowconfigure(2, weight=1)
        right_shell.rowconfigure(3, weight=0)
        self.team_editor_shell = right_shell

        hidden_controls = ttk.Frame(right_shell)
        hidden_controls.grid(row=99, column=0, sticky="ew")
        hidden_controls.grid_remove()
        self.team_hidden_controls = hidden_controls

        editor_fields = ttk.Frame(hidden_controls)
        editor_fields.grid(row=0, column=0, sticky="ew")
        editor_fields.columnconfigure(0, weight=1, uniform="team_editor_fields")
        editor_fields.columnconfigure(1, weight=1, uniform="team_editor_fields")
        self.team_editor_fields = editor_fields
        self._team_editor_field_frames: dict[str, ttk.Frame] = {}

        def _make_field(key: str, label_text: str | None) -> tuple[ttk.Frame, int]:
            frame = ttk.Frame(editor_fields)
            if label_text:
                frame.columnconfigure(1, weight=1)
                ttk.Label(frame, text=label_text).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
                input_col = 1
            else:
                frame.columnconfigure(0, weight=1)
                input_col = 0
            self._team_editor_field_frames[key] = frame
            return frame, input_col

        self.team_species_var = tk.StringVar()
        self.team_form_var = tk.StringVar(value="0")
        self.team_level_var = tk.StringVar(value="50")
        self.team_shiny_var = tk.BooleanVar(value=False)
        self.team_nature_var = tk.StringVar()
        self.team_ability_var = tk.StringVar(value="(None)")
        self.team_item_var = tk.StringVar(value="(None)")
        self.team_move_vars = [tk.StringVar(value="(None)") for _ in range(4)]
        self._team_ability_label_to_id: dict[str, str] = {}
        self._team_ability_id_to_label: dict[str, str] = {}
        self._team_move_label_to_id: dict[str, str] = {}
        self._team_move_id_to_label: dict[str, str] = {}

        species_values = self._damage_species_choice_values()
        item_labels = self._team_item_choice_labels()
        nature_labels = self._team_nature_choice_labels()

        species_row, species_col = _make_field("species", "Species")
        self.team_species_combo = ttk.Combobox(species_row, textvariable=self.team_species_var)
        self.team_species_combo.grid(row=0, column=species_col, sticky="ew", pady=2)
        self._set_combo_values(self.team_species_combo, species_values)
        self._enable_combo_search(self.team_species_combo)
        self._register_combo_tooltip_context(self.team_species_combo, kind="species", resolver=self.resolve_species_id)

        form_row, form_col = _make_field("form", "Form")
        self.team_form_entry = ttk.Entry(form_row, textvariable=self.team_form_var, width=8)
        self.team_form_entry.grid(row=0, column=form_col, sticky="w", pady=2)

        level_row, level_col = _make_field("level", "Level")
        self.team_level_entry = ttk.Entry(level_row, textvariable=self.team_level_var, width=8)
        self.team_level_entry.grid(row=0, column=level_col, sticky="w", pady=2)

        nature_row, nature_col = _make_field("nature", "Nature")
        self.team_nature_combo = ttk.Combobox(nature_row, textvariable=self.team_nature_var)
        self.team_nature_combo.grid(row=0, column=nature_col, sticky="ew", pady=2)
        self._set_combo_values(self.team_nature_combo, nature_labels)
        self._enable_combo_search(self.team_nature_combo)
        self._register_combo_tooltip_context(self.team_nature_combo, kind="nature", resolver=self._team_resolve_selected_nature_id)

        shiny_row, shiny_col = _make_field("shiny", None)
        self.team_shiny_check = tk.Checkbutton(
            shiny_row,
            text="Shiny",
            variable=self.team_shiny_var,
            command=self._team_editor_field_changed,
        )
        self.team_shiny_check.grid(row=0, column=shiny_col, sticky="w", pady=2)

        ability_row, ability_col = _make_field("ability", "Ability")
        self.team_ability_combo = ttk.Combobox(ability_row, textvariable=self.team_ability_var)
        self.team_ability_combo.grid(row=0, column=ability_col, sticky="ew", pady=2)
        self._set_combo_values(self.team_ability_combo, ["(None)"])
        self._enable_combo_search(self.team_ability_combo)
        self._register_combo_tooltip_context(self.team_ability_combo, kind="ability", resolver=self._team_resolve_selected_ability_id)

        item_row, item_col = _make_field("item", "Held Item")
        self.team_item_combo = ttk.Combobox(item_row, textvariable=self.team_item_var)
        self.team_item_combo.grid(row=0, column=item_col, sticky="ew", pady=2)
        self._set_combo_values(self.team_item_combo, item_labels)
        self._enable_combo_search(self.team_item_combo)
        self._register_combo_tooltip_context(self.team_item_combo, kind="item", resolver=self._team_resolve_selected_item_id)

        self.team_move_combos: list[ttk.Combobox] = []
        for idx in range(4):
            key = f"move{idx + 1}"
            row_frame, row_col = _make_field(key, f"Move {idx + 1}")
            combo = ttk.Combobox(row_frame, textvariable=self.team_move_vars[idx])
            combo.grid(row=0, column=row_col, sticky="ew", pady=2)
            self._set_combo_values(combo, ["(None)"])
            self._enable_combo_search(combo)
            self._register_combo_tooltip_context(combo, kind="move", resolver=self._team_resolve_selected_move_id)
            combo.bind("<<ComboboxSelected>>", self._team_editor_field_changed, add="+")
            combo.bind("<FocusOut>", self._team_editor_field_changed, add="+")
            self.team_move_combos.append(combo)

        for widget in (
            self.team_species_combo,
            self.team_nature_combo,
            self.team_ability_combo,
            self.team_item_combo,
        ):
            widget.bind("<<ComboboxSelected>>", self._team_editor_field_changed, add="+")
            widget.bind("<FocusOut>", self._team_editor_field_changed, add="+")
        for entry in (self.team_form_entry, self.team_level_entry):
            entry.bind("<FocusOut>", self._team_editor_field_changed, add="+")
            entry.bind("<Return>", self._team_editor_field_changed, add="+")

        self._layout_team_editor_fields(single_column=False)

        stats_shell = ttk.LabelFrame(right_shell, text="Selected Slot Details", padding=6)
        stats_shell.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        stats_shell.columnconfigure(0, weight=0, minsize=56)
        stats_shell.columnconfigure(1, weight=0, minsize=54)
        stats_shell.columnconfigure(2, weight=1, minsize=110)
        stats_shell.columnconfigure(3, weight=1, minsize=110)
        stats_shell.columnconfigure(4, weight=0, minsize=60)
        self.team_stats_shell = stats_shell

        self.team_detail_species_var = tk.StringVar(value="(Empty)")
        self.team_detail_meta_var = tk.StringVar(value="Lv -")
        self.team_detail_ability_var = tk.StringVar(value="Ability: (None)")
        self.team_detail_item_var = tk.StringVar(value="Item: (None)")
        ttk.Label(stats_shell, textvariable=self.team_detail_ability_var).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        ttk.Label(stats_shell, textvariable=self.team_detail_item_var).grid(
            row=0, column=2, columnspan=3, sticky="w", pady=(0, 2)
        )
        self.team_detail_types_host = ttk.Frame(stats_shell)
        self.team_detail_types_host.grid(row=1, column=0, columnspan=5, sticky="w", pady=(0, 4))

        ttk.Label(stats_shell, text="Stat", font=("", 9, "bold")).grid(row=2, column=0, sticky="w", padx=(0, 4))
        ttk.Label(stats_shell, text="Base", font=("", 9, "bold")).grid(row=2, column=1, sticky="w", padx=(0, 4))
        ttk.Label(stats_shell, text="IV", font=("", 9, "bold")).grid(row=2, column=2, sticky="w", padx=(0, 4))
        ttk.Label(stats_shell, text="EV", font=("", 9, "bold")).grid(row=2, column=3, sticky="w", padx=(0, 4))
        ttk.Label(stats_shell, text="Final", font=("", 9, "bold")).grid(row=2, column=4, sticky="w")

        self.team_base_stat_vars: dict[str, tk.StringVar] = {}
        self.team_iv_vars: dict[str, tk.StringVar] = {}
        self.team_ev_vars: dict[str, tk.StringVar] = {}
        self.team_final_stat_vars: dict[str, tk.StringVar] = {}
        for row_idx, (stat_id, short_label) in enumerate(STAT_ORDER, start=3):
            ttk.Label(stats_shell, text=short_label).grid(row=row_idx, column=0, sticky="w", padx=(0, 4), pady=1)
            base_var = tk.StringVar(value="0")
            iv_var = tk.StringVar(value="31")
            ev_var = tk.StringVar(value="0")
            final_var = tk.StringVar(value="0")
            self.team_base_stat_vars[stat_id] = base_var
            self.team_iv_vars[stat_id] = iv_var
            self.team_ev_vars[stat_id] = ev_var
            self.team_final_stat_vars[stat_id] = final_var

            ttk.Label(stats_shell, textvariable=base_var).grid(row=row_idx, column=1, sticky="w", padx=(0, 4), pady=1)
            iv_entry = ttk.Entry(stats_shell, textvariable=iv_var, width=4)
            iv_entry.grid(row=row_idx, column=2, sticky="w", padx=(0, 4), pady=1)
            iv_entry.bind("<FocusOut>", lambda _e, sid=stat_id: self._team_iv_ev_field_changed("iv", sid), add="+")
            iv_entry.bind("<Return>", lambda _e, sid=stat_id: self._team_iv_ev_field_changed("iv", sid), add="+")
            ev_entry = ttk.Entry(stats_shell, textvariable=ev_var, width=4)
            ev_entry.grid(row=row_idx, column=3, sticky="w", padx=(0, 4), pady=1)
            ev_entry.bind("<FocusOut>", lambda _e, sid=stat_id: self._team_iv_ev_field_changed("ev", sid), add="+")
            ev_entry.bind("<Return>", lambda _e, sid=stat_id: self._team_iv_ev_field_changed("ev", sid), add="+")
            ttk.Label(stats_shell, textvariable=final_var).grid(row=row_idx, column=4, sticky="w", pady=1)

        self.team_hidden_power_var = tk.StringVar(value="Unknown")
        ttk.Label(stats_shell, text="HP Type").grid(row=9, column=1, sticky="e", pady=(6, 2), padx=(0, 6))
        self.team_hidden_power_chip_host = ttk.Frame(stats_shell)
        self.team_hidden_power_chip_host.grid(row=9, column=2, sticky="w", pady=(6, 2))
        self._render_type_chip_row(self.team_hidden_power_chip_host, [], short=False, empty_text="Unknown")
        self.team_max_evs_btn = ttk.Button(stats_shell, text="Max EVs", command=self._team_set_max_evs)
        self.team_max_evs_btn.grid(row=9, column=3, sticky="w", padx=(8, 0), pady=(6, 2))

        stats_actions = ttk.Frame(hidden_controls)
        stats_actions.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        stats_actions.columnconfigure(1, weight=1)

        ttk.Button(stats_actions, text="Max IVs", command=self._team_set_max_ivs).grid(row=0, column=0, sticky="w")
        self.team_ev_preset_var = tk.StringVar(value="252 Atk / 252 Spe / 4 HP")
        self.team_ev_preset_combo = ttk.Combobox(
            stats_actions,
            textvariable=self.team_ev_preset_var,
            state="readonly",
            values=[
                "252 Atk / 252 Spe / 4 HP",
                "252 SpA / 252 Spe / 4 HP",
                "252 HP / 252 Def / 4 SpD",
                "252 HP / 252 SpD / 4 Def",
                "0 EVs",
            ],
        )
        self.team_ev_preset_combo.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(stats_actions, text="Apply EV Preset", command=self._team_apply_ev_preset).grid(
            row=0, column=2, sticky="w"
        )

        self.team_stats_note_var = tk.StringVar(value="IV cap 31 each (sum 186) | EV cap 252 each (no total cap)")
        ttk.Label(stats_shell, textvariable=self.team_stats_note_var, foreground="#606060").grid(
            row=10, column=0, columnspan=5, sticky="w", pady=(4, 0)
        )

        analysis_shell = ttk.LabelFrame(right_shell, text="Team Matchups", padding=8)
        analysis_shell.grid(row=1, column=0, sticky="nsew")
        analysis_shell.columnconfigure(0, weight=1)
        analysis_shell.rowconfigure(0, weight=1)
        analysis_shell.rowconfigure(1, weight=1)
        analysis_shell.rowconfigure(2, weight=0)
        self.team_analysis_shell = analysis_shell

        self.team_defense_section = ttk.LabelFrame(analysis_shell, text="Team Defence", padding=6)
        self.team_defense_section.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.team_defense_body = ttk.Frame(self.team_defense_section)
        self.team_defense_body.pack(fill="both", expand=True)

        self.team_offense_section = ttk.LabelFrame(analysis_shell, text="Team Type Coverage", padding=6)
        self.team_offense_section.grid(row=1, column=0, sticky="nsew")
        self.team_offense_body = ttk.Frame(self.team_offense_section)
        self.team_offense_body.pack(fill="both", expand=True)

        self.team_matchup_summary_var = tk.StringVar(value="No Pokemon selected.")
        ttk.Label(analysis_shell, textvariable=self.team_matchup_summary_var, foreground="#606060").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )

        type_chart_row = ttk.Frame(right_shell)
        type_chart_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        type_chart_row.columnconfigure(0, weight=1)
        ttk.Label(
            type_chart_row,
            text="Open full attack/defense type matrix in a popup.",
            foreground="#666666",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(type_chart_row, text="TYPE CHART", command=self._open_team_type_chart_popup).grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )

        workspace.bind("<Configure>", self._on_team_workspace_configure, add="+")
        workspace.bind("<Configure>", self._apply_team_tab_layout, add="+")
        self.team_scroll_canvas.bind("<Configure>", self._on_team_canvas_configure, add="+")
        self.team_scroll_canvas.bind("<MouseWheel>", self._on_team_tab_mousewheel, add="+")
        self.team_scroll_canvas.bind("<Button-4>", self._on_team_tab_mousewheel, add="+")
        self.team_scroll_canvas.bind("<Button-5>", self._on_team_tab_mousewheel, add="+")
        self._bind_team_content_mousewheel_recursive(workspace)
        cards_grid.bind("<Configure>", self._apply_team_cards_layout, add="+")
        right_shell.bind("<Configure>", self._apply_team_tab_layout, add="+")
        tab.after(20, self._apply_team_tab_layout)
        tab.after(40, self._apply_team_cards_layout)

        self._team_selected_slot = max(0, min(int(self._team_selected_slot), 5))
        self.refresh_team_tab()
        self._team_select_slot(self._team_selected_slot)

    def _layout_team_editor_fields(self, single_column: bool):
        if not hasattr(self, "team_editor_fields"):
            return
        frames = getattr(self, "_team_editor_field_frames", {})
        if not isinstance(frames, dict):
            return
        for frame in frames.values():
            try:
                frame.grid_forget()
            except Exception:
                pass
        if single_column:
            self.team_editor_fields.columnconfigure(0, weight=1, minsize=0)
            self.team_editor_fields.columnconfigure(1, weight=0, minsize=0)
            order = [
                "species",
                "form",
                "level",
                "nature",
                "shiny",
                "ability",
                "item",
                "move1",
                "move2",
                "move3",
                "move4",
            ]
            for row, key in enumerate(order):
                frame = frames.get(key)
                if frame is not None:
                    frame.grid(row=row, column=0, sticky="ew", pady=1)
        else:
            self.team_editor_fields.columnconfigure(0, weight=1, minsize=0)
            self.team_editor_fields.columnconfigure(1, weight=1, minsize=0)
            pairs = [
                ("species", "form"),
                ("level", "nature"),
                ("shiny", "ability"),
                ("item", None),
                ("move1", "move2"),
                ("move3", "move4"),
            ]
            for row, (left_key, right_key) in enumerate(pairs):
                left_frame = frames.get(left_key)
                if left_frame is not None:
                    left_frame.grid(row=row, column=0, sticky="ew", padx=(0, 6), pady=1)
                right_frame = frames.get(right_key) if right_key else None
                if right_frame is not None:
                    right_frame.grid(row=row, column=1, sticky="ew", padx=(6, 0), pady=1)
        self._team_editor_single_col = bool(single_column)

    def _on_team_workspace_configure(self, _event=None):
        canvas = getattr(self, "team_scroll_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            return

    def _on_team_canvas_configure(self, event):
        canvas = getattr(self, "team_scroll_canvas", None)
        window_id = getattr(self, "team_scroll_window", None)
        if canvas is None or window_id is None:
            return
        try:
            canvas.itemconfigure(window_id, width=max(1, int(event.width)))
        except Exception:
            return
        self._on_team_workspace_configure()
        self._apply_team_tab_layout()

    def _bind_team_content_mousewheel_recursive(self, widget):
        if widget is None:
            return
        key = str(widget)
        if key not in self._team_wheel_bound_widgets:
            try:
                widget.bind("<MouseWheel>", self._on_team_tab_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_team_tab_mousewheel, add="+")
                widget.bind("<Button-5>", self._on_team_tab_mousewheel, add="+")
                self._team_wheel_bound_widgets.add(key)
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._bind_team_content_mousewheel_recursive(child)

    def _on_team_tab_mousewheel(self, event):
        canvas = getattr(self, "team_scroll_canvas", None)
        team_tab = getattr(self, "team_tab", None)
        if canvas is None or team_tab is None:
            return
        try:
            selected_tab = self.nb.nametowidget(self.nb.select())
        except Exception:
            selected_tab = None
        if str(selected_tab) != str(team_tab):
            return
        active_popdown_listbox = self._find_active_combo_popdown_listbox()
        if active_popdown_listbox is not None:
            return self._on_combo_popdown_listbox_wheel(event, active_popdown_listbox)
        target = getattr(event, "widget", None)
        try:
            hovered = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
        except Exception:
            hovered = None
        # bind_all events can keep target on a focused widget inside Team canvas
        # even when pointer is currently over a combobox popdown listbox.
        # Prioritize hovered widget so popup list scrolling doesn't trigger global scroll.
        if hovered is not None:
            if not self._is_widget_descendant(hovered, canvas):
                return
        elif not self._is_widget_descendant(target, canvas):
            return
        return self._scroll_canvas_mousewheel(canvas, event)

    def _apply_team_tab_layout(self, _event=None):
        top_shell = getattr(self, "team_top_shell", None)
        slots_shell = getattr(self, "team_slots_shell", None)
        editor_shell = getattr(self, "team_editor_shell", None)
        if top_shell is None or slots_shell is None or editor_shell is None:
            return
        try:
            width = int(top_shell.winfo_width())
        except Exception:
            width = 0
        if width <= 1:
            try:
                top_shell.after(40, self._apply_team_tab_layout)
            except Exception:
                pass
            return

        mode = "split"
        if self._team_layout_mode != mode:
            try:
                slots_shell.grid_forget()
                editor_shell.grid_forget()
            except Exception:
                pass
            slots_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
            editor_shell.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
            self._team_layout_mode = mode
        top_shell.columnconfigure(0, weight=3, minsize=(420 if width >= 1100 else 340))
        top_shell.columnconfigure(1, weight=2, minsize=(360 if width >= 1100 else 300))
        top_shell.rowconfigure(0, weight=1)
        top_shell.rowconfigure(1, weight=0)

        try:
            editor_width = int(editor_shell.winfo_width())
        except Exception:
            editor_width = 0
        single_col = editor_width > 0 and editor_width < 640
        if single_col != self._team_editor_single_col:
            self._layout_team_editor_fields(single_column=single_col)

        self._apply_team_cards_layout()

    def _apply_team_cards_layout(self, _event=None):
        cards_grid = getattr(self, "team_cards_grid", None)
        if cards_grid is None:
            return
        try:
            width = int(cards_grid.winfo_width())
        except Exception:
            width = 0
        if width <= 1:
            try:
                cards_grid.after(40, self._apply_team_cards_layout)
            except Exception:
                pass
            return

        if width >= 380:
            cols = 2
        else:
            cols = 1
        if cols == self._team_cards_cols:
            return
        self._team_cards_cols = cols

        for i in range(6):
            cards_grid.columnconfigure(i, weight=0, minsize=0)
            cards_grid.rowconfigure(i, weight=0, minsize=0)
        for c in range(cols):
            cards_grid.columnconfigure(c, weight=1)
        rows = int(math.ceil(6 / max(1, cols)))
        for r in range(rows):
            cards_grid.rowconfigure(r, weight=0)

        for idx, ui in enumerate(getattr(self, "_team_slot_ui", [])):
            card = ui.get("card")
            if card is None:
                continue
            row = idx // cols
            col = idx % cols
            card.grid_configure(row=row, column=col, sticky="ew", padx=3, pady=3)

    @staticmethod
    def _team_nature_multiplier(stat_id: str, nature_id: str) -> int:
        up, down = NATURE_EFFECTS.get(str(nature_id or "").strip().upper(), (None, None))
        if stat_id == up:
            return 110
        if stat_id == down:
            return 90
        return 100

    def _team_calc_stat_value(self, stat_id: str, base: int, level: int, iv: int, ev: int, nature_id: str) -> int:
        if stat_id == "HP":
            if base == 1:
                return 1
            return (((base * 2) + iv + (ev // 4)) * level // 100) + level + 10
        core_val = (((base * 2) + iv + (ev // 4)) * level // 100) + 5
        return (core_val * self._team_nature_multiplier(stat_id, nature_id)) // 100

    def _team_clamped_ivs(self, raw_values: dict[str, Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            out[sid] = self._clamp_int(str(raw_values.get(sid, 31)), 0, 31, 31)
        total = sum(out.values())
        if total > 186:
            overflow = total - 186
            for sid, _label in reversed(STAT_ORDER):
                if overflow <= 0:
                    break
                reducible = min(overflow, out[sid])
                out[sid] -= reducible
                overflow -= reducible
        return out

    def _team_clamped_evs(
        self,
        raw_values: dict[str, Any],
        preferred_stat: str | None = None,
    ) -> dict[str, int]:
        out: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            out[sid] = self._clamp_int(str(raw_values.get(sid, 0)), 0, 252, 0)
        if self._is_party_ev_basic_mode():
            return self._normalize_basic_ev_values(out, preferred_stat=preferred_stat)
        total = sum(out.values())
        if total > 1512:
            overflow = total - 1512
            for sid, _label in reversed(STAT_ORDER):
                if overflow <= 0:
                    break
                reducible = min(overflow, out[sid])
                out[sid] -= reducible
                overflow -= reducible
        return out

    def _team_normalize_slot_stats(self, slot: dict[str, Any]):
        if not isinstance(slot, dict):
            return
        ivs = slot.get("ivs", {})
        if not isinstance(ivs, dict):
            ivs = {}
        evs = slot.get("evs", {})
        if not isinstance(evs, dict):
            evs = {}
        slot["ivs"] = self._team_clamped_ivs(ivs)
        slot["evs"] = self._team_clamped_evs(evs)

    def _team_current_iv_values(self) -> dict[str, int]:
        raw: dict[str, Any] = {}
        if hasattr(self, "team_iv_vars"):
            for sid, _label in STAT_ORDER:
                raw[sid] = self.team_iv_vars[sid].get()
        return self._team_clamped_ivs(raw)

    def _team_current_ev_values(self, preferred_stat: str | None = None) -> dict[str, int]:
        raw: dict[str, Any] = {}
        if hasattr(self, "team_ev_vars"):
            for sid, _label in STAT_ORDER:
                raw[sid] = self.team_ev_vars[sid].get()
        return self._team_clamped_evs(raw, preferred_stat=preferred_stat)

    def _team_refresh_stat_editor(self):
        if not hasattr(self, "team_base_stat_vars"):
            return
        species_id, form = self._team_species_form_from_editor()
        base_stats = self.catalogs.base_stats_for_species(species_id, form=form) if self.catalogs and species_id else {}
        level = self._clamp_int(self.team_level_var.get(), 1, 100, 50)
        self.team_level_var.set(str(level))
        nature_id = self._team_resolve_selected_nature_id(self.team_nature_var.get())
        ivs = self._team_current_iv_values()
        evs = self._team_current_ev_values()
        for sid, _label in STAT_ORDER:
            self.team_iv_vars[sid].set(str(ivs[sid]))
            self.team_ev_vars[sid].set(str(evs[sid]))
            base_value = int(base_stats.get(sid, 0))
            self.team_base_stat_vars[sid].set(str(base_value))
            final_value = self._team_calc_stat_value(sid, base_value, level, ivs[sid], evs[sid], nature_id)
            self.team_final_stat_vars[sid].set(str(final_value))
        hidden_power_type = self._hidden_power_type_from_ivs(ivs)
        if hasattr(self, "team_hidden_power_var"):
            self.team_hidden_power_var.set(hidden_power_type)
        if hasattr(self, "team_hidden_power_chip_host"):
            hp_ids = self._extract_type_ids(hidden_power_type)
            self._render_type_chip_row(
                self.team_hidden_power_chip_host,
                hp_ids,
                short=False,
                empty_text=hidden_power_type or "Unknown",
            )
        self._team_apply_ev_mode_ui()
        self._team_refresh_detail_panel()

    def _team_apply_ev_mode_ui(self):
        if not hasattr(self, "team_stats_note_var"):
            return
        ev_total = sum(self._team_current_ev_values().values())
        if self._is_party_ev_basic_mode():
            if hasattr(self, "team_max_evs_btn"):
                self.team_max_evs_btn.grid_remove()
            self.team_stats_note_var.set(
                f"IV cap 31 each (sum 186) | EV cap 252 each | Total EV cap 510 ({ev_total}/510)"
            )
        else:
            if hasattr(self, "team_max_evs_btn"):
                self.team_max_evs_btn.grid()
            self.team_stats_note_var.set(
                f"IV cap 31 each (sum 186) | EV cap 252 each | Total EV cap 1512 ({ev_total}/1512)"
            )

    def _team_refresh_detail_panel(self):
        if not hasattr(self, "team_detail_species_var"):
            return
        species_id, form = self._team_species_form_from_editor()
        has_species = bool(species_id)
        level = self._clamp_int(self.team_level_var.get() if hasattr(self, "team_level_var") else "50", 1, 100, 50)
        shiny = bool(self.team_shiny_var.get()) if hasattr(self, "team_shiny_var") else False

        species_label = self._english_species_name_for_id(species_id) if has_species else "(Empty)"
        self.team_detail_species_var.set(species_label)
        if has_species:
            meta_parts = [f"Lv {level}"]
            if int(form) > 0:
                meta_parts.append(f"Form {int(form)}")
            if shiny:
                meta_parts.append("Shiny")
            self.team_detail_meta_var.set(" | ".join(meta_parts))
        else:
            self.team_detail_meta_var.set("Lv -")

        ability_id = self._team_resolve_selected_ability_id(self.team_ability_var.get() if hasattr(self, "team_ability_var") else "")
        item_id = self._team_resolve_selected_item_id(self.team_item_var.get() if hasattr(self, "team_item_var") else "")
        ability_label = self._english_ability_name_for_id(ability_id) if ability_id else "(None)"
        item_label = self._english_item_name_for_id(item_id) if item_id else "(None)"
        self.team_detail_ability_var.set(f"Ability: {ability_label}")
        self.team_detail_item_var.set(f"Item: {item_label}")

        host = getattr(self, "team_detail_types_host", None)
        if host is None:
            return
        for child in host.winfo_children():
            child.destroy()
        if not has_species:
            ttk.Label(host, text="Type: (None)").grid(row=0, column=0, sticky="w")
            return
        type_ids = self._dex_species_type_ids(species_id, form=int(form))
        if not type_ids:
            ttk.Label(host, text="Type: (Unknown)").grid(row=0, column=0, sticky="w")
            return
        for idx, tid in enumerate(type_ids):
            chip = self._dex_make_type_chip(host, tid, short=False)
            chip.grid(row=0, column=idx, sticky="w", padx=(0, 6), pady=0)

    def _team_set_max_ivs(self):
        if not hasattr(self, "team_iv_vars"):
            return
        for sid, _label in STAT_ORDER:
            self.team_iv_vars[sid].set("31")
        self._team_refresh_stat_editor()
        self._team_apply_editor_to_selected_slot(refresh_legality=False)

    def _team_set_max_evs(self):
        if not hasattr(self, "team_ev_vars"):
            return
        raw_target = {sid: 252 for sid, _label in STAT_ORDER}
        values = self._team_clamped_evs(raw_target)
        for sid, _label in STAT_ORDER:
            self.team_ev_vars[sid].set(str(values[sid]))
        self._team_refresh_stat_editor()
        self._team_apply_editor_to_selected_slot(refresh_legality=False)

    def _team_apply_ev_preset(self):
        if not hasattr(self, "team_ev_vars"):
            return
        preset = str(self.team_ev_preset_var.get() if hasattr(self, "team_ev_preset_var") else "").strip()
        values = {sid: 0 for sid, _label in STAT_ORDER}
        if preset == "252 Atk / 252 Spe / 4 HP":
            values["ATTACK"] = 252
            values["SPEED"] = 252
            values["HP"] = 4
        elif preset == "252 SpA / 252 Spe / 4 HP":
            values["SPECIAL_ATTACK"] = 252
            values["SPEED"] = 252
            values["HP"] = 4
        elif preset == "252 HP / 252 Def / 4 SpD":
            values["HP"] = 252
            values["DEFENSE"] = 252
            values["SPECIAL_DEFENSE"] = 4
        elif preset == "252 HP / 252 SpD / 4 Def":
            values["HP"] = 252
            values["SPECIAL_DEFENSE"] = 252
            values["DEFENSE"] = 4
        for sid, _label in STAT_ORDER:
            self.team_ev_vars[sid].set(str(values[sid]))
        self._team_refresh_stat_editor()
        self._team_apply_editor_to_selected_slot(refresh_legality=False)

    def _team_iv_ev_field_changed(self, kind: str, _stat_id: str):
        if self._team_syncing:
            return "break"
        if kind == "iv":
            values = self._team_current_iv_values()
            for sid, _label in STAT_ORDER:
                self.team_iv_vars[sid].set(str(values[sid]))
        else:
            values = self._team_current_ev_values(preferred_stat=_stat_id)
            for sid, _label in STAT_ORDER:
                self.team_ev_vars[sid].set(str(values[sid]))
        self._team_refresh_stat_editor()
        self._team_apply_editor_to_selected_slot(refresh_legality=False)
        return "break"

    def _build_team_slot_card(self, parent, index: int):
        card = ttk.LabelFrame(parent, text=f"Slot {index + 1}", padding=6)
        card.grid(row=index // 3, column=index % 3, sticky="ew", padx=3, pady=3)
        card.columnconfigure(0, weight=0)
        card.columnconfigure(1, weight=1)
        card.rowconfigure(0, weight=0)
        card.rowconfigure(1, weight=0)

        sprite_wrap = ttk.Frame(card)
        sprite_wrap.grid(row=0, column=0, sticky="nw", padx=(0, 8))
        sprite_wrap.columnconfigure(0, weight=1)
        canvas = tk.Canvas(
            sprite_wrap,
            width=94,
            height=88,
            bg="#f6f6f6",
            highlightthickness=1,
            highlightbackground="#bdbdbd",
        )
        canvas.grid(row=0, column=0, sticky="nw")
        placeholder = tk.PhotoImage(width=80, height=80)
        image_id = canvas.create_image(47, 38, image=placeholder, anchor="center")
        text_id = canvas.create_text(47, 78, text="Empty", fill="#5f5f5f", font=("", 8, "bold"), anchor="s")
        name_var = tk.StringVar(value="(Empty)")
        ttk.Label(sprite_wrap, textvariable=name_var, font=("", 9, "bold"), anchor="center").grid(
            row=1, column=0, sticky="ew", pady=(2, 0)
        )

        right = ttk.Frame(card)
        right.grid(row=0, column=1, sticky="new")
        right.columnconfigure(0, weight=1)

        move_vars: list[tk.StringVar] = []
        move_combos: list[ttk.Combobox] = []
        for i in range(4):
            move_var = tk.StringVar(value="(None)")
            move_vars.append(move_var)
            move_combo = ttk.Combobox(right, textvariable=move_var, width=18)
            move_combo.grid(row=i, column=0, sticky="ew", pady=(0, 2))
            self._set_combo_values(move_combo, ["(None)"])
            self._enable_combo_search(move_combo)
            self._register_combo_tooltip_context(move_combo, kind="move", resolver=self._team_resolve_selected_move_id)
            move_combo.bind(
                "<<ComboboxSelected>>",
                lambda _e, idx=index, move_idx=i: self._team_card_move_changed(idx, move_idx),
                add="+",
            )
            move_combo.bind(
                "<FocusOut>",
                lambda _e, idx=index, move_idx=i: self._team_card_move_changed(idx, move_idx),
                add="+",
            )
            move_combos.append(move_combo)

        info_row = ttk.Frame(card)
        info_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        info_row.columnconfigure(1, weight=1)

        ttk.Label(info_row, text="Lv").grid(row=0, column=0, sticky="w")
        level_var = tk.StringVar(value="50")
        level_entry = ttk.Entry(info_row, textvariable=level_var, width=4)
        level_entry.grid(row=0, column=0, sticky="w", padx=(18, 0))
        level_entry.bind("<FocusOut>", lambda _e, idx=index: self._team_card_level_changed(idx), add="+")
        level_entry.bind("<Return>", lambda _e, idx=index: self._team_card_level_changed(idx), add="+")

        item_var = tk.StringVar(value="Item")
        item_combo = ttk.Combobox(info_row, textvariable=item_var, width=13)
        item_combo.grid(row=0, column=2, sticky="e", padx=(10, 6))
        self._set_combo_values(item_combo, ["Item"])
        self._enable_combo_search(item_combo)
        self._register_combo_tooltip_context(item_combo, kind="item", resolver=self._team_resolve_selected_item_id)
        item_combo.bind("<FocusIn>", lambda _e, idx=index: self._team_card_item_focus_in(idx), add="+")
        item_combo.bind("<<ComboboxSelected>>", lambda _e, idx=index: self._team_card_item_changed(idx), add="+")
        item_combo.bind("<FocusOut>", lambda _e, idx=index: self._team_card_item_focus_out(idx), add="+")

        ability_var = tk.StringVar(value="Ability")
        ability_combo = ttk.Combobox(info_row, textvariable=ability_var, width=14)
        ability_combo.grid(row=0, column=3, sticky="e")
        self._set_combo_values(ability_combo, ["Ability"])
        self._enable_combo_search(ability_combo)
        self._register_combo_tooltip_context(ability_combo, kind="ability", resolver=self._team_resolve_selected_ability_id)
        ability_combo.bind("<<ComboboxSelected>>", lambda _e, idx=index: self._team_card_ability_changed(idx), add="+")
        ability_combo.bind("<FocusOut>", lambda _e, idx=index: self._team_card_ability_changed(idx), add="+")

        meta_var = tk.StringVar(value="Lv -")

        bind_targets = [card, canvas, sprite_wrap, right, info_row]
        bind_targets.extend(child for child in right.winfo_children())
        bind_targets.extend(child for child in info_row.winfo_children())
        for target in bind_targets:
            self._team_bind_slot_card_select(target, index)
        try:
            # Click avatar to pick species for this slot directly.
            canvas.tag_bind(image_id, "<Button-1>", lambda e, idx=index: self._team_open_species_picker(idx, e))
            canvas.tag_bind(text_id, "<Button-1>", lambda e, idx=index: self._team_open_species_picker(idx, e))
        except Exception:
            pass
        canvas.bind("<Button-3>", lambda e, idx=index: self._team_open_avatar_context_menu(idx, e), add="+")
        canvas.bind("<Control-Button-1>", lambda e, idx=index: self._team_open_avatar_context_menu(idx, e), add="+")
        canvas.bind("<Configure>", lambda _e, idx=index: self._team_update_slot_card(idx), add="+")

        ui = {
            "card": card,
            "canvas": canvas,
            "image_id": image_id,
            "text_id": text_id,
            "sprite_placeholder": placeholder,
            "image_ref": placeholder,
            "name_var": name_var,
            "meta_var": meta_var,
            "level_var": level_var,
            "level_entry": level_entry,
            "item_var": item_var,
            "item_combo": item_combo,
            "item_label_to_id": {"Item": "", "(None)": ""},
            "item_id_to_label": {"": "Item"},
            "item_placeholder_active": True,
            "ability_var": ability_var,
            "ability_combo": ability_combo,
            "ability_label_to_id": {"Ability": ""},
            "ability_id_to_label": {"": "Ability"},
            "move_vars": move_vars,
            "move_combos": move_combos,
            "move_label_to_id": {"(None)": ""},
            "move_id_to_label": {"": "(None)"},
            "inline_species_key": ("", 0),
        }
        if len(self._team_slot_ui) <= index:
            self._team_slot_ui.append(ui)
        else:
            self._team_slot_ui[index] = ui

    def _team_bind_slot_card_select(self, widget, index: int):
        # Do not hijack clicks from interactive controls inside the card.
        interactive_types = (
            ttk.Combobox,
            ttk.Entry,
            ttk.Button,
            tk.Entry,
            tk.Button,
            tk.Checkbutton,
            tk.Spinbox,
            tk.Text,
        )
        try:
            if isinstance(widget, interactive_types):
                return
        except Exception:
            pass
        try:
            widget.bind("<Button-1>", lambda _e, idx=index: self._team_select_slot(idx), add="+")
        except Exception:
            return

    def _team_close_species_picker(self):
        popup = getattr(self, "_team_species_picker_popup", None)
        if popup is None:
            return
        try:
            popup.destroy()
        except Exception:
            pass
        self._team_species_picker_popup = None

    def _team_apply_species_to_slot(self, index: int, species_id: str):
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        sid = str(species_id or "").strip()
        if self.catalogs and sid:
            sid = self.catalogs.canonical_species_id(sid) or sid
        if not sid:
            self._team_clear_slot(idx)
            return
        self._team_select_slot(idx)
        self._team_syncing = True
        try:
            self.team_species_var.set(sid)
            self.team_form_var.set("0")
        finally:
            self._team_syncing = False
        self._team_apply_editor_to_selected_slot(refresh_legality=True)
        self._team_update_slot_card(idx)
        self._team_update_matchup_view()

    def _team_open_species_picker(self, index: int, event=None):
        if not self._team_slots:
            return "break"
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        self._team_select_slot(idx)
        self._team_close_species_picker()

        labels, label_to_id, id_to_label = self._team_species_picker_choice_data()
        popup = tk.Toplevel(self.root)
        popup.title(f"Choose Pokemon (Slot {idx + 1})")
        popup.resizable(False, False)
        try:
            popup.transient(self.root)
        except Exception:
            pass
        popup.protocol("WM_DELETE_WINDOW", self._team_close_species_picker)
        body = ttk.Frame(popup, padding=8)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="Species").grid(row=0, column=0, sticky="w")
        pick_var = tk.StringVar(value="")
        pick_combo = ttk.Combobox(body, textvariable=pick_var, width=34)
        pick_combo.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._set_combo_values(pick_combo, labels)
        self._enable_combo_search(pick_combo)
        self._register_combo_tooltip_context(
            pick_combo,
            kind="species",
            resolver=lambda raw, _label_to_id=label_to_id: _label_to_id.get(str(raw or "").strip(), self.resolve_species_id(raw)),
        )

        current_species = str(self._team_slots[idx].get("species_id", "")).strip()
        if current_species and current_species in id_to_label:
            pick_var.set(id_to_label[current_species])

        actions = ttk.Frame(body)
        actions.grid(row=2, column=0, sticky="e")

        def _apply():
            raw = pick_var.get().strip()
            species = label_to_id.get(raw, "")
            if not species and raw:
                try:
                    species = self.resolve_species_id(raw)
                except Exception:
                    species = extract_internal_id(raw).strip().lstrip(":")
            self._team_apply_species_to_slot(idx, species)
            self._team_close_species_picker()

        ttk.Button(actions, text="Set", command=_apply).pack(side="left")
        ttk.Button(
            actions,
            text="Clear",
            command=lambda: (self._team_apply_species_to_slot(idx, ""), self._team_close_species_picker()),
        ).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Cancel", command=self._team_close_species_picker).pack(side="left", padx=(6, 0))

        popup.bind("<Return>", lambda _e: _apply(), add="+")
        popup.bind("<Escape>", lambda _e: self._team_close_species_picker(), add="+")

        if event is not None:
            x = int(getattr(event, "x_root", self.root.winfo_pointerx())) + 8
            y = int(getattr(event, "y_root", self.root.winfo_pointery())) + 8
        else:
            x = int(self.root.winfo_pointerx()) + 8
            y = int(self.root.winfo_pointery()) + 8
        popup.geometry(f"+{x}+{y}")
        self._team_species_picker_popup = popup
        pick_combo.focus_set()
        pick_combo.icursor(tk.END)
        return "break"

    def _team_refresh_slot_inline_editors(self, index: int, species_id: str, form: int):
        if not hasattr(self, "_team_slot_ui") or index < 0 or index >= len(self._team_slot_ui):
            return
        ui = self._team_slot_ui[index]
        slot = self._team_slots[index]

        level_var = ui.get("level_var")
        if isinstance(level_var, tk.StringVar):
            level = self._clamp_int(str(slot.get("level", 50)), 1, 100, 50)
            level_var.set(str(level))

        item_combo = ui.get("item_combo")
        if item_combo is not None:
            item_labels, item_label_to_id, item_id_to_label = self._team_card_item_choice_data()
            ui["item_label_to_id"] = item_label_to_id
            ui["item_id_to_label"] = item_id_to_label
            self._set_combo_values(item_combo, item_labels)
            item_id = str(slot.get("item_id", "")).strip()
            label = item_id_to_label.get(item_id, "Item")
            if label not in item_labels:
                label = "Item"
                slot["item_id"] = ""
            ui["item_var"].set(label)
            ui["item_placeholder_active"] = (not item_id)
            try:
                item_combo.configure(state=("normal" if species_id else "disabled"))
            except Exception:
                pass

        ability_combo = ui.get("ability_combo")
        if ability_combo is not None:
            ability_labels, ability_label_to_id, ability_id_to_label = self._team_card_ability_choice_data(species_id, form)
            ui["ability_label_to_id"] = ability_label_to_id
            ui["ability_id_to_label"] = ability_id_to_label
            self._set_combo_values(ability_combo, ability_labels)
            ability_id = str(slot.get("ability_id", "")).strip()
            if not species_id:
                slot["ability_id"] = ""
                ui["ability_var"].set("Ability")
            else:
                if ability_id not in ability_id_to_label:
                    # Default to ability slot #1 when species changes or value is invalid.
                    first_label = ability_labels[0] if ability_labels else "Ability"
                    ui["ability_var"].set(first_label)
                    slot["ability_id"] = ability_label_to_id.get(first_label, "")
                else:
                    ui["ability_var"].set(ability_id_to_label[ability_id])
            try:
                ability_combo.configure(state=("normal" if species_id else "disabled"))
            except Exception:
                pass

        move_combos: list[ttk.Combobox] = list(ui.get("move_combos", []))
        move_vars: list[tk.StringVar] = list(ui.get("move_vars", []))
        species_key = (str(species_id), int(form))
        if ui.get("inline_species_key") != species_key:
            move_labels, move_label_to_id, move_id_to_label = self._team_card_move_choice_data(species_id, form)
            ui["move_label_to_id"] = move_label_to_id
            ui["move_id_to_label"] = move_id_to_label
            ui["inline_species_key"] = species_key
            for combo in move_combos:
                self._set_combo_values(combo, move_labels)

        move_id_to_label = dict(ui.get("move_id_to_label", {"": "(None)"}))
        allowed_moves = {mid for mid in move_id_to_label.keys() if mid}
        moves = slot.get("moves", [])
        if not isinstance(moves, list):
            moves = []
        while len(moves) < 4:
            moves.append("")
        for i, move_var in enumerate(move_vars[:4]):
            move_id = str(moves[i] if i < len(moves) else "").strip()
            if move_id and species_id and move_id not in allowed_moves:
                move_id = ""
                moves[i] = ""
            move_var.set(move_id_to_label.get(move_id, "(None)" if not move_id else self._team_move_label_for_id(move_id)))
        slot["moves"] = moves[:4]
        for combo in move_combos:
            try:
                combo.configure(state=("normal" if species_id else "disabled"))
            except Exception:
                pass

        level_entry = ui.get("level_entry")
        if level_entry is not None:
            try:
                level_entry.configure(state=("normal" if species_id else "disabled"))
            except Exception:
                pass

    def _team_card_item_changed(self, index: int):
        if self._team_syncing or not self._team_slots:
            return "break"
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        ui = self._team_slot_ui[idx]
        item_combo = ui.get("item_combo")
        slot = self._team_slots[idx]
        raw = str(ui.get("item_var").get() if ui.get("item_var") is not None else "").strip()
        placeholder_active = bool(ui.get("item_placeholder_active", False))
        if raw in {"", "(None)"} or (raw == "Item" and placeholder_active):
            slot["item_id"] = ""
            ui["item_placeholder_active"] = True
            self._team_update_slot_card(idx)
            if idx == self._team_selected_slot:
                self._team_load_slot_into_editor(idx)
            return "break"
        label_to_id = dict(ui.get("item_label_to_id", {"Item": "", "(None)": ""}))
        item_id = label_to_id.get(raw)
        if item_id is None:
            if isinstance(item_combo, ttk.Combobox) and self._is_combo_popdown_open(item_combo):
                # Ignore transient text while the popdown list is still active.
                return "break"
            item_id = self._team_resolve_selected_item_id(raw)
            if not item_id and raw not in {"", "Item", "(None)"}:
                # During typed search + click, FocusOut can fire before selected value lands.
                # Keep current slot item instead of clearing on transient text.
                current_item = str(slot.get("item_id", "")).strip()
                id_to_label = dict(ui.get("item_id_to_label", {"": "Item"}))
                ui["item_var"].set(id_to_label.get(current_item, "Item"))
                ui["item_placeholder_active"] = (not current_item)
                return "break"
        if item_id:
            ui["item_placeholder_active"] = False
        else:
            ui["item_placeholder_active"] = True
        slot["item_id"] = str(item_id or "").strip()
        self._team_update_slot_card(idx)
        if idx == self._team_selected_slot:
            self._team_load_slot_into_editor(idx)
        return "break"

    def _team_card_item_focus_in(self, index: int):
        if not self._team_slots:
            return "break"
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        if idx < 0 or idx >= len(self._team_slot_ui):
            return "break"
        ui = self._team_slot_ui[idx]
        if not bool(ui.get("item_placeholder_active", False)):
            return
        item_var = ui.get("item_var")
        if not isinstance(item_var, tk.StringVar):
            return
        if item_var.get().strip() == "Item":
            item_var.set("")

    def _team_card_item_focus_out(self, index: int):
        # Defer commit so mouse-based ComboboxSelected updates text first.
        delay_ms = 40
        try:
            ui = self._team_slot_ui[max(0, min(int(index), len(self._team_slot_ui) - 1))]
            combo = ui.get("item_combo")
            if isinstance(combo, ttk.Combobox) and self._is_combo_popdown_open(combo):
                delay_ms = 140
        except Exception:
            delay_ms = 40
        try:
            self.root.after(delay_ms, lambda idx=index: self._team_card_item_changed(idx))
        except Exception:
            self._team_card_item_changed(index)

    def _team_card_move_changed(self, index: int, move_index: int):
        if self._team_syncing or not self._team_slots:
            return "break"
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        m_idx = max(0, min(int(move_index), 3))
        ui = self._team_slot_ui[idx]
        slot = self._team_slots[idx]
        moves = slot.get("moves", [])
        if not isinstance(moves, list):
            moves = []
        while len(moves) < 4:
            moves.append("")
        move_vars: list[tk.StringVar] = list(ui.get("move_vars", []))
        raw = str(move_vars[m_idx].get() if m_idx < len(move_vars) else "").strip()
        label_to_id = dict(ui.get("move_label_to_id", {"(None)": ""}))
        move_id = label_to_id.get(raw)
        if move_id is None:
            move_id = self._team_resolve_selected_move_id(raw)
        moves[m_idx] = str(move_id or "").strip()
        slot["moves"] = moves[:4]
        self._team_update_slot_card(idx)
        if idx == self._team_selected_slot:
            self._team_load_slot_into_editor(idx)
        self._team_update_matchup_view()
        return "break"

    def _team_card_ability_changed(self, index: int):
        if self._team_syncing or not self._team_slots:
            return "break"
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        ui = self._team_slot_ui[idx]
        slot = self._team_slots[idx]
        raw = str(ui.get("ability_var").get() if ui.get("ability_var") is not None else "").strip()
        label_to_id = dict(ui.get("ability_label_to_id", {"Ability": ""}))
        ability_id = label_to_id.get(raw)
        if ability_id is None:
            ability_id = self._team_resolve_selected_ability_id(raw)
        slot["ability_id"] = str(ability_id or "").strip()
        self._team_update_slot_card(idx)
        if idx == self._team_selected_slot:
            self._team_load_slot_into_editor(idx)
        return "break"

    def _team_card_level_changed(self, index: int):
        if self._team_syncing or not self._team_slots:
            return "break"
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        ui = self._team_slot_ui[idx]
        slot = self._team_slots[idx]
        level_var = ui.get("level_var")
        raw = level_var.get() if isinstance(level_var, tk.StringVar) else str(slot.get("level", 50))
        level = self._clamp_int(raw, 1, 100, 50)
        slot["level"] = level
        if isinstance(level_var, tk.StringVar):
            level_var.set(str(level))
        self._team_update_slot_card(idx)
        if idx == self._team_selected_slot:
            self._team_load_slot_into_editor(idx)
        return "break"

    def _team_clear_slot(self, index: int):
        if index < 0 or index >= len(self._team_slots):
            return
        self._team_slots[index] = self._team_default_slot_data()
        if index == self._team_selected_slot:
            self._team_load_slot_into_editor(index)
        self._team_update_slot_title(index)
        self._team_update_slot_card(index)
        self._team_update_matchup_view()

    def _team_open_avatar_context_menu(self, index: int, event):
        if index < 0 or index >= len(self._team_slots):
            return "break"
        self._team_select_slot(index)
        slot = self._team_slots[index]
        has_species = bool(str(slot.get("species_id", "")).strip())
        if self._team_avatar_context_menu is None:
            self._team_avatar_context_menu = tk.Menu(self.root, tearoff=0)
        menu = self._team_avatar_context_menu
        try:
            menu.delete(0, "end")
            if has_species:
                menu.add_command(label="Add to Party", command=lambda idx=index: self._team_add_slot_to_party(idx))
                menu.add_separator()
                menu.add_command(label="Remove", command=lambda idx=index: self._team_clear_slot(idx))
            else:
                menu.add_command(label="Add to Party", state="disabled")
                menu.add_separator()
                menu.add_command(label="Remove", state="disabled")
        except Exception:
            return "break"
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    def _team_suggest_ability_index(self, species_id: str, form: int, ability_id: str) -> int:
        sid = str(species_id or "").strip()
        aid = str(ability_id or "").strip()
        if not sid or not aid or not self.catalogs:
            return 0
        profile = self.catalogs.get_species_form_profile(sid, form=form)
        if not profile:
            return 0
        regular: list[str] = []
        hidden: set[str] = set()
        for raw in profile.ability_ids:
            canonical = self.catalogs.canonical_ability_id(raw)
            if canonical and canonical not in regular:
                regular.append(canonical)
        for raw in profile.hidden_ability_ids:
            canonical = self.catalogs.canonical_ability_id(raw)
            if canonical:
                hidden.add(canonical)
        if aid in hidden:
            return 2
        if aid in regular:
            return max(0, min(1, regular.index(aid)))
        return 0

    def _team_create_pokemon_from_slot(self, slot: dict[str, Any]) -> core.RubyObject:
        species_id = str(slot.get("species_id", "")).strip().lstrip(":")
        if not species_id:
            raise ValueError("Slot has no species.")
        if self.catalogs:
            species_id = self.catalogs.canonical_species_id(species_id) or species_id
        form = self._clamp_int(str(slot.get("form", 0)), 0, 999, 0)
        level = self._clamp_int(str(slot.get("level", 50)), 1, 100, 50)
        shiny = bool(slot.get("shiny", False))
        nature_id = str(slot.get("nature_id", "HARDY")).strip().upper() or "HARDY"

        ability_id = str(slot.get("ability_id", "")).strip().lstrip(":")
        item_id = str(slot.get("item_id", "")).strip().lstrip(":")
        if self.catalogs:
            if ability_id:
                ability_id = self.catalogs.canonical_ability_id(ability_id) or ability_id
            if item_id:
                item_id = self.catalogs.canonical_item_id(item_id) or item_id
            if not ability_id:
                valid_abilities, _hidden = self.catalogs.valid_abilities_for_species(species_id, form=form)
                if valid_abilities:
                    ability_id = str(valid_abilities[0]).strip()

        initial_moves = self.catalogs.initial_moves_for_species(species_id, form=form, level=level) if self.catalogs else []
        raw_moves = slot.get("moves", [])
        if not isinstance(raw_moves, list):
            raw_moves = []
        move_ids: list[str] = []
        for i in range(4):
            move_id = str(raw_moves[i] if i < len(raw_moves) else "").strip().lstrip(":")
            if self.catalogs and move_id:
                move_id = self.catalogs.canonical_move_id(move_id) or move_id
            if not move_id and i < len(initial_moves):
                move_id = str(initial_moves[i]).strip().lstrip(":")
            move_ids.append(move_id)
        if not any(move_ids):
            seed = [str(mid).strip().lstrip(":") for mid in initial_moves[:4] if str(mid).strip()]
            if not seed:
                seed = ["TACKLE"]
            while len(seed) < 4:
                seed.append("")
            move_ids = seed[:4]

        template = self._party_template_pokemon or self._find_template_pokemon()
        if template is None:
            pkmn = core.RubyObject("Pokemon", {})
        else:
            self._party_template_pokemon = template
            pkmn = self._clone_ruby_object(template)

        pkmn.attributes["@species"] = core.Symbol(species_id)
        pkmn.attributes["@form"] = form
        pkmn.attributes["@level"] = level
        pkmn.attributes["@name"] = self._english_species_name_for_id(species_id)
        pkmn.attributes["@nature"] = core.Symbol(nature_id)
        pkmn.attributes["@happiness"] = self._clamp_int(str(core.read_attr(pkmn, "@happiness", 70)), 0, 255, 70)
        pkmn.attributes["@gender"] = self._clamp_int(str(core.read_attr(pkmn, "@gender", 0)), 0, 2, 0)
        pkmn.attributes["@shiny"] = shiny
        pkmn.attributes["@super_shiny"] = bool(core.read_attr(pkmn, "@super_shiny", False)) if shiny else False
        pkmn.attributes["@personalID"] = random.randint(0, 2**32 - 1)
        pkmn.attributes["@obtain_level"] = level
        pkmn.attributes["@obtain_map"] = self._clamp_int(str(core.read_attr(pkmn, "@obtain_map", 0)), 0, 999999, 0)
        pkmn.attributes["@obtain_method"] = self._clamp_int(str(core.read_attr(pkmn, "@obtain_method", 0)), 0, 999, 0)
        pkmn.attributes["@hatched_map"] = self._clamp_int(str(core.read_attr(pkmn, "@hatched_map", 0)), 0, 999999, 0)
        pkmn.attributes["@forced_form"] = form
        pkmn.attributes["@item"] = core.Symbol(item_id) if item_id else None
        pkmn.attributes["@ability"] = core.Symbol(ability_id) if ability_id else None
        pkmn.attributes["@ability_index"] = self._team_suggest_ability_index(species_id, form, ability_id)

        if self.catalogs:
            minimum_exp = self.catalogs.minimum_exp_for_level(species_id, level, form=form)
        else:
            minimum_exp = self._clamp_int(str(core.read_attr(pkmn, "@exp", 0)), 0, 99999999, 0)
        pkmn.attributes["@exp"] = self._clamp_int(str(minimum_exp), 0, 99999999, 0)

        moves = core.read_attr(pkmn, "@moves", [])
        if not isinstance(moves, list):
            moves = []
        while len(moves) < 4:
            moves.append(core.RubyObject("Pokemon::Move", {"@id": core.Symbol("TACKLE"), "@pp": 35, "@ppup": 0}))
        for i in range(4):
            move_obj = moves[i]
            if not isinstance(move_obj, core.RubyObject):
                move_obj = core.RubyObject("Pokemon::Move", {"@id": core.Symbol("TACKLE"), "@pp": 35, "@ppup": 0})
                moves[i] = move_obj
            move_id = str(move_ids[i] if i < len(move_ids) else "").strip().lstrip(":")
            if not move_id:
                move_id = "TACKLE"
            move_obj.attributes["@id"] = core.Symbol(move_id)
            ppup_value = 0
            max_pp = self._move_max_pp(move_id, ppup_value)
            move_obj.attributes["@ppup"] = ppup_value
            move_obj.attributes["@pp"] = max_pp
        pkmn.attributes["@moves"] = moves[:4]

        relearn_ids: list[str] = []
        for mid in move_ids:
            if mid and mid not in relearn_ids:
                relearn_ids.append(mid)
        if not relearn_ids:
            for mid in initial_moves:
                mid_clean = str(mid).strip().lstrip(":")
                if mid_clean and mid_clean not in relearn_ids:
                    relearn_ids.append(mid_clean)
        if relearn_ids:
            pkmn.attributes["@first_moves"] = [core.Symbol(mid) for mid in relearn_ids[:4]]

        ivs = self._team_clamped_ivs(slot.get("ivs", {}))
        evs = self._team_clamped_evs(slot.get("evs", {}))
        self._write_symbol_stat_dict(pkmn, "@iv", ivs)
        self._write_symbol_stat_dict(pkmn, "@ev", evs)

        base_stats = self.catalogs.base_stats_for_species(species_id, form=form) if self.catalogs else {}
        final_stats: dict[str, int] = {}
        for stat_id, _label in STAT_ORDER:
            base = self._clamp_int(str(base_stats.get(stat_id, 0)), 0, 999, 0)
            final_stats[stat_id] = self._team_calc_stat_value(stat_id, base, level, ivs[stat_id], evs[stat_id], nature_id)
        pkmn.attributes["@totalhp"] = final_stats["HP"]
        pkmn.attributes["@hp"] = final_stats["HP"]
        pkmn.attributes["@attack"] = final_stats["ATTACK"]
        pkmn.attributes["@defense"] = final_stats["DEFENSE"]
        pkmn.attributes["@spatk"] = final_stats["SPECIAL_ATTACK"]
        pkmn.attributes["@spdef"] = final_stats["SPECIAL_DEFENSE"]
        pkmn.attributes["@speed"] = final_stats["SPEED"]
        return pkmn

    @staticmethod
    def _team_party_capacity() -> int:
        return 6

    def _team_party_empty_indices(self, party: list[Any]) -> list[int]:
        cap = self._team_party_capacity()
        out: list[int] = []
        for i in range(cap):
            entry = party[i] if i < len(party) else None
            if not isinstance(entry, core.RubyObject):
                out.append(i)
        return out

    @staticmethod
    def _team_box_capacity(box_data: list[Any]) -> int:
        return max(PC_BOX_SLOT_CAPACITY, len(box_data))

    def _team_box_free_slots(self, box_index: int) -> int:
        boxes = self._get_storage_boxes()
        if box_index < 0 or box_index >= len(boxes):
            return 0
        box_data = self._get_box_pokemon_list(boxes[box_index])
        capacity = self._team_box_capacity(box_data)
        occupied = 0
        for i in range(capacity):
            entry = box_data[i] if i < len(box_data) else None
            if isinstance(entry, core.RubyObject):
                occupied += 1
        return max(0, capacity - occupied)

    def _team_insert_into_box(self, box_index: int, pokemon_list: list[core.RubyObject]) -> int:
        mons = [p for p in pokemon_list if isinstance(p, core.RubyObject)]
        if not mons:
            return 0
        boxes = self._get_storage_boxes()
        if box_index < 0 or box_index >= len(boxes):
            raise ValueError("Selected box is out of range.")
        box_obj = boxes[box_index]
        if not isinstance(box_obj, core.RubyObject):
            raise ValueError("Selected box is invalid.")
        box_data = self._get_box_pokemon_list(box_obj)
        capacity = self._team_box_capacity(box_data)
        while len(box_data) < capacity:
            box_data.append(None)
        empty_indices = [i for i in range(capacity) if not isinstance(box_data[i], core.RubyObject)]
        if len(empty_indices) < len(mons):
            box_name = self._box_display_name(box_obj, box_index)
            raise ValueError(f"{box_name} has only {len(empty_indices)} free slots.")
        for mon, slot_idx in zip(mons, empty_indices):
            box_data[slot_idx] = mon
        box_obj.attributes["@pokemon"] = box_data
        return len(mons)

    def _team_refresh_party_views(self, box_index: int | None = None):
        if box_index is not None:
            storage = self.get_root_key("pokemonStorage")
            if isinstance(storage, core.RubyObject):
                storage.attributes["@currentBox"] = int(box_index)
        self._refresh_party_box_controls()
        if self.party_view_mode_var.get() == "Box":
            self._party_selected_mode = None
            self._party_selected_index = None
            self._party_selected_box_index = None
        self._render_party_slot_grid()

    @staticmethod
    def _team_count_box_occupied(box_data: list[Any]) -> int:
        return sum(1 for i in range(min(len(box_data), PC_BOX_SLOT_CAPACITY)) if isinstance(box_data[i], core.RubyObject))

    def _team_draw_box_mini_preview(self, canvas: tk.Canvas, box_data: list[Any]):
        canvas.delete("all")
        cols = 6
        rows = 5
        dot = 4
        gap_x = 9
        gap_y = 8
        start_x = 4
        start_y = 4
        for i in range(rows * cols):
            row = i // cols
            col = i % cols
            x = start_x + (col * gap_x)
            y = start_y + (row * gap_y)
            occupied = i < len(box_data) and isinstance(box_data[i], core.RubyObject)
            color = "#53ae62" if occupied else "#d5d5d5"
            canvas.create_oval(x, y, x + dot, y + dot, fill=color, outline=color)

    def _team_close_box_picker(self):
        popup = self._team_box_picker_popup
        if popup is None:
            return
        try:
            popup.destroy()
        except Exception:
            pass
        self._team_box_picker_popup = None
        self._team_box_picker_icon_refs = []

    def _team_pick_box_popup(
        self,
        *,
        title: str,
        prompt: str,
        preferred_index: int | None = None,
    ) -> int | None:
        boxes = self._get_storage_boxes()
        if not boxes:
            messagebox.showwarning("No Boxes", "No storage boxes were found in this save.")
            return None

        self._team_close_box_picker()
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.transient(self.root)
        popup.resizable(False, False)
        popup.protocol("WM_DELETE_WINDOW", self._team_close_box_picker)
        self._team_box_picker_popup = popup

        result: dict[str, int | None] = {"box_index": None}
        per_page = 10
        total_boxes = len(boxes)
        total_pages = max(1, (total_boxes + per_page - 1) // per_page)
        preferred = self._selected_box_index() if preferred_index is None else int(preferred_index)
        preferred = max(0, min(preferred, total_boxes - 1))
        page_var = tk.IntVar(value=(preferred // per_page) + 1)
        selected_box_idx: dict[str, int | None] = {"value": preferred}
        tile_widgets: dict[int, tk.Frame] = {}

        shell = ttk.Frame(popup, padding=10)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        ttk.Label(shell, text=prompt, wraplength=440, justify="left").grid(row=0, column=0, sticky="w")

        pager = ttk.Frame(shell)
        pager.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        pager.columnconfigure(3, weight=1)
        ttk.Label(pager, text="Page").grid(row=0, column=0, sticky="w")
        page_values = [str(i + 1) for i in range(total_pages)]
        page_combo = ttk.Combobox(pager, state="readonly", values=page_values, width=6, textvariable=tk.StringVar())
        page_combo.grid(row=0, column=1, sticky="w", padx=(4, 6))
        page_combo.set(str(page_var.get()))
        ttk.Label(pager, text=f"/ {total_pages}").grid(row=0, column=2, sticky="w")
        prev_btn = ttk.Button(pager, text="<", width=3)
        prev_btn.grid(row=0, column=4, sticky="e", padx=(0, 4))
        next_btn = ttk.Button(pager, text=">", width=3)
        next_btn.grid(row=0, column=5, sticky="e")

        grid = ttk.Frame(shell)
        grid.grid(row=2, column=0, sticky="nsew")
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        def _finish(box_idx: int | None):
            result["box_index"] = box_idx
            self._team_close_box_picker()

        def _paint_tile(tile: tk.Frame, selected: bool):
            if selected:
                bg = "#dcecff"
                outline = "#3d79c4"
                thickness = 2
            else:
                bg = "#f6f6f6"
                outline = "#c8c8c8"
                thickness = 1
            try:
                tile.configure(bg=bg, highlightbackground=outline, highlightcolor=outline, highlightthickness=thickness)
            except Exception:
                return
            for child in tile.winfo_children():
                if isinstance(child, tk.Label):
                    try:
                        child.configure(bg=bg)
                    except Exception:
                        pass

        def _refresh_selection_highlight():
            chosen = selected_box_idx["value"]
            for idx, tile in tile_widgets.items():
                _paint_tile(tile, idx == chosen)

        def _set_selected(box_idx: int):
            selected_box_idx["value"] = int(box_idx)
            _refresh_selection_highlight()

        def _bind_pick_target(widget, box_idx: int):
            try:
                widget.bind("<Button-1>", lambda _e, idx=box_idx: _set_selected(idx), add="+")
            except Exception:
                pass

        def _render_page():
            for child in grid.winfo_children():
                child.destroy()
            tile_widgets.clear()
            current_page = max(1, min(page_var.get(), total_pages))
            page_var.set(current_page)
            page_combo.set(str(current_page))
            prev_btn.configure(state=("normal" if current_page > 1 else "disabled"))
            next_btn.configure(state=("normal" if current_page < total_pages else "disabled"))

            start = (current_page - 1) * per_page
            end = min(total_boxes, start + per_page)
            for local_idx, box_idx in enumerate(range(start, end)):
                box_obj = boxes[box_idx]
                box_name = self._box_display_name(box_obj, box_idx)
                box_data = self._get_box_pokemon_list(box_obj)
                occupied = self._team_count_box_occupied(box_data)
                free_slots = max(0, PC_BOX_SLOT_CAPACITY - occupied)

                tile = tk.Frame(grid, bd=0, relief="flat")
                tile.grid(row=local_idx // 2, column=local_idx % 2, sticky="nsew", padx=4, pady=4)
                title_lbl = tk.Label(tile, text=box_name, font=("", 8, "bold"), anchor="w")
                title_lbl.pack(anchor="w")
                preview = tk.Canvas(
                    tile,
                    width=60,
                    height=52,
                    highlightthickness=1,
                    highlightbackground="#c9c9c9",
                    bg="#f8f8f8",
                )
                preview.pack(anchor="w", pady=(2, 2))
                self._team_draw_box_mini_preview(preview, box_data)
                meta_lbl = tk.Label(tile, text=f"{occupied}/{PC_BOX_SLOT_CAPACITY}  (Free {free_slots})", anchor="w")
                meta_lbl.pack(anchor="w")
                tile_widgets[box_idx] = tile

                _bind_pick_target(tile, box_idx)
                _bind_pick_target(title_lbl, box_idx)
                _bind_pick_target(meta_lbl, box_idx)
                _bind_pick_target(preview, box_idx)
            _refresh_selection_highlight()

        def _set_page(value: int):
            page_var.set(max(1, min(int(value), total_pages)))
            _render_page()

        prev_btn.configure(command=lambda: _set_page(page_var.get() - 1))
        next_btn.configure(command=lambda: _set_page(page_var.get() + 1))
        page_combo.bind("<<ComboboxSelected>>", lambda _e: _set_page(self._clamp_int(page_combo.get(), 1, total_pages, 1)))

        actions = ttk.Frame(shell)
        actions.grid(row=3, column=0, sticky="e", pady=(8, 0))
        def _confirm():
            chosen = selected_box_idx["value"]
            if chosen is None or chosen < 0 or chosen >= total_boxes:
                messagebox.showwarning("No Selection", "Select a box first.")
                return
            _finish(chosen)

        ttk.Button(actions, text="OK", command=_confirm).pack(side="left")
        ttk.Button(actions, text="Cancel", command=lambda: _finish(None)).pack(side="left", padx=(6, 0))
        popup.bind("<Return>", lambda _e: _confirm(), add="+")
        popup.bind("<Escape>", lambda _e: _finish(None), add="+")

        _render_page()
        try:
            x = self.root.winfo_rootx() + 80
            y = self.root.winfo_rooty() + 80
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass
        popup.grab_set()
        popup.wait_window()
        return result["box_index"]

    def _team_pick_box_with_capacity(
        self,
        *,
        required_slots: int,
        title: str,
        prompt: str,
        preferred_index: int | None = None,
    ) -> int | None:
        needed = max(0, int(required_slots))
        while True:
            box_idx = self._team_pick_box_popup(title=title, prompt=prompt, preferred_index=preferred_index)
            if box_idx is None:
                return None
            free_slots = self._team_box_free_slots(box_idx)
            if free_slots >= needed:
                return box_idx
            box_obj = self._get_storage_boxes()[box_idx]
            box_name = self._box_display_name(box_obj, box_idx)
            retry = messagebox.askyesno(
                "Not Enough Space",
                f"{box_name} has only {free_slots} free slots, but {needed} are required.\n\nPick another box?",
            )
            if not retry:
                return None
            preferred_index = box_idx

    def _team_pick_party_slot_popup(
        self,
        *,
        party: list[Any],
        title: str,
        prompt: str,
        preferred_index: int | None = None,
        require_occupied: bool = True,
    ) -> int | None:
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.transient(self.root)
        popup.resizable(False, False)

        result: dict[str, int | None] = {"slot_index": None}
        selected_slot: dict[str, int | None] = {"value": None}
        button_map: dict[int, tk.Button] = {}
        icon_refs: list[tk.PhotoImage | None] = []
        capacity = self._team_party_capacity()

        default_idx = 0 if preferred_index is None else max(0, min(int(preferred_index), capacity - 1))
        if require_occupied:
            occupied = [i for i in range(capacity) if i < len(party) and isinstance(party[i], core.RubyObject)]
            if not occupied:
                messagebox.showwarning("No Party Pokemon", "Party has no Pokemon to replace.")
                try:
                    popup.destroy()
                except Exception:
                    pass
                return None
            if default_idx not in occupied:
                default_idx = occupied[0]
        selected_slot["value"] = default_idx

        shell = ttk.Frame(popup, padding=10)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        ttk.Label(shell, text=prompt, wraplength=430, justify="left").grid(row=0, column=0, sticky="w")

        grid = ttk.Frame(shell)
        grid.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for c in range(3):
            grid.columnconfigure(c, weight=1)
        for r in range(2):
            grid.rowconfigure(r, weight=1)

        def _slot_label(entry: Any, idx: int) -> str:
            if isinstance(entry, core.RubyObject):
                species_id = symbol_name(core.read_attr(entry, "@species", "")).strip()
                species_name = self._english_species_name_for_id(species_id) if species_id else "Pokemon"
                level = self._clamp_int(str(core.read_attr(entry, "@level", 1)), 1, 100, 1)
                return f"Party {idx + 1}\n{species_name}\nLv {level}"
            return f"Party {idx + 1}\n(Empty)"

        def _apply_selection_visual():
            chosen = selected_slot["value"]
            for idx, btn in button_map.items():
                entry = party[idx] if idx < len(party) else None
                is_selected = idx == chosen
                is_occupied = isinstance(entry, core.RubyObject)
                if is_selected:
                    bg = "#ffe8ad"
                    active = "#f7d887"
                elif is_occupied:
                    bg = "#dff3dc"
                    active = "#cde9c8"
                else:
                    bg = "#eeeeee"
                    active = "#e4e4e4"
                try:
                    btn.configure(bg=bg, activebackground=active)
                except Exception:
                    pass

        def _pick(idx: int):
            selected_slot["value"] = int(idx)
            _apply_selection_visual()

        for i in range(capacity):
            entry = party[i] if i < len(party) else None
            icon = self._get_party_icon_image(entry)
            icon_refs.append(icon)
            btn = tk.Button(
                grid,
                text=_slot_label(entry, i),
                image=icon,
                compound="top",
                justify="center",
                wraplength=110,
                width=14,
                relief="solid",
                bd=1,
                padx=3,
                pady=3,
                command=lambda idx=i: _pick(idx),
            )
            btn.grid(row=i // 3, column=i % 3, sticky="nsew", padx=3, pady=3)
            button_map[i] = btn

        _apply_selection_visual()

        def _finish(slot_idx: int | None):
            result["slot_index"] = slot_idx
            try:
                popup.destroy()
            except Exception:
                pass

        def _confirm():
            idx = selected_slot["value"]
            if idx is None:
                messagebox.showwarning("No Selection", "Select a party slot first.")
                return
            idx = max(0, min(int(idx), capacity - 1))
            entry = party[idx] if idx < len(party) else None
            if require_occupied and not isinstance(entry, core.RubyObject):
                messagebox.showwarning("Invalid Slot", "Selected party slot is empty.")
                return
            _finish(idx)

        actions = ttk.Frame(shell)
        actions.grid(row=2, column=0, sticky="e", pady=(8, 0))
        ttk.Button(actions, text="OK", command=_confirm).pack(side="left")
        ttk.Button(actions, text="Cancel", command=lambda: _finish(None)).pack(side="left", padx=(6, 0))
        popup.bind("<Return>", lambda _e: _confirm(), add="+")
        popup.bind("<Escape>", lambda _e: _finish(None), add="+")

        try:
            x = self.root.winfo_rootx() + 90
            y = self.root.winfo_rooty() + 80
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass
        popup.grab_set()
        popup.wait_window()
        _ = icon_refs  # keep image refs alive until popup closes
        return result["slot_index"]

    def _team_add_slot_to_party(self, index: int):
        if self.save_data is None:
            messagebox.showwarning("No Save", "Load a save first.")
            return
        if index < 0 or index >= len(self._team_slots):
            return
        slot = self._team_slots[index]
        if not str(slot.get("species_id", "")).strip():
            messagebox.showwarning("Empty Slot", "This team slot has no Pokemon.")
            return
        try:
            pkmn = self._team_create_pokemon_from_slot(slot)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Add to Party Error", str(exc))
            return

        player = self.get_player()
        if not player:
            return
        party = core.read_attr(player, "@party", [])
        if not isinstance(party, list):
            party = []
        while len(party) < self._team_party_capacity():
            party.append(None)

        empty_indices = self._team_party_empty_indices(party)
        if empty_indices:
            target_idx = empty_indices[0]
            party[target_idx] = pkmn
            player.attributes["@party"] = party
            self.mark_modified()
            self._team_refresh_party_views()
            self.set_status(f"Added slot {index + 1} Pokemon to Party slot {target_idx + 1}.")
            return

        choice = messagebox.askyesnocancel(
            "Party Full",
            (
                "Party is full.\n\n"
                "Yes: Replace one Pokemon in Party (you will choose the slot), then move the replaced Pokemon to a box.\n"
                "No: Add this Team Builder Pokemon directly to a box.\n"
                "Cancel: Do nothing."
            ),
        )
        if choice is None:
            return

        if choice:
            replace_idx = self._team_pick_party_slot_popup(
                party=party,
                title="Choose Party Slot to Replace",
                prompt="Select the Party Pokemon to replace.",
                preferred_index=0,
                require_occupied=True,
            )
            if replace_idx is None:
                return
            replaced = party[replace_idx] if replace_idx < len(party) else None
            if not isinstance(replaced, core.RubyObject):
                messagebox.showwarning("Invalid Selection", "Selected party slot is empty.")
                return
            box_idx = self._team_pick_box_with_capacity(
                required_slots=1,
                title="Choose Box for Replaced Pokemon",
                prompt="Select a box to store the replaced Party Pokemon.",
                preferred_index=self._selected_box_index(),
            )
            if box_idx is None:
                return
            try:
                self._team_insert_into_box(box_idx, [replaced])
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Move Replaced Pokemon Error", str(exc))
                return
            party[replace_idx] = pkmn
            player.attributes["@party"] = party
            self.mark_modified()
            self._team_refresh_party_views(box_idx)
            self.set_status(
                f"Replaced Party slot {replace_idx + 1} with Team slot {index + 1} Pokemon and moved replaced Pokemon to "
                f"{self._box_display_name(self._get_storage_boxes()[box_idx], box_idx)}."
            )
            return

        box_idx = self._team_pick_box_with_capacity(
            required_slots=1,
            title="Choose Box",
            prompt="Select a box to receive this Pokemon.",
            preferred_index=self._selected_box_index(),
        )
        if box_idx is None:
            return
        try:
            self._team_insert_into_box(box_idx, [pkmn])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Add to Box Error", str(exc))
            return
        self.mark_modified()
        self._team_refresh_party_views(box_idx)
        self.set_status(f"Added slot {index + 1} Pokemon to {self._box_display_name(self._get_storage_boxes()[box_idx], box_idx)}.")

    def _team_add_all_to_party(self):
        if self.save_data is None:
            messagebox.showwarning("No Save", "Load a save first.")
            return
        non_empty_slots: list[tuple[int, dict[str, Any]]] = []
        for idx, slot in enumerate(self._team_slots):
            if str(slot.get("species_id", "")).strip():
                non_empty_slots.append((idx, slot))
        if not non_empty_slots:
            messagebox.showwarning("No Pokemon", "There are no Pokemon in Team Builder to add.")
            return

        new_pokemon: list[core.RubyObject] = []
        for idx, slot in non_empty_slots:
            try:
                new_pokemon.append(self._team_create_pokemon_from_slot(slot))
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Build Team Pokemon Error", f"Slot {idx + 1}: {exc}")
                return

        player = self.get_player()
        if not player:
            return
        party = core.read_attr(player, "@party", [])
        if not isinstance(party, list):
            party = []
        while len(party) < self._team_party_capacity():
            party.append(None)

        empty_indices = self._team_party_empty_indices(party)
        if len(empty_indices) >= len(new_pokemon):
            for mon, slot_idx in zip(new_pokemon, empty_indices):
                party[slot_idx] = mon
            player.attributes["@party"] = party
            self.mark_modified()
            self._team_refresh_party_views()
            self.set_status(f"Added {len(new_pokemon)} Pokemon from Team Builder to Party.")
            return

        choice = messagebox.askyesnocancel(
            "Not Enough Party Slots",
            (
                f"Party has only {len(empty_indices)} free slot(s), but {len(new_pokemon)} Pokemon are ready to add.\n\n"
                "Yes: Add to Party anyway (move current party Pokemon to a chosen box first).\n"
                "No: Add the Team Builder Pokemon directly to a chosen box.\n"
                "Cancel: Do nothing."
            ),
        )
        if choice is None:
            return

        if choice:
            existing_party = [party[i] for i in range(self._team_party_capacity()) if isinstance(party[i], core.RubyObject)]
            required = len(existing_party)
            box_idx = self._team_pick_box_with_capacity(
                required_slots=required,
                title="Choose Box for Current Party",
                prompt="Select a box to move all current Party Pokemon into.",
                preferred_index=self._selected_box_index(),
            )
            if box_idx is None:
                return
            try:
                self._team_insert_into_box(box_idx, existing_party)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Move Party to Box Error", str(exc))
                return
            for i in range(self._team_party_capacity()):
                party[i] = None
            for i, mon in enumerate(new_pokemon[: self._team_party_capacity()]):
                party[i] = mon
            player.attributes["@party"] = party
            self.mark_modified()
            self._team_refresh_party_views(box_idx)
            self.set_status(
                f"Moved {len(existing_party)} current party Pokemon to "
                f"{self._box_display_name(self._get_storage_boxes()[box_idx], box_idx)} and loaded Team Builder party."
            )
            return

        # choice is No -> add all target Pokemon to box.
        box_idx = self._team_pick_box_with_capacity(
            required_slots=len(new_pokemon),
            title="Choose Box for Team Pokemon",
            prompt="Select a box to receive all Team Builder Pokemon.",
            preferred_index=self._selected_box_index(),
        )
        if box_idx is None:
            return
        try:
            self._team_insert_into_box(box_idx, new_pokemon)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Add Team to Box Error", str(exc))
            return
        self.mark_modified()
        self._team_refresh_party_views(box_idx)
        self.set_status(
            f"Added {len(new_pokemon)} Team Builder Pokemon to "
            f"{self._box_display_name(self._get_storage_boxes()[box_idx], box_idx)}."
        )

    def _team_update_slot_title(self, index: int):
        if not hasattr(self, "_team_slot_ui") or index < 0 or index >= len(self._team_slot_ui):
            return
        card = self._team_slot_ui[index].get("card")
        if card is None:
            return
        title = f"Slot {index + 1}"
        if index == self._team_selected_slot:
            title = f"> {title}"
        try:
            card.configure(text=title)
        except Exception:
            return

    def _team_species_form_from_editor(self) -> tuple[str, int]:
        species_raw = self.team_species_var.get().strip() if hasattr(self, "team_species_var") else ""
        species_id = ""
        if species_raw:
            try:
                species_id = self.resolve_species_id(species_raw)
            except Exception:
                species_id = extract_internal_id(species_raw).strip().lstrip(":")
        form = self._clamp_int(self.team_form_var.get() if hasattr(self, "team_form_var") else "0", 0, 999, 0)
        if hasattr(self, "team_form_var"):
            self.team_form_var.set(str(form))
        return species_id, form

    def _team_resolve_selected_nature_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return "HARDY"
        if raw in getattr(self, "_team_nature_label_to_id", {}):
            return self._team_nature_label_to_id[raw]
        cleaned = re.sub(r"\s+\([^)]+\)\s*$", "", raw)
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        cleaned = extract_internal_id(cleaned).strip().lstrip(":").upper()
        return cleaned or "HARDY"

    def _team_resolve_selected_item_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "(None)":
            return ""
        if raw in getattr(self, "_team_item_label_to_id", {}):
            return self._team_item_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw).strip()
        cleaned = extract_internal_id(cleaned).strip()
        if not cleaned:
            return ""
        if self.catalogs:
            try:
                return self.resolve_item_id(cleaned)
            except Exception:
                return self.catalogs.canonical_item_id(cleaned) or ""
        return cleaned.lstrip(":")

    def _team_resolve_selected_ability_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "(None)":
            return ""
        if raw in getattr(self, "_team_ability_label_to_id", {}):
            return self._team_ability_label_to_id[raw]
        cleaned = re.sub(r"\s+\(H\)\s*$", "", raw)
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        if self.catalogs:
            try:
                return self.resolve_ability_id(cleaned)
            except Exception:
                return self.catalogs.canonical_ability_id(cleaned) or ""
        return cleaned.lstrip(":")

    def _team_resolve_selected_move_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "(None)":
            return ""
        if raw in getattr(self, "_team_move_label_to_id", {}):
            return self._team_move_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw)
        cleaned = extract_internal_id(cleaned).strip()
        if self.catalogs:
            try:
                return self.resolve_move_id(cleaned)
            except Exception:
                return self.catalogs.canonical_move_id(cleaned) or ""
        return cleaned.lstrip(":")

    def _team_refresh_legality_dropdowns(self, reset_invalid: bool):
        if not hasattr(self, "team_ability_combo"):
            return
        species_id, form = self._team_species_form_from_editor()
        if not self.catalogs or not species_id:
            self._team_ability_label_to_id = {"(None)": ""}
            self._team_ability_id_to_label = {"": "(None)"}
            self._set_combo_values(self.team_ability_combo, ["(None)"])
            if reset_invalid:
                self.team_ability_var.set("(None)")
            self._team_move_label_to_id = {"(None)": ""}
            self._team_move_id_to_label = {"": "(None)"}
            for combo in self.team_move_combos:
                self._set_combo_values(combo, ["(None)"])
            if reset_invalid:
                for var in self.team_move_vars:
                    var.set("(None)")
            return

        ability_ids, hidden_ids = self.catalogs.valid_abilities_for_species(species_id, form=form)
        if not ability_ids:
            ability_ids = sorted(self.catalogs.abilities_by_id.keys(), key=str.casefold)
            hidden_ids = set()
        ability_pairs: list[tuple[str, str]] = []
        for ability_id in ability_ids:
            label = self._ability_label_for_id(ability_id, set(hidden_ids))
            if any(existing == label for existing, _ in ability_pairs):
                label = f"{label} [{ability_id}]"
            ability_pairs.append((label, ability_id))
        ability_pairs.sort(key=lambda row: row[0].casefold())
        self._team_ability_label_to_id = {label: aid for label, aid in ability_pairs}
        self._team_ability_id_to_label = {}
        for label, ability_id in ability_pairs:
            self._team_ability_id_to_label.setdefault(ability_id, label)
        ability_labels = ["(None)"] + [label for label, _ in ability_pairs]
        self._set_combo_values(self.team_ability_combo, ability_labels)
        current_ability_id = self._team_resolve_selected_ability_id(self.team_ability_var.get())
        if current_ability_id and current_ability_id in self._team_ability_id_to_label:
            self.team_ability_var.set(self._team_ability_id_to_label[current_ability_id])
        elif reset_invalid:
            self.team_ability_var.set(ability_labels[1] if len(ability_labels) > 1 else "(None)")

        move_ids = self.catalogs.valid_moves_for_species(species_id, form=form, include_pre_evolutions=True)
        if not move_ids:
            move_ids = sorted(self.catalogs.moves_by_id.keys(), key=str.casefold)
        move_pairs: list[tuple[str, str]] = []
        for move_id in move_ids:
            label = self._team_move_label_for_id(move_id)
            if any(existing == label for existing, _ in move_pairs):
                label = f"{label} [{move_id}]"
            move_pairs.append((label, move_id))
        move_pairs.sort(key=lambda row: row[0].casefold())
        self._team_move_label_to_id = {label: mid for label, mid in move_pairs}
        self._team_move_id_to_label = {}
        for label, move_id in move_pairs:
            self._team_move_id_to_label.setdefault(move_id, label)
        move_labels = ["(None)"] + [label for label, _ in move_pairs]
        for combo in self.team_move_combos:
            self._set_combo_values(combo, move_labels)
        for var in self.team_move_vars:
            current_move_id = self._team_resolve_selected_move_id(var.get())
            if current_move_id and current_move_id in self._team_move_id_to_label:
                var.set(self._team_move_id_to_label[current_move_id])
            elif reset_invalid:
                var.set("(None)")

    def _team_apply_editor_to_selected_slot(self, refresh_legality: bool = True):
        if self._team_syncing or not self._team_slots:
            return
        idx = max(0, min(int(self._team_selected_slot), len(self._team_slots) - 1))
        slot = self._team_slots[idx]
        self._team_normalize_slot_stats(slot)
        species_id, form = self._team_species_form_from_editor()
        species_changed = species_id != str(slot.get("species_id", "")) or int(form) != int(slot.get("form", 0))
        slot["species_id"] = species_id
        slot["form"] = int(form)

        if refresh_legality and species_changed:
            self._team_syncing = True
            try:
                self._team_refresh_legality_dropdowns(reset_invalid=True)
            finally:
                self._team_syncing = False
            species_id, form = self._team_species_form_from_editor()
            slot["species_id"] = species_id
            slot["form"] = int(form)

        self._team_refresh_stat_editor()
        level = self._clamp_int(self.team_level_var.get(), 1, 100, 50)
        self.team_level_var.set(str(level))
        slot["level"] = level
        slot["shiny"] = bool(self.team_shiny_var.get())
        slot["nature_id"] = self._team_resolve_selected_nature_id(self.team_nature_var.get())
        slot["ability_id"] = self._team_resolve_selected_ability_id(self.team_ability_var.get())
        slot["item_id"] = self._team_resolve_selected_item_id(self.team_item_var.get())
        slot["moves"] = [self._team_resolve_selected_move_id(var.get()) for var in self.team_move_vars]
        slot["ivs"] = self._team_current_iv_values()
        slot["evs"] = self._team_current_ev_values()
        self._team_update_slot_card(idx)
        self._team_update_matchup_view()

    def _team_editor_field_changed(self, _event=None):
        if self._team_syncing:
            return "break"
        self._team_apply_editor_to_selected_slot(refresh_legality=True)
        return "break"

    def _team_load_slot_into_editor(self, index: int):
        if not self._team_slots:
            return
        idx = max(0, min(int(index), len(self._team_slots) - 1))
        slot = self._team_slots[idx]
        self._team_normalize_slot_stats(slot)
        self._team_syncing = True
        try:
            self.team_species_var.set(str(slot.get("species_id", "")))
            self.team_form_var.set(str(self._clamp_int(str(slot.get("form", 0)), 0, 999, 0)))
            self.team_level_var.set(str(self._clamp_int(str(slot.get("level", 50)), 1, 100, 50)))
            self.team_shiny_var.set(bool(slot.get("shiny", False)))

            nature_id = str(slot.get("nature_id", "HARDY")).strip().upper() or "HARDY"
            self.team_nature_var.set(self._team_nature_id_to_label.get(nature_id, self._nature_label_for_id(nature_id)))

            item_id = str(slot.get("item_id", "")).strip()
            self.team_item_var.set(
                self._team_item_id_to_label.get(
                    item_id,
                    "(None)" if not item_id else self._english_item_name_for_id(item_id),
                )
            )

            self._team_refresh_legality_dropdowns(reset_invalid=False)

            ability_id = str(slot.get("ability_id", "")).strip()
            if ability_id and ability_id in self._team_ability_id_to_label:
                self.team_ability_var.set(self._team_ability_id_to_label[ability_id])
            elif ability_id:
                self.team_ability_var.set(self._english_ability_name_for_id(ability_id))
            else:
                self.team_ability_var.set("(None)")

            moves = slot.get("moves", [])
            if not isinstance(moves, list):
                moves = []
            for i in range(4):
                move_id = str(moves[i] if i < len(moves) else "").strip()
                if move_id and move_id in self._team_move_id_to_label:
                    self.team_move_vars[i].set(self._team_move_id_to_label[move_id])
                elif move_id:
                    self.team_move_vars[i].set(self._team_move_label_for_id(move_id))
                else:
                    self.team_move_vars[i].set("(None)")

            slot_ivs = slot.get("ivs", {})
            slot_evs = slot.get("evs", {})
            for sid, _label in STAT_ORDER:
                self.team_iv_vars[sid].set(str(slot_ivs.get(sid, 31)))
                self.team_ev_vars[sid].set(str(slot_evs.get(sid, 0)))
        finally:
            self._team_syncing = False
        self._team_refresh_stat_editor()

    def _team_select_slot(self, index: int):
        if not self._team_slots:
            return
        self._team_selected_slot = max(0, min(int(index), len(self._team_slots) - 1))
        if hasattr(self, "team_active_slot_var"):
            self.team_active_slot_var.set(f"Editing Slot {self._team_selected_slot + 1}")
        self._team_load_slot_into_editor(self._team_selected_slot)
        for idx in range(len(self._team_slots)):
            self._team_update_slot_title(idx)
            self._team_update_slot_card(idx)
        self._team_update_matchup_view()

    def _team_update_slot_card(self, index: int):
        if not hasattr(self, "_team_slot_ui"):
            return
        if index < 0 or index >= len(self._team_slot_ui) or index >= len(self._team_slots):
            return
        ui = self._team_slot_ui[index]
        slot = self._team_slots[index]
        species_id = str(slot.get("species_id", "")).strip()
        form = self._clamp_int(str(slot.get("form", 0)), 0, 999, 0)
        level = self._clamp_int(str(slot.get("level", 50)), 1, 100, 50)
        shiny = bool(slot.get("shiny", False))

        canvas = ui.get("canvas")
        if canvas is None:
            return
        actual_w = max(1, int(canvas.winfo_width()))
        actual_h = max(1, int(canvas.winfo_height()))
        if actual_w <= 2:
            actual_w = 168
        if actual_h <= 2:
            actual_h = 130
        target_w = max(72, int(actual_w * 0.8))
        target_h = max(84, int(actual_h * 0.78))

        sprite = self._get_damage_scaled_icon(species_id, form, shiny, target_w, target_h) if species_id else None
        if sprite is None:
            sprite = ui.get("sprite_placeholder")
        if sprite is None:
            sprite = tk.PhotoImage(width=96, height=96)
        ui["image_ref"] = sprite
        try:
            canvas.itemconfigure(ui["image_id"], image=sprite)
            canvas.coords(ui["image_id"], actual_w // 2, max(36, int(actual_h * 0.45)))
            canvas.itemconfigure(ui["text_id"], text="" if species_id else "(Empty)")
            canvas.coords(ui["text_id"], actual_w // 2, actual_h - 8)
        except Exception:
            pass

        species_label = self._english_species_name_for_id(species_id) if species_id else "(Empty)"
        ui["name_var"].set(species_label)
        shiny_mark = " | Shiny" if shiny and species_id else ""
        ui["meta_var"].set(f"Lv {level}{shiny_mark}" if species_id else "Lv -")

        self._team_refresh_slot_inline_editors(index, species_id, form)

    @staticmethod
    def _team_defense_bucket(multiplier: float) -> str:
        value = float(multiplier)
        if value <= 0.0:
            return "x0"
        if value >= 3.5:
            return "x4"
        if value > 1.0:
            return "x2"
        if value <= 0.26:
            return "x1/4"
        if value < 1.0:
            return "x1/2"
        return "x1"

    def _team_collect_move_types(self) -> list[str]:
        if not self.catalogs:
            return []
        out: list[str] = []
        for slot in self._team_slots:
            moves = slot.get("moves", [])
            if not isinstance(moves, list):
                continue
            for move_id in moves:
                mid = str(move_id or "").strip()
                if not mid:
                    continue
                canonical = self.catalogs.canonical_move_id(mid) or mid
                move = self.catalogs.moves_by_id.get(canonical)
                if not move:
                    continue
                move_type = str(move.extra.get("Type", "")).strip().lstrip(":").upper()
                if move_type and move_type not in out:
                    out.append(move_type)
        return out

    def _team_update_matchup_view(self):
        if not hasattr(self, "team_defense_body"):
            return
        for child in self.team_defense_body.winfo_children():
            child.destroy()
        for child in self.team_offense_body.winfo_children():
            child.destroy()

        if not self.catalogs:
            ttk.Label(self.team_defense_body, text="Catalog data unavailable.").grid(row=0, column=0, sticky="w")
            ttk.Label(self.team_offense_body, text="Catalog data unavailable.").grid(row=0, column=0, sticky="w")
            self.team_matchup_summary_var.set("Catalog data unavailable.")
            return

        defense_map, type_order = self._dex_load_type_chart_data()
        if not type_order:
            ttk.Label(self.team_defense_body, text="Type chart data unavailable.").grid(row=0, column=0, sticky="w")
            ttk.Label(self.team_offense_body, text="Type chart data unavailable.").grid(row=0, column=0, sticky="w")
            self.team_matchup_summary_var.set("Type chart data unavailable.")
            return

        active_slots: list[dict[str, Any]] = [s for s in self._team_slots if str(s.get("species_id", "")).strip()]
        if not active_slots:
            ttk.Label(self.team_defense_body, text="No Pokemon selected yet.").grid(row=0, column=0, sticky="w")
            ttk.Label(self.team_offense_body, text="No Pokemon selected yet.").grid(row=0, column=0, sticky="w")
            self.team_matchup_summary_var.set("No Pokemon selected.")
            return

        ttk.Label(self.team_defense_body, text="Type score (resists - weaknesses)", font=("", 9, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        defense_wrap = ttk.Frame(self.team_defense_body)
        defense_wrap.grid(row=1, column=0, sticky="w")
        max_cols = 6
        for idx, atk_type in enumerate(type_order):
            weak_count = 0
            resist_count = 0
            for slot in active_slots:
                species_id = str(slot.get("species_id", "")).strip()
                form = self._clamp_int(str(slot.get("form", 0)), 0, 999, 0)
                def_types = self._dex_species_type_ids(species_id, form=form) if species_id else []
                mult = 1.0
                for def_type in def_types:
                    mult *= float(defense_map.get(def_type, {}).get(atk_type, 1.0))
                if mult > 1.0:
                    weak_count += 1
                elif mult < 1.0:
                    resist_count += 1
            score = resist_count - weak_count
            row = (idx // max_cols) * 2
            col = idx % max_cols
            chip = self._dex_make_type_chip(defense_wrap, atk_type, short=True, chip_width=TYPE_CHIP_COMPACT_WIDTH)
            chip.grid(row=row, column=col, sticky="w", padx=2, pady=(1, 0))
            color = "#2e7d32" if score > 0 else ("#c62828" if score < 0 else "#555555")
            prefix = "+" if score > 0 else ""
            ttk.Label(defense_wrap, text=f"{prefix}{score}", foreground=color, font=("", 9, "bold")).grid(
                row=row + 1,
                column=col,
                sticky="w",
                padx=4,
                pady=(0, 3),
            )

        move_types = self._team_collect_move_types()
        if not move_types:
            ttk.Label(self.team_offense_body, text="Select at least one move to evaluate coverage.").grid(
                row=0, column=0, sticky="w"
            )
        else:
            ttk.Label(self.team_offense_body, text="Best damage multiplier per target type", font=("", 9, "bold")).grid(
                row=0, column=0, sticky="w", pady=(0, 4)
            )
            offense_wrap = ttk.Frame(self.team_offense_body)
            offense_wrap.grid(row=1, column=0, sticky="w")
            max_cols = 6
            for idx, def_type in enumerate(type_order):
                best = 0.0
                for atk_type in move_types:
                    best = max(best, float(defense_map.get(def_type, {}).get(atk_type, 1.0)))
                row = (idx // max_cols) * 2
                col = idx % max_cols
                chip = self._dex_make_type_chip(offense_wrap, def_type, short=True, chip_width=TYPE_CHIP_COMPACT_WIDTH)
                chip.grid(row=row, column=col, sticky="w", padx=2, pady=(1, 0))
                label = self._team_format_type_multiplier(best)
                color = "#2e7d32" if best > 1.0 else ("#c62828" if best < 1.0 else "#555555")
                ttk.Label(offense_wrap, text=label, foreground=color, font=("", 9, "bold")).grid(
                    row=row + 1,
                    column=col,
                    sticky="w",
                    padx=4,
                    pady=(0, 3),
                )

        self.team_matchup_summary_var.set(
            f"Active team: {len(active_slots)}/6 | Distinct move types: {len(move_types)}"
        )

    @staticmethod
    def _team_format_type_multiplier(multiplier: float) -> str:
        value = float(multiplier)
        if value <= 0.0:
            return "0"
        if abs(value - 0.25) < 0.001:
            return "1/4"
        if abs(value - 0.5) < 0.001:
            return "1/2"
        if abs(value - 1.0) < 0.001:
            return "1"
        if abs(value - 2.0) < 0.001:
            return "2"
        if abs(value - 4.0) < 0.001:
            return "4"
        return f"{value:g}"

    def _team_type_cell_style(self, multiplier: float) -> tuple[str, str]:
        value = float(multiplier)
        if value <= 0.0:
            return "#ffffff", "#111111"
        if value > 1.0:
            return "#ffffff", "#1f9d3a"
        if value < 1.0:
            return "#ffffff", "#c62828"
        return "#222222", "#eeeeee"

    def _open_team_type_chart_popup(self):
        popup = getattr(self, "_team_type_chart_popup", None)
        if popup is not None and popup.winfo_exists():
            self._render_team_type_chart_popup()
            popup.deiconify()
            popup.lift()
            popup.focus_force()
            return

        popup = tk.Toplevel(self.root)
        popup.title("Type Chart")
        popup.minsize(740, 520)
        popup.geometry("980x700")
        try:
            popup.transient(self.root)
        except Exception:
            pass
        popup.protocol("WM_DELETE_WINDOW", self._close_team_type_chart_popup)
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(1, weight=1)

        head = ttk.Frame(popup, padding=(10, 8))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        ttk.Label(
            head,
            text="Attack (rows) vs Defense (columns) multipliers",
            font=("", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(head, text="Close", command=self._close_team_type_chart_popup).grid(row=0, column=1, sticky="e")

        body_shell = ttk.Frame(popup, padding=(10, 0, 10, 10))
        body_shell.grid(row=1, column=0, sticky="nsew")
        body_shell.columnconfigure(0, weight=1)
        body_shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(body_shell, highlightthickness=1, highlightbackground="#cccccc")
        canvas.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(body_shell, orient="vertical", command=canvas.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(body_shell, orient="horizontal", command=canvas.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        canvas.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        body = ttk.Frame(canvas)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _on_canvas_configure(event):
            try:
                req_width = max(int(body.winfo_reqwidth()), int(event.width))
                canvas.itemconfigure(body_window, width=req_width)
            except Exception:
                return

        canvas.bind("<Configure>", _on_canvas_configure, add="+")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"), add="+")
        canvas.bind("<Button-4>", lambda _e: canvas.yview_scroll(-3, "units"), add="+")
        canvas.bind("<Button-5>", lambda _e: canvas.yview_scroll(3, "units"), add="+")

        self._team_type_chart_popup = popup
        self._team_type_chart_canvas = canvas
        self._team_type_chart_body = body
        self._render_team_type_chart_popup()
        try:
            popup.grab_set()
        except Exception:
            pass
        popup.focus_force()

    def _close_team_type_chart_popup(self):
        popup = getattr(self, "_team_type_chart_popup", None)
        if popup is None:
            return
        try:
            popup.grab_release()
        except Exception:
            pass
        try:
            popup.destroy()
        except Exception:
            pass
        self._team_type_chart_popup = None
        self._team_type_chart_canvas = None
        self._team_type_chart_body = None

    def _render_team_type_chart_popup(self):
        body = getattr(self, "_team_type_chart_body", None)
        if body is None:
            return
        for child in body.winfo_children():
            child.destroy()

        if not self.catalogs:
            ttk.Label(body, text="Catalog data unavailable.").grid(row=0, column=0, sticky="w")
            return
        defense_map, type_order = self._dex_load_type_chart_data()
        if not type_order:
            ttk.Label(body, text="Type chart data unavailable.").grid(row=0, column=0, sticky="w")
            return

        ttk.Label(body, text="Atk \\ Def", font=("", 9, "bold")).grid(row=0, column=0, sticky="w", padx=2, pady=2)
        for col_idx, def_type in enumerate(type_order, start=1):
            chip = self._dex_make_type_chip(body, def_type, short=True, chip_width=TYPE_CHIP_COMPACT_WIDTH)
            chip.grid(row=0, column=col_idx, sticky="ew", padx=1, pady=1)

        for row_idx, atk_type in enumerate(type_order, start=1):
            chip = self._dex_make_type_chip(body, atk_type, short=True, chip_width=TYPE_CHIP_COMPACT_WIDTH)
            chip.grid(row=row_idx, column=0, sticky="ew", padx=1, pady=1)
            for col_idx, def_type in enumerate(type_order, start=1):
                mult = float(defense_map.get(def_type, {}).get(atk_type, 1.0))
                fg, bg = self._team_type_cell_style(mult)
                cell = tk.Label(
                    body,
                    text=self._team_format_type_multiplier(mult),
                    width=4,
                    anchor="center",
                    fg=fg,
                    bg=bg,
                    font=("", 8, "bold"),
                    relief="solid",
                    bd=1,
                )
                cell.grid(row=row_idx, column=col_idx, sticky="nsew", padx=1, pady=1)
        for col in range(len(type_order) + 1):
            body.columnconfigure(col, weight=0)

    def _team_load_from_party(self):
        if self.save_data is None:
            messagebox.showwarning("No Save", "Load a save first, then use Load Party.")
            return
        party = self.get_party()
        slots: list[dict[str, Any]] = []
        for idx in range(6):
            if idx < len(party) and isinstance(party[idx], core.RubyObject):
                pkmn = party[idx]
                slot = self._team_default_slot_data()
                species_id = symbol_name(core.read_attr(pkmn, "@species", "")).strip()
                slot["species_id"] = self._species_choice(species_id)
                slot["form"] = self._clamp_int(str(core.read_attr(pkmn, "@form", 0)), 0, 999, 0)
                slot["level"] = self._clamp_int(str(core.read_attr(pkmn, "@level", 50)), 1, 100, 50)
                slot["shiny"] = bool(core.read_attr(pkmn, "@shiny", False))
                nature_id = self._nature_choice(symbol_name(core.read_attr(pkmn, "@nature", "HARDY")))
                slot["nature_id"] = nature_id or "HARDY"
                ability_id = symbol_name(core.read_attr(pkmn, "@ability", "")).strip().lstrip(":")
                item_id = symbol_name(core.read_attr(pkmn, "@item", "")).strip().lstrip(":")
                if self.catalogs:
                    if ability_id:
                        ability_id = self.catalogs.canonical_ability_id(ability_id) or ability_id
                    if item_id:
                        item_id = self.catalogs.canonical_item_id(item_id) or item_id
                slot["ability_id"] = ability_id
                slot["item_id"] = item_id
                moves: list[str] = []
                raw_moves = core.read_attr(pkmn, "@moves", [])
                if isinstance(raw_moves, list):
                    for move_obj in raw_moves[:4]:
                        if isinstance(move_obj, core.RubyObject):
                            move_id = symbol_name(core.read_attr(move_obj, "@id", "")).strip().lstrip(":")
                            if self.catalogs and move_id:
                                move_id = self.catalogs.canonical_move_id(move_id) or move_id
                            moves.append(move_id)
                        else:
                            moves.append("")
                while len(moves) < 4:
                    moves.append("")
                slot["moves"] = moves[:4]
                slot["ivs"] = self._team_clamped_ivs(self._read_symbol_stat_dict(pkmn, "@iv"))
                slot["evs"] = self._team_clamped_evs(self._read_symbol_stat_dict(pkmn, "@ev"))
                slots.append(slot)
            else:
                slots.append(self._team_default_slot_data())

        self._team_slots = slots
        first_non_empty = 0
        for i, slot in enumerate(self._team_slots):
            if str(slot.get("species_id", "")).strip():
                first_non_empty = i
                break
        self._team_select_slot(first_non_empty)
        self.set_status("Loaded party into Team Builder.")

    def _team_clear_slots(self):
        self._team_slots = [self._team_default_slot_data() for _ in range(6)]
        self._team_select_slot(0)
        self.set_status("Team Builder cleared.")

    def refresh_team_tab(self):
        if not hasattr(self, "team_species_combo"):
            return
        if not self._team_slots or len(self._team_slots) != 6:
            self._team_slots = [self._team_default_slot_data() for _ in range(6)]
        for slot in self._team_slots:
            self._team_normalize_slot_stats(slot)
        self._set_combo_values(self.team_species_combo, self._damage_species_choice_values())
        self._set_combo_values(self.team_nature_combo, self._team_nature_choice_labels())
        self._set_combo_values(self.team_item_combo, self._team_item_choice_labels())
        self._team_selected_slot = max(0, min(int(self._team_selected_slot), 5))
        self._team_load_slot_into_editor(self._team_selected_slot)
        for idx in range(len(self._team_slots)):
            self._team_update_slot_title(idx)
            self._team_update_slot_card(idx)
        self._team_update_matchup_view()
        self._team_refresh_stat_editor()
        self._apply_team_tab_layout()
        self._apply_team_cards_layout()

    def _build_damage_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Damage")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        species_values = self._damage_species_choice_values()
        item_labels = self._damage_item_choice_labels()
        nature_labels = self._damage_nature_choice_labels()

        root = ttk.Frame(tab)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=4, minsize=240, uniform="damage_cols")
        root.columnconfigure(1, weight=7, minsize=380)
        root.columnconfigure(2, weight=4, minsize=240, uniform="damage_cols")
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=0)

        left_col = ttk.Frame(root)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left_col.columnconfigure(0, weight=1)
        left_col.rowconfigure(0, weight=4)
        left_col.rowconfigure(1, weight=6)

        right_col = ttk.Frame(root)
        right_col.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right_col.columnconfigure(0, weight=1)
        right_col.rowconfigure(0, weight=4)
        right_col.rowconfigure(1, weight=6)

        self._build_damage_side_panel(
            left_col,
            side="attacker",
            title="Attacker",
            column=0,
            row=1,
            species_values=species_values,
            item_labels=item_labels,
            nature_labels=nature_labels,
        )
        self._build_damage_side_panel(
            right_col,
            side="defender",
            title="Defender",
            column=0,
            row=1,
            species_values=species_values,
            item_labels=item_labels,
            nature_labels=nature_labels,
        )
        self._build_damage_preview_card(left_col, side="attacker", column=0)
        self._build_damage_preview_card(right_col, side="defender", column=0)

        center = ttk.Frame(root)
        center.grid(row=0, column=1, sticky="nsew", padx=10)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(0, weight=0)
        center.rowconfigure(1, weight=7)
        center.rowconfigure(2, weight=3)
        self.damage_center_root = center
        self.damage_root_frame = root
        self.damage_left_col = left_col
        self.damage_right_col = right_col
        self.damage_center_col = center
        self._damage_layout_mode = ""

        top_row = ttk.Frame(center)
        top_row.grid(row=0, column=0, sticky="ew")
        ttk.Button(top_row, text="Swap <->", command=self._swap_damage_roles).pack(anchor="center")

        battle_opts = ttk.LabelFrame(center, text="Battle Modifiers", padding=8)
        battle_opts.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for idx in range(4):
            battle_opts.columnconfigure(idx, weight=1 if idx in {1, 3} else 0)
        battle_opts.rowconfigure(1, weight=1)
        self.damage_weather_var = tk.StringVar(value="None")
        self.damage_terrain_var = tk.StringVar(value="None")
        self.damage_helping_hand_var = tk.BooleanVar(value=False)
        self.damage_charge_var = tk.BooleanVar(value=False)
        self.damage_foresight_var = tk.BooleanVar(value=False)
        self.damage_power_spot_var = tk.BooleanVar(value=False)
        self.damage_battery_var = tk.BooleanVar(value=False)
        self.damage_steely_spirit_var = tk.BooleanVar(value=False)
        self.damage_flower_gift_atk_var = tk.BooleanVar(value=False)
        self.damage_critical_var = tk.BooleanVar(value=False)
        self.damage_reflect_var = tk.BooleanVar(value=False)
        self.damage_lightscreen_var = tk.BooleanVar(value=False)
        self.damage_aurora_veil_var = tk.BooleanVar(value=False)
        self.damage_friend_guard_var = tk.BooleanVar(value=False)
        self.damage_flower_gift_def_var = tk.BooleanVar(value=False)
        self.damage_power_override_var = tk.StringVar(value="")

        ttk.Label(battle_opts, text="Weather").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        self.damage_weather_combo = ttk.Combobox(
            battle_opts,
            textvariable=self.damage_weather_var,
            state="readonly",
            values=["None", "Sun", "Rain", "Sandstorm", "Hail"],
            width=11,
        )
        self.damage_weather_combo.grid(row=0, column=1, sticky="ew", pady=2)
        self.damage_weather_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")

        ttk.Label(battle_opts, text="Terrain").grid(row=0, column=2, sticky="w", padx=(10, 6), pady=2)
        self.damage_terrain_combo = ttk.Combobox(
            battle_opts,
            textvariable=self.damage_terrain_var,
            state="readonly",
            values=["None", "Electric", "Grassy", "Misty", "Psychic"],
            width=11,
        )
        self.damage_terrain_combo.grid(row=0, column=3, sticky="ew", pady=2)
        self.damage_terrain_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")

        effects_row = ttk.Frame(battle_opts)
        effects_row.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=(6, 2))
        effects_row.columnconfigure(0, weight=1)
        effects_row.columnconfigure(1, weight=1)

        atk_fx = ttk.LabelFrame(effects_row, text="Attacker effects", padding=6)
        atk_fx.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ttk.Checkbutton(
            atk_fx,
            text="Helping Hand",
            variable=self.damage_helping_hand_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            atk_fx,
            text="Charge",
            variable=self.damage_charge_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            atk_fx,
            text="Foresight",
            variable=self.damage_foresight_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            atk_fx,
            text="Power Spot",
            variable=self.damage_power_spot_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            atk_fx,
            text="Battery (Special)",
            variable=self.damage_battery_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            atk_fx,
            text="Steely Spirit (Steel)",
            variable=self.damage_steely_spirit_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            atk_fx,
            text="Flower Gift Atk (Sun)",
            variable=self.damage_flower_gift_atk_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")

        def_fx = ttk.LabelFrame(effects_row, text="Defender effects", padding=6)
        def_fx.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Checkbutton(
            def_fx,
            text="Reflect",
            variable=self.damage_reflect_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            def_fx,
            text="Light Screen",
            variable=self.damage_lightscreen_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            def_fx,
            text="Aurora Veil",
            variable=self.damage_aurora_veil_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            def_fx,
            text="Friend Guard",
            variable=self.damage_friend_guard_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")
        ttk.Checkbutton(
            def_fx,
            text="Flower Gift SpDef (Sun)",
            variable=self.damage_flower_gift_def_var,
            command=self._schedule_damage_calc_update,
        ).pack(anchor="w")

        self.damage_summary_var = tk.StringVar(value="Damage calculated: -")
        self.damage_summary_font = tkfont.Font(size=13, weight="bold")
        self.damage_summary_label = tk.Label(
            battle_opts,
            textvariable=self.damage_summary_var,
            font=self.damage_summary_font,
            anchor="w",
            justify="left",
            wraplength=520,
            bg="#f5f5f5",
            relief="solid",
            bd=1,
            padx=8,
            pady=8,
        )
        self.damage_summary_label.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 4))

        misc_row = ttk.Frame(battle_opts)
        misc_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 2))
        ttk.Checkbutton(
            misc_row,
            text="Critical hit",
            variable=self.damage_critical_var,
            command=self._schedule_damage_calc_update,
        ).pack(side="left")

        ttk.Label(battle_opts, text="Power override").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=(6, 2))
        power_entry = ttk.Entry(battle_opts, textvariable=self.damage_power_override_var, width=12)
        power_entry.grid(row=4, column=1, sticky="w", pady=(6, 2))
        power_entry.bind("<FocusOut>", lambda _e: self._schedule_damage_calc_update(), add="+")
        power_entry.bind("<Return>", lambda _e: self._schedule_damage_calc_update(), add="+")
        ttk.Label(
            battle_opts,
            text="Use this for variable/fixed-power moves when needed.",
            foreground="#606060",
            wraplength=320,
            justify="left",
        ).grid(row=4, column=2, columnspan=2, sticky="w", padx=(10, 0), pady=(6, 2))

        result_box = ttk.LabelFrame(center, text="Estimated Damage", padding=8)
        result_box.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        result_box.columnconfigure(0, weight=1)
        result_box.rowconfigure(0, weight=1)
        self.damage_result_text = tk.Text(result_box, wrap="word", height=10)
        self.damage_result_text.grid(row=0, column=0, sticky="nsew")
        self.damage_result_text.configure(state="disabled")

        root.bind(
            "<Configure>",
            lambda _e: (self._apply_damage_tab_layout(), self._schedule_damage_preview_refresh(), self._update_damage_summary_font()),
            add="+",
        )
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._on_damage_tab_changed(), add="+")
        left_col.bind("<Configure>", lambda _e: self._schedule_damage_preview_refresh(), add="+")
        right_col.bind("<Configure>", lambda _e: self._schedule_damage_preview_refresh(), add="+")
        battle_opts.bind("<Configure>", lambda _e: self._update_damage_summary_font(), add="+")

        self._apply_damage_tab_layout()
        self._update_damage_summary_font()
        self.root.after(120, self._on_damage_tab_changed)
        self._damage_init_defaults()
        self._schedule_damage_preview_refresh()
        self._schedule_damage_calc_update()

    def _on_damage_tab_changed(self):
        if not hasattr(self, "nb"):
            return
        try:
            selected = self.nb.select()
            tab_text = str(self.nb.tab(selected, "text"))
        except Exception:
            return
        if tab_text != "Damage":
            return
        self._apply_damage_tab_layout()
        self._schedule_damage_preview_refresh()

    def _apply_damage_tab_layout(self):
        root = getattr(self, "damage_root_frame", None)
        left_col = getattr(self, "damage_left_col", None)
        right_col = getattr(self, "damage_right_col", None)
        center = getattr(self, "damage_center_col", None)
        if root is None or left_col is None or right_col is None or center is None:
            return
        try:
            width = int(root.winfo_width())
        except Exception:
            return
        if width <= 1:
            try:
                root.after(40, self._apply_damage_tab_layout)
            except Exception:
                pass
            return

        if width >= 1450:
            side_min, center_min = 240, 380
            side_pad, center_pad = 8, 10
        elif width >= 1200:
            side_min, center_min = 210, 330
            side_pad, center_pad = 6, 8
        elif width >= 1020:
            side_min, center_min = 185, 285
            side_pad, center_pad = 4, 6
        else:
            side_min, center_min = 165, 245
            side_pad, center_pad = 3, 4

        signature = f"{side_min}:{center_min}:{side_pad}:{center_pad}"
        if getattr(self, "_damage_layout_mode", "") == signature:
            return

        # Keep the same 3-column layout at all window sizes; only scale sizing.
        left_col.grid_configure(row=0, column=0, sticky="nsew", padx=(0, side_pad), pady=0)
        center.grid_configure(row=0, column=1, columnspan=1, sticky="nsew", padx=center_pad, pady=0)
        right_col.grid_configure(row=0, column=2, sticky="nsew", padx=(side_pad, 0), pady=0)
        root.columnconfigure(0, weight=4, minsize=side_min, uniform="damage_cols")
        root.columnconfigure(1, weight=7, minsize=center_min, uniform="")
        root.columnconfigure(2, weight=4, minsize=side_min, uniform="damage_cols")
        root.rowconfigure(0, weight=1)
        root.rowconfigure(1, weight=0)

        self._damage_layout_mode = signature

    def _build_damage_side_panel(
        self,
        parent,
        *,
        side: str,
        title: str,
        column: int,
        row: int = 0,
        species_values: list[str],
        item_labels: list[str],
        nature_labels: list[str],
    ):
        shell = ttk.LabelFrame(parent, text=title, padding=8)
        shell.grid(row=row, column=column, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)
        existing_state = self._damage_state_by_side.get(side, {})
        existing_preview = existing_state.get("preview", {}) if isinstance(existing_state, dict) else {}

        state: dict[str, Any] = {
            "species_var": tk.StringVar(),
            "form_var": tk.StringVar(value="0"),
            "level_var": tk.StringVar(value="50"),
            "nature_var": tk.StringVar(),
            "ability_var": tk.StringVar(),
            "item_var": tk.StringVar(),
            "move_var": tk.StringVar(),
            "status_var": tk.StringVar(value="None"),
            "hp_pct_var": tk.StringVar(value="100"),
            "atk_stage_var": tk.StringVar(value="0"),
            "def_stage_var": tk.StringVar(value="0"),
            "def_stage_target_var": tk.StringVar(value="Def/SpDef"),
            "shiny_var": tk.BooleanVar(value=False),
            "ability_label_to_id": {},
            "ability_id_to_label": {},
            "move_label_to_id": {},
            "move_id_to_label": {},
            "hidden_abilities": set(),
            "base_vars": {},
            "iv_vars": {},
            "ev_vars": {},
            "final_vars": {},
            "stat_name_labels": {},
            "preview": existing_preview if isinstance(existing_preview, dict) else {},
        }
        self._damage_state_by_side[side] = state

        top = ttk.Frame(shell)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=3, uniform=f"damage_top_{side}")
        top.columnconfigure(1, weight=2, uniform=f"damage_top_{side}")

        ttk.Label(top, text="Species").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        species_combo = ttk.Combobox(top, textvariable=state["species_var"], width=16)
        species_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=3)
        self._set_combo_values(species_combo, species_values)
        self._enable_combo_search(species_combo)
        self._register_combo_tooltip_context(species_combo, kind="species", resolver=self.resolve_species_id)
        species_combo.bind("<<ComboboxSelected>>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")

        ttk.Label(top, text="Level").grid(row=0, column=2, sticky="w", padx=(0, 6), pady=3)
        level_row = ttk.Frame(top)
        level_row.grid(row=0, column=3, sticky="w", pady=3)
        level_entry = ttk.Entry(level_row, textvariable=state["level_var"], width=5)
        level_entry.pack(side="left")
        level_entry.bind("<FocusOut>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")
        level_entry.bind("<Return>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")
        tk.Checkbutton(top, text="★", variable=state["shiny_var"], fg="#cc8a00", width=2, command=self._schedule_damage_preview_refresh).grid(
            row=0, column=4, sticky="w", padx=(4, 0), pady=3
        )

        for old_shiny in top.grid_slaves(row=0, column=4):
            try:
                old_shiny.grid_remove()
            except Exception:
                pass

        ttk.Label(top, text="Form").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        form_entry = ttk.Entry(top, textvariable=state["form_var"], width=8)
        form_entry.grid(row=1, column=1, sticky="w", pady=3)
        form_entry.bind("<FocusOut>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")
        form_entry.bind("<Return>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")

        ttk.Label(top, text="Nature").grid(row=1, column=2, sticky="w", padx=(0, 6), pady=3)
        nature_combo = ttk.Combobox(top, textvariable=state["nature_var"], width=16)
        nature_combo.grid(row=1, column=3, sticky="ew", pady=3)
        self._set_combo_values(nature_combo, nature_labels)
        self._enable_combo_search(nature_combo)
        self._register_combo_tooltip_context(nature_combo, kind="nature", resolver=self._damage_resolve_selected_nature_id)
        nature_combo.bind("<<ComboboxSelected>>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")
        nature_combo.bind("<FocusOut>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")

        ttk.Label(top, text="Ability").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        ability_combo = ttk.Combobox(top, textvariable=state["ability_var"], width=16)
        ability_combo.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=3)
        self._enable_combo_search(ability_combo)
        self._register_combo_tooltip_context(
            ability_combo,
            kind="ability",
            resolver=lambda raw, _side=side: self._damage_resolve_selected_ability_id(_side, raw),
        )
        ability_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")
        ability_combo.bind("<FocusOut>", lambda _e: self._schedule_damage_calc_update(), add="+")

        ttk.Label(top, text="Item").grid(row=2, column=2, sticky="w", padx=(0, 6), pady=3)
        item_combo = ttk.Combobox(top, textvariable=state["item_var"], width=16)
        item_combo.grid(row=2, column=3, sticky="ew", pady=3)
        self._set_combo_values(item_combo, item_labels)
        self._enable_combo_search(item_combo)
        self._register_combo_tooltip_context(item_combo, kind="item", resolver=self._damage_resolve_selected_item_id)
        item_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_damage_misc_changed(), add="+")
        item_combo.bind("<FocusOut>", lambda _e: self._on_damage_misc_changed(), add="+")

        ttk.Label(top, text="Move").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=3)
        move_combo = ttk.Combobox(top, textvariable=state["move_var"], width=16)
        move_combo.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=3)
        self._enable_combo_search(move_combo)
        self._register_combo_tooltip_context(
            move_combo,
            kind="move",
            resolver=lambda raw, _side=side: self._damage_resolve_selected_move_id(_side, raw),
        )
        move_combo.bind("<<ComboboxSelected>>", lambda _e, s=side: self._on_damage_move_changed(s), add="+")
        move_combo.bind("<FocusOut>", lambda _e, s=side: self._on_damage_move_changed(s), add="+")

        ttk.Label(top, text="Status").grid(row=3, column=2, sticky="w", padx=(0, 6), pady=3)
        status_combo = ttk.Combobox(
            top,
            textvariable=state["status_var"],
            state="readonly",
            values=["None", "Burn", "Poison", "Toxic", "Paralysis", "Sleep", "Freeze"],
            width=12,
        )
        status_combo.grid(row=3, column=3, sticky="ew", pady=3)
        status_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_damage_misc_changed(), add="+")

        ttk.Label(top, text="HP%").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=3)
        hp_pct_entry = ttk.Entry(top, textvariable=state["hp_pct_var"], width=8)
        hp_pct_entry.grid(row=4, column=1, sticky="w", pady=3)
        hp_pct_entry.bind("<FocusOut>", lambda _e: self._schedule_damage_calc_update(), add="+")
        hp_pct_entry.bind("<Return>", lambda _e: self._schedule_damage_calc_update(), add="+")

        stage_row = ttk.Frame(top)
        stage_row.grid(row=4, column=2, columnspan=2, sticky="w", pady=3)
        ttk.Label(stage_row, text="Atk Stage").pack(side="left")
        atk_stage_combo = ttk.Combobox(
            stage_row,
            textvariable=state["atk_stage_var"],
            state="readonly",
            values=[str(i) for i in range(-6, 7)],
            width=4,
        )
        atk_stage_combo.pack(side="left", padx=(6, 10))
        atk_stage_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")

        ttk.Label(stage_row, text="Def Stage").pack(side="left")
        def_stage_combo = ttk.Combobox(
            stage_row,
            textvariable=state["def_stage_var"],
            state="readonly",
            values=[str(i) for i in range(-6, 7)],
            width=4,
        )
        def_stage_combo.pack(side="left", padx=(6, 0))
        def_stage_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")

        move_meta_var = tk.StringVar(value="Move data: -")
        ttk.Label(top, textvariable=move_meta_var, foreground="#606060").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(2, 4)
        )
        state["move_meta_var"] = move_meta_var
        state["widgets"] = {
            "species_combo": species_combo,
            "nature_combo": nature_combo,
            "ability_combo": ability_combo,
            "item_combo": item_combo,
            "move_combo": move_combo,
        }

        # Rebuild top editor layout to keep 2 columns per row with 60/40 width.
        for child in top.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        left_label_col_px = 54
        right_label_col_px = 50

        ability_box = ttk.Frame(top)
        ability_box.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=3)
        ability_box.columnconfigure(0, minsize=left_label_col_px)
        ability_box.columnconfigure(1, weight=1)
        ttk.Label(ability_box, text="Ability").grid(row=0, column=0, sticky="w", padx=(0, 4))
        ability_combo = ttk.Combobox(ability_box, textvariable=state["ability_var"], width=1)
        ability_combo.grid(row=0, column=1, sticky="ew")
        self._enable_combo_search(ability_combo)
        self._register_combo_tooltip_context(
            ability_combo,
            kind="ability",
            resolver=lambda raw, _side=side: self._damage_resolve_selected_ability_id(_side, raw),
        )
        ability_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")
        ability_combo.bind("<FocusOut>", lambda _e: self._schedule_damage_calc_update(), add="+")

        form_box = ttk.Frame(top)
        form_box.grid(row=0, column=1, sticky="ew", pady=3)
        form_box.columnconfigure(0, minsize=right_label_col_px)
        form_box.columnconfigure(1, weight=1)
        ttk.Label(form_box, text="Form").grid(row=0, column=0, sticky="w", padx=(0, 4))
        form_entry = ttk.Entry(form_box, textvariable=state["form_var"], width=1)
        form_entry.grid(row=0, column=1, sticky="ew")
        form_entry.bind("<FocusOut>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")
        form_entry.bind("<Return>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")

        nature_box = ttk.Frame(top)
        nature_box.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=3)
        nature_box.columnconfigure(0, minsize=left_label_col_px)
        nature_box.columnconfigure(1, weight=1)
        ttk.Label(nature_box, text="Nature").grid(row=0, column=0, sticky="w", padx=(0, 4))
        nature_combo = ttk.Combobox(nature_box, textvariable=state["nature_var"], width=1)
        nature_combo.grid(row=0, column=1, sticky="ew")
        self._set_combo_values(nature_combo, nature_labels)
        self._enable_combo_search(nature_combo)
        self._register_combo_tooltip_context(nature_combo, kind="nature", resolver=self._damage_resolve_selected_nature_id)
        nature_combo.bind("<<ComboboxSelected>>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")
        nature_combo.bind("<FocusOut>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")

        stage_box = ttk.Frame(top)
        stage_box.grid(row=1, column=1, sticky="ew", pady=3)
        stage_box.columnconfigure(0, minsize=right_label_col_px)
        stage_box.columnconfigure(1, weight=1)
        stage_box.columnconfigure(2, weight=0)
        defender_stage_target_combo = None
        if side == "attacker":
            ttk.Label(stage_box, text="Atk Stage").grid(row=0, column=0, sticky="w", padx=(0, 4))
            atk_stage_combo = ttk.Combobox(
                stage_box,
                textvariable=state["atk_stage_var"],
                state="readonly",
                values=[str(i) for i in range(-6, 7)],
                width=1,
            )
            atk_stage_combo.grid(row=0, column=1, sticky="ew")
            atk_stage_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")
        else:
            defender_stage_target_combo = ttk.Combobox(
                stage_box,
                textvariable=state["def_stage_target_var"],
                state="readonly",
                values=["Def/SpDef", "Def", "SpDef"],
                width=1,
            )
            defender_stage_target_combo.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            defender_stage_target_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")
            def_stage_combo = ttk.Combobox(
                stage_box,
                textvariable=state["def_stage_var"],
                state="readonly",
                values=[str(i) for i in range(-6, 7)],
                width=1,
            )
            def_stage_combo.grid(row=0, column=1, sticky="ew")
            def_stage_combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule_damage_calc_update(), add="+")

        move_box = ttk.Frame(top)
        move_box.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=3)
        move_box.columnconfigure(0, minsize=left_label_col_px)
        move_box.columnconfigure(1, weight=1)
        ttk.Label(move_box, text="Move").grid(row=0, column=0, sticky="w", padx=(0, 4))
        move_combo = ttk.Combobox(move_box, textvariable=state["move_var"], width=1)
        move_combo.grid(row=0, column=1, sticky="ew")
        self._enable_combo_search(move_combo)
        self._register_combo_tooltip_context(
            move_combo,
            kind="move",
            resolver=lambda raw, _side=side: self._damage_resolve_selected_move_id(_side, raw),
        )
        move_combo.bind("<<ComboboxSelected>>", lambda _e, s=side: self._on_damage_move_changed(s), add="+")
        move_combo.bind("<FocusOut>", lambda _e, s=side: self._on_damage_move_changed(s), add="+")

        status_box = ttk.Frame(top)
        status_box.grid(row=2, column=1, sticky="ew", pady=3)
        status_box.columnconfigure(0, minsize=right_label_col_px)
        status_box.columnconfigure(1, weight=1)
        ttk.Label(status_box, text="Status").grid(row=0, column=0, sticky="w", padx=(0, 4))
        status_combo = ttk.Combobox(
            status_box,
            textvariable=state["status_var"],
            state="readonly",
            values=["None", "Burn", "Poison", "Toxic", "Paralysis", "Sleep", "Freeze"],
            width=1,
        )
        status_combo.grid(row=0, column=1, sticky="ew")
        status_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_damage_misc_changed(), add="+")

        item_box = ttk.Frame(top)
        item_box.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=3)
        item_box.columnconfigure(0, minsize=left_label_col_px)
        item_box.columnconfigure(1, weight=1)
        ttk.Label(item_box, text="Item").grid(row=0, column=0, sticky="w", padx=(0, 4))
        item_combo = ttk.Combobox(item_box, textvariable=state["item_var"], width=1)
        item_combo.grid(row=0, column=1, sticky="ew")
        self._set_combo_values(item_combo, item_labels)
        self._enable_combo_search(item_combo)
        self._register_combo_tooltip_context(item_combo, kind="item", resolver=self._damage_resolve_selected_item_id)
        item_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_damage_misc_changed(), add="+")
        item_combo.bind("<FocusOut>", lambda _e: self._on_damage_misc_changed(), add="+")

        hp_box = ttk.Frame(top)
        hp_box.grid(row=3, column=1, sticky="ew", pady=3)
        hp_box.columnconfigure(0, minsize=right_label_col_px)
        hp_box.columnconfigure(1, weight=1)
        ttk.Label(hp_box, text="HP%").grid(row=0, column=0, sticky="w", padx=(0, 4))
        hp_pct_entry = ttk.Entry(hp_box, textvariable=state["hp_pct_var"], width=1)
        hp_pct_entry.grid(row=0, column=1, sticky="ew")
        hp_pct_entry.bind("<FocusOut>", lambda _e: self._schedule_damage_calc_update(), add="+")
        hp_pct_entry.bind("<Return>", lambda _e: self._schedule_damage_calc_update(), add="+")

        move_meta_var = tk.StringVar(value="Move data: -")
        ttk.Label(top, textvariable=move_meta_var, foreground="#606060").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(2, 4)
        )
        state["move_meta_var"] = move_meta_var
        state["widgets"] = {
            "species_combo": None,
            "level_entry": None,
            "nature_combo": nature_combo,
            "ability_combo": ability_combo,
            "item_combo": item_combo,
            "move_combo": move_combo,
            "form_entry": form_entry,
            "def_stage_target_combo": defender_stage_target_combo,
        }

        stats = ttk.LabelFrame(shell, text="Stats", padding=6)
        stats.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        for c in range(5):
            stats.columnconfigure(c, weight=0)
        stats.columnconfigure(1, weight=1)
        stats.columnconfigure(4, weight=1)
        ttk.Label(stats, text=" ").grid(row=0, column=0, padx=(0, 4), pady=(0, 4))
        ttk.Label(stats, text="Base").grid(row=0, column=1, padx=4, pady=(0, 4))
        ttk.Label(stats, text="IV").grid(row=0, column=2, padx=4, pady=(0, 4))
        ttk.Label(stats, text="EV").grid(row=0, column=3, padx=4, pady=(0, 4))
        ttk.Label(stats, text="Stat").grid(row=0, column=4, padx=4, pady=(0, 4))
        for row, (stat_id, stat_label) in enumerate(STAT_ORDER, start=1):
            name_lbl = tk.Label(stats, text=f"{stat_label}:", width=6, anchor="e")
            name_lbl.grid(row=row, column=0, sticky="e", padx=(0, 4), pady=2)
            state["stat_name_labels"][stat_id] = name_lbl

            base_var = tk.StringVar(value="0")
            state["base_vars"][stat_id] = base_var
            ttk.Label(stats, textvariable=base_var, width=6, anchor="center").grid(row=row, column=1, padx=4, pady=2)

            iv_var = tk.StringVar(value="31")
            state["iv_vars"][stat_id] = iv_var
            iv_entry = ttk.Entry(stats, textvariable=iv_var, width=6)
            iv_entry.grid(row=row, column=2, padx=4, pady=2)
            iv_entry.bind("<FocusOut>", lambda _e, s=side: self._on_damage_iv_ev_changed(s), add="+")
            iv_entry.bind("<Return>", lambda _e, s=side: self._on_damage_iv_ev_changed(s), add="+")

            ev_var = tk.StringVar(value="0")
            state["ev_vars"][stat_id] = ev_var
            ev_entry = ttk.Entry(stats, textvariable=ev_var, width=6)
            ev_entry.grid(row=row, column=3, padx=4, pady=2)
            ev_entry.bind("<FocusOut>", lambda _e, s=side: self._on_damage_iv_ev_changed(s), add="+")
            ev_entry.bind("<Return>", lambda _e, s=side: self._on_damage_iv_ev_changed(s), add="+")

            final_var = tk.StringVar(value="0")
            state["final_vars"][stat_id] = final_var
            ttk.Label(stats, textvariable=final_var, width=8, anchor="center").grid(row=row, column=4, padx=4, pady=2)

        ttk.Label(
            stats,
            text="IV: 0-31 each (total cap 186). EV: 0-252 each.",
            foreground="#606060",
        ).grid(row=8, column=0, columnspan=5, sticky="w", pady=(6, 0))

    def _build_damage_preview_card(self, parent, *, side: str, column: int):
        card = ttk.LabelFrame(parent, text=f"{side.capitalize()} Preview", padding=6)
        card.grid(row=0, column=column, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=0)
        card.rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            card,
            width=150,
            height=190,
            bg="#f6f6f6",
            highlightthickness=1,
            highlightbackground="#bdbdbd",
        )
        canvas.grid(row=0, column=0, columnspan=2, sticky="nsew")
        placeholder = tk.PhotoImage(width=96, height=96)
        img_id = canvas.create_image(75, 94, image=placeholder, anchor="center")
        text_id = canvas.create_text(
            75,
            176,
            text="(No Pokemon)",
            fill="#5f5f5f",
            font=("", 10, "bold"),
            anchor="s",
        )
        summary_species_var = tk.StringVar(value="-")
        summary_meta_var = tk.StringVar(value="Status: None")
        state = self._damage_state_by_side.get(side)
        if state is not None:
            state["preview"] = {
                "card": card,
                "canvas": canvas,
                "image_id": img_id,
                "text_id": text_id,
                "image_ref": placeholder,
            }

        item_row = ttk.Frame(card)
        item_row.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        shiny_var = state["shiny_var"] if isinstance(state, dict) and "shiny_var" in state else tk.BooleanVar(value=False)
        shiny_toggle = tk.Checkbutton(
            item_row,
            text="\u2605",
            variable=shiny_var,
            fg="#cc8a00",
            width=2,
            command=self._schedule_damage_preview_refresh,
        )
        shiny_toggle.pack(side="left", padx=(0, 8))
        item_icon_host = tk.Frame(item_row, width=28, height=28, bg="#f6f6f6", relief="solid", bd=1)
        item_icon_host.pack(side="left")
        item_icon_host.pack_propagate(False)
        item_icon = tk.Label(item_icon_host, bg="#f6f6f6")
        item_placeholder = tk.PhotoImage(width=24, height=24)
        item_icon.configure(image=item_placeholder)
        item_icon.image = item_placeholder
        item_icon.pack(fill="both", expand=True)
        item_name_var = tk.StringVar(value="(No item)")
        ttk.Label(item_row, textvariable=item_name_var).pack(side="left", padx=(6, 0))
        meta_row = ttk.Frame(card)
        meta_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        meta_row.columnconfigure(0, weight=1)
        meta_row.columnconfigure(1, weight=0)

        edit_box = ttk.Frame(meta_row)
        edit_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        edit_box.columnconfigure(1, weight=1)
        ttk.Label(edit_box, text="Species").grid(row=0, column=0, sticky="w", padx=(0, 6))
        species_combo = ttk.Combobox(
            edit_box,
            textvariable=state["species_var"] if isinstance(state, dict) else tk.StringVar(),
            width=22,
        )
        species_combo.grid(row=0, column=1, sticky="ew")
        self._set_combo_values(species_combo, self._damage_species_choice_values())
        self._enable_combo_search(species_combo)
        self._register_combo_tooltip_context(species_combo, kind="species", resolver=self.resolve_species_id)
        species_combo.bind("<<ComboboxSelected>>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")
        species_combo.bind("<FocusOut>", lambda _e, s=side: self._on_damage_species_or_form_changed(s), add="+")

        ttk.Label(edit_box, text="Level").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(3, 0))
        level_entry = ttk.Entry(
            edit_box,
            textvariable=state["level_var"] if isinstance(state, dict) else tk.StringVar(value="50"),
            width=8,
        )
        level_entry.grid(row=1, column=1, sticky="w", pady=(3, 0))
        level_entry.bind("<FocusOut>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")
        level_entry.bind("<Return>", lambda _e, s=side: self._on_damage_level_or_nature_changed(s), add="+")

        summary_box = ttk.Frame(meta_row)
        summary_box.grid(row=0, column=1, sticky="ne", padx=(2, 0))
        ttk.Label(summary_box, textvariable=summary_species_var, font=("", 9, "bold")).pack(anchor="w")
        ttk.Label(summary_box, textvariable=summary_meta_var).pack(anchor="w", pady=(2, 0))
        type_host = ttk.Frame(summary_box)
        type_host.pack(anchor="w", pady=(3, 0))
        self._render_type_chip_row(
            type_host,
            [],
            short=True,
            empty_text="-",
            max_per_row=3,
            chip_width=TYPE_CHIP_COMPACT_WIDTH,
        )
        if state is not None:
            state["preview"].update(
                {
                    "item_icon": item_icon,
                    "item_placeholder": item_placeholder,
                    "item_name_var": item_name_var,
                    "species_var": summary_species_var,
                    "meta_var": summary_meta_var,
                    "type_host": type_host,
                    "shiny_toggle": shiny_toggle,
                }
            )
            widgets = state.get("widgets", {})
            if isinstance(widgets, dict):
                widgets["species_combo"] = species_combo
                widgets["level_entry"] = level_entry

    def _damage_species_choice_values(self) -> list[str]:
        if not self.catalogs:
            return []
        base_species = self.catalogs.base_species_choices()
        if base_species:
            values = [item.internal_id for item in base_species]
        else:
            values = list(self.catalogs.species_by_id.keys())
        values.sort(key=str.casefold)
        return values

    def _damage_item_choice_labels(self) -> list[str]:
        self._damage_item_label_to_id: dict[str, str] = {}
        self._damage_item_id_to_label: dict[str, str] = {}
        self._damage_item_label_to_id["(None)"] = ""
        self._damage_item_id_to_label[""] = "(None)"
        if not self.catalogs:
            return ["(None)"]
        pairs: list[tuple[str, str]] = []
        for item_id in self.get_merged_held_item_options(include_key_items=False):
            label = self._english_item_name_for_id(item_id)
            if any(existing == label for existing, _iid in pairs):
                label = f"{label} [{item_id}]"
            pairs.append((label, item_id))
        pairs.sort(key=lambda row: row[0].casefold())
        for label, item_id in pairs:
            self._damage_item_label_to_id[label] = item_id
            self._damage_item_id_to_label.setdefault(item_id, label)
        return ["(None)"] + [label for label, _iid in pairs]

    def _damage_nature_choice_labels(self) -> list[str]:
        self._damage_nature_label_to_id: dict[str, str] = {}
        self._damage_nature_id_to_label: dict[str, str] = {}
        if self.catalogs:
            nature_ids = sorted(
                (self._nature_choice(n) for n in self.catalogs.natures if str(n).strip()),
                key=str.casefold,
            )
        else:
            nature_ids = sorted(
                {
                    "HARDY", "LONELY", "BRAVE", "ADAMANT", "NAUGHTY",
                    "BOLD", "DOCILE", "RELAXED", "IMPISH", "LAX",
                    "TIMID", "HASTY", "SERIOUS", "JOLLY", "NAIVE",
                    "MODEST", "MILD", "QUIET", "BASHFUL", "RASH",
                    "CALM", "GENTLE", "SASSY", "CAREFUL", "QUIRKY",
                },
                key=str.casefold,
            )
        labels: list[str] = []
        for nature_id in nature_ids:
            label = self._nature_label_for_id(nature_id)
            if label in self._damage_nature_label_to_id:
                label = f"{label} [{nature_id}]"
            self._damage_nature_label_to_id[label] = nature_id
            self._damage_nature_id_to_label.setdefault(nature_id, label)
            labels.append(label)
        return labels

    def _damage_side_state(self, side: str) -> dict[str, Any]:
        state = self._damage_state_by_side.get(str(side or "").strip().lower())
        if state is None:
            raise KeyError(f"Unknown damage side: {side!r}")
        return state

    def _damage_species_form(self, side: str) -> tuple[str, int]:
        state = self._damage_side_state(side)
        raw_species = state["species_var"].get().strip()
        if not raw_species:
            return "", 0
        try:
            species_id = self.resolve_species_id(raw_species)
        except Exception:
            species_id = ""
        form = self._clamp_int(state["form_var"].get(), 0, 999, 0)
        state["form_var"].set(str(form))
        return species_id, form

    def _damage_resolve_selected_nature_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if raw in getattr(self, "_damage_nature_label_to_id", {}):
            return self._damage_nature_label_to_id[raw]
        cleaned = re.sub(r"\s+\([^)]+\)\s*$", "", raw)
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        cleaned = extract_internal_id(cleaned).strip().lstrip(":").upper()
        return cleaned

    def _damage_resolve_selected_item_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "(None)":
            return ""
        if raw in getattr(self, "_damage_item_label_to_id", {}):
            return self._damage_item_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw).strip()
        cleaned = extract_internal_id(cleaned).strip()
        if not cleaned:
            return ""
        if self.catalogs:
            try:
                return self.resolve_item_id(cleaned)
            except Exception:
                return self.catalogs.canonical_item_id(cleaned) or ""
        return cleaned.lstrip(":")

    def _damage_resolve_selected_ability_id(self, side: str, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "(None)":
            return ""
        state = self._damage_side_state(side)
        label_to_id = state.get("ability_label_to_id", {})
        if raw in label_to_id:
            return label_to_id[raw]
        cleaned = re.sub(r"\s+\(H\)\s*$", "", raw)
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        if self.catalogs:
            try:
                return self.resolve_ability_id(cleaned)
            except Exception:
                return self.catalogs.canonical_ability_id(cleaned) or ""
        return cleaned.lstrip(":")

    def _damage_resolve_selected_move_id(self, side: str, text: str) -> str:
        raw = str(text or "").strip()
        if not raw or raw == "(None)":
            return ""
        state = self._damage_side_state(side)
        label_to_id = state.get("move_label_to_id", {})
        if raw in label_to_id:
            return label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw)
        cleaned = extract_internal_id(cleaned).strip()
        if self.catalogs:
            try:
                return self.resolve_move_id(cleaned)
            except Exception:
                return self.catalogs.canonical_move_id(cleaned) or ""
        return cleaned.lstrip(":")

    def _damage_move_label_for_id(self, move_id: str) -> str:
        return self._move_display_name_for_id(move_id)

    def _damage_default_move_id(self, move_ids: list[str]) -> str:
        if not self.catalogs:
            return move_ids[0] if move_ids else ""
        for move_id in move_ids:
            canonical = self.catalogs.canonical_move_id(move_id) or move_id
            move = self.catalogs.moves_by_id.get(canonical)
            if not move:
                continue
            category = self._damage_parse_move_category(move.extra.get("Category", ""))
            power = self._clamp_int(str(move.extra.get("Power", "0")), 0, 999, 0)
            if category != "status" and power > 0:
                return canonical
        return move_ids[0] if move_ids else ""

    def _damage_init_defaults(self):
        if not self._damage_state_by_side:
            return
        species_values = self._damage_species_choice_values()
        default_nature = self._damage_nature_id_to_label.get("HARDY", self._nature_label_for_id("HARDY"))

        for side in ("attacker", "defender"):
            state = self._damage_side_state(side)
            if side == "attacker":
                default_species = species_values[0] if species_values else ""
            else:
                default_species = species_values[1] if len(species_values) > 1 else (species_values[0] if species_values else "")
            state["species_var"].set(default_species)
            state["form_var"].set("0")
            state["level_var"].set("50")
            state["nature_var"].set(default_nature)
            state["item_var"].set("(None)")
            state["status_var"].set("None")
            state["hp_pct_var"].set("100")
            state["atk_stage_var"].set("0")
            state["def_stage_var"].set("0")
            state["def_stage_target_var"].set("Def/SpDef")
            state["shiny_var"].set(False)
            for sid, _label in STAT_ORDER:
                state["iv_vars"][sid].set("31")
                state["ev_vars"][sid].set("0")

        self._refresh_damage_legality_dropdowns("attacker", reset_invalid=True)
        self._refresh_damage_legality_dropdowns("defender", reset_invalid=True)
        self._refresh_damage_side_stats("attacker")
        self._refresh_damage_side_stats("defender")
        self._refresh_damage_move_metadata("attacker")
        self._refresh_damage_move_metadata("defender")

    def _refresh_damage_legality_dropdowns(self, side: str, reset_invalid: bool):
        if not self.catalogs:
            return
        state = self._damage_side_state(side)
        species_id, form = self._damage_species_form(side)
        if not species_id:
            return
        ability_combo = state["widgets"]["ability_combo"]
        move_combo = state["widgets"]["move_combo"]

        ability_ids, hidden_ids = self.catalogs.valid_abilities_for_species(species_id, form=form)
        if not ability_ids:
            ability_ids = sorted(self.catalogs.abilities_by_id.keys(), key=str.casefold)
            hidden_ids = set()
        ability_pairs: list[tuple[str, str]] = []
        for ability_id in ability_ids:
            label = self._ability_label_for_id(ability_id, set(hidden_ids))
            if any(existing == label for existing, _ in ability_pairs):
                label = f"{label} [{ability_id}]"
            ability_pairs.append((label, ability_id))
        ability_pairs.sort(key=lambda x: x[0].casefold())
        state["hidden_abilities"] = set(hidden_ids)
        state["ability_label_to_id"] = {label: aid for label, aid in ability_pairs}
        state["ability_id_to_label"] = {}
        for label, ability_id in ability_pairs:
            state["ability_id_to_label"].setdefault(ability_id, label)
        ability_labels = ["(None)"] + [label for label, _ in ability_pairs]
        self._set_combo_values(ability_combo, ability_labels)
        current_ability_id = self._damage_resolve_selected_ability_id(side, state["ability_var"].get())
        if current_ability_id and current_ability_id in state["ability_id_to_label"]:
            state["ability_var"].set(state["ability_id_to_label"][current_ability_id])
        elif reset_invalid:
            state["ability_var"].set(ability_labels[1] if len(ability_labels) > 1 else "(None)")

        move_ids = self.catalogs.valid_moves_for_species(species_id, form=form)
        if not move_ids:
            move_ids = sorted(self.catalogs.moves_by_id.keys(), key=str.casefold)
        move_pairs: list[tuple[str, str]] = []
        for move_id in move_ids:
            label = self._damage_move_label_for_id(move_id)
            if any(existing == label for existing, _ in move_pairs):
                label = f"{label} [{move_id}]"
            move_pairs.append((label, move_id))
        move_pairs.sort(key=lambda x: x[0].casefold())
        state["move_label_to_id"] = {label: mid for label, mid in move_pairs}
        state["move_id_to_label"] = {}
        for label, move_id in move_pairs:
            state["move_id_to_label"].setdefault(move_id, label)
        move_labels = ["(None)"] + [label for label, _ in move_pairs]
        self._set_combo_values(move_combo, move_labels)
        current_move_id = self._damage_resolve_selected_move_id(side, state["move_var"].get())
        if current_move_id and current_move_id in state["move_id_to_label"]:
            state["move_var"].set(state["move_id_to_label"][current_move_id])
        elif reset_invalid:
            default_move_id = self._damage_default_move_id(move_ids)
            if default_move_id and default_move_id in state["move_id_to_label"]:
                state["move_var"].set(state["move_id_to_label"][default_move_id])
            else:
                state["move_var"].set(move_labels[1] if len(move_labels) > 1 else "(None)")
        self._refresh_damage_move_metadata(side)

    def _damage_nature_changed_stats(self, side: str) -> tuple[str | None, str | None]:
        state = self._damage_side_state(side)
        nature = self._damage_resolve_selected_nature_id(state["nature_var"].get())
        if not nature:
            return None, None
        return NATURE_EFFECTS.get(nature, (None, None))

    def _damage_nature_multiplier(self, side: str, stat_id: str) -> int:
        up, down = self._damage_nature_changed_stats(side)
        if stat_id == up:
            return 110
        if stat_id == down:
            return 90
        return 100

    def _damage_calc_stat_value(self, side: str, stat_id: str, base: int, level: int, iv: int, ev: int) -> int:
        if stat_id == "HP":
            if base == 1:
                return 1
            return (((base * 2) + iv + (ev // 4)) * level // 100) + level + 10
        core_val = (((base * 2) + iv + (ev // 4)) * level // 100) + 5
        return (core_val * self._damage_nature_multiplier(side, stat_id)) // 100

    def _damage_current_iv_values(self, side: str) -> dict[str, int]:
        state = self._damage_side_state(side)
        out: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            out[sid] = self._clamp_int(state["iv_vars"][sid].get(), 0, 31, 0)
        total = sum(out.values())
        if total > 186:
            overflow = total - 186
            for sid, _label in reversed(STAT_ORDER):
                if overflow <= 0:
                    break
                reducible = min(overflow, out[sid])
                out[sid] -= reducible
                overflow -= reducible
        return out

    def _damage_current_ev_values(self, side: str) -> dict[str, int]:
        state = self._damage_side_state(side)
        out: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            out[sid] = self._clamp_int(state["ev_vars"][sid].get(), 0, 252, 0)
        return out

    def _update_damage_side_nature_colors(self, side: str):
        state = self._damage_side_state(side)
        up, down = self._damage_nature_changed_stats(side)
        for stat_id, lbl in state["stat_name_labels"].items():
            if stat_id == up:
                lbl.configure(fg="#c03535")
            elif stat_id == down:
                lbl.configure(fg="#2b5fc9")
            else:
                lbl.configure(fg="black")

    def _refresh_damage_side_stats(self, side: str):
        state = self._damage_side_state(side)
        species_id, form = self._damage_species_form(side)
        base_stats = self.catalogs.base_stats_for_species(species_id, form=form) if self.catalogs and species_id else {}
        level = self._clamp_int(state["level_var"].get(), 1, 100, 1)
        state["level_var"].set(str(level))
        ivs = self._damage_current_iv_values(side)
        evs = self._damage_current_ev_values(side)
        for sid, _label in STAT_ORDER:
            state["iv_vars"][sid].set(str(ivs[sid]))
            state["ev_vars"][sid].set(str(evs[sid]))
            state["base_vars"][sid].set(str(base_stats.get(sid, 0)))
            state["final_vars"][sid].set(
                str(self._damage_calc_stat_value(side, sid, base_stats.get(sid, 0), level, ivs[sid], evs[sid]))
            )
        self._update_damage_side_nature_colors(side)

    def _refresh_damage_move_metadata(self, side: str):
        state = self._damage_side_state(side)
        move_id = self._damage_resolve_selected_move_id(side, state["move_var"].get())
        if not move_id or not self.catalogs:
            state["move_meta_var"].set("Move data: -")
            return
        move = self.catalogs.moves_by_id.get(self.catalogs.canonical_move_id(move_id) or move_id)
        if not move:
            state["move_meta_var"].set(f"Move data: {self._english_move_name_for_id(move_id)}")
            return
        move_type = str(move.extra.get("Type", "")).strip().lstrip(":").upper() or "-"
        category = str(move.extra.get("Category", "")).strip().lstrip(":").upper() or "-"
        power = str(move.extra.get("Power", "")).strip() or "-"
        accuracy = str(move.extra.get("Accuracy", "")).strip() or "-"
        state["move_meta_var"].set(
            f"Move data: {self._english_move_name_for_id(move_id)} | {self._type_display_name_for_id(move_type)} | "
            f"{self._prettify_internal_id(category)} | Pow {power} | Acc {accuracy}"
        )

    def _on_damage_species_or_form_changed(self, side: str):
        self._refresh_damage_legality_dropdowns(side, reset_invalid=True)
        self._refresh_damage_side_stats(side)
        self._schedule_damage_preview_refresh()
        self._schedule_damage_calc_update()

    def _on_damage_level_or_nature_changed(self, side: str):
        self._refresh_damage_side_stats(side)
        self._schedule_damage_preview_refresh()
        self._schedule_damage_calc_update()

    def _on_damage_iv_ev_changed(self, side: str):
        self._refresh_damage_side_stats(side)
        self._schedule_damage_calc_update()

    def _on_damage_move_changed(self, side: str):
        self._refresh_damage_move_metadata(side)
        self._schedule_damage_calc_update()

    def _on_damage_misc_changed(self):
        self._schedule_damage_preview_refresh()
        self._schedule_damage_calc_update()

    def _damage_snapshot_side(self, side: str) -> dict[str, Any]:
        state = self._damage_side_state(side)
        species_id, form = self._damage_species_form(side)
        return {
            "species_id": species_id,
            "form": form,
            "level": self._clamp_int(state["level_var"].get(), 1, 100, 50),
            "nature_id": self._damage_resolve_selected_nature_id(state["nature_var"].get()) or "HARDY",
            "ability_id": self._damage_resolve_selected_ability_id(side, state["ability_var"].get()),
            "item_id": self._damage_resolve_selected_item_id(state["item_var"].get()),
            "move_id": self._damage_resolve_selected_move_id(side, state["move_var"].get()),
            "status": str(state["status_var"].get() or "None"),
            "hp_pct": self._clamp_int(state["hp_pct_var"].get(), 0, 100, 100),
            "atk_stage": self._clamp_int(state["atk_stage_var"].get(), -6, 6, 0),
            "def_stage": self._clamp_int(state["def_stage_var"].get(), -6, 6, 0),
            "def_stage_target": (
                str(state["def_stage_target_var"].get() or "").strip()
                if str(state["def_stage_target_var"].get() or "").strip().upper() in {"DEF", "SPDEF"}
                else ""
            ),
            "shiny": bool(state["shiny_var"].get()),
            "ivs": {sid: self._clamp_int(state["iv_vars"][sid].get(), 0, 31, 0) for sid, _ in STAT_ORDER},
            "evs": {sid: self._clamp_int(state["ev_vars"][sid].get(), 0, 252, 0) for sid, _ in STAT_ORDER},
        }

    def _damage_apply_snapshot(self, side: str, snapshot: dict[str, Any]):
        state = self._damage_side_state(side)
        self._damage_syncing = True
        try:
            state["species_var"].set(str(snapshot.get("species_id", "")))
            state["form_var"].set(str(self._clamp_int(str(snapshot.get("form", 0)), 0, 999, 0)))
            state["level_var"].set(str(self._clamp_int(str(snapshot.get("level", 50)), 1, 100, 50)))
            nature_id = str(snapshot.get("nature_id", "HARDY")).strip().upper()
            state["nature_var"].set(self._damage_nature_id_to_label.get(nature_id, self._nature_label_for_id(nature_id)))
            state["status_var"].set(str(snapshot.get("status", "None")))
            state["hp_pct_var"].set(str(self._clamp_int(str(snapshot.get("hp_pct", 100)), 0, 100, 100)))
            state["atk_stage_var"].set(str(self._clamp_int(str(snapshot.get("atk_stage", 0)), -6, 6, 0)))
            state["def_stage_var"].set(str(self._clamp_int(str(snapshot.get("def_stage", 0)), -6, 6, 0)))
            target = str(snapshot.get("def_stage_target", "")).strip().upper()
            if target == "SPDEF":
                state["def_stage_target_var"].set("SpDef")
            elif target == "DEF":
                state["def_stage_target_var"].set("Def")
            else:
                state["def_stage_target_var"].set("Def/SpDef")
            state["shiny_var"].set(bool(snapshot.get("shiny", False)))
            ivs = snapshot.get("ivs", {}) if isinstance(snapshot.get("ivs"), dict) else {}
            evs = snapshot.get("evs", {}) if isinstance(snapshot.get("evs"), dict) else {}
            for sid, _label in STAT_ORDER:
                state["iv_vars"][sid].set(str(self._clamp_int(str(ivs.get(sid, 31)), 0, 31, 31)))
                state["ev_vars"][sid].set(str(self._clamp_int(str(evs.get(sid, 0)), 0, 252, 0)))
            self._refresh_damage_legality_dropdowns(side, reset_invalid=True)
            ability_id = str(snapshot.get("ability_id", "")).strip()
            if ability_id:
                state["ability_var"].set(state["ability_id_to_label"].get(ability_id, state["ability_var"].get()))
            item_id = str(snapshot.get("item_id", "")).strip()
            state["item_var"].set(self._damage_item_id_to_label.get(item_id, "(None)"))
            move_id = str(snapshot.get("move_id", "")).strip()
            if move_id:
                state["move_var"].set(state["move_id_to_label"].get(move_id, state["move_var"].get()))
            self._refresh_damage_side_stats(side)
            self._refresh_damage_move_metadata(side)
        finally:
            self._damage_syncing = False

    def _swap_damage_roles(self):
        if not self._damage_state_by_side:
            return
        atk_snapshot = self._damage_snapshot_side("attacker")
        def_snapshot = self._damage_snapshot_side("defender")
        self._damage_apply_snapshot("attacker", def_snapshot)
        self._damage_apply_snapshot("defender", atk_snapshot)
        self._schedule_damage_preview_refresh()
        self._schedule_damage_calc_update()

    def _schedule_damage_preview_refresh(self):
        if not hasattr(self, "root"):
            return
        if self._damage_preview_update_job is not None:
            try:
                self.root.after_cancel(self._damage_preview_update_job)
            except Exception:
                pass
            self._damage_preview_update_job = None
        try:
            self._damage_preview_update_job = self.root.after(50, self._run_damage_preview_refresh)
        except Exception:
            self._damage_preview_update_job = None

    def _run_damage_preview_refresh(self):
        self._damage_preview_update_job = None
        if not self._damage_state_by_side:
            return
        self._apply_damage_tab_layout()
        try:
            for side in ("attacker", "defender"):
                self._update_damage_preview_for_side(side)
        except Exception:
            return

    def _damage_preview_target_size(self, side: str) -> tuple[int, int]:
        try:
            state = self._damage_side_state(side)
        except Exception:
            return 120, 150
        card = state.get("preview", {}).get("card")
        if card is None:
            return 120, 150
        card_w = max(1, int(card.winfo_width()))
        card_h = max(1, int(card.winfo_height()))
        if card_w <= 2:
            card_w = 120
        if card_h <= 2:
            card_h = 170
        root_w = max(360, int(self.root.winfo_width())) if hasattr(self, "root") else 1300
        if root_w >= 1700:
            max_w, max_h = 250, 330
        elif root_w >= 1450:
            max_w, max_h = 220, 300
        elif root_w >= 1200:
            max_w, max_h = 190, 255
        elif root_w >= 1000:
            max_w, max_h = 165, 220
        else:
            max_w, max_h = 140, 190
        target_w = max(72, min(max_w, card_w - 14))
        reserved_footer_h = 122
        max_canvas_h = max(36, card_h - reserved_footer_h)
        preferred_h = min(max_h, int(target_w * 1.28))
        target_h = min(max_canvas_h, max(36, preferred_h))
        return target_w, target_h

    def _get_damage_preview_base_image_for_fields(self, species_id: str, form: int, shiny: bool) -> tk.PhotoImage | None:
        species = str(species_id or "").strip().lstrip(":")
        if not species:
            return None
        subdir = "Front shiny" if shiny else "Front"
        root_dir = self.game_root / "Graphics" / "Pokemon" / subdir
        for stem in self._pokemon_icon_candidates_from_fields(species, form=form):
            cache_key = f"damage-base:{subdir}:{stem}"
            if cache_key in self._damage_icon_cache:
                return self._damage_icon_cache[cache_key]
            path = root_dir / f"{stem}.png"
            if not path.exists():
                continue
            try:
                img = tk.PhotoImage(file=str(path))
                img = self._normalize_icon_frame(img)
            except Exception:
                continue
            self._damage_icon_cache[cache_key] = img
            self._prune_dict_cache(self._damage_icon_cache, 1200)
            return img
        return self._get_party_icon_image_for_fields(species, form=form, shiny=shiny)

    def _get_damage_scaled_icon(self, species_id: str, form: int, shiny: bool, target_w: int, target_h: int) -> tk.PhotoImage | None:
        base = self._get_damage_preview_base_image_for_fields(species_id, form=form, shiny=shiny)
        if base is None:
            return None
        w = max(32, int(target_w))
        h = max(32, int(target_h))
        key = f"damage-scaled:{species_id}:{form}:{int(shiny)}:{w}x{h}"
        cached = self._damage_icon_cache.get(key)
        if cached is not None:
            return cached

        img = base
        try:
            src_w = max(1, base.width())
            src_h = max(1, base.height())
            ratio = min(w / src_w, h / src_h)
            ratio = max(0.05, ratio)
            frac = Fraction(ratio).limit_denominator(12)
            num = max(1, int(frac.numerator))
            den = max(1, int(frac.denominator))
            if num != 1:
                img = img.zoom(num, num)
            if den != 1:
                img = img.subsample(den, den)
        except Exception:
            pass

        self._damage_icon_cache[key] = img
        self._prune_dict_cache(self._damage_icon_cache, 900)
        return img

    def _get_damage_preview_item_icon(self, item_id: str, size: int = 24) -> tk.PhotoImage | None:
        iid = str(item_id or "").strip()
        if not iid:
            return None
        base = self._get_item_icon_image(iid)
        if base is None:
            return None
        target = max(12, int(size))
        key = f"damage-item:{iid}:{target}"
        cached = self._damage_icon_cache.get(key)
        if cached is not None:
            return cached
        img = base
        try:
            factor = max(
                1,
                int(math.ceil(base.width() / max(1, target))),
                int(math.ceil(base.height() / max(1, target))),
            )
            if factor > 1:
                img = base.subsample(factor, factor)
        except Exception:
            img = base
        self._damage_icon_cache[key] = img
        self._prune_dict_cache(self._damage_icon_cache, 1200)
        return img

    def _update_damage_preview_for_side(self, side: str):
        state = self._damage_side_state(side)
        preview = state.get("preview", {})
        canvas = preview.get("canvas")
        if canvas is None:
            return
        target_w, target_h = self._damage_preview_target_size(side)
        if self._damage_last_preview_size != (target_w, target_h):
            self._damage_last_preview_size = (target_w, target_h)
        try:
            canvas.configure(width=target_w, height=target_h)
        except Exception:
            pass
        actual_w = int(canvas.winfo_width())
        actual_h = int(canvas.winfo_height())
        if actual_w <= 2:
            actual_w = target_w
        if actual_h <= 2:
            actual_h = target_h

        species_id, form = self._damage_species_form(side)
        shiny = bool(state["shiny_var"].get())
        sprite_box_w = max(64, int(actual_w * (2 / 3)))
        sprite_box_h = max(80, int(actual_h * (2 / 3)))
        sprite = self._get_damage_scaled_icon(species_id, form, shiny, sprite_box_w, sprite_box_h) if species_id else None
        if sprite is None:
            sprite = preview.get("image_ref")
        if sprite is None:
            sprite = tk.PhotoImage(width=96, height=96)
        preview["image_ref"] = sprite
        text = "" if species_id else "(No Pokemon)"
        sprite_y = max(34, min(actual_h - 28, int(actual_h * 0.42)))
        try:
            canvas.itemconfigure(preview["image_id"], image=sprite)
            canvas.coords(preview["image_id"], actual_w // 2, sprite_y)
            canvas.itemconfigure(preview["text_id"], text=text)
            canvas.coords(preview["text_id"], actual_w // 2, actual_h - 8)
        except Exception:
            pass

        item_id = self._damage_resolve_selected_item_id(state["item_var"].get())
        item_icon = self._get_damage_preview_item_icon(item_id, size=24) if item_id else None
        if item_icon is None:
            item_icon = preview.get("item_placeholder")
        try:
            preview["item_icon"].configure(image=item_icon)
            preview["item_icon"].image = item_icon
            preview["item_name_var"].set(self._english_item_name_for_id(item_id) if item_id else "(No item)")
        except Exception:
            pass

        status = str(state["status_var"].get() or "None")
        try:
            preview["species_var"].set(self._english_species_name_for_id(species_id) if species_id else "-")
            preview["meta_var"].set(f"Status: {status}")
            type_ids = self._dex_species_type_ids(species_id, form=form) if species_id and self.catalogs else []
            self._render_type_chip_row(
                preview["type_host"],
                type_ids,
                short=True,
                empty_text="-",
                max_per_row=3,
                chip_width=TYPE_CHIP_COMPACT_WIDTH,
            )
        except Exception:
            pass

    def _schedule_damage_calc_update(self):
        if self._damage_syncing:
            return
        if not hasattr(self, "root"):
            return
        if self._damage_calc_update_job is not None:
            try:
                self.root.after_cancel(self._damage_calc_update_job)
            except Exception:
                pass
            self._damage_calc_update_job = None
        try:
            self._damage_calc_update_job = self.root.after(45, self._run_damage_calc_update)
        except Exception:
            self._damage_calc_update_job = None

    def _run_damage_calc_update(self):
        self._damage_calc_update_job = None
        if not hasattr(self, "damage_result_text"):
            return
        report = self._damage_calc_report()
        summary, details = self._damage_split_summary_from_report(report)
        if hasattr(self, "damage_summary_var"):
            self.damage_summary_var.set(summary)
            self._update_damage_summary_font()
        if details.strip():
            self._set_text_widget_content(self.damage_result_text, details)
        else:
            self.damage_result_text.configure(state="normal")
            self.damage_result_text.delete("1.0", "end")
            self.damage_result_text.configure(state="disabled")

    @staticmethod
    def _damage_split_summary_from_report(report: str) -> tuple[str, str]:
        text = str(report or "").strip()
        if not text:
            return "Damage calculated: -", ""
        lines = text.splitlines()
        marker_idx = -1
        for i, line in enumerate(lines):
            if str(line).strip().startswith("Damage calculated:"):
                marker_idx = i
                break
        if marker_idx >= 0:
            summary = str(lines[marker_idx]).strip()
            details = "\n".join(lines[:marker_idx] + lines[marker_idx + 1 :]).strip()
            return summary, details
        summary = str(lines[0]).strip()
        details = "\n".join(lines[1:]).strip()
        return summary, details

    def _update_damage_summary_font(self):
        label = getattr(self, "damage_summary_label", None)
        font_obj = getattr(self, "damage_summary_font", None)
        if label is None or font_obj is None:
            return
        try:
            width = int(label.winfo_width())
        except Exception:
            width = 0
        if width <= 1:
            return
        size = max(11, min(21, width // 44))
        try:
            font_obj.configure(size=size)
            label.configure(wraplength=max(200, width - 14))
        except Exception:
            return

    @staticmethod
    def _damage_stage_multiplier(stage: int) -> float:
        s = max(-6, min(6, int(stage)))
        if s >= 0:
            return (2 + s) / 2
        return 2 / (2 - s)

    @staticmethod
    def _damage_is_major_status(status_text: str) -> bool:
        token = str(status_text or "").strip().upper()
        return token not in {"", "NONE", "OK"}

    def _damage_hp_ratio(self, side: str) -> float:
        state = self._damage_side_state(side)
        pct = self._clamp_int(state["hp_pct_var"].get(), 0, 100, 100)
        state["hp_pct_var"].set(str(pct))
        return pct / 100.0

    @staticmethod
    def _damage_parse_move_category(raw: str) -> str:
        token = str(raw or "").strip().lstrip(":").upper()
        if token in {"0", "PHYSICAL", "PHYS"}:
            return "physical"
        if token in {"1", "SPECIAL", "SPEC"}:
            return "special"
        if token in {"2", "STATUS"}:
            return "status"
        if "SPECIAL" in token:
            return "special"
        if "STATUS" in token:
            return "status"
        return "physical"

    def _damage_type_multiplier(self, move_type: str, defender_types: list[str]) -> float:
        if not move_type:
            return 1.0
        defense_map, _order = self._dex_load_type_chart_data()
        mult = 1.0
        for def_type in defender_types:
            mult *= float(defense_map.get(def_type, {}).get(move_type, 1.0))
        return mult

    def _damage_can_evolve(self, species_id: str, form: int = 0) -> bool:
        if not self.catalogs or not species_id:
            return False
        rows = self.catalogs.species_evolution_rows(species_id, form=form)
        return bool(rows)

    def _damage_calc_report(self) -> str:
        if not self.catalogs:
            return "Game catalog is not loaded. Load valid game data first."
        atk_state = self._damage_side_state("attacker")
        def_state = self._damage_side_state("defender")
        atk_species, atk_form = self._damage_species_form("attacker")
        def_species, def_form = self._damage_species_form("defender")
        if not atk_species or not def_species:
            return "Choose both attacker and defender species to calculate damage."

        move_id = self._damage_resolve_selected_move_id("attacker", atk_state["move_var"].get())
        if not move_id:
            return "Select an attacking move in the Attacker panel."
        move_key = self.catalogs.canonical_move_id(move_id) or move_id
        move = self.catalogs.moves_by_id.get(move_key)
        if not move:
            return "Selected move is missing in move data."

        move_type = str(move.extra.get("Type", "")).strip().lstrip(":").upper()
        category = self._damage_parse_move_category(move.extra.get("Category", ""))
        if category == "status":
            return "Selected move is a status move (no direct damage)."

        override_raw = str(self.damage_power_override_var.get() if hasattr(self, "damage_power_override_var") else "").strip()
        if override_raw:
            power = self._clamp_int(override_raw, 1, 999, 1)
            power_source = "override"
        else:
            power = self._clamp_int(str(move.extra.get("Power", "0")), 0, 999, 0)
            power_source = "data"
        if power <= 0:
            return (
                "Move power is 0 or variable in current data.\n"
                "Set Power override in Battle Modifiers to estimate damage."
            )

        level = self._clamp_int(atk_state["level_var"].get(), 1, 100, 50)
        atk_state["level_var"].set(str(level))
        atk_stat_id = "ATTACK" if category == "physical" else "SPECIAL_ATTACK"
        def_stat_id = "DEFENSE" if category == "physical" else "SPECIAL_DEFENSE"
        atk_stat = self._clamp_int(atk_state["final_vars"][atk_stat_id].get(), 1, 9999, 1)
        def_stat = self._clamp_int(def_state["final_vars"][def_stat_id].get(), 1, 9999, 1)

        is_crit = bool(self.damage_critical_var.get()) if hasattr(self, "damage_critical_var") else False
        atk_stage = self._clamp_int(atk_state["atk_stage_var"].get(), -6, 6, 0)
        def_stage = self._clamp_int(def_state["def_stage_var"].get(), -6, 6, 0)
        def_stage_target = "AUTO"
        try:
            raw_target = str(def_state["def_stage_target_var"].get() or "").strip().upper()
            if raw_target in {"DEF", "SPDEF"}:
                def_stage_target = raw_target
            else:
                def_stage_target = "AUTO"
        except Exception:
            def_stage_target = "AUTO"
        uses_def_stage = (
            category == "physical" and def_stage_target in {"DEF", "AUTO"}
        ) or (
            category == "special" and def_stage_target in {"SPDEF", "AUTO"}
        )
        if not uses_def_stage:
            def_stage = 0
        if is_crit and atk_stage < 0:
            atk_stage = 0
        if is_crit and def_stage > 0:
            def_stage = 0
        atk_stage_mult = self._damage_stage_multiplier(atk_stage)
        def_stage_mult = self._damage_stage_multiplier(def_stage)
        effective_atk = max(1, int(round(atk_stat * atk_stage_mult)))
        effective_def = max(1, int(round(def_stat * def_stage_mult)))

        atk_ability = self._damage_resolve_selected_ability_id("attacker", atk_state["ability_var"].get())
        def_ability = self._damage_resolve_selected_ability_id("defender", def_state["ability_var"].get())
        atk_item = self._damage_resolve_selected_item_id(atk_state["item_var"].get())
        def_item = self._damage_resolve_selected_item_id(def_state["item_var"].get())
        atk_status = str(atk_state["status_var"].get() or "None")
        def_status = str(def_state["status_var"].get() or "None")
        weather = str(self.damage_weather_var.get() if hasattr(self, "damage_weather_var") else "None").strip().upper()
        terrain = str(self.damage_terrain_var.get() if hasattr(self, "damage_terrain_var") else "None").strip().upper()

        attacker_types = self._dex_species_type_ids(atk_species, form=atk_form)
        defender_types = self._dex_species_type_ids(def_species, form=def_form)
        attacker_effects: list[str] = []
        defender_effects: list[str] = []
        atk_ability_label = self._english_ability_name_for_id(atk_ability) if atk_ability else ""
        def_ability_label = self._english_ability_name_for_id(def_ability) if def_ability else ""
        atk_item_label = self._english_item_name_for_id(atk_item) if atk_item else ""
        def_item_label = self._english_item_name_for_id(def_item) if def_item else ""

        def add_unique_effect(bucket: list[str], label: str):
            text = str(label or "").strip()
            if text and text not in bucket:
                bucket.append(text)

        defender_types_for_chart = list(defender_types)
        if hasattr(self, "damage_foresight_var") and bool(self.damage_foresight_var.get()) and move_type in {"NORMAL", "FIGHTING"}:
            defender_types_for_chart = [tid for tid in defender_types_for_chart if tid != "GHOST"]
            add_unique_effect(attacker_effects, "Foresight")
        type_mult = self._damage_type_multiplier(move_type, defender_types_for_chart)

        # Ability-based immunities and resist/weak modifiers.
        if def_ability == "LEVITATE" and move_type == "GROUND":
            type_mult = 0.0
            add_unique_effect(defender_effects, f"{def_ability_label} (Immune)")
        if def_ability in {"WATERABSORB", "STORMDRAIN", "DRYSKIN"} and move_type == "WATER":
            type_mult = 0.0
            add_unique_effect(defender_effects, f"{def_ability_label} (Immune)")
        if def_ability in {"VOLTABSORB", "LIGHTNINGROD", "MOTORDRIVE"} and move_type == "ELECTRIC":
            type_mult = 0.0
            add_unique_effect(defender_effects, f"{def_ability_label} (Immune)")
        if def_ability == "FLASHFIRE" and move_type == "FIRE":
            type_mult = 0.0
            add_unique_effect(defender_effects, f"{def_ability_label} (Immune)")
        if def_ability == "SAPSIPPER" and move_type == "GRASS":
            type_mult = 0.0
            add_unique_effect(defender_effects, f"{def_ability_label} (Immune)")
        if def_ability == "THICKFAT" and move_type in {"FIRE", "ICE"} and type_mult > 0:
            type_mult *= 0.5
            add_unique_effect(defender_effects, def_ability_label)
        if def_ability == "DRYSKIN" and move_type == "FIRE" and type_mult > 0:
            type_mult *= 1.25
            add_unique_effect(defender_effects, "Dry Skin (Fire weakness)")

        attack_mod = 1.0
        defense_mod = 1.0
        final_mod = 1.0
        ally_mod = 1.0

        if hasattr(self, "damage_helping_hand_var") and bool(self.damage_helping_hand_var.get()):
            # Helping Hand boosts ally's move damage this turn by 1.5x.
            ally_mod *= 1.5
            add_unique_effect(attacker_effects, "Helping Hand")
        if hasattr(self, "damage_charge_var") and bool(self.damage_charge_var.get()) and move_type == "ELECTRIC":
            # Charge doubles the next Electric-type move's damage.
            ally_mod *= 2.0
            add_unique_effect(attacker_effects, "Charge")
        if hasattr(self, "damage_power_spot_var") and bool(self.damage_power_spot_var.get()):
            ally_mod *= 1.3
            add_unique_effect(attacker_effects, "Power Spot")
        if hasattr(self, "damage_battery_var") and bool(self.damage_battery_var.get()) and category == "special":
            ally_mod *= 1.3
            add_unique_effect(attacker_effects, "Battery")
        if hasattr(self, "damage_steely_spirit_var") and bool(self.damage_steely_spirit_var.get()) and move_type == "STEEL":
            ally_mod *= 1.5
            add_unique_effect(attacker_effects, "Steely Spirit")
        if (
            hasattr(self, "damage_flower_gift_atk_var")
            and bool(self.damage_flower_gift_atk_var.get())
            and weather == "SUN"
            and category == "physical"
        ):
            attack_mod *= 1.5
            add_unique_effect(attacker_effects, "Flower Gift (Atk)")

        if category == "physical":
            if atk_ability in {"HUGEPOWER", "PUREPOWER"}:
                attack_mod *= 2.0
                add_unique_effect(attacker_effects, atk_ability_label)
            if atk_ability == "HUSTLE":
                attack_mod *= 1.5
                add_unique_effect(attacker_effects, atk_ability_label)
            if atk_ability == "GUTS" and self._damage_is_major_status(atk_status):
                attack_mod *= 1.5
                add_unique_effect(attacker_effects, f"{atk_ability_label} ({atk_status})")
            if atk_item == "CHOICEBAND":
                attack_mod *= 1.5
                add_unique_effect(attacker_effects, atk_item_label)
            if self._damage_is_major_status(atk_status) and atk_status.strip().upper() == "BURN" and atk_ability != "GUTS":
                attack_mod *= 0.5
                add_unique_effect(attacker_effects, "Burn (Atk halved)")
            if bool(self.damage_reflect_var.get()) and not is_crit:
                final_mod *= 0.5
                add_unique_effect(defender_effects, "Reflect")
            if atk_item == "MUSCLEBAND":
                final_mod *= 1.1
                add_unique_effect(attacker_effects, atk_item_label)
            if def_ability == "MARVELSCALE" and self._damage_is_major_status(def_status):
                defense_mod *= 1.5
                add_unique_effect(defender_effects, f"{def_ability_label} ({def_status})")
        else:
            if atk_ability == "SOLARPOWER" and weather == "SUN":
                attack_mod *= 1.5
                add_unique_effect(attacker_effects, f"{atk_ability_label} (Sun)")
            if atk_item == "CHOICESPECS":
                attack_mod *= 1.5
                add_unique_effect(attacker_effects, atk_item_label)
            if atk_item == "WISEGLASSES":
                final_mod *= 1.1
                add_unique_effect(attacker_effects, atk_item_label)
            if bool(self.damage_lightscreen_var.get()) and not is_crit:
                final_mod *= 0.5
                add_unique_effect(defender_effects, "Light Screen")
            if def_item == "ASSAULTVEST":
                defense_mod *= 1.5
                add_unique_effect(defender_effects, def_item_label)
            if weather == "SANDSTORM" and "ROCK" in defender_types:
                defense_mod *= 1.5
                add_unique_effect(defender_effects, "Sandstorm (Rock SpDef)")

        if hasattr(self, "damage_aurora_veil_var") and bool(self.damage_aurora_veil_var.get()) and not is_crit:
            final_mod *= 0.5
            add_unique_effect(defender_effects, "Aurora Veil")
        if hasattr(self, "damage_friend_guard_var") and bool(self.damage_friend_guard_var.get()):
            final_mod *= 0.75
            add_unique_effect(defender_effects, "Friend Guard")
        if (
            hasattr(self, "damage_flower_gift_def_var")
            and bool(self.damage_flower_gift_def_var.get())
            and weather == "SUN"
            and category == "special"
        ):
            defense_mod *= 1.5
            add_unique_effect(defender_effects, "Flower Gift (SpDef)")

        if def_item == "EVIOLITE" and self._damage_can_evolve(def_species, def_form):
            defense_mod *= 1.5
            add_unique_effect(defender_effects, def_item_label)
        if atk_item == "LIFEORB":
            final_mod *= 1.3
            add_unique_effect(attacker_effects, atk_item_label)
        if atk_item == "EXPERTBELT" and type_mult > 1.0:
            final_mod *= 1.2
            add_unique_effect(attacker_effects, atk_item_label)
        if atk_ability == "TECHNICIAN" and power <= 60:
            final_mod *= 1.5
            add_unique_effect(attacker_effects, atk_ability_label)
        if def_ability in {"FILTER", "SOLIDROCK", "PRISMARMOR"} and type_mult > 1.0:
            final_mod *= 0.75
            add_unique_effect(defender_effects, def_ability_label)
        if def_ability in {"MULTISCALE", "SHADOWSHIELD"} and self._damage_hp_ratio("defender") >= 0.999:
            final_mod *= 0.5
            add_unique_effect(defender_effects, def_ability_label)
        if atk_ability == "TINTEDLENS" and 0 < type_mult < 1.0:
            final_mod *= 2.0
            add_unique_effect(attacker_effects, atk_ability_label)

        weather_mod = 1.0
        if weather == "SUN":
            if move_type == "FIRE":
                weather_mod *= 1.5
                add_unique_effect(attacker_effects, "Sun (Fire boost)")
            elif move_type == "WATER":
                weather_mod *= 0.5
                add_unique_effect(defender_effects, "Sun (Water weaken)")
        elif weather == "RAIN":
            if move_type == "WATER":
                weather_mod *= 1.5
                add_unique_effect(attacker_effects, "Rain (Water boost)")
            elif move_type == "FIRE":
                weather_mod *= 0.5
                add_unique_effect(defender_effects, "Rain (Fire weaken)")

        terrain_mod = 1.0
        if terrain == "ELECTRIC" and move_type == "ELECTRIC":
            terrain_mod *= 1.3
            add_unique_effect(attacker_effects, "Electric Terrain")
        elif terrain == "GRASSY" and move_type == "GRASS":
            terrain_mod *= 1.3
            add_unique_effect(attacker_effects, "Grassy Terrain")
        elif terrain == "PSYCHIC" and move_type == "PSYCHIC":
            terrain_mod *= 1.3
            add_unique_effect(attacker_effects, "Psychic Terrain")
        elif terrain == "MISTY" and move_type == "DRAGON":
            terrain_mod *= 0.5
            add_unique_effect(defender_effects, "Misty Terrain")

        stab = 1.0
        if move_type and move_type in attacker_types:
            stab = 2.0 if atk_ability == "ADAPTABILITY" else 1.5
            if atk_ability == "ADAPTABILITY":
                add_unique_effect(attacker_effects, atk_ability_label)
        crit_mod = 1.5 if is_crit else 1.0
        if is_crit and atk_ability == "SNIPER":
            crit_mod *= 1.5
            add_unique_effect(attacker_effects, atk_ability_label)
        if is_crit:
            add_unique_effect(attacker_effects, "Critical hit")

        effective_atk = max(1, int(round(effective_atk * attack_mod)))
        effective_def = max(1, int(round(effective_def * defense_mod)))
        base_damage = (((((2 * level) // 5) + 2) * power * effective_atk) // effective_def) // 50 + 2
        base_damage = max(1, int(base_damage))

        total_modifier = stab * type_mult * weather_mod * terrain_mod * final_mod * crit_mod
        total_modifier *= ally_mod
        if type_mult <= 0:
            min_damage = 0
            max_damage = 0
        else:
            min_damage = int(math.floor(base_damage * total_modifier * 0.85))
            max_damage = int(math.floor(base_damage * total_modifier))
            min_damage = max(1, min_damage)
            max_damage = max(min_damage, max_damage)

        defender_max_hp = self._clamp_int(def_state["final_vars"]["HP"].get(), 1, 9999, 1)
        defender_cur_hp = max(1, int(round(defender_max_hp * self._damage_hp_ratio("defender"))))
        min_pct = (min_damage / defender_max_hp) * 100 if defender_max_hp > 0 else 0.0
        max_pct = (max_damage / defender_max_hp) * 100 if defender_max_hp > 0 else 0.0

        if max_damage <= 0:
            ko_text = "No damage (immune)."
        elif min_damage >= defender_cur_hp:
            ko_text = "Guaranteed OHKO on current HP."
        elif max_damage < defender_cur_hp:
            hits = int(math.ceil(defender_cur_hp / max(1, max_damage)))
            ko_text = f"Not OHKO. Best case: {hits} hit(s) to KO current HP."
        else:
            ko_text = "Possible OHKO range."

        move_name = self._english_move_name_for_id(move_key)
        cat_label = "Physical" if category == "physical" else "Special"
        type_label = self._type_display_name_for_id(move_type) if move_type else "Unknown"
        eff_label = self._dex_multiplier_label(type_mult) if hasattr(self, "_dex_multiplier_label") else f"{type_mult:.2f}x"
        damage_calculated_line = (
            f"Damage calculated: {ko_text} | Current HP {defender_cur_hp} | "
            f"Actual damage {min_damage}-{max_damage}"
            if max_damage > 0
            else f"Damage calculated: {ko_text}"
        )

        lines = [
            damage_calculated_line,
            f"{self._english_species_name_for_id(atk_species)} -> {self._english_species_name_for_id(def_species)}",
            f"Move: {move_name} ({cat_label}, {type_label})",
            f"Power: {power} ({power_source}) | Lv: {level}",
            f"Damage: {min_damage} - {max_damage} HP ({min_pct:.1f}% - {max_pct:.1f}% of max HP)",
            f"Type effectiveness: {eff_label} | STAB {stab:.2f}x",
            f"Atk/Def used: {effective_atk}/{effective_def} ({atk_stat_id}/{def_stat_id})",
            (
                f"Attacker effects: {', '.join(attacker_effects)}"
                if attacker_effects
                else "Attacker effects: (none)"
            ),
            (
                f"Defender effects: {', '.join(defender_effects)}"
                if defender_effects
                else "Defender effects: (none)"
            ),
            (
                f"Mods: Weather {weather_mod:.2f}x | Terrain {terrain_mod:.2f}x | "
                f"Ally {ally_mod:.2f}x | Final {final_mod:.2f}x | Crit {crit_mod:.2f}x"
            ),
        ]
        return "\n".join(lines)

    def _build_bag_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Bag")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        top = ttk.Frame(tab)
        top.pack(fill="x")

        ttk.Label(top, text="Pocket").pack(side="left")
        self.bag_pocket_var = tk.StringVar()
        self.bag_pocket_option_to_index: dict[str, int] = {}
        pocket_values: list[str] = []
        # Always show English pocket labels in UI.
        for i in range(1, 9):
            label = f"{i} - {EN_POCKET_NAMES.get(i, f'Pocket {i}')}"
            self.bag_pocket_option_to_index[label] = i
            pocket_values.append(label)
        label0 = f"0 - {EN_POCKET_NAMES.get(0, 'Unused')}"
        self.bag_pocket_option_to_index[label0] = 0
        pocket_values.append(label0)
        self.bag_pocket_var.set(pocket_values[0])
        self.bag_pocket_combo = ttk.Combobox(
            top, textvariable=self.bag_pocket_var, state="readonly", width=20, values=pocket_values
        )
        self.bag_pocket_combo.pack(side="left", padx=(6, 6))
        self.bag_pocket_combo.bind("<<ComboboxSelected>>", self.on_bag_pocket_selected)
        ttk.Button(top, text="Refresh Pocket", command=self.refresh_bag_list).pack(side="left")

        body = ttk.Panedwindow(tab, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(8, 0))

        left = ttk.Frame(body)
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(left, weight=2)
        body.add(right, weight=3)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)

        self.bag_list = tk.Listbox(left, exportselection=False)
        self.bag_list.pack(fill="both", expand=True)
        self.bag_list.bind("<<ListboxSelect>>", self.on_bag_item_select)

        self.bag_item_var = tk.StringVar()
        self.bag_qty_var = tk.StringVar()
        self._bag_item_label_to_id: dict[str, str] = {}
        self._bag_item_id_to_label: dict[str, str] = {}
        item_values: list[str] = []
        ttk.Label(right, text="Item").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        self.bag_item_combo = ttk.Combobox(right, textvariable=self.bag_item_var, width=38)
        self.bag_item_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=4)
        self._set_combo_values(self.bag_item_combo, item_values)
        self._enable_combo_search(self.bag_item_combo)
        self._register_combo_tooltip_context(self.bag_item_combo, kind="item", resolver=self.resolve_selected_bag_item_id)
        self._register_description_widget(self.bag_item_combo, "bag", "item")
        self.bag_item_combo.bind("<<ComboboxSelected>>", lambda _e: self.update_bag_description(), add="+")
        self.bag_item_combo.bind("<FocusOut>", lambda _e: self.update_bag_description(), add="+")
        self.bag_item_combo.bind("<Enter>", lambda _e: self.update_bag_description(), add="+")
        self._add_labeled_entry(right, "Quantity", self.bag_qty_var, 1, 0)

        btns = ttk.Frame(right)
        btns.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(btns, text="Add New", command=self.bag_add_item).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="Update Selected", command=self.bag_update_item).pack(side="left", padx=4)
        ttk.Button(btns, text="Remove Selected", command=self.bag_remove_item).pack(side="left", padx=4)
        ttk.Button(btns, text="Add All", command=self.bag_add_all_items).pack(side="left", padx=4)
        ttk.Button(btns, text="Update All", command=self.bag_update_all_items).pack(side="left", padx=4)
        bag_desc_frame = ttk.LabelFrame(right, text="Description", padding=6)
        bag_desc_frame.grid(row=3, column=0, columnspan=4, sticky="nsew", pady=(12, 0))
        self.bag_desc_text = tk.Text(bag_desc_frame, height=8, wrap="word")
        self.bag_desc_text.pack(fill="both", expand=True)
        self.bag_desc_text.configure(state="disabled")
        self.update_bag_item_dropdown()
        self.update_bag_description()

    def _build_flags_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Switches/Vars")
        tab.columnconfigure(0, weight=1)

        sw_frame = ttk.LabelFrame(tab, text="Switch", padding=8)
        sw_frame.pack(fill="x")
        sw_frame.columnconfigure(1, weight=1)
        self.switch_index_var = tk.StringVar(value="1")
        self.switch_value_var = tk.BooleanVar(value=False)
        self._add_labeled_entry(sw_frame, "Index", self.switch_index_var, 0, 0, width=8)
        ttk.Checkbutton(sw_frame, text="Value", variable=self.switch_value_var).grid(row=0, column=2, sticky="w", padx=10)
        ttk.Button(sw_frame, text="Load", command=self.load_switch).grid(row=0, column=3, padx=4)
        ttk.Button(sw_frame, text="Apply", command=self.apply_switch).grid(row=0, column=4, padx=4)

        var_frame = ttk.LabelFrame(tab, text="Variable", padding=8)
        var_frame.pack(fill="x", pady=(10, 0))
        var_frame.columnconfigure(1, weight=1)
        self.var_index_var = tk.StringVar(value="1")
        self.var_value_var = tk.StringVar()
        self.var_type_label_var = tk.StringVar(value="Type: ?")
        self._add_labeled_entry(var_frame, "Index", self.var_index_var, 0, 0, width=8)
        self._add_labeled_entry(var_frame, "Value", self.var_value_var, 1, 0, width=50)
        ttk.Label(var_frame, textvariable=self.var_type_label_var).grid(row=1, column=2, sticky="w", padx=8)
        btns = ttk.Frame(var_frame)
        btns.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(btns, text="Load", command=self.load_variable).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="Apply", command=self.apply_variable).pack(side="left", padx=4)

    def _build_advanced_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Advanced")

        row1 = ttk.Frame(tab)
        row1.pack(fill="x")
        ttk.Label(row1, text="Path").pack(side="left")
        self.adv_path_var = tk.StringVar(value="player.@money")
        ttk.Entry(row1, textvariable=self.adv_path_var).pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Button(row1, text="Get", command=self.adv_get).pack(side="left")

        row2 = ttk.Frame(tab)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Value").pack(side="left")
        self.adv_value_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.adv_value_var).pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Label(row2, text="Type").pack(side="left")
        self.adv_type_var = tk.StringVar(value="auto")
        ttk.Combobox(
            row2,
            textvariable=self.adv_type_var,
            state="readonly",
            width=10,
            values=["auto", "int", "float", "str", "bool", "nil", "symbol", "json"],
        ).pack(side="left", padx=(6, 6))
        ttk.Button(row2, text="Set", command=self.adv_set).pack(side="left")

        row3 = ttk.Frame(tab)
        row3.pack(fill="x", pady=(8, 0))
        ttk.Button(row3, text="List Children", command=self.adv_list_children).pack(side="left")

        self.adv_output = tk.Text(tab, height=24, wrap="none")
        self.adv_output.pack(fill="both", expand=True, pady=(8, 0))

    def _build_custom_item_tab(self):
        tab = ttk.Frame(self.nb)
        self.custom_item_tab = tab
        self.nb.add(tab, text="CustomItem")
        self._custom_item_tab_visible = True
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        content_shell = ttk.Frame(tab)
        content_shell.grid(row=0, column=0, sticky="nsew")
        content_shell.columnconfigure(0, weight=1)
        content_shell.rowconfigure(0, weight=1)

        self.custom_item_scroll_canvas = tk.Canvas(content_shell, borderwidth=0, highlightthickness=0)
        self.custom_item_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.custom_item_scroll_vscroll = ttk.Scrollbar(
            content_shell, orient="vertical", command=self.custom_item_scroll_canvas.yview
        )
        self.custom_item_scroll_vscroll.grid(row=0, column=1, sticky="ns")
        self.custom_item_scroll_canvas.configure(yscrollcommand=self.custom_item_scroll_vscroll.set)
        self.custom_item_scroll_canvas.bind("<MouseWheel>", self._on_custom_item_tab_mousewheel, add="+")
        self.custom_item_scroll_canvas.bind("<Button-4>", self._on_custom_item_tab_mousewheel, add="+")
        self.custom_item_scroll_canvas.bind("<Button-5>", self._on_custom_item_tab_mousewheel, add="+")
        self._custom_item_wheel_bound_widgets = set()

        workspace = ttk.Frame(self.custom_item_scroll_canvas, padding=10)
        self._custom_item_scroll_window = self.custom_item_scroll_canvas.create_window((0, 0), window=workspace, anchor="nw")
        workspace.bind("<Configure>", self._on_custom_item_workspace_configure, add="+")
        self.custom_item_scroll_canvas.bind("<Configure>", self._on_custom_item_canvas_configure, add="+")

        workspace.columnconfigure(0, weight=1, minsize=220)
        workspace.columnconfigure(1, weight=3, minsize=560)
        workspace.rowconfigure(1, weight=1)

        self.custom_item_status_var = tk.StringVar(
            value="Manage custom item metadata + hybrid effect cloning (item/ability/move templates)."
        )
        self.custom_item_base_source_var = tk.StringVar()
        top = ttk.Frame(workspace)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.custom_item_status_var, foreground="#555555").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(top, text="Reload Manifest", command=self._custom_reload_manifest).grid(row=0, column=1, sticky="e")
        ttk.Button(top, text="Clear Form", command=self._custom_clear_form).grid(row=0, column=2, sticky="e", padx=(6, 0))
        ttk.Button(top, text="Auto Setup (Game+Save)", command=self.custom_item_auto_setup).grid(
            row=0, column=3, sticky="e", padx=(6, 0)
        )

        base_row = ttk.Frame(top)
        base_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        base_row.columnconfigure(1, weight=1)
        ttk.Label(base_row, text="Load Base Item").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.custom_item_base_source_combo = ttk.Combobox(
            base_row,
            textvariable=self.custom_item_base_source_var,
            width=42,
        )
        self.custom_item_base_source_combo.grid(row=0, column=1, sticky="ew")
        self._enable_combo_search(self.custom_item_base_source_combo)
        self._register_combo_tooltip_context(self.custom_item_base_source_combo, kind="item", resolver=self._custom_resolve_item_id)
        ttk.Button(base_row, text="Load Base -> Form", command=self._custom_load_base_item).grid(
            row=0, column=2, sticky="e", padx=(6, 0)
        )
        ttk.Button(base_row, text="New Default", command=self._custom_new_default).grid(
            row=0, column=3, sticky="e", padx=(6, 0)
        )

        left = ttk.LabelFrame(workspace, text="Custom Items", padding=8)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Manifest Entries").grid(row=0, column=0, sticky="w")
        self.custom_item_listbox = tk.Listbox(left, height=18, exportselection=False)
        self.custom_item_listbox.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.custom_item_listbox.bind("<<ListboxSelect>>", self._custom_on_select_item, add="+")
        list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.custom_item_listbox.yview)
        list_scroll.grid(row=1, column=1, sticky="ns", pady=(4, 0))
        self.custom_item_listbox.configure(yscrollcommand=list_scroll.set)

        right = ttk.LabelFrame(workspace, text="Editor", padding=8)
        right.grid(row=1, column=1, sticky="nsew")
        for idx in range(4):
            right.columnconfigure(idx, weight=1 if idx in {1, 3} else 0)

        self.custom_item_id_var = tk.StringVar()
        self.custom_item_name_var = tk.StringVar()
        self.custom_item_name_plural_var = tk.StringVar()
        self.custom_item_pocket_var = tk.StringVar(value="1 - Items")
        self.custom_item_price_var = tk.StringVar(value="0")
        self.custom_item_sell_price_var = tk.StringVar(value="0")
        self.custom_item_bp_price_var = tk.StringVar(value="1")
        self.custom_item_field_use_var = tk.StringVar(value="0 - None")
        self.custom_item_battle_use_var = tk.StringVar(value="0 - None")
        self.custom_item_flags_var = tk.StringVar()
        self.custom_item_move_var = tk.StringVar()
        self.custom_item_consumable_var = tk.BooleanVar(value=True)
        self.custom_item_show_qty_var = tk.BooleanVar(value=True)
        self.custom_item_holdable_var = tk.StringVar(value="Holdable: Yes")
        self.custom_item_icon_source_var = tk.StringVar(value="Icon source: use current item icon (no import pending).")
        self.custom_item_icon_size_var = tk.StringVar()
        self._custom_item_effect_item_label_to_id: dict[str, str] = {}
        self._custom_item_effect_move_label_to_id: dict[str, str] = {}
        self._custom_item_effect_ability_label_to_id: dict[str, str] = {}
        self._custom_item_effect_item_id_to_label: dict[str, str] = {}
        self._custom_item_effect_move_id_to_label: dict[str, str] = {}
        self._custom_item_effect_ability_id_to_label: dict[str, str] = {}
        self._custom_pool_effect_label_to_id: dict[str, str] = {}
        self._custom_pool_effect_id_to_label: dict[str, str] = {}
        self._custom_pool_effect_defs_by_id: dict[str, dict[str, Any]] = {}
        self._custom_pool_effect_source_map: dict[str, tuple[str, str]] = {}
        self._custom_selected_pool_effect_params: dict[str, dict[str, Any]] = {}
        self._custom_effect_manifest_rows_by_id: dict[str, dict[str, Any]] = {}
        self._custom_effect_builder_label_to_id: dict[str, str] = {}
        self._custom_item_id_syncing = False
        self._custom_item_id_manual_override = False
        self._custom_last_generated_description = ""
        self._custom_desc_updating = False
        self._custom_effect_selection_syncing = False

        self._add_labeled_entry(right, "Item ID", self.custom_item_id_var, 0, 0, width=26)
        self.custom_item_id_var.trace_add("write", lambda *_args: self._custom_on_item_id_changed())
        self._add_labeled_entry(right, "Name", self.custom_item_name_var, 1, 0, width=26)
        self.custom_item_name_var.trace_add("write", lambda *_args: self._custom_on_item_name_changed())
        self._add_labeled_entry(right, "Name Plural", self.custom_item_name_plural_var, 2, 0, width=26)

        ttk.Label(right, text="Pocket").grid(row=0, column=2, sticky="w", padx=(8, 6), pady=4)
        self.custom_item_pocket_combo = ttk.Combobox(
            right,
            textvariable=self.custom_item_pocket_var,
            state="readonly",
            values=[f"{idx} - {name}" for idx, name in EN_POCKET_NAMES.items() if idx > 0],
            width=24,
        )
        self.custom_item_pocket_combo.grid(row=0, column=3, sticky="ew", pady=4)
        self.custom_item_pocket_combo.bind("<<ComboboxSelected>>", lambda _e: self._custom_update_holdable_hint(), add="+")

        self._add_labeled_entry(right, "Price", self.custom_item_price_var, 1, 2, width=24)
        self._add_labeled_entry(right, "Sell Price", self.custom_item_sell_price_var, 2, 2, width=24)
        self._add_labeled_entry(right, "BP Price", self.custom_item_bp_price_var, 3, 2, width=24)

        ttk.Label(right, text="Field Use").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=4)
        self.custom_item_field_use_combo = ttk.Combobox(
            right,
            textvariable=self.custom_item_field_use_var,
            state="readonly",
            values=["0 - None", "1 - OnPokemon", "2 - Direct", "3 - TM", "4 - HM", "5 - TR"],
            width=24,
        )
        self.custom_item_field_use_combo.grid(row=3, column=1, sticky="ew", pady=4)
        self.custom_item_field_use_combo.bind("<<ComboboxSelected>>", lambda _e: self._custom_update_holdable_hint(), add="+")

        ttk.Label(right, text="Battle Use").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=4)
        self.custom_item_battle_use_combo = ttk.Combobox(
            right,
            textvariable=self.custom_item_battle_use_var,
            state="readonly",
            values=["0 - None", "1 - OnPokemon", "2 - OnMove", "3 - OnBattler", "4 - OnFoe", "5 - Direct"],
            width=24,
        )
        self.custom_item_battle_use_combo.grid(row=4, column=1, sticky="ew", pady=4)

        self._add_labeled_entry(right, "Flags (csv)", self.custom_item_flags_var, 4, 2, width=24)
        self._add_labeled_entry(right, "Move ID (optional)", self.custom_item_move_var, 5, 0, width=24)

        ttk.Checkbutton(right, text="Consumable", variable=self.custom_item_consumable_var).grid(
            row=5, column=2, sticky="w", padx=(8, 0), pady=2
        )
        ttk.Checkbutton(right, text="Show Quantity", variable=self.custom_item_show_qty_var).grid(
            row=5, column=3, sticky="w", pady=2
        )
        ttk.Label(right, textvariable=self.custom_item_holdable_var, foreground="#555555").grid(
            row=6, column=0, columnspan=4, sticky="w", pady=(2, 4)
        )

        icon_row = ttk.Frame(right)
        icon_row.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        icon_row.columnconfigure(4, weight=1)
        ttk.Label(icon_row, text="Icon").grid(row=0, column=0, sticky="w", padx=(0, 6))
        icon_host = tk.Frame(icon_row, width=34, height=34, bg="#f6f6f6", relief="solid", bd=1)
        icon_host.grid(row=0, column=1, sticky="w")
        icon_host.grid_propagate(False)
        self.custom_item_icon_preview_label = tk.Label(icon_host, bg="#f6f6f6")
        self.custom_item_icon_preview_label.place(relx=0.5, rely=0.5, anchor="center")
        ttk.Button(icon_row, text="Choose Image...", command=self._custom_choose_icon_source).grid(
            row=0, column=2, sticky="w", padx=(8, 4)
        )
        ttk.Button(icon_row, text="Reset Import", command=self._custom_clear_icon_source).grid(
            row=0, column=3, sticky="w", padx=(2, 8)
        )
        ttk.Label(icon_row, textvariable=self.custom_item_icon_size_var, foreground="#555555").grid(
            row=0, column=4, sticky="w"
        )
        ttk.Label(icon_row, textvariable=self.custom_item_icon_source_var, foreground="#555555").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(4, 0)
        )

        ttk.Label(right, text="Description").grid(row=8, column=0, sticky="nw", padx=(0, 6), pady=4)
        desc_frame = ttk.Frame(right)
        desc_frame.grid(row=8, column=1, columnspan=3, sticky="nsew", pady=4)
        desc_frame.columnconfigure(0, weight=1)
        desc_frame.rowconfigure(0, weight=1)
        self.custom_item_desc_text = tk.Text(desc_frame, height=6, wrap="word")
        self.custom_item_desc_text.grid(row=0, column=0, sticky="nsew")
        desc_scroll = ttk.Scrollbar(desc_frame, orient="vertical", command=self.custom_item_desc_text.yview)
        desc_scroll.grid(row=0, column=1, sticky="ns")
        self.custom_item_desc_text.configure(yscrollcommand=desc_scroll.set)
        self.custom_item_desc_text.bind("<KeyRelease>", self._custom_on_description_text_changed, add="+")

        ttk.Separator(right, orient="horizontal").grid(row=9, column=0, columnspan=4, sticky="ew", pady=(8, 6))
        effects = ttk.LabelFrame(right, text="Effects", padding=6)
        effects.grid(row=10, column=0, columnspan=4, sticky="nsew", pady=(2, 4))
        effects.columnconfigure(0, weight=1)
        effects.columnconfigure(1, weight=1)
        effects.columnconfigure(2, weight=1)
        effects.rowconfigure(0, weight=1)

        self.custom_item_effect_items_combo_var = tk.StringVar()
        self.custom_item_effect_moves_combo_var = tk.StringVar()
        self.custom_item_effect_abilities_combo_var = tk.StringVar()

        self._build_custom_effect_picker_column(
            effects,
            column=0,
            title="Items effect",
            kind="item",
            combo_var=self.custom_item_effect_items_combo_var,
            combo_attr_name="custom_item_effect_items_combo",
            listbox_attr_name="custom_item_effect_items_listbox",
            pad_left=0,
        )
        self._build_custom_effect_picker_column(
            effects,
            column=1,
            title="Moves effect",
            kind="move",
            combo_var=self.custom_item_effect_moves_combo_var,
            combo_attr_name="custom_item_effect_moves_combo",
            listbox_attr_name="custom_item_effect_moves_listbox",
            pad_left=8,
        )
        self._build_custom_effect_picker_column(
            effects,
            column=2,
            title="Abilities effect",
            kind="ability",
            combo_var=self.custom_item_effect_abilities_combo_var,
            combo_attr_name="custom_item_effect_abilities_combo",
            listbox_attr_name="custom_item_effect_abilities_listbox",
            pad_left=8,
        )
        ttk.Label(
            effects,
            text="Legacy source picker. Source Item/Move/Ability is kept for compatibility; normalized pool effects below are hook-based.",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        pool_frame = ttk.LabelFrame(right, text="Hook-based Effect Library (normalized pool)", padding=6)
        pool_frame.grid(row=11, column=0, columnspan=4, sticky="nsew", pady=(4, 4))
        pool_frame.columnconfigure(1, weight=1)
        pool_frame.columnconfigure(3, weight=1)
        pool_frame.rowconfigure(1, weight=1)

        self.custom_pool_effect_filter_source_var = tk.StringVar(value="All")
        self.custom_pool_effect_filter_status_var = tk.StringVar(value="All")
        self.custom_pool_effect_filter_hook_var = tk.StringVar(value="All")
        self.custom_pool_effect_search_var = tk.StringVar()
        self.custom_pool_effect_combo_var = tk.StringVar()

        ttk.Label(pool_frame, text="Search").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.custom_pool_effect_search_entry = ttk.Entry(pool_frame, textvariable=self.custom_pool_effect_search_var, width=18)
        self.custom_pool_effect_search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Label(pool_frame, text="Source").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self.custom_pool_effect_source_combo = ttk.Combobox(
            pool_frame, textvariable=self.custom_pool_effect_filter_source_var, state="readonly", width=12,
            values=["All", "item", "move", "ability", "custom"],
        )
        self.custom_pool_effect_source_combo.grid(row=0, column=3, sticky="ew", padx=(0, 8))
        ttk.Label(pool_frame, text="Status").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.custom_pool_effect_status_combo = ttk.Combobox(
            pool_frame, textvariable=self.custom_pool_effect_filter_status_var, state="readonly", width=12,
            values=["All", "supported", "partial", "advanced", "unsupported"],
        )
        self.custom_pool_effect_status_combo.grid(row=0, column=5, sticky="ew", padx=(0, 8))
        ttk.Label(pool_frame, text="Hook").grid(row=0, column=6, sticky="w", padx=(0, 4))
        self.custom_pool_effect_hook_combo = ttk.Combobox(
            pool_frame, textvariable=self.custom_pool_effect_filter_hook_var, state="readonly", width=18, values=["All"],
        )
        self.custom_pool_effect_hook_combo.grid(row=0, column=7, sticky="ew")

        self.custom_pool_effect_combo = ttk.Combobox(pool_frame, textvariable=self.custom_pool_effect_combo_var, width=58)
        self.custom_pool_effect_combo.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        self._enable_combo_search(self.custom_pool_effect_combo)
        self._register_combo_tooltip_context(
            self.custom_pool_effect_combo,
            kind="custom_pool_effect",
            resolver=lambda raw: self._custom_pool_effect_label_to_id.get(
                str(raw or "").strip(),
                extract_internal_id(str(raw or "")).strip().upper(),
            ),
        )
        ttk.Button(pool_frame, text="Add Pool Effect", command=self._custom_add_pool_effect_from_combo).grid(
            row=1, column=5, sticky="ew", padx=(6, 0), pady=(6, 0)
        )
        self.custom_pool_effects_listbox = tk.Listbox(pool_frame, height=5, exportselection=False)
        self.custom_pool_effects_listbox.grid(row=2, column=0, columnspan=6, sticky="nsew", pady=(6, 0))
        pool_scroll = ttk.Scrollbar(pool_frame, orient="vertical", command=self.custom_pool_effects_listbox.yview)
        pool_scroll.grid(row=2, column=6, sticky="ns", pady=(6, 0))
        self.custom_pool_effects_listbox.configure(yscrollcommand=pool_scroll.set)
        pool_buttons = ttk.Frame(pool_frame)
        pool_buttons.grid(row=2, column=7, sticky="nsw", padx=(8, 0), pady=(6, 0))
        ttk.Button(pool_buttons, text="Custom Effects...", command=self.manage_custom_effects).pack(anchor="w")
        ttk.Button(pool_buttons, text="Configure", command=self._custom_configure_selected_pool_effect).pack(anchor="w")
        ttk.Button(pool_buttons, text="Reset Params", command=self._custom_reset_selected_pool_effect_params).pack(anchor="w", pady=(4, 0))
        ttk.Button(pool_buttons, text="Remove", command=self._custom_remove_selected_pool_effects).pack(anchor="w")
        ttk.Button(pool_buttons, text="Clear", command=self._custom_clear_pool_effects).pack(anchor="w", pady=(4, 0))
        self.custom_pool_effect_detail_var = tk.StringVar(value="Pool effects are compiled by hook/template/params. Advanced/unsupported effects are visible for planning but not auto-compiled.")
        ttk.Label(pool_frame, textvariable=self.custom_pool_effect_detail_var, foreground="#555555", wraplength=860).grid(
            row=3, column=0, columnspan=8, sticky="w", pady=(4, 0)
        )
        for widget in (
            self.custom_pool_effect_search_entry,
            self.custom_pool_effect_source_combo,
            self.custom_pool_effect_status_combo,
            self.custom_pool_effect_hook_combo,
        ):
            widget.bind("<KeyRelease>", self._custom_refresh_pool_effect_choices, add="+")
            widget.bind("<<ComboboxSelected>>", self._custom_refresh_pool_effect_choices, add="+")
        self.custom_pool_effect_combo.bind("<<ComboboxSelected>>", self._custom_on_pool_effect_combo_selected, add="+")
        self.custom_pool_effects_listbox.bind("<<ListboxSelect>>", self._custom_on_pool_effect_list_select, add="+")

        effect_actions = ttk.Frame(right)
        effect_actions.grid(row=12, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Button(
            effect_actions,
            text="Regenerate Description",
            command=lambda: self._custom_refresh_generated_description(force=True),
        ).pack(side="left", padx=(0, 4))
        ttk.Button(effect_actions, text="Clear Effect Selection", command=self._custom_clear_effect_selection).pack(
            side="left", padx=4
        )

        actions = ttk.Frame(right)
        actions.grid(row=13, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(actions, text="Apply Custom Item", command=self.custom_item_upsert).pack(side="left", padx=(0, 4))
        ttk.Button(actions, text="Delete Selected", command=self.custom_item_delete_selected).pack(side="left", padx=4)
        ttk.Button(actions, text="Rollback Custom Item", command=self.custom_item_rollback_last).pack(side="left", padx=4)
        ttk.Button(actions, text="Runtime Patch...", command=self.manage_custom_item_runtime_patch).pack(side="left", padx=4)

        self._bind_custom_item_mousewheel_recursive(workspace)
        self._custom_item_icon_target_size = self._custom_detect_item_icon_target_size()
        self._custom_reload_manifest()
        self._custom_refresh_pool_effect_choices()
        self._custom_update_holdable_hint()
        self._custom_update_icon_preview()
        self._on_custom_item_workspace_configure()

    def _build_legality_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="Legality")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Button(top, text="Run Legality Check", command=self.run_legality_check).pack(side="left")
        ttk.Label(
            top,
            text="Checks: unknown item/species/move/ability IDs + basic level/PP ranges",
        ).pack(side="left", padx=10)
        self.legal_output = tk.Text(tab, wrap="none", height=28)
        self.legal_output.pack(fill="both", expand=True, pady=(8, 0))

    def _build_dex_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.dex_tab = tab
        self.nb.add(tab, text="Dex")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        self.dex_category_var = tk.StringVar(value=DEX_CATEGORY_KEY_TO_LABEL.get("Species", "Pokédex"))
        self.dex_search_var = tk.StringVar()
        self.dex_form_var = tk.StringVar(value="0")
        self.dex_result_count_var = tk.StringVar(value="0 results")
        self.dex_title_var = tk.StringVar(value="Dex")
        self.dex_subtitle_var = tk.StringVar(value="Select a category and entry.")
        self._dex_pairs: list[tuple[str, str]] = []
        self._dex_visible_pairs: list[tuple[str, str]] = []

        controls = ttk.Frame(tab)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Category").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.dex_category_combo = ttk.Combobox(
            controls,
            textvariable=self.dex_category_var,
            width=16,
            state="readonly",
            values=DEX_CATEGORY_LABELS,
        )
        self.dex_category_combo.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.dex_category_combo.bind("<<ComboboxSelected>>", self._on_dex_category_changed)

        ttk.Label(controls, text="Search").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.dex_search_entry = ttk.Entry(controls, textvariable=self.dex_search_var)
        self.dex_search_entry.grid(row=0, column=3, sticky="ew", padx=(0, 12))
        self.dex_search_entry.bind("<KeyRelease>", self._on_dex_search_changed, add="+")
        self.dex_search_entry.bind("<FocusOut>", self._on_dex_search_changed, add="+")

        ttk.Label(controls, text="Form").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self.dex_form_entry = ttk.Entry(controls, textvariable=self.dex_form_var, width=5)
        self.dex_form_entry.grid(row=0, column=5, sticky="w", padx=(0, 8))
        self.dex_form_entry.bind("<FocusOut>", self._on_dex_form_changed, add="+")
        self.dex_form_entry.bind("<Return>", self._on_dex_form_changed, add="+")
        ttk.Label(controls, textvariable=self.dex_result_count_var).grid(row=0, column=6, sticky="e")

        shell = ttk.Panedwindow(tab, orient="horizontal")
        shell.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.dex_shell = shell

        left = ttk.Frame(shell, width=320)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.dex_filter_frame = left
        self.dex_result_list = tk.Listbox(left, exportselection=False)
        self.dex_result_list.grid(row=0, column=0, sticky="nsew")
        dex_list_scroll = ttk.Scrollbar(left, orient="vertical", command=self.dex_result_list.yview)
        dex_list_scroll.grid(row=0, column=1, sticky="ns")
        self.dex_result_list.configure(yscrollcommand=dex_list_scroll.set)
        self.dex_result_list.bind("<<ListboxSelect>>", self._on_dex_result_selected)
        shell.add(left, weight=2)

        right = ttk.Frame(shell)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.dex_result_frame = right
        header = ttk.Frame(right, padding=(10, 8), relief="groove")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self.dex_sprite_placeholder = tk.PhotoImage(width=96, height=96)
        self.dex_sprite_label = ttk.Label(header, image=self.dex_sprite_placeholder)
        self.dex_sprite_label.grid(row=0, column=0, rowspan=3, sticky="nw", padx=(0, 12))
        self.dex_sprite_label.image = self.dex_sprite_placeholder

        ttk.Label(header, textvariable=self.dex_title_var, font=("", 14, "bold")).grid(row=0, column=1, sticky="w")
        ttk.Label(header, textvariable=self.dex_subtitle_var, foreground="#4d4d4d").grid(row=1, column=1, sticky="w")
        self.dex_hero_frame = ttk.Frame(header)
        self.dex_hero_frame.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        self.dex_hero_frame.columnconfigure(1, weight=1)

        detail_shell = ttk.Frame(right)
        detail_shell.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        detail_shell.columnconfigure(0, weight=1)
        detail_shell.rowconfigure(0, weight=1)

        self.dex_detail_canvas = tk.Canvas(detail_shell, borderwidth=0, highlightthickness=0)
        self.dex_detail_canvas.grid(row=0, column=0, sticky="nsew")
        dex_detail_scroll = ttk.Scrollbar(detail_shell, orient="vertical", command=self.dex_detail_canvas.yview)
        dex_detail_scroll.grid(row=0, column=1, sticky="ns")
        self.dex_detail_canvas.configure(yscrollcommand=dex_detail_scroll.set)

        self.dex_detail_body = ttk.Frame(self.dex_detail_canvas)
        self._dex_detail_window = self.dex_detail_canvas.create_window((0, 0), window=self.dex_detail_body, anchor="nw")
        self.dex_detail_body.bind(
            "<Configure>",
            lambda _e: self.dex_detail_canvas.configure(scrollregion=self.dex_detail_canvas.bbox("all")),
        )
        self.dex_detail_canvas.bind(
            "<Configure>",
            lambda e: self.dex_detail_canvas.itemconfigure(self._dex_detail_window, width=e.width),
        )
        self.dex_detail_canvas.bind("<MouseWheel>", self._on_dex_detail_mousewheel, add="+")
        self.dex_detail_canvas.bind("<Button-4>", self._on_dex_detail_mousewheel, add="+")
        self.dex_detail_canvas.bind("<Button-5>", self._on_dex_detail_mousewheel, add="+")
        self.dex_detail_body.bind("<MouseWheel>", self._on_dex_detail_mousewheel, add="+")
        self.dex_detail_body.bind("<Button-4>", self._on_dex_detail_mousewheel, add="+")
        self.dex_detail_body.bind("<Button-5>", self._on_dex_detail_mousewheel, add="+")
        self._install_dex_global_mousewheel()

        shell.add(right, weight=5)
        shell.bind("<Configure>", self._on_dex_shell_configure, add="+")
        shell.bind("<B1-Motion>", self._on_dex_shell_drag, add="+")
        shell.bind("<ButtonRelease-1>", self._on_dex_shell_drag, add="+")
        tab.after(60, self._dex_init_split_limits)

        self._update_dex_query_values()
        self._on_dex_search_changed()

    def _on_dex_shell_configure(self, _event=None):
        if not hasattr(self, "dex_shell"):
            return
        if not self._dex_split_initialized:
            self._dex_split_initialized = True
            self.root.after_idle(self._dex_init_split_limits)
            return
        self.root.after_idle(self._dex_apply_split_constraints)

    def _on_dex_shell_drag(self, _event=None):
        if not hasattr(self, "dex_shell"):
            return
        self.root.after_idle(self._dex_apply_split_constraints)

    def _dex_init_split_limits(self):
        if not hasattr(self, "dex_shell") or not hasattr(self, "dex_filter_frame"):
            return
        shell = self.dex_shell
        try:
            shell.update_idletasks()
            current = int(shell.sashpos(0))
        except Exception:
            try:
                current = max(220, int(self.dex_filter_frame.winfo_width()))
            except Exception:
                current = 260
        min_left = max(160, min(280, int(current * 0.55)))
        self._dex_split_min_left_width = min_left
        self._dex_split_max_left_width = max(min_left, current)
        self._dex_apply_split_constraints()

    def _dex_apply_split_constraints(self):
        if not hasattr(self, "dex_shell"):
            return
        shell = self.dex_shell
        try:
            total_w = int(shell.winfo_width())
            if total_w <= 1:
                return
            min_left = max(120, int(self._dex_split_min_left_width or 180))
            max_left_cfg = int(self._dex_split_max_left_width or 0)
            if max_left_cfg <= 0:
                max_left_cfg = max(min_left, int(total_w * 0.33))
                self._dex_split_max_left_width = max_left_cfg

            # Keep result/details pane usable while allowing the filter pane to shrink.
            right_min = max(420, int(total_w * 0.48))
            dynamic_max = max(min_left, total_w - right_min)
            max_left = max(min_left, min(max_left_cfg, dynamic_max))

            current = int(shell.sashpos(0))
            desired = max(min_left, min(current, max_left))
            if desired != current:
                shell.sashpos(0, desired)
        except Exception:
            return

    def _dex_selected_category_key(self) -> str:
        label = (self.dex_category_var.get().strip() or DEX_CATEGORY_KEY_TO_LABEL.get("Species", "Pokédex"))
        return DEX_CATEGORY_LABEL_TO_KEY.get(label, "Species")

    @staticmethod
    def _dex_category_label_for_key(category_key: str) -> str:
        return DEX_CATEGORY_KEY_TO_LABEL.get(category_key, category_key)

    def _on_dex_category_changed(self, _event=None):
        self._hide_dex_tooltip()
        self.dex_search_var.set("")
        is_species = self._dex_selected_category_key() == "Species"
        self.dex_form_entry.configure(state="normal" if is_species else "disabled")
        self._update_dex_query_values()

    def _on_dex_form_changed(self, _event=None):
        if self._dex_selected_category_key() == "Species":
            self._on_dex_query_confirmed()

    def _on_dex_search_changed(self, _event=None):
        if not hasattr(self, "dex_result_list"):
            return
        query = self.dex_search_var.get().strip().casefold()
        previous_id = self._resolve_dex_entry_id()
        if query:
            pairs = [pair for pair in self._dex_pairs if query in f"{pair[0]} {pair[1]}".casefold()]
        else:
            pairs = list(self._dex_pairs)
        self._dex_visible_pairs = pairs
        self.dex_result_list.delete(0, tk.END)
        for label, _entry_id in pairs:
            self.dex_result_list.insert(tk.END, label)
        self.dex_result_count_var.set(f"{len(pairs)} results")

        if not pairs:
            self._on_dex_query_confirmed()
            return

        index = 0
        if previous_id:
            for i, (_label, entry_id) in enumerate(pairs):
                if entry_id == previous_id:
                    index = i
                    break
        try:
            self.dex_result_list.selection_clear(0, tk.END)
            self.dex_result_list.selection_set(index)
            self.dex_result_list.activate(index)
            self.dex_result_list.see(index)
        except tk.TclError:
            pass
        self._on_dex_query_confirmed()

    def _on_dex_result_selected(self, _event=None):
        self._on_dex_query_confirmed()

    def _on_dex_query_confirmed(self, _event=None):
        self._hide_dex_tooltip()
        if not hasattr(self, "dex_detail_body"):
            return
        if not self.catalogs:
            self._dex_render_payload(
                {
                    "title": "Dex",
                    "subtitle": "Catalog data is not loaded.",
                    "hero": [],
                    "sections": [
                        {
                            "kind": "text",
                            "title": "Status",
                            "text": "Catalog data is not loaded.",
                        }
                    ],
                }
            )
            return
        category_key = self._dex_selected_category_key()
        entry_id = self._resolve_dex_entry_id()
        if not entry_id:
            self._dex_render_payload(
                {
                    "title": "Dex",
                    "subtitle": "No matching entry selected.",
                    "hero": [],
                    "sections": [
                        {
                            "kind": "text",
                            "title": "Status",
                            "text": "No matching entry selected.",
                        }
                    ],
                }
            )
            return
        try:
            payload = self._dex_build_payload(category_key, entry_id)
        except Exception as exc:  # noqa: BLE001
            payload = {
                "title": "Dex",
                "subtitle": "Failed to render details.",
                "hero": [],
                "sections": [
                    {
                        "kind": "text",
                        "title": "Error",
                        "text": f"Failed to render Dex details:\n{exc}",
                    }
                ],
            }
        self._dex_render_payload(payload)

    def _update_dex_query_values(self):
        if not hasattr(self, "dex_result_list"):
            return
        if not self.catalogs:
            self._dex_pairs = []
            self._dex_visible_pairs = []
            self.dex_result_list.delete(0, tk.END)
            self.dex_result_count_var.set("0 results")
            return

        category = self._dex_selected_category_key()
        pairs: list[tuple[str, str]] = []
        if category == "Species":
            choices = self.catalogs.base_species_choices()
            for item in choices:
                sid = self.catalogs.canonical_species_id(item.internal_id) or item.internal_id
                label = self._dex_display_name_for_entry("Species", sid)
                if sid:
                    pairs.append((label, sid))
        elif category == "Moves":
            for mid in sorted(self.catalogs.moves_by_id.keys(), key=str.casefold):
                pairs.append((self._dex_display_name_for_entry("Moves", mid), mid))
        elif category == "Items":
            for iid in sorted(self.catalogs.items_by_id.keys(), key=str.casefold):
                pairs.append((self._dex_display_name_for_entry("Items", iid), iid))
        elif category == "Abilities":
            for aid in sorted(self.catalogs.abilities_by_id.keys(), key=str.casefold):
                pairs.append((self._dex_display_name_for_entry("Abilities", aid), aid))
        elif category == "Natures":
            for nature in sorted((str(n).strip().upper() for n in self.catalogs.natures), key=str.casefold):
                if nature:
                    pairs.append((self._dex_display_name_for_entry("Natures", nature), nature))
        elif category == "Types":
            for tid in sorted(self.catalogs.type_names_by_id.keys(), key=str.casefold):
                pairs.append((self._dex_display_name_for_entry("Types", tid), tid))
        pairs.sort(key=lambda row: row[0].casefold())
        self._dex_pairs = pairs
        self._on_dex_search_changed()

    def _resolve_dex_entry_id(self) -> str:
        if not hasattr(self, "dex_result_list"):
            return ""
        selection = self.dex_result_list.curselection()
        if not selection:
            return ""
        idx = int(selection[0])
        if idx < 0 or idx >= len(self._dex_visible_pairs):
            return ""
        _label, entry_id = self._dex_visible_pairs[idx]
        return entry_id

    def _dex_jump_to_species_entry(self, species_id: str, form: int = 0):
        if not self.catalogs or not hasattr(self, "dex_result_list"):
            return
        raw = str(species_id or "").strip().lstrip(":")
        if not raw:
            return
        canonical = self.catalogs.canonical_species_id(raw) or raw
        if not canonical:
            return

        current_category = self._dex_selected_category_key()
        current_entry = self._resolve_dex_entry_id()
        current_canonical = self.catalogs.canonical_species_id(current_entry) or str(current_entry or "").strip().lstrip(":")
        current_form = self._clamp_int(self.dex_form_var.get(), 0, 999, 0)
        target_form = self._clamp_int(str(form), 0, 999, 0)
        if (
            current_category == "Species"
            and current_canonical.upper() == canonical.upper()
            and current_form == target_form
        ):
            return

        self._hide_dex_tooltip()
        species_category_label = self._dex_category_label_for_key("Species")
        if self.dex_category_var.get().strip() != species_category_label:
            self.dex_category_var.set(species_category_label)
            self._on_dex_category_changed()
        else:
            self._update_dex_query_values()

        self.dex_form_var.set(str(target_form))
        self.dex_search_var.set("")
        self._on_dex_search_changed()

        target_idx = -1
        for idx, (_label, entry_id) in enumerate(self._dex_visible_pairs):
            sid = self.catalogs.canonical_species_id(entry_id) or str(entry_id or "").strip().lstrip(":")
            if sid.upper() == canonical.upper():
                target_idx = idx
                break

        if target_idx >= 0:
            try:
                self.dex_result_list.selection_clear(0, tk.END)
                self.dex_result_list.selection_set(target_idx)
                self.dex_result_list.activate(target_idx)
                self.dex_result_list.see(target_idx)
            except tk.TclError:
                pass

        self._on_dex_query_confirmed()

    def _dex_display_name_for_entry(self, category_key: str, entry_id: str) -> str:
        key = str(category_key or "").strip()
        if not self.catalogs:
            if key == "Species":
                return self._english_species_name_for_id(entry_id)
            if key == "Moves":
                return self._english_move_name_for_id(entry_id)
            if key == "Items":
                return self._english_item_name_for_id(entry_id)
            if key == "Abilities":
                return self._english_ability_name_for_id(entry_id)
            if key == "Types":
                return self._type_display_name_for_id(entry_id)
            if key == "Natures":
                return self._title_case_words(entry_id)
            return self._prettify_internal_id(entry_id)
        eid = str(entry_id or "").strip().lstrip(":")
        if key == "Species":
            canonical = self.catalogs.canonical_species_id(eid) or eid
            return self._english_species_name_for_id(canonical)
        if key == "Moves":
            canonical = self.catalogs.canonical_move_id(eid) or eid
            return self._move_display_name_for_id(canonical)
        if key == "Items":
            canonical = self.catalogs.canonical_item_id(eid) or eid
            return self._dex_item_display_name(canonical)
        if key == "Abilities":
            canonical = self.catalogs.canonical_ability_id(eid) or eid
            return self._english_ability_name_for_id(canonical)
        if key == "Natures":
            return self._title_case_words(eid)
        if key == "Types":
            return self._type_display_name_for_id(eid)
        return self._prettify_internal_id(eid)

    def _dex_item_display_name(self, item_id: str) -> str:
        raw = str(item_id or "").strip().lstrip(":")
        if not raw:
            return ""
        canonical = self.catalogs.canonical_item_id(raw) if self.catalogs else raw
        canonical = canonical or raw
        m = re.match(r"^(TM|HM)(\d+)$", canonical, flags=re.IGNORECASE)
        if not m or not self.catalogs:
            return self._english_item_name_for_id(canonical)
        label = self._tm_hm_display_label(canonical, pocket_index=4)
        if label and label.upper() != canonical.upper():
            return label
        return self._english_item_name_for_id(canonical)

    @staticmethod
    def _dex_tm_sort_key(item_id: str) -> tuple[int, int, str]:
        raw = str(item_id or "").strip().upper()
        m = re.match(r"^(TM|HM)(\d+)$", raw)
        if not m:
            return (2, 9999, raw)
        bucket = 0 if m.group(1) == "TM" else 1
        try:
            num = int(m.group(2))
        except ValueError:
            num = 9999
        return (bucket, num, raw)

    def _dex_move_tm_labels(self, move_id: str) -> list[str]:
        if not self.catalogs:
            return []
        canonical_move = self.catalogs.canonical_move_id(move_id) or str(move_id or "").strip().lstrip(":")
        if not canonical_move:
            return []
        if self._dex_move_tm_map is None:
            move_tm_map: dict[str, list[str]] = {}
            for iid, item in self.catalogs.items_by_id.items():
                m = re.match(r"^(TM|HM)(\d+)$", iid, flags=re.IGNORECASE)
                if not m:
                    continue
                move_raw = str(item.extra.get("Move", "")).strip().lstrip(":")
                if not move_raw:
                    continue
                mid = self.catalogs.canonical_move_id(move_raw) or move_raw
                if not mid:
                    continue
                move_tm_map.setdefault(mid, []).append(iid.upper())
            for mid in list(move_tm_map.keys()):
                uniq = sorted(set(move_tm_map[mid]), key=self._dex_tm_sort_key)
                move_tm_map[mid] = uniq
            self._dex_move_tm_map = move_tm_map
        return list(self._dex_move_tm_map.get(canonical_move, []))

    @staticmethod
    def _dex_entity_cell(raw: Any) -> tuple[str, str, str] | None:
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("kind", "")).strip().casefold()
        entry_id = str(raw.get("id", "")).strip().lstrip(":")
        label = str(raw.get("label", "")).strip()
        if kind not in {"move", "ability"} or not entry_id:
            return None
        if not label:
            label = entry_id
        return kind, entry_id, label

    def _dex_tooltip_enabled(self) -> bool:
        return self._dex_selected_category_key() == "Species"

    def _hide_dex_tooltip(self):
        tip = self._dex_tooltip_window
        if tip is None:
            return
        try:
            tip.withdraw()
        except Exception:
            pass

    def _show_dex_tooltip(self, text: str, x_root: int, y_root: int):
        content = str(text or "").strip()
        if not content:
            self._hide_dex_tooltip()
            return
        tip = self._dex_tooltip_window
        if tip is None or not tip.winfo_exists():
            tip = tk.Toplevel(self.root)
            tip.wm_overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
            label = tk.Label(
                tip,
                text=content,
                justify="left",
                anchor="nw",
                bg="#fffde8",
                fg="#1f1f1f",
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("", 9),
                wraplength=520,
            )
            label.pack(fill="both", expand=True)
            self._dex_tooltip_window = tip
            self._dex_tooltip_label = label
        else:
            label = self._dex_tooltip_label
            if label is None or not label.winfo_exists():
                self._dex_tooltip_window = None
                self._dex_tooltip_label = None
                self._show_dex_tooltip(content, x_root, y_root)
                return
            try:
                if str(label.cget("text")) != content:
                    label.configure(text=content)
            except Exception:
                label.configure(text=content)
        # Position tooltip with its top-left at the mouse tail.
        try:
            tip.wm_geometry(f"+{int(x_root) + 12}+{int(y_root) + 14}")
            tip.deiconify()
            tip.lift()
        except Exception:
            pass

    def _hide_party_tooltip(self):
        tip = self._party_tooltip_window
        if tip is None:
            return
        try:
            tip.withdraw()
        except Exception:
            pass

    def _show_party_tooltip(self, text: str, event: Any = None, widget: Any = None):
        if widget is not None:
            try:
                if isinstance(widget, ttk.Combobox) and self._combo_uses_searchable_tooltip_picker(widget):
                    self._hide_party_tooltip()
                    return
            except Exception:
                pass
        content = str(text or "").strip()
        if not content:
            self._hide_party_tooltip()
            return
        tip = self._party_tooltip_window
        if tip is None or not tip.winfo_exists():
            tip = tk.Toplevel(self.root)
            tip.wm_overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
            label = tk.Label(
                tip,
                text=content,
                justify="left",
                anchor="nw",
                bg="#fffde8",
                fg="#1f1f1f",
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("", 9),
                wraplength=560,
            )
            label.pack(fill="both", expand=True)
            self._party_tooltip_window = tip
            self._party_tooltip_label = label
        else:
            label = self._party_tooltip_label
            if label is None or not label.winfo_exists():
                self._party_tooltip_window = None
                self._party_tooltip_label = None
                self._show_party_tooltip(content, event=event, widget=widget)
                return
            label.configure(text=content)
        try:
            if event is not None and hasattr(event, "x_root") and hasattr(event, "y_root"):
                x_root = int(getattr(event, "x_root"))
                y_root = int(getattr(event, "y_root"))
                if x_root <= 0 and y_root <= 0 and widget is not None:
                    x_root = int(widget.winfo_rootx()) + 8
                    y_root = int(widget.winfo_rooty()) + int(widget.winfo_height()) + 6
            elif widget is not None:
                x_root = int(widget.winfo_rootx()) + 8
                y_root = int(widget.winfo_rooty()) + int(widget.winfo_height()) + 6
            else:
                x_root = int(self.root.winfo_pointerx())
                y_root = int(self.root.winfo_pointery())
            # Top-left of tooltip starts at cursor tail.
            tip.wm_geometry(f"+{x_root + 12}+{y_root + 14}")
            tip.deiconify()
            tip.lift()
        except Exception:
            pass

    def _dex_move_tooltip_text(self, move_id: str) -> str:
        if not self.catalogs:
            return ""
        canonical = self.catalogs.canonical_move_id(move_id) or str(move_id or "").strip().lstrip(":")
        if not canonical:
            return ""
        cached = self._dex_tooltip_move_cache.get(canonical)
        if cached is not None:
            return cached
        raw_desc = self.catalogs.move_description(canonical)
        summary = self._move_numeric_summary_lines(canonical, raw_desc, "")
        summary = [
            line
            for line in summary
            if not line.startswith("Internal function code:")
            and not line.startswith("Numeric values detected in description text:")
        ]
        base_desc, summary = self._resolve_entity_description("move", canonical, raw_desc, summary)
        if summary:
            if base_desc:
                text = f"{base_desc}\n\n" + "\n".join(f"- {line}" for line in summary)
            else:
                text = "\n".join(f"- {line}" for line in summary)
        else:
            text = base_desc
        text = text.strip()
        self._dex_tooltip_move_cache[canonical] = text
        return text

    def _dex_ability_tooltip_text(self, ability_id: str) -> str:
        if not self.catalogs:
            return ""
        canonical = self.catalogs.canonical_ability_id(ability_id) or str(ability_id or "").strip().lstrip(":")
        if not canonical:
            return ""
        cached = self._dex_tooltip_ability_cache.get(canonical)
        if cached is not None:
            return cached
        raw_desc = self.catalogs.ability_description(canonical)
        summary = self._ability_numeric_summary_lines(canonical, raw_desc, "")
        summary = [
            line
            for line in summary
            if not line.startswith("Numeric values detected in description text:")
        ]
        base_desc, summary = self._resolve_entity_description("ability", canonical, raw_desc, summary)
        if summary:
            if base_desc:
                text = f"{base_desc}\n\n" + "\n".join(f"- {line}" for line in summary)
            else:
                text = "\n".join(f"- {line}" for line in summary)
        else:
            text = base_desc
        text = text.strip()
        self._dex_tooltip_ability_cache[canonical] = text
        return text

    def _dex_entity_tooltip_text(self, kind: str, entry_id: str) -> str:
        if kind == "move":
            return self._dex_move_tooltip_text(entry_id)
        if kind == "ability":
            return self._dex_ability_tooltip_text(entry_id)
        return ""

    def _bind_dex_entity_tooltip(self, widget, kind: str, entry_id: str):
        state: dict[str, Any] = {"text": None, "last_motion_ts": 0.0}

        def resolve_text() -> str:
            cached = state.get("text")
            if isinstance(cached, str):
                return cached
            text = self._dex_entity_tooltip_text(kind, entry_id)
            state["text"] = text
            return text

        def on_hover(event):
            if not self._dex_tooltip_enabled():
                self._hide_dex_tooltip()
                return
            text = resolve_text()
            if not text:
                self._hide_dex_tooltip()
                return
            self._show_dex_tooltip(text, event.x_root, event.y_root)

        def on_motion(event):
            if not self._dex_tooltip_enabled():
                self._hide_dex_tooltip()
                return
            now = time.monotonic()
            if (now - float(state.get("last_motion_ts", 0.0))) < 0.03:
                return
            state["last_motion_ts"] = now
            text = resolve_text()
            if not text:
                self._hide_dex_tooltip()
                return
            self._show_dex_tooltip(text, event.x_root, event.y_root)

        widget.bind("<Enter>", on_hover, add="+")
        widget.bind("<Motion>", on_motion, add="+")
        widget.bind("<Leave>", lambda _e: self._hide_dex_tooltip(), add="+")
        widget.bind("<ButtonPress>", lambda _e: self._hide_dex_tooltip(), add="+")

    def _dex_move_detail_cells(self, move_id: str) -> tuple[str, str, str, str, str]:
        if not self.catalogs:
            mid = str(move_id or "").strip().lstrip(":")
            return (self._english_move_name_for_id(mid), "-", "-", "-", "-")
        mid = self.catalogs.canonical_move_id(move_id) or str(move_id or "").strip().lstrip(":")
        move_name = self._dex_display_name_for_entry("Moves", mid)
        move = self.catalogs.moves_by_id.get(mid)
        if not move:
            return (move_name, "-", "-", "-", "-")
        move_type = self._type_display_name_for_id(str(move.extra.get("Type", "")).strip().lstrip(":")) or "-"
        category_raw = str(move.extra.get("Category", "")).strip().lstrip(":")
        category = self._prettify_internal_id(category_raw) if category_raw else "-"
        power = str(move.extra.get("Power", "")).strip() or "-"
        acc = str(move.extra.get("Accuracy", "")).strip() or "-"
        return (move_name, move_type, category, power, acc)

    def _dex_move_rows_for_ids(self, move_ids: list[str]) -> list[tuple[Any, Any, Any, Any, Any]]:
        rows: list[tuple[Any, Any, Any, Any, Any]] = []
        seen: set[str] = set()
        for raw in move_ids:
            mid = (self.catalogs.canonical_move_id(raw) if self.catalogs else raw) or str(raw or "").strip().lstrip(":")
            if not mid or mid in seen:
                continue
            move_name, move_type, category, power, acc = self._dex_move_detail_cells(mid)
            rows.append(({"kind": "move", "id": mid, "label": move_name}, move_type, category, power, acc))
            seen.add(mid)
        rows.sort(key=lambda row: self._value_to_text(row[0]).casefold())
        return rows

    def _dex_tm_rows_for_species(self, valid_moves: list[str]) -> list[tuple[Any, Any, Any, Any, Any, Any]]:
        if not self.catalogs:
            return []
        valid_set = {
            (self.catalogs.canonical_move_id(mid) or str(mid or "").strip().lstrip(":"))
            for mid in valid_moves
            if str(mid or "").strip()
        }
        rows: list[tuple[Any, Any, Any, Any, Any, Any]] = []
        for iid, item in self.catalogs.items_by_id.items():
            m = re.match(r"^(TM|HM)(\d+)$", iid, flags=re.IGNORECASE)
            if not m:
                continue
            move_raw = str(item.extra.get("Move", "")).strip().lstrip(":")
            if not move_raw:
                continue
            move_id = self.catalogs.canonical_move_id(move_raw) or move_raw
            if move_id not in valid_set:
                continue
            move_name, move_type, category, power, acc = self._dex_move_detail_cells(move_id)
            rows.append((iid.upper(), {"kind": "move", "id": move_id, "label": move_name}, move_type, category, power, acc))
        rows.sort(key=lambda row: self._dex_tm_sort_key(row[0]))
        return rows

    @staticmethod
    def _dex_join_list(values: list[str], limit: int = 40) -> str:
        if not values:
            return "(none)"
        if len(values) <= limit:
            return ", ".join(values)
        extra = len(values) - limit
        return f"{', '.join(values[:limit])}, ... (+{extra} more)"

    def _dex_build_payload(self, category: str, entry_id: str) -> dict[str, Any]:
        raw_category = str(category or "").strip() or "Species"
        category_key = DEX_CATEGORY_LABEL_TO_KEY.get(raw_category, raw_category)
        if category_key == "Species":
            return self._dex_species_payload(entry_id)
        if category_key == "Moves":
            return self._dex_move_payload(entry_id)
        if category_key == "Items":
            return self._dex_item_payload(entry_id)
        if category_key == "Abilities":
            return self._dex_ability_payload(entry_id)
        if category_key == "Natures":
            return self._dex_nature_payload(entry_id)
        if category_key == "Types":
            return self._dex_type_payload(entry_id)
        return {
            "title": "Dex",
            "subtitle": "Unknown category.",
            "hero": [],
            "sections": [{"kind": "text", "title": "Status", "text": "Unknown category."}],
        }

    def _dex_render_payload(self, payload: dict[str, Any]):
        title = str(payload.get("title", "Dex"))
        subtitle = str(payload.get("subtitle", ""))
        hero = payload.get("hero", [])
        sections = payload.get("sections", [])
        sprite_spec = payload.get("image")

        # Backward compatibility for previous payload shape.
        if not sections:
            overview = payload.get("overview", [])
            rows = payload.get("rows", [])
            notes = str(payload.get("notes", "")).strip()
            sections = []
            if overview:
                sections.append({"kind": "kv", "title": "Overview", "rows": overview})
            if rows:
                sections.append(
                    {
                        "kind": "table",
                        "title": "Details",
                        "columns": ["Section", "Entry"],
                        "rows": rows,
                    }
                )
            if notes:
                sections.append({"kind": "text", "title": "Description", "text": notes})
            if not sections:
                sections = [{"kind": "text", "title": "Status", "text": "No details available."}]

        self.dex_title_var.set(title)
        self.dex_subtitle_var.set(subtitle)
        self._dex_set_sprite_preview(sprite_spec)

        for child in self.dex_hero_frame.winfo_children():
            child.destroy()
        for row_idx, row in enumerate(hero):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            key = str(row[0])
            value = row[1]
            ttk.Label(self.dex_hero_frame, text=f"{key}:", font=("", 9, "bold")).grid(
                row=row_idx, column=0, sticky="nw", padx=(0, 6), pady=1
            )
            self._render_value_or_type_chips(
                self.dex_hero_frame,
                key,
                value,
                row=row_idx,
                column=1,
                wraplength=740,
                short=False,
                max_per_row=3,
            )

        self._dex_clear_detail_sections()
        for section in sections:
            if not isinstance(section, dict):
                continue
            kind = str(section.get("kind", "text")).strip().lower()
            title_text = str(section.get("title", "Section"))
            if kind == "kv":
                self._dex_add_kv_section(title_text, section.get("rows", []))
            elif kind == "table":
                self._dex_add_table_section(
                    title_text,
                    section.get("columns", []),
                    section.get("rows", []),
                    section.get("height"),
                )
            elif kind == "evolution_chart":
                self._dex_add_evolution_chart_section(
                    title_text,
                    str(section.get("species_id", "")).strip(),
                    self._clamp_int(str(section.get("form", 0)), 0, 999, 0),
                    section.get("height"),
                    bool(section.get("show_all_conditions", False)),
                )
            elif kind == "stats":
                self._dex_add_stats_section(title_text, section.get("rows", []))
            elif kind == "moves_grid":
                self._dex_add_moves_grid_section(title_text, section.get("blocks", []))
            elif kind == "type_matchups":
                self._dex_add_type_matchups_section(
                    title_text,
                    section.get("defenses", []),
                    section.get("attacks", []),
                    str(section.get("defense_title", "Type Defenses")),
                    str(section.get("attack_title", "Type Attacks")),
                )
            else:
                text = str(section.get("text", "")).strip() or "No details available."
                self._dex_add_text_section(title_text, text)

        try:
            self.dex_detail_body.update_idletasks()
            self.dex_detail_canvas.configure(scrollregion=self.dex_detail_canvas.bbox("all"))
            self.dex_detail_canvas.yview_moveto(0.0)
        except Exception:
            pass
        self._dex_bind_mousewheel_recursive(self.dex_detail_body)

    def _install_dex_global_mousewheel(self):
        if self._dex_global_wheel_enabled:
            return
        try:
            self.root.bind_all("<MouseWheel>", self._on_dex_global_mousewheel, add="+")
            self.root.bind_all("<Button-4>", self._on_dex_global_mousewheel, add="+")
            self.root.bind_all("<Button-5>", self._on_dex_global_mousewheel, add="+")
            self._dex_global_wheel_enabled = True
        except Exception:
            self._dex_global_wheel_enabled = False

    def _on_dex_global_mousewheel(self, event):
        if not hasattr(self, "dex_detail_canvas") or not hasattr(self, "nb") or not hasattr(self, "dex_tab"):
            return
        try:
            if str(self.nb.select()) != str(self.dex_tab):
                return
        except Exception:
            return
        canvas = self.dex_detail_canvas
        target = getattr(event, "widget", None)
        if not self._is_widget_descendant(target, canvas):
            try:
                hovered = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
            except Exception:
                hovered = None
            if not self._is_widget_descendant(hovered, canvas):
                return
        return self._queue_dex_canvas_scroll(canvas, event)

    def _queue_dex_canvas_scroll(self, canvas: tk.Canvas, event):
        if canvas is None:
            return
        try:
            x0, y0, x1, y1 = [int(float(v)) for v in str(canvas.cget("scrollregion")).split()]
        except Exception:
            return
        if (y1 - y0) <= canvas.winfo_height():
            return
        steps = self._mousewheel_steps(event)
        if steps == 0:
            return "break"
        self._dex_wheel_canvas = canvas
        self._dex_wheel_accum_steps += steps
        if self._dex_wheel_flush_job is None:
            try:
                self._dex_wheel_flush_job = self.root.after(16, self._flush_dex_canvas_scroll)
            except Exception:
                self._dex_wheel_flush_job = None
                pending = self._dex_wheel_accum_steps
                self._dex_wheel_accum_steps = 0
                try:
                    canvas.yview_scroll(pending, "units")
                except Exception:
                    pass
        return "break"

    def _flush_dex_canvas_scroll(self):
        self._dex_wheel_flush_job = None
        canvas = self._dex_wheel_canvas
        steps = int(self._dex_wheel_accum_steps)
        self._dex_wheel_accum_steps = 0
        if canvas is None or steps == 0:
            return
        try:
            x0, y0, x1, y1 = [int(float(v)) for v in str(canvas.cget("scrollregion")).split()]
        except Exception:
            return
        if (y1 - y0) <= canvas.winfo_height():
            return
        try:
            canvas.yview_scroll(steps, "units")
        except Exception:
            pass

    def _dex_bind_mousewheel_recursive(self, widget):
        if self._dex_global_wheel_enabled:
            return
        if widget is None:
            return
        key = str(widget)
        if key not in self._dex_wheel_bound_widgets:
            try:
                widget.bind("<MouseWheel>", self._on_dex_detail_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_dex_detail_mousewheel, add="+")
                widget.bind("<Button-5>", self._on_dex_detail_mousewheel, add="+")
                self._dex_wheel_bound_widgets.add(key)
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._dex_bind_mousewheel_recursive(child)

    @staticmethod
    def _is_widget_descendant(widget, parent) -> bool:
        if widget is None or parent is None:
            return False
        wname = str(widget)
        pname = str(parent)
        return wname == pname or wname.startswith(f"{pname}.")

    def _on_dex_detail_mousewheel(self, event):
        if not hasattr(self, "dex_detail_canvas"):
            return
        canvas = self.dex_detail_canvas
        target = getattr(event, "widget", None)
        if not self._is_widget_descendant(target, canvas):
            try:
                hovered = self.root.winfo_containing(self.root.winfo_pointerx(), self.root.winfo_pointery())
            except Exception:
                hovered = None
            if not self._is_widget_descendant(hovered, canvas):
                return
        return self._queue_dex_canvas_scroll(canvas, event)

    def _dex_set_sprite_preview(self, sprite_spec: Any):
        if not hasattr(self, "dex_sprite_label"):
            return
        img = self.dex_sprite_placeholder
        if isinstance(sprite_spec, dict):
            species_id = str(sprite_spec.get("species_id", "")).strip()
            item_id = str(sprite_spec.get("item_id", "")).strip()
            form = self._clamp_int(str(sprite_spec.get("form", 0)), 0, 999, 0)
            shiny = bool(sprite_spec.get("shiny", False))
            if species_id:
                img2 = self._get_party_preview_icon_image(species_id, form=form, shiny=shiny)
                if img2 is not None:
                    img = img2
            elif item_id:
                img2 = self._get_item_icon_image(item_id)
                if img2 is not None:
                    try:
                        img = img2.zoom(2, 2) if img2.width() <= 32 else img2
                    except Exception:
                        img = img2
        self.dex_sprite_label.configure(image=img)
        self.dex_sprite_label.image = img

    def _dex_clear_detail_sections(self):
        self._hide_dex_tooltip()
        for frame in self._dex_detail_sections:
            try:
                frame.destroy()
            except Exception:
                pass
        self._dex_detail_sections = []

    def _dex_add_text_section(self, title: str, text: str):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="x", expand=False, pady=(0, 8))
        is_description = str(title or "").strip().casefold() == "description"
        lbl_font = ("", 9, "bold") if is_description else None
        ttk.Label(frame, text=text, justify="left", wraplength=860, font=lbl_font).pack(anchor="w")
        self._dex_detail_sections.append(frame)

    def _dex_add_kv_section(self, title: str, rows: Any):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="x", expand=False, pady=(0, 8))
        frame.columnconfigure(1, weight=1)
        row_items = rows if isinstance(rows, list) else []
        if not row_items:
            ttk.Label(frame, text="(none)").grid(row=0, column=0, sticky="w")
            self._dex_detail_sections.append(frame)
            return
        for idx, row in enumerate(row_items):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            key = str(row[0]).strip()
            value = row[1]
            ttk.Label(frame, text=f"{key}:", font=("", 9, "bold")).grid(
                row=idx, column=0, sticky="nw", padx=(0, 8), pady=1
            )
            value_list = value if isinstance(value, list) else []
            ability_entities = [
                self._dex_entity_cell(entry)
                for entry in value_list
                if isinstance(entry, dict)
            ]
            ability_entities = [entry for entry in ability_entities if entry is not None and entry[0] == "ability"]
            if key.casefold() == "abilities" and ability_entities:
                holder = ttk.Frame(frame)
                holder.grid(row=idx, column=1, sticky="nw", pady=1)
                row_cursor = 0
                col_cursor = 0
                for kind, entry_id, label in ability_entities:
                    chip = tk.Label(
                        holder,
                        text=label,
                        bg="#f0f2f5",
                        fg="#1f1f1f",
                        padx=6,
                        pady=2,
                        bd=1,
                        relief="solid",
                        font=("", 8, "bold"),
                    )
                    chip.grid(row=row_cursor, column=col_cursor, sticky="w", padx=2, pady=1)
                    self._bind_dex_entity_tooltip(chip, kind, entry_id)
                    col_cursor += 1
                    if col_cursor >= 3:
                        col_cursor = 0
                        row_cursor += 1
                continue
            self._render_value_or_type_chips(
                frame,
                key,
                value,
                row=idx,
                column=1,
                wraplength=820,
                short=False,
                max_per_row=4,
            )
        self._dex_detail_sections.append(frame)

    def _dex_add_table_section(self, title: str, columns: Any, rows: Any, height_hint: Any = None):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="both", expand=False, pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        col_list = [str(c) for c in columns if str(c).strip()] if isinstance(columns, list) else []
        if not col_list:
            col_list = ["Value"]

        row_list = rows if isinstance(rows, list) else []
        try:
            hinted = int(height_hint)
        except (TypeError, ValueError):
            hinted = 0
        if hinted <= 0:
            hinted = max(1, min(7, len(row_list) if row_list else 1))

        type_cols = [idx for idx, label in enumerate(col_list) if self._is_type_field_label(label)]
        if type_cols:
            self._dex_add_type_aware_table_content(frame, col_list, row_list, hinted, type_cols)
            self._dex_detail_sections.append(frame)
            return

        tree = ttk.Treeview(
            frame,
            columns=tuple(f"c{i}" for i in range(len(col_list))),
            show="headings",
            height=hinted,
        )
        for idx, label in enumerate(col_list):
            cid = f"c{idx}"
            tree.heading(cid, text=label)
            stretch = idx == len(col_list) - 1
            width = 110 if len(col_list) > 1 else 320
            tree.column(cid, anchor="w", width=width, stretch=stretch)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)

        if not row_list:
            tree.insert("", "end", values=("(none)",) + tuple("" for _ in range(len(col_list) - 1)))
        else:
            for row in row_list:
                if isinstance(row, (list, tuple)):
                    values = [str(v) for v in row[: len(col_list)]]
                else:
                    values = [str(row)]
                while len(values) < len(col_list):
                    values.append("")
                tree.insert("", "end", values=tuple(values))
        self._dex_detail_sections.append(frame)

    def _dex_add_type_aware_table_content(
        self,
        frame: ttk.LabelFrame,
        col_list: list[str],
        row_list: list[Any],
        hinted: int,
        type_cols: list[int],
    ):
        shell = ttk.Frame(frame)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew")
        for idx, label in enumerate(col_list):
            header.columnconfigure(idx, weight=1 if idx == len(col_list) - 1 else 0)
            ttk.Label(header, text=label, font=("", 9, "bold")).grid(
                row=0, column=idx, sticky="w", padx=(2, 8), pady=(0, 4)
            )

        body_canvas_h = max(68, min(420, (max(1, hinted) * 30) + 8))
        canvas = tk.Canvas(shell, height=body_canvas_h, borderwidth=0, highlightthickness=0)
        canvas.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)

        body = ttk.Frame(canvas)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_window, width=e.width), add="+")
        self._dex_bind_mousewheel_recursive(body)

        if not row_list:
            row_list = [("(none)",) + tuple("" for _ in range(max(0, len(col_list) - 1)))]

        for ridx, row in enumerate(row_list):
            if isinstance(row, (list, tuple)):
                values: list[Any] = list(row[: len(col_list)])
            else:
                values = [row]
            while len(values) < len(col_list):
                values.append("")

            for cidx, raw in enumerate(values):
                body.columnconfigure(cidx, weight=1 if cidx == len(col_list) - 1 else 0)
                cell = ttk.Frame(body)
                cell.grid(row=ridx, column=cidx, sticky="nw", padx=(2, 8), pady=1)
                if cidx in type_cols:
                    type_ids = self._extract_type_ids(raw)
                    if type_ids:
                        self._render_type_chip_row(
                            cell,
                            type_ids,
                            short=False,
                            empty_text="-",
                            max_per_row=3,
                            clear_existing=False,
                        )
                    else:
                        ttk.Label(cell, text=self._value_to_text(raw).strip() or "-", justify="left").pack(anchor="w")
                else:
                    ttk.Label(
                        cell,
                        text=self._value_to_text(raw).strip(),
                        justify="left",
                        wraplength=360,
                    ).pack(anchor="w")

    @staticmethod
    def _dex_table_column_layout(col_list: list[str]) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for idx, raw_label in enumerate(col_list):
            label = re.sub(r"[^a-z0-9]+", " ", str(raw_label or "").casefold()).strip()
            if label in {"lv", "lvl", "level", "tm", "hm", "tm no", "hm no"}:
                out.append((0, 58))
            elif label in {"move", "name"}:
                out.append((3, 180))
            elif label in {"type"}:
                out.append((1, 92))
            elif label in {"cat", "category"}:
                out.append((0, 72))
            elif label in {"power", "acc", "accuracy", "pp", "rate", "levels"}:
                out.append((0, 66))
            elif label in {"map", "method", "location"}:
                out.append((2, 140))
            else:
                out.append((1 if idx == len(col_list) - 1 else 0, 110))
        if out and not any(weight > 0 for weight, _min_w in out):
            weight, min_w = out[-1]
            out[-1] = (max(1, weight), min_w)
        return out

    def _dex_add_inline_table_content(self, frame: ttk.Frame, col_list: list[str], row_list: list[Any]):
        table = ttk.Frame(frame)
        table.grid(row=0, column=0, sticky="ew")
        specs = self._dex_table_column_layout(col_list)
        for idx, (weight, min_w) in enumerate(specs):
            table.columnconfigure(idx, weight=weight, minsize=min_w)

        for cidx, label in enumerate(col_list):
            ttk.Label(table, text=str(label), font=("", 9, "bold")).grid(
                row=0, column=cidx, sticky="w", padx=(2, 8), pady=(0, 4)
            )
        ttk.Separator(table, orient="horizontal").grid(
            row=1, column=0, columnspan=max(1, len(col_list)), sticky="ew", pady=(0, 4)
        )

        norm_rows = row_list if row_list else [("(none)",) + tuple("" for _ in range(max(0, len(col_list) - 1)))]
        for ridx, row in enumerate(norm_rows, start=2):
            if isinstance(row, (list, tuple)):
                values = list(row[: len(col_list)])
            else:
                values = [row]
            while len(values) < len(col_list):
                values.append("")
            for cidx, raw in enumerate(values):
                cell = ttk.Frame(table)
                cell.grid(row=ridx, column=cidx, sticky="nw", padx=(2, 8), pady=1)
                entity = self._dex_entity_cell(raw)
                if entity is not None:
                    kind, entry_id, label = entity
                    lbl = ttk.Label(
                        cell,
                        text=label.strip() or "-",
                        justify="left",
                        wraplength=420 if cidx == len(col_list) - 1 else 280,
                    )
                    lbl.grid(row=0, column=0, sticky="nw")
                    self._bind_dex_entity_tooltip(lbl, kind, entry_id)
                    continue
                self._render_value_or_type_chips(
                    cell,
                    col_list[cidx],
                    raw,
                    row=0,
                    column=0,
                    wraplength=420 if cidx == len(col_list) - 1 else 280,
                    short=False,
                    max_per_row=3,
                    padx=(0, 0),
                    pady=0,
                )

    def _dex_add_moves_grid_section(self, title: str, blocks: Any):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="x", expand=False, pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        shell = ttk.Frame(frame)
        shell.grid(row=0, column=0, sticky="ew")
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=1)

        left_col = ttk.Frame(shell)
        right_col = ttk.Frame(shell)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        block_rows = blocks if isinstance(blocks, list) else []
        if not block_rows:
            ttk.Label(frame, text="No move data.").grid(row=1, column=0, sticky="w", pady=(6, 0))
            self._dex_detail_sections.append(frame)
            return

        left_items: list[dict[str, Any]] = []
        right_items: list[dict[str, Any]] = []
        for block in block_rows:
            if not isinstance(block, dict):
                continue
            target = right_items if int(block.get("column", 0)) == 1 else left_items
            target.append(block)
        left_items.sort(key=lambda b: int(b.get("order", 0)))
        right_items.sort(key=lambda b: int(b.get("order", 0)))

        def render_block(parent, block: dict[str, Any]):
            sub = ttk.LabelFrame(parent, text=str(block.get("title", "Moves")), padding=6)
            sub.pack(fill="x", expand=False, pady=(0, 8))
            sub.columnconfigure(0, weight=1)

            columns = block.get("columns", [])
            col_list = [str(c) for c in columns if str(c).strip()] if isinstance(columns, list) else []
            if not col_list:
                col_list = ["Value"]
            rows = block.get("rows", [])
            row_list = rows if isinstance(rows, list) else []
            self._dex_add_inline_table_content(sub, col_list, row_list)

        for block in left_items:
            render_block(left_col, block)
        for block in right_items:
            render_block(right_col, block)

        def _layout(_event=None):
            try:
                width = int(shell.winfo_width())
            except Exception:
                width = 0
            stacked = width > 0 and width < 900
            try:
                left_col.grid_forget()
                right_col.grid_forget()
            except Exception:
                pass
            if stacked:
                left_col.grid(row=0, column=0, sticky="ew", padx=(0, 0))
                right_col.grid(row=1, column=0, sticky="ew", padx=(0, 0))
                shell.columnconfigure(1, weight=0)
            else:
                left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
                right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
                shell.columnconfigure(1, weight=1)

        shell.bind("<Configure>", _layout, add="+")
        frame.after(10, _layout)
        self._dex_detail_sections.append(frame)

    def _dex_add_stats_section(self, title: str, rows: Any):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="x", expand=False, pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        row_list = rows if isinstance(rows, list) else []
        if not row_list:
            ttk.Label(frame, text="(none)").grid(row=0, column=0, sticky="w")
            self._dex_detail_sections.append(frame)
            return

        total = 0
        for idx, row in enumerate(row_list):
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            name = str(row[0]).strip()
            value = self._clamp_int(str(row[1]), 0, 255, 0)
            total += value
            ttk.Label(frame, text=name, width=8).grid(row=idx, column=0, sticky="w", padx=(0, 6), pady=1)
            bar = ttk.Progressbar(frame, mode="determinate", maximum=255, value=value)
            bar.grid(row=idx, column=1, sticky="ew", padx=(0, 6), pady=1)
            ttk.Label(frame, text=str(value), width=4).grid(row=idx, column=2, sticky="e", pady=1)
        ttk.Label(frame, text=f"BST: {total}", font=("", 9, "bold")).grid(
            row=len(row_list), column=0, columnspan=3, sticky="w", pady=(6, 0)
        )
        self._dex_detail_sections.append(frame)

    @staticmethod
    def _value_to_text(value: Any) -> str:
        if isinstance(value, dict):
            label = str(value.get("label", "")).strip()
            if label:
                return label
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(v) for v in value if str(v).strip())
        return str(value)

    @staticmethod
    def _sanitize_lookup_token(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(text or "").casefold())

    def _known_type_ids(self) -> list[str]:
        known: set[str] = {str(t).strip().upper() for t in TYPE_COLOR_HEX.keys()}
        if self.catalogs:
            known.update(str(t).strip().upper() for t in self.catalogs.type_names_by_id.keys())
        return sorted((t for t in known if t), key=str.casefold)

    def _normalize_type_id(self, raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        text = text.lstrip(":").strip()
        if not text:
            return ""
        known = self._known_type_ids()
        upper = text.upper().replace("-", "_").replace(" ", "_")
        if upper in known:
            return upper

        needle = self._sanitize_lookup_token(text)
        if not needle:
            return ""
        for tid in known:
            if needle == self._sanitize_lookup_token(self._type_display_name_for_id(tid)):
                return tid
            if self.catalogs:
                display = self.catalogs.type_names_by_id.get(tid, "")
                if display and needle == self._sanitize_lookup_token(display):
                    return tid
        return ""

    def _extract_type_ids(self, value: Any) -> list[str]:
        out: list[str] = []
        if isinstance(value, (list, tuple, set)):
            for item in value:
                for tid in self._extract_type_ids(item):
                    if tid not in out:
                        out.append(tid)
            return out

        raw = str(value or "").strip()
        if not raw:
            return out
        parts = [p.strip() for p in re.split(r"[\\/,|]", raw) if p.strip()]
        if not parts:
            parts = [raw]
        for part in parts:
            tid = self._normalize_type_id(part)
            if tid and tid not in out:
                out.append(tid)
        return out

    def _is_pure_type_value(self, value: Any) -> bool:
        if isinstance(value, (list, tuple, set)):
            values = [str(v).strip() for v in value if str(v).strip()]
            if not values:
                return False
            return all(bool(self._normalize_type_id(v)) for v in values)
        raw = str(value or "").strip()
        if not raw:
            return False
        parts = [p.strip() for p in re.split(r"[\\/,|]", raw) if p.strip()]
        if not parts:
            return False
        return all(bool(self._normalize_type_id(p)) for p in parts)

    @staticmethod
    def _is_type_field_label(label: str) -> bool:
        key = re.sub(r"[^a-z0-9]+", " ", str(label or "").casefold()).strip()
        if not key:
            return False
        if key in {"type", "types", "hidden power type", "primary type", "secondary type"}:
            return True
        return key.endswith(" type") or key.startswith("type ")

    def _render_type_chip_row(
        self,
        parent,
        type_ids: list[str],
        *,
        short: bool = False,
        empty_text: str = "(none)",
        max_per_row: int = 4,
        clear_existing: bool = True,
        chip_width: int | None = None,
    ):
        if clear_existing:
            for child in parent.winfo_children():
                child.destroy()
        values = [str(t).strip().upper() for t in type_ids if str(t).strip()]
        if not values:
            ttk.Label(parent, text=empty_text).grid(row=0, column=0, sticky="w")
            return
        chunks = self._dex_chunk_list(values, size=max(1, max_per_row))
        for r, chunk in enumerate(chunks):
            for c, tid in enumerate(chunk):
                chip = self._dex_make_type_chip(parent, tid, short=short, chip_width=chip_width)
                chip.grid(row=r, column=c, sticky="w", padx=2, pady=1)

    def _render_value_or_type_chips(
        self,
        parent,
        field_label: str,
        raw_value: Any,
        *,
        row: int,
        column: int,
        wraplength: int,
        short: bool = False,
        max_per_row: int = 4,
        padx: tuple[int, int] = (0, 0),
        pady: int | tuple[int, int] = 1,
    ):
        text_value = self._value_to_text(raw_value).strip()
        if self._is_type_field_label(field_label):
            type_ids = self._extract_type_ids(raw_value)
        else:
            fallback_ids = self._extract_type_ids(raw_value)
            type_ids = fallback_ids if fallback_ids and self._is_pure_type_value(raw_value) else []
        if type_ids:
            holder = ttk.Frame(parent)
            holder.grid(row=row, column=column, sticky="nw", padx=padx, pady=pady)
            self._render_type_chip_row(
                holder,
                type_ids,
                short=short,
                empty_text=text_value or "-",
                max_per_row=max_per_row,
                clear_existing=False,
            )
        else:
            ttk.Label(parent, text=text_value, wraplength=wraplength, justify="left").grid(
                row=row, column=column, sticky="nw", padx=padx, pady=pady
            )

    def _dex_type_chip_colors(self, type_id: str) -> tuple[str, str]:
        tid = str(type_id or "").strip().upper()
        bg = TYPE_COLOR_HEX.get(tid, "#6d7781")
        fg = "#1b1b1b" if tid in TYPE_LIGHT_BG_IDS else "#ffffff"
        return bg, fg

    def _dex_type_chip_label(self, type_id: str, short: bool = False) -> str:
        tid = str(type_id or "").strip().upper()
        if short:
            return TYPE_SHORT_LABELS.get(tid, self._type_display_name_for_id(tid)[:3].upper())
        return self._type_display_name_for_id(tid)

    def _dex_make_type_chip(self, parent, type_id: str, short: bool = False, chip_width: int | None = None):
        bg, fg = self._dex_type_chip_colors(type_id)
        text = self._dex_type_chip_label(type_id, short=short)
        width = chip_width if chip_width is not None else TYPE_CHIP_FIXED_WIDTH
        lbl = tk.Label(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            padx=6,
            pady=2,
            bd=1,
            relief="solid",
            width=max(2, int(width)),
            anchor="center",
            font=("", 8, "bold"),
        )
        return lbl

    @staticmethod
    def _dex_chunk_list(values: list[str], size: int) -> list[list[str]]:
        if size <= 0:
            size = 1
        out: list[list[str]] = []
        for i in range(0, len(values), size):
            out.append(values[i : i + size])
        return out

    def _dex_add_type_matchups_section(
        self,
        title: str,
        defenses: Any,
        attacks: Any,
        defense_title: str = "Type Defenses",
        attack_title: str = "Type Attacks",
    ):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="x", expand=False, pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        shell = ttk.Frame(frame)
        shell.grid(row=0, column=0, sticky="ew")
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=1)

        left = ttk.LabelFrame(shell, text=defense_title, padding=6)
        right = ttk.LabelFrame(shell, text=attack_title, padding=6)
        left_body = ttk.Frame(left)
        left_body.pack(fill="x", expand=True)
        right_body = ttk.Frame(right)
        right_body.pack(fill="x", expand=True)

        defense_rows = defenses if isinstance(defenses, list) else []
        if not defense_rows:
            ttk.Label(left_body, text="(none)").grid(row=0, column=0, sticky="w")
        else:
            defense_groups: dict[float, list[str]] = {}
            for row in defense_rows:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                type_id = str(row[0]).strip().upper()
                mult_value = self._dex_parse_multiplier_value(row[1])
                if not type_id or mult_value is None:
                    continue
                defense_groups.setdefault(round(mult_value, 4), []).append(type_id)

            if not defense_groups:
                ttk.Label(left_body, text="(none)").grid(row=0, column=0, sticky="w")
            else:
                line = 0
                for mult_value in sorted(defense_groups.keys(), reverse=True):
                    bucket_label = self._dex_multiplier_bucket_label(mult_value)
                    ttk.Label(left_body, text=f"{bucket_label}:", font=("", 9, "bold")).grid(
                        row=line, column=0, sticky="nw", padx=(0, 6), pady=(2, 1)
                    )
                    chips_wrap = ttk.Frame(left_body)
                    chips_wrap.grid(row=line, column=1, sticky="w", pady=(1, 2))
                    value_ids = sorted(
                        {str(v).strip().upper() for v in defense_groups.get(mult_value, []) if str(v).strip()},
                        key=str.casefold,
                    )
                    if not value_ids:
                        ttk.Label(chips_wrap, text="(none)").grid(row=0, column=0, sticky="w")
                    else:
                        chunks = self._dex_chunk_list(value_ids, size=5)
                        for r, chunk in enumerate(chunks):
                            for c, item_type_id in enumerate(chunk):
                                chip = self._dex_make_type_chip(
                                    chips_wrap,
                                    item_type_id,
                                    short=True,
                                    chip_width=TYPE_CHIP_COMPACT_WIDTH,
                                )
                                chip.grid(row=r, column=c, sticky="w", padx=2, pady=2)
                    line += 1

        attack_rows = attacks if isinstance(attacks, list) else []
        if not attack_rows:
            ttk.Label(right_body, text="(none)").grid(row=0, column=0, sticky="w")
        else:
            line = 0
            for row in attack_rows:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                bucket = str(row[0]).strip()
                values = row[1] if isinstance(row[1], list) else []
                ttk.Label(right_body, text=f"{bucket}:", font=("", 9, "bold")).grid(
                    row=line, column=0, sticky="nw", padx=(0, 6), pady=(2, 1)
                )
                chips_wrap = ttk.Frame(right_body)
                chips_wrap.grid(row=line, column=1, sticky="w", pady=(1, 2))
                value_ids = [str(v).strip().upper() for v in values if str(v).strip()]
                if not value_ids:
                    ttk.Label(chips_wrap, text="(none)").grid(row=0, column=0, sticky="w")
                else:
                    chunks = self._dex_chunk_list(value_ids, size=4)
                    for r, chunk in enumerate(chunks):
                        for c, type_id in enumerate(chunk):
                            chip = self._dex_make_type_chip(
                                chips_wrap,
                                type_id,
                                short=True,
                                chip_width=TYPE_CHIP_COMPACT_WIDTH,
                            )
                            chip.grid(row=r, column=c, sticky="w", padx=2, pady=2)
                line += 1

        def _layout(_event=None):
            try:
                width = int(shell.winfo_width())
            except Exception:
                width = 0
            stacked = width > 0 and width < 760
            try:
                left.grid_forget()
                right.grid_forget()
            except Exception:
                pass
            if stacked:
                left.grid(row=0, column=0, sticky="ew", pady=(0, 8))
                right.grid(row=1, column=0, sticky="ew")
                shell.columnconfigure(1, weight=0)
            else:
                left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
                right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
                shell.columnconfigure(1, weight=1)

        shell.bind("<Configure>", _layout, add="+")
        frame.after(10, _layout)
        self._dex_detail_sections.append(frame)

    def _on_dex_evo_canvas_mousewheel(self, canvas: tk.Canvas, event):
        result = self._scroll_canvas_mousewheel(canvas, event)
        if result == "break":
            return "break"
        return self._on_dex_detail_mousewheel(event)

    def _dex_add_evolution_chart_section(
        self,
        title: str,
        species_id: str,
        form: int,
        height_hint: Any = None,
        show_all_conditions: bool = False,
    ):
        frame = ttk.LabelFrame(self.dex_detail_body, text=title, padding=8)
        frame.pack(fill="both", expand=False, pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        shell = ttk.Frame(frame)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        try:
            hinted = int(height_hint)
        except (TypeError, ValueError):
            hinted = 340
        chart_h = max(240, hinted)
        chart_species = str(species_id or "").strip().lstrip(":")
        if self.catalogs and chart_species:
            chart_species = self.catalogs.canonical_species_id(chart_species) or chart_species
        chart_form = self._clamp_int(str(form), 0, 999, 0)

        canvas = tk.Canvas(shell, height=chart_h, borderwidth=0, highlightthickness=0, background="#fbfbfb")
        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vscroll.set)

        canvas.bind("<MouseWheel>", lambda e, c=canvas: self._on_dex_evo_canvas_mousewheel(c, e), add="+")
        canvas.bind("<Button-4>", lambda e, c=canvas: self._on_dex_evo_canvas_mousewheel(c, e), add="+")
        canvas.bind("<Button-5>", lambda e, c=canvas: self._on_dex_evo_canvas_mousewheel(c, e), add="+")

        def _on_node_click(node_species_id: str, active_species_id=chart_species):
            clicked = str(node_species_id or "").strip().lstrip(":")
            if self.catalogs and clicked:
                clicked = self.catalogs.canonical_species_id(clicked) or clicked
            active = str(active_species_id or "").strip().lstrip(":")
            if self.catalogs and active:
                active = self.catalogs.canonical_species_id(active) or active
            if not clicked or clicked.upper() == active.upper():
                return
            self._dex_jump_to_species_entry(clicked, form=0)

        def _redraw(_event=None, c=canvas, sid=chart_species, sid_form=chart_form, show_all=show_all_conditions):
            self._render_evolution_chart_to_canvas(
                c,
                sid,
                sid_form,
                no_species_text="No evolution chain data.",
                invalid_species_text="No evolution chain data.",
                show_all_conditions=show_all,
                on_node_click=_on_node_click,
            )

        canvas.bind("<Configure>", _redraw, add="+")
        try:
            frame.after(10, _redraw)
        except Exception:
            _redraw()

        self._dex_detail_sections.append(frame)

    def _dex_species_payload(self, species_id: str) -> dict[str, Any]:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_species_id(species_id) or species_id
        form = self._clamp_int(self.dex_form_var.get(), 0, 999, 0)
        self.dex_form_var.set(str(form))
        profile = self.catalogs.get_species_form_profile(canonical, form=form)
        if not profile:
            return {
                "title": "Pokédex",
                "subtitle": f"No profile found for form {form}.",
                "hero": [("Requested ID", canonical), ("Form", str(form))],
                "sections": [
                    {
                        "kind": "text",
                        "title": "Status",
                        "text": f"No species profile found for form {form}.",
                    }
                ],
            }

        item = self.catalogs.species_by_id.get(profile.internal_id) or self.catalogs.species_by_id.get(profile.species_id)
        display_name = self._dex_display_name_for_entry("Species", profile.species_id)
        base = self.catalogs.base_stats_for_species(profile.species_id, form=profile.form)
        bst = sum(int(base.get(k, 0)) for k in ("HP", "ATTACK", "DEFENSE", "SPECIAL_ATTACK", "SPECIAL_DEFENSE", "SPEED"))
        growth = self.catalogs.growth_rate_for_species(profile.species_id, form=profile.form)
        type_ids = self._dex_species_type_ids(profile.species_id, profile.form, profile=profile)
        type_labels = [self._type_display_name_for_id(tid) for tid in type_ids]

        ability_ids, hidden_ids = self.catalogs.valid_abilities_for_species(profile.species_id, form=profile.form)
        ability_labels = []
        ability_entries: list[dict[str, str]] = []
        for aid in ability_ids:
            label = self._english_ability_name_for_id(aid)
            if aid in hidden_ids:
                label = f"{label} (H)"
            ability_labels.append(label)
            ability_entries.append({"kind": "ability", "id": aid, "label": label})

        valid_moves = self.catalogs.valid_moves_for_species(profile.species_id, form=profile.form, include_pre_evolutions=True)
        relearn_moves = self.catalogs.valid_relearn_moves_for_species(
            profile.species_id,
            form=profile.form,
            include_pre_evolutions=True,
        )
        level_pairs = sorted(profile.level_up_pairs, key=lambda row: (row[0], row[1].casefold()))
        level_rows: list[tuple[Any, Any, Any, Any, Any, Any]] = []
        evolution_rows: list[tuple[Any, Any, Any, Any, Any]] = []
        for lvl, raw_mid in level_pairs:
            mid = self.catalogs.canonical_move_id(raw_mid) or raw_mid
            move_name, move_type, category, power, acc = self._dex_move_detail_cells(mid)
            move_entry = {"kind": "move", "id": mid, "label": move_name}
            if lvl <= 0:
                evolution_rows.append((move_entry, move_type, category, power, acc))
            else:
                level_rows.append((str(lvl), move_entry, move_type, category, power, acc))

        tm_rows = self._dex_tm_rows_for_species(valid_moves)
        tutor_rows = self._dex_move_rows_for_ids(profile.tutor_moves)
        egg_rows = self._dex_move_rows_for_ids(profile.egg_moves)
        relearn_rows = self._dex_move_rows_for_ids(relearn_moves)

        forms = sorted({pf.form for (_sid, _form), pf in self.catalogs.species_form_profiles.items() if pf.species_id == profile.species_id})
        defense_rows = self._dex_type_defense_rows(type_ids)
        offense_rows = self._dex_type_offense_rows(type_ids)
        spawn_rows = self._dex_spawn_rows_for_species(profile.species_id)

        dex_text_raw = str(item.extra.get("Pokedex", "")).strip() if item else ""
        dex_text = self._english_description(dex_text_raw, "") or dex_text_raw or "No Pokédex description available."
        form_text = f"{profile.form}" + (f" ({profile.form_name})" if profile.form_name else "")
        hero_rows = [
            ("Category", "Pokédex"),
            ("Form", form_text),
            ("Internal ID", profile.species_id),
            ("Type", " / ".join(type_labels) if type_labels else "Unknown"),
        ]
        move_blocks: list[dict[str, Any]] = [
            {
                "title": "Moves learnt by level up",
                "column": 0,
                "order": 0,
                "columns": ["Lv", "Move", "Type", "Cat", "Power", "Acc"],
                "rows": level_rows,
            },
            {
                "title": "Moves learnt on evolution",
                "column": 0,
                "order": 1,
                "columns": ["Move", "Type", "Cat", "Power", "Acc"],
                "rows": evolution_rows,
            },
            {
                "title": "Moves learnt by reminder",
                "column": 0,
                "order": 2,
                "columns": ["Move", "Type", "Cat", "Power", "Acc"],
                "rows": relearn_rows,
            },
            {
                "title": "Egg moves",
                "column": 0,
                "order": 3,
                "columns": ["Move", "Type", "Cat", "Power", "Acc"],
                "rows": egg_rows,
            },
            {
                "title": "Moves learnt by TM/HM",
                "column": 1,
                "order": 0,
                "columns": ["TM", "Move", "Type", "Cat", "Power", "Acc"],
                "rows": tm_rows,
            },
            {
                "title": "Tutor moves",
                "column": 1,
                "order": 1,
                "columns": ["Move", "Type", "Cat", "Power", "Acc"],
                "rows": tutor_rows,
            },
        ]
        sections: list[dict[str, Any]] = [
            {
                "kind": "kv",
                "title": "Pokédex data",
                "rows": [
                    ("Name", display_name),
                    ("Growth Rate", growth),
                    ("Abilities", ability_entries if ability_entries else self._dex_join_list(ability_labels, limit=12)),
                    ("Available Forms", ", ".join(str(v) for v in forms) if forms else "0"),
                    ("Legal Moves (incl. pre-evo)", str(len(valid_moves))),
                    ("Relearn Moves (incl. pre-evo)", str(len(relearn_moves))),
                ],
            },
            {
                "kind": "stats",
                "title": "Base stats",
                "rows": [
                    ("HP", base.get("HP", 0)),
                    ("Atk", base.get("ATTACK", 0)),
                    ("Def", base.get("DEFENSE", 0)),
                    ("SpA", base.get("SPECIAL_ATTACK", 0)),
                    ("SpD", base.get("SPECIAL_DEFENSE", 0)),
                    ("Spe", base.get("SPEED", 0)),
                ],
            },
            {
                "kind": "type_matchups",
                "title": "Type Matchups",
                "defense_title": "Type Defenses",
                "attack_title": "Type Attacks",
                "defenses": defense_rows,
                "attacks": offense_rows,
            },
            {
                "kind": "evolution_chart",
                "title": "Evolution chart",
                "species_id": profile.species_id,
                "form": profile.form,
                "height": 360,
                "show_all_conditions": True,
            },
            {"kind": "moves_grid", "title": "Move learnsets", "blocks": move_blocks},
            {
                "kind": "table",
                "title": "Where to find",
                "columns": ["Map", "Method", "Levels", "Rate"],
                "rows": spawn_rows,
            },
            {
                "kind": "text",
                "title": "Description",
                "text": dex_text,
            },
        ]
        return {
            "title": display_name,
            "subtitle": f"Pokédex - {self._english_species_name_for_id(profile.species_id)} (BST {bst})",
            "image": {"species_id": profile.species_id, "form": profile.form, "shiny": False},
            "hero": hero_rows,
            "sections": sections,
        }

    def _dex_move_payload(self, move_id: str) -> dict[str, Any]:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_move_id(move_id) or move_id
        move = self.catalogs.moves_by_id.get(canonical)
        if not move:
            return {
                "title": "Moves dex",
                "subtitle": "No move data found.",
                "hero": [("Internal ID", canonical)],
                "sections": [{"kind": "text", "title": "Status", "text": "No move data found."}],
            }

        display_name = self._dex_display_name_for_entry("Moves", canonical)
        raw_desc = self.catalogs.move_description(canonical)
        summary = self._move_numeric_summary_lines(canonical, raw_desc, "")
        base_desc, summary = self._resolve_entity_description("move", canonical, raw_desc, summary)
        learners = self._dex_species_with_move(canonical)
        learner_labels = [self._dex_display_name_for_entry("Species", sid) for sid in learners]

        facts = [("Internal ID", canonical)]
        for key in ("Type", "Category", "Power", "Accuracy", "TotalPP", "Priority", "Target", "FunctionCode", "Flags"):
            value = str(move.extra.get(key, "")).strip()
            if value:
                if key == "Type":
                    value = self._type_display_name_for_id(value.lstrip(":"))
                facts.append((key, value))
        tm_labels = self._dex_move_tm_labels(canonical)
        if tm_labels:
            facts.append(("TM No.", ", ".join(tm_labels)))
        facts.append(("Learner species", str(len(learner_labels))))

        notes = self._append_mechanics_block(base_desc, summary)
        sections = [
            {"kind": "kv", "title": "Move data", "rows": facts},
            {"kind": "text", "title": "Description", "text": notes},
            {
                "kind": "table",
                "title": "Species that can learn this move",
                "columns": ["Species"],
                "rows": [(label,) for label in learner_labels],
            },
        ]
        return {
            "title": display_name,
            "subtitle": "Moves dex",
            "hero": [("Category", "Moves dex"), ("Name", display_name)],
            "sections": sections,
        }

    def _dex_item_payload(self, item_id: str) -> dict[str, Any]:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_item_id(item_id) or item_id
        item = self.catalogs.items_by_id.get(canonical)
        if not item:
            return {
                "title": "Items dex",
                "subtitle": "No item data found.",
                "hero": [("Internal ID", canonical)],
                "sections": [{"kind": "text", "title": "Status", "text": "No item data found."}],
            }

        display_name = self._dex_display_name_for_entry("Items", canonical)
        raw_desc = self.catalogs.item_description(canonical)
        summary = self._item_numeric_summary_lines(canonical, raw_desc, "")
        base_desc, summary = self._resolve_entity_description("item", canonical, raw_desc, summary)

        facts = [("Internal ID", canonical)]
        pocket_raw = str(item.extra.get("Pocket", "")).strip()
        if pocket_raw:
            try:
                pidx = int(pocket_raw)
                pocket_text = EN_POCKET_NAMES.get(pidx, f"Pocket {pidx}")
            except ValueError:
                pocket_text = pocket_raw
            facts.append(("Pocket", pocket_text))
        for key in ("Price", "FieldUse", "BattleUse", "Flags"):
            value = str(item.extra.get(key, "")).strip()
            if value:
                facts.append((key, value))

        rows: list[tuple[str, ...]] = []
        move_raw = str(item.extra.get("Move", "")).strip().lstrip(":")
        if move_raw:
            move_key = self.catalogs.canonical_move_id(move_raw) or move_raw
            rows.append((self._dex_display_name_for_entry("Moves", move_key),))

        shop_rows = self._dex_item_shop_rows(canonical)
        notes = self._append_mechanics_block(base_desc, summary)
        sections: list[dict[str, Any]] = [
            {"kind": "kv", "title": "Item data", "rows": facts},
            {"kind": "text", "title": "Description", "text": notes},
        ]
        if rows:
            sections.append(
                {
                    "kind": "table",
                    "title": "Associated move",
                    "columns": ["Move"],
                    "rows": rows,
                    "height": 1,
                }
            )
        if shop_rows:
            sections.append(
                {
                    "kind": "table",
                    "title": "Where to find",
                    "columns": ["Map", "Shop", "Currency"],
                    "rows": shop_rows,
                    "height": min(6, len(shop_rows)),
                }
            )
        return {
            "title": display_name,
            "subtitle": "Items dex",
            "hero": [("Category", "Items dex"), ("Name", display_name)],
            "image": {"item_id": canonical},
            "sections": sections,
        }

    def _dex_ability_payload(self, ability_id: str) -> dict[str, Any]:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_ability_id(ability_id) or ability_id
        ability = self.catalogs.abilities_by_id.get(canonical)
        if not ability:
            return {
                "title": "Abilities dex",
                "subtitle": "No ability data found.",
                "hero": [("Internal ID", canonical)],
                "sections": [{"kind": "text", "title": "Status", "text": "No ability data found."}],
            }

        display_name = self._english_ability_name_for_id(canonical)
        raw_desc = self.catalogs.ability_description(canonical)
        summary = self._ability_numeric_summary_lines(canonical, raw_desc, "")
        base_desc, summary = self._resolve_entity_description("ability", canonical, raw_desc, summary)
        normal_species, hidden_species = self._dex_species_with_ability(canonical)
        normal_labels = [self._dex_display_name_for_entry("Species", sid) for sid in normal_species]
        hidden_labels = [self._dex_display_name_for_entry("Species", sid) for sid in hidden_species]

        facts = [
            ("Internal ID", canonical),
            ("Normal-slot species", str(len(normal_labels))),
            ("Hidden-slot species", str(len(hidden_labels))),
        ]
        notes = self._append_mechanics_block(base_desc, summary)
        rows = [("Normal", name) for name in normal_labels] + [("Hidden", name) for name in hidden_labels]
        return {
            "title": display_name,
            "subtitle": "Abilities dex",
            "hero": [("Category", "Abilities dex"), ("Name", display_name)],
            "sections": [
                {"kind": "kv", "title": "Ability data", "rows": facts},
                {"kind": "text", "title": "Description", "text": notes},
                {
                    "kind": "table",
                    "title": "Species with this ability",
                    "columns": ["Slot", "Species"],
                    "rows": rows,
                },
            ],
        }

    def _dex_nature_payload(self, nature_id: str) -> dict[str, Any]:
        nature = str(nature_id or "").strip().upper()
        if not nature:
            return {
                "title": "Natures dex",
                "subtitle": "No nature selected.",
                "hero": [],
                "sections": [{"kind": "text", "title": "Status", "text": "No nature selected."}],
            }
        up, down = NATURE_EFFECTS.get(nature, (None, None))
        rows = [("Nature", self._title_case_words(nature)), ("Internal ID", nature)]
        if not up or not down:
            rows.extend(
                [
                    ("Boosted Stat", "None"),
                    ("Lowered Stat", "None"),
                    ("Stat Multipliers", "All non-HP stats remain x1.0"),
                ]
            )
        else:
            rows.extend(
                [
                    ("Boosted Stat", f"{STAT_SHORT_LABELS.get(up, up)} (x1.1)"),
                    ("Lowered Stat", f"{STAT_SHORT_LABELS.get(down, down)} (x0.9)"),
                    ("Other Non-HP Stats", "x1.0"),
                ]
            )
        return {
            "title": self._title_case_words(nature),
            "subtitle": "Natures dex",
            "hero": [("Category", "Natures dex"), ("Name", self._title_case_words(nature))],
            "sections": [
                {"kind": "kv", "title": "Nature data", "rows": rows},
                {"kind": "text", "title": "Description", "text": self._nature_description(nature)},
            ],
        }

    def _dex_type_payload(self, type_id: str) -> dict[str, Any]:
        assert self.catalogs is not None
        tid = str(type_id or "").strip().upper()
        if not tid:
            return {
                "title": "Types dex",
                "subtitle": "No type selected.",
                "hero": [],
                "sections": [{"kind": "text", "title": "Status", "text": "No type selected."}],
            }

        display = self._type_display_name_for_id(tid)
        move_ids = [
            mid
            for mid, item in self.catalogs.moves_by_id.items()
            if str(item.extra.get("Type", "")).strip().lstrip(":").upper() == tid
        ]
        move_ids.sort(key=str.casefold)
        move_labels = [self._dex_display_name_for_entry("Moves", mid) for mid in move_ids]
        species_ids = self._dex_species_with_type(tid)
        species_labels = [self._dex_display_name_for_entry("Species", sid) for sid in species_ids]
        defense_rows = self._dex_type_defense_rows([tid])
        offense_rows = self._dex_type_offense_rows([tid])

        detail_rows = [("Internal ID", tid), ("Moves Count", str(len(move_labels))), ("Species Count", str(len(species_labels)))]
        if tid in self.catalogs.hidden_power_type_ids:
            idx = self.catalogs.hidden_power_type_ids.index(tid)
            detail_rows.append(("Hidden Power Index", f"{idx + 1}/{len(self.catalogs.hidden_power_type_ids)}"))

        return {
            "title": display,
            "subtitle": "Types dex",
            "hero": [("Category", "Types dex"), ("Name", display)],
            "sections": [
                {"kind": "kv", "title": "Type data", "rows": detail_rows},
                {
                    "kind": "type_matchups",
                    "title": "Type Matchups",
                    "defense_title": "Type Defenses",
                    "attack_title": "Type Attacks",
                    "defenses": defense_rows,
                    "attacks": offense_rows,
                },
                {"kind": "table", "title": "Moves of this type", "columns": ["Move"], "rows": [(x,) for x in move_labels]},
                {
                    "kind": "table",
                    "title": "Species with this type",
                    "columns": ["Species"],
                    "rows": [(x,) for x in species_labels],
                },
            ],
        }

    def _dex_load_type_chart_data(self) -> tuple[dict[str, dict[str, float]], list[str]]:
        if self._dex_type_chart_defense is not None:
            return self._dex_type_chart_defense, list(self._dex_type_order)

        valid_types = {str(t).strip().upper() for t in (self.catalogs.type_names_by_id.keys() if self.catalogs else [])}
        sections = parse_pbs_sections(self.game_root / "PBS" / "types.txt")
        defense_map: dict[str, dict[str, float]] = {}

        for raw_id, data in sections.items():
            tid = str(raw_id or "").strip().upper()
            if not tid:
                continue
            is_pseudo = str(data.get("IsPseudoType", data.get("PseudoType", ""))).strip().lower() in {"true", "1", "yes"}
            if is_pseudo:
                continue
            if valid_types and tid not in valid_types:
                continue
            defense_map.setdefault(tid, {})

        if not defense_map:
            for tid in sorted(valid_types, key=str.casefold):
                defense_map.setdefault(tid, {})

        all_types = sorted(defense_map.keys(), key=str.casefold)
        if self.catalogs and self.catalogs.hidden_power_type_ids:
            ordered = [tid for tid in self.catalogs.hidden_power_type_ids if tid in defense_map]
            ordered.extend([tid for tid in all_types if tid not in ordered])
            all_types = ordered

        for def_tid in all_types:
            defense_map[def_tid] = {atk_tid: 1.0 for atk_tid in all_types}

        def _parse_type_list(raw: str) -> list[str]:
            out: list[str] = []
            for chunk in str(raw or "").split(","):
                tid = chunk.strip().lstrip(":").upper()
                if tid and tid in defense_map:
                    out.append(tid)
            return out

        for raw_id, data in sections.items():
            def_tid = str(raw_id or "").strip().upper()
            if def_tid not in defense_map:
                continue
            for atk_tid in _parse_type_list(data.get("Weaknesses", "")):
                defense_map[def_tid][atk_tid] = 2.0
            for atk_tid in _parse_type_list(data.get("Resistances", "")):
                defense_map[def_tid][atk_tid] = 0.5
            for atk_tid in _parse_type_list(data.get("Immunities", "")):
                defense_map[def_tid][atk_tid] = 0.0

        self._dex_type_chart_defense = defense_map
        self._dex_type_order = all_types
        return defense_map, list(all_types)

    @staticmethod
    def _dex_multiplier_label(multiplier: float) -> str:
        value = float(multiplier)
        if abs(value) < 1e-9:
            return "0x"
        rounded = round(value, 4)
        if rounded.is_integer():
            return f"{int(rounded)}x"
        return f"{rounded:g}x"

    @staticmethod
    def _dex_parse_multiplier_value(raw: Any) -> float | None:
        text = str(raw or "").strip().lower().replace(" ", "")
        if not text:
            return None
        if text.startswith("x"):
            text = text[1:]
        if text.endswith("x"):
            text = text[:-1]
        if not text:
            return None
        if "/" in text:
            left, right = text.split("/", 1)
            try:
                num = float(left)
                den = float(right)
            except Exception:
                return None
            if abs(den) < 1e-9:
                return None
            return num / den
        try:
            return float(text)
        except Exception:
            return None

    @staticmethod
    def _dex_multiplier_bucket_label(value: float) -> str:
        rounded = round(float(value), 4)
        if abs(rounded) < 1e-9:
            return "x0"
        if rounded >= 1.0:
            if rounded.is_integer():
                return f"x{int(rounded)}"
            return f"x{rounded:g}"
        reciprocal = round(1.0 / rounded) if abs(rounded) > 1e-9 else 0
        if reciprocal > 0 and abs(rounded - (1.0 / reciprocal)) <= 1e-4:
            return f"x1/{reciprocal}"
        return f"x{rounded:g}"

    def _dex_species_type_ids(
        self,
        species_id: str,
        form: int = 0,
        profile: Any | None = None,
    ) -> list[str]:
        if not self.catalogs:
            return []
        pf = profile if profile is not None else self.catalogs.get_species_form_profile(species_id, form=form)
        candidates: list[str] = []
        if pf is not None:
            if pf.internal_id:
                candidates.append(pf.internal_id)
            if pf.species_id and pf.species_id not in candidates:
                candidates.append(pf.species_id)
        canonical = self.catalogs.canonical_species_id(species_id)
        if canonical and canonical not in candidates:
            candidates.append(canonical)

        type_ids: list[str] = []
        for sid in candidates:
            item = self.catalogs.species_by_id.get(sid)
            if not item:
                continue
            raw_types = str(item.extra.get("Types", item.extra.get("Type", ""))).strip()
            if not raw_types:
                continue
            for chunk in raw_types.split(","):
                tid = chunk.strip().lstrip(":").upper()
                if tid and tid not in type_ids:
                    type_ids.append(tid)
            if type_ids:
                break
        return type_ids

    def _dex_type_defense_rows(self, type_ids: list[str]) -> list[tuple[str, str]]:
        defense_map, type_order = self._dex_load_type_chart_data()
        if not type_ids or not type_order:
            return []
        rows: list[tuple[str, str, float]] = []
        for atk_tid in type_order:
            mult = 1.0
            for def_tid in type_ids:
                mult *= float(defense_map.get(def_tid, {}).get(atk_tid, 1.0))
            rows.append((atk_tid, self._dex_multiplier_label(mult), mult))
        rows.sort(key=lambda row: (-row[2], row[0].casefold()))
        return [(tid, label) for tid, label, _mult in rows]

    def _dex_type_offense_rows(self, attack_type_ids: list[str]) -> list[tuple[str, list[str]]]:
        defense_map, type_order = self._dex_load_type_chart_data()
        if not attack_type_ids or not type_order:
            return [
                ("2x", []),
                ("1/2x", []),
                ("0x", []),
            ]
        strong: list[str] = []
        resisted: list[str] = []
        immune: list[str] = []
        for def_tid in type_order:
            best = 0.0
            for atk_tid in attack_type_ids:
                best = max(best, float(defense_map.get(def_tid, {}).get(atk_tid, 1.0)))
            if best <= 0.0:
                immune.append(def_tid)
            elif best > 1.0:
                strong.append(def_tid)
            elif best < 1.0:
                resisted.append(def_tid)
        strong.sort(key=str.casefold)
        resisted.sort(key=str.casefold)
        immune.sort(key=str.casefold)
        return [
            ("2x", strong),
            ("1/2x", resisted),
            ("0x", immune),
        ]

    def _dex_load_spawn_index(self):
        if self._dex_spawn_index is not None:
            return
        self._dex_spawn_index = {}
        self._dex_map_names = {}
        if not self.catalogs:
            return

        map_sections = parse_pbs_sections(self.game_root / "PBS" / "map_metadata.txt")
        for raw_id, data in map_sections.items():
            try:
                map_id = int(str(raw_id).strip())
            except (TypeError, ValueError):
                continue
            name = str(data.get("Name", "")).strip()
            if name:
                self._dex_map_names[map_id] = name

        encounters_path = self.game_root / "PBS" / "encounters.txt"
        if not encounters_path.exists():
            return

        current_map_id: int | None = None
        current_map_hint = ""
        current_method = ""
        for raw in encounters_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            m = re.match(r"^\[(\d+)\](?:\s*#\s*(.*))?$", stripped)
            if m:
                try:
                    current_map_id = int(m.group(1))
                except ValueError:
                    current_map_id = None
                current_map_hint = str(m.group(2) or "").strip()
                current_method = ""
                continue
            if current_map_id is None:
                continue

            if raw[:1].isspace():
                if not current_method:
                    continue
                parts = [chunk.strip() for chunk in stripped.split(",")]
                if len(parts) < 4:
                    continue
                method_key = current_method.strip()
                if method_key.upper().endswith("CLASSIC"):
                    continue
                species_raw = parts[1].lstrip(":").strip()
                canonical_species = self.catalogs.canonical_species_id(species_raw) or species_raw.upper()
                if not canonical_species:
                    continue
                try:
                    min_level = int(parts[2])
                    max_level = int(parts[3])
                except (TypeError, ValueError):
                    continue
                try:
                    weight = int(parts[0])
                except (TypeError, ValueError):
                    weight = 0
                map_name = self._dex_map_names.get(current_map_id, "")
                if not map_name:
                    map_name = current_map_hint or f"Map {current_map_id:03d}"
                self._dex_spawn_index.setdefault(canonical_species, []).append(
                    {
                        "map_id": current_map_id,
                        "map_name": map_name,
                        "method": method_key,
                        "min_level": min_level,
                        "max_level": max_level,
                        "weight": weight,
                    }
                )
                continue

            current_method = stripped.split(",", 1)[0].strip()

    def _dex_spawn_rows_for_species(self, species_id: str) -> list[tuple[str, str, str, str]]:
        if not self.catalogs:
            return []
        self._dex_load_spawn_index()
        if self._dex_spawn_index is None:
            return []
        canonical = self.catalogs.canonical_species_id(species_id) or str(species_id or "").strip().lstrip(":").upper()
        entries = self._dex_spawn_index.get(canonical, [])
        if not entries:
            return []

        grouped: dict[tuple[int, str], dict[str, Any]] = {}
        for row in entries:
            map_id = int(row.get("map_id", 0))
            method = str(row.get("method", "")).strip()
            key = (map_id, method)
            current = grouped.get(key)
            if current is None:
                grouped[key] = dict(row)
                continue
            current["min_level"] = min(int(current.get("min_level", 0)), int(row.get("min_level", 0)))
            current["max_level"] = max(int(current.get("max_level", 0)), int(row.get("max_level", 0)))
            current["weight"] = int(current.get("weight", 0)) + int(row.get("weight", 0))

        rows: list[tuple[str, str, str, str]] = []
        for (_map_id, _method), row in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1].casefold())):
            map_id = int(row.get("map_id", 0))
            map_name = str(row.get("map_name", "")).strip() or f"Map {map_id:03d}"
            map_label = f"{map_name} [{map_id:03d}]"
            method = str(row.get("method", "")).strip() or "Unknown"
            min_level = int(row.get("min_level", 0))
            max_level = int(row.get("max_level", 0))
            level_range = str(min_level) if min_level == max_level else f"{min_level}-{max_level}"
            rate = int(row.get("weight", 0))
            rate_label = f"{rate}%"
            rows.append((map_label, method, level_range, rate_label))
        return rows

    @staticmethod
    def _dex_script_param_text(value: Any) -> str:
        if isinstance(value, core.RubyString):
            return str(value)
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("latin-1", errors="replace")
        if isinstance(value, str):
            return value
        return ""

    def _dex_extract_event_scripts(self, map_obj: Any) -> list[str]:
        if not isinstance(map_obj, core.RubyObject):
            return []
        events = core.read_attr(map_obj, "@events", {})
        if not isinstance(events, dict):
            return []
        scripts: list[str] = []
        for event in events.values():
            if not isinstance(event, core.RubyObject):
                continue
            pages = core.read_attr(event, "@pages", [])
            if not isinstance(pages, list):
                continue
            for page in pages:
                if not isinstance(page, core.RubyObject):
                    continue
                commands = core.read_attr(page, "@list", [])
                if not isinstance(commands, list):
                    continue
                idx = 0
                while idx < len(commands):
                    cmd = commands[idx]
                    if not isinstance(cmd, core.RubyObject):
                        idx += 1
                        continue
                    code = core.read_attr(cmd, "@code", None)
                    if code != 355:
                        idx += 1
                        continue
                    lines: list[str] = []
                    params = core.read_attr(cmd, "@parameters", [])
                    if isinstance(params, list) and params:
                        text = self._dex_script_param_text(params[0]).strip()
                        if text:
                            lines.append(text)
                    j = idx + 1
                    while j < len(commands):
                        nxt = commands[j]
                        if not isinstance(nxt, core.RubyObject):
                            break
                        ncode = core.read_attr(nxt, "@code", None)
                        if ncode != 655:
                            break
                        nparams = core.read_attr(nxt, "@parameters", [])
                        if isinstance(nparams, list) and nparams:
                            text = self._dex_script_param_text(nparams[0]).strip()
                            if text:
                                lines.append(text)
                        j += 1
                    if lines:
                        scripts.append("\n".join(lines))
                    idx = j
        return scripts

    def _dex_load_item_shop_index(self):
        if self._dex_item_shop_index is not None:
            return
        self._dex_item_shop_index = {}
        if not self.catalogs:
            return

        if not self._dex_map_names:
            map_sections = parse_pbs_sections(self.game_root / "PBS" / "map_metadata.txt")
            for raw_id, data in map_sections.items():
                try:
                    map_id = int(str(raw_id).strip())
                except (TypeError, ValueError):
                    continue
                name = str(data.get("Name", "")).strip()
                if name:
                    self._dex_map_names[map_id] = name

        data_dir = self.game_root / "Data"
        for map_path in sorted(data_dir.glob("Map*.rxdata")):
            m = re.match(r"^Map(\d+)\.rxdata$", map_path.name, flags=re.IGNORECASE)
            if not m:
                continue
            try:
                map_id = int(m.group(1))
            except ValueError:
                continue
            try:
                raw = map_path.read_bytes()
            except Exception:
                continue
            has_poke_mart = b"pbPokemonMart" in raw
            has_bp_shop = b"pbBattlePointShop" in raw
            if not has_poke_mart and not has_bp_shop:
                continue

            try:
                map_obj = core.load_save(map_path)
            except Exception:
                continue
            scripts = self._dex_extract_event_scripts(map_obj)
            if not scripts:
                continue

            map_name = self._dex_map_names.get(map_id, f"Map {map_id:03d}")
            for script in scripts:
                if "pbPokemonMart" in script:
                    for blob in re.findall(r"pbPokemonMart\(\s*\[(.*?)\]\s*\)", script, flags=re.IGNORECASE | re.DOTALL):
                        for sym in re.findall(r":([A-Za-z0-9_]+)", blob):
                            canonical = self.catalogs.canonical_item_id(sym)
                            if not canonical:
                                continue
                            self._dex_item_shop_index.setdefault(canonical, []).append(
                                {
                                    "map_id": map_id,
                                    "map_name": map_name,
                                    "shop_type": "Poké Mart",
                                    "currency": "Money",
                                }
                            )
                if "pbBattlePointShop" in script:
                    for blob in re.findall(r"pbBattlePointShop\(\s*\[(.*?)\]\s*\)", script, flags=re.IGNORECASE | re.DOTALL):
                        for sym in re.findall(r":([A-Za-z0-9_]+)", blob):
                            canonical = self.catalogs.canonical_item_id(sym)
                            if not canonical:
                                continue
                            self._dex_item_shop_index.setdefault(canonical, []).append(
                                {
                                    "map_id": map_id,
                                    "map_name": map_name,
                                    "shop_type": "BP Shop",
                                    "currency": "BP",
                                }
                            )

    def _dex_item_shop_rows(self, item_id: str) -> list[tuple[str, str, str]]:
        if not self.catalogs:
            return []
        self._dex_load_item_shop_index()
        if self._dex_item_shop_index is None:
            return []
        canonical = self.catalogs.canonical_item_id(item_id) or str(item_id or "").strip().lstrip(":").upper()
        entries = self._dex_item_shop_index.get(canonical, [])
        if not entries:
            return []

        seen: set[tuple[int, str, str]] = set()
        rows: list[tuple[str, str, str]] = []
        for row in entries:
            map_id = int(row.get("map_id", 0))
            shop_type = str(row.get("shop_type", "")).strip() or "Shop"
            currency = str(row.get("currency", "")).strip() or "Money"
            key = (map_id, shop_type, currency)
            if key in seen:
                continue
            seen.add(key)
            map_name = str(row.get("map_name", "")).strip() or f"Map {map_id:03d}"
            map_label = f"{map_name} [{map_id:03d}]"
            rows.append((map_label, shop_type, currency))
        rows.sort(key=lambda r: (r[0].casefold(), r[1].casefold(), r[2].casefold()))
        return rows

    def _dex_species_details(self, species_id: str) -> str:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_species_id(species_id) or species_id
        form = self._clamp_int(self.dex_form_var.get(), 0, 999, 0)
        self.dex_form_var.set(str(form))
        profile = self.catalogs.get_species_form_profile(canonical, form=form)
        if not profile:
            return f"Species: {canonical}\n\nNo species profile found for form {form}."

        item = self.catalogs.species_by_id.get(profile.internal_id) or self.catalogs.species_by_id.get(profile.species_id)
        display_name = item.display_name if item else profile.internal_id
        english_name = self._english_species_name_for_id(profile.species_id)
        lines = [
            f"Species: {profile.species_id} - {english_name}",
            f"Display name in data: {display_name}",
            f"Profile ID: {profile.internal_id}",
            f"Form: {profile.form}" + (f" ({profile.form_name})" if profile.form_name else ""),
        ]

        base = self.catalogs.base_stats_for_species(profile.species_id, form=profile.form)
        if base:
            bst = sum(int(base.get(k, 0)) for k in ("HP", "ATTACK", "DEFENSE", "SPECIAL_ATTACK", "SPECIAL_DEFENSE", "SPEED"))
            lines.append(
                "Base stats: "
                f"HP {base.get('HP', 0)} / Atk {base.get('ATTACK', 0)} / Def {base.get('DEFENSE', 0)} / "
                f"SpA {base.get('SPECIAL_ATTACK', 0)} / SpD {base.get('SPECIAL_DEFENSE', 0)} / Spe {base.get('SPEED', 0)}"
            )
            lines.append(f"Base stat total: {bst}")

        growth = self.catalogs.growth_rate_for_species(profile.species_id, form=profile.form)
        lines.append(f"Growth rate: {growth}")

        ability_ids, hidden_ids = self.catalogs.valid_abilities_for_species(profile.species_id, form=profile.form)
        ability_labels = []
        for aid in ability_ids:
            label = self._english_ability_name_for_id(aid)
            if aid in hidden_ids:
                label = f"{label} (H)"
            ability_labels.append(label)
        lines.append(f"Abilities: {self._dex_join_list(ability_labels, limit=12)}")

        forms = sorted(
            {pf.form for (_sid, _form), pf in self.catalogs.species_form_profiles.items() if pf.species_id == profile.species_id}
        )
        if forms:
            lines.append(f"Available forms: {', '.join(str(v) for v in forms)}")

        level_pairs = sorted(profile.level_up_pairs, key=lambda row: (row[0], row[1].casefold()))
        level_moves = [f"Lv{lvl} {self._english_move_name_for_id(mid)}" for lvl, mid in level_pairs]
        lines.append(f"Level-up moves (this form): {self._dex_join_list(level_moves, limit=30)}")

        tutor_moves = [self._english_move_name_for_id(mid) for mid in profile.tutor_moves]
        egg_moves = [self._english_move_name_for_id(mid) for mid in profile.egg_moves]
        lines.append(f"Tutor moves (this form): {self._dex_join_list(tutor_moves, limit=30)}")
        lines.append(f"Egg moves (this form): {self._dex_join_list(egg_moves, limit=30)}")

        valid_moves = self.catalogs.valid_moves_for_species(profile.species_id, form=profile.form, include_pre_evolutions=True)
        relearn_moves = self.catalogs.valid_relearn_moves_for_species(profile.species_id, form=profile.form, include_pre_evolutions=True)
        direct_move_set = {
            self.catalogs.canonical_move_id(mid)
            for mid in (profile.level_up_moves + profile.tutor_moves + profile.egg_moves)
            if self.catalogs.canonical_move_id(mid)
        }
        inherited = [mid for mid in valid_moves if mid not in direct_move_set]
        inherited_names = [self._english_move_name_for_id(mid) for mid in inherited]
        lines.append(f"Legal moves incl. pre-evolutions: {len(valid_moves)}")
        lines.append(f"Relearn moves incl. pre-evolutions: {len(relearn_moves)}")
        if inherited_names:
            lines.append(f"Inherited from pre-evolution chain: {self._dex_join_list(inherited_names, limit=30)}")

        evo_text = self._species_evolution_description(profile.species_id, profile.form)
        lines.append("")
        lines.append(evo_text)
        return "\n".join(lines)

    def _dex_species_with_move(self, move_id: str) -> list[str]:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_move_id(move_id) or move_id
        out: list[str] = []
        seen: set[str] = set()
        for (_sid, _form), profile in self.catalogs.species_form_profiles.items():
            pool = profile.level_up_moves + profile.tutor_moves + profile.egg_moves
            has_move = False
            for raw in pool:
                mid = self.catalogs.canonical_move_id(raw)
                if mid == canonical:
                    has_move = True
                    break
            if not has_move:
                continue
            sid = profile.species_id
            if sid in seen:
                continue
            seen.add(sid)
            out.append(sid)
        out.sort(key=str.casefold)
        return out

    def _dex_move_details(self, move_id: str) -> str:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_move_id(move_id) or move_id
        move = self.catalogs.moves_by_id.get(canonical)
        if not move:
            return f"Move: {canonical}\n\nNo move data found."
        english_name = self._english_move_name_for_id(canonical)
        lines = [f"Move: {canonical} - {english_name}", f"Display name in data: {move.display_name or canonical}"]

        for key in ("Type", "Category", "Power", "Accuracy", "TotalPP", "Priority", "Target", "FunctionCode", "Flags"):
            value = str(move.extra.get(key, "")).strip()
            if value:
                lines.append(f"{key}: {value}")

        raw_desc = self.catalogs.move_description(canonical)
        summary = self._move_numeric_summary_lines(canonical, raw_desc, "")
        base_desc, summary = self._resolve_entity_description("move", canonical, raw_desc, summary)
        lines.append("")
        lines.append(base_desc or "No description available in current game data.")
        if summary:
            lines.append("")
            lines.append("Mechanics (Known):")
            lines.extend(f"- {line}" for line in summary)

        learners = self._dex_species_with_move(canonical)
        learner_labels = [self._english_species_name_for_id(sid) for sid in learners]
        lines.append("")
        lines.append(f"Species that can learn this move (any source): {len(learner_labels)}")
        lines.append(self._dex_join_list(learner_labels, limit=45))
        return "\n".join(lines)

    def _dex_item_details(self, item_id: str) -> str:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_item_id(item_id) or item_id
        item = self.catalogs.items_by_id.get(canonical)
        if not item:
            return f"Item: {canonical}\n\nNo item data found."
        english_name = self._english_item_name_for_id(canonical)
        lines = [f"Item: {canonical} - {english_name}", f"Display name in data: {item.display_name or canonical}"]

        pocket_raw = str(item.extra.get("Pocket", "")).strip()
        if pocket_raw:
            try:
                pidx = int(pocket_raw)
            except ValueError:
                pidx = -1
            if pidx >= 0:
                lines.append(f"Pocket: {pidx} - {EN_POCKET_NAMES.get(pidx, f'Pocket {pidx}')}")
            else:
                lines.append(f"Pocket: {pocket_raw}")
        for key in ("Price", "FieldUse", "BattleUse", "Flags"):
            value = str(item.extra.get(key, "")).strip()
            if value:
                lines.append(f"{key}: {value}")

        move_raw = str(item.extra.get("Move", "")).strip().lstrip(":")
        if move_raw:
            move_id = self.catalogs.canonical_move_id(move_raw) or move_raw
            lines.append(f"TM/HM Move: {move_id} - {self._english_move_name_for_id(move_id)}")

        raw_desc = self.catalogs.item_description(canonical)
        summary = self._item_numeric_summary_lines(canonical, raw_desc, "")
        base_desc, summary = self._resolve_entity_description("item", canonical, raw_desc, summary)
        lines.append("")
        lines.append(base_desc or "No description available in current game data.")
        if summary:
            lines.append("")
            lines.append("Mechanics (Known):")
            lines.extend(f"- {line}" for line in summary)
        return "\n".join(lines)

    def _dex_species_with_ability(self, ability_id: str) -> tuple[list[str], list[str]]:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_ability_id(ability_id) or ability_id
        normal: set[str] = set()
        hidden: set[str] = set()
        for (_sid, _form), profile in self.catalogs.species_form_profiles.items():
            sid = profile.species_id
            for raw in profile.ability_ids:
                aid = self.catalogs.canonical_ability_id(raw)
                if aid == canonical:
                    normal.add(sid)
            for raw in profile.hidden_ability_ids:
                aid = self.catalogs.canonical_ability_id(raw)
                if aid == canonical:
                    hidden.add(sid)
        normal_only = sorted((sid for sid in normal if sid not in hidden), key=str.casefold)
        hidden_sorted = sorted(hidden, key=str.casefold)
        return normal_only, hidden_sorted

    def _dex_ability_details(self, ability_id: str) -> str:
        assert self.catalogs is not None
        canonical = self.catalogs.canonical_ability_id(ability_id) or ability_id
        ability = self.catalogs.abilities_by_id.get(canonical)
        if not ability:
            return f"Ability: {canonical}\n\nNo ability data found."
        english_name = self._english_ability_name_for_id(canonical)
        lines = [f"Ability: {canonical} - {english_name}", f"Display name in data: {ability.display_name or canonical}"]
        raw_desc = self.catalogs.ability_description(canonical)
        summary = self._ability_numeric_summary_lines(canonical, raw_desc, "")
        base_desc, summary = self._resolve_entity_description("ability", canonical, raw_desc, summary)
        lines.append("")
        lines.append(base_desc or "No description available in current game data.")
        if summary:
            lines.append("")
            lines.append("Mechanics (Known):")
            lines.extend(f"- {line}" for line in summary)

        normal_species, hidden_species = self._dex_species_with_ability(canonical)
        normal_labels = [self._english_species_name_for_id(sid) for sid in normal_species]
        hidden_labels = [self._english_species_name_for_id(sid) for sid in hidden_species]
        lines.append("")
        lines.append(f"Species with this ability (normal slots): {len(normal_labels)}")
        lines.append(self._dex_join_list(normal_labels, limit=45))
        lines.append(f"Species with this ability (hidden slot): {len(hidden_labels)}")
        lines.append(self._dex_join_list(hidden_labels, limit=45))
        return "\n".join(lines)

    def _dex_nature_details(self, nature_id: str) -> str:
        nature = str(nature_id or "").strip().upper()
        if not nature:
            return "No nature selected."
        up, down = NATURE_EFFECTS.get(nature, (None, None))
        lines = [f"Nature: {nature}"]
        if not up or not down:
            lines.append("Effect: Neutral nature.")
            lines.append("Multiplier: all non-HP stats stay at 1.0x.")
        else:
            lines.append(f"Boosted stat: {STAT_SHORT_LABELS.get(up, up)} (x1.1)")
            lines.append(f"Lowered stat: {STAT_SHORT_LABELS.get(down, down)} (x0.9)")
            lines.append("Other non-HP stats: x1.0")
        lines.append("")
        lines.append(self._nature_description(nature))
        return "\n".join(lines)

    def _dex_species_with_type(self, type_id: str) -> list[str]:
        assert self.catalogs is not None
        target = str(type_id or "").strip().upper()
        if not target:
            return []
        out: set[str] = set()
        for sid, item in self.catalogs.species_by_id.items():
            raw_types = str(item.extra.get("Types", item.extra.get("Type", ""))).strip()
            if not raw_types:
                continue
            parts = [chunk.strip().lstrip(":").upper() for chunk in raw_types.split(",") if chunk.strip()]
            if target in parts:
                canonical = self.catalogs.canonical_species_id(sid) or sid
                out.add(canonical)
        return sorted(out, key=str.casefold)

    def _dex_type_details(self, type_id: str) -> str:
        assert self.catalogs is not None
        tid = str(type_id or "").strip().upper()
        if not tid:
            return "No type selected."
        display = self._type_display_name_for_id(tid)
        lines = [f"Type: {tid} - {self._type_display_name_for_id(tid)}", f"Display name in data: {display}"]

        if tid in self.catalogs.hidden_power_type_ids:
            idx = self.catalogs.hidden_power_type_ids.index(tid)
            lines.append(f"Hidden Power index order: {idx + 1}/{len(self.catalogs.hidden_power_type_ids)}")

        move_ids = [
            mid
            for mid, item in self.catalogs.moves_by_id.items()
            if str(item.extra.get("Type", "")).strip().lstrip(":").upper() == tid
        ]
        move_ids.sort(key=str.casefold)
        move_labels = [self._english_move_name_for_id(mid) for mid in move_ids]
        lines.append(f"Moves of this type: {len(move_labels)}")
        lines.append(self._dex_join_list(move_labels, limit=50))

        species_ids = self._dex_species_with_type(tid)
        species_labels = [self._english_species_name_for_id(sid) for sid in species_ids]
        lines.append("")
        lines.append(f"Species listed with this type in catalog: {len(species_labels)}")
        lines.append(self._dex_join_list(species_labels, limit=50))
        return "\n".join(lines)

    @staticmethod
    def _add_labeled_entry(parent, label, variable, row, col, readonly=False, width=28):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 6), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        try:
            parent.columnconfigure(col + 1, weight=1)
        except Exception:
            pass
        entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 16), pady=4)
        if readonly:
            entry.state(["readonly"])
        return entry

    def _register_description_widget(self, widget, panel: str, source: str, index: int | None = None):
        key = str(widget)
        self._desc_widget_context[key] = (panel, source, index)
        if str(source or "").strip().lower() == "species":
            return
        widget.bind(
            "<Enter>",
            lambda e, p=panel, s=source, i=index: self._on_description_hover(e, p, s, i),
            add="+",
        )
        widget.bind(
            "<FocusIn>",
            lambda e, p=panel, s=source, i=index: self._on_description_focus_in(e, p, s, i),
            add="+",
        )
        widget.bind(
            "<Button-1>",
            lambda e, p=panel, s=source, i=index: self._on_description_focus_in(e, p, s, i),
            add="+",
        )
        widget.bind("<FocusOut>", lambda _e, p=panel: self._on_description_focus_out(p), add="+")
        widget.bind(
            "<Leave>",
            lambda e, p=panel, s=source, i=index: self._on_description_leave(e, p, s, i),
            add="+",
        )

    def _sync_description_lock_from_clicked_widget(self, clicked):
        if clicked is None:
            self._desc_lock["party"] = None
            self._desc_lock["bag"] = None
            self._hide_party_tooltip()
            return
        clicked_name = str(clicked).lower()
        if "popdown" in clicked_name:
            return
        ctx = self._desc_widget_context.get(str(clicked))
        if ctx is None:
            self._desc_lock["party"] = None
            self._desc_lock["bag"] = None
            self._hide_party_tooltip()
            return
        panel, source, index = ctx
        self._desc_lock[panel] = (source, index)
        other = "bag" if panel == "party" else "party"
        self._desc_lock[other] = None
        if panel != "party":
            self._hide_party_tooltip()

    def _on_description_focus_in(self, event, panel: str, source: str, index: int | None = None):
        self._desc_lock[panel] = (source, index)
        if self._description_event_uses_searchable_picker(event):
            if panel == "party":
                if self._party_description_has_value(source, index):
                    self.update_party_description(source, index, force=True)
                self._hide_party_tooltip()
            elif panel == "bag":
                self.update_bag_description(source=source, force=True)
                self._hide_party_tooltip()
            return
        if panel == "party":
            if not self._party_description_has_value(source, index):
                self._hide_party_tooltip()
                return
            text = self.update_party_description(source, index, force=True)
            self._show_party_tooltip(text, event=event, widget=getattr(event, "widget", None))
        elif panel == "bag":
            self.update_bag_description(source=source, force=True)

    def _on_description_focus_out(self, panel: str):
        def _sync_after_focus_change():
            focused = self.root.focus_get()
            if focused is None:
                self._desc_lock[panel] = None
                if panel == "party":
                    self._hide_party_tooltip()
                return
            focused_name = str(focused).lower()
            if "popdown" in focused_name:
                return
            ctx = self._desc_widget_context.get(str(focused))
            if ctx is None or ctx[0] != panel:
                self._desc_lock[panel] = None
                if panel == "party":
                    self._hide_party_tooltip()

        self.root.after_idle(_sync_after_focus_change)

    def _on_description_hover(self, event, panel: str, source: str, index: int | None = None):
        lock = self._desc_lock.get(panel)
        if lock is not None and lock != (source, index):
            if panel == "party":
                self._hide_party_tooltip()
            return
        if self._description_event_uses_searchable_picker(event):
            if panel == "party":
                if self._party_description_has_value(source, index):
                    self.update_party_description(source, index, force=True)
                self._hide_party_tooltip()
            elif panel == "bag":
                self.update_bag_description(source=source, force=True)
                self._hide_party_tooltip()
            return
        if panel == "party":
            if not self._party_description_has_value(source, index):
                self._hide_party_tooltip()
                return
            text = self.update_party_description(source, index, force=True)
            self._show_party_tooltip(text, event=event, widget=getattr(event, "widget", None))
        elif panel == "bag":
            self.update_bag_description(source=source, force=True)

    def _on_description_leave(self, _event, panel: str, source: str, index: int | None = None):
        if panel != "party":
            return
        lock = self._desc_lock.get("party")
        if lock is None or lock != (source, index):
            self._hide_party_tooltip()

    def _party_description_has_value(self, source: str | None, index: int | None = None) -> bool:
        kind = str(source or "").strip().lower()
        if kind == "species":
            # Requested: do not show tooltip for Species in Party.
            return False
        try:
            if kind == "item":
                raw = self.pk_item_var.get().strip()
                return bool(self.resolve_selected_party_item_id(raw)) if raw else False
            if kind == "ability":
                return bool(self.resolve_selected_ability_id(self.pk_ability_var.get()))
            if kind == "nature":
                return bool(self.resolve_selected_nature_id(self.pk_nature_var.get()))
            if kind == "relearn":
                idx = index if index is not None else 0
                if 0 <= idx < len(self.relearn_move_vars):
                    return bool(self.resolve_selected_relearn_move_id(self.relearn_move_vars[idx].get()))
                return False
            if kind == "move":
                idx = index if index is not None else 0
                if 0 <= idx < len(self.move_id_vars):
                    return bool(self.resolve_selected_move_id(self.move_id_vars[idx].get()))
                return False
        except Exception:
            return False
        return False

    def _party_description_key(self, source: str, index: int | None = None) -> tuple[str, int | None, str, int]:
        kind = str(source or "").strip().lower()
        idx = index if kind in {"move", "relearn"} else None
        form = self._clamp_int(self.pk_form_var.get(), 0, 99, 0)
        try:
            if kind == "item":
                value = self.resolve_selected_party_item_id(self.pk_item_var.get()) or ""
            elif kind == "ability":
                value = self.resolve_selected_ability_id(self.pk_ability_var.get()) or ""
            elif kind == "nature":
                value = self.resolve_selected_nature_id(self.pk_nature_var.get()) or ""
            elif kind == "species":
                value = self.resolve_species_id(self.pk_species_var.get()) or ""
            elif kind == "relearn":
                i = idx if idx is not None else 0
                value = (
                    self.resolve_selected_relearn_move_id(self.relearn_move_vars[i].get())
                    if 0 <= i < len(self.relearn_move_vars)
                    else ""
                )
            else:
                i = idx if idx is not None else 0
                value = (
                    self.resolve_selected_move_id(self.move_id_vars[i].get())
                    if 0 <= i < len(self.move_id_vars)
                    else ""
                )
        except Exception:
            value = ""
        return kind, idx, str(value or "").strip(), int(form)

    def _set_combo_values(self, combo: ttk.Combobox, values: list[str]):
        key = str(combo)
        cleaned: list[str] = []
        seen: set[str] = set()
        for v in values:
            s = str(v)
            if not s or s in seen:
                continue
            cleaned.append(s)
            seen.add(s)
        self._combo_all_values[key] = cleaned
        self._combo_nav_index[key] = 0
        for cache_key in [cache_key for cache_key in self._combo_tooltip_text_cache if cache_key[0] == key]:
            self._combo_tooltip_text_cache.pop(cache_key, None)
        for cache_key in [cache_key for cache_key in self._combo_popup_fast_tooltip_cache if cache_key[0] == key]:
            self._combo_popup_fast_tooltip_cache.pop(cache_key, None)
        combo["values"] = cleaned

    def _enable_combo_search(self, combo: ttk.Combobox):
        combo.configure(state="normal")
        self._combo_search_widgets[str(combo)] = combo
        self._prepare_combo_popdown(combo)
        self._bind_combo_popdown_selection(combo)
        combo.bind("<KeyPress>", lambda e, cb=combo: self._on_combo_keypress(e, cb), add="+")
        combo.bind("<KeyRelease>", lambda e, cb=combo: self._on_combo_keyrelease(e, cb), add="+")
        combo.bind("<KeyRelease>", lambda _e, cb=combo: self._on_combo_tooltip_activity(cb), add="+")
        combo.bind("<Button-1>", lambda e, cb=combo: self._on_combo_buttonpress(e, cb), add="+")
        combo.bind("<ButtonRelease-1>", lambda e, cb=combo: self._on_combo_buttonrelease(e, cb), add="+")
        combo.bind("<FocusIn>", lambda _e, cb=combo: self._on_combo_tooltip_activity(cb), add="+")
        combo.bind("<FocusOut>", lambda _e, cb=combo: cb.after(120, lambda _cb=cb: self._on_combo_tooltip_focus_out(_cb)), add="+")
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _e, cb=combo: cb.after_idle(lambda _cb=cb: self._reset_combo_filter(_cb)),
            add="+",
        )
        combo.bind("<Escape>", lambda _e, cb=combo: self._on_combo_escape(cb), add="+")

    def _register_combo_tooltip_context(
        self,
        combo: ttk.Combobox,
        *,
        kind: str,
        label_to_id: dict[str, str] | None = None,
        resolver: Any = None,
    ):
        clean_kind = str(kind or "").strip().lower()
        if clean_kind == "species":
            self._combo_tooltip_context_by_name.pop(str(combo), None)
            return
        self._combo_tooltip_context_by_name[str(combo)] = {
            "kind": clean_kind,
            "label_to_id": label_to_id,
            "resolver": resolver,
        }
        for cache_key in [cache_key for cache_key in self._combo_tooltip_text_cache if cache_key[0] == str(combo)]:
            self._combo_tooltip_text_cache.pop(cache_key, None)
        for cache_key in [cache_key for cache_key in self._combo_popup_fast_tooltip_cache if cache_key[0] == str(combo)]:
            self._combo_popup_fast_tooltip_cache.pop(cache_key, None)

    def _on_combo_buttonpress(self, event, combo: ttk.Combobox):
        if self._combo_uses_searchable_tooltip_picker(combo):
            if self._combo_tooltip_popup is not None and self._combo_tooltip_popup_combo is combo and self._combo_arrow_hit(combo, event):
                self._hide_combo_tooltip_popup()
            else:
                self._show_combo_tooltip_popup(combo, show_initial_detail=False)
            try:
                combo.focus_set()
                combo.icursor(tk.END)
            except Exception:
                pass
            return "break"
        combo.after(1, lambda _cb=combo: self._on_combo_tooltip_activity(_cb))
        return None

    def _on_combo_buttonrelease(self, _event, combo: ttk.Combobox):
        if self._combo_uses_searchable_tooltip_picker(combo):
            return "break"
        return None

    def _combo_uses_searchable_tooltip_picker(self, combo: ttk.Combobox) -> bool:
        ctx = self._combo_context_for(combo)
        kind = str(ctx.get("kind", "") or "").strip().lower()
        return bool(kind and kind != "species")

    def _description_event_uses_searchable_picker(self, event) -> bool:
        widget = getattr(event, "widget", None)
        if widget is None:
            return False
        try:
            is_combo = isinstance(widget, ttk.Combobox)
        except Exception:
            is_combo = False
        if not is_combo:
            return False
        return self._combo_uses_searchable_tooltip_picker(widget)

    @staticmethod
    def _combo_arrow_hit(combo: ttk.Combobox, event) -> bool:
        try:
            part = str(combo.identify(int(getattr(event, "x", 0)), int(getattr(event, "y", 0))) or "").lower()
            if "arrow" in part:
                return True
        except Exception:
            pass
        try:
            return int(getattr(event, "x", 0)) >= int(combo.winfo_width()) - 24
        except Exception:
            return False

    def _combo_picker_filtered_values(self, combo: ttk.Combobox) -> list[str]:
        all_values = [str(v) for v in self._combo_all_values.get(str(combo), []) if str(v)]
        if not all_values:
            all_values = self._combo_filtered_values(combo)
        try:
            query = str(combo.get() or "").strip().casefold()
        except Exception:
            query = ""
        if not query:
            return all_values
        filtered = [v for v in all_values if query in v.casefold()]
        return filtered

    def _show_combo_tooltip_popup(
        self,
        combo: ttk.Combobox,
        values: list[str] | None = None,
        *,
        show_initial_detail: bool = False,
    ):
        if not self._combo_uses_searchable_tooltip_picker(combo):
            return
        if self._combo_tooltip_popup is not None and self._combo_tooltip_popup_combo is not combo:
            self._hide_combo_tooltip_popup()
        values = list(values) if values is not None else self._combo_picker_filtered_values(combo)
        if not values:
            values = [str(v) for v in self._combo_all_values.get(str(combo), []) if str(v)]
        if not values:
            return
        height = max(1, min(12, len(values)))
        popup = self._combo_tooltip_popup
        listbox = self._combo_tooltip_popup_listbox
        detail_label = self._combo_tooltip_popup_detail_label
        try:
            popup_exists = bool(popup is not None and popup.winfo_exists())
        except Exception:
            popup_exists = False
        if not popup_exists or listbox is None or detail_label is None:
            popup = tk.Toplevel(self.root)
            popup.wm_overrideredirect(True)
            try:
                popup.attributes("-topmost", True)
            except Exception:
                pass
            frame = ttk.Frame(popup, borderwidth=1, relief="solid")
            frame.pack(fill="both", expand=True)
            list_frame = ttk.Frame(frame)
            list_frame.grid(row=0, column=0, sticky="nsew")
            detail_frame = ttk.Frame(frame, padding=(8, 6))
            detail_frame.grid(row=0, column=1, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=0)
            frame.rowconfigure(0, weight=1)
            list_frame.columnconfigure(0, weight=1)
            list_frame.rowconfigure(0, weight=1)
            detail_frame.columnconfigure(0, weight=1)
            detail_frame.rowconfigure(0, weight=1)
            listbox = tk.Listbox(list_frame, height=height, exportselection=False, activestyle="dotbox")
            scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
            listbox.configure(yscrollcommand=scroll.set)
            listbox.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            detail_label = tk.Label(
                detail_frame,
                text="",
                justify="left",
                anchor="nw",
                bg="#fffde8",
                fg="#1f1f1f",
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("", 9),
                wraplength=460,
                width=58,
                height=12,
            )
            detail_label.grid(row=0, column=0, sticky="nsew")
            self._combo_tooltip_popup = popup
            self._combo_tooltip_popup_combo = combo
            self._combo_tooltip_popup_listbox = listbox
            self._combo_tooltip_popup_detail_label = detail_label

            listbox.bind("<Motion>", lambda ev, cb=combo, lb=listbox: self._on_combo_picker_motion(ev, cb, lb), add="+")
            listbox.bind("<Leave>", lambda _e: self._combo_picker_clear_detail(), add="+")
            listbox.bind("<ButtonRelease-1>", lambda ev, cb=combo, lb=listbox: self._on_combo_picker_select_event(ev, cb, lb), add="+")
            listbox.bind("<MouseWheel>", lambda e, listbox=listbox: self._on_combo_custom_popup_wheel(e, listbox), add="+")
            listbox.bind("<Button-4>", lambda e, listbox=listbox: self._on_combo_custom_popup_wheel(e, listbox), add="+")
            listbox.bind("<Button-5>", lambda e, listbox=listbox: self._on_combo_custom_popup_wheel(e, listbox), add="+")
            popup.bind("<Escape>", lambda _e: self._hide_combo_tooltip_popup(), add="+")
        else:
            self._combo_tooltip_popup_combo = combo
            try:
                listbox.configure(height=height)
            except Exception:
                pass
        self._hide_combo_context_tooltip()
        self._combo_tooltip_popup_values = values
        try:
            listbox.delete(0, tk.END)
            if values:
                listbox.insert(tk.END, *values)
        except Exception:
            return
        current = str(combo.get() or "").strip()
        if current in values:
            idx = values.index(current)
        else:
            idx = 0
        self._combo_picker_highlight(combo, idx, show_detail=bool(show_initial_detail and current in values and current))
        try:
            x = int(combo.winfo_rootx())
            y = int(combo.winfo_rooty() + combo.winfo_height())
            width = max(int(combo.winfo_width()) + 500, 640)
        except Exception:
            x = int(self.root.winfo_pointerx())
            y = int(self.root.winfo_pointery())
            width = 640
        popup.wm_geometry(f"{width}x{max(220, height * 22 + 16)}+{x}+{y}")
        try:
            popup.deiconify()
            popup.lift()
        except Exception:
            pass

    def _combo_picker_label_at_event(self, listbox: tk.Listbox | None, event) -> tuple[str, int | None]:
        if listbox is None:
            return "", None
        try:
            x_local = int(getattr(event, "x", 0))
            y_local = int(getattr(event, "y", 0))
            idx = int(listbox.index(f"@{x_local},{y_local}"))
            size = int(listbox.size())
        except Exception:
            return "", None
        if idx < 0 or idx >= size:
            return "", None
        try:
            bbox = listbox.bbox(idx)
        except Exception:
            bbox = None
        if bbox is not None:
            try:
                row_top = int(bbox[1])
                row_height = max(1, int(bbox[3]))
                if y_local < row_top or y_local > row_top + row_height:
                    return "", None
            except Exception:
                pass
        try:
            return str(listbox.get(idx)).strip(), idx
        except Exception:
            return "", None

    def _combo_picker_detail_text(self, combo: ttk.Combobox, label: str) -> str:
        clean_label = str(label or "").strip()
        if not clean_label:
            return ""
        cache_key = (str(combo), clean_label)
        cached = self._combo_tooltip_text_cache.get(cache_key)
        if cached is not None:
            _tooltip_kind, text = cached
            return str(text or "").strip()
        text = self._combo_popup_fast_tooltip_cache.get(cache_key)
        if text is None:
            text = self._fast_combo_popup_tooltip_text(combo, clean_label)
            if text:
                self._combo_popup_fast_tooltip_cache[cache_key] = text
        tooltip_kind = "party"
        if not text:
            tooltip_kind, text = self._tooltip_text_for_combo_label(combo, clean_label)
        if text:
            self._combo_tooltip_text_cache[cache_key] = (tooltip_kind, text)
        return str(text or "").strip()

    def _combo_picker_set_detail(self, combo: ttk.Combobox, label: str):
        detail_label = self._combo_tooltip_popup_detail_label
        if detail_label is None:
            return
        text = self._combo_picker_detail_text(combo, label)
        try:
            detail_label.configure(text=text or "")
        except Exception:
            pass

    def _combo_picker_clear_detail(self):
        self._combo_tooltip_last_key = None
        detail_label = self._combo_tooltip_popup_detail_label
        if detail_label is not None:
            try:
                detail_label.configure(text="")
            except Exception:
                pass

    def _combo_picker_highlight(self, combo: ttk.Combobox, index: int, *, show_detail: bool):
        listbox = self._combo_tooltip_popup_listbox
        if listbox is None:
            return
        try:
            size = int(listbox.size())
        except Exception:
            size = 0
        if size <= 0:
            self._combo_picker_clear_detail()
            return
        idx = max(0, min(int(index or 0), size - 1))
        try:
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(idx)
            listbox.activate(idx)
            listbox.see(idx)
        except Exception:
            pass
        self._combo_nav_index[str(combo)] = idx
        if not show_detail:
            return
        try:
            label = str(listbox.get(idx)).strip()
        except Exception:
            label = ""
        if not label:
            self._combo_picker_clear_detail()
            return
        key = (str(combo), label)
        if key != self._combo_tooltip_last_key:
            self._combo_tooltip_last_key = key
            self._combo_picker_set_detail(combo, label)

    def _on_combo_picker_motion(self, event, combo: ttk.Combobox, listbox: tk.Listbox):
        label, idx = self._combo_picker_label_at_event(listbox, event)
        if idx is None or not label:
            self._combo_picker_clear_detail()
            return
        self._combo_picker_highlight(combo, idx, show_detail=True)

    def _on_combo_picker_select_event(self, event, combo: ttk.Combobox, listbox: tk.Listbox):
        label, idx = self._combo_picker_label_at_event(listbox, event)
        if not label:
            label, idx = self._combo_picker_selected_label()
        if label:
            self._hide_combo_tooltip_popup()
            self._commit_combo_listbox_selection(combo, label, idx)
        return "break"

    def _combo_picker_selected_label(self) -> tuple[str, int | None]:
        listbox = self._combo_tooltip_popup_listbox
        if listbox is None:
            return "", None
        try:
            sels = listbox.curselection()
            if sels:
                idx = int(sels[0])
                return str(listbox.get(idx)).strip(), idx
        except Exception:
            pass
        try:
            idx = int(listbox.index("active"))
            return str(listbox.get(idx)).strip(), idx
        except Exception:
            return "", None

    def _is_widget_inside_combo_tooltip_popup(self, widget) -> bool:
        popup = self._combo_tooltip_popup
        combo = self._combo_tooltip_popup_combo
        if popup is None or widget is None:
            return False
        if widget is combo:
            return True
        current = widget
        while current is not None:
            if current is popup:
                return True
            try:
                current = current.master
            except Exception:
                break
        return False

    def _hide_combo_tooltip_popup(self):
        popup = self._combo_tooltip_popup
        self._combo_tooltip_popup = None
        self._combo_tooltip_popup_combo = None
        self._combo_tooltip_popup_listbox = None
        self._combo_tooltip_popup_detail_label = None
        self._combo_tooltip_popup_values = []
        self._hide_combo_context_tooltip()
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass

    def _on_combo_custom_popup_wheel(self, event, listbox):
        return self._on_combo_popdown_listbox_wheel(event, listbox)

    def _schedule_combo_popup_tooltip_prewarm(
        self,
        combo: ttk.Combobox,
        popup: tk.Toplevel,
        values: list[str],
        *,
        start_index: int,
        visible_count: int,
    ):
        if not values:
            return
        size = len(values)
        start = max(0, min(int(start_index or 0), size - 1))
        visible = max(1, int(visible_count or 1))
        priority: list[int] = []
        for idx in range(start, min(size, start + visible * 2)):
            priority.append(idx)
        for idx in range(max(0, start - visible), start):
            priority.append(idx)
        remaining = [idx for idx in range(size) if idx not in set(priority)]
        order = priority + remaining

        def _prewarm(pos: int = 0):
            if self._combo_tooltip_popup is not popup:
                return
            try:
                if popup is None or not bool(popup.winfo_exists()):
                    return
            except Exception:
                return
            end = min(len(order), pos + 4)
            for order_idx in range(pos, end):
                idx = order[order_idx]
                try:
                    label = str(values[idx]).strip()
                except Exception:
                    label = ""
                if not label:
                    continue
                cache_key = (str(combo), label)
                if cache_key in self._combo_popup_fast_tooltip_cache:
                    continue
                text = self._fast_combo_popup_tooltip_text(combo, label)
                if text:
                    self._combo_popup_fast_tooltip_cache[cache_key] = text
            if end < len(order):
                try:
                    self.root.after(5, lambda: _prewarm(end))
                except Exception:
                    pass

        try:
            self.root.after(10, _prewarm)
        except Exception:
            pass

    def _show_combo_popup_fast_tooltip(self, combo: ttk.Combobox, label: str, x_root: int, y_root: int):
        cache_key = (str(combo), str(label or "").strip())
        text = self._combo_popup_fast_tooltip_cache.get(cache_key)
        if text is None:
            text = self._fast_combo_popup_tooltip_text(combo, label)
            if text:
                self._combo_popup_fast_tooltip_cache[cache_key] = text
        if not text:
            self._hide_combo_context_tooltip()
            return
        self._hide_custom_effect_tooltip()
        self._show_party_tooltip_at(text, int(x_root), int(y_root))

    def _fast_combo_popup_tooltip_text(self, combo: ttk.Combobox, label: str) -> str:
        ctx = self._combo_context_for(combo)
        kind = str(ctx.get("kind", "") or "").strip().lower()
        if not kind:
            return ""
        entity_id = self._resolve_combo_context_id(combo, label, ctx)
        if not entity_id:
            return ""
        if kind.startswith("custom_effect_"):
            effect_kind = kind.replace("custom_effect_", "", 1)
            name = self._custom_effect_name_for_id(effect_kind, entity_id)
            desc = ""
            if effect_kind == "item":
                item_key = str(entity_id or "").strip().lstrip(":").upper()
                if item_key in self._custom_manifest_item_specs():
                    desc = self._custom_manifest_item_description_text(item_key)
                elif self.catalogs:
                    desc = self.catalogs.item_description(item_key)
                    desc = self._english_name_from_translation_file("ITEM_DESCRIPTIONS.txt", desc) or desc
            elif effect_kind == "move" and self.catalogs:
                desc = self.catalogs.move_description(entity_id)
                desc = self._english_name_from_translation_file("MOVE_DESCRIPTIONS.txt", desc) or desc
            elif effect_kind == "ability" and self.catalogs:
                desc = self.catalogs.ability_description(entity_id)
                desc = self._english_name_from_translation_file("ABILITY_DESCRIPTIONS.txt", desc) or desc
            parts = [str(name or entity_id).strip()]
            body = str(desc or "").strip()
            if body and body.casefold() != str(name or "").strip().casefold():
                parts.extend(["", body])
            elif not body:
                parts.extend(["", "No description available."])
            return "\n".join(parts)
        if kind == "custom_pool_effect":
            effect = self._custom_pool_effect_defs_by_id.get(str(entity_id).strip().upper(), {})
            if not isinstance(effect, dict):
                return ""
            display = str(effect.get("display_name", "") or "").strip()
            desc = str(effect.get("description", "") or "").strip()
            status = str(effect.get("support_status", "") or "").strip()
            parts = [f"Effect: {entity_id}"]
            if display:
                parts.append(display)
            if desc and desc.casefold() != display.casefold():
                parts.extend(["", desc])
            if status:
                parts.extend(["", f"Status: {status}"])
            return "\n".join(parts)
        if kind == "item":
            item_key = str(entity_id or "").strip().lstrip(":").upper()
            if item_key in self._custom_manifest_item_specs():
                body = self._custom_manifest_item_description_text(item_key)
            else:
                body = self.catalogs.item_description(entity_id) if self.catalogs else ""
                body = self._english_name_from_translation_file("ITEM_DESCRIPTIONS.txt", body) or body
            return f"Item: {entity_id}\n\n{str(body or '').strip() or 'No description available.'}"
        if kind == "ability":
            body = self.catalogs.ability_description(entity_id) if self.catalogs else ""
            body = self._english_name_from_translation_file("ABILITY_DESCRIPTIONS.txt", body) or body
            return f"Ability: {entity_id}\n\n{str(body or '').strip() or 'No description available.'}"
        if kind in {"move", "relearn"}:
            body = self.catalogs.move_description(entity_id) if self.catalogs else ""
            body = self._english_name_from_translation_file("MOVE_DESCRIPTIONS.txt", body) or body
            return f"Move: {entity_id}\n\n{str(body or '').strip() or 'No description available.'}"
        if kind == "nature":
            return f"Nature: {entity_id}\n\n{self._nature_description(entity_id) or 'No description available.'}"
        if kind == "species":
            lines: list[str] = []
            if self.catalogs:
                base = self.catalogs.base_stats_for_species(entity_id, form=0)
                if base:
                    lines.append(
                        f"Base stats: HP {base.get('HP', 0)}, Atk {base.get('ATTACK', 0)}, Def {base.get('DEFENSE', 0)}, "
                        f"SpA {base.get('SPECIAL_ATTACK', 0)}, SpD {base.get('SPECIAL_DEFENSE', 0)}, Spe {base.get('SPEED', 0)}."
                    )
            return f"Species: {entity_id}\n\n{chr(10).join(lines) if lines else 'No description available.'}"
        return ""

    def _prepare_combo_popdown(self, combo: ttk.Combobox):
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
            listbox_widget = f"{popdown}.f.l"
            # Keep typing focus on combobox entry while dropdown is shown.
            # This prevents key input from randomly jumping to listbox selection.
            combo.tk.call("bind", listbox_widget, "<Map>", "break")
        except tk.TclError:
            pass

    def _ensure_combo_popdown_tooltip_tcl(self, combo: ttk.Combobox):
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
            listbox_widget = f"{popdown}.f.l"
        except tk.TclError:
            return
        self._bind_combo_popdown_tooltip_tcl(combo, listbox_widget, force=True)

    def _bind_combo_popdown_tooltip_tcl(self, combo: ttk.Combobox, listbox_widget: str, *, force: bool):
        key = str(combo)
        bind_key = (key, str(listbox_widget))
        if not force and bind_key in self._combo_popdown_tcl_tooltip_bound:
            return
        self._combo_popdown_tcl_tooltip_bound.add(bind_key)

        scripts = self._combo_popdown_tcl_tooltip_scripts.get(bind_key)
        if scripts is None:
            motion_cmd = self.root.register(
                lambda x, y, x_root, y_root, cb_key=key, lb_path=listbox_widget: self._on_combo_popdown_tcl_motion(
                    cb_key,
                    lb_path,
                    x,
                    y,
                    x_root,
                    y_root,
                )
            )
            hide_cmd = self.root.register(lambda cb_key=key: self._on_combo_popdown_tcl_hide(cb_key))
            self._combo_popdown_tcl_tooltip_scripts[bind_key] = (motion_cmd, hide_cmd)
            self._combo_popdown_tcl_tooltip_commands.extend([motion_cmd, hide_cmd])
        else:
            motion_cmd, hide_cmd = scripts
        try:
            motion_binding = str(combo.tk.call("bind", listbox_widget, "<Motion>") or "")
            if motion_cmd not in motion_binding:
                combo.tk.call("bind", listbox_widget, "<Motion>", f"+{motion_cmd} %x %y %X %Y")
            for sequence in ("<Leave>", "<Unmap>", "<ButtonPress>"):
                binding = str(combo.tk.call("bind", listbox_widget, sequence) or "")
                if hide_cmd not in binding:
                    combo.tk.call("bind", listbox_widget, sequence, f"+{hide_cmd}")
        except tk.TclError:
            pass

    def _bind_combo_popdown_selection(self, combo: ttk.Combobox):
        key = str(combo)
        if key in self._combo_popdown_bound:
            return
        lb = self._combo_listbox_widget(combo)
        if lb is None:
            return
        self._combo_popdown_bound.add(key)
        lb.bind(
            "<Return>",
            lambda e, cb=combo: self._on_combo_popdown_return(e, cb),
            add="+",
        )
        lb.bind(
            "<MouseWheel>",
            lambda e, listbox=lb: self._on_combo_popdown_listbox_wheel(e, listbox),
            add="+",
        )
        lb.bind(
            "<Button-4>",
            lambda e, listbox=lb: self._on_combo_popdown_listbox_wheel(e, listbox),
            add="+",
        )
        lb.bind(
            "<Button-5>",
            lambda e, listbox=lb: self._on_combo_popdown_listbox_wheel(e, listbox),
            add="+",
        )
        lb.bind("<Unmap>", lambda _e, cb=combo: self._stop_combo_tooltip_poll(cb), add="+")
        lb.bind("<ButtonPress>", lambda _e, cb=combo: self._hide_combo_context_tooltip(), add="+")

    @staticmethod
    def _on_combo_popdown_listbox_wheel(event, listbox):
        steps = 0
        num = getattr(event, "num", None)
        if num == 4:
            steps = -1
        elif num == 5:
            steps = 1
        else:
            try:
                delta = int(getattr(event, "delta", 0))
            except Exception:
                delta = 0
            if delta > 0:
                steps = -max(1, abs(delta) // 120)
            elif delta < 0:
                steps = max(1, abs(delta) // 120)
        if steps == 0:
            return "break"
        try:
            listbox.yview_scroll(steps, "units")
        except Exception:
            pass
        return "break"

    def _on_combo_popdown_mouse_release(self, event, combo: ttk.Combobox):
        lb = self._combo_listbox_widget(combo)
        if lb is None:
            lb = getattr(event, "widget", None)
        idx: int | None = None
        try:
            if lb is not None:
                # Prefer actual pointer position relative to listbox to avoid stale/incorrect event.y
                # when popdown internals forward events from nested widgets.
                try:
                    pointer_y = int(lb.winfo_pointery())
                    root_y = int(lb.winfo_rooty())
                    y = pointer_y - root_y
                except Exception:
                    y = int(getattr(event, "y", 0))
                nearest = int(lb.nearest(y))
                if nearest >= 0:
                    idx = nearest
                    try:
                        lb.selection_clear(0, tk.END)
                        lb.selection_set(nearest)
                        lb.activate(nearest)
                        lb.see(nearest)
                    except Exception:
                        pass
        except Exception:
            idx = None
        if idx is not None:
            self._combo_nav_index[str(combo)] = max(0, int(idx))
        # Keep default ttk click-selection behavior to avoid stale-value overrides.
        return None

    def _on_combo_popdown_return(self, _event, combo: ttk.Combobox):
        lb = self._combo_listbox_widget(combo)
        selected = ""
        idx: int | None = None
        if lb is not None:
            try:
                sels = lb.curselection()
            except Exception:
                sels = ()
            if sels:
                try:
                    idx = int(sels[0])
                    selected = str(lb.get(idx)).strip()
                except Exception:
                    selected = ""
                    idx = None
        if selected:
            self._commit_combo_listbox_selection(combo, selected, idx)
        return "break"

    def _commit_combo_listbox_selection(
        self,
        combo: ttk.Combobox,
        selected: str = "",
        selected_index: int | None = None,
    ):
        self._stop_combo_tooltip_poll(combo)
        selected_text = str(selected or "").strip()
        idx = selected_index if isinstance(selected_index, int) else None
        if not selected_text:
            lb = self._combo_listbox_widget(combo)
            if lb is None:
                return
            try:
                sels = lb.curselection()
            except Exception:
                sels = ()
            if not sels:
                return
            try:
                idx = int(sels[0])
            except Exception:
                return
            try:
                selected_text = str(lb.get(idx)).strip()
            except Exception:
                selected_text = ""
        if not selected_text:
            return
        if idx is None:
            values = self._combo_filtered_values(combo)
            try:
                idx = values.index(selected_text)
            except ValueError:
                idx = 0
            except Exception:
                idx = 0
        lb = self._combo_listbox_widget(combo)
        combo.delete(0, tk.END)
        combo.insert(0, selected_text)
        combo.icursor(tk.END)
        self._combo_nav_index[str(combo)] = max(0, int(idx))
        try:
            combo.tk.call("ttk::combobox::Unpost", str(combo))
        except tk.TclError:
            pass
        try:
            combo.event_generate("<<ComboboxSelected>>")
        except Exception:
            return

    def _on_combo_escape(self, combo: ttk.Combobox):
        self._hide_combo_tooltip_popup()
        self._stop_combo_tooltip_poll(combo)
        self._reset_combo_filter(combo)
        try:
            combo.tk.call("ttk::combobox::Unpost", str(combo))
        except tk.TclError:
            pass

    def _reset_combo_filter(self, combo: ttk.Combobox):
        selected_text = combo.get()
        all_values = self._combo_all_values.get(str(combo), [])
        combo["values"] = all_values
        if selected_text:
            try:
                combo.delete(0, tk.END)
                combo.insert(0, selected_text)
                combo.icursor(tk.END)
            except Exception:
                pass
            try:
                self._combo_nav_index[str(combo)] = max(0, all_values.index(selected_text))
            except Exception:
                self._combo_nav_index[str(combo)] = 0

    @staticmethod
    def _combo_filtered_values(combo: ttk.Combobox) -> list[str]:
        try:
            values = list(combo.cget("values"))
        except Exception:
            values = []
        return [str(v) for v in values if str(v)]

    @staticmethod
    def _combo_listbox_widget(combo: ttk.Combobox):
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
            listbox_widget = f"{popdown}.f.l"
            return combo.nametowidget(listbox_widget)
        except Exception:
            return None

    @staticmethod
    def _is_combo_popdown_open(combo: ttk.Combobox) -> bool:
        try:
            popdown = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
            return int(combo.tk.call("winfo", "viewable", popdown)) == 1
        except Exception:
            return False

    def _find_active_combo_popdown_listbox(self):
        for key, combo in list(self._combo_search_widgets.items()):
            try:
                if combo is None or not bool(combo.winfo_exists()):
                    self._combo_search_widgets.pop(key, None)
                    continue
            except Exception:
                self._combo_search_widgets.pop(key, None)
                continue
            try:
                popdown = combo.tk.call("ttk::combobox::PopdownWindow", str(combo))
                # "viewable" is more reliable than widget mapping checks for ttk popdown.
                if int(combo.tk.call("winfo", "viewable", popdown)) != 1:
                    continue
            except Exception:
                continue
            try:
                return self.root.nametowidget(f"{popdown}.f.l")
            except Exception:
                try:
                    return combo.nametowidget(f"{popdown}.f.l")
                except Exception:
                    continue
        return None

    @staticmethod
    def _listbox_label_under_pointer(listbox, event) -> str:
        if listbox is None:
            return ""
        try:
            size = int(listbox.size())
        except Exception:
            size = 0
        if size <= 0:
            return ""
        try:
            y = int(getattr(event, "y", 0))
            idx = int(listbox.nearest(y))
        except Exception:
            return ""
        if idx < 0 or idx >= size:
            return ""
        try:
            bbox = listbox.bbox(idx)
        except Exception:
            bbox = None
        if bbox is not None:
            try:
                row_top = int(bbox[1])
                row_height = max(1, int(bbox[3]))
                if y < row_top or y > (row_top + row_height):
                    return ""
            except Exception:
                pass
        try:
            return str(listbox.get(idx)).strip()
        except Exception:
            return ""

    def _combo_context_for(self, combo: ttk.Combobox) -> dict[str, Any]:
        ctx = self._combo_tooltip_context_by_name.get(str(combo), {})
        if isinstance(ctx, dict) and ctx:
            return ctx
        kind = str(self._custom_effect_combo_kind_by_name.get(str(combo), "") or "").strip().lower()
        if kind in {"item", "move", "ability"}:
            return {"kind": f"custom_effect_{kind}"}
        desc_ctx = self._desc_widget_context.get(str(combo))
        if desc_ctx is not None:
            panel, source, index = desc_ctx
            if str(source or "").strip().lower() == "species":
                return {}
            return {"kind": str(source or ""), "panel": panel, "index": index}
        return {}

    def _resolve_combo_context_id(self, combo: ttk.Combobox, label: str, ctx: dict[str, Any]) -> str:
        raw = str(label or "").strip()
        if not raw:
            return ""
        label_to_id = ctx.get("label_to_id")
        if isinstance(label_to_id, dict) and raw in label_to_id:
            return str(label_to_id.get(raw, "") or "").strip()
        resolver = ctx.get("resolver")
        if callable(resolver):
            try:
                resolved = resolver(raw)
                if resolved:
                    return str(resolved).strip()
            except Exception:
                pass
        kind = str(ctx.get("kind", "") or "").strip().lower()
        if kind == "custom_effect_item":
            return self._custom_effect_id_from_label("item", raw)
        if kind == "custom_effect_move":
            return self._custom_effect_id_from_label("move", raw)
        if kind == "custom_effect_ability":
            return self._custom_effect_id_from_label("ability", raw)
        if kind == "custom_pool_effect":
            return self._custom_pool_effect_label_to_id.get(raw, extract_internal_id(raw).strip().upper())
        try:
            if kind == "item":
                return self.resolve_selected_party_item_id(raw) or self._team_resolve_selected_item_id(raw) or self._damage_resolve_selected_item_id(raw) or self.resolve_item_id(raw)
            if kind == "ability":
                return self.resolve_selected_ability_id(raw) or self._team_resolve_selected_ability_id(raw) or self._damage_resolve_selected_ability_id("attacker", raw) or self.resolve_ability_id(raw)
            if kind in {"move", "relearn"}:
                return self.resolve_selected_move_id(raw) or self.resolve_selected_relearn_move_id(raw) or self._team_resolve_selected_move_id(raw) or self._damage_resolve_selected_move_id("attacker", raw) or self.resolve_move_id(raw)
            if kind == "nature":
                return self.resolve_selected_nature_id(raw) or self._team_resolve_selected_nature_id(raw) or self._damage_resolve_selected_nature_id(raw)
            if kind == "species":
                return self.resolve_species_id(raw)
        except Exception:
            return ""
        return ""

    def _tooltip_text_for_combo_label(self, combo: ttk.Combobox, label: str) -> tuple[str, str]:
        ctx = self._combo_context_for(combo)
        kind = str(ctx.get("kind", "") or "").strip().lower()
        if not kind:
            return "", ""
        entity_id = self._resolve_combo_context_id(combo, label, ctx)
        if not entity_id:
            return "", ""
        if kind.startswith("custom_effect_"):
            effect_kind = kind.replace("custom_effect_", "", 1)
            return "custom", self._custom_effect_tooltip_text(effect_kind, entity_id)
        if kind == "custom_pool_effect":
            effect = self._custom_pool_effect_defs_by_id.get(str(entity_id).strip().upper(), {})
            if not isinstance(effect, dict):
                return "", ""
            title = f"Effect: {entity_id}"
            display = str(effect.get("display_name", "") or "").strip()
            desc = str(effect.get("description", "") or "").strip()
            hook = str(effect.get("hook", "") or "").strip()
            template = str(effect.get("template", "") or "").strip()
            status = str(effect.get("support_status", "") or "").strip()
            parts = [title]
            if display:
                parts.append(display)
            body = desc if desc and desc.casefold() != display.casefold() else ""
            meta = ", ".join(x for x in [f"hook={hook}" if hook else "", f"template={template}" if template else "", f"status={status}" if status else ""] if x)
            if body:
                parts.extend(["", body])
            if meta:
                parts.extend(["", meta])
            return "custom", "\n".join(parts)
        if kind == "item":
            item_key = str(entity_id or "").strip().lstrip(":").upper()
            if item_key in self._custom_manifest_item_specs():
                body = self._custom_manifest_item_description_text(item_key)
            else:
                raw_desc = self.catalogs.item_description(entity_id) if self.catalogs else ""
                summary = self._item_numeric_summary_lines(entity_id, raw_desc, "")
                base_desc, summary = self._resolve_entity_description("item", entity_id, raw_desc, summary)
                body = self._append_mechanics_block(base_desc, summary)
            return "party", f"Item: {entity_id}\n\n{str(body or '').strip() or 'No description available.'}"
        if kind == "ability":
            raw_desc = self.catalogs.ability_description(entity_id) if self.catalogs else ""
            summary = self._ability_numeric_summary_lines(entity_id, raw_desc, "")
            base_desc, summary = self._resolve_entity_description("ability", entity_id, raw_desc, summary)
            body = self._append_mechanics_block(base_desc, summary)
            return "party", f"Ability: {entity_id}\n\n{str(body or '').strip() or 'No description available.'}"
        if kind in {"move", "relearn"}:
            raw_desc = self.catalogs.move_description(entity_id) if self.catalogs else ""
            summary = self._move_numeric_summary_lines(entity_id, raw_desc, "")
            base_desc, summary = self._resolve_entity_description("move", entity_id, raw_desc, summary)
            body = self._append_mechanics_block(base_desc, summary)
            return "party", f"Move: {entity_id}\n\n{str(body or '').strip() or 'No description available.'}"
        if kind == "nature":
            return "party", f"Nature: {entity_id}\n\n{self._nature_description(entity_id) or 'No description available.'}"
        if kind == "species":
            lines: list[str] = []
            if self.catalogs:
                base = self.catalogs.base_stats_for_species(entity_id, form=0)
                if base:
                    lines.append(
                        f"Base stats: HP {base.get('HP', 0)}, Atk {base.get('ATTACK', 0)}, Def {base.get('DEFENSE', 0)}, "
                        f"SpA {base.get('SPECIAL_ATTACK', 0)}, SpD {base.get('SPECIAL_DEFENSE', 0)}, Spe {base.get('SPEED', 0)}."
                    )
            return "party", f"Species: {entity_id}\n\n{chr(10).join(lines) if lines else 'No description available.'}"
        return "", ""

    def _show_combo_context_tooltip(
        self,
        combo: ttk.Combobox,
        label: str,
        event: Any = None,
        x_root: int | None = None,
        y_root: int | None = None,
        use_cache: bool = False,
    ):
        if self._combo_uses_searchable_tooltip_picker(combo):
            self._hide_combo_context_tooltip()
            return
        cache_key = (str(combo), str(label or "").strip())
        cached = self._combo_tooltip_text_cache.get(cache_key) if use_cache else None
        if cached is not None:
            tooltip_kind, text = cached
        else:
            tooltip_kind, text = self._tooltip_text_for_combo_label(combo, label)
            if use_cache and text:
                self._combo_tooltip_text_cache[cache_key] = (tooltip_kind, text)
        if not text:
            self._hide_combo_context_tooltip()
            return
        if tooltip_kind == "custom":
            self._hide_party_tooltip()
            if x_root is not None and y_root is not None:
                x = int(x_root)
                y = int(y_root)
            elif event is not None:
                x = int(getattr(event, "x_root", 0))
                y = int(getattr(event, "y_root", 0))
            else:
                try:
                    x = int(combo.winfo_rootx() + combo.winfo_width())
                    y = int(combo.winfo_rooty())
                except Exception:
                    x = y = 0
            self._show_custom_effect_tooltip(text, x, y)
        else:
            self._hide_custom_effect_tooltip()
            if x_root is not None and y_root is not None:
                self._show_party_tooltip_at(text, int(x_root), int(y_root))
            else:
                self._show_party_tooltip(text, event=event, widget=combo)

    def _show_party_tooltip_at(self, text: str, x_root: int, y_root: int):
        self._show_party_tooltip(text, event=None, widget=None)
        tip = self._party_tooltip_window
        if tip is None:
            return
        try:
            tip.wm_geometry(f"+{int(x_root) + 12}+{int(y_root) + 14}")
            tip.deiconify()
            tip.lift()
        except Exception:
            pass

    def _hide_combo_context_tooltip(self):
        self._combo_tooltip_last_key = None
        self._hide_custom_effect_tooltip()
        self._hide_party_tooltip()

    def _on_combo_tooltip_activity(self, combo: ttk.Combobox):
        if self._combo_uses_searchable_tooltip_picker(combo):
            return
        self._start_combo_tooltip_poll(combo)

    def _on_combo_popdown_tcl_hide(self, combo_key: str = ""):
        if not combo_key or self._combo_tooltip_last_key is None or self._combo_tooltip_last_key[0] == combo_key:
            self._hide_combo_context_tooltip()
        return ""

    def _on_combo_popdown_tcl_motion(
        self,
        combo_key: str,
        listbox_path: str,
        x: str,
        y: str,
        x_root: str,
        y_root: str,
    ):
        combo = self._combo_search_widgets.get(str(combo_key))
        if combo is None or not self._combo_context_for(combo) or self._combo_uses_searchable_tooltip_picker(combo):
            self._hide_combo_context_tooltip()
            return ""
        try:
            lb = self.root.nametowidget(str(listbox_path))
        except Exception:
            try:
                lb = combo.nametowidget(str(listbox_path))
            except Exception:
                return ""
        try:
            y_int = int(float(y))
            idx = int(lb.nearest(y_int))
            size = int(lb.size())
        except Exception:
            return ""
        if idx < 0 or idx >= size:
            self._hide_combo_context_tooltip()
            return ""
        try:
            bbox = lb.bbox(idx)
        except Exception:
            bbox = None
        if bbox is not None:
            try:
                row_top = int(bbox[1])
                row_height = max(1, int(bbox[3]))
                if y_int < row_top or y_int > row_top + row_height:
                    self._hide_combo_context_tooltip()
                    return ""
            except Exception:
                pass
        try:
            label = str(lb.get(idx)).strip()
        except Exception:
            label = ""
        if not label:
            self._hide_combo_context_tooltip()
            return ""
        key = (str(combo), label)
        if key != self._combo_tooltip_last_key:
            self._combo_tooltip_last_key = key
            try:
                xr = int(float(x_root))
                yr = int(float(y_root))
            except Exception:
                xr = int(self.root.winfo_pointerx())
                yr = int(self.root.winfo_pointery())
            self._show_combo_context_tooltip(combo, label, x_root=xr, y_root=yr)
        return ""

    def _start_combo_tooltip_poll(self, combo: ttk.Combobox):
        if self._combo_uses_searchable_tooltip_picker(combo) or not self._combo_context_for(combo):
            self._hide_combo_context_tooltip()
            return
        self._combo_tooltip_poll_combo = combo
        if self._combo_tooltip_poll_after_id:
            return
        self._combo_tooltip_poll_after_id = self.root.after(80, self._poll_combo_tooltip)

    def _on_combo_tooltip_focus_out(self, combo: ttk.Combobox):
        if self._combo_uses_searchable_tooltip_picker(combo):
            self._stop_combo_tooltip_poll(combo)
            return
        if self._is_combo_popdown_open(combo):
            self._start_combo_tooltip_poll(combo)
            return
        self._stop_combo_tooltip_poll(combo)

    def _stop_combo_tooltip_poll(self, combo: ttk.Combobox | None = None):
        if combo is None or self._combo_tooltip_poll_combo is combo:
            after_id = self._combo_tooltip_poll_after_id
            self._combo_tooltip_poll_after_id = None
            self._combo_tooltip_poll_combo = None
            if after_id:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
        self._hide_combo_context_tooltip()

    def _poll_combo_tooltip(self):
        self._combo_tooltip_poll_after_id = None
        combo = self._combo_tooltip_poll_combo
        if combo is None:
            self._hide_combo_context_tooltip()
            return
        try:
            exists = bool(combo.winfo_exists())
        except Exception:
            exists = False
        if not exists:
            self._stop_combo_tooltip_poll(combo)
            return
        try:
            has_focus = combo.focus_get() is combo
        except Exception:
            has_focus = False
        popdown_open = self._is_combo_popdown_open(combo)
        if not has_focus and not popdown_open:
            self._stop_combo_tooltip_poll(combo)
            return
        shown = False
        if popdown_open:
            shown = self._poll_combo_popdown_row_tooltip(combo)
        if not shown and has_focus:
            shown = self._poll_combo_typed_text_tooltip(combo)
        if not shown:
            self._hide_combo_context_tooltip()
        self._combo_tooltip_poll_after_id = self.root.after(120, self._poll_combo_tooltip)

    def _poll_combo_popdown_row_tooltip(self, combo: ttk.Combobox) -> bool:
        lb = self._combo_listbox_widget(combo)
        if lb is None:
            return False
        try:
            x_root = int(lb.winfo_pointerx())
            y_root = int(lb.winfo_pointery())
            left = int(lb.winfo_rootx())
            top = int(lb.winfo_rooty())
            width = int(lb.winfo_width())
            height = int(lb.winfo_height())
        except Exception:
            return False
        if x_root < left or x_root >= left + width or y_root < top or y_root >= top + height:
            return False
        y = y_root - top
        try:
            size = int(lb.size())
            idx = int(lb.nearest(y))
        except Exception:
            return False
        if idx < 0 or idx >= size:
            return False
        try:
            bbox = lb.bbox(idx)
        except Exception:
            bbox = None
        if bbox is not None:
            try:
                row_top = int(bbox[1])
                row_height = max(1, int(bbox[3]))
                if y < row_top or y > row_top + row_height:
                    return False
            except Exception:
                pass
        try:
            label = str(lb.get(idx)).strip()
        except Exception:
            label = ""
        if not label:
            return False
        key = (str(combo), label)
        if key != self._combo_tooltip_last_key:
            self._combo_tooltip_last_key = key
            self._show_combo_context_tooltip(combo, label, x_root=x_root, y_root=y_root)
        return True

    def _poll_combo_typed_text_tooltip(self, combo: ttk.Combobox) -> bool:
        try:
            raw = str(combo.get() or "").strip()
        except Exception:
            raw = ""
        if not raw:
            return False
        try:
            values = {str(v).strip() for v in combo.cget("values")}
        except Exception:
            values = set()
        if raw not in values:
            return False
        key = (str(combo), raw)
        if key != self._combo_tooltip_last_key:
            self._combo_tooltip_last_key = key
            try:
                x_root = int(combo.winfo_rootx() + combo.winfo_width())
                y_root = int(combo.winfo_rooty())
            except Exception:
                x_root = int(self.root.winfo_pointerx())
                y_root = int(self.root.winfo_pointery())
            self._show_combo_context_tooltip(combo, raw, x_root=x_root, y_root=y_root)
        return True

    def _sync_combo_highlight(self, combo: ttk.Combobox, index: int):
        values = self._combo_filtered_values(combo)
        if not values:
            return
        idx = max(0, min(int(index), len(values) - 1))
        self._combo_nav_index[str(combo)] = idx
        lb = self._combo_listbox_widget(combo)
        if lb is None:
            return
        try:
            lb.selection_clear(0, tk.END)
            lb.selection_set(idx)
            lb.activate(idx)
            lb.see(idx)
        except Exception:
            return

    def _on_combo_keypress(self, event, combo: ttk.Combobox):
        key = str(event.keysym or "")
        if key not in {"Up", "Down", "Return", "KP_Enter"}:
            return

        if self._combo_uses_searchable_tooltip_picker(combo):
            values = self._combo_picker_filtered_values(combo)
            if not values:
                return "break"
            if self._combo_tooltip_popup is None or self._combo_tooltip_popup_combo is not combo:
                self._show_combo_tooltip_popup(combo, values)
            if key in {"Up", "Down"}:
                current_idx = self._combo_nav_index.get(str(combo), 0)
                delta = -1 if key == "Up" else 1
                next_idx = max(0, min(int(current_idx) + delta, len(values) - 1))
                self._combo_picker_highlight(combo, next_idx, show_detail=True)
                return "break"
            selected, idx = self._combo_picker_selected_label()
            if not selected:
                raw = str(combo.get() or "").strip()
                if raw in values:
                    selected = raw
                    idx = values.index(raw)
                else:
                    selected = values[max(0, min(self._combo_nav_index.get(str(combo), 0), len(values) - 1))]
                    idx = values.index(selected)
            self._hide_combo_tooltip_popup()
            self._commit_combo_listbox_selection(combo, selected, idx)
            return "break"

        values = self._combo_filtered_values(combo)
        if not values:
            all_values = self._combo_all_values.get(str(combo), [])
            if all_values:
                combo["values"] = all_values
                values = [str(v) for v in all_values]
        if not values:
            return "break"

        current_text = combo.get().strip()
        current_idx = self._combo_nav_index.get(str(combo), 0)
        if current_text in values:
            current_idx = values.index(current_text)
        elif current_text:
            query = current_text.casefold()
            for i, val in enumerate(values):
                if query in val.casefold():
                    current_idx = i
                    break
        current_idx = max(0, min(current_idx, len(values) - 1))

        if key in {"Up", "Down"}:
            delta = -1 if key == "Up" else 1
            next_idx = max(0, min(current_idx + delta, len(values) - 1))
            selected = values[next_idx]
            combo.delete(0, tk.END)
            combo.insert(0, selected)
            combo.icursor(tk.END)
            self._post_combo_dropdown(combo)
            self._sync_combo_highlight(combo, next_idx)
            return "break"

        # Enter confirms the highlighted/current row.
        chosen_idx = current_idx
        if current_text and current_text in values:
            chosen_idx = values.index(current_text)
        selected = values[chosen_idx]
        combo.delete(0, tk.END)
        combo.insert(0, selected)
        combo.icursor(tk.END)
        self._sync_combo_highlight(combo, chosen_idx)
        try:
            combo.tk.call("ttk::combobox::Unpost", str(combo))
        except tk.TclError:
            pass
        try:
            combo.event_generate("<<ComboboxSelected>>")
        except Exception:
            pass
        return "break"

    def _on_combo_keyrelease(self, event, combo: ttk.Combobox):
        if event.keysym in {
            "Up", "Down", "Left", "Right", "Return", "Tab",
            "Shift_L", "Shift_R", "Control_L", "Control_R",
            "Alt_L", "Alt_R", "Escape", "Home", "End", "Prior", "Next",
        }:
            return
        all_values = self._combo_all_values.get(str(combo), [])
        if not all_values:
            return
        original_text = combo.get()
        query = original_text.strip().casefold()
        if not query:
            filtered = all_values
        else:
            filtered = [v for v in all_values if query in v.casefold()]
        combo["values"] = filtered
        self._combo_nav_index[str(combo)] = 0
        if combo.get() != original_text:
            combo.delete(0, tk.END)
            combo.insert(0, original_text)
        combo.icursor(tk.END)
        if self._combo_uses_searchable_tooltip_picker(combo):
            if filtered:
                exact_match = bool(original_text.strip() and original_text.strip() in filtered)
                self._show_combo_tooltip_popup(combo, filtered, show_initial_detail=exact_match)
            else:
                self._hide_combo_tooltip_popup()
            return "break"
        if filtered:
            self._post_combo_dropdown(combo)
        else:
            try:
                combo.tk.call("ttk::combobox::Unpost", str(combo))
            except tk.TclError:
                pass

    @staticmethod
    def _post_combo_dropdown(combo: ttk.Combobox):
        try:
            combo.tk.call("ttk::combobox::Post", str(combo))
            combo.focus_set()
            combo.icursor(tk.END)
        except tk.TclError:
            pass

    # ------------------------- Mapper/Profile lock -------------------------
    def _reload_profile_lock(self):
        self.profile_lock_warning = None
        if probe_mapper is None:
            self.profile_lock_data = None
            self.profile_lock_warning = "Probe mapper module is unavailable."
            return
        try:
            self.profile_lock_data = probe_mapper.load_profile(self.profile_lock_path)
        except Exception as exc:  # noqa: BLE001
            self.profile_lock_data = None
            self.profile_lock_warning = str(exc)

    def _candidate_probe_save_path(self, preferred: Path | None = None) -> Path | None:
        if preferred and Path(preferred).exists():
            return Path(preferred)
        if self.save_path and self.save_path.exists():
            return self.save_path
        chosen = self.save_var.get().strip()
        if chosen:
            path = Path(chosen)
            if path.exists():
                return path
        return None

    def _pick_probe_save_path(self, initial: Path | None = None) -> Path | None:
        initial_dir = ""
        if initial is not None:
            try:
                initial_dir = str(Path(initial).resolve().parent)
            except Exception:
                initial_dir = ""
        if not initial_dir:
            initial_dir = str(core.default_save_dir())
        picked = filedialog.askopenfilename(
            title="Select Save File For Mapping",
            initialdir=initial_dir,
            filetypes=[("RGSS Save", "*.rxdata"), ("All files", "*.*")],
        )
        if not picked:
            return None
        return Path(picked).resolve()

    def _choose_probe_save_for_wizard(self) -> Path | None:
        current = self._candidate_probe_save_path()
        current_text = str(current) if current is not None else "(none)"
        choice = messagebox.askyesnocancel(
            "Map Game Data",
            (
                "Map Game Data creates/updates the profile lock for the selected game folder.\n"
                "This prevents wrong save/game mapping.\n\n"
                f"Current game root:\n{self.game_root}\n\n"
                f"Current save candidate:\n{current_text}\n\n"
                "Yes = Use current save candidate\n"
                "No = Choose another save file\n"
                "Cancel = Abort"
            ),
        )
        if choice is None:
            return None
        if choice:
            if current is not None and current.exists():
                return current
            messagebox.showinfo(
                "Save File Required",
                "Current save candidate is missing. Please choose a save file to continue mapping.",
            )
        return self._pick_probe_save_path(initial=current)

    def _run_profile_mapper(self, preferred_save: Path | None = None, show_success: bool = True) -> bool:
        if probe_mapper is None:
            messagebox.showerror(
                "Mapper Unavailable",
                "pokemon_indigo_probe_mapper.py is missing or failed to load.",
            )
            return False
        save_path = self._candidate_probe_save_path(preferred_save)
        if save_path is None:
            save_path = self._pick_probe_save_path(initial=preferred_save)
            if save_path is None:
                return False
        try:
            profile = probe_mapper.run_probe(
                game_root=self.game_root,
                save_path=save_path,
                profile_path=self.profile_lock_path,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Mapper Error", f"Could not run mapper/probe:\n{exc}")
            return False
        try:
            self._remember_current_game_root()
            self._remember_last_save_path(save_path)
        except Exception:
            pass
        self.profile_lock_data = profile
        self.profile_lock_warning = None
        self.set_status(f"Profile lock mapped from {save_path.name}.")
        if show_success:
            messagebox.showinfo(
                "Mapper Completed",
                f"Profile lock updated:\n{self.profile_lock_path}\n\nSave used:\n{save_path}",
            )
        return True

    def run_game_probe_wizard(self):
        selected = self._choose_probe_save_for_wizard()
        if selected is None:
            return
        self._run_profile_mapper(preferred_save=selected, show_success=True)

    def probe_patch_capability(self):
        if patch_capability is None:
            messagebox.showerror(
                "Capability Probe Unavailable",
                "pokemon_indigo_patch_capability.py is missing or failed to load.",
            )
            return
        try:
            profile = patch_capability.probe_patch_capability(self.game_root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Capability Probe Error", str(exc))
            return
        levels = profile.get("patch_levels", {})
        profile_path = str(profile.get("profile_path", "")).strip() or str(
            patch_capability.default_capability_path(self.game_root)
        )
        messagebox.showinfo(
            "Patch Capability Probe",
            (
                f"Capability profile updated:\n{profile_path}\n\n"
                f"Level A (metadata item patch): {bool(levels.get('A_metadata_item_data'))}\n"
                f"Level B (clone existing effects): {bool(levels.get('B_clone_existing_effects'))}\n"
                f"Level C (ruby injection): {bool(levels.get('C_ruby_injection'))}"
            ),
        )
        self.set_status("Patch capability profile updated.")

    def rebuild_patch_adapter(self):
        if patch_capability is None:
            messagebox.showerror(
                "Adapter Builder Unavailable",
                "pokemon_indigo_patch_capability.py is missing or failed to load.",
            )
            return
        try:
            adapter = patch_capability.rebuild_patch_adapter(self.game_root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rebuild Adapter Error", str(exc))
            return
        adapter_path = str(adapter.get("adapter_path", "")).strip() or str(
            patch_capability.default_adapter_path(self.game_root)
        )
        messagebox.showinfo(
            "Patch Adapter Rebuilt",
            (
                f"Adapter written:\n{adapter_path}\n\n"
                f"Adapter ID: {adapter.get('adapter_id', 'unknown')}\n"
                f"Mode: {adapter.get('strategies', {}).get('ruby_injection', {}).get('mode', 'unknown')}"
            ),
        )
        self.set_status("Patch adapter rebuilt.")

    def manage_battle_overlay(self):
        if battle_overlay_patcher is None:
            messagebox.showerror(
                "Battle Overlay Unavailable",
                "battle_overlay_patcher.py is missing or failed to load.",
            )
            return

        win = tk.Toplevel(self.root)
        win.title("Battle Overlay")
        win.geometry("760x430")
        win.transient(self.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        text = tk.Text(win, wrap="word", height=18)
        text.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=(8, 4))
        text.configure(yscrollcommand=scroll.set)

        btns = ttk.Frame(win)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
        status_var = tk.StringVar(value="")
        ttk.Label(btns, textvariable=status_var).pack(side="left", fill="x", expand=True)

        def set_report(report: str):
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", report)
            text.configure(state="disabled")

        def refresh_report():
            try:
                status = battle_overlay_patcher.inspect_overlay_status(self.game_root)
                report = battle_overlay_patcher.format_status_report(status)
            except Exception as exc:  # noqa: BLE001
                report = f"Battle Overlay inspect failed:\n{exc}"
                status_var.set("Inspect failed.")
            else:
                status_var.set("Overlay status refreshed.")
            set_report(report)

        def apply_overlay():
            try:
                status = battle_overlay_patcher.inspect_overlay_status(self.game_root)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Battle Overlay Inspect Failed", str(exc), parent=win)
                return
            if not status.get("can_apply"):
                messagebox.showwarning(
                    "Battle Overlay Unsupported",
                    (
                        "This game root does not have a safe overlay install adapter yet.\n\n"
                        f"{status.get('reason', '')}"
                    ),
                    parent=win,
                )
                refresh_report()
                return
            if not messagebox.askyesno(
                "Apply Battle Overlay",
                (
                    "Install or update the in-game battle overlay runtime patch?\n\n"
                    f"Adapter: {status.get('adapter', 'unknown')}\n"
                    f"Target: {status.get('target_path', '(unknown)')}\n\n"
                    "A timestamped backup will be created before Scripts.rxdata is changed.\n"
                    "No save data, items.dat, moves.dat, abilities.dat, or custom item manifest will be modified."
                ),
                parent=win,
            ):
                return
            try:
                result = battle_overlay_patcher.apply_battle_overlay(self.game_root)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Battle Overlay Apply Failed", str(exc), parent=win)
                return
            set_report(battle_overlay_patcher.format_status_report(result))
            if result.get("changed"):
                status_var.set("Battle overlay applied. Launch/restart game to test it.")
                self.set_status("Battle overlay applied.")
            else:
                status_var.set("Battle overlay is already current.")
                self.set_status("Battle overlay already current.")

        def remove_overlay():
            try:
                status = battle_overlay_patcher.inspect_overlay_status(self.game_root)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Battle Overlay Inspect Failed", str(exc), parent=win)
                return
            if not status.get("active"):
                messagebox.showinfo("Battle Overlay", "Battle overlay is not installed.", parent=win)
                refresh_report()
                return
            if not messagebox.askyesno(
                "Remove Battle Overlay",
                (
                    "Remove the in-game battle overlay runtime patch?\n\n"
                    f"Target: {status.get('target_path', '(unknown)')}\n\n"
                    "A timestamped backup will be created before Scripts.rxdata is changed."
                ),
                parent=win,
            ):
                return
            try:
                result = battle_overlay_patcher.remove_battle_overlay(self.game_root)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Battle Overlay Remove Failed", str(exc), parent=win)
                return
            set_report(battle_overlay_patcher.format_status_report(result))
            status_var.set("Battle overlay removed.")
            self.set_status("Battle overlay removed.")

        ttk.Button(btns, text="Refresh", command=refresh_report).pack(side="right", padx=2)
        ttk.Button(btns, text="Apply/Update", command=apply_overlay).pack(side="right", padx=2)
        ttk.Button(btns, text="Remove", command=remove_overlay).pack(side="right", padx=2)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right", padx=2)

        refresh_report()

    def _remap_after_game_data_change_prompt(self, action_name: str):
        self._reload_profile_lock()
        should_map = messagebox.askyesno(
            "Remap Recommended",
            (
                f"{action_name} changed game scripts.\n\n"
                "To keep save/game mapping valid, run 'Map Game Data' now."
            ),
        )
        if not should_map:
            self.set_status(f"{action_name} completed. Run 'Map Game Data' before loading/saving.")
            return
        selected = self._choose_probe_save_for_wizard()
        if selected is None:
            self.set_status(f"{action_name} completed. Mapping skipped by user.")
            return
        self._run_profile_mapper(preferred_save=selected, show_success=True)

    def apply_ev_unlock_patch(self):
        if ev_patcher is None:
            messagebox.showerror(
                "EV Patcher Unavailable",
                "pokemon_indigo_ev_patcher.py is missing or failed to load.",
            )
            return
        try:
            status = ev_patcher.inspect_patch_status(self.game_root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("EV Patch Error", f"Could not inspect game scripts:\n{exc}")
            return
        current = status.get("current_ev_limit")
        target = status.get("target_ev_limit", 1512)
        source_type = str(status.get("source_type", "")).strip() or "unknown"
        target_path = str(status.get("target_path", "")).strip() or "(not detected)"
        if current is None:
            current_text = "unknown"
        else:
            current_text = str(current)
        if not messagebox.askyesno(
            "Apply EV Patch",
            (
                "This will patch the detected game script target to allow a higher total EV cap.\n\n"
                f"Source: {source_type}\n"
                f"Target file: {target_path}\n"
                f"Current EV_LIMIT: {current_text}\n"
                f"Target EV_LIMIT: {target}\n\n"
                "A backup file will be created automatically.\n"
                "Continue?"
            ),
        ):
            return
        try:
            result = ev_patcher.apply_ev_patch(self.game_root, target_ev_limit=int(target))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("EV Patch Failed", str(exc))
            return
        if not result.get("changed", False):
            messagebox.showinfo(
                "EV Patch",
                f"EV patch already active.\nCurrent EV_LIMIT: {result.get('current_ev_limit', 'unknown')}",
            )
            self.set_status("EV patch already active.")
            return
        backup_path = str(result.get("backup_path", "")).strip()
        messagebox.showinfo(
            "EV Patch Applied",
            (
                f"Patch applied successfully.\n\n"
                f"Source: {result.get('source_type', source_type)}\n"
                f"Target file: {result.get('target_path', target_path)}\n"
                f"EV_LIMIT: {result.get('current_ev_limit', 'unknown')}\n"
                f"Backup: {backup_path or '(not reported)'}"
            ),
        )
        self._remap_after_game_data_change_prompt("EV patch")

    def rollback_ev_unlock_patch(self):
        if ev_patcher is None:
            messagebox.showerror(
                "EV Patcher Unavailable",
                "pokemon_indigo_ev_patcher.py is missing or failed to load.",
            )
            return
        try:
            status = ev_patcher.inspect_patch_status(self.game_root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rollback Error", f"Could not inspect game scripts:\n{exc}")
            return
        target_path = str(status.get("target_path", "")).strip() or "(not detected)"
        source_type = str(status.get("source_type", "")).strip() or "unknown"
        if not messagebox.askyesno(
            "Rollback EV Patch",
            (
                "Rollback will restore the detected patch target from EV patch backup.\n\n"
                f"Source: {source_type}\n"
                f"Target file: {target_path}\n\n"
                "Continue?"
            ),
        ):
            return
        try:
            result = ev_patcher.rollback_ev_patch(self.game_root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rollback Failed", str(exc))
            return
        messagebox.showinfo(
            "Rollback Completed",
            (
                f"Scripts restored from:\n{result.get('restored_from_backup', '(unknown)')}\n\n"
                f"Target file: {result.get('target_path', target_path)}\n"
                f"Current EV_LIMIT: {result.get('current_ev_limit', 'unknown')}"
            ),
        )
        self._remap_after_game_data_change_prompt("EV patch rollback")

    def _ensure_profile_lock(self, save_path: Path | None, interactive: bool = True) -> bool:
        if probe_mapper is None:
            if interactive:
                messagebox.showerror(
                    "Mapper Unavailable",
                    "pokemon_indigo_probe_mapper.py is missing or failed to load.",
                )
            return False
        if self.profile_lock_data is None:
            self._reload_profile_lock()
        ok, reason, _details = probe_mapper.verify_profile_data(
            self.profile_lock_data,
            self.game_root,
            save_path=save_path,
        )
        if ok:
            return True
        if not interactive:
            return False
        should_map = messagebox.askyesno(
            "Profile Lock Required",
            (
                f"{reason}\n\n"
                "To avoid wrong game/save mapping, this editor requires a fresh profile lock.\n"
                "Run mapper now?"
            ),
        )
        if not should_map:
            self.set_status("Blocked: profile lock is missing/outdated.")
            return False
        if not self._run_profile_mapper(preferred_save=save_path, show_success=False):
            self.set_status("Blocked: mapper did not complete.")
            return False
        ok2, reason2, _details2 = probe_mapper.verify_profile_data(
            self.profile_lock_data,
            self.game_root,
            save_path=save_path,
        )
        if not ok2:
            messagebox.showerror("Profile Check Failed", reason2)
            self.set_status("Blocked: profile check failed.")
            return False
        self.set_status("Profile lock check passed.")
        return True

    # ------------------------- Core actions -------------------------
    def _schedule_status_title_poll(self):
        if self._status_title_poll_after_id is not None:
            return
        try:
            self._status_title_poll_after_id = self.root.after(500, self._poll_status_title_timeout)
        except Exception:
            self._status_title_poll_after_id = None

    def _poll_status_title_timeout(self):
        self._status_title_poll_after_id = None
        try:
            if self._status_title_visible_until and time.monotonic() >= self._status_title_visible_until:
                self._status_title_visible_until = 0.0
                self.root.title(self._base_window_title)
        except Exception:
            return
        self._schedule_status_title_poll()

    def set_status(self, text: str):
        suffix = " (modified)" if self.modified else ""
        status_text = f"{str(text or '').strip()}{suffix}".strip()
        self.status_var.set(status_text)
        title = self._base_window_title
        if status_text:
            compact = " ".join(status_text.split())
            title = f"{self._base_window_title} - {compact}"
            self._status_title_visible_until = time.monotonic() + (self._status_title_timeout_ms / 1000.0)
        else:
            self._status_title_visible_until = 0.0
        try:
            self.root.title(title)
        except Exception:
            pass
        self._schedule_status_title_poll()

    def mark_modified(self):
        self.modified = True
        self.save_btn.state(["!disabled"])
        self.set_status("Save loaded.")

    def refresh_save_list(self):
        self._reload_profile_lock()
        try:
            files = core.list_save_files(core.default_save_dir())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Error", f"Cannot read save folder: {exc}")
            return
        values = [str(p) for p in files]
        remembered = str(self.app_settings.get("last_save_path", "")).strip()
        if remembered:
            try:
                remembered_path = str(Path(remembered).expanduser().resolve())
                if Path(remembered_path).exists() and remembered_path not in values:
                    values.insert(0, remembered_path)
            except Exception:
                pass
        self.save_combo["values"] = values
        if values and not self.save_var.get():
            self.save_var.set(values[0])
        notes: list[str] = []
        notes.append(f"Game root: {self.game_root}")
        if self.catalog_error:
            notes.append(f"Catalog warning: {self.catalog_error}")
        if probe_mapper is None:
            notes.append("Mapper module unavailable.")
        elif self.profile_lock_data is None:
            notes.append("No profile lock yet (click 'Map Game Data').")
        elif self.profile_lock_warning:
            notes.append(f"Profile lock warning: {self.profile_lock_warning}")
        if notes:
            self.set_status(f"Save list refreshed. {' '.join(notes)}")
        else:
            self.set_status("Save list refreshed.")

    def browse_save(self):
        picked = filedialog.askopenfilename(
            title="Select Save File",
            filetypes=[("RGSS Save", "*.rxdata"), ("All files", "*.*")],
        )
        if picked:
            self.save_var.set(picked)
            try:
                self._remember_last_save_path(Path(picked))
            except Exception:
                pass

    def load_selected_save(self):
        chosen = self.save_var.get().strip()
        if not chosen:
            messagebox.showwarning("No Save", "Please select a save file.")
            return
        path = Path(chosen)
        if not path.exists():
            messagebox.showerror("Missing File", f"File not found:\n{path}")
            return
        if not self._ensure_profile_lock(path, interactive=True):
            return
        try:
            self.save_data = core.load_save(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Load Error", f"Could not load save:\n{exc}")
            return
        self.save_path = path
        self._remember_last_save_path(path)
        self.modified = False
        self.save_btn.state(["!disabled"])
        issues = core.sanity_check_save_data(self.save_data)
        if issues:
            issue_text = "\n".join(f"- {x}" for x in issues)
            messagebox.showwarning(
                "Save Warning",
                "Loaded save appears corrupted or inconsistent:\n\n"
                f"{issue_text}\n\n"
                "You should restore from an older backup before editing.",
            )
        normalized_count, unresolved_ids = self.normalize_known_ids()
        if normalized_count > 0:
            self.modified = True
            self.save_btn.state(["!disabled"])
            msg = (
                f"Normalized {normalized_count} ID field(s) to canonical game IDs.\n"
                "Click 'Save Changes' to permanently write this fix to the save file."
            )
            if unresolved_ids:
                sample = ", ".join(unresolved_ids[:6])
                msg += f"\n\nUnresolved unknown IDs (sample): {sample}"
            messagebox.showinfo("ID Normalized", msg)
        self.refresh_all_tabs()
        self.set_status(f"Loaded {path.name}")

    def _create_save_backup_snapshot(self) -> Path | None:
        if self.save_path is None:
            return None
        source = Path(self.save_path)
        if not source.exists():
            return None
        # High-resolution suffix avoids collisions for rapid consecutive saves.
        suffix_ns = time.time_ns() % 1_000_000_000
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{suffix_ns:09d}"
        backup_path = source.with_name(f"{source.name}.apply-{stamp}.bak")
        shutil.copy2(source, backup_path)
        return backup_path

    def write_save(self):
        if self.save_data is None or self.save_path is None:
            messagebox.showwarning("No Save", "No save loaded.")
            return
        if not self._ensure_profile_lock(self.save_path, interactive=True):
            return
        normalized_count = 0
        unresolved_ids: list[str] = []
        pre_backup: Path | None = None
        backup: Path | None = None
        try:
            pre_backup = self._create_save_backup_snapshot()
            normalized_count, unresolved_ids = self.normalize_known_ids()
            backup = core.save_save(self.save_path, self.save_data, make_backup=True)
            issues = core.validate_save_file(self.save_path)
            if issues:
                if backup and Path(backup).exists():
                    shutil.copy2(backup, self.save_path)
                issue_text = "\n".join(f"- {x}" for x in issues)
                raise ValueError(
                    "Saved file failed sanity check and was reverted from backup.\n"
                    f"{issue_text}"
                )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save Error", f"Could not save file:\n{exc}")
            return
        self.modified = False
        self.set_status(f"Saved {self.save_path.name}")
        msg = f"Saved:\n{self.save_path}"
        if pre_backup:
            msg += f"\n\nPre-save backup:\n{pre_backup}"
        if backup:
            msg += f"\n\nBackup:\n{backup}"
        if normalized_count:
            msg += f"\n\nNormalized IDs before save: {normalized_count}"
        if unresolved_ids:
            sample = ", ".join(unresolved_ids[:6])
            msg += f"\nUnresolved unknown IDs (sample): {sample}"
        messagebox.showinfo("Saved", msg)

    def refresh_all_tabs(self):
        self.refresh_trainer_tab()
        self.refresh_party_tab()
        self.refresh_team_tab()
        self.refresh_bag_list()
        if hasattr(self, "switch_index_var"):
            self.load_switch()
        if hasattr(self, "var_index_var"):
            self.load_variable()
        adv_output = getattr(self, "adv_output", None)
        if adv_output is not None:
            adv_output.delete("1.0", "end")

    # ------------------------- Trainer tab -------------------------
    def refresh_trainer_tab(self):
        player = self.get_player()
        if not player:
            return
        self.trainer_name_var.set(symbol_name(core.read_attr(player, "@name", "")))
        self.trainer_id_var.set(str(core.read_attr(player, "@id", "")))
        self.trainer_type_var.set(symbol_name(core.read_attr(player, "@trainer_type", "")))
        self.money_var.set(str(core.read_attr(player, "@money", 0)))
        self.coins_var.set(str(core.read_attr(player, "@coins", 0)))
        self.bp_var.set(str(core.read_attr(player, "@battle_points", 0)))
        self.save_slot_var.set(symbol_name(core.read_attr(player, "@save_slot", "")))

        badges = core.read_attr(player, "@badges", [])
        if isinstance(badges, list):
            for i, b in enumerate(self.badge_vars):
                if i < len(badges):
                    b.set(bool(badges[i]))
                else:
                    b.set(False)

    def apply_trainer_changes(self):
        player = self.get_player()
        if not player:
            return
        try:
            player.attributes["@name"] = self.trainer_name_var.get().strip()
            if "@trainer_type" in player.attributes:
                player.attributes["@trainer_type"] = to_symbol_or_none(self.trainer_type_var.get())
            if "@money" in player.attributes:
                player.attributes["@money"] = parse_int(self.money_var.get(), "Money")
            if "@coins" in player.attributes:
                player.attributes["@coins"] = parse_int(self.coins_var.get(), "Coins")
            if "@battle_points" in player.attributes:
                player.attributes["@battle_points"] = parse_int(self.bp_var.get(), "Battle Points")
            if "@save_slot" in player.attributes:
                player.attributes["@save_slot"] = self.save_slot_var.get().strip()

            badges = core.read_attr(player, "@badges", [])
            if isinstance(badges, list):
                needed = max(len(badges), len(self.badge_vars))
                if len(badges) < needed:
                    badges.extend([False] * (needed - len(badges)))
                for i, var in enumerate(self.badge_vars):
                    badges[i] = bool(var.get())
                player.attributes["@badges"] = badges
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Apply Error", str(exc))
            return
        self.mark_modified()
        self.set_status("Trainer changes applied.")

    # ------------------------- Party tab -------------------------
    def refresh_party_tab(self):
        self._refresh_party_box_controls()
        self._party_selected_mode = None
        self._party_selected_index = None
        self._party_selected_box_index = None
        self._clear_party_detail_fields()
        self.party_slot_status_var.set("Right-click a slot for View/Set.")
        self._render_party_slot_grid()
        self.update_party_editor_preview()
        self.update_party_evolution_chart()

    def _selected_slot_entry(self) -> tuple[Any, str]:
        if self._party_selected_mode is None or self._party_selected_index is None:
            return None, ""
        idx = self._party_selected_index
        if self._party_selected_mode == "party":
            player = self.get_root_key("player")
            party = core.read_attr(player, "@party", []) if isinstance(player, core.RubyObject) else []
            if not isinstance(party, list):
                return None, f"Party {idx + 1}"
            if idx >= len(party):
                return None, f"Party {idx + 1}"
            return party[idx], f"Party {idx + 1}"
        boxes = self._get_storage_boxes()
        box_idx = self._party_selected_box_index if self._party_selected_box_index is not None else self._selected_box_index()
        if box_idx < 0 or box_idx >= len(boxes):
            return None, f"Box ? Slot {idx + 1}"
        box_name = self._box_display_name(boxes[box_idx], box_idx)
        box_data = self._get_box_pokemon_list(boxes[box_idx])
        if idx >= len(box_data):
            return None, f"{box_name} Slot {idx + 1}"
        return box_data[idx], f"{box_name} Slot {idx + 1}"

    def select_party_slot(self, idx: int):
        _entries, _rows, _cols, mode, box_idx = self._party_slot_cells()
        self._party_selected_mode = mode
        self._party_selected_index = idx
        self._party_selected_box_index = box_idx
        self._render_party_slot_grid()
        entry, label = self._selected_slot_entry()
        if not isinstance(entry, core.RubyObject):
            self.party_slot_status_var.set(f"Target: {label} (empty)")
            return
        self.party_slot_status_var.set(f"Target: {label}")

    def load_selected_slot_into_editor(self):
        entry, label = self._selected_slot_entry()
        if not isinstance(entry, core.RubyObject):
            messagebox.showwarning("No Pokemon", "Selected slot is empty.")
            return
        self._load_selected_pokemon_into_editor(entry)
        self.party_slot_status_var.set(f"Loaded: {label}")

    def _on_party_slot_right_click(self, event, idx: int):
        self.select_party_slot(idx)
        if not hasattr(self, "party_slot_context_menu"):
            return "break"
        entry, _label = self._selected_slot_entry()
        has_pokemon = isinstance(entry, core.RubyObject)
        try:
            self.party_slot_context_menu.delete(0, "end")
            if has_pokemon:
                self.party_slot_context_menu.add_command(label="View", command=self._party_slot_context_view)
            self.party_slot_context_menu.add_command(label="Set", command=self._party_slot_context_set)
            if has_pokemon:
                self.party_slot_context_menu.add_separator()
                self.party_slot_context_menu.add_command(label="Delete", command=self._party_slot_context_delete)
        except Exception:
            pass
        try:
            self.party_slot_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                self.party_slot_context_menu.grab_release()
            except Exception:
                pass
        return "break"

    def _party_slot_context_view(self):
        self.load_selected_slot_into_editor()

    def _party_slot_context_set(self):
        self.set_new_pokemon_to_selected_slot()

    def _party_slot_context_delete(self):
        entry, label = self._selected_slot_entry()
        if not isinstance(entry, core.RubyObject):
            return
        if not messagebox.askyesno("Delete Pokemon", f"Delete Pokemon in {label}?"):
            return
        try:
            self._set_selected_slot_entry(None)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Delete Error", str(exc))
            return
        self.mark_modified()
        self._render_party_slot_grid()
        self.party_slot_status_var.set(f"Deleted: {label}")
        self.set_status(f"Pokemon deleted from {label}.")

    def _load_selected_pokemon_into_editor(self, pkmn: core.RubyObject):
        species_id = symbol_name(core.read_attr(pkmn, "@species", ""))
        self.pk_species_var.set(self._species_choice(species_id))
        self.pk_form_var.set(str(core.read_attr(pkmn, "@form", 0)))
        self.pk_level_var.set(str(core.read_attr(pkmn, "@level", "")))
        self.pk_exp_var.set(str(core.read_attr(pkmn, "@exp", "")))
        self.pk_hp_var.set(str(core.read_attr(pkmn, "@hp", "")))
        self.pk_totalhp_var.set(str(core.read_attr(pkmn, "@totalhp", "")))
        self.pk_attack_var.set(str(core.read_attr(pkmn, "@attack", "")))
        self.pk_defense_var.set(str(core.read_attr(pkmn, "@defense", "")))
        self.pk_spatk_var.set(str(core.read_attr(pkmn, "@spatk", "")))
        self.pk_spdef_var.set(str(core.read_attr(pkmn, "@spdef", "")))
        self.pk_speed_var.set(str(core.read_attr(pkmn, "@speed", "")))
        self.pk_happiness_var.set(str(core.read_attr(pkmn, "@happiness", "")))
        nature_id = self._nature_choice(symbol_name(core.read_attr(pkmn, "@nature", "")))
        self.pk_nature_var.set(self._party_nature_id_to_label.get(nature_id, self._nature_label_for_id(nature_id)))
        self.pk_name_var.set(symbol_name(core.read_attr(pkmn, "@name", "")))
        self.pk_obtain_level_var.set(str(core.read_attr(pkmn, "@obtain_level", "")))
        self.pk_obtain_map_var.set(str(core.read_attr(pkmn, "@obtain_map", "")))
        self.pk_obtain_method_var.set(str(core.read_attr(pkmn, "@obtain_method", "")))
        self.pk_obtain_text_var.set(symbol_name(core.read_attr(pkmn, "@obtain_text", "")))
        self.pk_hatched_map_var.set(str(core.read_attr(pkmn, "@hatched_map", "")))
        self.pk_ability_index_var.set(self._normalize_optional_int_text(core.read_attr(pkmn, "@ability_index", "")))
        self.pk_personal_id_var.set(str(core.read_attr(pkmn, "@personalID", "")))
        self.pk_forced_form_var.set(self._normalize_optional_int_text(core.read_attr(pkmn, "@forced_form", "")))
        legacy = core.read_attr(pkmn, "@legacy_data", "")
        if isinstance(legacy, (dict, list, tuple, core.RubyObject)):
            self.pk_legacy_var.set(f"<{type(legacy).__name__}>")
        else:
            self.pk_legacy_var.set(symbol_name(legacy))

        self.pk_shiny_var.set(bool(core.read_attr(pkmn, "@shiny", False)))
        self.pk_super_shiny_var.set(bool(core.read_attr(pkmn, "@super_shiny", False)))
        self.pk_gender_var.set(str(core.read_attr(pkmn, "@gender", "")))
        status_raw = core.read_attr(pkmn, "@status", "NONE")
        status_count_raw = core.read_attr(pkmn, "@statusCount", 0)
        self.pk_field_status_var.set(self._party_status_label_from_fields(status_raw, status_count_raw))

        iv_map = self._read_symbol_stat_dict(pkmn, "@iv")
        ev_map = self._read_symbol_stat_dict(pkmn, "@ev")
        for stat_id, _label in STAT_ORDER:
            self.party_iv_vars[stat_id].set(str(iv_map.get(stat_id, 0)))
            self.party_ev_vars[stat_id].set(str(ev_map.get(stat_id, 0)))

        self.refresh_party_legality_dropdowns(reset_invalid=False)
        self._refresh_stats_from_editor_inputs()

        item_id = symbol_name(core.read_attr(pkmn, "@item", ""))
        if item_id:
            canonical_item = self._item_choice(item_id)
            item_id_to_label = getattr(self, "_party_item_id_to_label", {})
            self.pk_item_var.set(
                item_id_to_label.get(
                    canonical_item,
                    self._english_item_name_for_id(canonical_item),
                )
            )
        else:
            self.pk_item_var.set("")
        ability_id = symbol_name(core.read_attr(pkmn, "@ability", ""))
        if ability_id:
            ability_key = self.catalogs.canonical_ability_id(ability_id) if self.catalogs else ability_id.lstrip(":")
            self.pk_ability_var.set(self._party_ability_id_to_label.get(ability_key, self._ability_choice(ability_id)))
        else:
            self.pk_ability_var.set("")

        moves = core.read_attr(pkmn, "@moves", [])
        for i in range(4):
            if i < len(moves) and isinstance(moves[i], core.RubyObject):
                move = moves[i]
                move_id = symbol_name(core.read_attr(move, "@id", ""))
                if move_id:
                    move_key = self.catalogs.canonical_move_id(move_id) if self.catalogs else move_id.lstrip(":")
                    self.move_id_vars[i].set(self._party_move_id_to_label.get(move_key, self._move_choice(move_id)))
                else:
                    move_key = ""
                    self.move_id_vars[i].set("")
                ppup_value = self._clamp_int(str(core.read_attr(move, "@ppup", 0)), 0, 3, 0)
                pp_value = core.read_attr(move, "@pp", "")
                pp_text = str(pp_value).strip()
                if move_key:
                    max_pp = self._move_max_pp(move_key, ppup_value)
                    if not pp_text:
                        pp_text = str(max_pp)
                    else:
                        pp_text = str(self._clamp_int(pp_text, 0, max_pp, max_pp))
                self.move_pp_vars[i].set(pp_text)
                self.move_ppup_vars[i].set(str(ppup_value))
            else:
                self.move_id_vars[i].set("")
                self.move_pp_vars[i].set("")
                self.move_ppup_vars[i].set("")

        first_moves = core.read_attr(pkmn, "@first_moves", [])
        if not isinstance(first_moves, list):
            first_moves = []
        for i in range(4):
            if i < len(first_moves):
                move_id = symbol_name(first_moves[i])
                move_key = self.catalogs.canonical_move_id(move_id) if self.catalogs else move_id.lstrip(":")
                self.relearn_move_vars[i].set(self._party_relearn_id_to_label.get(move_key, "(None)"))
            else:
                self.relearn_move_vars[i].set("(None)")
        self._sync_ability_index_from_selection(force=False)
        self._update_nature_effect_labels()
        self.update_party_editor_preview()
        self.update_party_evolution_chart()
        self.update_party_description("species")

    def on_species_or_form_changed(self, _event=None):
        self.refresh_party_legality_dropdowns(reset_invalid=True)
        self._refresh_stats_from_editor_inputs()
        editor_blank = not any(
            [
                self.pk_level_var.get().strip(),
                self.pk_exp_var.get().strip(),
                self.pk_nature_var.get().strip(),
                self.move_id_vars[0].get().strip() if self.move_id_vars else "",
            ]
        )
        if editor_blank:
            self.load_species_defaults_into_editor()
        self.update_party_editor_preview()
        self.update_party_evolution_chart()
        self.update_party_description("species")

    def on_nature_changed(self, _event=None):
        self._update_nature_effect_labels()
        self._refresh_stats_from_editor_inputs()
        self.update_party_description("nature")

    @staticmethod
    def _normalize_optional_int_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        raw = str(value).strip()
        if raw.lower() in {"none", "nil", "null"}:
            return ""
        return raw

    def _suggest_ability_index_for_current(self) -> int | None:
        if not self.catalogs:
            return None
        species_id, form = self._current_species_form()
        if not species_id:
            return None
        ability_id = self.resolve_selected_ability_id(self.pk_ability_var.get())
        if not ability_id:
            return None
        profile = self.catalogs.get_species_form_profile(species_id, form=form)
        if not profile:
            return None
        regular: list[str] = []
        for raw in profile.ability_ids:
            aid = self.catalogs.canonical_ability_id(raw)
            if aid and aid not in regular:
                regular.append(aid)
        hidden: set[str] = set()
        for raw in profile.hidden_ability_ids:
            aid = self.catalogs.canonical_ability_id(raw)
            if aid:
                hidden.add(aid)
        if ability_id in hidden:
            return 2
        if ability_id in regular:
            return regular.index(ability_id)
        return 0

    def _sync_ability_index_from_selection(self, force: bool = False):
        suggestion = self._suggest_ability_index_for_current()
        if suggestion is None:
            return
        raw = self.pk_ability_index_var.get().strip()
        if force or raw == "" or raw.lower() in {"none", "nil", "null"}:
            self.pk_ability_index_var.set(str(self._clamp_int(str(suggestion), 0, 3, 0)))

    def on_ability_changed(self, _event=None):
        self._sync_ability_index_from_selection(force=True)
        self.update_party_description("ability")

    def on_ability_index_focus_out(self, _event=None):
        raw = self.pk_ability_index_var.get().strip()
        if raw.lower() in {"", "none", "nil", "null"}:
            self._sync_ability_index_from_selection(force=False)
            return
        try:
            value = parse_int(raw, "Ability Index")
        except Exception:
            self._sync_ability_index_from_selection(force=True)
            return
        self.pk_ability_index_var.set(str(self._clamp_int(str(value), 0, 3, 0)))

    def on_forced_form_focus_out(self, _event=None):
        raw = self.pk_forced_form_var.get().strip()
        if raw.lower() in {"", "none", "nil", "null"}:
            self.pk_forced_form_var.set("")
            return
        try:
            value = parse_int(raw, "Forced Form")
        except Exception:
            self.pk_forced_form_var.set("")
            return
        self.pk_forced_form_var.set(str(self._clamp_int(str(value), 0, 999, 0)))

    def on_shiny_changed(self):
        self.update_party_editor_preview()
        self.update_party_description("species")

    def _nature_choice(self, nature_id: str) -> str:
        return nature_id.strip().lstrip(":").upper()

    def _nature_label_for_id(self, nature_id: str) -> str:
        nature = self._nature_choice(nature_id)
        if not nature:
            return ""
        up, down = NATURE_EFFECTS.get(nature, (None, None))
        if up and down:
            return f"{nature} ({STAT_SHORT_LABELS.get(up, up)}↑ / {STAT_SHORT_LABELS.get(down, down)}↓)"
        return nature

    def _refresh_nature_choices(self):
        if not hasattr(self, "pk_nature_combo"):
            return
        if self.catalogs:
            nature_ids = sorted((self._nature_choice(n) for n in self.catalogs.natures if str(n).strip()), key=str.casefold)
        else:
            nature_ids = sorted({"HARDY", "LONELY", "BRAVE", "ADAMANT", "NAUGHTY", "BOLD", "DOCILE", "RELAXED",
                                 "IMPISH", "LAX", "TIMID", "HASTY", "SERIOUS", "JOLLY", "NAIVE", "MODEST",
                                 "MILD", "QUIET", "BASHFUL", "RASH", "CALM", "GENTLE", "SASSY", "CAREFUL", "QUIRKY"},
                                key=str.casefold)
        label_pairs: list[tuple[str, str]] = []
        for nature_id in nature_ids:
            label = self._nature_label_for_id(nature_id)
            if any(existing == label for existing, _ in label_pairs):
                label = f"{label} [{nature_id}]"
            label_pairs.append((label, nature_id))
        self._party_nature_label_to_id = {label: nid for label, nid in label_pairs}
        self._party_nature_id_to_label = {}
        for label, nature_id in label_pairs:
            self._party_nature_id_to_label.setdefault(nature_id, label)
        self._set_combo_values(self.pk_nature_combo, [label for label, _ in label_pairs])

    def resolve_selected_nature_id(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        if raw in self._party_nature_label_to_id:
            return self._party_nature_label_to_id[raw]
        cleaned = re.sub(r"\s+\([^)]+\)\s*$", "", raw)
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        cleaned = extract_internal_id(cleaned).strip().lstrip(":").upper()
        if not cleaned:
            return ""
        return cleaned

    def _default_move_pp(self, move_id: str) -> int:
        if self.catalogs:
            return self.catalogs.move_total_pp(move_id, default=5)
        return 5

    def _move_max_pp(self, move_id: str, ppup_value: str | int) -> int:
        base_pp = self._default_move_pp(move_id)
        ppup = self._clamp_int(str(ppup_value), 0, 3, 0)
        # Mainline formula: MaxPP = BasePP + floor(BasePP * PPUps / 5)
        return base_pp + ((base_pp * ppup) // 5)

    def on_move_combo_changed(self, index: int, force_pp: bool = True, update_description: bool = True):
        if index < 0 or index >= len(self.move_id_vars):
            return
        move_id = self.resolve_selected_move_id(self.move_id_vars[index].get())
        ppup = self._clamp_int(self.move_ppup_vars[index].get(), 0, 3, 0)
        self.move_ppup_vars[index].set(str(ppup))
        if force_pp:
            self.move_pp_vars[index].set(str(self._move_max_pp(move_id, ppup)) if move_id else "")
        elif move_id:
            max_pp = self._move_max_pp(move_id, ppup)
            if not self.move_pp_vars[index].get().strip():
                self.move_pp_vars[index].set(str(max_pp))
            else:
                self.move_pp_vars[index].set(str(self._clamp_int(self.move_pp_vars[index].get(), 0, max_pp, max_pp)))
        if update_description:
            self.update_party_description("move", index)

    def on_move_ppup_changed(self, index: int):
        if index < 0 or index >= len(self.move_id_vars):
            return
        ppup = self._clamp_int(self.move_ppup_vars[index].get(), 0, 3, 0)
        self.move_ppup_vars[index].set(str(ppup))
        move_id = self.resolve_selected_move_id(self.move_id_vars[index].get())
        if move_id:
            self.move_pp_vars[index].set(str(self._move_max_pp(move_id, ppup)))
        self.update_party_description("move", index)

    def on_move_pp_focus_out(self, index: int):
        if index < 0 or index >= len(self.move_id_vars):
            return
        move_id = self.resolve_selected_move_id(self.move_id_vars[index].get())
        ppup = self._clamp_int(self.move_ppup_vars[index].get(), 0, 3, 0)
        self.move_ppup_vars[index].set(str(ppup))
        if move_id:
            max_pp = self._move_max_pp(move_id, ppup)
            self.move_pp_vars[index].set(str(self._clamp_int(self.move_pp_vars[index].get(), 0, max_pp, max_pp)))
        else:
            self.move_pp_vars[index].set(str(self._clamp_int(self.move_pp_vars[index].get(), 0, 999, 0)))

    def _set_text_widget_content(self, widget: tk.Text, text: str):
        content = text.strip() or "No description available."
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        self._bold_type_terms_in_description(widget, content)
        widget.configure(state="disabled")

    def _description_type_terms(self) -> list[str]:
        terms = {self._type_display_name_for_id(tid) for tid in self._known_type_ids()}
        return sorted((t for t in terms if t), key=lambda v: (-len(v), v.casefold()))

    def _bold_type_terms_in_description(self, widget: tk.Text, content: str):
        try:
            base_font = tkfont.nametofont(str(widget.cget("font")))
            bold_font = getattr(widget, "_desc_bold_font", None)
            if bold_font is None:
                bold_font = base_font.copy()
                bold_font.configure(weight="bold")
                setattr(widget, "_desc_bold_font", bold_font)
            widget.tag_configure("desc_type_bold", font=bold_font)
            widget.tag_remove("desc_type_bold", "1.0", "end")
            for term in self._description_type_terms():
                pattern = rf"(?i)\b{re.escape(term)}(?:-type)?\b"
                for match in re.finditer(pattern, content):
                    start = f"1.0+{match.start()}c"
                    end = f"1.0+{match.end()}c"
                    widget.tag_add("desc_type_bold", start, end)
        except Exception:
            return

    @staticmethod
    def _title_case_words(text: str) -> str:
        raw = re.sub(r"\s+", " ", str(text or "").strip())
        if not raw:
            return ""
        return raw.title()

    @staticmethod
    def _prettify_internal_id(raw_id: str) -> str:
        text = str(raw_id or "").strip().lstrip(":")
        if not text:
            return ""
        tokens = re.split(r"[_\-\s]+", text)
        suffixes = (
            "POWER",
            "FORCE",
            "GUARD",
            "BODY",
            "SKIN",
            "ARMOR",
            "ARMOUR",
            "STREAM",
            "START",
            "EYES",
            "VOICE",
            "DANCE",
            "STONE",
            "CLAW",
            "COAT",
            "CORD",
            "WHIP",
            "FANG",
            "TOOTH",
            "SHARD",
            "ORB",
        )
        out: list[str] = []
        for token in tokens:
            upper = token.upper()
            if not upper:
                continue
            split_done = False
            for suffix in suffixes:
                if upper.endswith(suffix) and len(upper) > len(suffix) + 2:
                    out.append(upper[: -len(suffix)])
                    out.append(suffix)
                    split_done = True
                    break
            if not split_done:
                out.append(upper)
        return SaveEditorApp._title_case_words(" ".join(out))

    def _english_name_from_translation_file(self, filename: str, localized_name: str) -> str:
        raw_name = str(localized_name or "").strip().lstrip("\ufeff")
        if not raw_name:
            return ""
        if not hasattr(self, "_english_name_translation_maps"):
            self._english_name_translation_maps: dict[str, dict[str, str]] = {}
        cache = self._english_name_translation_maps
        if filename not in cache:
            mapping: dict[str, str] = {}
            path = self.game_root / "Text_english_game" / filename
            try:
                lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except Exception:
                lines = []
            cleaned: list[str] = []
            for line in lines:
                s = str(line or "").strip().lstrip("\ufeff")
                if not s or s.startswith("#") or (s.startswith("[") and s.endswith("]")):
                    continue
                cleaned.append(s)
            for i in range(0, len(cleaned) - 1, 2):
                source = cleaned[i].strip()
                english = cleaned[i + 1].strip()
                if source and english:
                    mapping[source] = english
                    mapping[source.casefold()] = english
            cache[filename] = mapping
        data = cache.get(filename, {})
        return str(data.get(raw_name, data.get(raw_name.casefold(), "")) or "").strip()

    def _translate_to_english(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        if raw in self._translated_desc_miss_cache:
            return ""
        cached = self._translated_desc_cache.get(raw)
        if cached:
            return cached
        translated = ""
        try:
            url = (
                "https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl=auto&tl=en&dt=t&q={urllib.parse.quote(raw)}"
            )
            with urllib.request.urlopen(url, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if isinstance(payload, list) and payload and isinstance(payload[0], list):
                parts = []
                for chunk in payload[0]:
                    if isinstance(chunk, list) and chunk:
                        segment = str(chunk[0]).strip()
                        if segment:
                            parts.append(segment)
                translated = "".join(parts).strip()
        except Exception:
            translated = ""
        # Persist misses too; avoids repeated UI-thread timeouts on same source text.
        if translated:
            if len(self._translated_desc_cache) > 5000:
                self._translated_desc_cache.clear()
            self._translated_desc_cache[raw] = translated
        else:
            if len(self._translated_desc_miss_cache) > 5000:
                self._translated_desc_miss_cache.clear()
            self._translated_desc_miss_cache.add(raw)
        return translated

    def _english_description(self, text: str, fallback: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return fallback
        is_ascii = all(ord(ch) < 128 for ch in raw)
        looks_non_english_ascii = is_ascii and self._looks_non_english_ascii(raw)
        if is_ascii and not looks_non_english_ascii:
            # Fast path for likely-English descriptions.
            return raw
        translated = self._translate_to_english(raw)
        if translated:
            return translated
        if is_ascii and not looks_non_english_ascii:
            return raw
        return fallback

    @staticmethod
    def _looks_non_english_ascii(text: str) -> bool:
        words = re.findall(r"[A-Za-z']+", str(text or "").casefold())
        if not words:
            return False
        spanish_markers = {
            "al", "del", "con", "sin", "para", "nivel", "ataque", "defensa", "rival",
            "combate", "disminuye", "aumenta", "pokemon", "movimiento", "turno",
            "objetivo", "habilidad", "entra", "sale", "usa", "puede",
        }
        if any(w in spanish_markers for w in words):
            return True
        english_markers = {
            "the", "target", "user", "attack", "defense", "damage", "move",
            "turn", "level", "pokemon", "this", "that", "when", "after", "before",
            "raises", "lowers", "heals", "accuracy", "power", "speed", "ability",
        }
        long_words = [w for w in words if len(w) >= 3]
        if not long_words:
            return False
        english_hits = sum(1 for w in long_words if w in english_markers)
        ratio = english_hits / max(1, len(long_words))
        return ratio < 0.18

    @staticmethod
    def _sanitize_move_description_text(text: str) -> str:
        out = re.sub(r"\s+", " ", str(text or "").strip())
        if not out:
            return ""
        replacements = (
            (r"\bHe\b", "It"),
            (r"\bhe\b", "it"),
            (r"\bShe\b", "It"),
            (r"\bshe\b", "it"),
            (r"\bHis\b", "Its"),
            (r"\bhis\b", "its"),
            (r"\bHer(?=\s+[A-Za-z])", "Its"),
            (r"\bher(?=\s+[A-Za-z])", "its"),
            (r"\bHim\b", "It"),
            (r"\bhim\b", "it"),
            (r"\bHimself\b", "Itself"),
            (r"\bhimself\b", "itself"),
            (r"\bHerself\b", "Itself"),
            (r"\bherself\b", "itself"),
            (r"\bHer\b", "It"),
            (r"\bher\b", "it"),
        )
        for pattern, repl in replacements:
            out = re.sub(pattern, repl, out)
        if out:
            out = out[0].upper() + out[1:]
        return out

    def _is_low_quality_move_description(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return True
        normalized = raw.casefold().strip(". !?")
        if normalized in LOW_QUALITY_DESC_TOKENS:
            return True
        words = re.findall(r"[A-Za-z']+", raw)
        if len(words) <= 2:
            return True
        # Likely still mistranslated if it keeps obvious non-English ASCII markers.
        if all(ord(ch) < 128 for ch in raw) and self._looks_non_english_ascii(raw):
            return True
        return False

    def _english_ability_name_for_id(self, ability_id: str) -> str:
        aid = str(ability_id or "").strip().lstrip(":")
        if not aid:
            return ""
        if self.catalogs:
            canonical = self.catalogs.canonical_ability_id(aid) or aid
            english = self.catalogs.ability_english_name(canonical)
            if english:
                translated = self._english_name_from_translation_file("ABILITY_NAMES.txt", english)
                return translated or english
            ability_item = self.catalogs.abilities_by_id.get(canonical)
            ability_display = str(ability_item.display_name if ability_item else "").strip()
            translated = self._english_name_from_translation_file("ABILITY_NAMES.txt", ability_display)
            if translated:
                return translated
            # Always prefer internal IDs for stable English labels even if catalog
            # display names are localized.
            return self._prettify_internal_id(canonical)
        return self._prettify_internal_id(aid)

    def _english_species_name_for_id(self, species_id: str) -> str:
        sid = str(species_id or "").strip().lstrip(":")
        if not sid:
            return ""
        if self.catalogs:
            canonical = self.catalogs.canonical_species_id(sid) or sid
            display = str(self.catalogs.species_display(canonical) or "").strip()
            if display:
                if display.casefold() == canonical.casefold():
                    return self._prettify_internal_id(canonical)
                return display
            return self._prettify_internal_id(canonical)
        return self._prettify_internal_id(sid)

    def _english_move_name_for_id(self, move_id: str) -> str:
        mid = str(move_id or "").strip().lstrip(":")
        if not mid:
            return ""
        canonical = self.catalogs.canonical_move_id(mid) if self.catalogs else mid
        canonical = canonical or mid

        if not hasattr(self, "_move_english_loaded"):
            self._move_english_loaded = False
        if not hasattr(self, "_move_english_by_id"):
            self._move_english_by_id = {}
        if not self._move_english_loaded:
            mapping: dict[str, str] = {}
            try:
                path = self.game_root / "Data" / "data_for_showdown" / "moves_en.txt"
                if path.exists():
                    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = raw.strip()
                        if not line or line.startswith("#"):
                            continue
                        move_key, sep, display = line.partition(",")
                        if not sep:
                            continue
                        move_key = move_key.strip().lstrip(":")
                        label = display.strip()
                        if not move_key or not label:
                            continue
                        canonical_key = self.catalogs.canonical_move_id(move_key) if self.catalogs else move_key
                        canonical_key = canonical_key or move_key
                        mapping[canonical_key] = label
            except Exception:
                mapping = {}
            self._move_english_by_id = mapping
            self._move_english_loaded = True

        english = str(self._move_english_by_id.get(canonical, "")).strip()
        if english:
            translated = self._english_name_from_translation_file("MOVE_NAMES.txt", english)
            return translated or english
        if self.catalogs:
            display = str(self.catalogs.move_display(canonical) or "").strip()
            translated = self._english_name_from_translation_file("MOVE_NAMES.txt", display)
            if translated:
                return translated
            if display and display.casefold() == canonical.casefold():
                return self._prettify_internal_id(canonical)
        return self._prettify_internal_id(canonical)

    def _english_item_name_for_id(self, item_id: str) -> str:
        iid = str(item_id or "").strip().lstrip(":")
        if not iid:
            return ""
        custom_id = iid.upper()
        if custom_id in self._custom_manifest_item_specs():
            return self._custom_manifest_item_name(custom_id)
        canonical = self.catalogs.canonical_item_id(iid) if self.catalogs else iid
        canonical = canonical or iid

        if not hasattr(self, "_item_english_loaded"):
            self._item_english_loaded = False
        if not hasattr(self, "_item_english_by_id"):
            self._item_english_by_id = {}
        if not self._item_english_loaded:
            mapping: dict[str, str] = {}
            try:
                path = self.game_root / "Data" / "data_for_showdown" / "items_en.txt"
                if path.exists():
                    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                        line = raw.strip()
                        if not line or line.startswith("#"):
                            continue
                        item_key, sep, display = line.partition(",")
                        if not sep:
                            continue
                        item_key = item_key.strip().lstrip(":")
                        label = display.strip()
                        if not item_key or not label:
                            continue
                        canonical_key = self.catalogs.canonical_item_id(item_key) if self.catalogs else item_key
                        canonical_key = canonical_key or item_key
                        mapping[canonical_key] = label
            except Exception:
                mapping = {}
            self._item_english_by_id = mapping
            self._item_english_loaded = True

        english = str(self._item_english_by_id.get(canonical, "")).strip()
        if english:
            translated = self._english_name_from_translation_file("ITEM_NAMES.txt", english)
            return translated or english
        if self.catalogs:
            display = str(self.catalogs.item_display(canonical) or "").strip()
            translated = self._english_name_from_translation_file("ITEM_NAMES.txt", display)
            if translated:
                return translated
            if display and display.casefold() == canonical.casefold():
                return self._prettify_internal_id(canonical)
        return self._prettify_internal_id(canonical)

    def _type_display_name_for_id(self, type_id: str) -> str:
        raw = str(type_id or "").strip().lstrip(":")
        if not raw:
            return ""
        canonical = raw.upper()
        if self.catalogs and canonical not in self.catalogs.type_names_by_id:
            needle = self._sanitize_lookup_token(raw)
            if needle:
                for tid, display in self.catalogs.type_names_by_id.items():
                    if needle == self._sanitize_lookup_token(tid) or needle == self._sanitize_lookup_token(display):
                        canonical = str(tid).strip().upper()
                        break
        if canonical in {"QMARKS", "QMARK", "UNKNOWN", "???"}:
            return "???"
        # Force English-style type labels globally; do not use localized display names.
        return self._prettify_internal_id(canonical)

    def _tm_hm_display_label(self, item_id: str, pocket_index: int | None = None) -> str:
        iid = str(item_id or "").strip().lstrip(":")
        if not iid:
            return ""
        if pocket_index is None:
            try:
                pocket_index = self.get_selected_bag_pocket_index()
            except Exception:
                pocket_index = None
        if pocket_index != 4 or not self.catalogs:
            return self._english_item_name_for_id(iid)
        m = re.match(r"^(TM|HM)(\d+)$", iid, flags=re.IGNORECASE)
        if not m:
            return self._english_item_name_for_id(iid)
        item = self.catalogs.items_by_id.get(iid) or self.catalogs.items_by_id.get(self.catalogs.canonical_item_id(iid) or "")
        if not item:
            return self._english_item_name_for_id(iid)
        move_raw = str(item.extra.get("Move", "")).strip().lstrip(":")
        if not move_raw:
            return self._english_item_name_for_id(iid)
        move_id = self.catalogs.canonical_move_id(move_raw) or move_raw
        move_name = self._english_move_name_for_id(move_id)
        if not move_name:
            return self._english_item_name_for_id(iid)
        return f"{iid.upper()} - {move_name}"

    def _nature_description(self, nature_id: str) -> str:
        nature = self._nature_choice(nature_id)
        if not nature:
            return ""
        up, down = NATURE_EFFECTS.get(nature, (None, None))
        if not up or not down:
            return "Neutral nature. No stat is increased or decreased."
        return (
            f"Increases {STAT_SHORT_LABELS.get(up, up)} and decreases {STAT_SHORT_LABELS.get(down, down)} "
            "when calculating battle stats."
        )

    @staticmethod
    def _join_with_and(values: list[str]) -> str:
        if not values:
            return ""
        if len(values) == 1:
            return values[0]
        if len(values) == 2:
            return f"{values[0]} and {values[1]}"
        return f"{', '.join(values[:-1])}, and {values[-1]}"

    @staticmethod
    def _dedupe_preserve(lines: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for line in lines:
            text = str(line or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out

    @staticmethod
    def _extract_numeric_tokens(*texts: str) -> list[str]:
        merged = " ".join(str(text or "") for text in texts if str(text or "").strip())
        if not merged:
            return []
        patterns = (
            r"\b\d+\s*/\s*\d+\b",
            r"\b\d+(?:\.\d+)?\s*%\b",
            r"\b\d+(?:\.\d+)?x\b",
            r"\bx\d+(?:\.\d+)?\b",
            r"\+\d+\b",
            r"-\d+\b",
        )
        out: list[str] = []
        for pattern in patterns:
            for match in re.findall(pattern, merged, flags=re.IGNORECASE):
                token = re.sub(r"\s+", "", str(match))
                if token not in out:
                    out.append(token)
        return out

    @staticmethod
    def _split_function_stat_blob(stat_blob: str) -> list[str]:
        remaining = str(stat_blob or "").strip()
        if not remaining:
            return []
        out: list[str] = []
        while remaining:
            matched = False
            for token, label in FUNCTION_STAT_TOKEN_LABELS:
                if remaining.startswith(token):
                    if label not in out:
                        out.append(label)
                    remaining = remaining[len(token):]
                    matched = True
                    break
            if not matched:
                return []
        return out

    def _move_function_hint(self, function_code: str) -> str:
        code = str(function_code or "").strip()
        if not code or code.upper() == "NONE":
            return ""
        exact = MOVE_FUNCTION_EXACT_HINTS.get(code)
        if exact:
            return exact

        stat_match = re.match(
            r"^(Raise|Lower)(User|Target|Allies|GrassBattlers|GroundedGrassBattlers|PlusMinusUserAndAllies)"
            r"([A-Za-z]+?)(\d)(.*)$",
            code,
        )
        if stat_match:
            action, subject_code, stat_blob, stages_raw, suffix = stat_match.groups()
            stats = self._split_function_stat_blob(stat_blob)
            if stats:
                subject_map = {
                    "User": "user",
                    "Target": "target",
                    "Allies": "all allies",
                    "GrassBattlers": "Grass-type battlers",
                    "GroundedGrassBattlers": "grounded Grass-type battlers",
                    "PlusMinusUserAndAllies": "user and allies with Plus/Minus",
                }
                subject = subject_map.get(subject_code, "affected battlers")
                stage_count = int(stages_raw)
                stage_word = "stage" if stage_count == 1 else "stages"
                verb = "Raises" if action == "Raise" else "Lowers"
                line = f"{verb} {self._join_with_and(stats)} of {subject} by {stage_count} {stage_word}."
                if suffix:
                    line += " Additional conditional effect applies."
                return line

        if "HalfOfTotalHP" in code:
            return "Uses a 1/2 max HP formula in its effect logic."
        if "QuarterOfTotalHP" in code:
            return "Uses a 1/4 max HP formula in its effect logic."
        if "ThirdOfTotalHP" in code:
            return "Uses a 1/3 max HP formula in its effect logic."
        if "ByHalfOfDamageDone" in code:
            return "Uses healing equal to 1/2 of damage dealt."
        if "ByThreeQuartersOfDamageDone" in code:
            return "Uses healing equal to 3/4 of damage dealt."
        if "RecoilHalfOfDamageDealt" in code:
            return "Uses recoil equal to 1/2 of damage dealt."
        if "RecoilThirdOfDamageDealt" in code:
            return "Uses recoil equal to 1/3 of damage dealt."
        if "RecoilQuarterOfDamageDealt" in code:
            return "Uses recoil equal to 1/4 of damage dealt."
        if "PowerHigherWith" in code or "PowerLowerWith" in code:
            return "Power is variable and scales with battle conditions."
        return ""

    def _move_numeric_summary_lines(self, move_id: str, raw_desc: str, english_desc: str) -> list[str]:
        if not self.catalogs or not move_id:
            return []
        canonical = self.catalogs.canonical_move_id(move_id) or move_id
        move = self.catalogs.moves_by_id.get(canonical)
        if not move:
            return []
        lines: list[str] = []

        power_raw = str(move.extra.get("Power", "")).strip()
        if power_raw:
            try:
                power = int(power_raw)
                lines.append(f"Base power: {power}.")
            except ValueError:
                pass

        accuracy_raw = str(move.extra.get("Accuracy", "")).strip()
        if accuracy_raw:
            try:
                accuracy = int(float(accuracy_raw))
                if accuracy <= 0:
                    lines.append("Accuracy: no standard accuracy roll (self-target or guaranteed effect).")
                else:
                    lines.append(f"Accuracy: {accuracy}%.")
            except ValueError:
                pass

        pp_raw = str(move.extra.get("TotalPP", move.extra.get("PP", ""))).strip()
        if pp_raw:
            try:
                lines.append(f"Base PP: {int(pp_raw)}.")
            except ValueError:
                pass

        priority_raw = str(move.extra.get("Priority", "")).strip()
        if priority_raw:
            try:
                priority = int(priority_raw)
                if priority:
                    sign = "+" if priority > 0 else ""
                    lines.append(f"Priority: {sign}{priority}.")
            except ValueError:
                pass

        function_code = str(move.extra.get("FunctionCode", "")).strip()
        function_hint = self._move_function_hint(function_code)
        if function_hint:
            lines.append(function_hint)
        if function_code and function_code.upper() != "NONE":
            lines.append(f"Internal function code: {function_code}.")

        numeric_tokens = self._extract_numeric_tokens(raw_desc, english_desc)
        if numeric_tokens:
            lines.append(f"Numeric values detected in description text: {', '.join(numeric_tokens)}.")
        return self._dedupe_preserve(lines)

    def _item_numeric_summary_lines(self, item_id: str, raw_desc: str, english_desc: str) -> list[str]:
        if not self.catalogs or not item_id:
            return []
        canonical = self.catalogs.canonical_item_id(item_id) or item_id
        item = self.catalogs.items_by_id.get(canonical)
        if not item:
            return []
        lines: list[str] = []

        known = ITEM_NUMERIC_HINTS.get(canonical)
        if known:
            lines.append(known)

        flags = str(item.extra.get("Flags", "")).strip()
        fling_match = re.search(r"\bFling[_\s-]?(\d+)\b", flags, flags=re.IGNORECASE)
        if fling_match:
            lines.append(f"Fling base power: {int(fling_match.group(1))}.")

        numeric_tokens = self._extract_numeric_tokens(raw_desc, english_desc)
        if numeric_tokens:
            lines.append(f"Numeric values detected in description text: {', '.join(numeric_tokens)}.")
        return self._dedupe_preserve(lines)

    def _ability_numeric_summary_lines(self, ability_id: str, raw_desc: str, english_desc: str) -> list[str]:
        if not self.catalogs or not ability_id:
            return []
        canonical = self.catalogs.canonical_ability_id(ability_id) or ability_id
        ability = self.catalogs.abilities_by_id.get(canonical)
        if not ability:
            return []
        lines: list[str] = []

        known = ABILITY_NUMERIC_HINTS.get(canonical)
        if known:
            lines.append(known)

        numeric_tokens = self._extract_numeric_tokens(raw_desc, english_desc)
        if numeric_tokens:
            lines.append(f"Numeric values detected in description text: {', '.join(numeric_tokens)}.")
        return self._dedupe_preserve(lines)

    def _generated_move_flavor_description(self, move_id: str) -> str:
        if not self.catalogs or not move_id:
            return ""
        canonical = self.catalogs.canonical_move_id(move_id) or str(move_id or "").strip().lstrip(":")
        move = self.catalogs.moves_by_id.get(canonical)
        if not move:
            return ""
        type_id = str(move.extra.get("Type", "")).strip().lstrip(":")
        category_id = str(move.extra.get("Category", "")).strip().lstrip(":")
        target_id = str(move.extra.get("Target", "")).strip().lstrip(":")
        type_label = self._type_display_name_for_id(type_id) if type_id else ""
        category_label = self._prettify_internal_id(category_id) if category_id else ""
        target_label = self._prettify_internal_id(target_id) if target_id else ""
        parts: list[str] = []
        if type_label and category_label:
            parts.append(f"{type_label}-type {category_label.lower()} move.")
        elif type_label:
            parts.append(f"{type_label}-type move.")
        elif category_label:
            parts.append(f"{category_label} move.")
        if target_label:
            parts.append(f"Target: {target_label}.")
        return " ".join(parts).strip()

    def _resolve_entity_description(
        self,
        kind: str,
        entity_id: str,
        raw_desc: str,
        summary_lines: list[str],
    ) -> tuple[str, list[str]]:
        cleaned = [str(line or "").strip() for line in summary_lines if str(line or "").strip()]
        cache_key = (
            str(kind or "").strip().casefold(),
            str(entity_id or "").strip(),
            str(raw_desc or ""),
            tuple(cleaned),
        )
        cached = self._resolved_entity_desc_cache.get(cache_key)
        if cached is not None:
            base_cached, cleaned_cached = cached
            return base_cached, list(cleaned_cached)
        base_desc = self._english_description(raw_desc, "")
        if kind == "move" and base_desc:
            base_desc = self._sanitize_move_description_text(base_desc)
            if self._is_low_quality_move_description(base_desc):
                base_desc = ""
        if not base_desc:
            if kind == "move":
                base_desc = self._generated_move_flavor_description(entity_id)
            if not base_desc and cleaned:
                base_desc = cleaned[0]
            if not base_desc and kind == "ability":
                base_desc = "No ability description exists in the current game data."
            if not base_desc and kind == "item":
                base_desc = "No item description exists in the current game data."
        base_norm = base_desc.strip().casefold() if base_desc else ""
        if base_norm:
            cleaned = [line for line in cleaned if line.strip().casefold() != base_norm]
        result = (base_desc.strip(), cleaned)
        if len(self._resolved_entity_desc_cache) > 8000:
            self._resolved_entity_desc_cache.clear()
        self._resolved_entity_desc_cache[cache_key] = (result[0], tuple(result[1]))
        return result

    @staticmethod
    def _append_mechanics_block(description: str, summary_lines: list[str]) -> str:
        lines = [str(line or "").strip() for line in summary_lines if str(line or "").strip()]
        if not lines:
            return description
        block = "Mechanics (Known):\n" + "\n".join(f"- {line}" for line in lines)
        base = str(description or "").strip()
        if not base:
            return block
        return f"{base}\n\n{block}"

    def _evolution_condition_param_label(self, category: str, value: str) -> str:
        raw = str(value or "").strip().lstrip(":")
        if not raw:
            return ""
        cat = str(category or "").strip().lower()
        if not self.catalogs:
            return self._prettify_internal_id(raw)
        if cat == "item":
            canonical = self.catalogs.canonical_item_id(raw) or raw
            return self._dex_item_display_name(canonical)
        if cat == "move":
            canonical = self.catalogs.canonical_move_id(raw) or raw
            return self._dex_display_name_for_entry("Moves", canonical)
        if cat == "species":
            canonical = self.catalogs.canonical_species_id(raw) or raw
            return self._dex_display_name_for_entry("Species", canonical)
        return self._prettify_internal_id(raw)

    def _evolution_condition_text(self, method: str, param: str) -> str:
        method_key = (method or "").strip().upper()
        value = (param or "").strip()
        if method_key == "LEVEL":
            return f"Level {value or '?'}"
        if method_key == "LEVELMALE":
            return f"Level {value or '?'} (male)"
        if method_key == "LEVELFEMALE":
            return f"Level {value or '?'} (female)"
        if method_key == "ITEM":
            item = self._evolution_condition_param_label("item", value)
            return f"Use {item}" if item else "Use required item"
        if method_key == "ITEMFEMALE":
            item = self._evolution_condition_param_label("item", value)
            return f"Use {item} (female)" if item else "Use required item (female)"
        if method_key == "DAYHOLDITEM":
            item = self._evolution_condition_param_label("item", value)
            return f"Level up in daytime while holding {item}" if item else "Level up in daytime while holding required item"
        if method_key == "TRADEITEM":
            item = self._evolution_condition_param_label("item", value)
            return f"Trade while holding {item}" if item else "Trade while holding required item"
        if method_key == "TRADE":
            return "Trade"
        if method_key == "TRADESPECIES":
            species = self._evolution_condition_param_label("species", value)
            return f"Trade for {species}" if species else "Trade for specific species"
        if method_key == "LINKINGCORD":
            return "Use Linking Cord"
        if method_key == "HAPPINESS":
            return "High friendship"
        if method_key == "HAPPINESSDAY":
            return "High friendship\n(day time)"
        if method_key == "HAPPINESSNIGHT":
            return "High friendship\n(night time)"
        if method_key == "HASMOVE":
            move = self._evolution_condition_param_label("move", value)
            return f"Know move {move}" if move else "Know required move"
        if method_key == "HASINPARTY":
            species = self._evolution_condition_param_label("species", value)
            return f"Have {species} in party" if species else "Have required Pokemon in party"
        if method_key == "ATTACKGREATER":
            return f"Level {value or '?'} with Atk > Def"
        if method_key == "DEFENSEGREATER":
            return f"Level {value or '?'} with Def > Atk"
        if method_key == "ATKDEFEQUAL":
            return f"Level {value or '?'} with Atk = Def"
        if method_key == "SYLVEON":
            return "Level up with high friendship and a Fairy-type move"
        if method_key == "CASCOON":
            return "Level up (Cascoon branch)"
        if method_key == "SILCOON":
            return "Level up (Silcoon branch)"
        if method_key == "NINJASK":
            return "Level up (Ninjask branch)"
        if method_key == "SHEDINJA":
            return "Level up with empty party slot and a Poke Ball (Shedinja branch)"
        if not method_key:
            return "Unknown condition"
        pretty = self._prettify_internal_id(method_key)
        val = self._prettify_internal_id(value)
        return f"{pretty}: {val}".strip(": ")

    def _species_evolution_description(self, species_id: str, form: int) -> str:
        if not self.catalogs or not species_id:
            return "Evolution family: No evolution chain data."
        edges = self.catalogs.species_evolution_family_edges(species_id, form=form)
        if not edges:
            return "Evolution family: No evolution chain data."
        children: dict[str, list[tuple[str, str]]] = {}
        parents: dict[str, set[str]] = {}
        nodes: set[str] = set()
        for source, target, conds in edges:
            condition_texts = [self._evolution_condition_text(method, param) for method, param in conds]
            condition_texts = list(dict.fromkeys([t for t in condition_texts if t]))
            condition = " OR ".join(condition_texts) if condition_texts else "Unknown condition"
            children.setdefault(source, []).append((target, condition))
            parents.setdefault(target, set()).add(source)
            nodes.add(source)
            nodes.add(target)
        for source in list(children.keys()):
            children[source].sort(key=lambda row: (row[0].casefold(), row[1].casefold()))
        roots = sorted([n for n in nodes if not parents.get(n)], key=str.casefold)
        if not roots:
            roots = sorted(nodes, key=str.casefold)

        selected = species_id.strip().lstrip(":").upper()
        lines = ["Evolution family chain:"]

        def walk(node: str, prefix: str, edge_label: str, is_last: bool, path: set[str]):
            marker = "* " if node.upper() == selected else ""
            if prefix:
                connector = "\\- " if is_last else "|- "
                label = f" [{edge_label}]" if edge_label else ""
                lines.append(f"{prefix}{connector}{marker}{node}{label}")
            else:
                lines.append(f"{marker}{node}")

            if node in path:
                lines.append(f"{prefix}{'   ' if is_last else '|  '}\\- (cycle truncated)")
                return
            next_path = set(path)
            next_path.add(node)

            next_prefix = prefix + ("   " if is_last else "|  ")
            kids = children.get(node, [])
            for idx, (child, cond) in enumerate(kids):
                child_last = idx == len(kids) - 1
                walk(child, next_prefix, cond, child_last, next_path)

        for idx, root in enumerate(roots):
            walk(root, "", "", idx == len(roots) - 1, set())
            if idx != len(roots) - 1:
                lines.append("")
        return "\n".join(lines)

    def _chart_scaled_image(self, img: tk.PhotoImage, cache_key: str, factor: int) -> tk.PhotoImage:
        if factor <= 1:
            return img
        key = f"{cache_key}:{factor}"
        cached = self._party_evo_scaled_icon_cache.get(key)
        if cached is not None:
            return cached
        try:
            out = img.subsample(factor, factor)
        except Exception:
            out = img
        self._party_evo_scaled_icon_cache[key] = out
        self._prune_dict_cache(self._party_evo_scaled_icon_cache, PARTY_EVO_SCALED_ICON_CACHE_LIMIT)
        return out

    def _evolution_edge_item_id(self, conditions: list[tuple[str, str]]) -> str:
        if not self.catalogs:
            return ""
        for method, param in conditions:
            method_key = str(method or "").strip().upper()
            value = str(param or "").strip().lstrip(":")
            if method_key == "LINKINGCORD":
                return self.catalogs.canonical_item_id("LINKINGCORD") or "LINKINGCORD"
            if method_key in {"ITEM", "ITEMMALE", "ITEMFEMALE", "USEITEM", "TRADEITEM", "DAYHOLDITEM"} and value:
                return self.catalogs.canonical_item_id(value) or value
        return ""

    def _evolution_edge_short_text(self, conditions: list[tuple[str, str]], item_id: str) -> str:
        _ = item_id
        labels: list[str] = []
        for method, param in conditions:
            text = self._evolution_condition_text(method, param)
            if not text:
                continue
            labels.append(text)
        labels = list(dict.fromkeys(labels))
        out = " + ".join(labels)
        if len(out) > 160:
            out = f"{out[:157]}..."
        return out

    @staticmethod
    def _estimate_wrapped_line_count(text: str, max_chars: int = 28) -> int:
        raw = " ".join(str(text or "").split())
        if not raw:
            return 0
        width = max(8, int(max_chars))
        words = raw.split(" ")
        lines = 1
        line_len = 0
        for word in words:
            wlen = len(word)
            if line_len == 0:
                line_len = wlen
                continue
            if line_len + 1 + wlen <= width:
                line_len += 1 + wlen
            else:
                lines += 1
                line_len = wlen
        return max(1, lines)

    def _evolution_condition_line_count(
        self,
        conditions: list[tuple[str, str]],
        target_node: str | None = None,
    ) -> int:
        _ = target_node
        item_id = self._evolution_edge_item_id(conditions)
        text = self._evolution_edge_short_text(conditions, item_id)
        return self._estimate_wrapped_line_count(text, max_chars=30)

    @staticmethod
    def _filter_evolution_edges_for_selected_species(
        selected_species_id: str,
        edges: list[tuple[str, str, list[tuple[str, str]]]],
    ) -> tuple[list[tuple[str, str, list[tuple[str, str]]]], set[str]]:
        selected = str(selected_species_id or "").strip()
        if not edges:
            return [], {selected} if selected else set()

        all_nodes: set[str] = set()
        for source, target, _conditions in edges:
            all_nodes.add(source)
            all_nodes.add(target)
        if selected:
            all_nodes.add(selected)

        selected_upper = selected.upper()
        selected_outgoing = sum(1 for source, _target, _conditions in edges if source.upper() == selected_upper)
        # If selected species is a branch point itself (ex: Eevee), keep full family chart.
        if selected_outgoing >= 2:
            return list(edges), all_nodes

        children: dict[str, set[str]] = {}
        parents: dict[str, set[str]] = {}
        for source, target, _conditions in edges:
            children.setdefault(source, set()).add(target)
            parents.setdefault(target, set()).add(source)

        start_nodes = [node for node in all_nodes if node.upper() == selected_upper]
        if not start_nodes and selected:
            start_nodes = [selected]

        ancestors: set[str] = set(start_nodes)
        stack = list(start_nodes)
        while stack:
            current = stack.pop()
            for prev in parents.get(current, set()):
                if prev not in ancestors:
                    ancestors.add(prev)
                    stack.append(prev)

        descendants: set[str] = set(start_nodes)
        stack = list(start_nodes)
        while stack:
            current = stack.pop()
            for nxt in children.get(current, set()):
                if nxt not in descendants:
                    descendants.add(nxt)
                    stack.append(nxt)

        keep_nodes = ancestors | descendants
        if selected:
            keep_nodes.add(selected)
        if not keep_nodes:
            keep_nodes = {selected} if selected else set()

        filtered_edges = [(source, target, conds) for source, target, conds in edges if source in keep_nodes and target in keep_nodes]
        return filtered_edges, keep_nodes

    def update_party_evolution_chart(self):
        if not hasattr(self, "party_evo_canvas"):
            return
        if self._party_evo_rendering:
            return
        species_raw = self.pk_species_var.get().strip()
        try:
            form = int(self.pk_form_var.get().strip()) if self.pk_form_var.get().strip() else 0
        except ValueError:
            form = 0
        try:
            canvas_width = int(self.party_evo_canvas.winfo_width())
        except Exception:
            canvas_width = 0
        render_key = (species_raw.upper(), int(form), max(0, canvas_width))
        if self._party_evo_last_render_key == render_key:
            return
        self._party_evo_rendering = True
        try:
            rendered_height = self._render_evolution_chart_to_canvas(
                self.party_evo_canvas,
                species_raw,
                form,
                no_species_text="Choose a species to view evolution chart.",
                invalid_species_text="Choose a valid species to view evolution chart.",
                show_all_conditions=True,
            )
            try:
                target_height = max(220, int(rendered_height))
            except Exception:
                target_height = 220
            try:
                current_height = int(float(self.party_evo_canvas.cget("height")))
            except Exception:
                current_height = 0
            if abs(current_height - target_height) >= 2:
                try:
                    self.party_evo_canvas.configure(height=target_height)
                except Exception:
                    pass
            self._party_evo_last_render_key = render_key
        finally:
            self._party_evo_rendering = False

    def _render_evolution_chart_to_canvas(
        self,
        canvas: tk.Canvas,
        species_raw: str,
        form: int = 0,
        no_species_text: str = "Choose a species to view evolution chart.",
        invalid_species_text: str = "Choose a valid species to view evolution chart.",
        show_all_conditions: bool = False,
        on_node_click: Any = None,
    ) -> int:
        if canvas is None:
            return 220
        old_top = canvas.yview()[0] if str(canvas.cget("scrollregion")).strip() else 0.0
        canvas.delete("all")

        canvas_key = str(canvas)
        if not hasattr(self, "_evo_canvas_image_refs"):
            self._evo_canvas_image_refs = {}
        refs = self._evo_canvas_image_refs.setdefault(canvas_key, [])
        refs.clear()
        previous_refs = self._party_evo_canvas_image_refs
        self._party_evo_canvas_image_refs = refs
        previous_show_all = bool(getattr(self, "_evo_chart_show_all_conditions", False))
        self._evo_chart_show_all_conditions = bool(show_all_conditions)

        try:
            try:
                canvas.update_idletasks()
            except Exception:
                pass
            width = max(340, canvas.winfo_width())
            viewport_height = max(220, canvas.winfo_height())
            section_margin = 20

            def _reset_view():
                canvas.configure(scrollregion=(0, 0, width, viewport_height))
                canvas.yview_moveto(0.0)

            if not self.catalogs:
                canvas.create_text(8, 8, anchor="nw", text="No game data loaded.")
                _reset_view()
                return viewport_height

            species_text = str(species_raw or "").strip()
            if not species_text:
                canvas.create_text(8, 8, anchor="nw", text=no_species_text)
                _reset_view()
                return viewport_height

            try:
                species_id = self.resolve_species_id(species_text)
            except Exception:
                species_id = extract_internal_id(species_text).strip().lstrip(":")
                if not species_id:
                    canvas.create_text(8, 8, anchor="nw", text=invalid_species_text)
                    _reset_view()
                    return viewport_height

            all_edges = self.catalogs.species_evolution_family_edges(species_id, form=form)
            edges, nodes = self._filter_evolution_edges_for_selected_species(species_id, all_edges)
            undirected_neighbors: dict[str, set[str]] = {}
            direct_children: dict[str, set[str]] = {}
            outgoing_counts: dict[str, int] = {}
            for source, target, _conditions in edges:
                undirected_neighbors.setdefault(source, set()).add(target)
                undirected_neighbors.setdefault(target, set()).add(source)
                direct_children.setdefault(source, set()).add(target)
                outgoing_counts[source] = outgoing_counts.get(source, 0) + 1

            root_branch_count = sum(1 for source, _target, _conds in edges if source.upper() == species_id.upper())
            max_branch_count = max(outgoing_counts.values()) if outgoing_counts else 0
            hub_species_id = species_id
            if max_branch_count > 4:
                hub_species_id = min(
                    (src for src, cnt in outgoing_counts.items() if cnt == max_branch_count),
                    key=str.casefold,
                )
            chart_branch_count = outgoing_counts.get(hub_species_id, root_branch_count)
            node_size = 32
            node_half = node_size // 2
            # Height follows chart content (not viewport), with visible margins.
            base_height = self._estimate_party_evolution_height(chart_branch_count, 320)
            height = max(220, base_height + (section_margin * 2))
            if max_branch_count > 4:
                cluster_count = (chart_branch_count + 3) // 4
                split_cols = self._split_chart_columns_for_width(cluster_count, width, node_half)
                split_rows = (cluster_count + split_cols - 1) // max(1, split_cols)
                root_edge_lines = 1
                if bool(show_all_conditions):
                    for source, target, conds in edges:
                        if source.upper() != hub_species_id.upper():
                            continue
                        root_edge_lines = max(root_edge_lines, self._evolution_condition_line_count(conds, target_node=target))
                line_extra = max(0, root_edge_lines - 1) * 16
                row_height = 268 + line_extra
                needed = (split_rows * row_height) + ((split_rows + 1) * section_margin)
                height = max(height, needed)

            center_degree = len(undirected_neighbors.get(species_id, set()))
            if max_branch_count > 4:
                # Multi-branch species must always use clustered layout.
                if self._draw_split_center_evolution_chart(
                    canvas,
                    hub_species_id,
                    nodes,
                    edges,
                    width,
                    height,
                    node_half,
                    focus_species_id=species_id,
                    on_node_click=on_node_click,
                ):
                    canvas.configure(scrollregion=(0, 0, width, height))
                    canvas.yview_moveto(min(max(old_top, 0.0), 1.0) if height > viewport_height else 0.0)
                    return height
            elif self._draw_branch_bus_evolution_chart(
                canvas,
                species_id,
                nodes,
                edges,
                width,
                height,
                node_half,
                focus_species_id=species_id,
                on_node_click=on_node_click,
            ):
                canvas.configure(scrollregion=(0, 0, width, height))
                canvas.yview_moveto(min(max(old_top, 0.0), 1.0) if height > viewport_height else 0.0)
                return height

            has_multi_branch = center_degree >= 4 or any(len(v) >= 4 for v in direct_children.values())
            use_radial = has_multi_branch or len(nodes) >= 12

            if use_radial:
                positions = self._radial_evolution_positions(nodes, edges, species_id, width, height, node_half)
            else:
                positions = self._layered_evolution_positions(nodes, edges, species_id, width, height, node_half)

            if root_branch_count <= 4:
                positions = self._compress_positions_horizontally(positions, width, node_half, ratio=0.70)

            self._draw_evolution_edges(canvas, edges, positions, node_half)
            self._draw_evolution_nodes(canvas, positions, species_id, node_half, height, on_node_click=on_node_click)
            canvas.configure(scrollregion=(0, 0, width, height))
            canvas.yview_moveto(min(max(old_top, 0.0), 1.0) if height > viewport_height else 0.0)
            return height
        finally:
            self._evo_chart_show_all_conditions = previous_show_all
            if hasattr(self, "party_evo_canvas") and canvas == self.party_evo_canvas:
                self._party_evo_canvas_image_refs = refs
            else:
                self._party_evo_canvas_image_refs = previous_refs

    @staticmethod
    def _compress_positions_horizontally(
        positions: dict[str, tuple[int, int]],
        width: int,
        node_half: int,
        ratio: float,
    ) -> dict[str, tuple[int, int]]:
        if not positions:
            return positions
        safe_ratio = max(0.1, min(1.0, float(ratio)))
        if safe_ratio >= 0.999:
            return positions
        cx = width // 2
        min_x = node_half + 10
        max_x = width - node_half - 10
        out: dict[str, tuple[int, int]] = {}
        for node, (x, y) in positions.items():
            nx = cx + int((x - cx) * safe_ratio)
            nx = max(min_x, min(max_x, nx))
            out[node] = (nx, y)
        return out

    def _layered_evolution_positions(
        self,
        nodes: set[str],
        edges: list[tuple[str, str, list[tuple[str, str]]]],
        species_id: str,
        width: int,
        height: int,
        node_half: int,
    ) -> dict[str, tuple[int, int]]:
        parents: dict[str, set[str]] = {}
        for source, target, _conditions in edges:
            parents.setdefault(target, set()).add(source)

        level_cache: dict[str, int] = {}

        def compute_level(node: str, path: set[str]) -> int:
            if node in level_cache:
                return level_cache[node]
            if node in path:
                return 0
            prev = parents.get(node, set())
            if not prev:
                lvl = 0
            else:
                lvl = 1 + max(compute_level(parent, path | {node}) for parent in prev)
            level_cache[node] = lvl
            return lvl

        for node in nodes:
            compute_level(node, set())

        unique_levels = sorted(set(level_cache.values()))
        if not unique_levels:
            unique_levels = [0]
        remap = {lvl: idx for idx, lvl in enumerate(unique_levels)}
        grouped: dict[int, list[str]] = {}
        for node in nodes:
            grouped.setdefault(remap.get(level_cache.get(node, 0), 0), []).append(node)
        for lvl, arr in grouped.items():
            arr.sort(key=lambda n: (n.upper() != species_id.upper(), n.casefold()))
            grouped[lvl] = arr

        margin_x = 26
        margin_y = 20
        label_space = 20
        level_ids = sorted(grouped.keys())
        if not level_ids:
            level_ids = [0]
            grouped[0] = [species_id]
        col_count = len(level_ids)
        x_for_level: dict[int, int] = {}
        if col_count == 1:
            x_for_level[level_ids[0]] = width // 2
        else:
            span = max(1, width - (2 * margin_x))
            for idx, lvl in enumerate(level_ids):
                x_for_level[lvl] = margin_x + int((idx * span) / (col_count - 1))

        positions: dict[str, tuple[int, int]] = {}
        y_top = margin_y + node_half
        y_bottom = max(y_top, height - margin_y - label_space - node_half)
        for lvl in level_ids:
            arr = grouped.get(lvl, [])
            if not arr:
                continue
            if len(arr) == 1:
                ys = [int((y_top + y_bottom) / 2)]
            else:
                step = (y_bottom - y_top) / (len(arr) - 1)
                ys = [int(y_top + (idx * step)) for idx in range(len(arr))]
            x = x_for_level[lvl]
            for node, y in zip(arr, ys):
                positions[node] = (x, y)
        return positions

    def _radial_evolution_positions(
        self,
        nodes: set[str],
        edges: list[tuple[str, str, list[tuple[str, str]]]],
        species_id: str,
        width: int,
        height: int,
        node_half: int,
    ) -> dict[str, tuple[int, int]]:
        center_x = width // 2
        center_y = height // 2
        positions: dict[str, tuple[int, int]] = {species_id: (center_x, center_y)}

        neighbors: dict[str, set[str]] = {}
        for source, target, _conditions in edges:
            neighbors.setdefault(source, set()).add(target)
            neighbors.setdefault(target, set()).add(source)

        distance: dict[str, int] = {species_id: 0}
        queue: list[str] = [species_id]
        while queue:
            current = queue.pop(0)
            for nxt in sorted(neighbors.get(current, set()), key=str.casefold):
                if nxt in distance:
                    continue
                distance[nxt] = distance[current] + 1
                queue.append(nxt)

        if nodes:
            max_d = max(distance.values()) if distance else 0
            for node in sorted(nodes, key=str.casefold):
                if node not in distance:
                    max_d += 1
                    distance[node] = max_d

        grouped: dict[int, list[str]] = {}
        for node, d in distance.items():
            if d <= 0:
                continue
            grouped.setdefault(d, []).append(node)

        max_radius = max(110, min(width, height) // 2 - (node_half + 20))
        ring_step = 110
        ring_cursor = 0
        for d in sorted(grouped.keys()):
            nodes_in_ring = sorted(grouped[d], key=str.casefold)
            if not nodes_in_ring:
                continue
            radius = min(max_radius, 102 + ((d - 1) * ring_step))
            remaining = list(nodes_in_ring)
            while remaining:
                circumference = max(1.0, 2.0 * math.pi * max(radius, 1))
                capacity = max(5, int(circumference / 98.0))
                take = max(1, min(len(remaining), capacity))
                segment = remaining[:take]
                remaining = remaining[take:]
                start_angle = -90.0 + (ring_cursor * 14.0)
                step = 360.0 / max(1, len(segment))
                for idx, node in enumerate(segment):
                    ang = math.radians(start_angle + (idx * step))
                    x = int(center_x + (radius * math.cos(ang)))
                    y = int(center_y + (radius * math.sin(ang)))
                    x = max(node_half + 10, min(width - node_half - 10, x))
                    y = max(node_half + 10, min(height - node_half - 20, y))
                    positions[node] = (x, y)
                ring_cursor += 1
                if len(remaining) > 0:
                    radius = min(max_radius, radius + 72)
        return positions

    @staticmethod
    def _split_branch_targets_balanced(targets: list[str], max_per_cluster: int = 4) -> list[list[str]]:
        if not targets:
            return []
        max_cap = max(1, int(max_per_cluster))
        cluster_count = (len(targets) + max_cap - 1) // max_cap
        base = len(targets) // cluster_count
        extra = len(targets) % cluster_count
        sizes = [base + (1 if i < extra else 0) for i in range(cluster_count)]
        out: list[list[str]] = []
        cursor = 0
        for size in sizes:
            out.append(targets[cursor : cursor + size])
            cursor += size
        return out

    def _draw_single_evolution_edge(
        self,
        canvas: tk.Canvas,
        sx: int,
        sy: int,
        tx: int,
        ty: int,
        conditions: list[tuple[str, str]],
        node_half: int,
        show_condition_text: bool = True,
        target_node: str | None = None,
    ):
        dx = tx - sx
        dy = ty - sy
        dist = math.sqrt((dx * dx) + (dy * dy))
        if dist <= 0.0:
            return
        ux = dx / dist
        uy = dy / dist
        start_x = sx + int(ux * (node_half + 3))
        start_y = sy + int(uy * (node_half + 3))
        end_x = tx - int(ux * (node_half + 3))
        end_y = ty - int(uy * (node_half + 3))
        canvas.create_line(start_x, start_y, end_x, end_y, arrow=tk.LAST, width=2, fill="#666666")
        mid_x = int((start_x + end_x) / 2)
        mid_y = int((start_y + end_y) / 2)
        item_id = self._evolution_edge_item_id(conditions)
        time_marker = self._evolution_edge_time_marker(conditions, target_node)

        edge_icons: list[tuple[str, Any]] = []
        icon_half_span = 0
        has_item_icon = False
        if item_id:
            item_img = self._get_item_icon_image(item_id)
            if item_img is not None:
                scaled_item = self._chart_scaled_image(item_img, f"evo_item:{item_id}", 2 if item_img.width() >= 40 else 1)
                self._party_evo_canvas_image_refs.append(scaled_item)
                edge_icons.append(("item", scaled_item))
                icon_half_span = max(icon_half_span, max(scaled_item.width(), scaled_item.height()) // 2 + 2)
                has_item_icon = True
        if time_marker:
            edge_icons.append(("time", time_marker))
            icon_half_span = max(icon_half_span, 9)

        if edge_icons:
            icon_gap = 22
            start_icon_x = mid_x - int(((len(edge_icons) - 1) * icon_gap) / 2)
            for idx, (icon_kind, payload) in enumerate(edge_icons):
                icon_x = start_icon_x + (idx * icon_gap)
                icon_y = mid_y
                if icon_kind == "item":
                    assert isinstance(payload, tk.PhotoImage)
                    half = max(8, max(payload.width(), payload.height()) // 2 + 2)
                    self._draw_evolution_marker_badge(canvas, icon_x, icon_y, half=half)
                    canvas.create_image(icon_x, icon_y, image=payload)
                    continue
                marker_kind = str(payload)
                if marker_kind == "day":
                    self._draw_sun_marker(canvas, icon_x, icon_y)
                else:
                    self._draw_moon_marker(canvas, icon_x, icon_y)

        if not show_condition_text:
            return
        force_show_all = bool(getattr(self, "_evo_chart_show_all_conditions", False))
        if not force_show_all and (item_id or time_marker):
            return
        cond_text = self._evolution_edge_short_text(conditions, item_id)
        if not cond_text:
            return
        wrap_width_px = 170
        lines = self._estimate_wrapped_line_count(cond_text, max_chars=30)
        text_x = mid_x
        if has_item_icon:
            # Keep text as close as possible to item icon without touching it.
            text_y = mid_y + icon_half_span + 2
        elif icon_half_span > 0:
            # Non-item markers still keep a minimal non-overlap gap from marker icon.
            text_y = mid_y + icon_half_span + 2
        else:
            # No icon: keep text close to the arrow line without touching.
            text_y = mid_y + 4
        tid = canvas.create_text(
            text_x,
            text_y,
            text=cond_text,
            fill="#555555",
            font=("", 8),
            anchor="n",
            justify="center",
            width=wrap_width_px,
        )
        if lines > 0:
            bbox = canvas.bbox(tid)
            if bbox:
                bg = str(canvas.cget("bg") or "#fbfbfb")
                rect = canvas.create_rectangle(
                    bbox[0] - 2,
                    bbox[1] - 1,
                    bbox[2] + 2,
                    bbox[3] + 1,
                    fill=bg,
                    outline="",
                )
                canvas.tag_raise(tid, rect)

    def _draw_evolution_marker_badge(self, canvas: tk.Canvas, x: int, y: int, half: int = 9):
        bg = str(canvas.cget("bg") or "#fbfbfb")
        r = max(6, int(half))
        canvas.create_rectangle(x - r, y - r, x + r, y + r, fill=bg, outline="#c8c8c8", width=1)

    def _draw_sun_marker(self, canvas: tk.Canvas, x: int, y: int):
        self._draw_evolution_marker_badge(canvas, x, y, half=9)
        r = 5
        canvas.create_oval(x - r, y - r, x + r, y + r, fill="#f3c623", outline="#b98500", width=1)
        for idx in range(8):
            ang = (idx * math.pi) / 4.0
            x1 = x + int(math.cos(ang) * (r + 2))
            y1 = y + int(math.sin(ang) * (r + 2))
            x2 = x + int(math.cos(ang) * (r + 4))
            y2 = y + int(math.sin(ang) * (r + 4))
            canvas.create_line(x1, y1, x2, y2, fill="#b98500", width=1)

    def _draw_moon_marker(self, canvas: tk.Canvas, x: int, y: int):
        self._draw_evolution_marker_badge(canvas, x, y, half=9)
        r = 6
        bg = str(canvas.cget("bg") or "#fbfbfb")
        canvas.create_oval(x - r, y - r, x + r, y + r, fill="#7296df", outline="#4f6ea8", width=1)
        canvas.create_oval(x - r + 3, y - r - 1, x + r - 1, y + r - 1, fill=bg, outline=bg)

    @staticmethod
    def _evolution_edge_time_marker(conditions: list[tuple[str, str]], target_node: str | None = None) -> str:
        for method, _param in conditions:
            key = str(method or "").strip().upper()
            if key == "HAPPINESSDAY":
                return "day"
            if key == "HAPPINESSNIGHT":
                return "night"
            if key == "DAYHOLDITEM":
                return "day"
        target = str(target_node or "").strip().upper()
        if target == "ESPEON":
            return "day"
        if target == "UMBREON":
            return "night"
        return ""

    def _draw_single_evolution_node(
        self,
        canvas: tk.Canvas,
        node: str,
        x: int,
        y: int,
        selected: bool,
        node_half: int,
        canvas_height: int,
        label_anchor: tuple[int, int] | None = None,
        on_node_click: Any = None,
    ):
        _ = label_anchor  # label is intentionally tied directly to its own icon
        left = x - node_half - 2
        top = y - node_half - 2
        right = x + node_half + 2
        bottom = y + node_half + 2
        clickable_items: list[int] = []
        rect_id = canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#e3a100" if selected else "#9a9a9a",
            width=2 if selected else 1,
            fill="#ffffff",
        )
        clickable_items.append(rect_id)
        icon = self._get_party_icon_image_for_fields(node, form=0, shiny=False)
        if icon is not None:
            scaled_icon = self._chart_scaled_image(icon, f"evo_node:{node}", 2 if icon.width() >= 56 else 1)
            self._party_evo_canvas_image_refs.append(scaled_icon)
            image_id = canvas.create_image(x, y, image=scaled_icon)
            clickable_items.append(image_id)
        else:
            text_id = canvas.create_text(x, y, text=node[:2], font=("", 8, "bold"), fill="#333333")
            clickable_items.append(text_id)
        canvas_width = max(1, int(canvas.winfo_width()))
        label_margin_x = 54
        label_x = max(label_margin_x, min(canvas_width - label_margin_x, x))
        # Keep each name directly under its own icon for unambiguous mapping.
        label_y = y + node_half + 16
        label_y = max(14, min(canvas_height - 10, label_y))
        label_id = canvas.create_text(
            label_x,
            label_y,
            text=self._english_species_name_for_id(node),
            fill="#1f1f1f",
            font=("", 8, "bold" if selected else "normal"),
            anchor="center",
        )
        clickable_items.append(label_id)

        if callable(on_node_click):
            for item_id in clickable_items:
                try:
                    canvas.tag_bind(item_id, "<Button-1>", lambda _e, sid=node: on_node_click(sid))
                except Exception:
                    continue

    def _draw_evolution_edges(
        self,
        canvas: tk.Canvas,
        edges: list[tuple[str, str, list[tuple[str, str]]]],
        positions: dict[str, tuple[int, int]],
        node_half: int,
    ):
        for source, target, conditions in edges:
            if source not in positions or target not in positions:
                continue
            sx, sy = positions[source]
            tx, ty = positions[target]
            self._draw_single_evolution_edge(
                canvas,
                sx,
                sy,
                tx,
                ty,
                conditions,
                node_half,
                target_node=target,
            )

    def _draw_evolution_nodes(
        self,
        canvas: tk.Canvas,
        positions: dict[str, tuple[int, int]],
        species_id: str,
        node_half: int,
        canvas_height: int,
        on_node_click: Any = None,
    ):
        for node, (x, y) in positions.items():
            selected = node.upper() == species_id.upper()
            self._draw_single_evolution_node(
                canvas,
                node,
                x,
                y,
                selected,
                node_half,
                canvas_height,
                on_node_click=on_node_click,
            )

    def _draw_bus_outgoing_from_point(
        self,
        canvas: tk.Canvas,
        sx: int,
        sy: int,
        outgoing: list[tuple[str, list[tuple[str, str]]]],
        positions: dict[str, tuple[int, int]],
        node_half: int,
        show_condition_text: bool,
    ):
        rows: list[tuple[str, int, int, list[tuple[str, str]]]] = []
        for target, conditions in outgoing:
            pos = positions.get(target)
            if pos is None:
                continue
            tx, ty = pos
            rows.append((target, tx, ty, conditions))
        if not rows:
            return
        rows.sort(key=lambda row: (row[2], row[1], row[0].casefold()))

        if len(rows) == 1:
            target, tx, ty, conditions = rows[0]
            self._draw_single_evolution_edge(
                canvas,
                sx,
                sy,
                tx,
                ty,
                conditions,
                node_half=node_half,
                show_condition_text=show_condition_text,
                target_node=target,
            )
            return

        min_tx = min(row[1] for row in rows)
        start_x = sx + node_half + 2
        bus_x = sx + max(24, min(68, int((min_tx - sx) * 0.36)))
        bus_x = min(bus_x, min_tx - 14)
        if bus_x < start_x:
            bus_x = start_x

        canvas.create_line(start_x, sy, bus_x, sy, width=2, fill="#666666")
        y_values = [row[2] for row in rows]
        canvas.create_line(bus_x, min(y_values), bus_x, max(y_values), width=2, fill="#666666")

        for target, tx, ty, conditions in rows:
            self._draw_single_evolution_edge(
                canvas,
                bus_x,
                ty,
                tx,
                ty,
                conditions,
                node_half=0,
                show_condition_text=show_condition_text,
                target_node=target,
            )

    def _draw_branch_bus_evolution_chart(
        self,
        canvas: tk.Canvas,
        species_id: str,
        nodes: set[str],
        edges: list[tuple[str, str, list[tuple[str, str]]]],
        width: int,
        height: int,
        node_half: int,
        focus_species_id: str | None = None,
        on_node_click: Any = None,
    ) -> bool:
        outgoing_by_source: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {}
        for source, target, conds in edges:
            outgoing_by_source.setdefault(source, []).append((target, conds))
        if not any(len(v) >= 2 for v in outgoing_by_source.values()):
            return False

        positions = self._layered_evolution_positions(nodes, edges, species_id, width, height, node_half)
        root_branch_count = sum(1 for source, _target, _conds in edges if source.upper() == species_id.upper())
        if root_branch_count <= 4:
            positions = self._compress_positions_horizontally(positions, width, node_half, ratio=0.70)
        for source, outgoing in outgoing_by_source.items():
            if source not in positions:
                continue
            sx, sy = positions[source]
            self._draw_bus_outgoing_from_point(
                canvas,
                sx,
                sy,
                outgoing,
                positions,
                node_half=node_half,
                show_condition_text=True,
            )
        self._draw_evolution_nodes(
            canvas,
            positions,
            focus_species_id or species_id,
            node_half,
            height,
            on_node_click=on_node_click,
        )
        return True

    def _draw_split_center_evolution_chart(
        self,
        canvas: tk.Canvas,
        species_id: str,
        nodes: set[str],
        edges: list[tuple[str, str, list[tuple[str, str]]]],
        width: int,
        height: int,
        node_half: int,
        focus_species_id: str | None = None,
        on_node_click: Any = None,
    ) -> bool:
        children: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {}
        parents: dict[str, set[str]] = {}
        for source, target, conditions in edges:
            children.setdefault(source, []).append((target, conditions))
            parents.setdefault(target, set()).add(source)

        root_children = sorted(children.get(species_id, []), key=lambda row: row[0].casefold())
        if len(root_children) <= 4:
            return False

        side_pad = node_half + 10
        top_pad = node_half + 10
        bottom_pad = node_half + 10
        usable_w = width - (2 * side_pad)
        usable_h = height - top_pad - bottom_pad
        if usable_w < 120:
            side_pad = node_half + 4
            usable_w = width - (2 * side_pad)
        if usable_h < 90:
            top_pad = node_half + 4
            bottom_pad = node_half + 4
            usable_h = height - top_pad - bottom_pad

        root_targets = [target for target, _conds in root_children]
        chunks = self._split_branch_targets_balanced(root_targets, max_per_cluster=4)
        cluster_count = len(chunks)
        if cluster_count == 0:
            return False

        cols = self._split_chart_columns_for_width(cluster_count, width, node_half)
        rows = (cluster_count + cols - 1) // cols
        cell_w = usable_w / max(1, cols)
        cell_h = usable_h / max(1, rows)
        cluster_raise = max(10, int(cell_h * 0.10))

        def cluster_center(index: int) -> tuple[int, int]:
            r = index // cols
            c = index % cols
            # Place center toward the left side of each cell so right branches can spread wider.
            x = int(side_pad + (c * cell_w) + (cell_w * 0.12))
            y = int(top_pad + ((r + 0.52) * cell_h) - cluster_raise)
            row_top = int(top_pad + (r * cell_h))
            row_bottom = int(top_pad + ((r + 1) * cell_h))
            y = max(row_top + node_half + 12, min(row_bottom - node_half - 12, y))
            return x, y

        positions: dict[str, tuple[int, int]] = {}
        group_centers: list[tuple[int, int]] = []
        group_bounds: list[tuple[int, int, int, int]] = []
        group_roots: list[list[str]] = []
        node_group: dict[str, int] = {}
        root_group: dict[str, int] = {}
        root_conditions: dict[str, list[tuple[str, str]]] = {}
        for target, conds in root_children:
            root_conditions.setdefault(target, conds)

        for idx, roots_in_group in enumerate(chunks):
            cx, cy = cluster_center(idx)
            group_centers.append((cx, cy))
            group_roots.append(roots_in_group)
            col = idx % cols
            row = idx // cols
            cell_left = int(side_pad + (col * cell_w))
            cell_right = int(side_pad + ((col + 1) * cell_w))
            cell_top = int(top_pad + (row * cell_h))
            cell_bottom = int(top_pad + ((row + 1) * cell_h))
            left = max(side_pad, cell_left + 8)
            right = min(width - side_pad, cell_right - 8)
            top = max(top_pad, cell_top + 8)
            bottom = min(height - bottom_pad, cell_bottom - 8)
            group_bounds.append((left, right, top, bottom))

            # Keep branch column wide, but shorten center->branch distance to 70% for readability.
            target_right = right - (node_half + 2)
            target_x = cx + int((target_right - cx) * 0.70)
            branch_count = len(roots_in_group)
            if branch_count == 1:
                ys = [cy]
            else:
                # Ensure enough vertical spacing so labels below icons don't overlap the next icon.
                top_limit = top + 12
                bot_limit = bottom - 12
                base_ratio = 0.30 if branch_count <= 3 else 0.40
                cond_lines = 1
                if bool(getattr(self, "_evo_chart_show_all_conditions", False)):
                    for node in roots_in_group:
                        conds = root_conditions.get(node, [])
                        cond_lines = max(cond_lines, self._evolution_condition_line_count(conds, target_node=node))
                min_step = (node_half * 4) + max(0, cond_lines - 1) * 14
                min_span = min_step * (branch_count - 1)
                desired_span = max(int(cell_h * base_ratio * 2.0), min_span)
                max_half_span = max(0, min(cy - top_limit, bot_limit - cy))
                if max_half_span <= 0:
                    top_line = top_limit
                    bot_line = bot_limit
                else:
                    half_span = min(desired_span // 2, max_half_span)
                    top_line = cy - half_span
                    bot_line = cy + half_span
                if bot_line <= top_line:
                    ys = [cy for _ in range(branch_count)]
                else:
                    step = (bot_line - top_line) / max(1, branch_count - 1)
                    ys = [int(top_line + (i * step)) for i in range(branch_count)]

            for node, y in zip(roots_in_group, ys):
                x = target_x
                y = max(top, min(bottom, y))
                positions[node] = (x, y)
                node_group[node] = idx
                root_group[node] = idx

        root_set = set(root_targets)
        extras_by_group: dict[int, list[str]] = {i: [] for i in range(cluster_count)}
        for node in sorted(nodes, key=str.casefold):
            if node == species_id or node in positions:
                continue
            visited: set[str] = set()
            queue: list[str] = [node]
            owner_group = 0
            while queue:
                cur = queue.pop(0)
                for prev in parents.get(cur, set()):
                    if prev in root_set:
                        owner_group = root_group.get(prev, 0)
                        queue = []
                        break
                    if prev != species_id and prev not in visited:
                        visited.add(prev)
                        queue.append(prev)
            extras_by_group.setdefault(owner_group, []).append(node)

        for group_idx, extra_nodes in extras_by_group.items():
            if not extra_nodes:
                continue
            left, right, top, bottom = group_bounds[group_idx]
            base_x = max(
                left + 70,
                max((positions[n][0] for n in group_roots[group_idx] if n in positions), default=left + 70) + 192,
            )
            col_step = 220
            per_col = 4
            cursor = 0
            col = 0
            while cursor < len(extra_nodes):
                seg = extra_nodes[cursor : cursor + per_col]
                x = min(right - (node_half + 6), base_x + (col * col_step))
                if len(seg) == 1:
                    ys = [int((top + bottom) / 2)]
                else:
                    y_top = top + 16
                    y_bottom = bottom - 16
                    step = (y_bottom - y_top) / max(1, len(seg) - 1)
                    ys = [int(y_top + (i * step)) for i in range(len(seg))]
                for node, y in zip(seg, ys):
                    y = max(top, min(bottom, y))
                    positions[node] = (x, y)
                    node_group[node] = group_idx
                cursor += per_col
                col += 1

        for group_idx, roots_in_group in enumerate(group_roots):
            cx, cy = group_centers[group_idx]
            outgoing = [(node, root_conditions.get(node, [])) for node in roots_in_group if node in positions]
            self._draw_bus_outgoing_from_point(
                canvas,
                cx,
                cy,
                outgoing,
                positions,
                node_half=node_half,
                show_condition_text=bool(getattr(self, "_evo_chart_show_all_conditions", False)),
            )

        outgoing_by_source: dict[str, list[tuple[str, list[tuple[str, str]]]]] = {}
        for source, target, conds in edges:
            if source == species_id:
                continue
            if source in positions and target in positions:
                outgoing_by_source.setdefault(source, []).append((target, conds))

        for source, outgoing in outgoing_by_source.items():
            sx, sy = positions[source]
            self._draw_bus_outgoing_from_point(
                canvas,
                sx,
                sy,
                outgoing,
                positions,
                node_half=node_half,
                show_condition_text=True,
            )

        focus_upper = str(focus_species_id or species_id).strip().upper()
        center_selected = species_id.upper() == focus_upper
        for cx, cy in group_centers:
            self._draw_single_evolution_node(
                canvas,
                species_id,
                cx,
                cy,
                center_selected,
                node_half,
                height,
                on_node_click=on_node_click,
            )

        for node, (x, y) in positions.items():
            group_idx = node_group.get(node, 0)
            anchor_center = group_centers[group_idx] if 0 <= group_idx < len(group_centers) else None
            self._draw_single_evolution_node(
                canvas,
                node,
                x,
                y,
                node.upper() == focus_upper,
                node_half,
                height,
                label_anchor=anchor_center,
                on_node_click=on_node_click,
            )
        return True

    def update_party_description(self, source: str | None = None, index: int | None = None, force: bool = False) -> str:
        lock = self._desc_lock.get("party")
        if not force and lock is not None:
            lock_source, lock_index = lock
            if source is None:
                source = lock_source
                index = lock_index
            else:
                norm_index = index if source in {"move", "relearn"} else None
                lock_norm_index = lock_index if lock_source in {"move", "relearn"} else None
                if source != lock_source or norm_index != lock_norm_index:
                    return ""
        if source is None:
            if self.pk_ability_var.get().strip():
                source = "ability"
            elif self.pk_item_var.get().strip():
                source = "item"
            elif self.pk_nature_var.get().strip():
                source = "nature"
            elif self.pk_species_var.get().strip():
                source = "species"
            else:
                source = "move"
        if not self._party_description_has_value(source, index):
            self._party_last_description_text = ""
            self._party_last_description_key = None
            self._hide_party_tooltip()
            return ""
        current_key = self._party_description_key(source, index)
        if self._party_last_description_key == current_key and self._party_last_description_text:
            return self._party_last_description_text
        title = ""
        description = ""
        try:
            if source == "item":
                item_id = self.resolve_selected_party_item_id(self.pk_item_var.get()) if self.pk_item_var.get().strip() else ""
                title = f"Item: {item_id}" if item_id else "Item"
                item_key = str(item_id or "").strip().lstrip(":").upper()
                if item_key in self._custom_manifest_item_specs():
                    description = self._custom_manifest_item_description_text(item_key)
                else:
                    raw_desc = self.catalogs.item_description(item_id) if self.catalogs and item_id else ""
                    summary = self._item_numeric_summary_lines(item_id, raw_desc, "")
                    base_desc, summary = self._resolve_entity_description("item", item_id, raw_desc, summary)
                    description = self._append_mechanics_block(base_desc, summary)
            elif source == "ability":
                ability_id = self.resolve_selected_ability_id(self.pk_ability_var.get())
                title = f"Ability: {ability_id}" if ability_id else "Ability"
                raw_desc = self.catalogs.ability_description(ability_id) if self.catalogs and ability_id else ""
                summary = self._ability_numeric_summary_lines(ability_id, raw_desc, "")
                base_desc, summary = self._resolve_entity_description("ability", ability_id, raw_desc, summary)
                description = self._append_mechanics_block(base_desc, summary)
            elif source == "nature":
                nature_id = self.resolve_selected_nature_id(self.pk_nature_var.get())
                title = f"Nature: {nature_id}" if nature_id else "Nature"
                description = self._nature_description(nature_id)
            elif source == "species":
                species_id = self.resolve_species_id(self.pk_species_var.get()) if self.pk_species_var.get().strip() else ""
                title = f"Species: {species_id}" if species_id else "Species"
                lines: list[str] = []
                if self.catalogs and species_id:
                    form = self._clamp_int(self.pk_form_var.get(), 0, 99, 0)
                    base = self.catalogs.base_stats_for_species(species_id, form=form)
                    if base:
                        lines.append(
                            f"Base stats: HP {base.get('HP', 0)}, Atk {base.get('ATTACK', 0)}, Def {base.get('DEFENSE', 0)}, "
                            f"SpA {base.get('SPECIAL_ATTACK', 0)}, SpD {base.get('SPECIAL_DEFENSE', 0)}, Spe {base.get('SPEED', 0)}."
                        )
                    lines.append(self._species_evolution_description(species_id, form))
                description = "\n\n".join(line for line in lines if line.strip())
            elif source == "relearn":
                idx = index if index is not None else 0
                if 0 <= idx < len(self.relearn_move_vars):
                    move_id = self.resolve_selected_relearn_move_id(self.relearn_move_vars[idx].get())
                else:
                    move_id = ""
                title = f"Relearn Move {idx + 1}: {move_id}" if move_id else "Relearn Move"
                raw_desc = self.catalogs.move_description(move_id) if self.catalogs and move_id else ""
                summary = self._move_numeric_summary_lines(move_id, raw_desc, "")
                base_desc, summary = self._resolve_entity_description("move", move_id, raw_desc, summary)
                description = self._append_mechanics_block(base_desc, summary)
            else:
                idx = index if index is not None else 0
                if 0 <= idx < len(self.move_id_vars):
                    move_id = self.resolve_selected_move_id(self.move_id_vars[idx].get())
                else:
                    move_id = ""
                title = f"Move {idx + 1}: {move_id}" if move_id else "Move"
                raw_desc = self.catalogs.move_description(move_id) if self.catalogs and move_id else ""
                summary = self._move_numeric_summary_lines(move_id, raw_desc, "")
                base_desc, summary = self._resolve_entity_description("move", move_id, raw_desc, summary)
                description = self._append_mechanics_block(base_desc, summary)
        except Exception:
            title = "Description"
            description = ""
        body = description.strip() if description else "No description available."
        text = f"{title}\n\n{body}" if title else body
        self._party_last_description_text = text
        self._party_last_description_key = current_key
        tip = self._party_tooltip_window
        label = self._party_tooltip_label
        if tip is not None and label is not None:
            try:
                if tip.winfo_exists() and label.winfo_exists() and tip.state() != "withdrawn":
                    label.configure(text=text)
            except Exception:
                pass
        if hasattr(self, "party_desc_text"):
            self._set_text_widget_content(self.party_desc_text, text)
        return text

    def update_bag_description(self, source: str | None = None, force: bool = False):
        if not hasattr(self, "bag_desc_text"):
            return
        lock = self._desc_lock.get("bag")
        if not force and lock is not None:
            lock_source, _lock_index = lock
            if source is None:
                source = lock_source
            elif source != lock_source:
                return
        title = "Item"
        description = ""
        try:
            item_id = self.resolve_item_id(self.bag_item_var.get()) if self.bag_item_var.get().strip() else ""
            if item_id:
                title = f"Item: {item_id}"
                item_key = str(item_id or "").strip().lstrip(":").upper()
                if item_key in self._custom_manifest_item_specs():
                    description = self._custom_manifest_item_description_text(item_key)
                else:
                    raw_desc = self.catalogs.item_description(item_id) if self.catalogs else ""
                    summary = self._item_numeric_summary_lines(item_id, raw_desc, "")
                    base_desc, summary = self._resolve_entity_description("item", item_id, raw_desc, summary)
                    description = self._append_mechanics_block(base_desc, summary)
        except Exception:
            pass
        body = description.strip() if description else "No description available."
        self._set_text_widget_content(self.bag_desc_text, f"{title}\n\n{body}")

    def _ability_label_for_id(self, ability_id: str, hidden_ids: set[str]) -> str:
        base = self._english_ability_name_for_id(ability_id)
        if ability_id in hidden_ids:
            return f"{base} (H)"
        return base

    def _party_item_choice_data(self, item_ids: list[str]) -> tuple[list[str], dict[str, str], dict[str, str]]:
        label_to_id: dict[str, str] = {}
        id_to_label: dict[str, str] = {}
        pairs: list[tuple[str, str]] = []
        for raw_item_id in item_ids:
            item_id = str(raw_item_id or "").strip().lstrip(":")
            if not item_id:
                continue
            canonical = self.catalogs.canonical_item_id(item_id) if self.catalogs else item_id
            canonical = canonical or item_id
            if canonical in self._custom_manifest_item_specs():
                label = self._custom_manifest_item_name(canonical)
            else:
                label = self._english_item_name_for_id(canonical)
            if any(existing == label for existing, _iid in pairs):
                label = f"{label} [{canonical}]"
            pairs.append((label, canonical))
        pairs.sort(key=lambda row: row[0].casefold())
        labels: list[str] = []
        for label, item_id in pairs:
            labels.append(label)
            label_to_id[label] = item_id
            id_to_label.setdefault(item_id, label)
        return labels, label_to_id, id_to_label

    def resolve_selected_party_item_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if hasattr(self, "_party_item_label_to_id") and raw in self._party_item_label_to_id:
            return self._party_item_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw).strip()
        try:
            return self.resolve_item_id(cleaned)
        except Exception:
            return ""

    def resolve_selected_bag_item_id(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        if hasattr(self, "_bag_item_label_to_id") and raw in self._bag_item_label_to_id:
            return self._bag_item_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw).strip()
        try:
            return self.resolve_item_id(cleaned)
        except Exception:
            return ""

    def _move_display_name_for_id(self, move_id: str) -> str:
        return self._english_move_name_for_id(move_id)

    def _move_label_for_id(self, move_id: str) -> str:
        return self._move_display_name_for_id(move_id)

    def refresh_party_legality_dropdowns(self, reset_invalid: bool):
        if not self.catalogs:
            return
        if not hasattr(self, "pk_ability_combo"):
            return
        species_raw = self.pk_species_var.get().strip()
        if not species_raw:
            return
        try:
            species_id = self.resolve_species_id(species_raw)
        except Exception:
            return
        try:
            form = int(self.pk_form_var.get().strip()) if self.pk_form_var.get().strip() else 0
        except ValueError:
            form = 0

        ability_ids, hidden_ids = self.catalogs.valid_abilities_for_species(species_id, form=form)
        if not ability_ids:
            ability_ids = sorted(self.catalogs.abilities_by_id.keys(), key=str.casefold)
            hidden_ids = set()
        self._party_hidden_abilities = set(hidden_ids)
        ability_pairs: list[tuple[str, str]] = []
        for ability_id in ability_ids:
            label = self._ability_label_for_id(ability_id, hidden_ids)
            if any(existing == label for existing, _ in ability_pairs):
                label = f"{label} [{ability_id}]"
            ability_pairs.append((label, ability_id))
        ability_pairs.sort(key=lambda x: x[0].casefold())
        self._party_ability_label_to_id = {label: aid for label, aid in ability_pairs}
        self._party_ability_id_to_label = {}
        for label, ability_id in ability_pairs:
            self._party_ability_id_to_label.setdefault(ability_id, label)
        ability_labels = [label for label, _ in ability_pairs]
        self._set_combo_values(self.pk_ability_combo, ability_labels)

        current_ability_id = self.resolve_selected_ability_id(self.pk_ability_var.get())
        if current_ability_id and current_ability_id in self._party_ability_id_to_label:
            self.pk_ability_var.set(self._party_ability_id_to_label[current_ability_id])
        elif reset_invalid:
            self.pk_ability_var.set(ability_labels[0] if ability_labels else "")
        self._sync_ability_index_from_selection(force=reset_invalid)

        valid_move_ids = self.catalogs.valid_moves_for_species(species_id, form=form)
        if not valid_move_ids:
            valid_move_ids = sorted(self.catalogs.moves_by_id.keys(), key=str.casefold)
        move_pairs: list[tuple[str, str]] = []
        for move_id in valid_move_ids:
            label = self._move_label_for_id(move_id)
            if any(existing == label for existing, _ in move_pairs):
                label = f"{label} [{move_id}]"
            move_pairs.append((label, move_id))
        move_pairs.sort(key=lambda x: x[0].casefold())
        self._party_move_label_to_id = {label: mid for label, mid in move_pairs}
        self._party_move_id_to_label = {}
        for label, move_id in move_pairs:
            self._party_move_id_to_label.setdefault(move_id, label)
        move_labels = [label for label, _ in move_pairs]
        for combo in self.move_id_combos:
            self._set_combo_values(combo, move_labels)
        for i, var in enumerate(self.move_id_vars):
            current_move_id = self.resolve_selected_move_id(var.get())
            if current_move_id and current_move_id in self._party_move_id_to_label:
                var.set(self._party_move_id_to_label[current_move_id])
            elif reset_invalid:
                var.set(move_labels[min(i, len(move_labels) - 1)] if move_labels else "")
            self.on_move_combo_changed(i, force_pp=False, update_description=False)

        relearn_ids = self.catalogs.valid_relearn_moves_for_species(species_id, form=form)
        if not relearn_ids:
            relearn_ids = valid_move_ids
        relearn_pairs: list[tuple[str, str]] = []
        for move_id in relearn_ids:
            label = self._move_label_for_id(move_id)
            if any(existing == label for existing, _ in relearn_pairs):
                label = f"{label} [{move_id}]"
            relearn_pairs.append((label, move_id))
        relearn_pairs.sort(key=lambda x: x[0].casefold())
        self._party_relearn_label_to_id = {label: mid for label, mid in relearn_pairs}
        self._party_relearn_id_to_label = {}
        for label, move_id in relearn_pairs:
            self._party_relearn_id_to_label.setdefault(move_id, label)
        relearn_labels = ["(None)"] + [label for label, _ in relearn_pairs]
        for combo in self.relearn_move_combos:
            self._set_combo_values(combo, relearn_labels)
        for var in self.relearn_move_vars:
            current_move_id = self.resolve_selected_relearn_move_id(var.get())
            if current_move_id and current_move_id in self._party_relearn_id_to_label:
                var.set(self._party_relearn_id_to_label[current_move_id])
            elif reset_invalid:
                var.set("(None)")

    def resolve_selected_ability_id(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        if raw in self._party_ability_label_to_id:
            return self._party_ability_label_to_id[raw]
        cleaned = re.sub(r"\s+\(H\)\s*$", "", raw)
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        try:
            return self.resolve_ability_id(cleaned)
        except Exception:
            return ""

    def resolve_selected_move_id(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        if raw in self._party_move_label_to_id:
            return self._party_move_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw)
        try:
            return self.resolve_move_id(cleaned)
        except Exception:
            return ""

    def resolve_selected_relearn_move_id(self, text: str) -> str:
        raw = text.strip()
        if not raw or raw == "(None)":
            return ""
        if raw in self._party_relearn_label_to_id:
            return self._party_relearn_label_to_id[raw]
        cleaned = re.sub(r"\s+\[[^\]]+\]\s*$", "", raw)
        try:
            return self.resolve_move_id(cleaned)
        except Exception:
            return ""

    def _nature_changed_stats(self) -> tuple[str | None, str | None]:
        nature = self.resolve_selected_nature_id(self.pk_nature_var.get())
        if not nature:
            return None, None
        return NATURE_EFFECTS.get(nature, (None, None))

    def _update_nature_stat_label_colors(self):
        up, down = self._nature_changed_stats()
        for stat_id, lbl in self.party_stat_name_labels.items():
            if stat_id == up:
                lbl.configure(fg="#c03535")
            elif stat_id == down:
                lbl.configure(fg="#2b5fc9")
            else:
                lbl.configure(fg="black")

    def _update_nature_effect_labels(self):
        up, down = self._nature_changed_stats()
        if not up or not down:
            self.pk_nature_effect_var.set("Nature effect: neutral")
            self.pk_nature_neutral_var.set("Neutral")
            self.pk_nature_up_var.set("")
            self.pk_nature_sep_var.set("")
            self.pk_nature_down_var.set("")
            return
        self.pk_nature_effect_var.set("Nature effect:")
        self.pk_nature_neutral_var.set("")
        self.pk_nature_up_var.set(f"{STAT_SHORT_LABELS.get(up, up)}↑")
        self.pk_nature_sep_var.set(" / ")
        self.pk_nature_down_var.set(f"{STAT_SHORT_LABELS.get(down, down)}↓")

    def _read_symbol_stat_dict(self, pkmn: core.RubyObject, attr: str) -> dict[str, int]:
        raw = core.read_attr(pkmn, attr, {})
        out: dict[str, int] = {sid: 0 for sid, _ in STAT_ORDER}
        if not isinstance(raw, dict):
            return out
        for key, value in raw.items():
            name = symbol_name(key).strip().lstrip(":").upper()
            if name not in out:
                continue
            try:
                out[name] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    def _write_symbol_stat_dict(self, pkmn: core.RubyObject, attr: str, values: dict[str, int]):
        current = core.read_attr(pkmn, attr, {})
        key_map: dict[str, Any] = {}
        if isinstance(current, dict):
            for key in current.keys():
                key_map[symbol_name(key).strip().lstrip(":").upper()] = key
        out: dict[Any, int] = {}
        for sid, _label in STAT_ORDER:
            key = key_map.get(sid, core.Symbol(sid))
            out[key] = int(values.get(sid, 0))
        pkmn.attributes[attr] = out

    @staticmethod
    def _clamp_int(text: str, low: int, high: int, default: int = 0) -> int:
        try:
            value = int(text.strip())
        except (TypeError, ValueError, AttributeError):
            value = default
        if value < low:
            return low
        if value > high:
            return high
        return value

    def _current_species_form(self) -> tuple[str | None, int]:
        species_raw = self.pk_species_var.get().strip()
        if not species_raw:
            return None, 0
        try:
            species_id = self.resolve_species_id(species_raw)
        except Exception:
            return None, 0
        try:
            form = int(self.pk_form_var.get().strip()) if self.pk_form_var.get().strip() else 0
        except ValueError:
            form = 0
        return species_id, form

    def _sync_exp_with_level(self, force: bool = False):
        level = self._clamp_int(self.pk_level_var.get(), 1, 100, 1)
        self.pk_level_var.set(str(level))
        species_id, form = self._current_species_form()
        if not species_id or not self.catalogs:
            if force and not self.pk_exp_var.get().strip():
                self.pk_exp_var.set("0")
            return
        minimum_exp = self.catalogs.minimum_exp_for_level(species_id, level, form=form)
        current_exp = self._clamp_int(self.pk_exp_var.get(), 0, 99999999, minimum_exp)
        if force or current_exp < minimum_exp:
            current_exp = minimum_exp
        self.pk_exp_var.set(str(current_exp))

    def _nature_multiplier(self, stat_id: str) -> int:
        up, down = self._nature_changed_stats()
        if stat_id == up:
            return 110
        if stat_id == down:
            return 90
        return 100

    def _calc_stat_value(self, stat_id: str, base: int, level: int, iv: int, ev: int) -> int:
        if stat_id == "HP":
            if base == 1:
                return 1
            return (((base * 2) + iv + (ev // 4)) * level // 100) + level + 10
        core_val = (((base * 2) + iv + (ev // 4)) * level // 100) + 5
        return (core_val * self._nature_multiplier(stat_id)) // 100

    def _hidden_power_type_from_ivs(self, ivs: dict[str, int]) -> str:
        if not self.catalogs:
            return "Unknown"
        types = self.catalogs.hidden_power_type_ids
        if not types:
            return "Unknown"
        idx_type = 0
        idx_type |= (ivs.get("HP", 0) & 1)
        idx_type |= (ivs.get("ATTACK", 0) & 1) << 1
        idx_type |= (ivs.get("DEFENSE", 0) & 1) << 2
        idx_type |= (ivs.get("SPEED", 0) & 1) << 3
        idx_type |= (ivs.get("SPECIAL_ATTACK", 0) & 1) << 4
        idx_type |= (ivs.get("SPECIAL_DEFENSE", 0) & 1) << 5
        idx_type = (len(types) - 1) * idx_type // 63
        if idx_type < 0 or idx_type >= len(types):
            return "Unknown"
        type_id = types[idx_type]
        return type_id

    def _current_editor_iv_values(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            out[sid] = self._clamp_int(self.party_iv_vars[sid].get(), 0, 31, 0)
        total = sum(out.values())
        if total > 186:
            overflow = total - 186
            for sid, _label in reversed(STAT_ORDER):
                if overflow <= 0:
                    break
                reducible = min(overflow, out[sid])
                out[sid] -= reducible
                overflow -= reducible
        return out

    def _is_advanced_mode(self) -> bool:
        return bool(self.advanced_mode_var.get()) if hasattr(self, "advanced_mode_var") else False

    def _toggle_advanced_mode(self, _event=None):
        current = self._is_advanced_mode()
        self.advanced_mode_var.set(not current)
        self._apply_advanced_mode_ui(update_status=True)
        return "break"

    def _apply_advanced_mode_ui(self, update_status: bool):
        advanced = self._is_advanced_mode()

        # Persist preference so advanced visibility survives app relaunch.
        self.app_settings["advanced_mode"] = bool(advanced)
        self._save_app_settings()

        for btn_name in (
            "apply_ev_patch_btn",
            "rollback_ev_patch_btn",
            "probe_patch_capability_btn",
            "rebuild_patch_adapter_btn",
        ):
            btn = getattr(self, btn_name, None)
            if btn is None:
                continue
            if advanced:
                if not btn.winfo_ismapped():
                    btn.pack(side="left", padx=2)
            else:
                if btn.winfo_manager():
                    btn.pack_forget()

        # CustomItem is part of the normal workflow now; keep it visible even
        # when advanced-only maintenance buttons are hidden.
        if hasattr(self, "nb") and hasattr(self, "custom_item_tab"):
            if not self._custom_item_tab_visible:
                self.nb.add(self.custom_item_tab, text="CustomItem")
                self._custom_item_tab_visible = True

        if hasattr(self, "party_ev_mode_var"):
            before_evs = self._current_editor_ev_values()
            self.party_ev_mode_var.set("Advanced" if advanced else "Basic")
            after_evs = self._current_editor_ev_values()
            for sid, _label in STAT_ORDER:
                self.party_ev_vars[sid].set(str(after_evs[sid]))
            if hasattr(self, "party_ev_note_var"):
                self._apply_party_ev_mode_ui()
            if hasattr(self, "party_base_stat_vars"):
                self._refresh_stats_from_editor_inputs()
            if before_evs != after_evs:
                entry, _slot_label = self._selected_slot_entry()
                if isinstance(entry, core.RubyObject):
                    self._apply_stat_block_to_pokemon(entry, preserve_hp_ratio=True)
                    self.mark_modified()

        if hasattr(self, "team_ev_vars"):
            team_evs = self._team_current_ev_values()
            for sid, _label in STAT_ORDER:
                self.team_ev_vars[sid].set(str(team_evs[sid]))
            if self._team_slots:
                idx = max(0, min(int(getattr(self, "_team_selected_slot", 0)), len(self._team_slots) - 1))
                self._team_slots[idx]["evs"] = dict(team_evs)
            self._team_refresh_stat_editor()

        if update_status:
            self.set_status(f"Advanced mode: {'ON' if advanced else 'OFF'}")

    def _is_party_ev_basic_mode(self) -> bool:
        mode_var = getattr(self, "party_ev_mode_var", None)
        return isinstance(mode_var, tk.StringVar) and mode_var.get().strip().lower() == "basic"

    def _normalize_basic_ev_values(
        self,
        values: dict[str, int],
        preferred_stat: str | None = None,
    ) -> dict[str, int]:
        evs: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            evs[sid] = self._clamp_int(str(values.get(sid, 0)), 0, 252, 0)

        total = sum(evs.values())
        if total <= 510:
            return evs

        preferred_key = preferred_stat.upper() if preferred_stat else ""
        if preferred_key in evs:
            others_total = total - evs[preferred_key]
            allowed_for_preferred = max(0, min(252, 510 - others_total))
            if evs[preferred_key] > allowed_for_preferred:
                evs[preferred_key] = allowed_for_preferred
            total = sum(evs.values())

        if total <= 510:
            return evs

        overflow = total - 510
        reduce_order = [sid for sid, _label in reversed(STAT_ORDER) if sid != preferred_key]
        if preferred_key in evs:
            reduce_order.append(preferred_key)
        for sid in reduce_order:
            if overflow <= 0:
                break
            reducible = min(overflow, evs[sid])
            if reducible <= 0:
                continue
            evs[sid] -= reducible
            overflow -= reducible
        return evs

    def _current_editor_ev_values(self, preferred_stat: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            out[sid] = self._clamp_int(self.party_ev_vars[sid].get(), 0, 252, 0)
        if self._is_party_ev_basic_mode():
            return self._normalize_basic_ev_values(out, preferred_stat=preferred_stat)
        return out

    def _apply_party_ev_mode_ui(self):
        if not hasattr(self, "party_ev_note_var"):
            return
        basic_mode = self._is_party_ev_basic_mode()
        if hasattr(self, "party_max_evs_btn"):
            if basic_mode:
                self.party_max_evs_btn.grid_remove()
            else:
                self.party_max_evs_btn.grid()
        if hasattr(self, "party_evs_left_wrap"):
            if basic_mode:
                self.party_evs_left_wrap.grid()
            else:
                self.party_evs_left_wrap.grid_remove()
        if basic_mode:
            ev_total = sum(self._current_editor_ev_values().values())
            remaining = max(0, 510 - ev_total)
            self.party_evs_left_var.set(str(remaining))
            if hasattr(self, "party_evs_left_value_label"):
                if remaining <= 0:
                    color = "#c62828"
                elif remaining <= 126:
                    color = "#d97706"
                elif remaining <= 252:
                    color = "#b08a00"
                else:
                    color = "#2e7d32"
                self.party_evs_left_value_label.configure(fg=color)
            self.party_ev_note_var.set("IV limit: 0-31 each, total capped at 186. EV limit: 0-252 each, total capped at 510.")
        else:
            self.party_evs_left_var.set("-")
            if hasattr(self, "party_evs_left_value_label"):
                self.party_evs_left_value_label.configure(fg="#2f5fd0")
            self.party_ev_note_var.set(
                "IV limit: 0-31 each, total capped at 186. EV limit: 0-252 each (no total cap)."
            )

    def _toggle_party_ev_mode(self, _event=None):
        if not hasattr(self, "party_ev_mode_var"):
            return "break"
        before_evs = self._current_editor_ev_values()
        if self._is_party_ev_basic_mode():
            self.party_ev_mode_var.set("Advanced")
        else:
            self.party_ev_mode_var.set("Basic")
        after_evs = self._current_editor_ev_values()
        for sid, _label in STAT_ORDER:
            self.party_ev_vars[sid].set(str(after_evs[sid]))
        self._refresh_stats_from_editor_inputs()
        if after_evs != before_evs:
            entry, _slot_label = self._selected_slot_entry()
            if isinstance(entry, core.RubyObject):
                self._apply_stat_block_to_pokemon(entry, preserve_hp_ratio=True)
                self.mark_modified()
        mode_label = "Basic" if self._is_party_ev_basic_mode() else "Advanced"
        self.set_status(f"Party EV mode: {mode_label}")
        if hasattr(self, "team_ev_vars"):
            team_evs = self._team_current_ev_values()
            for sid, _label in STAT_ORDER:
                self.team_ev_vars[sid].set(str(team_evs[sid]))
            if self._team_slots:
                idx = max(0, min(int(getattr(self, "_team_selected_slot", 0)), len(self._team_slots) - 1))
                self._team_slots[idx]["evs"] = dict(team_evs)
                self._team_refresh_stat_editor()
                self._team_update_slot_card(idx)
        return "break"

    def _refresh_stats_from_editor_inputs(self):
        species_id, form = self._current_species_form()
        base_stats = self.catalogs.base_stats_for_species(species_id, form=form) if self.catalogs and species_id else {}
        level = self._clamp_int(self.pk_level_var.get(), 1, 100, 1)
        self.pk_level_var.set(str(level))
        self._sync_exp_with_level(force=False)

        ivs = self._current_editor_iv_values()
        evs = self._current_editor_ev_values()
        for sid, _label in STAT_ORDER:
            self.party_iv_vars[sid].set(str(ivs[sid]))
            self.party_ev_vars[sid].set(str(evs[sid]))
            self.party_base_stat_vars[sid].set(str(base_stats.get(sid, 0)))

        computed: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            stat_value = self._calc_stat_value(sid, base_stats.get(sid, 0), level, ivs[sid], evs[sid])
            computed[sid] = stat_value
            self.party_final_stat_vars[sid].set(str(stat_value))

        self.pk_totalhp_var.set(str(computed.get("HP", 0)))
        self.pk_attack_var.set(str(computed.get("ATTACK", 0)))
        self.pk_defense_var.set(str(computed.get("DEFENSE", 0)))
        self.pk_spatk_var.set(str(computed.get("SPECIAL_ATTACK", 0)))
        self.pk_spdef_var.set(str(computed.get("SPECIAL_DEFENSE", 0)))
        self.pk_speed_var.set(str(computed.get("SPEED", 0)))
        current_hp_raw = self.pk_hp_var.get().strip()
        computed_hp = computed.get("HP", 0)
        if not current_hp_raw:
            current_hp = computed_hp
        else:
            current_hp = self._clamp_int(current_hp_raw, 0, computed_hp, computed_hp)
        self.pk_hp_var.set(str(current_hp))
        hidden_power_type = self._hidden_power_type_from_ivs(ivs)
        self.party_hidden_power_var.set(hidden_power_type)
        if hasattr(self, "party_hidden_power_chip_host"):
            hp_ids = self._extract_type_ids(hidden_power_type)
            self._render_type_chip_row(
                self.party_hidden_power_chip_host,
                hp_ids,
                short=False,
                empty_text=hidden_power_type or "Unknown",
            )
        self._apply_party_ev_mode_ui()
        self._update_nature_stat_label_colors()
        self.update_party_editor_preview()

    def on_iv_ev_focus_out(self, kind: str, stat_id: str):
        stat_id = stat_id.upper()
        if kind == "iv":
            values = self._current_editor_iv_values()
            for sid, _label in STAT_ORDER:
                self.party_iv_vars[sid].set(str(values[sid]))
        else:
            values = self._current_editor_ev_values(preferred_stat=stat_id)
            for sid, _label in STAT_ORDER:
                self.party_ev_vars[sid].set(str(values[sid]))
        self._refresh_stats_from_editor_inputs()

        entry, _slot_label = self._selected_slot_entry()
        if isinstance(entry, core.RubyObject):
            self._apply_stat_block_to_pokemon(entry, preserve_hp_ratio=True)
            self.mark_modified()

    def set_all_evs_max(self):
        if self._is_party_ev_basic_mode():
            return
        for sid, _label in STAT_ORDER:
            self.party_ev_vars[sid].set("252")
        self._refresh_stats_from_editor_inputs()
        entry, _slot_label = self._selected_slot_entry()
        if isinstance(entry, core.RubyObject):
            self._apply_stat_block_to_pokemon(entry, preserve_hp_ratio=True)
            self.mark_modified()

    def _apply_stat_block_to_pokemon(self, pkmn: core.RubyObject, preserve_hp_ratio: bool, forced_hp: int | None = None):
        ivs = self._current_editor_iv_values()
        evs = self._current_editor_ev_values()
        self._write_symbol_stat_dict(pkmn, "@iv", ivs)
        self._write_symbol_stat_dict(pkmn, "@ev", evs)

        final_stats: dict[str, int] = {}
        for sid, _label in STAT_ORDER:
            final_stats[sid] = self._clamp_int(self.party_final_stat_vars[sid].get(), 0, 9999, 0)

        old_total_hp = core.read_attr(pkmn, "@totalhp", final_stats["HP"])
        old_hp = core.read_attr(pkmn, "@hp", final_stats["HP"])
        try:
            old_total_hp = int(old_total_hp)
        except (TypeError, ValueError):
            old_total_hp = final_stats["HP"]
        try:
            old_hp = int(old_hp)
        except (TypeError, ValueError):
            old_hp = final_stats["HP"]

        if forced_hp is not None:
            new_hp = max(0, min(final_stats["HP"], int(forced_hp)))
        elif preserve_hp_ratio and old_total_hp > 0:
            new_hp = old_hp + (final_stats["HP"] - old_total_hp)
            new_hp = max(1, min(final_stats["HP"], new_hp))
        else:
            new_hp = final_stats["HP"]

        pkmn.attributes["@totalhp"] = final_stats["HP"]
        pkmn.attributes["@hp"] = new_hp
        pkmn.attributes["@attack"] = final_stats["ATTACK"]
        pkmn.attributes["@defense"] = final_stats["DEFENSE"]
        pkmn.attributes["@spatk"] = final_stats["SPECIAL_ATTACK"]
        pkmn.attributes["@spdef"] = final_stats["SPECIAL_DEFENSE"]
        pkmn.attributes["@speed"] = final_stats["SPEED"]

        self.pk_hp_var.set(str(new_hp))
        self.pk_totalhp_var.set(str(final_stats["HP"]))
        self.pk_attack_var.set(str(final_stats["ATTACK"]))
        self.pk_defense_var.set(str(final_stats["DEFENSE"]))
        self.pk_spatk_var.set(str(final_stats["SPECIAL_ATTACK"]))
        self.pk_spdef_var.set(str(final_stats["SPECIAL_DEFENSE"]))
        self.pk_speed_var.set(str(final_stats["SPEED"]))
        self.update_party_editor_preview()

    def load_species_defaults_into_editor(self):
        species_id, form = self._current_species_form()
        if not species_id:
            messagebox.showwarning("Missing Species", "Choose a species first.")
            return
        level = self._clamp_int(self.pk_level_var.get(), 1, 100, 1)
        self.pk_level_var.set(str(level))
        if not self.pk_nature_var.get().strip():
            self.pk_nature_var.set(self._party_nature_id_to_label.get("HARDY", self._nature_label_for_id("HARDY")))
        if not self.pk_happiness_var.get().strip():
            self.pk_happiness_var.set("70")
        if not self.pk_name_var.get().strip():
            self.pk_name_var.set(self._english_species_name_for_id(species_id))
        if not self.pk_gender_var.get().strip():
            self.pk_gender_var.set("0")
        self.pk_field_status_var.set(PARTY_FIELD_STATUS_DEFAULT_LABEL)
        self._sync_exp_with_level(force=True)

        for sid, _label in STAT_ORDER:
            self.party_iv_vars[sid].set("31")
            self.party_ev_vars[sid].set("0")

        self.refresh_party_legality_dropdowns(reset_invalid=True)
        self._sync_ability_index_from_selection(force=True)
        initial_moves = self.catalogs.initial_moves_for_species(species_id, form=form, level=level) if self.catalogs else []
        for i in range(4):
            if i < len(initial_moves):
                move_id = initial_moves[i]
                self.move_id_vars[i].set(self._party_move_id_to_label.get(move_id, self._move_label_for_id(move_id)))
            else:
                self.move_id_vars[i].set("")
            self.move_ppup_vars[i].set("0")
            move_id = self.resolve_selected_move_id(self.move_id_vars[i].get())
            self.move_pp_vars[i].set(str(self._move_max_pp(move_id, 0)) if move_id else "")

        relearn_ids = self.catalogs.valid_relearn_moves_for_species(species_id, form=form) if self.catalogs else []
        for i in range(4):
            if i < len(relearn_ids):
                mid = relearn_ids[i]
                self.relearn_move_vars[i].set(self._party_relearn_id_to_label.get(mid, self._move_label_for_id(mid)))
            else:
                self.relearn_move_vars[i].set("(None)")

        self._refresh_stats_from_editor_inputs()
        self._update_nature_effect_labels()
        self.update_party_evolution_chart()
        self.update_party_description("species")

    def _clone_ruby_object(self, obj: core.RubyObject) -> core.RubyObject:
        buf = io.BytesIO()
        core.marshal_write(buf, obj, cls=core.SaveWriter)
        buf.seek(0)
        if buf.read(1) != b"\x04" or buf.read(1) != b"\x08":
            raise ValueError("Failed to clone object (marshal header mismatch).")
        reader = core.CycleAwareReader(buf, registry=core.global_registry)
        cloned = reader.read()
        if not isinstance(cloned, core.RubyObject):
            raise TypeError("Cloned object is not a RubyObject.")
        return cloned

    def _find_template_pokemon(self) -> core.RubyObject | None:
        player = self.get_root_key("player")
        party = core.read_attr(player, "@party", []) if isinstance(player, core.RubyObject) else []
        if isinstance(party, list):
            for p in party:
                if isinstance(p, core.RubyObject):
                    return p
        boxes = self._get_storage_boxes()
        for box in boxes:
            for p in self._get_box_pokemon_list(box):
                if isinstance(p, core.RubyObject):
                    return p
        return None

    def _set_selected_slot_entry(self, value: Any):
        if self._party_selected_mode is None or self._party_selected_index is None:
            raise ValueError("No slot selected.")
        idx = self._party_selected_index
        if self._party_selected_mode == "party":
            player = self.get_root_key("player")
            if not isinstance(player, core.RubyObject):
                raise ValueError("Player section missing.")
            party = core.read_attr(player, "@party", [])
            if not isinstance(party, list):
                party = []
            while len(party) <= idx:
                party.append(None)
            party[idx] = value
            player.attributes["@party"] = party
            return
        boxes = self._get_storage_boxes()
        box_idx = self._party_selected_box_index if self._party_selected_box_index is not None else self._selected_box_index()
        if box_idx < 0 or box_idx >= len(boxes):
            raise ValueError("Box index out of range.")
        box_obj = boxes[box_idx]
        if not isinstance(box_obj, core.RubyObject):
            raise ValueError("Selected box is invalid.")
        box_data = self._get_box_pokemon_list(box_obj)
        while len(box_data) <= idx:
            box_data.append(None)
        box_data[idx] = value
        box_obj.attributes["@pokemon"] = box_data

    def _create_new_pokemon_from_editor(self) -> core.RubyObject:
        self._refresh_stats_from_editor_inputs()
        self._sync_exp_with_level(force=True)
        species_id, form = self._current_species_form()
        if not species_id:
            raise ValueError("Species is required.")
        template = self._party_template_pokemon or self._find_template_pokemon()
        if template is None:
            pkmn = core.RubyObject("Pokemon", {})
        else:
            self._party_template_pokemon = template
            pkmn = self._clone_ruby_object(template)

        level = self._clamp_int(self.pk_level_var.get(), 1, 100, 1)
        pkmn.attributes["@species"] = core.Symbol(species_id)
        if "@form" in pkmn.attributes:
            pkmn.attributes["@form"] = form
        if "@level" in pkmn.attributes:
            pkmn.attributes["@level"] = level
        if "@name" in pkmn.attributes:
            pkmn.attributes["@name"] = self.pk_name_var.get().strip() or species_id
        if "@exp" in pkmn.attributes:
            pkmn.attributes["@exp"] = self._clamp_int(self.pk_exp_var.get(), 0, 99999999, 0)
        if "@nature" in pkmn.attributes:
            nature = self.resolve_selected_nature_id(self.pk_nature_var.get()) or "HARDY"
            pkmn.attributes["@nature"] = core.Symbol(nature)
        status_id, status_count = self._resolve_party_field_status_spec(self.pk_field_status_var.get())
        if "@status" in pkmn.attributes:
            pkmn.attributes["@status"] = core.Symbol(status_id)
        if "@statusCount" in pkmn.attributes:
            pkmn.attributes["@statusCount"] = status_count
        if "@item" in pkmn.attributes:
            item_id = self.resolve_selected_party_item_id(self.pk_item_var.get().strip()) if self.pk_item_var.get().strip() else ""
            pkmn.attributes["@item"] = core.Symbol(item_id) if item_id else None
        if "@ability" in pkmn.attributes:
            ability_id = self.resolve_selected_ability_id(self.pk_ability_var.get())
            if not ability_id and self._party_ability_id_to_label:
                ability_id = next(iter(self._party_ability_id_to_label.keys()))
            pkmn.attributes["@ability"] = core.Symbol(ability_id) if ability_id else None
        if "@ability_index" in pkmn.attributes:
            pkmn.attributes["@ability_index"] = self._clamp_int(self.pk_ability_index_var.get(), 0, 3, 0)
        if "@gender" in pkmn.attributes:
            pkmn.attributes["@gender"] = self._clamp_int(self.pk_gender_var.get(), 0, 2, 0)
        if "@happiness" in pkmn.attributes:
            pkmn.attributes["@happiness"] = self._clamp_int(self.pk_happiness_var.get(), 0, 255, 70)
        if "@shiny" in pkmn.attributes:
            pkmn.attributes["@shiny"] = bool(self.pk_shiny_var.get())
        if "@super_shiny" in pkmn.attributes:
            pkmn.attributes["@super_shiny"] = bool(self.pk_super_shiny_var.get())
        if "@personalID" in pkmn.attributes:
            pkmn.attributes["@personalID"] = random.randint(0, 2**32 - 1)
        if "@obtain_level" in pkmn.attributes:
            pkmn.attributes["@obtain_level"] = self._clamp_int(self.pk_obtain_level_var.get(), 0, 100, level)
        if "@obtain_map" in pkmn.attributes:
            pkmn.attributes["@obtain_map"] = self._clamp_int(self.pk_obtain_map_var.get(), 0, 999999, 0)
        if "@obtain_method" in pkmn.attributes:
            pkmn.attributes["@obtain_method"] = self._clamp_int(self.pk_obtain_method_var.get(), 0, 999, 0)
        if "@hatched_map" in pkmn.attributes:
            pkmn.attributes["@hatched_map"] = self._clamp_int(self.pk_hatched_map_var.get(), 0, 999999, 0)

        moves = core.read_attr(pkmn, "@moves", [])
        if not isinstance(moves, list):
            moves = []
        initial_moves = self.catalogs.initial_moves_for_species(species_id, form=form, level=level) if self.catalogs else []
        while len(moves) < 4:
            moves.append(core.RubyObject("Pokemon::Move", {"@id": core.Symbol("TACKLE"), "@pp": 35, "@ppup": 0}))
        for i, move_obj in enumerate(moves[:4]):
            if not isinstance(move_obj, core.RubyObject):
                move_obj = core.RubyObject("Pokemon::Move", {"@id": core.Symbol("TACKLE"), "@pp": 35, "@ppup": 0})
                moves[i] = move_obj
            move_id = self.resolve_selected_move_id(self.move_id_vars[i].get()) if self.move_id_vars[i].get().strip() else ""
            if not move_id and i < len(initial_moves):
                move_id = initial_moves[i]
            if not move_id:
                continue
            move_obj.attributes["@id"] = core.Symbol(move_id)
            ppup_value = self._clamp_int(self.move_ppup_vars[i].get(), 0, 3, 0)
            max_pp = self._move_max_pp(move_id, ppup_value)
            if "@ppup" in move_obj.attributes:
                move_obj.attributes["@ppup"] = ppup_value
            if "@pp" in move_obj.attributes:
                move_obj.attributes["@pp"] = self._clamp_int(self.move_pp_vars[i].get(), 0, max_pp, max_pp)
        pkmn.attributes["@moves"] = moves

        if "@first_moves" in pkmn.attributes:
            relearn_ids: list[str] = []
            for i in range(4):
                mid = self.resolve_selected_relearn_move_id(self.relearn_move_vars[i].get())
                if mid and mid not in relearn_ids:
                    relearn_ids.append(mid)
            if not relearn_ids:
                relearn_ids = initial_moves[:]
            pkmn.attributes["@first_moves"] = [core.Symbol(mid) for mid in relearn_ids]
        elif initial_moves:
            pkmn.attributes["@first_moves"] = [core.Symbol(mid) for mid in initial_moves[:4]]

        # Ensure essential fields exist for newly-created objects.
        pkmn.attributes.setdefault("@species", core.Symbol(species_id))
        pkmn.attributes.setdefault("@form", form)
        pkmn.attributes.setdefault("@level", level)
        pkmn.attributes.setdefault("@exp", self._clamp_int(self.pk_exp_var.get(), 0, 99999999, 0))
        pkmn.attributes.setdefault("@name", self.pk_name_var.get().strip() or species_id)
        pkmn.attributes.setdefault("@nature", core.Symbol(self.resolve_selected_nature_id(self.pk_nature_var.get()) or "HARDY"))
        pkmn.attributes.setdefault("@happiness", self._clamp_int(self.pk_happiness_var.get(), 0, 255, 70))
        pkmn.attributes.setdefault("@gender", self._clamp_int(self.pk_gender_var.get(), 0, 2, 0))
        pkmn.attributes.setdefault("@status", core.Symbol(status_id))
        pkmn.attributes.setdefault("@statusCount", status_count)
        pkmn.attributes.setdefault("@item", None)
        pkmn.attributes.setdefault("@ability_index", 0)
        pkmn.attributes.setdefault("@forced_form", form)
        pkmn.attributes.setdefault("@obtain_level", level)
        pkmn.attributes.setdefault("@obtain_map", 0)
        pkmn.attributes.setdefault("@obtain_method", 0)
        pkmn.attributes.setdefault("@hatched_map", 0)
        pkmn.attributes.setdefault("@personalID", random.randint(0, 2**32 - 1))
        pkmn.attributes.setdefault("@shiny", bool(self.pk_shiny_var.get()))
        pkmn.attributes.setdefault("@super_shiny", bool(self.pk_super_shiny_var.get()))
        pkmn.attributes.setdefault("@iv", {core.Symbol(sid): 31 for sid, _ in STAT_ORDER})
        pkmn.attributes.setdefault("@ev", {core.Symbol(sid): 0 for sid, _ in STAT_ORDER})
        pkmn.attributes.setdefault("@moves", moves[:4])

        hp_override = self._clamp_int(self.pk_hp_var.get(), 0, 9999, self._clamp_int(self.pk_totalhp_var.get(), 0, 9999, 0))
        self._apply_stat_block_to_pokemon(pkmn, preserve_hp_ratio=False, forced_hp=hp_override)
        return pkmn

    def set_new_pokemon_to_selected_slot(self):
        try:
            new_pkmn = self._create_new_pokemon_from_editor()
            self._set_selected_slot_entry(new_pkmn)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Set Error", str(exc))
            return
        self.mark_modified()
        self._render_party_slot_grid()
        self._load_selected_pokemon_into_editor(new_pkmn)
        _entry, slot_label = self._selected_slot_entry()
        self.set_status(f"Active Pokemon assigned to {slot_label}.")

    def _clear_party_detail_fields(self):
        for v in [
            self.pk_species_var,
            self.pk_form_var,
            self.pk_level_var,
            self.pk_exp_var,
            self.pk_hp_var,
            self.pk_totalhp_var,
            self.pk_attack_var,
            self.pk_defense_var,
            self.pk_spatk_var,
            self.pk_spdef_var,
            self.pk_speed_var,
            self.pk_happiness_var,
            self.pk_nature_var,
            self.pk_item_var,
            self.pk_ability_var,
            self.pk_field_status_var,
            self.pk_gender_var,
            self.pk_name_var,
            self.pk_obtain_level_var,
            self.pk_obtain_map_var,
            self.pk_obtain_method_var,
            self.pk_obtain_text_var,
            self.pk_hatched_map_var,
            self.pk_ability_index_var,
            self.pk_personal_id_var,
            self.pk_forced_form_var,
            self.pk_legacy_var,
        ]:
            v.set("")
        self.pk_field_status_var.set(PARTY_FIELD_STATUS_DEFAULT_LABEL)
        for sid, _label in STAT_ORDER:
            self.party_iv_vars[sid].set("0")
            self.party_ev_vars[sid].set("0")
            self.party_base_stat_vars[sid].set("0")
            self.party_final_stat_vars[sid].set("0")
        self.party_hidden_power_var.set("Unknown")
        if hasattr(self, "party_hidden_power_chip_host"):
            self._render_type_chip_row(
                self.party_hidden_power_chip_host,
                [],
                short=False,
                empty_text="Unknown",
            )
        self.pk_shiny_var.set(False)
        self.pk_super_shiny_var.set(False)
        for i in range(4):
            self.move_id_vars[i].set("")
            self.move_pp_vars[i].set("")
            self.move_ppup_vars[i].set("")
            self.relearn_move_vars[i].set("(None)")
        self.pk_nature_effect_var.set("")
        self.pk_nature_neutral_var.set("")
        self.pk_nature_up_var.set("")
        self.pk_nature_sep_var.set("")
        self.pk_nature_down_var.set("")
        self._update_nature_stat_label_colors()
        self._apply_party_ev_mode_ui()
        self.update_party_editor_preview()
        self.update_party_evolution_chart()
        self.update_party_description()

    def apply_selected_pokemon(self):
        entry, slot_label = self._selected_slot_entry()
        if not isinstance(entry, core.RubyObject):
            messagebox.showwarning("No Selection", "Select a non-empty Party/Box slot first.")
            return
        self._sync_exp_with_level(force=True)
        self.on_ability_index_focus_out()
        self.on_forced_form_focus_out()
        pkmn = entry

        def set_int_attr(attr: str, value: str, field_name: str):
            if attr in pkmn.attributes:
                clean = value.strip()
                if clean != "":
                    pkmn.attributes[attr] = parse_int(clean, field_name)

        try:
            if "@species" in pkmn.attributes:
                pkmn.attributes["@species"] = core.Symbol(self.resolve_species_id(self.pk_species_var.get()))
            set_int_attr("@form", self.pk_form_var.get(), "Form")
            set_int_attr("@level", self.pk_level_var.get(), "Level")
            set_int_attr("@exp", self.pk_exp_var.get(), "EXP")
            set_int_attr("@happiness", self.pk_happiness_var.get(), "Friendship")
            set_int_attr("@gender", self.pk_gender_var.get(), "Gender")
            set_int_attr("@obtain_level", self.pk_obtain_level_var.get(), "Obtain Level")
            set_int_attr("@obtain_map", self.pk_obtain_map_var.get(), "Obtain Map")
            set_int_attr("@obtain_method", self.pk_obtain_method_var.get(), "Obtain Method")
            set_int_attr("@hatched_map", self.pk_hatched_map_var.get(), "Hatched Map")
            if "@ability_index" in pkmn.attributes:
                raw_ability_index = self.pk_ability_index_var.get().strip()
                if raw_ability_index.lower() in {"", "none", "nil", "null"}:
                    suggested = self._suggest_ability_index_for_current()
                    ability_index = self._clamp_int(str(suggested if suggested is not None else 0), 0, 3, 0)
                else:
                    ability_index = self._clamp_int(str(parse_int(raw_ability_index, "Ability Index")), 0, 3, 0)
                pkmn.attributes["@ability_index"] = ability_index
                self.pk_ability_index_var.set(str(ability_index))
            set_int_attr("@personalID", self.pk_personal_id_var.get(), "Personal ID")
            if "@forced_form" in pkmn.attributes:
                raw_forced_form = self.pk_forced_form_var.get().strip()
                if raw_forced_form.lower() in {"", "none", "nil", "null"}:
                    pkmn.attributes["@forced_form"] = None
                    self.pk_forced_form_var.set("")
                else:
                    forced_form = parse_int(raw_forced_form, "Forced Form")
                    pkmn.attributes["@forced_form"] = forced_form
                    self.pk_forced_form_var.set(str(forced_form))

            if "@name" in pkmn.attributes:
                pkmn.attributes["@name"] = self.pk_name_var.get().strip()
            if "@obtain_text" in pkmn.attributes:
                pkmn.attributes["@obtain_text"] = self.pk_obtain_text_var.get().strip()
            if "@nature" in pkmn.attributes:
                nature_raw = self.resolve_selected_nature_id(self.pk_nature_var.get())
                pkmn.attributes["@nature"] = core.Symbol(nature_raw) if nature_raw else None
            status_id, status_count = self._resolve_party_field_status_spec(self.pk_field_status_var.get())
            if "@status" in pkmn.attributes:
                pkmn.attributes["@status"] = core.Symbol(status_id)
            if "@statusCount" in pkmn.attributes:
                pkmn.attributes["@statusCount"] = status_count
            if "@item" in pkmn.attributes:
                item_raw = self.pk_item_var.get().strip()
                item_id = self.resolve_selected_party_item_id(item_raw) if item_raw else ""
                pkmn.attributes["@item"] = core.Symbol(item_id) if item_id else None
            if "@ability" in pkmn.attributes:
                ability_id = self.resolve_selected_ability_id(self.pk_ability_var.get())
                pkmn.attributes["@ability"] = core.Symbol(ability_id) if ability_id else None
            if "@shiny" in pkmn.attributes:
                pkmn.attributes["@shiny"] = bool(self.pk_shiny_var.get())
            if "@super_shiny" in pkmn.attributes:
                pkmn.attributes["@super_shiny"] = bool(self.pk_super_shiny_var.get())

            moves = core.read_attr(pkmn, "@moves", [])
            if isinstance(moves, list):
                for i in range(min(4, len(moves))):
                    move_obj = moves[i]
                    if not isinstance(move_obj, core.RubyObject):
                        continue
                    move_id = self.resolve_selected_move_id(self.move_id_vars[i].get())
                    if move_id and "@id" in move_obj.attributes:
                        move_obj.attributes["@id"] = core.Symbol(move_id)
                    pp_text = self.move_pp_vars[i].get().strip()
                    ppup_text = self.move_ppup_vars[i].get().strip()
                    ppup_value = self._clamp_int(ppup_text, 0, 3, 0)
                    if "@ppup" in move_obj.attributes:
                        move_obj.attributes["@ppup"] = ppup_value
                    if "@pp" in move_obj.attributes:
                        max_pp = self._move_max_pp(move_id, ppup_value) if move_id else 999
                        move_obj.attributes["@pp"] = self._clamp_int(pp_text, 0, max_pp, max_pp if move_id else 0)
                pkmn.attributes["@moves"] = moves

            if "@first_moves" in pkmn.attributes:
                relearn_ids: list[str] = []
                for i in range(4):
                    mid = self.resolve_selected_relearn_move_id(self.relearn_move_vars[i].get())
                    if mid and mid not in relearn_ids:
                        relearn_ids.append(mid)
                pkmn.attributes["@first_moves"] = [core.Symbol(mid) for mid in relearn_ids]
            hp_override = self._clamp_int(
                self.pk_hp_var.get(),
                0,
                9999,
                self._clamp_int(self.pk_totalhp_var.get(), 0, 9999, 0),
            )
            self._apply_stat_block_to_pokemon(pkmn, preserve_hp_ratio=True, forced_hp=hp_override)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Apply Error", str(exc))
            return
        self.mark_modified()
        self._render_party_slot_grid()
        self._load_selected_pokemon_into_editor(pkmn)
        self.set_status(f"Party changes applied ({slot_label}).")

    # ------------------------- Bag tab -------------------------
    def get_selected_bag_pocket_index(self) -> int:
        raw = self.bag_pocket_var.get().strip()
        if raw in self.bag_pocket_option_to_index:
            return self.bag_pocket_option_to_index[raw]
        m = re.match(r"^\s*(\d+)", raw)
        if m:
            return int(m.group(1))
        raw_ci = raw.casefold()
        for idx, label in EN_POCKET_NAMES.items():
            if label.casefold() == raw_ci:
                return idx
        raise ValueError(f"Invalid pocket selection: {raw}")

    def bag_pocket_label(self, index: int) -> str:
        if index in EN_POCKET_NAMES:
            return EN_POCKET_NAMES[index]
        return f"Pocket {index}"

    @staticmethod
    def _parse_pocket_value(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return None
        m = re.match(r"^\s*(\d+)", text)
        if m:
            return int(m.group(1))
        return None

    def _bag_item_ids_for_pocket(self, pocket_index: int) -> list[str]:
        if not self.catalogs:
            return []
        return self.get_merged_held_item_options(
            include_key_items=True,
            allowed_pocket=int(pocket_index),
        )

    def _ask_bag_bulk_quantity(self, action: str) -> int | None:
        pocket_index = self.get_selected_bag_pocket_index()
        pocket_label = self.bag_pocket_label(pocket_index)
        initial = self._clamp_int(self.bag_qty_var.get(), 1, 9999, 1)
        qty = simpledialog.askinteger(
            title=f"{action} - {pocket_label}",
            prompt=f"Enter quantity for all items in pocket {pocket_index} ({pocket_label}):",
            parent=self.root,
            minvalue=1,
            maxvalue=9999,
            initialvalue=initial,
        )
        if qty is None:
            return None
        self.bag_qty_var.set(str(qty))
        return int(qty)

    def update_bag_item_dropdown(self):
        if not hasattr(self, "bag_item_combo"):
            return
        if not self.catalogs:
            return
        try:
            pocket_index = self.get_selected_bag_pocket_index()
        except Exception:
            return
        label_pairs: list[tuple[str, str]] = []
        for iid in self._bag_item_ids_for_pocket(pocket_index):
            label = self._tm_hm_display_label(iid, pocket_index=pocket_index)
            if any(existing == label for existing, _ in label_pairs):
                label = f"{label} [{iid}]"
            label_pairs.append((label, iid))
        label_pairs.sort(key=lambda x: x[0].casefold())
        self._bag_item_label_to_id = {label: iid for label, iid in label_pairs}
        self._bag_item_id_to_label = {}
        for label, iid in label_pairs:
            self._bag_item_id_to_label.setdefault(iid, label)
        self._set_combo_values(self.bag_item_combo, [label for label, _ in label_pairs])

        current = self.bag_item_var.get().strip()
        if not current:
            return
        try:
            cur_id = self.resolve_item_id(current)
            cur_item = self.catalogs.items_by_id.get(cur_id)
            cur_pocket = self._parse_pocket_value(cur_item.extra.get("Pocket", "")) if cur_item else None
            if cur_pocket != pocket_index:
                self.bag_item_var.set("")
            elif cur_id in self._bag_item_id_to_label:
                self.bag_item_var.set(self._bag_item_id_to_label[cur_id])
        except Exception:
            self.bag_item_var.set("")

    def on_bag_pocket_selected(self, _event=None):
        self.bag_item_var.set("")
        self.bag_qty_var.set("")
        self.refresh_bag_list()
        self.update_bag_description()

    def get_bag_pocket(self) -> list:
        bag = self.get_root_key("bag")
        if not isinstance(bag, core.RubyObject):
            raise ValueError("Bag section is missing.")
        pockets = core.read_attr(bag, "@pockets", [])
        if not isinstance(pockets, list):
            raise ValueError("Bag pockets format is invalid.")
        pocket_index = self.get_selected_bag_pocket_index()
        if pocket_index < 0 or pocket_index >= len(pockets):
            raise ValueError(f"Pocket index out of range (0-{len(pockets)-1}).")
        pocket = pockets[pocket_index]
        if pocket is None:
            pocket = []
            pockets[pocket_index] = pocket
            bag.attributes["@pockets"] = pockets
        if not isinstance(pocket, list):
            raise ValueError("Pocket is not a list.")
        return pocket

    def refresh_bag_list(self):
        self.bag_list.delete(0, "end")
        self.update_bag_item_dropdown()
        if self.save_data is None:
            self.update_bag_description()
            return
        try:
            pocket = self.get_bag_pocket()
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Bag load error: {exc}")
            self.update_bag_description()
            return
        for i, entry in enumerate(pocket):
            if isinstance(entry, list) and len(entry) >= 2:
                item_id = symbol_name(entry[0])
                item = self._tm_hm_display_label(self._item_choice(item_id), pocket_index=self.get_selected_bag_pocket_index())
                qty = entry[1]
                self.bag_list.insert("end", f"{i}: {item} x{qty}")
            else:
                self.bag_list.insert("end", f"{i}: {entry}")
        self.update_bag_description()

    def on_bag_item_select(self, _event=None):
        sel = self.bag_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        try:
            pocket = self.get_bag_pocket()
        except Exception:
            return
        if idx >= len(pocket):
            return
        entry = pocket[idx]
        if isinstance(entry, list) and len(entry) >= 2:
            item_id = symbol_name(entry[0])
            canonical = self._item_choice(item_id)
            self.bag_item_var.set(self._bag_item_id_to_label.get(canonical, self._tm_hm_display_label(canonical)))
            self.bag_qty_var.set(str(entry[1]))
        self.update_bag_description()

    def bag_add_item(self):
        if self.save_data is None:
            return
        try:
            item = self.bag_item_var.get().strip()
            qty = parse_int(self.bag_qty_var.get(), "Quantity")
            if not item:
                raise ValueError("Item symbol is required.")
            pocket_index = self.get_selected_bag_pocket_index()
            pocket = self.get_bag_pocket()
            item_id = self.resolve_item_id(item)
            if self.catalogs:
                item_data = self.catalogs.items_by_id.get(item_id)
                if item_data:
                    item_pocket = int(item_data.extra.get("Pocket", "0"))
                    if item_pocket != pocket_index:
                        raise ValueError(
                            f"Item '{item_data.display_name}' belongs to pocket {item_pocket} "
                            f"({self.bag_pocket_label(item_pocket)}), not pocket {pocket_index} "
                            f"({self.bag_pocket_label(pocket_index)})."
                        )
            pocket.append([core.Symbol(item_id), qty])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Bag Error", str(exc))
            return
        self.mark_modified()
        self.refresh_bag_list()
        self.set_status("Bag item added.")

    def bag_update_item(self):
        sel = self.bag_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a bag item first.")
            return
        idx = int(sel[0])
        try:
            item = self.bag_item_var.get().strip()
            qty = parse_int(self.bag_qty_var.get(), "Quantity")
            if not item:
                raise ValueError("Item symbol is required.")
            pocket_index = self.get_selected_bag_pocket_index()
            pocket = self.get_bag_pocket()
            if idx >= len(pocket):
                return
            item_id = self.resolve_item_id(item)
            if self.catalogs:
                item_data = self.catalogs.items_by_id.get(item_id)
                if item_data:
                    item_pocket = int(item_data.extra.get("Pocket", "0"))
                    if item_pocket != pocket_index:
                        raise ValueError(
                            f"Item '{item_data.display_name}' belongs to pocket {item_pocket} "
                            f"({self.bag_pocket_label(item_pocket)}), not pocket {pocket_index} "
                            f"({self.bag_pocket_label(pocket_index)})."
                        )
            pocket[idx] = [core.Symbol(item_id), qty]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Bag Error", str(exc))
            return
        self.mark_modified()
        self.refresh_bag_list()
        self.set_status("Bag item updated.")

    def bag_add_all_items(self):
        if self.save_data is None:
            return
        try:
            if not self.catalogs:
                raise ValueError("Catalog data is not loaded.")
            pocket_index = self.get_selected_bag_pocket_index()
            qty = self._ask_bag_bulk_quantity("Add All")
            if qty is None:
                return
            pocket = self.get_bag_pocket()
            item_ids = self._bag_item_ids_for_pocket(pocket_index)
            if not item_ids:
                raise ValueError(
                    f"No items found for pocket {pocket_index} ({self.bag_pocket_label(pocket_index)})."
                )
            existing_ids: set[str] = set()
            for entry in pocket:
                if isinstance(entry, list) and len(entry) >= 2:
                    iid = self._item_choice(symbol_name(entry[0]))
                    if iid:
                        existing_ids.add(iid)
            added = 0
            for iid in item_ids:
                if iid in existing_ids:
                    continue
                pocket.append([core.Symbol(iid), qty])
                added += 1
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Bag Error", str(exc))
            return
        if added <= 0:
            self.set_status("Add All completed: all pocket items already exist.")
            return
        self.mark_modified()
        self.refresh_bag_list()
        self.set_status(
            f"Add All completed: added {added} items to pocket {pocket_index} ({self.bag_pocket_label(pocket_index)})."
        )

    def bag_update_all_items(self):
        if self.save_data is None:
            return
        try:
            pocket_index = self.get_selected_bag_pocket_index()
            qty = self._ask_bag_bulk_quantity("Update All")
            if qty is None:
                return
            pocket = self.get_bag_pocket()
            updated = 0
            for idx, entry in enumerate(pocket):
                if not (isinstance(entry, list) and len(entry) >= 2):
                    continue
                item_id = self._item_choice(symbol_name(entry[0]))
                if not item_id:
                    continue
                pocket[idx] = [core.Symbol(item_id), qty]
                updated += 1
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Bag Error", str(exc))
            return
        if updated <= 0:
            self.set_status("Update All completed: no items found in selected pocket.")
            return
        self.mark_modified()
        self.refresh_bag_list()
        self.set_status(
            f"Update All completed: updated {updated} items in pocket {pocket_index} ({self.bag_pocket_label(pocket_index)})."
        )

    def bag_remove_item(self):
        sel = self.bag_list.curselection()
        if not sel:
            messagebox.showwarning("No Selection", "Select a bag item first.")
            return
        idx = int(sel[0])
        try:
            pocket = self.get_bag_pocket()
            if idx < len(pocket):
                pocket.pop(idx)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Bag Error", str(exc))
            return
        self.mark_modified()
        self.refresh_bag_list()
        self.set_status("Bag item removed.")

    # ------------------------- Switches / Variables -------------------------
    def load_switch(self):
        if self.save_data is None:
            return
        try:
            switches = self.get_root_key("switches")
            if not isinstance(switches, core.RubyObject):
                return
            data = core.read_attr(switches, "@data", [])
            idx = parse_int(self.switch_index_var.get(), "Switch index")
            if idx < 0 or idx >= len(data):
                raise ValueError(f"Switch index out of range (0-{len(data)-1})")
            self.switch_value_var.set(bool(data[idx]))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Switch Error", str(exc))

    def apply_switch(self):
        if self.save_data is None:
            return
        try:
            switches = self.get_root_key("switches")
            if not isinstance(switches, core.RubyObject):
                raise ValueError("Switches section missing.")
            data = core.read_attr(switches, "@data", [])
            idx = parse_int(self.switch_index_var.get(), "Switch index")
            if idx < 0 or idx >= len(data):
                raise ValueError(f"Switch index out of range (0-{len(data)-1})")
            data[idx] = bool(self.switch_value_var.get())
            switches.attributes["@data"] = data
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Switch Error", str(exc))
            return
        self.mark_modified()
        self.set_status("Switch updated.")

    def load_variable(self):
        if self.save_data is None:
            return
        try:
            variables = self.get_root_key("variables")
            if not isinstance(variables, core.RubyObject):
                return
            data = core.read_attr(variables, "@data", [])
            idx = parse_int(self.var_index_var.get(), "Variable index")
            if idx < 0 or idx >= len(data):
                raise ValueError(f"Variable index out of range (0-{len(data)-1})")
            value = data[idx]
            self.var_type_label_var.set(f"Type: {type(value).__name__}")
            self.var_value_var.set(symbol_name(value))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Variable Error", str(exc))

    def apply_variable(self):
        if self.save_data is None:
            return
        try:
            variables = self.get_root_key("variables")
            if not isinstance(variables, core.RubyObject):
                raise ValueError("Variables section missing.")
            data = core.read_attr(variables, "@data", [])
            idx = parse_int(self.var_index_var.get(), "Variable index")
            if idx < 0 or idx >= len(data):
                raise ValueError(f"Variable index out of range (0-{len(data)-1})")
            current = data[idx]
            raw = self.var_value_var.get()

            if isinstance(current, bool):
                parsed = raw.strip().lower() in {"1", "true", "yes", "y", "on"}
            elif isinstance(current, int) and not isinstance(current, bool):
                parsed = int(raw)
            elif isinstance(current, float):
                parsed = float(raw)
            elif isinstance(current, core.Symbol):
                parsed = core.Symbol(raw.lstrip(":"))
            elif current is None:
                text = raw.strip()
                if text.lower() in {"nil", "none", ""}:
                    parsed = None
                else:
                    try:
                        parsed = int(text)
                    except ValueError:
                        try:
                            parsed = float(text)
                        except ValueError:
                            parsed = text
            elif isinstance(current, (str, core.RubyString, bytes)):
                parsed = raw
            else:
                raise ValueError(
                    f"Variable at index {idx} has unsupported type {type(current).__name__}. "
                    "Use Advanced tab for complex objects."
                )

            data[idx] = parsed
            variables.attributes["@data"] = data
            self.var_type_label_var.set(f"Type: {type(parsed).__name__}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Variable Error", str(exc))
            return
        self.mark_modified()
        self.set_status("Variable updated.")

    # ------------------------- Advanced tab -------------------------
    def adv_get(self):
        if self.save_data is None:
            return
        path = self.adv_path_var.get().strip()
        try:
            value = core.get_path_value(self.save_data, path)
            text = core.describe(value, depth=4)
            self.adv_output.delete("1.0", "end")
            self.adv_output.insert("1.0", text)
            if isinstance(value, (str, core.RubyString, int, float, bool, type(None), core.Symbol)):
                self.adv_value_var.set(symbol_name(value))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Get Error", str(exc))

    def adv_set(self):
        if self.save_data is None:
            return
        path = self.adv_path_var.get().strip()
        raw = self.adv_value_var.get()
        value_type = self.adv_type_var.get()
        try:
            current = core.get_path_value(self.save_data, path)
            parsed = core.parse_value(raw, value_type, current)
            core.set_path_value(self.save_data, path, parsed)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Set Error", str(exc))
            return
        self.mark_modified()
        self.adv_get()
        self.set_status(f"Advanced path updated: {path}")

    def adv_list_children(self):
        if self.save_data is None:
            return
        path = self.adv_path_var.get().strip()
        try:
            value = core.get_path_value(self.save_data, path) if path else self.save_data
            if isinstance(value, core.RubyObject):
                out = "\n".join(sorted(value.attributes.keys()))
            elif isinstance(value, dict):
                out = "\n".join(core.format_atom(k) for k in value.keys())
            elif isinstance(value, (list, tuple)):
                out = "\n".join(str(i) for i in range(len(value)))
            else:
                out = f"Scalar: {core.format_atom(value)}"
            self.adv_output.delete("1.0", "end")
            self.adv_output.insert("1.0", out)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("List Error", str(exc))

    # ------------------------- CustomItem tab -------------------------
    @staticmethod
    def _custom_enum_to_int(raw_value: str, default: int) -> int:
        raw = str(raw_value or "").strip()
        m = re.match(r"^\s*(\d+)", raw)
        if not m:
            return default
        try:
            return int(m.group(1))
        except Exception:
            return default

    def _custom_resolve_item_id(self, raw_value: str) -> str:
        raw = extract_internal_id(str(raw_value or "").strip())
        if not raw:
            return ""
        try:
            return self.resolve_item_id(raw)
        except Exception:
            return raw.lstrip(":").upper()

    def _custom_resolve_ability_id(self, raw_value: str) -> str:
        raw = extract_internal_id(str(raw_value or "").strip())
        if not raw:
            return ""
        try:
            return self.resolve_ability_id(raw)
        except Exception:
            return raw.lstrip(":").upper()

    def _custom_resolve_move_id(self, raw_value: str) -> str:
        raw = extract_internal_id(str(raw_value or "").strip())
        if not raw:
            return ""
        try:
            return self.resolve_move_id(raw)
        except Exception:
            return raw.lstrip(":").upper()

    def _custom_current_item_id(self) -> str:
        if not hasattr(self, "custom_item_id_var"):
            return ""
        return str(self.custom_item_id_var.get() or "").strip().lstrip(":").upper()

    def _custom_detect_item_icon_target_size(self) -> tuple[int, int]:
        icons_dir = self.game_root / "Graphics" / "Items"
        for path in (icons_dir / "000.png", icons_dir / "back.png"):
            if not path.exists():
                continue
            try:
                img = tk.PhotoImage(file=str(path))
            except Exception:
                continue
            width = int(img.width())
            height = int(img.height())
            if width > 0 and height > 0:
                return width, height
        return 48, 48

    def _custom_icon_destination_path(self, item_id: str) -> Path:
        iid = str(item_id or "").strip().lstrip(":").upper()
        if not iid:
            raise ValueError("Item ID is required before saving icon.")
        return self.game_root / "tools" / "custom_item" / "assets" / "items" / f"{iid}.png"

    def _custom_clear_item_icon_cache(self, item_id: str):
        iid = str(item_id or "").strip().lstrip(":").upper()
        if not iid:
            return
        item_keys: set[str] = {iid}
        if self.catalogs:
            try:
                canonical = self.catalogs.canonical_item_id(iid)
            except Exception:
                canonical = None
            if canonical:
                item_keys.add(str(canonical).strip().lstrip(":").upper())
        for item_key in item_keys:
            self._party_item_icon_cache.pop(f"item:{item_key}", None)
        for key in list(self._damage_icon_cache.keys()):
            if any(str(key).startswith(f"damage-item:{item_key}:") for item_key in item_keys):
                self._damage_icon_cache.pop(key, None)

    def _custom_scale_photo_to_box(self, source: tk.PhotoImage, target_w: int, target_h: int) -> tk.PhotoImage:
        tw = max(1, int(target_w))
        th = max(1, int(target_h))
        sw = max(1, int(source.width()))
        sh = max(1, int(source.height()))
        ratio = min(tw / sw, th / sh)
        ratio = max(0.001, float(ratio))
        scaled = source
        try:
            frac = Fraction(ratio).limit_denominator(max(1, max(sw, sh, tw, th)))
            num = max(1, int(frac.numerator))
            den = max(1, int(frac.denominator))
            if num != 1:
                scaled = scaled.zoom(num, num)
            if den != 1:
                scaled = scaled.subsample(den, den)
        except Exception:
            scaled = source
        try:
            if scaled.width() > tw or scaled.height() > th:
                factor = max(
                    1,
                    int(math.ceil(scaled.width() / max(1, tw))),
                    int(math.ceil(scaled.height() / max(1, th))),
                )
                if factor > 1:
                    scaled = scaled.subsample(factor, factor)
        except Exception:
            pass
        out = tk.PhotoImage(width=tw, height=th)
        x = max(0, (tw - int(scaled.width())) // 2)
        y = max(0, (th - int(scaled.height())) // 2)
        try:
            out.tk.call(str(out), "copy", str(scaled), "-to", x, y)
            return out
        except Exception:
            return scaled

    def _custom_update_icon_preview(self):
        if not hasattr(self, "custom_item_icon_preview_label"):
            return
        item_id = self._custom_current_item_id()
        if not item_id:
            item_id = "000"
        if self._custom_item_icon_target_size == (48, 48):
            self._custom_item_icon_target_size = self._custom_detect_item_icon_target_size()
        target_w, target_h = self._custom_item_icon_target_size
        if hasattr(self, "custom_item_icon_size_var"):
            self.custom_item_icon_size_var.set(f"Target icon size: {target_w}x{target_h}")

        preview_img: tk.PhotoImage | None = None
        pending_source = self._custom_item_pending_icon_source
        if pending_source is not None:
            try:
                source_img = tk.PhotoImage(file=str(pending_source))
                preview_img = self._custom_scale_photo_to_box(source_img, 28, 28)
            except Exception:
                preview_img = None
        if preview_img is None:
            try:
                base = self._get_item_icon_image(item_id)
            except Exception:
                base = None
            if base is None and item_id != "000":
                base = self._get_item_icon_image("000")
            if base is not None:
                preview_img = self._custom_scale_photo_to_box(base, 28, 28)
        self._custom_item_preview_image = preview_img
        try:
            self.custom_item_icon_preview_label.configure(image=preview_img)
            self.custom_item_icon_preview_label.image = preview_img
        except Exception:
            pass
        if hasattr(self, "custom_item_icon_source_var"):
            if pending_source is not None:
                target_label = self._custom_current_item_id() or "<ITEM_ID>"
                self.custom_item_icon_source_var.set(
                    f"Pending import: {pending_source.name} -> tools/custom_item/assets/items/{target_label}.png"
                )
            else:
                target_label = self._custom_current_item_id() or "<ITEM_ID>"
                self.custom_item_icon_source_var.set(
                    f"Icon source: parallel file tools/custom_item/assets/items/{target_label}.png (falls back to Graphics/Items/000)."
                )

    def _custom_on_item_id_changed(self):
        self._custom_update_icon_preview()
        if self._custom_item_id_syncing:
            return
        self._custom_item_id_manual_override = True

    def _custom_set_item_id_value(self, item_id: str):
        self._custom_item_id_syncing = True
        try:
            self.custom_item_id_var.set(str(item_id or "").strip().lstrip(":").upper())
        finally:
            self._custom_item_id_syncing = False

    @staticmethod
    def _custom_slug_item_id_from_name(name: str) -> str:
        text = str(name or "").strip()
        if not text:
            return "NEWCUSTOMITEM"
        text = text.replace("’", "'").replace("`", "'")
        text = re.sub(r"(?i)'s\b", "", text)
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^A-Za-z0-9]+", "", text).upper()
        return text or "NEWCUSTOMITEM"

    def _custom_on_item_name_changed(self):
        if self._custom_item_id_syncing or self._custom_item_id_manual_override:
            return
        name = str(self.custom_item_name_var.get() or "").strip()
        if not name:
            return
        current_id = self._custom_current_item_id()
        base = self._custom_slug_item_id_from_name(name)
        suggested = self._custom_suggest_new_item_id(base, allow_item_id=current_id)
        if suggested and suggested != current_id:
            self._custom_set_item_id_value(suggested)

    def _custom_choose_icon_source(self):
        start_dir = self.game_root / "Graphics" / "Items"
        if not start_dir.exists():
            start_dir = self.game_root
        file_path = filedialog.askopenfilename(
            title="Choose Custom Item Icon",
            initialdir=str(start_dir),
            filetypes=[
                ("Image files", "*.png *.gif *.ppm *.pgm"),
                ("PNG files", "*.png"),
                ("All files", "*.*"),
            ],
        )
        if not file_path:
            return
        src = Path(file_path).expanduser().resolve()
        try:
            _ = tk.PhotoImage(file=str(src))
        except Exception:
            messagebox.showerror(
                "Icon Import Error",
                "Unsupported image format for Tk PhotoImage.\nUse PNG/GIF/PPM/PGM.",
            )
            return
        self._custom_item_pending_icon_source = src
        self._custom_update_icon_preview()

    def _custom_clear_icon_source(self):
        self._custom_item_pending_icon_source = None
        self._custom_update_icon_preview()

    def _custom_apply_pending_icon_import(self, item_id: str) -> str:
        source = self._custom_item_pending_icon_source
        if source is None:
            return ""
        src_path = Path(source).expanduser().resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Icon source file not found: {src_path}")
        iid = str(item_id or "").strip().lstrip(":").upper()
        if not iid:
            raise ValueError("Item ID is required before applying icon import.")
        target_w, target_h = self._custom_item_icon_target_size
        if target_w <= 0 or target_h <= 0:
            target_w, target_h = self._custom_detect_item_icon_target_size()
            self._custom_item_icon_target_size = (target_w, target_h)
        source_img = tk.PhotoImage(file=str(src_path))
        output_img = self._custom_scale_photo_to_box(source_img, target_w, target_h)
        out_path = self._custom_icon_destination_path(iid)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        output_img.write(str(out_path), format="png")
        self._custom_item_pending_icon_source = None
        self._custom_clear_item_icon_cache(iid)
        self._custom_update_icon_preview()
        return f"Icon saved to tools/custom_item/assets/items/{iid}.png ({target_w}x{target_h})."

    def _build_custom_effect_picker_column(
        self,
        parent,
        column: int,
        title: str,
        kind: str,
        combo_var: tk.StringVar,
        combo_attr_name: str,
        listbox_attr_name: str,
        pad_left: int,
    ):
        panel = ttk.LabelFrame(parent, text=title, padding=4)
        panel.grid(row=0, column=column, sticky="nsew", padx=(pad_left, 0))
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        combo = ttk.Combobox(panel, textvariable=combo_var, width=26)
        combo.grid(row=0, column=0, sticky="ew")
        self._enable_combo_search(combo)
        self._custom_effect_combo_kind_by_name[str(combo)] = str(kind or "").strip().lower()
        setattr(self, combo_attr_name, combo)
        ttk.Button(
            panel,
            text="Add",
            command=lambda _kind=kind: self._custom_add_effect_from_combo(_kind),
        ).grid(row=0, column=1, sticky="e", padx=(4, 0))

        listbox = tk.Listbox(
            panel,
            height=6,
            selectmode="extended",
            exportselection=False,
        )
        listbox.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        scroll = ttk.Scrollbar(panel, orient="vertical", command=listbox.yview)
        scroll.grid(row=1, column=2, sticky="ns", pady=(4, 0))
        listbox.configure(yscrollcommand=scroll.set)
        listbox.bind(
            "<Motion>",
            lambda e, _kind=kind, _listbox=listbox: self._custom_on_effect_listbox_motion(e, _kind, _listbox),
            add="+",
        )
        listbox.bind("<Leave>", lambda _e: self._hide_custom_effect_tooltip(), add="+")
        listbox.bind("<ButtonPress>", lambda _e: self._hide_custom_effect_tooltip(), add="+")
        setattr(self, listbox_attr_name, listbox)

        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(
            actions,
            text="Remove",
            command=lambda _kind=kind: self._custom_remove_selected_effects(_kind),
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            actions,
            text="Clear",
            command=lambda _kind=kind: self._custom_clear_effects_kind(_kind),
        ).pack(side="left")

    def _custom_effect_widgets(
        self,
        kind: str,
    ) -> tuple[ttk.Combobox | None, tk.Listbox | None, dict[str, str], dict[str, str], Any]:
        key = str(kind or "").strip().lower()
        if key == "item":
            return (
                getattr(self, "custom_item_effect_items_combo", None),
                getattr(self, "custom_item_effect_items_listbox", None),
                self._custom_item_effect_item_label_to_id,
                self._custom_item_effect_item_id_to_label,
                self._custom_resolve_item_id,
            )
        if key == "move":
            return (
                getattr(self, "custom_item_effect_moves_combo", None),
                getattr(self, "custom_item_effect_moves_listbox", None),
                self._custom_item_effect_move_label_to_id,
                self._custom_item_effect_move_id_to_label,
                self._custom_resolve_move_id,
            )
        if key == "ability":
            return (
                getattr(self, "custom_item_effect_abilities_combo", None),
                getattr(self, "custom_item_effect_abilities_listbox", None),
                self._custom_item_effect_ability_label_to_id,
                self._custom_item_effect_ability_id_to_label,
                self._custom_resolve_ability_id,
            )
        return None, None, {}, {}, lambda _raw: ""

    def _custom_effect_name_for_id(self, kind: str, effect_id: str) -> str:
        normalized = str(effect_id or "").strip().lstrip(":").upper()
        if not normalized:
            return ""
        key = str(kind or "").strip().lower()
        if key == "item":
            label = self._english_item_name_for_id(normalized)
        elif key == "move":
            label = self._english_move_name_for_id(normalized)
        elif key == "ability":
            label = self._english_ability_name_for_id(normalized)
        else:
            label = normalized
        text = str(label or "").strip()
        if text:
            return text
        return self._prettify_internal_id(normalized) or normalized

    def _custom_effect_label_from_id(self, kind: str, effect_id: str) -> str:
        return self._custom_effect_name_for_id(kind, effect_id)

    def _custom_effect_id_from_label(self, kind: str, label: str) -> str:
        raw_text = str(label or "").strip()
        if not raw_text:
            return ""
        _combo, _listbox, mapping, _id_to_label, resolver = self._custom_effect_widgets(kind)
        raw_id = mapping.get(raw_text, extract_internal_id(raw_text))
        effect_id = resolver(raw_id)
        return str(effect_id or "").strip().lstrip(":").upper()

    def _custom_effect_tooltip_text(self, kind: str, effect_id: str) -> str:
        key = str(kind or "").strip().lower()
        normalized = str(effect_id or "").strip().lstrip(":").upper()
        if key not in {"item", "move", "ability"} or not normalized:
            return ""
        cache_key = (key, normalized)
        cached = self._custom_effect_desc_cache.get(cache_key)
        if cached is not None:
            return cached
        name = self._custom_effect_name_for_id(key, normalized)
        desc = self._custom_effect_description_text(key, normalized)
        desc = str(desc or "").strip()
        if desc and name and desc.casefold() != name.casefold():
            text = f"{name}\n\n{desc}"
        else:
            text = desc or name
        text = text.strip()
        self._custom_effect_desc_cache[cache_key] = text
        return text

    def _hide_custom_effect_tooltip(self):
        tip = self._custom_effect_tooltip_window
        if tip is None:
            return
        try:
            tip.withdraw()
        except Exception:
            pass

    def _show_custom_effect_tooltip(self, text: str, x_root: int, y_root: int):
        content = str(text or "").strip()
        if not content:
            self._hide_custom_effect_tooltip()
            return
        tip = self._custom_effect_tooltip_window
        if tip is None or not tip.winfo_exists():
            tip = tk.Toplevel(self.root)
            tip.wm_overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
            label = tk.Label(
                tip,
                text=content,
                justify="left",
                anchor="nw",
                bg="#fffde8",
                fg="#1f1f1f",
                relief="solid",
                bd=1,
                padx=8,
                pady=6,
                font=("", 9),
                wraplength=560,
            )
            label.pack(fill="both", expand=True)
            self._custom_effect_tooltip_window = tip
            self._custom_effect_tooltip_label = label
        else:
            label = self._custom_effect_tooltip_label
            if label is None or not label.winfo_exists():
                self._custom_effect_tooltip_window = None
                self._custom_effect_tooltip_label = None
                self._show_custom_effect_tooltip(content, x_root, y_root)
                return
            label.configure(text=content)
        try:
            tip.wm_geometry(f"+{int(x_root) + 12}+{int(y_root) + 14}")
            tip.deiconify()
            tip.lift()
        except Exception:
            pass

    def _custom_on_effect_listbox_motion(self, event, kind: str, listbox: tk.Listbox | None):
        label = self._listbox_label_under_pointer(listbox, event)
        if not label:
            self._hide_custom_effect_tooltip()
            return
        effect_id = self._custom_effect_id_from_label(kind, label)
        if not effect_id:
            self._hide_custom_effect_tooltip()
            return
        text = self._custom_effect_tooltip_text(kind, effect_id)
        if not text:
            self._hide_custom_effect_tooltip()
            return
        self._show_custom_effect_tooltip(text, int(getattr(event, "x_root", 0)), int(getattr(event, "y_root", 0)))

    def _custom_selected_effect_ids_from_list(
        self,
        listbox: tk.Listbox | None,
        mapping: dict[str, str],
        resolver,
    ) -> list[str]:
        if listbox is None:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for idx in range(listbox.size()):
            try:
                label = str(listbox.get(idx))
            except Exception:
                continue
            raw = mapping.get(label, extract_internal_id(label))
            effect_id = resolver(raw)
            if not effect_id or effect_id in seen:
                continue
            seen.add(effect_id)
            out.append(effect_id)
        return out

    def _custom_apply_effect_selection(
        self,
        listbox: tk.Listbox | None,
        mapping: dict[str, str],
        target_ids: list[str],
        id_to_label: dict[str, str] | None = None,
        kind: str = "",
    ):
        if listbox is None:
            return
        listbox.delete(0, tk.END)
        normalized_ids: list[str] = []
        seen_ids: set[str] = set()
        for raw_id in target_ids:
            effect_id = str(raw_id or "").strip().lstrip(":").upper()
            if not effect_id or effect_id in seen_ids:
                continue
            seen_ids.add(effect_id)
            normalized_ids.append(effect_id)
        if not normalized_ids:
            return
        if id_to_label is None:
            id_to_label = {}
        for effect_id in normalized_ids:
            label = str(id_to_label.get(effect_id, "") or "").strip()
            if not label:
                for text, mapped in mapping.items():
                    if str(mapped or "").strip().lstrip(":").upper() == effect_id:
                        label = str(text)
                        break
            if not label:
                label = self._custom_effect_label_from_id(kind, effect_id) if kind else (
                    self._prettify_internal_id(effect_id) or effect_id
                )
            listbox.insert(tk.END, label)

    def _custom_set_effect_list_values(
        self,
        combo: ttk.Combobox | None,
        label_to_id: dict[str, str],
        id_to_label: dict[str, str],
        label_pairs: list[tuple[str, str]],
    ):
        if combo is None:
            return
        label_to_id.clear()
        id_to_label.clear()
        combo_labels: list[str] = []
        seen_labels: set[str] = set()
        seen_ids: set[str] = set()
        for label, effect_id in label_pairs:
            text = str(label or "").strip()
            normalized_id = str(effect_id or "").strip().lstrip(":").upper()
            if not text or not normalized_id or text in seen_labels:
                continue
            seen_labels.add(text)
            label_to_id[text] = normalized_id
            combo_labels.append(text)
            if normalized_id not in seen_ids:
                seen_ids.add(normalized_id)
                id_to_label[normalized_id] = text
        self._set_combo_values(combo, combo_labels)

    def _custom_add_effect_from_combo(self, kind: str):
        combo, listbox, mapping, id_to_label, resolver = self._custom_effect_widgets(kind)
        if combo is None or listbox is None:
            return
        raw_label = str(combo.get() or "").strip()
        if not raw_label:
            return
        raw_id = mapping.get(raw_label, extract_internal_id(raw_label))
        effect_id = resolver(raw_id)
        if not effect_id:
            self.custom_item_status_var.set(f"Could not resolve {kind} effect from '{raw_label}'.")
            return
        current_ids = self._custom_selected_effect_ids_from_list(listbox, mapping, resolver)
        if effect_id in current_ids:
            self.custom_item_status_var.set(f"{effect_id} is already selected in {kind} effects.")
            return
        label = str(id_to_label.get(effect_id, "") or "").strip() or self._custom_effect_label_from_id(kind, effect_id)
        if label:
            mapping[label] = effect_id
            listbox.insert(tk.END, label)
        combo.set("")
        self._custom_on_effect_selection_changed()

    def _custom_effect_category_options(self) -> list[str]:
        return ["Damage", "Healing", "Stat", "Status", "Speed", "Contact", "End Turn", "Battle Field"]

    def _custom_effect_category_key(self, category: str) -> str:
        text = str(category or "").strip().casefold().replace("_", " ")
        text = re.sub(r"\s+", " ", text)
        aliases = {
            "damage": "damage",
            "healing": "healing",
            "heal": "healing",
            "stat": "stat",
            "stats": "stat",
            "status": "status",
            "speed": "speed",
            "contact": "contact",
            "end turn": "end_turn",
            "end of turn": "end_turn",
            "end round": "end_turn",
            "end of round": "end_turn",
            "battle field": "battle_field",
            "field": "battle_field",
            "battlefield": "battle_field",
        }
        return aliases.get(text, text.replace(" ", "_"))

    def _custom_effect_category_type_keys(self, category: str) -> list[str] | None:
        """Return supported Builder v1 effect-type keys for a category.

        None means unknown/custom category, so keep the full list for backward
        compatibility. An empty list means the category is known, but Builder v1
        has no safe authoring template for it yet.
        """
        mapping = {
            "damage": ["damage_multiplier"],
            "healing": ["heal_holder", "drain_damage_dealt"],
            "stat": ["change_user_stat_stage"],
            "status": [],
            "speed": ["speed_multiplier"],
            "contact": [],
            "end_turn": ["heal_holder", "change_user_stat_stage"],
            "battle_field": [],
        }
        key = self._custom_effect_category_key(category)
        return mapping.get(key)

    def _custom_effect_type_options(self, category: str = "") -> list[tuple[str, str]]:
        all_options = [
            ("Damage multiplier", "damage_multiplier"),
            ("Heal holder", "heal_holder"),
            ("Drain damage dealt", "drain_damage_dealt"),
            ("Change holder stat stage", "change_user_stat_stage"),
            ("Speed multiplier", "speed_multiplier"),
        ]
        if not category:
            return all_options
        allowed_keys = self._custom_effect_category_type_keys(category)
        if allowed_keys is None:
            return all_options
        allowed = set(allowed_keys)
        return [(label, key) for label, key in all_options if key in allowed]

    def _custom_effect_type_key(self, label: str) -> str:
        text = str(label or "").strip()
        for shown, key in self._custom_effect_type_options():
            if text == shown or text.casefold() == shown.casefold() or text == key:
                return key
        return text.casefold().replace(" ", "_")

    def _custom_effect_type_label(self, key: str) -> str:
        raw = str(key or "").strip()
        for shown, option_key in self._custom_effect_type_options():
            if raw == option_key or raw.casefold() == shown.casefold():
                return shown
        if raw == "raise_user_stat_stage":
            return "Change holder stat stage"
        return self._prettify_internal_id(raw.upper()) or raw

    def _custom_effect_builder_category_note(self, category: str) -> str:
        options = self._custom_effect_type_options(category)
        if options:
            labels = ", ".join(label for label, _key in options)
            prefix = f"Category filters Effect Type: {labels}."
        else:
            prefix = "No supported Builder v1 Effect Type for this category yet."
        return (
            f"{prefix} Only fields related to the selected Effect Type are enabled. "
            "Stat timing 'End of turn' checks every turn; 'Once per battle' only applies to after-move timing."
        )

    @staticmethod
    def _custom_effect_builder_direction_key(label: str) -> str:
        text = str(label or "").strip().casefold()
        return "lower" if "lower" in text or "decrease" in text or "giảm" in text else "raise"

    @staticmethod
    def _custom_effect_builder_direction_label(key: str) -> str:
        return "Lower" if str(key or "").strip().casefold() == "lower" else "Raise"

    @staticmethod
    def _custom_effect_builder_timing_key(label: str) -> str:
        text = str(label or "").strip().casefold()
        if "end" in text or "turn" in text or "round" in text or "cuối" in text:
            return "end_of_round"
        return "after_move"

    @staticmethod
    def _custom_effect_builder_timing_label(key: str) -> str:
        normalized = str(key or "").strip().casefold()
        if normalized in {"end_of_round", "end_of_turn", "end turn", "end_turn"}:
            return "End of turn"
        return "After holder uses a move"

    def _custom_effect_slug_from_name(self, name: str) -> str:
        if custom_item_effect_pool is not None and hasattr(custom_item_effect_pool, "slug_effect_id_from_name"):
            try:
                return custom_item_effect_pool.slug_effect_id_from_name(str(name or ""), fallback="CUSTOM_EFFECT")
            except Exception:
                pass
        text = str(name or "").strip()
        if not text:
            return "CUSTOM_EFFECT"
        text = text.replace("'", "")
        text = re.sub(r"[^A-Za-z0-9]+", "_", text).upper()
        text = re.sub(r"_+", "_", text).strip("_")
        return text or "CUSTOM_EFFECT"

    def _custom_effect_unique_id(self, base_id: str, allow_effect_id: str = "") -> str:
        base = str(base_id or "").strip().lstrip(":").upper() or "CUSTOM_EFFECT"
        allow = str(allow_effect_id or "").strip().lstrip(":").upper()
        existing = set(self._custom_pool_effect_defs_by_id.keys())
        existing.update(self._custom_effect_manifest_rows_by_id.keys())
        if base not in existing or base == allow:
            return base
        for idx in range(2, 1000):
            candidate = f"{base}_{idx}"
            if candidate not in existing or candidate == allow:
                return candidate
        return base

    def _custom_effect_type_ids(self) -> list[str]:
        if not self.catalogs:
            return []
        ids: list[str] = []
        type_source = getattr(self.catalogs, "type_names_by_id", {}) or {}
        for type_id in type_source.keys():
            tid = str(type_id or "").strip().lstrip(":").upper()
            if tid:
                ids.append(tid)
        return sorted(set(ids), key=str.casefold)

    def _custom_effect_type_labels(self) -> list[str]:
        labels = ["Any"]
        for type_id in self._custom_effect_type_ids():
            name = self._type_display_name_for_id(type_id)
            labels.append(f"{type_id} | {name}" if name and name != type_id else type_id)
        return labels

    def _custom_effect_collect_authoring(self) -> dict[str, Any]:
        effect_type_key = self._custom_effect_type_key(getattr(self, "custom_effect_builder_type_var", tk.StringVar()).get())
        move_type_raw = str(getattr(self, "custom_effect_builder_move_type_var", tk.StringVar(value="Any")).get() or "").strip()
        move_type = ""
        if move_type_raw and move_type_raw.casefold() != "any":
            move_type = extract_internal_id(move_type_raw).strip().lstrip(":").upper()
        stat_vars = getattr(self, "_custom_effect_builder_stat_vars", {})
        stats: list[str] = []
        if isinstance(stat_vars, dict) and stat_vars:
            for stat_id, var in stat_vars.items():
                try:
                    if bool(var.get()):
                        stats.append(str(stat_id).strip().upper())
                except Exception:
                    pass
        else:
            stat = extract_internal_id(str(getattr(self, "custom_effect_builder_stat_var", tk.StringVar(value="ATTACK")).get() or "ATTACK")).strip().lstrip(":").upper()
            if stat:
                stats.append(stat)
        desc_text = ""
        desc_widget = getattr(self, "custom_effect_builder_desc_text", None)
        if desc_widget is not None:
            try:
                desc_text = desc_widget.get("1.0", "end").strip()
            except Exception:
                desc_text = ""
        return {
            "id": str(getattr(self, "custom_effect_builder_id_var", tk.StringVar()).get() or "").strip().lstrip(":").upper(),
            "name": str(getattr(self, "custom_effect_builder_name_var", tk.StringVar()).get() or "").strip(),
            "description": desc_text,
            "category": str(getattr(self, "custom_effect_builder_category_var", tk.StringVar(value="Damage")).get() or "").strip(),
            "effect_type": effect_type_key,
            "target": "holder",
            "conditions": {
                "move_type": move_type,
                "require_super_effective": bool(getattr(self, "custom_effect_builder_super_effective_var", tk.BooleanVar()).get()),
            },
            "values": {
                "multiplier": str(getattr(self, "custom_effect_builder_multiplier_var", tk.StringVar(value="1.2")).get() or "1.2").strip(),
                "fraction_numerator": str(getattr(self, "custom_effect_builder_fraction_num_var", tk.StringVar(value="1")).get() or "1").strip(),
                "fraction_denominator": str(getattr(self, "custom_effect_builder_fraction_den_var", tk.StringVar(value="16")).get() or "16").strip(),
                "percent": str(getattr(self, "custom_effect_builder_percent_var", tk.StringVar(value="75")).get() or "75").strip(),
                "stats": stats,
                "stages": str(getattr(self, "custom_effect_builder_stages_var", tk.StringVar(value="1")).get() or "1").strip(),
                "once_per_battle": bool(getattr(self, "custom_effect_builder_once_var", tk.BooleanVar(value=True)).get()),
                "direction": self._custom_effect_builder_direction_key(
                    str(getattr(self, "custom_effect_builder_direction_var", tk.StringVar(value="Raise")).get() or "Raise")
                ),
                "trigger_timing": self._custom_effect_builder_timing_key(
                    str(getattr(self, "custom_effect_builder_timing_var", tk.StringVar(value="After holder uses a move")).get() or "")
                ),
            },
        }

    def _custom_effect_builder_validation_errors(self, authoring: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        effect_id = str(authoring.get("id", "") or "").strip().lstrip(":").upper()
        name = str(authoring.get("name", "") or "").strip()
        category = str(authoring.get("category", "") or "").strip()
        effect_type = str(authoring.get("effect_type", "") or "").strip()
        selected_id = self._custom_effect_builder_selected_id()
        if not effect_id:
            errors.append("Effect ID is required.")
        if not name:
            errors.append("Name is required.")
        options = self._custom_effect_type_options(category)
        if not options:
            errors.append(f"{category or 'This category'} has no supported Builder v1 Effect Type.")
        else:
            allowed_keys = {key for _label, key in options}
            if effect_type not in allowed_keys:
                errors.append(
                    f"Effect Type '{effect_type or '<empty>'}' is not valid for category '{category or '<empty>'}'."
                )

        existing_custom = set(self._custom_effect_manifest_rows_by_id.keys())
        if effect_id and effect_id in existing_custom and effect_id != selected_id:
            errors.append(f"Effect ID already exists in custom effect manifest: {effect_id}.")

        if custom_item_effect_pool is not None:
            try:
                builtin_ids = {
                    str(x or "").strip().upper()
                    for x in custom_item_effect_pool.list_builtin_pool_effect_ids(self.game_root)
                }
                if effect_id and effect_id in builtin_ids:
                    errors.append(f"Effect ID collides with built-in effect pool entry: {effect_id}.")
            except Exception:
                pass
            try:
                backend_errors = custom_item_effect_pool.validate_custom_effect_authoring(authoring)
            except Exception as exc:  # noqa: BLE001
                backend_errors = [f"Validation error: {exc}"]
            errors.extend(str(err) for err in backend_errors if str(err).strip())
        return errors

    def _custom_effect_compiled_preview_text(self, authoring: dict[str, Any]) -> str:
        if custom_item_effect_pool is None:
            return "Custom Effect backend is unavailable."
        validation_errors = self._custom_effect_builder_validation_errors(authoring)
        try:
            compiled, errors = custom_item_effect_pool.compile_custom_effect_authoring(authoring)
        except Exception as exc:  # noqa: BLE001
            return f"Validation error: {exc}"
        merged_errors = []
        seen_errors: set[str] = set()
        for err in [*validation_errors, *errors]:
            text = str(err or "").strip()
            if text and text not in seen_errors:
                seen_errors.add(text)
                merged_errors.append(text)
        if merged_errors:
            lines = ["Validation:", *[f"- {err}" for err in merged_errors]]
            if isinstance(compiled, dict):
                lines.extend(
                    [
                        "",
                        f"Effect ID: {authoring.get('id', '')}",
                        f"Name: {authoring.get('name', '')}",
                        f"Category: {authoring.get('category', '')}",
                        f"Effect Type: {authoring.get('effect_type', '')}",
                    ]
                )
            return "\n".join(lines)
        if not isinstance(compiled, dict):
            return "Validation failed."
        mechanics = self._custom_pool_effect_mechanics_lines(compiled)
        params_text = json.dumps(compiled.get("params", {}), ensure_ascii=True, sort_keys=True)
        values = authoring.get("values", {}) if isinstance(authoring.get("values"), dict) else {}
        trigger_timing = str(values.get("trigger_timing", "") or "").strip() or "n/a"
        lines = [
            "Ready: compile-shape resolved for Builder v1.",
            f"Effect ID: {compiled.get('id', authoring.get('id', ''))}",
            f"Name: {compiled.get('display_name', authoring.get('name', ''))}",
            f"Category: {authoring.get('category', '')}",
            f"Effect Type: {authoring.get('effect_type', '')}",
            f"Generated hook: {compiled.get('hook', '')}",
            f"Generated template: {compiled.get('template', '')}",
            f"Generated params: {params_text}",
            f"Trigger timing: {trigger_timing}",
            f"Target: {compiled.get('target', authoring.get('target', 'holder'))}",
            f"Support status: {compiled.get('support_status', 'supported')}",
            f"Risk level: {compiled.get('risk_level', 'low')}",
        ]
        if mechanics:
            lines.append("Expected mechanics summary:")
            lines.extend(f"- {line}" for line in mechanics)
        return "\n".join(lines)

    def _custom_effect_builder_update_preview(self, _event=None):
        preview = getattr(self, "custom_effect_builder_preview_var", None)
        if preview is None:
            return
        preview.set(self._custom_effect_compiled_preview_text(self._custom_effect_collect_authoring()))

    def _custom_effect_builder_refresh_type_options(self, preserve_current: bool = True):
        combo = getattr(self, "custom_effect_builder_type_combo", None)
        type_var = getattr(self, "custom_effect_builder_type_var", None)
        category = str(getattr(self, "custom_effect_builder_category_var", tk.StringVar(value="Damage")).get() or "").strip()
        options = self._custom_effect_type_options(category)
        labels = [label for label, _key in options]
        current_label = str(type_var.get() if type_var is not None else "").strip()
        current_key = self._custom_effect_type_key(current_label)
        if combo is not None:
            try:
                combo.configure(values=labels)
            except Exception:
                pass
        if type_var is not None:
            if labels:
                allowed_keys = {key for _label, key in options}
                if (not preserve_current) or current_key not in allowed_keys:
                    type_var.set(labels[0])
            else:
                type_var.set("No supported Builder v1 effect type")
        note_var = getattr(self, "custom_effect_builder_category_note_var", None)
        if note_var is not None:
            note_var.set(self._custom_effect_builder_category_note(category))
        if combo is not None:
            try:
                combo.configure(state="readonly" if labels else "disabled")
            except Exception:
                pass
        self._custom_effect_builder_refresh_field_states()

    def _custom_effect_builder_on_category_changed(self, _event=None):
        self._custom_effect_builder_refresh_type_options(preserve_current=False)

    def _custom_effect_builder_autofill_id(self, _event=None):
        id_var = getattr(self, "custom_effect_builder_id_var", None)
        name_var = getattr(self, "custom_effect_builder_name_var", None)
        if id_var is None or name_var is None:
            return
        current = str(id_var.get() or "").strip()
        if current:
            self._custom_effect_builder_update_preview()
            return
        base = self._custom_effect_slug_from_name(str(name_var.get() or ""))
        id_var.set(self._custom_effect_unique_id(base))
        self._custom_effect_builder_update_preview()

    def _custom_effect_builder_rows(self) -> list[dict[str, Any]]:
        if custom_item_effect_pool is None:
            return []
        try:
            rows = custom_item_effect_pool.list_custom_effects(self.game_root)
        except Exception:
            return []
        self._custom_effect_manifest_rows_by_id = {
            str(row.get("id", "") or "").strip().upper(): dict(row)
            for row in rows
            if isinstance(row, dict) and str(row.get("id", "") or "").strip()
        }
        return rows

    def _custom_effect_builder_refresh_list(self, select_id: str = ""):
        listbox = getattr(self, "custom_effect_builder_listbox", None)
        if listbox is None:
            return
        rows = self._custom_effect_builder_rows()
        self._custom_effect_builder_label_to_id = {}
        listbox.delete(0, tk.END)
        select_idx = None
        for idx, row in enumerate(rows):
            effect_id = str(row.get("id", "") or "").strip().upper()
            if not effect_id:
                continue
            name = str(row.get("name", "") or row.get("display_name", "") or effect_id).strip()
            status = str(row.get("support_status", "") or "supported").strip()
            effect_type = self._custom_effect_type_label(str(row.get("effect_type", "") or ""))
            errors = row.get("validation_errors", [])
            suffix = "invalid" if isinstance(errors, list) and errors else status
            label = f"{effect_id} | {name} | {effect_type} | {suffix}"
            self._custom_effect_builder_label_to_id[label] = effect_id
            listbox.insert(tk.END, label)
            if select_id and effect_id == select_id:
                select_idx = idx
        if select_idx is not None:
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(select_idx)
            listbox.see(select_idx)

    def _custom_effect_builder_selected_id(self) -> str:
        listbox = getattr(self, "custom_effect_builder_listbox", None)
        if listbox is None:
            return ""
        sel = listbox.curselection()
        if not sel:
            return ""
        try:
            label = str(listbox.get(int(sel[0])) or "")
        except Exception:
            return ""
        return str(self._custom_effect_builder_label_to_id.get(label, extract_internal_id(label)) or "").strip().upper()

    def _custom_effect_builder_set_desc(self, text: str):
        widget = getattr(self, "custom_effect_builder_desc_text", None)
        if widget is None:
            return
        widget.delete("1.0", "end")
        if str(text or "").strip():
            widget.insert("1.0", str(text or "").strip())

    def _custom_effect_builder_clear_form(self):
        if not hasattr(self, "custom_effect_builder_id_var"):
            return
        self.custom_effect_builder_id_var.set("")
        self.custom_effect_builder_name_var.set("")
        self.custom_effect_builder_category_var.set("Damage")
        self._custom_effect_builder_refresh_type_options(preserve_current=False)
        self.custom_effect_builder_move_type_var.set("Any")
        self.custom_effect_builder_super_effective_var.set(False)
        self.custom_effect_builder_multiplier_var.set("1.2")
        self.custom_effect_builder_fraction_num_var.set("1")
        self.custom_effect_builder_fraction_den_var.set("16")
        self.custom_effect_builder_percent_var.set("75")
        self.custom_effect_builder_direction_var.set("Raise")
        self.custom_effect_builder_timing_var.set("After holder uses a move")
        stat_vars = getattr(self, "_custom_effect_builder_stat_vars", {})
        if isinstance(stat_vars, dict):
            for stat_id, var in stat_vars.items():
                try:
                    var.set(str(stat_id).upper() == "ATTACK")
                except Exception:
                    pass
        if hasattr(self, "custom_effect_builder_stat_var"):
            self.custom_effect_builder_stat_var.set("ATTACK")
        self.custom_effect_builder_stages_var.set("1")
        self.custom_effect_builder_once_var.set(True)
        self._custom_effect_builder_set_desc("")
        self._custom_effect_builder_refresh_field_states()
        self._custom_effect_builder_update_preview()

    def _custom_effect_builder_load_selected(self, _event=None):
        effect_id = self._custom_effect_builder_selected_id()
        if not effect_id:
            return
        row = self._custom_effect_manifest_rows_by_id.get(effect_id, {})
        if not row:
            return
        self.custom_effect_builder_id_var.set(effect_id)
        self.custom_effect_builder_name_var.set(str(row.get("name", "") or effect_id))
        self.custom_effect_builder_category_var.set(str(row.get("category", "") or "Custom"))
        self.custom_effect_builder_type_var.set(self._custom_effect_type_label(str(row.get("effect_type", "") or "")))
        self._custom_effect_builder_refresh_type_options(preserve_current=True)
        conditions = row.get("conditions", {}) if isinstance(row.get("conditions"), dict) else {}
        values = row.get("values", {}) if isinstance(row.get("values"), dict) else {}
        move_type = str(conditions.get("move_type", "") or "").strip().lstrip(":").upper()
        if move_type:
            move_label = move_type
            for label in self._custom_effect_type_labels():
                if extract_internal_id(label).strip().upper() == move_type:
                    move_label = label
                    break
            self.custom_effect_builder_move_type_var.set(move_label)
        else:
            self.custom_effect_builder_move_type_var.set("Any")
        self.custom_effect_builder_super_effective_var.set(str(conditions.get("require_super_effective", "")).casefold() in {"true", "1", "yes"})
        self.custom_effect_builder_multiplier_var.set(str(values.get("multiplier", "1.2")))
        self.custom_effect_builder_fraction_num_var.set(str(values.get("fraction_numerator", "1")))
        self.custom_effect_builder_fraction_den_var.set(str(values.get("fraction_denominator", "16")))
        self.custom_effect_builder_percent_var.set(str(values.get("percent", "75")))
        stats = values.get("stats", values.get("stat", "ATTACK"))
        if isinstance(stats, list):
            stat_values = {str(stat).strip().lstrip(":").upper() for stat in stats if str(stat).strip()}
        else:
            stat_values = {str(stats or "ATTACK").strip().lstrip(":").upper()}
        if not stat_values:
            stat_values = {"ATTACK"}
        stat_vars = getattr(self, "_custom_effect_builder_stat_vars", {})
        if isinstance(stat_vars, dict):
            for stat_id, var in stat_vars.items():
                try:
                    var.set(str(stat_id).upper() in stat_values)
                except Exception:
                    pass
        if hasattr(self, "custom_effect_builder_stat_var"):
            self.custom_effect_builder_stat_var.set(next(iter(sorted(stat_values))) or "ATTACK")
        self.custom_effect_builder_stages_var.set(str(values.get("stages", "1")))
        self.custom_effect_builder_once_var.set(str(values.get("once_per_battle", "true")).casefold() not in {"false", "0", "no"})
        self.custom_effect_builder_direction_var.set(self._custom_effect_builder_direction_label(str(values.get("direction", "raise"))))
        self.custom_effect_builder_timing_var.set(self._custom_effect_builder_timing_label(str(values.get("trigger_timing", values.get("trigger", "after_move")))))
        self._custom_effect_builder_set_desc(str(row.get("description", "") or ""))
        self._custom_effect_builder_refresh_field_states()
        self._custom_effect_builder_update_preview()

    def _custom_effect_builder_save(self):
        if custom_item_effect_pool is None:
            messagebox.showerror("Custom Effect Error", "Custom Effect backend is unavailable.")
            return
        category = str(getattr(self, "custom_effect_builder_category_var", tk.StringVar(value="Damage")).get() or "").strip()
        options = self._custom_effect_type_options(category)
        if not options:
            messagebox.showwarning(
                "Custom Effect Category",
                f"{category or 'This category'} does not have a supported Builder v1 Effect Type yet.",
            )
            return
        effect_type_key = self._custom_effect_type_key(str(getattr(self, "custom_effect_builder_type_var", tk.StringVar()).get() or ""))
        allowed_keys = {key for _label, key in options}
        if effect_type_key not in allowed_keys:
            messagebox.showwarning(
                "Custom Effect Category",
                f"Effect Type is not valid for category {category or '<empty>'}. Pick one of: "
                + ", ".join(label for label, _key in options),
            )
            return
        authoring = self._custom_effect_collect_authoring()
        selected_id = self._custom_effect_builder_selected_id()
        if selected_id:
            authoring["editing_id"] = selected_id
        validation_errors = self._custom_effect_builder_validation_errors(authoring)
        if validation_errors:
            messagebox.showerror(
                "Custom Effect Validation",
                "Cannot save custom effect:\n\n" + "\n".join(f"- {err}" for err in validation_errors),
            )
            return
        try:
            result = custom_item_effect_pool.upsert_custom_effect(self.game_root, authoring)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Custom Effect Validation", str(exc))
            return
        effect_id = str(result.get("id", authoring.get("id", "")) or "").strip().upper()
        self._custom_effect_builder_refresh_list(select_id=effect_id)
        self._custom_refresh_pool_effect_choices()
        self.custom_item_status_var.set(f"Saved custom effect {effect_id} in parallel manifest.")
        self.set_status(f"Saved custom effect {effect_id}.")
        self._custom_effect_builder_update_preview()

    def _custom_effect_builder_delete(self):
        if custom_item_effect_pool is None:
            return
        effect_id = self._custom_effect_builder_selected_id() or str(getattr(self, "custom_effect_builder_id_var", tk.StringVar()).get() or "").strip().upper()
        if not effect_id:
            messagebox.showinfo("Delete Custom Effect", "Select a custom effect first.")
            return
        if not messagebox.askyesno("Delete Custom Effect", f"Delete custom effect {effect_id} from the parallel manifest?"):
            return
        try:
            result = custom_item_effect_pool.delete_custom_effect(self.game_root, effect_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Delete Custom Effect Error", str(exc))
            return
        deleted = bool(result.get("deleted"))
        self._custom_effect_builder_refresh_list()
        self._custom_refresh_pool_effect_choices()
        self._custom_effect_builder_clear_form()
        self.custom_item_status_var.set(f"Deleted custom effect {effect_id}." if deleted else f"Custom effect {effect_id} was not present.")
        self.set_status(f"Deleted custom effect {effect_id}." if deleted else f"Custom effect {effect_id} not found.")

    def _custom_effect_builder_add_to_item_pool(self):
        effect_id = self._custom_effect_builder_selected_id() or str(getattr(self, "custom_effect_builder_id_var", tk.StringVar()).get() or "").strip().upper()
        if not effect_id:
            messagebox.showinfo("Add Custom Effect", "Select or save a custom effect first.")
            return
        self._custom_load_pool_effect_defs()
        effect = self._custom_pool_effect_defs_by_id.get(effect_id, {})
        if not effect:
            messagebox.showwarning("Add Custom Effect", f"{effect_id} is not available in the effect pool. Save it first.")
            return
        status = str(effect.get("support_status", "") or "").strip().lower()
        if status in {"advanced", "unsupported"}:
            messagebox.showwarning("Add Custom Effect", f"{effect_id} is marked {status} and cannot be auto-compiled.")
            return
        if effect_id in self._custom_selected_pool_effect_ids():
            self.custom_item_status_var.set(f"{effect_id} is already selected in normalized pool effects.")
            return
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return
        self._custom_selected_pool_effect_params.setdefault(effect_id, self._custom_pool_effect_default_params(effect_id))
        label = self._custom_selected_pool_effect_label(effect_id)
        self._custom_pool_effect_label_to_id[label] = effect_id
        self._custom_pool_effect_id_to_label[effect_id] = label
        listbox.insert(tk.END, label)
        self._custom_on_effect_selection_changed()
        self.custom_item_status_var.set(f"Added custom effect {effect_id} to this item.")

    def _custom_effect_builder_set_group_state(self, group_name: str, enabled: bool):
        groups = getattr(self, "_custom_effect_builder_field_groups", {})
        widgets = groups.get(group_name, []) if isinstance(groups, dict) else []
        readonly_widgets = getattr(self, "_custom_effect_builder_readonly_widgets", set())
        for widget in widgets:
            try:
                if enabled:
                    state = "readonly" if widget in readonly_widgets else "normal"
                else:
                    state = "disabled"
                widget.configure(state=state)
            except Exception:
                pass

    def _custom_effect_builder_refresh_field_states(self, _event=None):
        effect_type = self._custom_effect_type_key(str(getattr(self, "custom_effect_builder_type_var", tk.StringVar()).get() or ""))
        is_damage = effect_type == "damage_multiplier"
        is_heal = effect_type == "heal_holder"
        is_drain = effect_type == "drain_damage_dealt"
        is_stat = effect_type in {"change_user_stat_stage", "raise_user_stat_stage"}
        is_speed = effect_type == "speed_multiplier"
        for group_name, enabled in {
            "damage": is_damage,
            "heal": is_heal,
            "drain": is_drain,
            "stat": is_stat,
            "multiplier": is_damage or is_speed,
        }.items():
            self._custom_effect_builder_set_group_state(group_name, enabled)
        timing = self._custom_effect_builder_timing_key(str(getattr(self, "custom_effect_builder_timing_var", tk.StringVar()).get() or ""))
        self._custom_effect_builder_set_group_state("once", is_stat and timing == "after_move")
        if is_stat and timing != "after_move":
            try:
                self.custom_effect_builder_once_var.set(False)
            except Exception:
                pass
        self._custom_effect_builder_update_preview()

    def manage_custom_effects(self):
        if custom_item_effect_pool is None:
            messagebox.showerror("Custom Effects Unavailable", "custom_item/effect_pool.py is missing or failed to load.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Custom Effects")
        dialog.transient(self.root)
        dialog.geometry("1040x700")
        dialog.columnconfigure(1, weight=1)
        dialog.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(dialog, text="Parallel Custom Effects", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        left.rowconfigure(0, weight=1)
        self.custom_effect_builder_listbox = tk.Listbox(left, width=38, exportselection=False)
        self.custom_effect_builder_listbox.grid(row=0, column=0, sticky="nsew")
        effect_scroll = ttk.Scrollbar(left, orient="vertical", command=self.custom_effect_builder_listbox.yview)
        effect_scroll.grid(row=0, column=1, sticky="ns")
        self.custom_effect_builder_listbox.configure(yscrollcommand=effect_scroll.set)
        self.custom_effect_builder_listbox.bind("<<ListboxSelect>>", self._custom_effect_builder_load_selected, add="+")

        right = ttk.Frame(dialog, padding=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        right.columnconfigure(1, weight=1)
        right.columnconfigure(3, weight=1)
        right.rowconfigure(10, weight=1)

        self.custom_effect_builder_id_var = tk.StringVar()
        self.custom_effect_builder_name_var = tk.StringVar()
        self.custom_effect_builder_category_var = tk.StringVar(value="Damage")
        self.custom_effect_builder_type_var = tk.StringVar(value="Damage multiplier")
        self.custom_effect_builder_move_type_var = tk.StringVar(value="Any")
        self.custom_effect_builder_super_effective_var = tk.BooleanVar(value=False)
        self.custom_effect_builder_multiplier_var = tk.StringVar(value="1.2")
        self.custom_effect_builder_fraction_num_var = tk.StringVar(value="1")
        self.custom_effect_builder_fraction_den_var = tk.StringVar(value="16")
        self.custom_effect_builder_percent_var = tk.StringVar(value="75")
        self.custom_effect_builder_stat_var = tk.StringVar(value="ATTACK")
        self.custom_effect_builder_direction_var = tk.StringVar(value="Raise")
        self.custom_effect_builder_timing_var = tk.StringVar(value="After holder uses a move")
        self.custom_effect_builder_stages_var = tk.StringVar(value="1")
        self.custom_effect_builder_once_var = tk.BooleanVar(value=True)
        self.custom_effect_builder_preview_var = tk.StringVar()
        self.custom_effect_builder_category_note_var = tk.StringVar()
        self._custom_effect_builder_field_groups = {}

        ttk.Label(right, text="Effect ID").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(right, textvariable=self.custom_effect_builder_id_var, width=28).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(right, text="Name").grid(row=0, column=2, sticky="w", padx=(8, 6), pady=3)
        name_entry = ttk.Entry(right, textvariable=self.custom_effect_builder_name_var, width=28)
        name_entry.grid(row=0, column=3, sticky="ew", pady=3)
        name_entry.bind("<KeyRelease>", self._custom_effect_builder_autofill_id, add="+")

        ttk.Label(right, text="Category").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        category_combo = ttk.Combobox(
            right,
            textvariable=self.custom_effect_builder_category_var,
            values=self._custom_effect_category_options(),
            state="readonly",
            width=24,
        )
        category_combo.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(right, text="Effect Type").grid(row=1, column=2, sticky="w", padx=(8, 6), pady=3)
        type_combo = ttk.Combobox(
            right,
            textvariable=self.custom_effect_builder_type_var,
            values=[label for label, _key in self._custom_effect_type_options(self.custom_effect_builder_category_var.get())],
            state="readonly",
            width=26,
        )
        self.custom_effect_builder_type_combo = type_combo
        type_combo.grid(row=1, column=3, sticky="ew", pady=3)

        ttk.Label(right, text="Target").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Label(right, text="Holder (fixed in Builder v1)", foreground="#555555").grid(row=2, column=1, sticky="w", pady=3)
        super_check = ttk.Checkbutton(right, text="Require super-effective move", variable=self.custom_effect_builder_super_effective_var)
        super_check.grid(row=2, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=3)

        move_type_label = ttk.Label(right, text="Move Type Condition")
        move_type_label.grid(row=3, column=0, sticky="w", padx=(0, 6), pady=3)
        move_type_combo = ttk.Combobox(
            right,
            textvariable=self.custom_effect_builder_move_type_var,
            values=self._custom_effect_type_labels(),
            width=24,
        )
        move_type_combo.grid(row=3, column=1, sticky="ew", pady=3)
        self._enable_combo_search(move_type_combo)

        multiplier_label = ttk.Label(right, text="Multiplier")
        multiplier_label.grid(row=4, column=0, sticky="w", padx=(0, 6), pady=3)
        multiplier_entry = ttk.Entry(right, textvariable=self.custom_effect_builder_multiplier_var, width=12)
        multiplier_entry.grid(row=4, column=1, sticky="w", pady=3)
        heal_fraction_label = ttk.Label(right, text="Heal Fraction")
        heal_fraction_label.grid(row=4, column=2, sticky="w", padx=(8, 6), pady=3)
        fraction_frame = ttk.Frame(right)
        fraction_frame.grid(row=4, column=3, sticky="w", pady=3)
        fraction_num_entry = ttk.Entry(fraction_frame, textvariable=self.custom_effect_builder_fraction_num_var, width=5)
        fraction_num_entry.pack(side="left")
        fraction_slash_label = ttk.Label(fraction_frame, text="/")
        fraction_slash_label.pack(side="left", padx=3)
        fraction_den_entry = ttk.Entry(fraction_frame, textvariable=self.custom_effect_builder_fraction_den_var, width=5)
        fraction_den_entry.pack(side="left")

        drain_label = ttk.Label(right, text="Drain Percent")
        drain_label.grid(row=5, column=0, sticky="w", padx=(0, 6), pady=3)
        drain_entry = ttk.Entry(right, textvariable=self.custom_effect_builder_percent_var, width=12)
        drain_entry.grid(row=5, column=1, sticky="w", pady=3)
        direction_label = ttk.Label(right, text="Direction")
        direction_label.grid(row=5, column=2, sticky="w", padx=(8, 6), pady=3)
        direction_combo = ttk.Combobox(
            right,
            textvariable=self.custom_effect_builder_direction_var,
            values=["Raise", "Lower"],
            state="readonly",
            width=14,
        )
        direction_combo.grid(row=5, column=3, sticky="w", pady=3)

        timing_label = ttk.Label(right, text="Timing")
        timing_label.grid(row=6, column=0, sticky="w", padx=(0, 6), pady=3)
        timing_combo = ttk.Combobox(
            right,
            textvariable=self.custom_effect_builder_timing_var,
            values=["After holder uses a move", "End of turn"],
            state="readonly",
            width=24,
        )
        timing_combo.grid(row=6, column=1, sticky="ew", pady=3)
        stages_label = ttk.Label(right, text="Stages")
        stages_label.grid(row=6, column=2, sticky="w", padx=(8, 6), pady=3)
        stages_entry = ttk.Entry(right, textvariable=self.custom_effect_builder_stages_var, width=8)
        stages_entry.grid(row=6, column=3, sticky="w", pady=3)

        stats_label = ttk.Label(right, text="Stats")
        stats_label.grid(row=7, column=0, sticky="nw", padx=(0, 6), pady=3)
        stats_frame = ttk.Frame(right)
        stats_frame.grid(row=7, column=1, columnspan=3, sticky="ew", pady=3)
        self._custom_effect_builder_stat_vars = {}
        stat_widgets = []
        stat_ids = ["ATTACK", "DEFENSE", "SPECIAL_ATTACK", "SPECIAL_DEFENSE", "SPEED", "ACCURACY", "EVASION"]
        for idx, stat_id in enumerate(stat_ids):
            var = tk.BooleanVar(value=(stat_id == "ATTACK"))
            self._custom_effect_builder_stat_vars[stat_id] = var
            cb = ttk.Checkbutton(stats_frame, text=self._custom_stat_label(stat_id), variable=var)
            cb.grid(row=idx // 4, column=idx % 4, sticky="w", padx=(0, 12), pady=1)
            stat_widgets.append(cb)
            var.trace_add("write", lambda *_args: self._custom_effect_builder_update_preview())
        once_check = ttk.Checkbutton(right, text="Once per battle", variable=self.custom_effect_builder_once_var)
        once_check.grid(row=8, column=1, columnspan=3, sticky="w", pady=3)

        ttk.Label(right, textvariable=self.custom_effect_builder_category_note_var, foreground="#555555", wraplength=720).grid(
            row=9, column=0, columnspan=4, sticky="ew", pady=(6, 4)
        )

        ttk.Label(right, text="Description").grid(row=10, column=0, sticky="nw", padx=(0, 6), pady=3)
        desc = tk.Text(right, height=5, wrap="word")
        desc.grid(row=10, column=1, columnspan=3, sticky="nsew", pady=3)
        self.custom_effect_builder_desc_text = desc

        ttk.Label(right, text="Preview").grid(row=11, column=0, sticky="nw", padx=(0, 6), pady=4)
        ttk.Label(right, textvariable=self.custom_effect_builder_preview_var, foreground="#555555", wraplength=720, justify="left").grid(
            row=11, column=1, columnspan=3, sticky="ew", pady=4
        )

        buttons = ttk.Frame(right)
        buttons.grid(row=12, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="New", command=self._custom_effect_builder_clear_form).pack(side="left", padx=(0, 4))
        ttk.Button(buttons, text="Save Custom Effect", command=self._custom_effect_builder_save).pack(side="left", padx=4)
        ttk.Button(buttons, text="Delete", command=self._custom_effect_builder_delete).pack(side="left", padx=4)
        ttk.Button(buttons, text="Add To Current Item", command=self._custom_effect_builder_add_to_item_pool).pack(side="left", padx=4)
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")

        for var in (
            self.custom_effect_builder_id_var,
            self.custom_effect_builder_category_var,
            self.custom_effect_builder_type_var,
            self.custom_effect_builder_move_type_var,
            self.custom_effect_builder_multiplier_var,
            self.custom_effect_builder_fraction_num_var,
            self.custom_effect_builder_fraction_den_var,
            self.custom_effect_builder_percent_var,
            self.custom_effect_builder_direction_var,
            self.custom_effect_builder_timing_var,
            self.custom_effect_builder_stages_var,
        ):
            var.trace_add("write", lambda *_args: self._custom_effect_builder_update_preview())
        self.custom_effect_builder_super_effective_var.trace_add("write", lambda *_args: self._custom_effect_builder_update_preview())
        self.custom_effect_builder_once_var.trace_add("write", lambda *_args: self._custom_effect_builder_update_preview())
        desc.bind("<KeyRelease>", self._custom_effect_builder_update_preview, add="+")
        category_combo.bind("<<ComboboxSelected>>", self._custom_effect_builder_on_category_changed, add="+")
        type_combo.bind("<<ComboboxSelected>>", self._custom_effect_builder_refresh_field_states, add="+")
        timing_combo.bind("<<ComboboxSelected>>", self._custom_effect_builder_refresh_field_states, add="+")
        self._custom_effect_builder_field_groups = {
            "damage": [move_type_label, move_type_combo, super_check],
            "heal": [heal_fraction_label, fraction_num_entry, fraction_slash_label, fraction_den_entry],
            "drain": [drain_label, drain_entry],
            "stat": [direction_label, direction_combo, timing_label, timing_combo, stages_label, stages_entry, stats_label, *stat_widgets],
            "once": [once_check],
            "multiplier": [multiplier_label, multiplier_entry],
        }
        self._custom_effect_builder_readonly_widgets = {category_combo, type_combo, direction_combo, timing_combo}

        self._custom_effect_builder_refresh_list()
        self._custom_effect_builder_clear_form()
        try:
            dialog.geometry("+%d+%d" % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 60))
        except Exception:
            pass

    def _custom_remove_selected_effects(self, kind: str):
        _combo, listbox, _mapping, _id_to_label, _resolver = self._custom_effect_widgets(kind)
        if listbox is None:
            return
        selected = [int(idx) for idx in listbox.curselection()]
        if not selected:
            return
        self._hide_custom_effect_tooltip()
        for idx in sorted(selected, reverse=True):
            listbox.delete(idx)
        self._custom_on_effect_selection_changed()

    def _custom_clear_effects_kind(self, kind: str, refresh: bool = True):
        _combo, listbox, _mapping, _id_to_label, _resolver = self._custom_effect_widgets(kind)
        if listbox is None:
            return
        self._hide_custom_effect_tooltip()
        if listbox.size() > 0:
            listbox.delete(0, tk.END)
        if refresh:
            self._custom_on_effect_selection_changed()


    def _custom_load_pool_effect_defs(self) -> list[dict[str, Any]]:
        if custom_item_load_effect_pool is None:
            return []
        try:
            pool = custom_item_load_effect_pool(self.game_root)
            effects = list(pool.list_all())
        except Exception:
            return []
        self._custom_pool_effect_defs_by_id = {}
        self._custom_pool_effect_source_map = {}
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            effect_id = str(effect.get("id", "") or "").strip().upper()
            if not effect_id:
                continue
            self._custom_pool_effect_defs_by_id[effect_id] = dict(effect)
            source_kind = str(effect.get("source_kind", "") or "").strip().lower()
            source_id = str(effect.get("source_id", "") or "").strip().lstrip(":").upper()
            if source_kind and source_id:
                self._custom_pool_effect_source_map[effect_id] = (source_kind, source_id)
        return [self._custom_pool_effect_defs_by_id[k] for k in sorted(self._custom_pool_effect_defs_by_id)]

    def _custom_pool_effect_label(self, effect: dict[str, Any]) -> str:
        effect_id = str(effect.get("id", "") or "").strip().upper()
        name = str(effect.get("display_name", "") or "").strip() or self._prettify_internal_id(effect_id)
        source_kind = str(effect.get("source_kind", "") or "").strip().lower() or "custom"
        hook = str(effect.get("hook", "") or "").strip() or "unknown"
        status = str(effect.get("support_status", "") or "").strip().lower() or "unknown"
        risk = str(effect.get("risk_level", "") or "").strip().lower() or "unknown"
        return f"{name} | {source_kind} | {hook} | {status}/{risk}"

    def _custom_pool_effect_default_params(self, effect_id: str) -> dict[str, Any]:
        eid = str(effect_id or "").strip().upper()
        effect = self._custom_pool_effect_defs_by_id.get(eid, {})
        params = effect.get("params", {}) if isinstance(effect, dict) else {}
        return dict(params) if isinstance(params, dict) else {}

    def _custom_pool_effect_params_for(self, effect_id: str) -> dict[str, Any]:
        eid = str(effect_id or "").strip().upper()
        configured = self._custom_selected_pool_effect_params.get(eid)
        if isinstance(configured, dict):
            return dict(configured)
        return self._custom_pool_effect_default_params(eid)

    def _custom_pool_effect_params_summary(self, effect_id: str) -> str:
        params = self._custom_pool_effect_params_for(effect_id)
        if not params:
            return "params: none"
        parts: list[str] = []
        for key in sorted(params.keys(), key=str.casefold):
            value = params.get(key)
            if isinstance(value, list):
                shown = "[" + ", ".join(str(v) for v in value[:4]) + (", ..." if len(value) > 4 else "") + "]"
            else:
                shown = str(value)
            parts.append(f"{key}={shown}")
            if len(parts) >= 4:
                break
        if len(params) > len(parts):
            parts.append("...")
        return "params: " + ", ".join(parts)

    def _custom_selected_pool_effect_label(self, effect_id: str) -> str:
        eid = str(effect_id or "").strip().upper()
        effect = self._custom_pool_effect_defs_by_id.get(eid, {"id": eid})
        name = str(effect.get("display_name", "") or "").strip() or self._prettify_internal_id(eid)
        hook = str(effect.get("hook", "") or "").strip() or "unknown"
        status = str(effect.get("support_status", "") or "").strip().lower() or "unknown"
        risk = str(effect.get("risk_level", "") or "").strip().lower() or "unknown"
        return f"{eid} | {name} | {hook} | {status}/{risk} | {self._custom_pool_effect_params_summary(eid)}"

    def _custom_pool_effect_detail_text(self, effect_id: str) -> str:
        eid = str(effect_id or "").strip().upper()
        effect = self._custom_pool_effect_defs_by_id.get(eid, {})
        if not effect:
            return "No pool effect selected."
        name = str(effect.get("display_name", "") or "").strip() or eid
        source_kind = str(effect.get("source_kind", "") or "").strip() or "custom"
        source_id = str(effect.get("source_id", "") or "").strip() or ""
        hook = str(effect.get("hook", "") or "").strip() or "unknown"
        template = str(effect.get("template", "") or "").strip() or "none"
        status = str(effect.get("support_status", "") or "").strip() or "unknown"
        risk = str(effect.get("risk_level", "") or "").strip() or "unknown"
        desc = str(effect.get("description", "") or "").strip()
        notes = str(effect.get("notes", "") or "").strip()
        params = self._custom_pool_effect_params_for(eid)
        parts = [f"{name} [{eid}]", f"Source: {source_kind}:{source_id} | Hook: {hook} | Template: {template} | Status: {status} | Risk: {risk}"]
        parts.append(f"Configured params: {json.dumps(params, ensure_ascii=False, sort_keys=True)}")
        if desc:
            parts.append(desc)
        if notes:
            parts.append(f"Notes: {notes}")
        if status.lower() in {"advanced", "unsupported"}:
            parts.append("This effect is listed for planning/visibility and cannot be added from the UI until a safe compiler template exists.")
        return "\n".join(parts)

    def _custom_refresh_pool_effect_choices(self, _event=None):
        combo = getattr(self, "custom_pool_effect_combo", None)
        if combo is None:
            return
        effects = self._custom_load_pool_effect_defs()
        source_filter = str(getattr(self, "custom_pool_effect_filter_source_var", tk.StringVar(value="All")).get() or "All").strip().lower()
        status_filter = str(getattr(self, "custom_pool_effect_filter_status_var", tk.StringVar(value="All")).get() or "All").strip().lower()
        hook_filter = str(getattr(self, "custom_pool_effect_filter_hook_var", tk.StringVar(value="All")).get() or "All").strip().lower()
        search = str(getattr(self, "custom_pool_effect_search_var", tk.StringVar()).get() or "").strip().casefold()
        hooks = sorted({str(e.get("hook", "") or "").strip() for e in effects if str(e.get("hook", "") or "").strip()}, key=str.casefold)
        hook_combo = getattr(self, "custom_pool_effect_hook_combo", None)
        if hook_combo is not None:
            current_values = list(hook_combo.cget("values") or [])
            new_values = ["All"] + hooks
            if current_values != new_values:
                self._set_combo_values(hook_combo, new_values)
        labels: list[str] = []
        self._custom_pool_effect_label_to_id = {}
        self._custom_pool_effect_id_to_label = {}
        for effect in effects:
            effect_id = str(effect.get("id", "") or "").strip().upper()
            if not effect_id:
                continue
            source_kind = str(effect.get("source_kind", "") or "").strip().lower()
            status = str(effect.get("support_status", "") or "").strip().lower()
            hook = str(effect.get("hook", "") or "").strip().lower()
            if source_filter != "all" and source_kind != source_filter:
                continue
            if status_filter != "all" and status != status_filter:
                continue
            if hook_filter != "all" and hook != hook_filter:
                continue
            label = self._custom_pool_effect_label(effect)
            haystack = " ".join([
                label,
                effect_id,
                str(effect.get("source_id", "") or ""),
                str(effect.get("description", "") or ""),
                str(effect.get("notes", "") or ""),
            ]).casefold()
            if search and search not in haystack:
                continue
            if label in self._custom_pool_effect_label_to_id:
                label = f"{label} [{effect_id}]"
            labels.append(label)
            self._custom_pool_effect_label_to_id[label] = effect_id
            self._custom_pool_effect_id_to_label.setdefault(effect_id, label)
        labels.sort(key=str.casefold)
        self._set_combo_values(combo, labels)

    def _custom_add_pool_effect_from_combo(self):
        combo = getattr(self, "custom_pool_effect_combo", None)
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if combo is None or listbox is None:
            return
        raw_label = str(combo.get() or "").strip()
        if not raw_label:
            return
        effect_id = self._custom_pool_effect_label_to_id.get(raw_label, extract_internal_id(raw_label).strip().upper())
        if not effect_id:
            return
        self._custom_load_pool_effect_defs()
        effect = self._custom_pool_effect_defs_by_id.get(effect_id, {})
        status = str(effect.get("support_status", "") or "").strip().lower()
        if status in {"advanced", "unsupported"}:
            detail = self._custom_pool_effect_detail_text(effect_id)
            self.custom_item_status_var.set(f"{effect_id} is {status}; not added to compiled pool effects.")
            messagebox.showwarning(
                "Effect Not Auto-Compiled",
                (
                    f"{effect_id} is marked {status} and is not safe to auto-compile yet.\n\n"
                    f"{detail}"
                ),
            )
            return
        current = self._custom_selected_pool_effect_ids()
        if effect_id in current:
            self.custom_item_status_var.set(f"{effect_id} is already selected in normalized pool effects.")
            return
        self._custom_selected_pool_effect_params.setdefault(effect_id, self._custom_pool_effect_default_params(effect_id))
        label = self._custom_selected_pool_effect_label(effect_id)
        self._custom_pool_effect_label_to_id[label] = effect_id
        self._custom_pool_effect_id_to_label[effect_id] = label
        listbox.insert(tk.END, label)
        combo.set("")
        self._custom_on_effect_selection_changed()

    def _custom_selected_pool_effect_ids(self) -> list[str]:
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return []
        out: list[str] = []
        seen: set[str] = set()
        for idx in range(listbox.size()):
            label = str(listbox.get(idx) or "").strip()
            effect_id = self._custom_pool_effect_label_to_id.get(label, extract_internal_id(label).strip().upper())
            effect_id = str(effect_id or "").strip().upper()
            if effect_id and effect_id not in seen:
                seen.add(effect_id)
                out.append(effect_id)
        return out

    def _custom_apply_pool_effect_selection(self, effect_ids: list[str]):
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return
        self._custom_load_pool_effect_defs()
        listbox.delete(0, tk.END)
        self._custom_pool_effect_label_to_id = dict(getattr(self, "_custom_pool_effect_label_to_id", {}))
        self._custom_pool_effect_id_to_label = dict(getattr(self, "_custom_pool_effect_id_to_label", {}))
        for raw_id in effect_ids:
            effect_id = str(raw_id or "").strip().upper()
            if not effect_id:
                continue
            self._custom_selected_pool_effect_params.setdefault(effect_id, self._custom_pool_effect_default_params(effect_id))
            label = self._custom_selected_pool_effect_label(effect_id)
            self._custom_pool_effect_label_to_id[label] = effect_id
            self._custom_pool_effect_id_to_label[effect_id] = label
            listbox.insert(tk.END, label)

    def _custom_rebuild_pool_effect_listbox(self, select_effect_id: str = ""):
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return
        effect_ids = self._custom_selected_pool_effect_ids()
        listbox.delete(0, tk.END)
        self._custom_pool_effect_label_to_id = {
            label: eid for label, eid in self._custom_pool_effect_label_to_id.items()
            if eid not in effect_ids
        }
        for idx, effect_id in enumerate(effect_ids):
            label = self._custom_selected_pool_effect_label(effect_id)
            self._custom_pool_effect_label_to_id[label] = effect_id
            self._custom_pool_effect_id_to_label[effect_id] = label
            listbox.insert(tk.END, label)
            if select_effect_id and effect_id == select_effect_id:
                listbox.selection_clear(0, tk.END)
                listbox.selection_set(idx)
                listbox.see(idx)

    def _custom_selected_pool_effect_id_from_listbox(self) -> str:
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return ""
        sel = listbox.curselection()
        if not sel:
            return ""
        label = str(listbox.get(int(sel[0])) or "")
        return str(self._custom_pool_effect_label_to_id.get(label, extract_internal_id(label).strip().upper()) or "").strip().upper()

    def _custom_configure_selected_pool_effect(self):
        effect_id = self._custom_selected_pool_effect_id_from_listbox()
        if not effect_id:
            messagebox.showinfo("Configure Effect", "Select a pool effect first.")
            return
        current = self._custom_pool_effect_params_for(effect_id)
        text = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True)
        new_text = self._custom_edit_json_text_dialog("Configure Effect Params", effect_id, text)
        if new_text is None:
            return
        try:
            parsed = json.loads(new_text.strip() or "{}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Invalid Params JSON", str(exc))
            return
        if not isinstance(parsed, dict):
            messagebox.showerror("Invalid Params JSON", "Params must be a JSON object.")
            return
        self._custom_selected_pool_effect_params[effect_id] = parsed
        self._custom_rebuild_pool_effect_listbox(select_effect_id=effect_id)
        if hasattr(self, "custom_pool_effect_detail_var"):
            self.custom_pool_effect_detail_var.set(self._custom_pool_effect_detail_text(effect_id))
        self._custom_on_effect_selection_changed()

    def _custom_edit_json_text_dialog(self, title: str, effect_id: str, initial_text: str) -> str | None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(dialog, text=f"{effect_id} params JSON").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        text = tk.Text(dialog, width=72, height=12, wrap="none")
        text.grid(row=1, column=0, sticky="nsew", padx=10)
        text.insert("1.0", initial_text)
        result: dict[str, str | None] = {"value": None}
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=10, pady=10)

        def accept():
            result["value"] = text.get("1.0", "end").strip()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        ttk.Button(buttons, text="OK", command=accept).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="left")
        dialog.bind("<Escape>", lambda _e: cancel(), add="+")
        dialog.bind("<Control-Return>", lambda _e: accept(), add="+")
        try:
            dialog.geometry("+%d+%d" % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 80))
        except Exception:
            pass
        text.focus_set()
        self.root.wait_window(dialog)
        return result["value"]

    def _custom_reset_selected_pool_effect_params(self):
        effect_id = self._custom_selected_pool_effect_id_from_listbox()
        if not effect_id:
            messagebox.showinfo("Reset Params", "Select a pool effect first.")
            return
        self._custom_selected_pool_effect_params[effect_id] = self._custom_pool_effect_default_params(effect_id)
        self._custom_rebuild_pool_effect_listbox(select_effect_id=effect_id)
        if hasattr(self, "custom_pool_effect_detail_var"):
            self.custom_pool_effect_detail_var.set(self._custom_pool_effect_detail_text(effect_id))
        self._custom_on_effect_selection_changed()

    def _custom_remove_selected_pool_effects(self):
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return
        selected = [int(idx) for idx in listbox.curselection()]
        removed_ids: set[str] = set()
        for idx in selected:
            label = str(listbox.get(idx) or "")
            effect_id = self._custom_pool_effect_label_to_id.get(label, extract_internal_id(label).strip().upper())
            if effect_id:
                removed_ids.add(effect_id)
        for idx in sorted(selected, reverse=True):
            listbox.delete(idx)
        for effect_id in removed_ids:
            self._custom_selected_pool_effect_params.pop(effect_id, None)
        self._custom_on_effect_selection_changed()

    def _custom_clear_pool_effects(self):
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is not None and listbox.size() > 0:
            listbox.delete(0, tk.END)
        self._custom_selected_pool_effect_params.clear()
        self._custom_on_effect_selection_changed()

    def _custom_on_pool_effect_combo_selected(self, _event=None):
        combo = getattr(self, "custom_pool_effect_combo", None)
        if combo is None:
            return
        effect_id = self._custom_pool_effect_label_to_id.get(str(combo.get() or ""))
        if effect_id and hasattr(self, "custom_pool_effect_detail_var"):
            self.custom_pool_effect_detail_var.set(self._custom_pool_effect_detail_text(effect_id))

    def _custom_on_pool_effect_list_select(self, _event=None):
        listbox = getattr(self, "custom_pool_effects_listbox", None)
        if listbox is None:
            return
        sel = listbox.curselection()
        if not sel:
            return
        label = str(listbox.get(int(sel[0])) or "")
        effect_id = self._custom_pool_effect_label_to_id.get(label, extract_internal_id(label).strip().upper())
        if effect_id and hasattr(self, "custom_pool_effect_detail_var"):
            self.custom_pool_effect_detail_var.set(self._custom_pool_effect_detail_text(effect_id))

    def _custom_refresh_source_choices(self):
        if not hasattr(self, "custom_item_base_source_combo"):
            return
        self.detect_baked_custom_items()
        selected_item_ids = self._custom_selected_effect_ids_from_list(
            getattr(self, "custom_item_effect_items_listbox", None),
            self._custom_item_effect_item_label_to_id,
            self._custom_resolve_item_id,
        )
        selected_move_ids = self._custom_selected_effect_ids_from_list(
            getattr(self, "custom_item_effect_moves_listbox", None),
            self._custom_item_effect_move_label_to_id,
            self._custom_resolve_move_id,
        )
        selected_ability_ids = self._custom_selected_effect_ids_from_list(
            getattr(self, "custom_item_effect_abilities_listbox", None),
            self._custom_item_effect_ability_label_to_id,
            self._custom_resolve_ability_id,
        )

        item_pairs: list[tuple[str, str]] = []
        ability_pairs: list[tuple[str, str]] = []
        move_pairs: list[tuple[str, str]] = []
        source_item_labels: list[str] = []
        source_item_ids: set[str] = set()
        if self.catalogs:
            for item_id in self.get_vanilla_item_options(include_key_items=True):
                effect_label = self._custom_effect_name_for_id("item", item_id)
                item_pairs.append((effect_label, item_id))
                if item_id not in source_item_ids:
                    source_item_ids.add(item_id)
                    source_item_labels.append(f"{item_id} | {self._english_item_name_for_id(item_id)}")
            for ability_id in sorted(self.catalogs.abilities_by_id.keys(), key=str.casefold):
                ability_pairs.append((self._custom_effect_name_for_id("ability", ability_id), ability_id))
            for move_id in sorted(self.catalogs.moves_by_id.keys(), key=str.casefold):
                move_pairs.append((self._custom_effect_name_for_id("move", move_id), move_id))

        if custom_item_patcher is not None and hasattr(custom_item_patcher, "list_effect_template_ids"):
            try:
                template_ids = custom_item_patcher.list_effect_template_ids(self.game_root)
            except Exception:
                template_ids = {}
            if isinstance(template_ids, dict):
                for raw_id in template_ids.get("ability_ids", []) or []:
                    aid = self._custom_resolve_ability_id(str(raw_id))
                    if aid and all(existing != aid for _label, existing in ability_pairs):
                        ability_pairs.append((self._custom_effect_name_for_id("ability", aid), aid))
                for raw_id in template_ids.get("move_ids", []) or []:
                    mid = self._custom_resolve_move_id(str(raw_id))
                    if mid and all(existing != mid for _label, existing in move_pairs):
                        move_pairs.append((self._custom_effect_name_for_id("move", mid), mid))

        # Load Base Item and legacy effect-source picker intentionally use the
        # vanilla-only list (custom manifest + baked/orphan custom IDs filtered).

        item_pairs.sort(key=lambda row: row[0].casefold())
        move_pairs.sort(key=lambda row: row[0].casefold())
        ability_pairs.sort(key=lambda row: row[0].casefold())
        source_item_labels.sort(key=str.casefold)

        self._set_combo_values(self.custom_item_base_source_combo, source_item_labels)
        self._custom_set_effect_list_values(
            getattr(self, "custom_item_effect_items_combo", None),
            self._custom_item_effect_item_label_to_id,
            self._custom_item_effect_item_id_to_label,
            item_pairs,
        )
        self._custom_set_effect_list_values(
            getattr(self, "custom_item_effect_moves_combo", None),
            self._custom_item_effect_move_label_to_id,
            self._custom_item_effect_move_id_to_label,
            move_pairs,
        )
        self._custom_set_effect_list_values(
            getattr(self, "custom_item_effect_abilities_combo", None),
            self._custom_item_effect_ability_label_to_id,
            self._custom_item_effect_ability_id_to_label,
            ability_pairs,
        )
        self._custom_effect_selection_syncing = True
        try:
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_items_listbox", None),
                self._custom_item_effect_item_label_to_id,
                selected_item_ids,
                self._custom_item_effect_item_id_to_label,
                kind="item",
            )
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_moves_listbox", None),
                self._custom_item_effect_move_label_to_id,
                selected_move_ids,
                self._custom_item_effect_move_id_to_label,
                kind="move",
            )
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_abilities_listbox", None),
                self._custom_item_effect_ability_label_to_id,
                selected_ability_ids,
                self._custom_item_effect_ability_id_to_label,
                kind="ability",
            )
        finally:
            self._custom_effect_selection_syncing = False

    def _custom_effect_ids_from_spec(self, effect: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        if not isinstance(effect, dict):
            return [], [], []
        item_ids: list[str] = []
        move_ids: list[str] = []
        ability_ids: list[str] = []

        def parse_ids(raw_value: Any, resolver) -> list[str]:
            chunks: list[Any]
            if isinstance(raw_value, (list, tuple, set)):
                chunks = list(raw_value)
            else:
                text = str(raw_value or "").strip()
                if not text:
                    return []
                chunks = [chunk.strip() for chunk in text.split(",")]
            out: list[str] = []
            seen: set[str] = set()
            for chunk in chunks:
                resolved = resolver(str(chunk))
                if not resolved or resolved in seen:
                    continue
                seen.add(resolved)
                out.append(resolved)
            return out

        item_ids = parse_ids(effect.get("selected_item_effect_ids", []), self._custom_resolve_item_id)
        move_ids = parse_ids(effect.get("selected_move_effect_ids", []), self._custom_resolve_move_id)
        ability_ids = parse_ids(effect.get("selected_ability_effect_ids", []), self._custom_resolve_ability_id)
        if item_ids or move_ids or ability_ids:
            return item_ids, move_ids, ability_ids

        mode = str(effect.get("mode", "none")).strip().lower()
        source_item_id = self._custom_resolve_item_id(str(effect.get("source_item_id", "")))
        if mode in {"clone_item", "ability_template", "move_template"} and source_item_id:
            item_ids.append(source_item_id)
        if mode == "ability_template":
            aid = self._custom_resolve_ability_id(str(effect.get("ability_id", "")))
            if aid:
                ability_ids.append(aid)
        if mode == "move_template":
            mid = self._custom_resolve_move_id(str(effect.get("move_id", "")))
            if mid:
                move_ids.append(mid)
        origin_mode = str(effect.get("origin_mode", "")).strip().lower()
        origin_id = str(effect.get("origin_id", "")).strip()
        if origin_mode == "ability_template":
            aid = self._custom_resolve_ability_id(origin_id)
            if aid and aid not in ability_ids:
                ability_ids.append(aid)
        elif origin_mode == "move_template":
            mid = self._custom_resolve_move_id(origin_id)
            if mid and mid not in move_ids:
                move_ids.append(mid)
        for source in parse_ids(effect.get("resolved_source_item_ids", []), self._custom_resolve_item_id):
            if source not in item_ids:
                item_ids.append(source)
        return item_ids, move_ids, ability_ids

    def _custom_pool_effect_ids_from_spec(self, effect: dict[str, Any]) -> list[str]:
        if not isinstance(effect, dict):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for raw_id in self._parse_generic_id_list(effect.get("selected_effect_ids", [])):
            eid = str(raw_id or "").strip().lstrip(":").upper()
            if eid and eid not in seen:
                seen.add(eid)
                out.append(eid)
        return out

    def _custom_pool_effect_params_from_spec(self, effect: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not isinstance(effect, dict):
            return {}
        raw = effect.get("selected_effect_params", {})
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            eid = str(key or "").strip().lstrip(":").upper()
            if eid and isinstance(value, dict):
                out[eid] = dict(value)
        return out

    def _parse_generic_id_list(self, raw_value: Any) -> list[str]:
        if isinstance(raw_value, (list, tuple, set)):
            chunks = list(raw_value)
        else:
            text = str(raw_value or "").strip()
            if not text:
                return []
            chunks = [chunk.strip() for chunk in text.split(",")]
        out: list[str] = []
        for chunk in chunks:
            value = str(chunk or "").strip().lstrip(":")
            if value:
                out.append(value)
        return out

    def _custom_collect_selected_effect_ids(self) -> tuple[list[str], list[str], list[str]]:
        item_ids = self._custom_selected_effect_ids_from_list(
            getattr(self, "custom_item_effect_items_listbox", None),
            self._custom_item_effect_item_label_to_id,
            self._custom_resolve_item_id,
        )
        move_ids = self._custom_selected_effect_ids_from_list(
            getattr(self, "custom_item_effect_moves_listbox", None),
            self._custom_item_effect_move_label_to_id,
            self._custom_resolve_move_id,
        )
        ability_ids = self._custom_selected_effect_ids_from_list(
            getattr(self, "custom_item_effect_abilities_listbox", None),
            self._custom_item_effect_ability_label_to_id,
            self._custom_resolve_ability_id,
        )
        return item_ids, move_ids, ability_ids

    def _custom_effect_description_text(self, kind: str, effect_id: str) -> str:
        if not self.catalogs:
            return "No description available in current game data."
        normalized = str(effect_id or "").strip().lstrip(":")
        if not normalized:
            return "No description available in current game data."
        if kind == "item":
            raw_desc = self.catalogs.item_description(normalized)
            summary = self._item_numeric_summary_lines(normalized, raw_desc, "")
            base_desc, summary = self._resolve_entity_description("item", normalized, raw_desc, summary)
        elif kind == "move":
            raw_desc = self.catalogs.move_description(normalized)
            summary = self._move_numeric_summary_lines(normalized, raw_desc, "")
            base_desc, summary = self._resolve_entity_description("move", normalized, raw_desc, summary)
        elif kind == "ability":
            raw_desc = self.catalogs.ability_description(normalized)
            summary = self._ability_numeric_summary_lines(normalized, raw_desc, "")
            base_desc, summary = self._resolve_entity_description("ability", normalized, raw_desc, summary)
        else:
            return "No description available in current game data."
        text = self._append_mechanics_block(base_desc, summary).strip()
        if text:
            return text
        return "No description available in current game data."

    def _custom_stat_label(self, stat_id: str) -> str:
        raw = str(stat_id or "").strip().lstrip(":").upper()
        full_labels = {
            "HP": "HP",
            "ATTACK": "Attack",
            "DEFENSE": "Defense",
            "SPECIAL_ATTACK": "Sp. Atk",
            "SPECIAL_DEFENSE": "Sp. Def",
            "SPEED": "Speed",
            "ACCURACY": "Accuracy",
            "EVASION": "Evasion",
        }
        return full_labels.get(raw, self._prettify_internal_id(raw) or raw)

    def _custom_pool_effect_mechanics_lines(self, effect: dict[str, Any]) -> list[str]:
        if not isinstance(effect, dict):
            return []
        template = str(effect.get("template", "") or "").strip()
        params = effect.get("params", {})
        if not isinstance(params, dict):
            params = {}
        source_kind = str(effect.get("source_kind", "") or "").strip().lower()
        source_id = str(effect.get("source_id", "") or "").strip().lstrip(":").upper()
        source_label = ""
        if source_kind == "item":
            source_label = self._english_item_name_for_id(source_id)
        elif source_kind == "move":
            source_label = self._english_move_name_for_id(source_id)
        elif source_kind == "ability":
            source_label = self._english_ability_name_for_id(source_id)
        source_label = source_label or str(effect.get("display_name", "") or "").strip() or source_id

        def number(value: Any) -> str:
            try:
                fval = float(value)
            except Exception:
                return str(value)
            if fval.is_integer():
                return str(int(fval))
            return f"{fval:g}"

        lines: list[str] = []
        if template == "heal_fraction_max_hp":
            num = params.get("fraction_numerator", 1)
            den = params.get("fraction_denominator", 1)
            lines.append(f"Heals holder by {number(num)}/{number(den)} max HP at end of each turn.")
        elif template == "drain_heal_multiplier":
            mult = params.get("multiplier", "")
            lines.append(f"Drain/healing-from-damage effects are multiplied by {number(mult)}x.")
        elif template == "heal_percent_damage_dealt":
            percent = params.get("percent", "")
            lines.append(f"Heals holder for {number(percent)}% of damage dealt.")
        elif template == "raise_user_stat_stage":
            stats = params.get("stats")
            if not isinstance(stats, list) or not stats:
                stats = [params.get("stat", "")]
            stat_text = self._join_with_and([self._custom_stat_label(str(stat)) for stat in stats if str(stat or "").strip()])
            stages = int(float(params.get("stages", 1) or 1))
            direction = str(params.get("direction", "raise") or "raise").strip().casefold()
            is_lower = direction == "lower"
            verb = "Lowers" if is_lower else "Raises"
            sign = "-" if is_lower else "+"
            trigger = "after holder uses a move"
            if params.get("once_per_battle"):
                trigger += " once per battle"
            if stat_text:
                lines.append(f"{verb} {stat_text} by {sign}{abs(stages)} stage{'s' if abs(stages) != 1 else ''} {trigger}.")
        elif template == "raise_user_stat_stage_end_of_round":
            stats = params.get("stats")
            if not isinstance(stats, list) or not stats:
                stats = [params.get("stat", "")]
            stat_text = self._join_with_and([self._custom_stat_label(str(stat)) for stat in stats if str(stat or "").strip()])
            stages = int(float(params.get("stages", 1) or 1))
            direction = str(params.get("direction", "raise") or "raise").strip().casefold()
            is_lower = direction == "lower"
            verb = "Lowers" if is_lower else "Raises"
            sign = "-" if is_lower else "+"
            if stat_text:
                lines.append(f"{verb} {stat_text} by {sign}{abs(stages)} stage{'s' if abs(stages) != 1 else ''} at end of each turn.")
        elif template == "flinch_target":
            chance = params.get("chance_percent", 100)
            lines.append(f"{number(chance)}% chance to flinch the target after holder uses a move.")
        elif template == "damage_multiplier_conditional":
            mult = params.get("multiplier", "")
            clauses: list[str] = []
            if params.get("require_super_effective"):
                clauses.append("super-effective moves")
            move_type = str(params.get("require_move_type", "") or "").strip().lstrip(":").upper()
            if move_type:
                clauses.append(f"{self._type_display_name_for_id(move_type)}-type moves")
            condition = self._join_with_and(clauses) if clauses else "matching moves"
            lines.append(f"{condition.capitalize()} deal {number(mult)}x damage.")
        elif template == "speed_multiplier_conditional":
            mult = params.get("multiplier", "")
            weather = str(params.get("weather", "") or params.get("require_weather", "") or "").strip()
            suffix = f" during {self._prettify_internal_id(weather)}" if weather else ""
            lines.append(f"Holder Speed is multiplied by {number(mult)}x{suffix}.")
        elif template == "ability_active_bridge":
            ability = params.get("ability_id") or source_id
            ability_label = self._english_ability_name_for_id(str(ability))
            lines.append(f"Grants {ability_label or ability} behavior while holder has this item active.")
        elif template == "move_additional_effect_bridge":
            move_label = self._english_move_name_for_id(source_id)
            lines.append(f"Applies {move_label or source_label} additional effect while holder has this item active.")

        if not lines:
            description = str(effect.get("description", "") or "").strip()
            display = str(effect.get("display_name", "") or "").strip()
            fallback = description if description and description.casefold() != display.casefold() else display
            if fallback:
                lines.append(fallback)
        return self._dedupe_preserve(lines)

    def _custom_source_effect_mechanics_lines(self, kind: str, effect_id: str) -> list[str]:
        normalized = str(effect_id or "").strip().lstrip(":").upper()
        if not normalized or not self.catalogs:
            return []
        if kind == "item":
            raw_desc = self.catalogs.item_description(normalized)
            return self._item_numeric_summary_lines(normalized, raw_desc, "")
        if kind == "move":
            raw_desc = self.catalogs.move_description(normalized)
            lines = self._move_numeric_summary_lines(normalized, raw_desc, "")
            return [line for line in lines if not line.startswith(("Base power:", "Accuracy:", "Base PP:", "Priority:", "Internal function code:"))]
        if kind == "ability":
            raw_desc = self.catalogs.ability_description(normalized)
            return self._ability_numeric_summary_lines(normalized, raw_desc, "")
        return []

    def _custom_effect_spec_mechanics_lines(self, effect: dict[str, Any]) -> list[str]:
        if not isinstance(effect, dict):
            return []
        lines: list[str] = []
        resolved_pool = effect.get("resolved_pool_effects", [])
        if isinstance(resolved_pool, list):
            for pool_effect in resolved_pool:
                if isinstance(pool_effect, dict):
                    lines.extend(self._custom_pool_effect_mechanics_lines(pool_effect))
        if lines:
            return self._dedupe_preserve(lines)
        for item_id in self._parse_generic_id_list(effect.get("selected_item_effect_ids", [])):
            lines.extend(self._custom_source_effect_mechanics_lines("item", item_id))
        for move_id in self._parse_generic_id_list(effect.get("selected_move_effect_ids", [])):
            lines.extend(self._custom_source_effect_mechanics_lines("move", move_id))
        for ability_id in self._parse_generic_id_list(effect.get("selected_ability_effect_ids", [])):
            lines.extend(self._custom_source_effect_mechanics_lines("ability", ability_id))
        return self._dedupe_preserve(lines)

    def _custom_manifest_item_description_text(self, item_id: str) -> str:
        item_key = str(item_id or "").strip().lstrip(":").upper()
        entry = self._custom_manifest_item_entry(item_key)
        spec = self._custom_manifest_item_specs().get(item_key, {})
        desc = str(spec.get("description", "") if isinstance(spec, dict) else "").strip()
        if desc:
            return desc
        effect = entry.get("effect_spec", {}) if isinstance(entry, dict) else {}
        lines = self._custom_effect_spec_mechanics_lines(effect if isinstance(effect, dict) else {})
        if lines:
            return "Mechanics:\n" + "\n".join(f"- {line}" for line in lines)
        return ""

    def _custom_generate_effect_description(self) -> str:
        item_ids, move_ids, ability_ids = self._custom_collect_selected_effect_ids()
        pool_effect_ids = self._custom_selected_pool_effect_ids()
        if not item_ids and not move_ids and not ability_ids and not pool_effect_ids:
            return ""
        lines: list[str] = []
        for item_id in item_ids:
            lines.extend(self._custom_source_effect_mechanics_lines("item", item_id))
        for move_id in move_ids:
            lines.extend(self._custom_source_effect_mechanics_lines("move", move_id))
        for ability_id in ability_ids:
            lines.extend(self._custom_source_effect_mechanics_lines("ability", ability_id))
        for effect_id in pool_effect_ids:
            effect = self._custom_pool_effect_defs_by_id.get(effect_id, {})
            if isinstance(effect, dict):
                params = self._custom_selected_pool_effect_params.get(effect_id, {})
                if isinstance(params, dict) and params:
                    effect = dict(effect)
                    merged_params = dict(effect.get("params", {}) if isinstance(effect.get("params"), dict) else {})
                    merged_params.update(params)
                    effect["params"] = merged_params
                lines.extend(self._custom_pool_effect_mechanics_lines(effect))
        lines = self._dedupe_preserve(lines)
        if not lines:
            return ""
        return "Mechanics:\n" + "\n".join(f"- {line}" for line in lines)

    def _custom_set_description_text(self, text: str, mark_generated: bool):
        self._custom_desc_updating = True
        try:
            self.custom_item_desc_text.delete("1.0", "end")
            cleaned = str(text or "").strip()
            if cleaned:
                self.custom_item_desc_text.insert("1.0", cleaned)
        finally:
            self._custom_desc_updating = False
        self._custom_last_generated_description = str(text or "").strip() if mark_generated else ""

    def _custom_on_description_text_changed(self, _event=None):
        if self._custom_desc_updating:
            return
        current = self.custom_item_desc_text.get("1.0", "end").strip()
        if current != self._custom_last_generated_description:
            self._custom_last_generated_description = ""

    def _custom_refresh_generated_description(self, force: bool = False):
        generated = self._custom_generate_effect_description().strip()
        current = self.custom_item_desc_text.get("1.0", "end").strip()
        if not generated:
            if force and current == self._custom_last_generated_description:
                self._custom_set_description_text("", mark_generated=True)
            return
        should_replace = force or not current or current == self._custom_last_generated_description
        if should_replace:
            self._custom_set_description_text(generated, mark_generated=True)

    def _custom_on_effect_selection_changed(self, _event=None):
        if self._custom_effect_selection_syncing:
            return
        self._custom_refresh_generated_description(force=False)

    def _custom_clear_effect_selection(self):
        self._hide_custom_effect_tooltip()
        self._custom_effect_selection_syncing = True
        try:
            self._custom_clear_effects_kind("item", refresh=False)
            self._custom_clear_effects_kind("move", refresh=False)
            self._custom_clear_effects_kind("ability", refresh=False)
            for combo in (
                getattr(self, "custom_item_effect_items_combo", None),
                getattr(self, "custom_item_effect_moves_combo", None),
                getattr(self, "custom_item_effect_abilities_combo", None),
                getattr(self, "custom_pool_effect_combo", None),
            ):
                if combo is not None:
                    combo.set("")
            pool_listbox = getattr(self, "custom_pool_effects_listbox", None)
            if pool_listbox is not None and pool_listbox.size() > 0:
                pool_listbox.delete(0, tk.END)
        finally:
            self._custom_effect_selection_syncing = False
        self._custom_refresh_generated_description(force=False)

    def custom_item_auto_setup(self):
        if custom_item_controller is None:
            messagebox.showerror(
                "Auto Setup Unavailable",
                "custom_item/controller.py is missing or failed to load.",
            )
            return
        selected = self._choose_probe_save_for_wizard()
        if selected is None:
            return
        try:
            result = custom_item_controller.bootstrap_custom_item_environment(
                game_root=self.game_root,
                save_path=selected,
                profile_path=self.profile_lock_path,
                run_runtime_autofill=True,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CustomItem Auto Setup Error", str(exc))
            return

        try:
            self._remember_current_game_root()
            self._remember_last_save_path(Path(selected))
        except Exception:
            pass

        self._reload_profile_lock()
        self._custom_reload_manifest()

        cap = result.get("patch_capability", {}) if isinstance(result, dict) else {}
        levels = cap.get("patch_levels", {}) if isinstance(cap, dict) else {}
        adapter = result.get("patch_adapter", {}) if isinstance(result, dict) else {}
        strategies = adapter.get("strategies", {}) if isinstance(adapter, dict) else {}
        ruby_injection = strategies.get("ruby_injection", {}) if isinstance(strategies, dict) else {}
        adapter_mode = str(ruby_injection.get("mode", "unknown"))

        runtime = result.get("runtime_mapping", {}) if isinstance(result, dict) else {}
        after = runtime.get("after", {}) if isinstance(runtime, dict) else {}
        move_supported = int(self._clamp_int(after.get("move_supported", 0), 0, 9_999_999, 0))
        move_total = int(self._clamp_int(after.get("move_total", 0), 0, 9_999_999, 0))
        ability_supported = int(self._clamp_int(after.get("ability_supported", 0), 0, 9_999_999, 0))
        ability_total = int(self._clamp_int(after.get("ability_total", 0), 0, 9_999_999, 0))
        runtime_move_missing = int(self._clamp_int(after.get("runtime_move_missing_count", 0), 0, 9_999_999, 0))
        runtime_ability_missing = int(self._clamp_int(after.get("runtime_ability_missing_count", 0), 0, 9_999_999, 0))

        level_a = bool(levels.get("A_metadata_item_data"))
        level_b = bool(levels.get("B_clone_existing_effects"))
        level_c = bool(levels.get("C_ruby_injection"))
        ready = bool(result.get("ready_for_custom_item_patch"))

        warnings = result.get("warnings", []) if isinstance(result, dict) else []
        warning_text = ""
        if isinstance(warnings, list):
            warning_text = " | ".join(str(x).strip() for x in warnings if str(x).strip())

        status = (
            "Auto setup completed. "
            f"Levels A/B/C={int(level_a)}/{int(level_b)}/{int(level_c)}; "
            f"Adapter mode={adapter_mode}; "
            f"Coverage ability={ability_supported}/{ability_total}, move={move_supported}/{move_total}; "
            f"Runtime missing ability={runtime_ability_missing}, move={runtime_move_missing}."
        )
        if warning_text:
            status += f" Warnings: {warning_text}"
        self.custom_item_status_var.set(status)
        self.set_status("Custom item auto setup completed.")

        message_lines = [
            f"Game root: {self.game_root}",
            f"Save file: {selected}",
            "",
            f"Patch levels: A={level_a}, B={level_b}, C={level_c}",
            f"Adapter mode: {adapter_mode}",
            f"Ready for custom-item patch: {ready}",
            "",
            f"Runtime coverage ability: {ability_supported}/{ability_total}",
            f"Runtime coverage move: {move_supported}/{move_total}",
            f"Runtime missing ability: {runtime_ability_missing}",
            f"Runtime missing move: {runtime_move_missing}",
        ]
        if warning_text:
            message_lines.extend(["", f"Warnings: {warning_text}"])
        messagebox.showinfo("CustomItem Auto Setup", "\n".join(message_lines))

    def _custom_refresh_listbox(self):
        if not hasattr(self, "custom_item_listbox"):
            return
        self.custom_item_listbox.delete(0, tk.END)
        self._custom_item_label_to_id = {}
        if custom_item_patcher is None:
            self.custom_item_status_var.set("Custom item patcher module unavailable.")
            return
        try:
            rows = custom_item_patcher.list_custom_items(self.game_root)
        except Exception as exc:  # noqa: BLE001
            self.custom_item_status_var.set(f"Could not load custom items: {exc}")
            return
        for row in rows:
            item_id = str(row.get("id", "")).strip()
            if not item_id:
                continue
            name = str(row.get("name", item_id)).strip()
            effect_count = int(self._clamp_int(row.get("effect_count", 0), 0, 9999, 0))
            label = f"{item_id} | {name} | fx:{effect_count}"
            self._custom_item_label_to_id[label] = item_id
            self.custom_item_listbox.insert(tk.END, label)
        if rows:
            self.custom_item_status_var.set(f"Loaded {len(rows)} custom item(s).")
        else:
            self.custom_item_status_var.set("No custom items in manifest.")

    def _custom_reload_manifest(self):
        if custom_item_patcher is None:
            self._custom_item_manifest = {}
            self.refresh_custom_manifest_list()
            return
        try:
            self._custom_item_manifest = custom_item_patcher.load_manifest(self.game_root)
        except Exception as exc:  # noqa: BLE001
            self._custom_item_manifest = {}
            self.custom_item_status_var.set(f"Manifest read error: {exc}")
        self.refresh_custom_manifest_list()
        self.refresh_base_item_dropdowns()
        self._custom_refresh_pool_effect_choices()
        report = self.detect_baked_custom_items()
        orphan_ids = [
            str(x or "").strip().lstrip(":").upper()
            for x in (report.get("orphan_baked_item_ids", []) if isinstance(report, dict) else [])
            if str(x or "").strip()
        ]
        if orphan_ids:
            self.custom_item_status_var.set(
                "Orphan baked custom items detected in Data/items.dat (hidden from Load Base Item): "
                + ", ".join(orphan_ids[:6])
                + (" ..." if len(orphan_ids) > 6 else "")
            )

    def _custom_selected_item_id(self) -> str:
        if not hasattr(self, "custom_item_listbox"):
            return ""
        sel = self.custom_item_listbox.curselection()
        if not sel:
            return ""
        idx = int(sel[0])
        try:
            label = str(self.custom_item_listbox.get(idx))
        except Exception:
            return ""
        if label in self._custom_item_label_to_id:
            return self._custom_item_label_to_id[label]
        return extract_internal_id(label).strip().upper()

    def _custom_manifest_item_ids(self) -> set[str]:
        if not isinstance(self._custom_item_manifest, dict):
            return set()
        items = self._custom_item_manifest.get("items", {})
        if not isinstance(items, dict):
            return set()
        out: set[str] = set()
        for raw_id in items.keys():
            item_id = str(raw_id or "").strip().lstrip(":").upper()
            if item_id:
                out.add(item_id)
        return out

    def _custom_manifest_item_specs(self) -> dict[str, dict[str, Any]]:
        if not isinstance(self._custom_item_manifest, dict):
            return {}
        items = self._custom_item_manifest.get("items", {})
        if not isinstance(items, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for raw_id, raw_spec in items.items():
            item_id = str(raw_id or "").strip().lstrip(":").upper()
            if not item_id or not isinstance(raw_spec, dict):
                continue
            item_spec = raw_spec.get("item_spec")
            out[item_id] = item_spec if isinstance(item_spec, dict) else raw_spec
        return out

    def _custom_manifest_item_entry(self, item_id: str) -> dict[str, Any]:
        iid = str(item_id or "").strip().lstrip(":").upper()
        if not iid or not isinstance(self._custom_item_manifest, dict):
            return {}
        items = self._custom_item_manifest.get("items", {})
        if not isinstance(items, dict):
            return {}
        entry = items.get(iid, {})
        return entry if isinstance(entry, dict) else {}

    def _custom_load_manifest_cache_silent(self):
        if custom_item_patcher is None:
            return
        try:
            manifest = custom_item_patcher.load_manifest(self.game_root)
        except Exception:
            return
        if isinstance(manifest, dict):
            self._custom_item_manifest = manifest

    def _canonical_item_id_or_custom_manifest(self, value: str) -> str | None:
        raw = str(value or "").strip().lstrip(":")
        if not raw:
            return None
        custom_id = raw.upper()
        if custom_id in self._custom_manifest_item_specs():
            return custom_id
        if not self.catalogs:
            return None
        return self.catalogs.canonical_item_id(raw)

    def _custom_manifest_item_name(self, item_id: str, spec: dict[str, Any] | None = None) -> str:
        iid = str(item_id or "").strip().lstrip(":").upper()
        if not iid:
            return ""
        if spec is None:
            spec = self._custom_manifest_item_specs().get(iid, {})
        name = str((spec or {}).get("name", "") or "").strip()
        if name:
            return name
        return self._prettify_internal_id(iid)

    def _custom_manifest_item_pocket(self, item_id: str, spec: dict[str, Any] | None = None) -> int | None:
        iid = str(item_id or "").strip().lstrip(":").upper()
        if spec is None:
            spec = self._custom_manifest_item_specs().get(iid, {})
        raw = (spec or {}).get("pocket", "")
        try:
            pocket = int(self._custom_enum_to_int(str(raw), 1))
        except Exception:
            pocket = self._parse_pocket_value(str(raw))
        if pocket is None:
            return 1
        return int(pocket)

    def _custom_add_manifest_items_to_pairs(
        self,
        pairs: list[tuple[str, str]],
        *,
        include_key_items: bool = False,
        allowed_pocket: int | None = None,
        label_prefix: str = "",
    ) -> list[tuple[str, str]]:
        existing_ids = {str(item_id or "").strip().lstrip(":").upper() for _label, item_id in pairs}
        existing_labels = {str(label or "") for label, _item_id in pairs}
        for item_id, spec in self._custom_manifest_item_specs().items():
            pocket_idx = self._custom_manifest_item_pocket(item_id, spec)
            if allowed_pocket is not None and pocket_idx != allowed_pocket:
                continue
            if not include_key_items and pocket_idx == 8:
                continue
            if item_id in existing_ids:
                continue
            label = f"{label_prefix}{self._custom_manifest_item_name(item_id, spec)}"
            if label in existing_labels:
                label = f"{label} [{item_id}]"
            pairs.append((label, item_id))
            existing_ids.add(item_id)
            existing_labels.add(label)
        return pairs

    def detect_baked_custom_items(self) -> dict[str, Any]:
        report: dict[str, Any] = {}
        if custom_item_patcher is not None and hasattr(custom_item_patcher, "detect_baked_custom_items"):
            try:
                loaded = custom_item_patcher.detect_baked_custom_items(self.game_root)
                if isinstance(loaded, dict):
                    report = loaded
            except Exception as exc:  # noqa: BLE001
                report = {"warning": f"Failed to detect baked custom items: {exc}"}
        orphan_ids = set()
        for raw_id in report.get("orphan_baked_item_ids", []) if isinstance(report, dict) else []:
            item_id = str(raw_id or "").strip().lstrip(":").upper()
            if item_id:
                orphan_ids.add(item_id)
        self._custom_baked_item_report = report if isinstance(report, dict) else {}
        self._custom_orphan_baked_item_ids = orphan_ids
        blocked = set(self._custom_manifest_item_ids())
        blocked.update(orphan_ids)
        for raw_id in self._custom_baked_item_report.get("detected_custom_item_ids", []):
            item_id = str(raw_id or "").strip().lstrip(":").upper()
            if item_id:
                blocked.add(item_id)
        self._custom_base_dropdown_blocked_ids = blocked
        return self._custom_baked_item_report

    def _custom_base_blocked_item_ids(self) -> set[str]:
        if not getattr(self, "_custom_base_dropdown_blocked_ids", None):
            self.detect_baked_custom_items()
        return set(getattr(self, "_custom_base_dropdown_blocked_ids", set()))

    def get_vanilla_item_options(
        self,
        *,
        include_key_items: bool = True,
        allowed_pocket: int | None = None,
    ) -> list[str]:
        if not self.catalogs:
            return []
        blocked_ids = self._custom_base_blocked_item_ids()
        item_ids: list[str] = []
        for item_id, item in self.catalogs.items_by_id.items():
            iid = str(item_id or "").strip().lstrip(":").upper()
            if not iid or iid in blocked_ids:
                continue
            pocket_idx = self._parse_pocket_value(item.extra.get("Pocket", ""))
            if allowed_pocket is not None and pocket_idx != allowed_pocket:
                continue
            if not include_key_items and pocket_idx == 8:
                continue
            item_ids.append(iid)
        item_ids.sort(key=str.casefold)
        return item_ids

    def get_custom_manifest_item_options(
        self,
        *,
        include_key_items: bool = True,
        allowed_pocket: int | None = None,
    ) -> list[str]:
        item_ids: list[str] = []
        for item_id, spec in self._custom_manifest_item_specs().items():
            pocket_idx = self._custom_manifest_item_pocket(item_id, spec)
            if allowed_pocket is not None and pocket_idx != allowed_pocket:
                continue
            if not include_key_items and pocket_idx == 8:
                continue
            item_ids.append(item_id)
        item_ids.sort(key=str.casefold)
        return item_ids

    def get_merged_held_item_options(
        self,
        *,
        include_key_items: bool = False,
        allowed_pocket: int | None = None,
    ) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for item_id in self.get_vanilla_item_options(include_key_items=include_key_items, allowed_pocket=allowed_pocket):
            if item_id not in seen:
                seen.add(item_id)
                merged.append(item_id)
        for item_id in self.get_custom_manifest_item_options(include_key_items=include_key_items, allowed_pocket=allowed_pocket):
            if item_id not in seen:
                seen.add(item_id)
                merged.append(item_id)
        return merged

    def refresh_base_item_dropdowns(self):
        self._custom_refresh_source_choices()

    def refresh_custom_manifest_list(self):
        self._custom_refresh_listbox()

    def refresh_held_item_dropdowns(self, preferred_item_id: str = ""):
        self._refresh_item_option_widgets_after_custom_item_change(preferred_item_id)

    def _refresh_item_option_widgets_after_custom_item_change(self, preferred_item_id: str = ""):
        """Refresh item dropdowns that normally come from game-data cache.

        Held-item selectors are merged from vanilla + custom manifest entries.
        Refresh active dropdowns so users can assign a newly applied custom item
        immediately without restarting the tool.
        """
        item_id = str(preferred_item_id or "").strip().lstrip(":").upper()
        try:
            if hasattr(self, "pk_item_combo"):
                current_id = self.resolve_selected_party_item_id(self.pk_item_var.get()) or item_id
                base_ids = self.get_merged_held_item_options(include_key_items=False)
                labels, self._party_item_label_to_id, self._party_item_id_to_label = self._party_item_choice_data(base_ids)
                self._set_combo_values(self.pk_item_combo, labels)
                if current_id and current_id in self._party_item_id_to_label:
                    self.pk_item_var.set(self._party_item_id_to_label[current_id])
        except Exception:
            pass

        try:
            if hasattr(self, "team_item_combo"):
                current_id = self._team_resolve_selected_item_id(self.team_item_var.get()) if hasattr(self, "team_item_var") else ""
                labels = self._team_item_choice_labels()
                self._set_combo_values(self.team_item_combo, labels)
                if current_id and current_id in getattr(self, "_team_item_id_to_label", {}):
                    self.team_item_var.set(self._team_item_id_to_label[current_id])
                if hasattr(self, "_team_slot_ui"):
                    for idx in range(len(self._team_slot_ui)):
                        try:
                            species_id = str(self._team_slots[idx].get("species_id", "")) if idx < len(self._team_slots) else ""
                            form = int(self._team_slots[idx].get("form", 0)) if idx < len(self._team_slots) else 0
                            self._team_refresh_slot_inline_editors(idx, species_id, form)
                        except Exception:
                            pass
        except Exception:
            pass

        try:
            if hasattr(self, "_damage_state_by_side"):
                item_labels = self._damage_item_choice_labels()
                for state in self._damage_state_by_side.values():
                    if not isinstance(state, dict):
                        continue
                    widgets = state.get("widgets", {}) if isinstance(state.get("widgets", {}), dict) else {}
                    item_combo = widgets.get("item_combo")
                    if item_combo is not None:
                        self._set_combo_values(item_combo, item_labels)
                    misc_widgets = state.get("misc_widgets", {}) if isinstance(state.get("misc_widgets", {}), dict) else {}
                    misc_item_combo = misc_widgets.get("item_combo")
                    if misc_item_combo is not None:
                        self._set_combo_values(misc_item_combo, item_labels)
        except Exception:
            pass

        try:
            if hasattr(self, "bag_item_combo"):
                self.update_bag_item_dropdown()
        except Exception:
            pass

    def _custom_suggest_new_item_id(self, seed: str, allow_item_id: str = "") -> str:
        base = str(seed or "").strip().lstrip(":").upper() or "NEWCUSTOMITEM"
        allow_id = str(allow_item_id or "").strip().lstrip(":").upper()
        if base and base == allow_id:
            return base
        existing = self._custom_manifest_item_ids()
        if base not in existing:
            return base
        idx = 2
        while True:
            candidate = f"{base}{idx}"
            if candidate == allow_id:
                return candidate
            if candidate not in existing:
                return candidate
            idx += 1

    def _custom_apply_item_spec_to_form(self, spec: dict[str, Any], item_id_hint: str = ""):
        if not isinstance(spec, dict):
            spec = {}
        item_id = str(spec.get("id", item_id_hint) or item_id_hint).strip().lstrip(":").upper()
        if not item_id:
            item_id = "NEWCUSTOMITEM"
        self._custom_item_id_syncing = True
        try:
            self.custom_item_id_var.set(item_id)
            self.custom_item_name_var.set(str(spec.get("name", item_id) or item_id))
            self.custom_item_name_plural_var.set(str(spec.get("name_plural", spec.get("name", item_id)) or item_id))
        finally:
            self._custom_item_id_syncing = False
        pocket = int(self._custom_enum_to_int(str(spec.get("pocket", "1")), 1))
        self.custom_item_pocket_var.set(f"{pocket} - {EN_POCKET_NAMES.get(pocket, f'Pocket {pocket}')}")
        self.custom_item_price_var.set(str(spec.get("price", 0)))
        self.custom_item_sell_price_var.set(str(spec.get("sell_price", 0)))
        self.custom_item_bp_price_var.set(str(spec.get("bp_price", 1)))
        field_use = int(self._custom_enum_to_int(str(spec.get("field_use", "0")), 0))
        battle_use = int(self._custom_enum_to_int(str(spec.get("battle_use", "0")), 0))
        field_map = {
            0: "0 - None",
            1: "1 - OnPokemon",
            2: "2 - Direct",
            3: "3 - TM",
            4: "4 - HM",
            5: "5 - TR",
        }
        battle_map = {
            0: "0 - None",
            1: "1 - OnPokemon",
            2: "2 - OnMove",
            3: "3 - OnBattler",
            4: "4 - OnFoe",
            5: "5 - Direct",
        }
        self.custom_item_field_use_var.set(field_map.get(field_use, "0 - None"))
        self.custom_item_battle_use_var.set(battle_map.get(battle_use, "0 - None"))
        flags = spec.get("flags", [])
        if isinstance(flags, list):
            self.custom_item_flags_var.set(",".join(str(x) for x in flags if str(x).strip()))
        else:
            self.custom_item_flags_var.set(str(flags or ""))
        self.custom_item_move_var.set(str(spec.get("move_id", "") or ""))
        self.custom_item_consumable_var.set(bool(spec.get("consumable", True)))
        self.custom_item_show_qty_var.set(bool(spec.get("show_quantity", True)))
        self._custom_item_pending_icon_source = None
        self._custom_set_description_text(str(spec.get("description", "") or ""), mark_generated=False)
        self._custom_update_holdable_hint()
        self._custom_update_icon_preview()

    def _custom_new_default(self):
        if custom_item_patcher is not None and hasattr(custom_item_patcher, "default_item_spec"):
            try:
                spec = custom_item_patcher.default_item_spec("NEWCUSTOMITEM")
            except Exception:
                spec = {}
        else:
            spec = {}
        if not isinstance(spec, dict):
            spec = {}
        spec = dict(spec)
        spec["id"] = self._custom_suggest_new_item_id(str(spec.get("id", "NEWCUSTOMITEM")))
        if not str(spec.get("description", "")).strip():
            spec["description"] = "TODO: customize this item (name/flags/effects)."
        self._custom_item_id_manual_override = False
        self._custom_apply_item_spec_to_form(spec, item_id_hint=str(spec["id"]))
        self._custom_clear_effect_selection()
        self._custom_last_generated_description = self.custom_item_desc_text.get("1.0", "end").strip()
        if hasattr(self, "custom_item_base_source_var"):
            self.custom_item_base_source_var.set("")
        if hasattr(self, "custom_item_listbox"):
            self.custom_item_listbox.selection_clear(0, tk.END)
        self.custom_item_status_var.set(f"Prepared default custom item template: {spec['id']}")

    def _custom_load_base_item(self):
        if custom_item_patcher is None or not hasattr(custom_item_patcher, "read_item_spec"):
            messagebox.showerror(
                "CustomItem Unavailable",
                "custom_item/patcher.py does not expose read_item_spec().",
            )
            return
        base_item_id = self._custom_resolve_item_id(self.custom_item_base_source_var.get())
        if not base_item_id:
            messagebox.showwarning("Missing Base Item", "Choose a base item to load.")
            return
        blocked_ids = self._custom_base_blocked_item_ids()
        if base_item_id in blocked_ids:
            reason = "custom/orphan baked item"
            if base_item_id in self._custom_manifest_item_ids():
                reason = "custom manifest item"
            messagebox.showwarning(
                "Base Item Blocked",
                (
                    "Load Base Item only accepts vanilla/base game items.\n\n"
                    f"Blocked ID: {base_item_id} ({reason}).\n"
                    "Use Manifest Entries for custom items."
                ),
            )
            return
        try:
            spec = custom_item_patcher.read_item_spec(self.game_root, base_item_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Load Base Item Error", str(exc))
            return
        if not isinstance(spec, dict):
            messagebox.showerror("Load Base Item Error", f"Invalid base item payload: {base_item_id}")
            return
        suggested_id = self._custom_suggest_new_item_id(f"{base_item_id}_CUSTOM")
        spec = dict(spec)
        spec["id"] = suggested_id
        self._custom_item_id_manual_override = False
        self._custom_apply_item_spec_to_form(spec, item_id_hint=suggested_id)
        self._custom_effect_selection_syncing = True
        try:
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_items_listbox", None),
                self._custom_item_effect_item_label_to_id,
                [base_item_id],
                self._custom_item_effect_item_id_to_label,
                kind="item",
            )
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_moves_listbox", None),
                self._custom_item_effect_move_label_to_id,
                [],
                self._custom_item_effect_move_id_to_label,
                kind="move",
            )
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_abilities_listbox", None),
                self._custom_item_effect_ability_label_to_id,
                [],
                self._custom_item_effect_ability_id_to_label,
                kind="ability",
            )
        finally:
            self._custom_effect_selection_syncing = False
        self._custom_refresh_generated_description(force=False)
        self._custom_last_generated_description = self.custom_item_desc_text.get("1.0", "end").strip()
        if hasattr(self, "custom_item_listbox"):
            self.custom_item_listbox.selection_clear(0, tk.END)
        self.custom_item_status_var.set(
            f"Loaded base item {base_item_id} into form. Suggested new ID: {suggested_id}"
        )

    def _custom_on_select_item(self, _event=None):
        item_id = self._custom_selected_item_id()
        if not item_id:
            return
        items = self._custom_item_manifest.get("items", {}) if isinstance(self._custom_item_manifest, dict) else {}
        entry = items.get(item_id, {}) if isinstance(items, dict) else {}
        if not isinstance(entry, dict):
            return
        spec = entry.get("item_spec", {})
        effect = entry.get("effect_spec", {})
        if not isinstance(spec, dict):
            spec = {}
        if not isinstance(effect, dict):
            effect = {}

        self._custom_apply_item_spec_to_form(spec, item_id_hint=item_id)
        self._custom_item_id_manual_override = True
        item_effect_ids, move_effect_ids, ability_effect_ids = self._custom_effect_ids_from_spec(effect)
        pool_effect_ids = self._custom_pool_effect_ids_from_spec(effect)
        pool_effect_params = self._custom_pool_effect_params_from_spec(effect)
        self._custom_effect_selection_syncing = True
        try:
            self._custom_selected_pool_effect_params = dict(pool_effect_params)
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_items_listbox", None),
                self._custom_item_effect_item_label_to_id,
                item_effect_ids,
                self._custom_item_effect_item_id_to_label,
                kind="item",
            )
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_moves_listbox", None),
                self._custom_item_effect_move_label_to_id,
                move_effect_ids,
                self._custom_item_effect_move_id_to_label,
                kind="move",
            )
            self._custom_apply_effect_selection(
                getattr(self, "custom_item_effect_abilities_listbox", None),
                self._custom_item_effect_ability_label_to_id,
                ability_effect_ids,
                self._custom_item_effect_ability_id_to_label,
                kind="ability",
            )
            self._custom_apply_pool_effect_selection(pool_effect_ids)
        finally:
            self._custom_effect_selection_syncing = False
        if not str(spec.get("description", "")).strip():
            self._custom_refresh_generated_description(force=True)
        else:
            self._custom_last_generated_description = self.custom_item_desc_text.get("1.0", "end").strip()
        self._custom_update_holdable_hint()

    def _custom_clear_form(self):
        self._custom_item_id_syncing = True
        try:
            self.custom_item_id_var.set("")
            self.custom_item_name_var.set("")
            self.custom_item_name_plural_var.set("")
        finally:
            self._custom_item_id_syncing = False
        self._custom_item_id_manual_override = False
        self.custom_item_pocket_var.set("1 - Items")
        self.custom_item_price_var.set("0")
        self.custom_item_sell_price_var.set("0")
        self.custom_item_bp_price_var.set("1")
        self.custom_item_field_use_var.set("0 - None")
        self.custom_item_battle_use_var.set("0 - None")
        self.custom_item_flags_var.set("")
        self.custom_item_move_var.set("")
        self.custom_item_consumable_var.set(True)
        self.custom_item_show_qty_var.set(True)
        self._custom_item_pending_icon_source = None
        self._custom_selected_pool_effect_params.clear()
        self._custom_set_description_text("", mark_generated=False)
        self._custom_clear_effect_selection()
        self._custom_clear_pool_effects()
        if hasattr(self, "custom_item_base_source_var"):
            self.custom_item_base_source_var.set("")
        if hasattr(self, "custom_item_listbox"):
            self.custom_item_listbox.selection_clear(0, tk.END)
        self._custom_update_holdable_hint()
        self._custom_update_icon_preview()

    def _custom_update_holdable_hint(self):
        pocket = self._custom_enum_to_int(self.custom_item_pocket_var.get(), 1)
        field_use = self._custom_enum_to_int(self.custom_item_field_use_var.get(), 0)
        flags = {x.strip().lower() for x in self.custom_item_flags_var.get().split(",") if x.strip()}
        important = pocket == 8 or "keyitem" in flags or field_use in {3, 4}
        self.custom_item_holdable_var.set("Holdable: No" if important else "Holdable: Yes")

    def _custom_collect_specs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        item_id = str(self.custom_item_id_var.get() or "").strip().lstrip(":").upper()
        if not item_id:
            raise ValueError("Item ID is required.")
        name = self.custom_item_name_var.get().strip() or item_id
        name_plural = self.custom_item_name_plural_var.get().strip() or name
        pocket = self._custom_enum_to_int(self.custom_item_pocket_var.get(), 1)
        price = self._clamp_int(self.custom_item_price_var.get(), 0, 9_999_999, 0)
        sell_price = self._clamp_int(self.custom_item_sell_price_var.get(), 0, 9_999_999, max(0, price // 4))
        bp_price = self._clamp_int(self.custom_item_bp_price_var.get(), 0, 9_999, 1)
        field_use = self._custom_enum_to_int(self.custom_item_field_use_var.get(), 0)
        battle_use = self._custom_enum_to_int(self.custom_item_battle_use_var.get(), 0)
        move_id = str(self.custom_item_move_var.get() or "").strip().lstrip(":").upper()
        flags = [x.strip() for x in self.custom_item_flags_var.get().split(",") if x.strip()]
        description = self.custom_item_desc_text.get("1.0", "end").strip()
        generated = self._custom_generate_effect_description().strip()
        if not description and generated:
            description = generated
        item_spec = {
            "id": item_id,
            "name": name,
            "name_plural": name_plural,
            "pocket": pocket,
            "price": price,
            "sell_price": sell_price,
            "bp_price": bp_price,
            "field_use": field_use,
            "battle_use": battle_use,
            "flags": flags,
            "move_id": move_id,
            "description": description,
            "consumable": bool(self.custom_item_consumable_var.get()),
            "show_quantity": bool(self.custom_item_show_qty_var.get()),
        }
        selected_item_effect_ids, selected_move_effect_ids, selected_ability_effect_ids = self._custom_collect_selected_effect_ids()
        selected_pool_effect_ids = self._custom_selected_pool_effect_ids()
        selected_pool_effect_params: dict[str, dict[str, Any]] = {}
        for effect_id in selected_pool_effect_ids:
            default_params = self._custom_pool_effect_default_params(effect_id)
            configured_params = self._custom_pool_effect_params_for(effect_id)
            if configured_params != default_params:
                selected_pool_effect_params[effect_id] = configured_params
        effect_spec = {
            "selected_item_effect_ids": selected_item_effect_ids,
            "selected_move_effect_ids": selected_move_effect_ids,
            "selected_ability_effect_ids": selected_ability_effect_ids,
            "selected_effect_ids": selected_pool_effect_ids,
            "selected_effect_params": selected_pool_effect_params,
        }
        return item_spec, effect_spec

    def custom_item_upsert(self):
        if custom_item_patcher is None:
            messagebox.showerror(
                "CustomItem Unavailable",
                "custom_item/patcher.py is missing or failed to load.",
            )
            return
        try:
            item_spec, effect_spec = self._custom_collect_specs()
            result = custom_item_patcher.upsert_custom_item(
                self.game_root,
                item_spec=item_spec,
                effect_spec=effect_spec,
                bake_to_items_dat=False,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CustomItem Apply Error", str(exc))
            return
        item_id = str(result.get("item_id", item_spec.get("id", ""))).strip()
        icon_status_note = ""
        icon_warning = ""
        try:
            icon_status_note = self._custom_apply_pending_icon_import(item_id)
        except Exception as exc:  # noqa: BLE001
            icon_warning = str(exc)
        effect_result = result.get("effect_spec", {})
        unsupported_reason = ""
        source_count = 0
        template_count = 0
        if isinstance(effect_result, dict):
            unsupported_reason = str(effect_result.get("unsupported_reason", "") or "").strip()
            sources = effect_result.get("resolved_source_item_ids", [])
            templates = effect_result.get("resolved_templates", [])
            if isinstance(sources, list):
                source_count = len([x for x in sources if str(x).strip()])
            if isinstance(templates, list):
                template_count = len([x for x in templates if isinstance(x, dict)])
        self._custom_reload_manifest()
        self.refresh_held_item_dropdowns(item_id)
        status_note = f"Custom item {item_id} applied. Patched files: {len(result.get('patched_files', []))}."
        if source_count or template_count:
            status_note += f" Effects: {source_count} clone source(s), {template_count} runtime template(s)."
        if unsupported_reason:
            status_note += f" Mapping warning: {unsupported_reason}"
        if icon_status_note:
            status_note += f" {icon_status_note}"
        if icon_warning:
            status_note += " Icon import failed."
        self.custom_item_status_var.set(status_note)
        self.set_status(f"Custom item applied: {item_id}")
        self._custom_set_item_id_value(item_id)
        self._custom_update_holdable_hint()
        self._custom_update_icon_preview()
        if icon_warning:
            messagebox.showwarning(
                "CustomItem Icon Warning",
                (
                    f"Custom item {item_id} was applied, but icon import failed.\n\n"
                    f"{icon_warning}"
                ),
            )
        if unsupported_reason:
            messagebox.showwarning(
                "Effect Mapping Warning",
                (
                    f"Custom item {item_id} was saved, but some selected mappings are unsupported.\n\n"
                    f"{unsupported_reason}"
                ),
            )

    def custom_item_delete_selected(self):
        if custom_item_patcher is None:
            messagebox.showerror(
                "CustomItem Unavailable",
                "custom_item/patcher.py is missing or failed to load.",
            )
            return
        item_id = self._custom_selected_item_id() or str(self.custom_item_id_var.get() or "").strip().lstrip(":").upper()
        if not item_id:
            messagebox.showwarning("Missing Item ID", "Choose a custom item entry or fill Item ID.")
            return
        if not messagebox.askyesno(
            "Delete Custom Item",
            (
                f"Delete custom item {item_id} from custom manifest/runtime patch?\n\n"
                "Parallel-only mode is enforced: Data/items.dat will not be modified. "
                "A rollback snapshot will be created."
            ),
        ):
            return
        try:
            result = custom_item_patcher.delete_custom_item(
                self.game_root,
                item_id,
                remove_from_items_dat=False,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CustomItem Delete Error", str(exc))
            return
        self._custom_reload_manifest()
        self.refresh_held_item_dropdowns()
        self._custom_clear_form()
        self.custom_item_status_var.set(
            f"Custom item {item_id} deleted. Patched files: {len(result.get('patched_files', []))}."
        )
        self.set_status(f"Custom item deleted: {item_id}")

    def custom_item_rollback_last(self):
        if custom_item_patcher is None:
            messagebox.showerror(
                "CustomItem Unavailable",
                "custom_item/patcher.py is missing or failed to load.",
            )
            return
        if not messagebox.askyesno(
            "Rollback Custom Item",
            "Rollback last custom item transaction (manifest/scripts and parallel custom-item files) now?",
        ):
            return
        try:
            result = custom_item_patcher.rollback_last_custom_item_transaction(self.game_root)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("CustomItem Rollback Error", str(exc))
            return
        self._custom_reload_manifest()
        self.refresh_held_item_dropdowns()
        self.custom_item_status_var.set(
            f"Rollback completed. Restored files: {len(result.get('restored_files', []))}."
        )
        self.set_status("Custom item rollback completed.")

    def manage_custom_item_runtime_patch(self):
        if custom_item_patcher is None:
            messagebox.showerror(
                "CustomItem Unavailable",
                "custom_item/patcher.py is missing or failed to load.",
            )
            return

        win = tk.Toplevel(self.root)
        win.title("Custom Item Runtime Patch")
        win.geometry("780x460")
        win.transient(self.root)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        text = tk.Text(win, wrap="word", height=20)
        text.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=(8, 4))
        text.configure(yscrollcommand=scroll.set)

        btns = ttk.Frame(win)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(4, 8))
        status_var = tk.StringVar(value="")
        ttk.Label(btns, textvariable=status_var).pack(side="left", fill="x", expand=True)

        def set_report(report: str):
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", report)
            text.configure(state="disabled")

        def refresh_report():
            try:
                status = custom_item_patcher.inspect_custom_item_runtime_patch(self.game_root)
                report = custom_item_patcher.format_custom_item_patch_report(status)
            except Exception as exc:  # noqa: BLE001
                report = f"Custom Item runtime inspect failed:\n{exc}"
                status_var.set("Inspect failed.")
            else:
                status_var.set("Runtime patch status refreshed.")
            set_report(report)

        def remove_runtime_patch():
            try:
                status = custom_item_patcher.inspect_custom_item_runtime_patch(self.game_root)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Runtime Patch Inspect Failed", str(exc), parent=win)
                return
            if not status.get("script_entry_present"):
                messagebox.showinfo("Custom Item Runtime Patch", "Runtime patch is not installed.", parent=win)
                refresh_report()
                return
            if not messagebox.askyesno(
                "Remove Runtime Patch",
                (
                    "Remove ZZ_CustomItemPatch from Data/Scripts.rxdata?\n\n"
                    "A rollback snapshot will be created. Manifest items and parallel runtime data will be kept, "
                    "so Apply Custom Item can install the patch again later."
                ),
                parent=win,
            ):
                return
            try:
                result = custom_item_patcher.remove_custom_item_runtime_patch(
                    self.game_root,
                    remove_runtime_data=False,
                )
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Runtime Patch Remove Failed", str(exc), parent=win)
                return
            after = result.get("status_after", {})
            set_report(custom_item_patcher.format_custom_item_patch_report(after if isinstance(after, dict) else {}))
            status_var.set("Runtime patch removed.")
            self.custom_item_status_var.set("Custom item runtime patch removed. Manifest/runtime data kept.")
            self.set_status("Custom item runtime patch removed.")

        def rollback_runtime_change():
            if not messagebox.askyesno(
                "Rollback Runtime Patch Change",
                "Rollback the last custom item transaction snapshot now?",
                parent=win,
            ):
                return
            try:
                result = custom_item_patcher.rollback_last_custom_item_transaction(self.game_root)
                status = custom_item_patcher.inspect_custom_item_runtime_patch(self.game_root)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Runtime Patch Rollback Failed", str(exc), parent=win)
                return
            set_report(custom_item_patcher.format_custom_item_patch_report(status))
            restored_count = len(result.get("restored_files", []))
            status_var.set(f"Rollback completed. Restored files: {restored_count}.")
            self._custom_reload_manifest()
            self.refresh_held_item_dropdowns()
            self.set_status("Custom item runtime rollback completed.")

        ttk.Button(btns, text="Refresh", command=refresh_report).pack(side="right", padx=2)
        ttk.Button(btns, text="Remove Patch", command=remove_runtime_patch).pack(side="right", padx=2)
        ttk.Button(btns, text="Rollback", command=rollback_runtime_change).pack(side="right", padx=2)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right", padx=2)

        refresh_report()

    # ------------------------- Legality check -------------------------
    def normalize_known_ids(self) -> tuple[int, list[str]]:
        if self.save_data is None or not self.catalogs:
            return 0, []

        self._custom_load_manifest_cache_silent()
        changes = 0
        unresolved: set[str] = set()

        def normalize_symbol_attr(
            obj: Any,
            attr_name: str,
            canonical_fn,
            unresolved_tag: str,
        ):
            nonlocal changes
            if not isinstance(obj, core.RubyObject):
                return
            if attr_name not in obj.attributes:
                return
            raw = symbol_name(obj.attributes[attr_name]).strip()
            if not raw:
                return
            raw_clean = raw.lstrip(":")
            canonical = canonical_fn(raw_clean)
            if canonical is None:
                unresolved.add(f"{unresolved_tag}:{raw_clean}")
                return
            if canonical != raw_clean:
                obj.attributes[attr_name] = core.Symbol(canonical)
                changes += 1

        player = self.get_root_key("player")
        party = core.read_attr(player, "@party", []) if isinstance(player, core.RubyObject) else []
        if isinstance(party, list):
            for pidx, pkmn in enumerate(party):
                if not isinstance(pkmn, core.RubyObject):
                    continue
                normalize_symbol_attr(
                    pkmn, "@species", self.catalogs.canonical_species_id, f"party[{pidx}].species"
                )
                normalize_symbol_attr(
                    pkmn, "@item", self._canonical_item_id_or_custom_manifest, f"party[{pidx}].item"
                )
                normalize_symbol_attr(
                    pkmn, "@ability", self.catalogs.canonical_ability_id, f"party[{pidx}].ability"
                )
                moves = core.read_attr(pkmn, "@moves", [])
                if isinstance(moves, list):
                    for midx, move in enumerate(moves):
                        normalize_symbol_attr(
                            move,
                            "@id",
                            self.catalogs.canonical_move_id,
                            f"party[{pidx}].move[{midx}]",
                        )

        bag = self.get_root_key("bag")
        pockets = core.read_attr(bag, "@pockets", []) if isinstance(bag, core.RubyObject) else []
        if isinstance(pockets, list):
            for pidx, pocket in enumerate(pockets):
                if not isinstance(pocket, list):
                    continue
                for eidx, entry in enumerate(pocket):
                    if not isinstance(entry, list) or len(entry) < 1:
                        continue
                    raw = symbol_name(entry[0]).strip()
                    if not raw:
                        continue
                    raw_clean = raw.lstrip(":")
                    canonical = self._canonical_item_id_or_custom_manifest(raw_clean)
                    if canonical is None:
                        unresolved.add(f"bag[{pidx}][{eidx}]:{raw_clean}")
                        continue
                    if canonical != raw_clean:
                        entry[0] = core.Symbol(canonical)
                        changes += 1
        return changes, sorted(unresolved)

    def _generate_legality_report(self) -> tuple[str, bool]:
        if self.save_data is None:
            return "No save loaded.", False
        self._custom_load_manifest_cache_silent()
        issues: list[str] = []
        warnings: list[str] = []
        if not self.catalogs:
            warnings.append("PBS catalogs are not loaded. ID checks are limited.")

        # Core structure sanity
        core_issues = core.sanity_check_save_data(self.save_data)
        for x in core_issues:
            issues.append(f"[Structure] {x}")

        party = self.get_party()
        for idx, pkmn in enumerate(party):
            if not isinstance(pkmn, core.RubyObject):
                warnings.append(f"[Party #{idx + 1}] Slot is not a Pokemon object.")
                continue

            species = symbol_name(core.read_attr(pkmn, "@species", ""))
            species_key = None
            if self.catalogs and species:
                species_key = self.catalogs.canonical_species_id(species)
                if species_key is None:
                    issues.append(f"[Party #{idx + 1}] Unknown species ID: {species}")

            level = core.read_attr(pkmn, "@level", None)
            if isinstance(level, int) and (level < 1 or level > 100):
                issues.append(f"[Party #{idx + 1}] Level out of range: {level}")

            held_item = symbol_name(core.read_attr(pkmn, "@item", ""))
            if self.catalogs and held_item:
                held_item_key = str(held_item or "").strip().lstrip(":").upper()
                if self.catalogs.canonical_item_id(held_item) is None and held_item_key not in self._custom_manifest_item_specs():
                    issues.append(f"[Party #{idx + 1}] Unknown held item ID: {held_item}")

            ability = symbol_name(core.read_attr(pkmn, "@ability", ""))
            if self.catalogs and ability:
                if self.catalogs.canonical_ability_id(ability) is None:
                    issues.append(f"[Party #{idx + 1}] Unknown ability ID: {ability}")

            moves = core.read_attr(pkmn, "@moves", [])
            if isinstance(moves, list):
                for mi, move_obj in enumerate(moves):
                    if not isinstance(move_obj, core.RubyObject):
                        warnings.append(f"[Party #{idx + 1} Move #{mi + 1}] Not a move object.")
                        continue
                    move_id = symbol_name(core.read_attr(move_obj, "@id", ""))
                    pp = core.read_attr(move_obj, "@pp", None)
                    ppup = core.read_attr(move_obj, "@ppup", 0)
                    move_key = None
                    if self.catalogs and move_id:
                        move_key = self.catalogs.canonical_move_id(move_id)
                    if self.catalogs and move_id and move_key is None:
                        issues.append(f"[Party #{idx + 1} Move #{mi + 1}] Unknown move ID: {move_id}")
                    if isinstance(pp, int) and pp < 0:
                        issues.append(f"[Party #{idx + 1} Move #{mi + 1}] Negative PP: {pp}")
                    if self.catalogs and move_key and move_key in self.catalogs.moves_by_id and isinstance(pp, int):
                        base = self.catalogs.moves_by_id[move_key].extra.get("TotalPP", "")
                        try:
                            base_pp = int(base)
                            max_pp = int(base_pp * (5 + (ppup if isinstance(ppup, int) else 0)) / 5)
                            if pp > max_pp:
                                warnings.append(
                                    f"[Party #{idx + 1} Move #{mi + 1}] PP {pp} > expected max {max_pp} ({move_key})."
                                )
                        except ValueError:
                            pass

        # Bag check
        bag = self.get_root_key("bag")
        pockets = core.read_attr(bag, "@pockets", []) if isinstance(bag, core.RubyObject) else []
        if isinstance(pockets, list):
            for pidx, pocket in enumerate(pockets):
                if not isinstance(pocket, list):
                    continue
                for eidx, entry in enumerate(pocket):
                    if not isinstance(entry, list) or len(entry) < 2:
                        warnings.append(f"[Bag pocket {pidx} idx {eidx}] Invalid entry structure.")
                        continue
                    iid = symbol_name(entry[0])
                    qty = entry[1]
                    iid_key = str(iid or "").strip().lstrip(":").upper()
                    if self.catalogs and iid and self.catalogs.canonical_item_id(iid) is None and iid_key not in self._custom_manifest_item_specs():
                        issues.append(f"[Bag pocket {pidx} idx {eidx}] Unknown item ID: {iid}")
                    if not isinstance(qty, int) or qty < 0:
                        issues.append(f"[Bag pocket {pidx} idx {eidx}] Invalid quantity: {qty}")

        report = []
        report.append("Legality Check Report")
        report.append("=" * 60)
        report.append(f"Issues: {len(issues)}")
        report.append(f"Warnings: {len(warnings)}")
        report.append("")
        if issues:
            report.append("[Issues]")
            report.extend(f"- {x}" for x in issues)
            report.append("")
        if warnings:
            report.append("[Warnings]")
            report.extend(f"- {x}" for x in warnings)
            report.append("")
        if not issues and not warnings:
            report.append("No obvious legality/consistency problems found.")

        return "\n".join(report), bool(issues)

    def _show_legality_report_window(self, report_text: str, has_issues: bool):
        win = tk.Toplevel(self.root)
        win.title("Legality Check")
        win.geometry("780x520")
        win.minsize(620, 380)
        try:
            win.transient(self.root)
        except Exception:
            pass

        shell = ttk.Frame(win, padding=10)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        summary = "Issues found" if has_issues else "No hard issues"
        ttk.Label(
            header,
            text=f"Checks unknown IDs and basic level/PP/quantity ranges. Result: {summary}.",
            foreground="#555555",
        ).grid(row=0, column=0, sticky="w")

        text_frame = ttk.Frame(shell)
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        output = tk.Text(text_frame, wrap="none", height=24)
        output.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(text_frame, orient="vertical", command=output.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(text_frame, orient="horizontal", command=output.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        output.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        output.insert("1.0", report_text)
        output.configure(state="disabled")

        btns = ttk.Frame(shell)
        btns.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        def rerun():
            new_report, new_has_issues = self._generate_legality_report()
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.insert("1.0", new_report)
            output.configure(state="disabled")
            new_summary = "Issues found" if new_has_issues else "No hard issues"
            for child in header.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(
                        text=f"Checks unknown IDs and basic level/PP/quantity ranges. Result: {new_summary}."
                    )
                    break
            self.set_status(
                "Legality check finished: issues found."
                if new_has_issues
                else "Legality check finished: no hard issues."
            )

        ttk.Button(btns, text="Run Again", command=rerun).pack(side="right", padx=2)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right", padx=2)

    def run_legality_check(self):
        report_text, has_issues = self._generate_legality_report()
        self._show_legality_report_window(report_text, has_issues)
        if self.save_data is None:
            self.set_status("Legality check skipped: no save loaded.")
        elif has_issues:
            self.set_status("Legality check finished: issues found.")
        else:
            self.set_status("Legality check finished: no hard issues.")

    # ------------------------- Helpers -------------------------
    def _species_choice(self, sid: str) -> str:
        sid = sid.lstrip(":")
        canonical = sid
        if self.catalogs:
            canonical = self.catalogs.canonical_species_id(sid) or sid
        return canonical

    def _move_choice(self, mid: str) -> str:
        mid = mid.lstrip(":")
        canonical = mid
        if self.catalogs:
            canonical = self.catalogs.canonical_move_id(mid) or mid
        return canonical

    def _item_choice(self, iid: str) -> str:
        iid = iid.lstrip(":")
        custom_id = iid.upper()
        if custom_id in self._custom_manifest_item_specs():
            return custom_id
        canonical = iid
        if self.catalogs:
            canonical = self.catalogs.canonical_item_id(iid) or iid
        return canonical

    def _ability_choice(self, aid: str) -> str:
        aid = aid.lstrip(":")
        canonical = aid
        if self.catalogs:
            canonical = self.catalogs.canonical_ability_id(aid) or aid
        return canonical

    def resolve_species_id(self, text: str) -> str:
        value = extract_internal_id(text)
        if self.catalogs:
            return self.catalogs.resolve_species_id(value)
        return value.lstrip(":")

    def resolve_move_id(self, text: str) -> str:
        value = extract_internal_id(text)
        if self.catalogs:
            return self.catalogs.resolve_move_id(value)
        return value.lstrip(":")

    def resolve_item_id(self, text: str) -> str:
        raw = text.strip()
        if hasattr(self, "_bag_item_label_to_id") and raw in self._bag_item_label_to_id:
            return self._bag_item_label_to_id[raw]
        if hasattr(self, "_party_item_label_to_id") and raw in self._party_item_label_to_id:
            return self._party_item_label_to_id[raw]
        value = extract_internal_id(raw)
        value = re.sub(r"\s+\[[^\]]+\]\s*$", "", value).strip()
        if " - " in value:
            value = value.split(" - ", 1)[0].strip()
        custom_id = value.strip().lstrip(":").upper()
        if custom_id in self._custom_manifest_item_specs():
            return custom_id
        if self.catalogs:
            return self.catalogs.resolve_item_id(value)
        return value.lstrip(":")

    def resolve_ability_id(self, text: str) -> str:
        value = extract_internal_id(text)
        if self.catalogs:
            return self.catalogs.resolve_ability_id(value)
        return value.lstrip(":")

    def get_root_key(self, key_name: str):
        if self.save_data is None:
            return None
        return core.read_root_key(self.save_data, key_name)

    def get_player(self):
        player = self.get_root_key("player")
        if not isinstance(player, core.RubyObject):
            messagebox.showerror("Error", "Player section missing in save.")
            return None
        return player

    def get_party(self) -> list:
        player = self.get_player()
        if not player:
            return []
        party = core.read_attr(player, "@party", [])
        if not isinstance(party, list):
            return []
        return party


def run_self_test() -> int:
    try:
        save_path = core.resolve_save_path(None)
        data = core.load_save(save_path)
        player = core.read_root_key(data, "player")
        money = core.read_attr(player, "@money") if isinstance(player, core.RubyObject) else None
        print(f"OK: loaded {save_path}")
        print(f"Player money: {money}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"SELF-TEST FAILED: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pokemon Indigo Save Editor GUI")
    parser.add_argument("--self-test", action="store_true", help="Run load test and exit.")
    parser.add_argument("--probe", action="store_true", help="Run game probe/remap and exit.")
    parser.add_argument("--verify-profile", action="store_true", help="Verify profile lock and exit.")
    parser.add_argument("--save", help="Path to save file (.rxdata).")
    parser.add_argument("--game-root", help="Path to game root folder.")
    parser.add_argument("--profile", help="Path to profile lock JSON.")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.probe or args.verify_profile:
        if probe_mapper is None:
            print("ERROR: probe mapper module is unavailable.", file=sys.stderr)
            return 2
        game_root = Path(args.game_root).expanduser().resolve() if args.game_root else DEFAULT_GAME_ROOT
        if not _looks_like_game_root(game_root):
            print(
                f"ERROR: invalid game root '{game_root}'. Expected Data folder (PBS optional for some games).",
                file=sys.stderr,
            )
            return 2
        try:
            save_path = (
                Path(args.save).expanduser().resolve()
                if args.save
                else core.resolve_save_path(None)
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if not save_path.exists():
            print(f"ERROR: save file not found: {save_path}", file=sys.stderr)
            return 2
        profile_path = (
            Path(args.profile).expanduser().resolve()
            if args.profile
            else probe_mapper.default_profile_path(game_root)
        )
        if args.verify_profile:
            ok, reason, details = probe_mapper.verify_profile_path(profile_path, game_root, save_path=save_path)
            print(reason)
            print(json.dumps(details, ensure_ascii=False, indent=2))
            return 0 if ok else 1
        profile = probe_mapper.run_probe(game_root=game_root, save_path=save_path, profile_path=profile_path)
        cfg = _load_app_settings()
        cfg["game_root"] = str(game_root)
        cfg["last_save_path"] = str(save_path)
        _save_app_settings(cfg)
        print(f"Profile written: {profile_path}")
        print(f"Game root: {game_root}")
        print(f"Save: {save_path}")
        print(f"Tracked files: {profile.get('game_probe', {}).get('tracked_file_count', 0)}")
        return 0

    initial_game_root: Path | None = None
    if args.game_root:
        try:
            initial_game_root = Path(args.game_root).expanduser().resolve()
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: invalid --game-root: {exc}", file=sys.stderr)
            return 2
        if not _looks_like_game_root(initial_game_root):
            print(
                f"ERROR: invalid game root '{initial_game_root}'. Expected Data folder (PBS optional for some games).",
                file=sys.stderr,
            )
            return 2
    root = tk.Tk()
    app = SaveEditorApp(root, initial_game_root=initial_game_root)
    if args.save:
        try:
            chosen = str(Path(args.save).expanduser().resolve())
            app.save_var.set(chosen)
        except Exception:
            app.save_var.set(str(args.save))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
