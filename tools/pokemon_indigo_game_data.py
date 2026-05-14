#!/usr/bin/env python
"""Load lightweight game data catalogs from PBS files."""

from __future__ import annotations

import unicodedata
from difflib import get_close_matches
from dataclasses import dataclass
from pathlib import Path
from importlib import import_module
import re
import zlib


def normalize_name(text: str) -> str:
    text = text.strip().lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    allowed = []
    for ch in text:
        if ch.isalnum():
            allowed.append(ch)
    return "".join(allowed)


def parse_pbs_sections(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    if not path.exists():
        return sections
    current_id: str | None = None
    current: dict[str, str] = {}

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            if current_id is not None:
                sections[current_id] = current
            current_id = line[1:-1].strip()
            current = {}
            continue
        if "=" in line and current_id is not None:
            k, v = line.split("=", 1)
            current[k.strip()] = v.strip()

    if current_id is not None:
        sections[current_id] = current
    return sections


@dataclass
class CatalogItem:
    internal_id: str
    display_name: str
    extra: dict[str, str]

    @property
    def label(self) -> str:
        if self.display_name and self.display_name != self.internal_id:
            return f"{self.internal_id} | {self.display_name}"
        return self.internal_id


@dataclass
class SpeciesLegalityProfile:
    internal_id: str
    species_id: str
    form: int
    form_name: str
    growth_rate_id: str
    base_stats: dict[str, int]
    ability_ids: list[str]
    hidden_ability_ids: list[str]
    level_up_moves: list[str]
    level_up_pairs: list[tuple[int, str]]
    tutor_moves: list[str]
    egg_moves: list[str]


class GameCatalogs:
    def __init__(self):
        self.items_by_id: dict[str, CatalogItem] = {}
        self.moves_by_id: dict[str, CatalogItem] = {}
        self.species_by_id: dict[str, CatalogItem] = {}
        self.abilities_by_id: dict[str, CatalogItem] = {}
        self.species_form_profiles: dict[tuple[str, int], SpeciesLegalityProfile] = {}
        self.growth_rate_exp_tables: dict[str, list[int]] = {}
        self.type_names_by_id: dict[str, str] = {}
        self.hidden_power_type_ids: list[str] = []
        self.natures: set[str] = set()
        self.pocket_names: list[str] = []
        self._item_name_index: dict[str, set[str]] = {}
        self._move_name_index: dict[str, set[str]] = {}
        self._species_name_index: dict[str, set[str]] = {}
        self._ability_name_index: dict[str, set[str]] = {}
        self._species_form_key_by_id: dict[str, tuple[str, int]] = {}
        self._item_id_ci: dict[str, str] = {}
        self._move_id_ci: dict[str, str] = {}
        self._species_id_ci: dict[str, str] = {}
        self._ability_id_ci: dict[str, str] = {}
        self._evolution_parents_cache: dict[str, set[str]] | None = None
        self.ability_english_by_id: dict[str, str] = {}

    @staticmethod
    def _add_name_index(index: dict[str, set[str]], display_name: str, internal_id: str):
        if not display_name:
            return
        key = normalize_name(display_name)
        if not key:
            return
        index.setdefault(key, set()).add(internal_id)

    @classmethod
    def load(cls, game_root: Path) -> "GameCatalogs":
        pbs = game_root / "PBS"
        out = cls()
        out.pocket_names = cls._load_bag_pocket_names(game_root)

        loaded_dat = out._load_from_dat(game_root)
        if not loaded_dat:
            out._load_from_pbs(pbs)
        out._merge_pbs_metadata(pbs)
        out._load_growth_rate_exp_tables(game_root)
        out._load_showdown_english_names(game_root)

        # Natures from scripts are usually fixed; include standard IDs used in Essentials.
        out.natures = {
            "HARDY", "LONELY", "BRAVE", "ADAMANT", "NAUGHTY",
            "BOLD", "DOCILE", "RELAXED", "IMPISH", "LAX",
            "TIMID", "HASTY", "SERIOUS", "JOLLY", "NAIVE",
            "MODEST", "MILD", "QUIET", "BASHFUL", "RASH",
            "CALM", "GENTLE", "SASSY", "CAREFUL", "QUIRKY",
        }
        return out

    @staticmethod
    def _normalize_growth_rate_id(value: str) -> str:
        raw = re.sub(r"[^A-Za-z0-9]", "", str(value).strip().lstrip(":")).upper()
        aliases = {
            "MEDIUMFAST": "MEDIUM",
            "MEDIUMSLOW": "PARABOLIC",
        }
        return aliases.get(raw, raw)

    @staticmethod
    def _minimum_exp_formula(growth_rate_id: str, level: int) -> int:
        lvl = max(1, int(level))
        gid = GameCatalogs._normalize_growth_rate_id(growth_rate_id)
        if gid == "FAST":
            return (lvl**3) * 4 // 5
        if gid == "SLOW":
            return (lvl**3) * 5 // 4
        if gid == "PARABOLIC":
            return ((lvl**3) * 6 // 5) - (15 * (lvl**2)) + (100 * lvl) - 140
        if gid == "ERRATIC":
            if lvl <= 50:
                return (lvl**3) * (100 - lvl) // 50
            if lvl <= 68:
                return (lvl**3) * (150 - lvl) // 100
            if lvl <= 98:
                return (lvl**3) * ((1911 - (10 * lvl)) // 3) // 500
            return (lvl**3) * (160 - lvl) // 100
        if gid == "FLUCTUATING":
            if lvl <= 15:
                return (lvl**3) * (24 + ((lvl + 1) // 3)) // 50
            if lvl <= 35:
                return (lvl**3) * (14 + lvl) // 50
            return (lvl**3) * (32 + (lvl // 2)) // 50
        return lvl**3

    def _load_growth_rate_exp_tables(self, game_root: Path):
        scripts_path = game_root / "Data" / "Scripts.rxdata"
        if not scripts_path.exists():
            return
        try:
            from rubymarshal.reader import loads  # lazy import
        except Exception:
            return
        try:
            scripts = loads(scripts_path.read_bytes())
            growth_src = None
            for _, name, comp in scripts:
                script_name = name.decode("utf-8", "replace") if isinstance(name, (bytes, bytearray)) else str(name)
                if script_name == "GrowthRate":
                    growth_src = zlib.decompress(comp).decode("utf-8", "replace")
                    break
            if not growth_src:
                return
            pattern = re.compile(
                r"GameData::GrowthRate\.register\(\{.*?:id\s*=>\s*:(\w+).*?:exp_values\s*=>\s*\[(.*?)\]",
                flags=re.DOTALL,
            )
            for growth_id, values_blob in pattern.findall(growth_src):
                values = [int(raw) for raw in re.findall(r"-?\d+", values_blob)]
                if len(values) <= 1:
                    continue
                key = self._normalize_growth_rate_id(growth_id)
                if key:
                    self.growth_rate_exp_tables[key] = values
        except Exception:
            return

    @staticmethod
    def _symbol_name(value) -> str:
        # Lazy import to avoid requiring rubymarshal when only reading PBS.
        try:
            from rubymarshal.classes import Symbol  # type: ignore
            if isinstance(value, Symbol):
                return value.name
        except Exception:
            pass
        return str(value)

    @staticmethod
    def _display_string(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode("latin-1", errors="replace")
        return str(value)

    def _register_item(self, target: dict[str, CatalogItem], id_ci: dict[str, str], name_idx: dict[str, set[str]], item: CatalogItem):
        target[item.internal_id] = item
        id_ci[item.internal_id.lower()] = item.internal_id
        self._add_name_index(name_idx, item.display_name, item.internal_id)

    @staticmethod
    def _unique_ordered(values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for v in values:
            if not v or v in seen:
                continue
            out.append(v)
            seen.add(v)
        return out

    def _symbol_list(self, values) -> list[str]:
        if not isinstance(values, list):
            return []
        out: list[str] = []
        for value in values:
            if value is None:
                continue
            out.append(self._symbol_name(value))
        return self._unique_ordered(out)

    def _level_up_move_ids(self, values) -> list[str]:
        if not isinstance(values, list):
            return []
        out: list[str] = []
        for entry in values:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                out.append(self._symbol_name(entry[1]))
        return self._unique_ordered(out)

    def _level_up_pairs(self, values) -> list[tuple[int, str]]:
        if not isinstance(values, list):
            return []
        out: list[tuple[int, str]] = []
        for entry in values:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            try:
                level = int(entry[0])
            except (TypeError, ValueError):
                continue
            move_id = self._symbol_name(entry[1])
            if not move_id:
                continue
            out.append((level, move_id))
        return out

    def _stat_dict(self, values) -> dict[str, int]:
        if not isinstance(values, dict):
            return {}
        out: dict[str, int] = {}
        for key, value in values.items():
            name = self._symbol_name(key)
            try:
                out[name] = int(value)
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _coerce_form(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _load_save_core_module(game_root: Path):
        from importlib.util import module_from_spec, spec_from_file_location

        candidates: list[Path] = []
        game_tools_core = game_root / "tools" / "pokemon_indigo_save_editor.py"
        if game_tools_core.exists():
            candidates.append(game_tools_core)
        local_core = Path(__file__).resolve().with_name("pokemon_indigo_save_editor.py")
        if local_core.exists():
            candidates.append(local_core)

        for core_path in candidates:
            try:
                spec = spec_from_file_location(f"_save_core_{len(str(core_path))}", core_path)
                if spec is None or spec.loader is None:
                    continue
                mod = module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore
                if hasattr(mod, "load_save") and hasattr(mod, "read_attr"):
                    return mod
            except Exception:
                continue

        try:
            mod = import_module("pokemon_indigo_save_editor")
            if hasattr(mod, "load_save") and hasattr(mod, "read_attr"):
                return mod
        except Exception:
            pass
        return None

    def _load_from_dat(self, game_root: Path) -> bool:
        try:
            mod = self._load_save_core_module(game_root)
            if mod is None:
                return False

            def load_map(path: Path):
                if not path.exists():
                    return None
                obj = mod.load_save(path)
                return obj if isinstance(obj, dict) else None

            items = load_map(game_root / "Data" / "items.dat")
            moves = load_map(game_root / "Data" / "moves.dat")
            species = load_map(game_root / "Data" / "species.dat")
            abilities = load_map(game_root / "Data" / "abilities.dat")
            types = load_map(game_root / "Data" / "types.dat")
            if not all([items, moves, species, abilities, types]):
                return False

            for key, val in items.items():
                iid = self._symbol_name(key)
                name = self._display_string(mod.read_attr(val, "@real_name", iid))
                pocket = mod.read_attr(val, "@pocket", "")
                extra = {"Pocket": str(pocket)}
                self._register_item(self.items_by_id, self._item_id_ci, self._item_name_index, CatalogItem(iid, name, extra))

            for key, val in moves.items():
                mid = self._symbol_name(key)
                name = self._display_string(mod.read_attr(val, "@real_name", mid))
                total_pp = mod.read_attr(val, "@total_pp", "")
                extra = {"TotalPP": str(total_pp)}
                self._register_item(self.moves_by_id, self._move_id_ci, self._move_name_index, CatalogItem(mid, name, extra))

            for key, val in species.items():
                sid = self._symbol_name(key)
                name = self._display_string(mod.read_attr(val, "@real_name", sid))
                self._register_item(self.species_by_id, self._species_id_ci, self._species_name_index, CatalogItem(sid, name, {}))
                species_base = self._symbol_name(mod.read_attr(val, "@species", sid))
                form = self._coerce_form(mod.read_attr(val, "@form", 0))
                form_name = self._display_string(mod.read_attr(val, "@real_form_name", ""))
                profile = SpeciesLegalityProfile(
                    internal_id=sid,
                    species_id=species_base,
                    form=form,
                    form_name=form_name,
                    growth_rate_id=self._symbol_name(mod.read_attr(val, "@growth_rate", "")),
                    base_stats=self._stat_dict(mod.read_attr(val, "@base_stats", {})),
                    ability_ids=self._symbol_list(mod.read_attr(val, "@abilities", [])),
                    hidden_ability_ids=self._symbol_list(mod.read_attr(val, "@hidden_abilities", [])),
                    level_up_moves=self._level_up_move_ids(mod.read_attr(val, "@moves", [])),
                    level_up_pairs=self._level_up_pairs(mod.read_attr(val, "@moves", [])),
                    tutor_moves=self._symbol_list(mod.read_attr(val, "@tutor_moves", [])),
                    egg_moves=self._symbol_list(mod.read_attr(val, "@egg_moves", [])),
                )
                self.species_form_profiles[(species_base, form)] = profile
                self._species_form_key_by_id[sid] = (species_base, form)

            for key, val in abilities.items():
                aid = self._symbol_name(key)
                name = self._display_string(mod.read_attr(val, "@real_name", aid))
                self._register_item(self.abilities_by_id, self._ability_id_ci, self._ability_name_index, CatalogItem(aid, name, {}))

            type_rows: list[tuple[int, str]] = []
            for key, val in types.items():
                tid = self._symbol_name(key)
                tname = self._display_string(mod.read_attr(val, "@real_name", tid))
                self.type_names_by_id[tid] = tname or tid
                icon_pos = mod.read_attr(val, "@icon_position", None)
                pseudo_type = bool(mod.read_attr(val, "@pseudo_type", False))
                if pseudo_type or tid in {"NORMAL", "SHADOW"}:
                    continue
                try:
                    icon = int(icon_pos)
                except (TypeError, ValueError):
                    continue
                type_rows.append((icon, tid))
            type_rows.sort(key=lambda x: x[0])
            self.hidden_power_type_ids = [tid for _icon, tid in type_rows]
            return True
        except Exception:
            return False

    def _load_from_pbs(self, pbs: Path):
        for iid, data in parse_pbs_sections(pbs / "items.txt").items():
            name = data.get("Name", iid)
            self._register_item(self.items_by_id, self._item_id_ci, self._item_name_index, CatalogItem(iid, name, data))
        for mid, data in parse_pbs_sections(pbs / "moves.txt").items():
            name = data.get("Name", mid)
            self._register_item(self.moves_by_id, self._move_id_ci, self._move_name_index, CatalogItem(mid, name, data))
        for sid, data in parse_pbs_sections(pbs / "pokemon.txt").items():
            name = data.get("Name", sid)
            self._register_item(self.species_by_id, self._species_id_ci, self._species_name_index, CatalogItem(sid, name, data))
            form = self._coerce_form(data.get("Form", 0))
            abilities = [x.strip() for x in data.get("Abilities", "").split(",") if x.strip()]
            hidden = [x.strip() for x in data.get("HiddenAbilities", "").split(",") if x.strip()]
            raw_moves = [x.strip() for x in data.get("Moves", "").split(",") if x.strip()]
            level_up_moves = [raw_moves[i] for i in range(1, len(raw_moves), 2)]
            tutor_moves = [x.strip() for x in data.get("TutorMoves", "").split(",") if x.strip()]
            egg_moves = [x.strip() for x in data.get("EggMoves", "").split(",") if x.strip()]
            species_base = data.get("Species", sid).strip() or sid
            profile = SpeciesLegalityProfile(
                internal_id=sid,
                species_id=species_base,
                form=form,
                form_name=data.get("FormName", ""),
                growth_rate_id=data.get("GrowthRate", ""),
                base_stats={},
                ability_ids=self._unique_ordered(abilities),
                hidden_ability_ids=self._unique_ordered(hidden),
                level_up_moves=self._unique_ordered(level_up_moves),
                level_up_pairs=[],
                tutor_moves=self._unique_ordered(tutor_moves),
                egg_moves=self._unique_ordered(egg_moves),
            )
            self.species_form_profiles[(species_base, form)] = profile
            self._species_form_key_by_id[sid] = (species_base, form)
        for aid, data in parse_pbs_sections(pbs / "abilities.txt").items():
            name = data.get("Name", aid)
            self._register_item(self.abilities_by_id, self._ability_id_ci, self._ability_name_index, CatalogItem(aid, name, data))

    def _merge_pbs_metadata(self, pbs: Path):
        if not pbs.exists():
            return

        def merge_section(
            path: Path,
            target: dict[str, CatalogItem],
            canonical_lookup,
        ):
            for raw_id, data in parse_pbs_sections(path).items():
                if not raw_id:
                    continue
                canonical = canonical_lookup(raw_id) or raw_id
                item = target.get(canonical)
                if not item:
                    continue
                for key, value in data.items():
                    if key not in item.extra or not str(item.extra.get(key, "")).strip():
                        item.extra[key] = value
                if (not item.display_name or item.display_name == item.internal_id) and data.get("Name"):
                    item.display_name = data["Name"]

        merge_section(pbs / "items.txt", self.items_by_id, self.canonical_item_id)
        merge_section(pbs / "moves.txt", self.moves_by_id, self.canonical_move_id)
        merge_section(pbs / "abilities.txt", self.abilities_by_id, self.canonical_ability_id)
        merge_section(pbs / "pokemon.txt", self.species_by_id, self.canonical_species_id)

    def _load_showdown_english_names(self, game_root: Path):
        path = game_root / "Data" / "data_for_showdown" / "abs_en.txt"
        if not path.exists():
            return
        try:
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                ability_id, sep, display = line.partition(",")
                if not sep:
                    continue
                canonical = self.canonical_ability_id(ability_id.strip()) or ability_id.strip().lstrip(":")
                label = display.strip()
                if canonical and label:
                    self.ability_english_by_id[canonical] = label
        except Exception:
            return

    @staticmethod
    def _load_bag_pocket_names(game_root: Path) -> list[str]:
        defaults = [
            "Items",
            "Medicine",
            "Poke Balls",
            "TMs/HMs",
            "Berries",
            "Mega Stones",
            "Battle Items",
            "Key Items",
        ]
        scripts_path = game_root / "Data" / "Scripts.rxdata"
        if not scripts_path.exists():
            return defaults
        try:
            from rubymarshal.reader import loads  # lazy import
        except Exception:
            return defaults
        try:
            scripts = loads(scripts_path.read_bytes())
            settings_src = None
            for _, name, comp in scripts:
                n = name.decode("utf-8", "replace") if isinstance(name, (bytes, bytearray)) else str(name)
                if n == "Settings":
                    settings_src = zlib.decompress(comp).decode("utf-8", "replace")
                    break
            if not settings_src:
                return defaults
            m = re.search(
                r"def\s+self\.bag_pocket_names\s*.*?return\s*\[(.*?)\]\s*end",
                settings_src,
                flags=re.DOTALL,
            )
            if not m:
                return defaults
            arr = m.group(1)
            names = re.findall(r'_INTL\("([^"]+)"\)', arr)
            return names or defaults
        except Exception:
            return defaults

    @staticmethod
    def _resolve_generic(
        value: str,
        by_id: dict[str, CatalogItem],
        by_id_ci: dict[str, str],
        by_name: dict[str, set[str]],
        kind: str,
    ) -> str:
        raw = value.strip()
        if not raw:
            raise ValueError(f"{kind} value is empty.")

        candidate = raw.lstrip(":")
        if candidate in by_id:
            return candidate
        low = candidate.lower()
        if low in by_id_ci:
            return by_id_ci[low]

        n = normalize_name(raw)
        if n in by_name:
            ids = sorted(by_name[n])
            if len(ids) == 1:
                return ids[0]
            raise ValueError(f"Ambiguous {kind} name '{raw}'. Matches: {', '.join(ids[:10])}")

        # Partial match against normalized display names.
        partial_ids: set[str] = set()
        for name_key, ids in by_name.items():
            if n and (n in name_key or name_key in n):
                partial_ids.update(ids)
        if len(partial_ids) == 1:
            return next(iter(partial_ids))
        if len(partial_ids) > 1:
            sample = ", ".join(sorted(partial_ids)[:10])
            raise ValueError(f"Ambiguous {kind} name '{raw}'. Similar: {sample}")

        # Try near-match by containment in label
        matches = [iid for iid, item in by_id.items() if n and n in normalize_name(item.label)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ValueError(f"Unknown {kind} '{raw}'. Similar: {', '.join(matches[:10])}")

        close_name_keys = get_close_matches(n, list(by_name.keys()), n=5, cutoff=0.80)
        if close_name_keys:
            ids: set[str] = set()
            for nk in close_name_keys:
                ids.update(by_name.get(nk, set()))
            if len(ids) == 1:
                return next(iter(ids))
            if ids:
                raise ValueError(f"Unknown {kind} '{raw}'. Similar: {', '.join(sorted(ids)[:10])}")

        raise ValueError(f"Unknown {kind} '{raw}'.")

    def resolve_item_id(self, value: str) -> str:
        return self._resolve_generic(value, self.items_by_id, self._item_id_ci, self._item_name_index, "item")

    def resolve_move_id(self, value: str) -> str:
        return self._resolve_generic(value, self.moves_by_id, self._move_id_ci, self._move_name_index, "move")

    def resolve_species_id(self, value: str) -> str:
        return self._resolve_generic(value, self.species_by_id, self._species_id_ci, self._species_name_index, "species")

    def resolve_ability_id(self, value: str) -> str:
        return self._resolve_generic(value, self.abilities_by_id, self._ability_id_ci, self._ability_name_index, "ability")

    def canonical_item_id(self, value: str) -> str | None:
        raw = value.strip().lstrip(":")
        if not raw:
            return None
        if raw in self.items_by_id:
            return raw
        return self._item_id_ci.get(raw.lower())

    def canonical_move_id(self, value: str) -> str | None:
        raw = value.strip().lstrip(":")
        if not raw:
            return None
        if raw in self.moves_by_id:
            return raw
        return self._move_id_ci.get(raw.lower())

    def canonical_species_id(self, value: str) -> str | None:
        raw = value.strip().lstrip(":")
        if not raw:
            return None
        if raw in self.species_by_id:
            return raw
        return self._species_id_ci.get(raw.lower())

    def canonical_ability_id(self, value: str) -> str | None:
        raw = value.strip().lstrip(":")
        if not raw:
            return None
        if raw in self.abilities_by_id:
            return raw
        return self._ability_id_ci.get(raw.lower())

    def ability_english_name(self, ability_id: str) -> str:
        canonical = self.canonical_ability_id(ability_id)
        if not canonical:
            return ""
        return str(self.ability_english_by_id.get(canonical, "")).strip()

    def get_species_form_profile(self, species_id: str, form: int | None = None) -> SpeciesLegalityProfile | None:
        canonical = self.canonical_species_id(species_id)
        if not canonical:
            return None
        species_base, form_from_id = self._species_form_key_by_id.get(canonical, (canonical, 0))
        target_form = form_from_id if form is None else self._coerce_form(form)
        profile = self.species_form_profiles.get((species_base, target_form))
        if profile:
            return profile
        profile = self.species_form_profiles.get((species_base, form_from_id))
        if profile:
            return profile
        return self.species_form_profiles.get((species_base, 0))

    def valid_abilities_for_species(self, species_id: str, form: int = 0) -> tuple[list[str], set[str]]:
        profile = self.get_species_form_profile(species_id, form=form)
        if not profile:
            return [], set()
        valid: list[str] = []
        for raw in self._unique_ordered(profile.ability_ids + profile.hidden_ability_ids):
            aid = self.canonical_ability_id(raw)
            if aid and aid not in valid:
                valid.append(aid)
        hidden: set[str] = set()
        for raw in profile.hidden_ability_ids:
            aid = self.canonical_ability_id(raw)
            if aid and aid in valid:
                hidden.add(aid)
        return valid, hidden

    def _evolution_parents_index(self) -> dict[str, set[str]]:
        if self._evolution_parents_cache is not None:
            return self._evolution_parents_cache
        parents: dict[str, set[str]] = {}
        for source_id, source_item in self.species_by_id.items():
            source = self.canonical_species_id(source_id) or source_id
            raw = str(source_item.extra.get("Evolutions", "")).strip()
            if not raw:
                continue
            for target_raw, _method, _param in self._parse_evolution_triplets(raw):
                target = self.canonical_species_id(target_raw) or target_raw
                if not target:
                    continue
                parents.setdefault(target, set()).add(source)
        self._evolution_parents_cache = parents
        return parents

    def ancestor_species_ids(self, species_id: str, form: int = 0) -> list[str]:
        profile = self.get_species_form_profile(species_id, form=form)
        start = ""
        if profile:
            start = profile.species_id or profile.internal_id
        if not start:
            start = self.canonical_species_id(species_id) or species_id.strip().lstrip(":")
        start = self.canonical_species_id(start) or start
        if not start:
            return []

        parents = self._evolution_parents_index()
        out: list[str] = []
        seen: set[str] = {start}
        stack: list[str] = [start]
        while stack:
            node = stack.pop()
            for parent in sorted(parents.get(node, set()), key=str.casefold):
                if parent in seen:
                    continue
                seen.add(parent)
                out.append(parent)
                stack.append(parent)
        return out

    def _move_legality_profiles_for_species(
        self,
        species_id: str,
        form: int = 0,
        include_pre_evolutions: bool = True,
    ) -> list[SpeciesLegalityProfile]:
        profiles: list[SpeciesLegalityProfile] = []
        seen_keys: set[tuple[str, int]] = set()

        def add_profile(target_species: str, target_form: int):
            profile = self.get_species_form_profile(target_species, form=target_form)
            if not profile:
                return
            key = (profile.species_id, profile.form)
            if key in seen_keys:
                return
            seen_keys.add(key)
            profiles.append(profile)

        add_profile(species_id, form)
        if include_pre_evolutions:
            for ancestor_id in self.ancestor_species_ids(species_id, form=form):
                add_profile(ancestor_id, 0)
        return profiles

    def valid_moves_for_species(self, species_id: str, form: int = 0, include_pre_evolutions: bool = True) -> list[str]:
        profiles = self._move_legality_profiles_for_species(
            species_id,
            form=form,
            include_pre_evolutions=include_pre_evolutions,
        )
        if not profiles:
            return []
        valid: list[str] = []
        for profile in profiles:
            for raw in profile.level_up_moves + profile.tutor_moves + profile.egg_moves:
                mid = self.canonical_move_id(raw)
                if mid and mid not in valid:
                    valid.append(mid)
        return valid

    def valid_relearn_moves_for_species(
        self,
        species_id: str,
        form: int = 0,
        include_pre_evolutions: bool = True,
    ) -> list[str]:
        profiles = self._move_legality_profiles_for_species(
            species_id,
            form=form,
            include_pre_evolutions=include_pre_evolutions,
        )
        if not profiles:
            return []
        valid: list[str] = []
        for profile in profiles:
            for raw in profile.level_up_moves + profile.egg_moves:
                mid = self.canonical_move_id(raw)
                if mid and mid not in valid:
                    valid.append(mid)
        return valid

    def base_stats_for_species(self, species_id: str, form: int = 0) -> dict[str, int]:
        profile = self.get_species_form_profile(species_id, form=form)
        return dict(profile.base_stats) if profile else {}

    def growth_rate_for_species(self, species_id: str, form: int = 0) -> str:
        profile = self.get_species_form_profile(species_id, form=form)
        raw = profile.growth_rate_id if profile else ""
        gid = self._normalize_growth_rate_id(raw)
        if gid:
            return gid
        return "MEDIUM"

    def minimum_exp_for_level(self, species_id: str, level: int, form: int = 0) -> int:
        try:
            lvl = max(1, int(level))
        except (TypeError, ValueError):
            lvl = 1
        growth_id = self.growth_rate_for_species(species_id, form=form)
        exp_values = self.growth_rate_exp_tables.get(growth_id)
        if exp_values:
            max_level = len(exp_values) - 1
            if max_level > 0:
                lvl = min(lvl, max_level)
            if lvl < len(exp_values):
                return max(0, int(exp_values[lvl]))
        return max(0, self._minimum_exp_formula(growth_id, lvl))

    def initial_moves_for_species(self, species_id: str, form: int = 0, level: int = 1) -> list[str]:
        profile = self.get_species_form_profile(species_id, form=form)
        if not profile:
            return []
        try:
            lvl = int(level)
        except (TypeError, ValueError):
            lvl = 1
        valid: list[str] = []
        for req_level, move in sorted(profile.level_up_pairs, key=lambda x: x[0]):
            if req_level > lvl:
                continue
            mid = self.canonical_move_id(move)
            if mid and mid not in valid:
                valid.append(mid)
        if not valid:
            valid = self.valid_moves_for_species(species_id, form=form, include_pre_evolutions=False)
        return valid[:4]

    @staticmethod
    def _description_from_extra(extra: dict[str, str]) -> str:
        if not isinstance(extra, dict):
            return ""
        for key in ("Description", "description", "Desc", "desc"):
            value = str(extra.get(key, "")).strip()
            if value:
                return value
        return ""

    def move_total_pp(self, move_id: str, default: int = 5) -> int:
        canonical = self.canonical_move_id(move_id)
        if not canonical:
            return default
        move = self.moves_by_id.get(canonical)
        if not move:
            return default
        raw = str(move.extra.get("TotalPP", move.extra.get("PP", ""))).strip()
        try:
            pp = int(raw)
        except (TypeError, ValueError):
            return default
        if pp <= 0:
            return default
        return pp

    def item_description(self, item_id: str) -> str:
        canonical = self.canonical_item_id(item_id)
        if not canonical:
            return ""
        item = self.items_by_id.get(canonical)
        if not item:
            return ""
        return self._description_from_extra(item.extra)

    def move_description(self, move_id: str) -> str:
        canonical = self.canonical_move_id(move_id)
        if not canonical:
            return ""
        item = self.moves_by_id.get(canonical)
        if not item:
            return ""
        return self._description_from_extra(item.extra)

    def ability_description(self, ability_id: str) -> str:
        canonical = self.canonical_ability_id(ability_id)
        if not canonical:
            return ""
        item = self.abilities_by_id.get(canonical)
        if not item:
            return ""
        return self._description_from_extra(item.extra)

    def species_evolution_rows(self, species_id: str, form: int = 0) -> list[tuple[str, str, str]]:
        profile = self.get_species_form_profile(species_id, form=form)
        candidate_ids: list[str] = []
        if profile:
            if profile.internal_id:
                candidate_ids.append(profile.internal_id)
            if profile.species_id and profile.species_id not in candidate_ids:
                candidate_ids.append(profile.species_id)
        canonical = self.canonical_species_id(species_id)
        if canonical and canonical not in candidate_ids:
            candidate_ids.append(canonical)

        raw = ""
        for sid in candidate_ids:
            item = self.species_by_id.get(sid)
            if not item:
                continue
            value = str(item.extra.get("Evolutions", "")).strip()
            if value:
                raw = value
                break
        if not raw:
            return []
        return self._parse_evolution_triplets(raw)

    @staticmethod
    def _parse_evolution_triplets(raw: str) -> list[tuple[str, str, str]]:
        # Essentials stores evolutions as repeating triplets:
        # target_species,method,parameter
        parts = [chunk.strip() for chunk in str(raw).split(",")]
        rows: list[tuple[str, str, str]] = []
        for i in range(0, len(parts), 3):
            target = parts[i] if i < len(parts) else ""
            method = parts[i + 1] if i + 1 < len(parts) else ""
            param = parts[i + 2] if i + 2 < len(parts) else ""
            if not target:
                continue
            rows.append((target, method, param))
        return rows

    def species_evolution_family_edges(
        self, species_id: str, form: int = 0
    ) -> list[tuple[str, str, list[tuple[str, str]]]]:
        profile = self.get_species_form_profile(species_id, form=form)
        start = ""
        if profile:
            start = profile.species_id or profile.internal_id
        if not start:
            start = self.canonical_species_id(species_id) or species_id.strip().lstrip(":")
        start = self.canonical_species_id(start) or start
        if not start:
            return []

        children: dict[str, set[str]] = {}
        parents: dict[str, set[str]] = {}
        edge_conditions: dict[tuple[str, str], set[tuple[str, str]]] = {}

        for source_id, source_item in self.species_by_id.items():
            source = self.canonical_species_id(source_id) or source_id
            raw = str(source_item.extra.get("Evolutions", "")).strip()
            if not raw:
                continue
            for target_raw, method, param in self._parse_evolution_triplets(raw):
                target = self.canonical_species_id(target_raw) or target_raw
                if not target:
                    continue
                children.setdefault(source, set()).add(target)
                parents.setdefault(target, set()).add(source)
                edge_conditions.setdefault((source, target), set()).add((method.strip(), param.strip()))

        # Build undirected evolution family component containing the selected species.
        component: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            for nxt in children.get(node, set()):
                if nxt not in component:
                    stack.append(nxt)
            for prev in parents.get(node, set()):
                if prev not in component:
                    stack.append(prev)

        edges: list[tuple[str, str, list[tuple[str, str]]]] = []
        for (source, target), conds in edge_conditions.items():
            if source not in component or target not in component:
                continue
            cond_list = sorted(conds, key=lambda x: (x[0].casefold(), x[1].casefold()))
            edges.append((source, target, cond_list))
        edges.sort(key=lambda row: (row[0].casefold(), row[1].casefold()))
        return edges

    def base_species_choices(self) -> list[CatalogItem]:
        ids: list[str] = []
        seen: set[str] = set()
        for (_, form), profile in self.species_form_profiles.items():
            if form != 0:
                continue
            sid = profile.internal_id
            if sid in self.species_by_id and sid not in seen:
                ids.append(sid)
                seen.add(sid)
        if not ids:
            for sid in self.species_by_id.keys():
                if sid in seen:
                    continue
                if "_" in sid:
                    continue
                ids.append(sid)
                seen.add(sid)
        ids.sort(key=lambda sid: self.species_by_id[sid].display_name.casefold())
        return [self.species_by_id[sid] for sid in ids]

    def item_display(self, iid: str) -> str:
        key = iid.lstrip(":")
        item = self.items_by_id.get(key) or self.items_by_id.get(self._item_id_ci.get(key.lower(), ""))
        return item.display_name if item else iid

    def move_display(self, mid: str) -> str:
        key = mid.lstrip(":")
        item = self.moves_by_id.get(key) or self.moves_by_id.get(self._move_id_ci.get(key.lower(), ""))
        return item.display_name if item else mid

    def species_display(self, sid: str) -> str:
        key = sid.lstrip(":")
        item = self.species_by_id.get(key) or self.species_by_id.get(self._species_id_ci.get(key.lower(), ""))
        return item.display_name if item else sid
