#!/usr/bin/env python
"""Pokemon Indigo save editor (Ruby Marshal, cycle-aware).

This tool targets Pokemon Indigo/Pokemon Anil save files in:
  %APPDATA%\\Pokemon Anil\\*.rxdata

It supports:
  - Listing save files
  - Quick summary
  - Reading any path
  - Writing any path (with automatic backup)

Path syntax examples:
  player.@money
  player.party.0.@level
  stats.@trainer_battles_won
  bag.@pockets.1.0.1
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Tuple

try:
    from rubymarshal.classes import (
        Extended,
        Module,
        RubyObject,
        RubyString,
        Symbol,
        UserDef,
        UsrMarshal,
    )
    from rubymarshal.classes import registry as global_registry
    from rubymarshal.constants import (
        TYPE_ARRAY,
        TYPE_BIGNUM,
        TYPE_CLASS,
        TYPE_DATA,
        TYPE_EXTENDED,
        TYPE_FALSE,
        TYPE_FIXNUM,
        TYPE_FLOAT,
        TYPE_HASH,
        TYPE_IVAR,
        TYPE_LINK,
        TYPE_MODULE,
        TYPE_NIL,
        TYPE_OBJECT,
        TYPE_REGEXP,
        TYPE_STRING,
        TYPE_STRUCT,
        TYPE_SYMBOL,
        TYPE_SYMLINK,
        TYPE_TRUE,
        TYPE_USERDEF,
        TYPE_USRMARSHAL,
    )
    from rubymarshal.reader import Reader
    from rubymarshal.writer import Writer, write as marshal_write
except ImportError as exc:
    print(
        "Missing dependency: rubymarshal.\n"
        "Install with: python -m pip install rubymarshal\n"
        f"Import error: {exc}",
        file=sys.stderr,
    )
    sys.exit(2)


class CycleAwareReader(Reader):
    """Patch rubymarshal reader to support cyclic object graphs in save files."""

    def read(self, in_ivar: bool = False):  # noqa: C901
        result = None
        object_index = None
        re_flags = None

        token = self.fd.read(1)

        # Reserve object slot for all linkable types.
        if token in (
            TYPE_CLASS,
            TYPE_MODULE,
            TYPE_FLOAT,
            TYPE_BIGNUM,
            TYPE_STRING,
            TYPE_REGEXP,
            TYPE_ARRAY,
            TYPE_HASH,
            TYPE_STRUCT,
            TYPE_OBJECT,
            TYPE_DATA,
            TYPE_USRMARSHAL,
            TYPE_USERDEF,
        ):
            object_index = len(self.objects)
            self.objects.append(None)

        if token == TYPE_NIL:
            pass
        elif token == TYPE_TRUE:
            result = True
        elif token == TYPE_FALSE:
            result = False
        elif token == TYPE_IVAR:
            result = self.read(in_ivar=True)
        elif token == TYPE_STRING:
            result = self.read_blob()
            if object_index is not None:
                self.objects[object_index] = result
        elif token == TYPE_SYMBOL:
            result = self.read_symreal()
        elif token == TYPE_FIXNUM:
            result = self.read_long()
        elif token == TYPE_ARRAY:
            size = self.read_long()
            result = []
            if object_index is not None:
                self.objects[object_index] = result
            for _ in range(size):
                result.append(self.read())
        elif token == TYPE_HASH:
            size = self.read_long()
            result = {}
            if object_index is not None:
                self.objects[object_index] = result
            for _ in range(size):
                key = self.ensure_hashable(self.read())
                value = self.read()
                result[key] = value
        elif token == TYPE_FLOAT:
            floatn = self.read_blob().split(b"\0")
            result = float(floatn[0].decode("utf-8"))
            if object_index is not None:
                self.objects[object_index] = result
        elif token == TYPE_BIGNUM:
            sign = 1 if self.fd.read(1) == b"+" else -1
            size = self.read_long()
            result = 0
            factor = 1
            for _ in range(size):
                result += self.read_short() * factor
                factor *= 2**16
            result *= sign
            if object_index is not None:
                self.objects[object_index] = result
        elif token == TYPE_REGEXP:
            result = self.read_blob()
            if object_index is not None:
                self.objects[object_index] = result
            options = ord(self.fd.read(1))
            re_flags = 0
            if options & 1:
                re_flags |= re.IGNORECASE
            if options & 4:
                re_flags |= re.MULTILINE
        elif token == TYPE_USRMARSHAL:
            class_symbol = self.read()
            if not isinstance(class_symbol, Symbol):
                raise ValueError(f"invalid class name: {class_symbol!r}")
            class_name = class_symbol.name
            python_class = self.registry.get(class_name, UsrMarshal)
            if not issubclass(python_class, UsrMarshal):
                raise ValueError(
                    f"invalid class mapping for {class_name!r}: {python_class!r}"
                )
            result = python_class(class_name)
            if object_index is not None:
                self.objects[object_index] = result
            attr_list = self.read()
            result.marshal_load(attr_list)
        elif token == TYPE_SYMLINK:
            result = self.read_symlink()
        elif token == TYPE_LINK:
            link_id = self.read_long()
            if link_id > len(self.objects):
                raise ValueError(
                    f"invalid link destination: {link_id} > {len(self.objects)}"
                )
            result = self.objects[link_id]
        elif token == TYPE_USERDEF:
            class_symbol = self.read()
            private_data = self.read_blob()
            if not isinstance(class_symbol, Symbol):
                raise ValueError(f"invalid class name: {class_symbol!r}")
            class_name = class_symbol.name
            python_class = self.registry.get(class_name, UserDef)
            if not issubclass(python_class, UserDef):
                raise ValueError(
                    f"invalid class mapping for {class_name!r}: {python_class!r}"
                )
            result = python_class(class_name)
            if object_index is not None:
                self.objects[object_index] = result
            result._load(private_data)  # pylint: disable=protected-access
        elif token == TYPE_MODULE:
            result = Module(self.read_blob().decode(), None)
            if object_index is not None:
                self.objects[object_index] = result
        elif token == TYPE_OBJECT:
            class_symbol = self.read()
            if not isinstance(class_symbol, Symbol):
                raise ValueError(f"invalid class name: {class_symbol!r}")
            class_name = class_symbol.name
            python_class = self.registry.get(class_name, RubyObject)
            if not issubclass(python_class, RubyObject):
                raise ValueError(
                    f"invalid class mapping for {class_name!r}: {python_class!r}"
                )
            result = python_class(class_name, {})
            if object_index is not None:
                self.objects[object_index] = result
            result.set_attributes(self.read_attributes())
        elif token == TYPE_EXTENDED:
            result = Extended(self.read_blob(), None)
            if object_index is not None:
                self.objects[object_index] = result
        elif token == TYPE_CLASS:
            class_name = self.read_blob().decode()
            if class_name in self.registry:
                result = self.registry[class_name]
            else:
                result = type(
                    class_name.rpartition(":")[2],
                    (RubyObject,),
                    {"ruby_class_name": class_name},
                )
            if object_index is not None:
                self.objects[object_index] = result
        else:
            raise ValueError(f"token {token!r} is not recognized")

        if in_ivar:
            attributes = self.read_attributes()
            if token in (TYPE_STRING, TYPE_REGEXP):
                encoding = self._get_encoding(attributes)
                try:
                    result = result.decode(encoding)
                except UnicodeDecodeError:
                    result = result.decode("unicode-escape")
                if attributes and token == TYPE_STRING:
                    result = RubyString(result, attributes)
            elif attributes and hasattr(result, "set_attributes"):
                result.set_attributes(attributes)

        if token == TYPE_REGEXP:
            result = re.compile(str(result), re_flags)

        if object_index is not None and self.objects[object_index] is None:
            self.objects[object_index] = result
        return result


class SaveWriter(Writer):
    """Ruby Marshal writer with stricter object-link accounting.

    The upstream writer doesn't treat some linkable token types (e.g. TYPE_FLOAT,
    TYPE_STRING/str/bytes, TYPE_MODULE, TYPE_CLASS, TYPE_BIGNUM) as tracked
    objects, which can shift link IDs and corrupt complex save graphs.
    """

    _RE_CLASS = type(re.compile(""))
    _SIMPLE_FLOAT_RE = re.compile(r"^\d+\.\d*0+$")

    def write(self, obj):  # noqa: C901
        if obj is None:
            self.write_none()
        elif obj is False:
            self.write_false()
        elif obj is True:
            self.write_true()
        elif isinstance(obj, int):
            self.write_int(obj)
        elif isinstance(obj, Symbol):
            self.write_symbol(obj)
        elif isinstance(obj, list):
            self.write_list(obj)
        elif isinstance(obj, dict):
            self.write_dict(obj)
        elif isinstance(obj, bytes):
            self.write_bytes(obj)
        elif isinstance(obj, str):
            self.write_string(obj)
        elif isinstance(obj, RubyString):
            self.write_ruby_string(obj)
        elif isinstance(obj, float):
            self.write_float(obj)
        elif isinstance(obj, self._RE_CLASS):
            self.write_regexp(obj)
        elif isinstance(obj, Module):
            self.write_module(obj)
        elif isinstance(obj, UsrMarshal):
            self.write_usr_marshal(obj)
        elif isinstance(obj, UserDef):
            self.write_user_def(obj)
        elif isinstance(obj, RubyObject):
            self.write_ruby_object(obj)
        elif isinstance(obj, type) and issubclass(obj, RubyObject):
            self.write_class(obj)
        else:
            self.write_python_object(obj)

    def write_python_object(self, obj):
        if isinstance(obj, tuple):
            # tuple keys came from Ruby array keys in hashes; write back as array
            return self.write_list(list(obj))
        return super().write_python_object(obj)

    def _write_bytes_raw(self, blob: bytes):
        self.fd.write(TYPE_STRING)
        self.write_long(len(blob))
        self.fd.write(blob)

    def write_bytes(self, obj):
        if self.must_write(obj):
            self._write_bytes_raw(obj)

    def write_string(self, obj):
        if self.must_write(obj):
            encoded = obj.encode("utf-8")
            self.fd.write(TYPE_IVAR)
            self._write_bytes_raw(encoded)
            self.write_long(1)
            self.write(Symbol("E"))
            self.write(True)

    def write_ruby_string(self, obj):
        if self.must_write(obj):
            encoding = "utf-8"
            attributes = obj.attributes
            if "E" in attributes and not attributes["E"]:
                encoding = "latin-1"
            elif "encoding" in attributes:
                encoding = attributes["encoding"].decode()
            else:
                attributes["E"] = True
            encoded = obj.encode(encoding)
            self.fd.write(TYPE_IVAR)
            self._write_bytes_raw(encoded)
            self.write_attributes(attributes)

    def write_float(self, obj):
        if self.must_write(obj):
            text = "%.20g" % obj
            if self._SIMPLE_FLOAT_RE.match(text):
                while text.endswith("0"):
                    text = text[:-1]
            encoded = text.encode("utf-8")
            self.fd.write(TYPE_FLOAT)
            self.write_long(len(encoded))
            self.fd.write(encoded)

    def write_regexp(self, obj):
        if self.must_write(obj):
            flags = 0
            if obj.flags & re.IGNORECASE:
                flags += 1
            if obj.flags & re.MULTILINE:
                flags += 4
            self.fd.write(TYPE_IVAR)
            self.fd.write(TYPE_REGEXP)
            pattern = obj.pattern.encode("utf-8")
            self.write_long(len(pattern))
            self.fd.write(pattern)
            self.fd.write(bytes([flags]))
            self.write_long(1)
            self.write(Symbol("E"))
            self.write(False)

    def write_module(self, obj):
        if self.must_write(obj):
            self.fd.write(TYPE_MODULE)
            encoded = obj.ruby_class_name.encode()
            self.write_long(len(encoded))
            self.fd.write(encoded)

    def write_class(self, obj):
        if self.must_write(obj):
            self.fd.write(TYPE_CLASS)
            encoded = obj.ruby_class_name.encode()
            self.write_long(len(encoded))
            self.fd.write(encoded)

    def write_int(self, obj):
        # Fixnum isn't linkable in Marshal; Bignum is.
        if obj.bit_length() <= 5 * 8:
            self.fd.write(TYPE_FIXNUM)
            self.write_long(obj)
            return
        if self.must_write(obj):
            self.fd.write(TYPE_BIGNUM)
            self.fd.write(b"-" if obj < 0 else b"+")
            obj = abs(obj)
            size = int((obj.bit_length() + 15) // 16)
            self.write_long(size)
            for _ in range(size):
                self.write_short(obj % 65536)
                obj //= 65536


def load_save(path: Path):
    with path.open("rb") as f:
        if f.read(1) != b"\x04" or f.read(1) != b"\x08":
            raise ValueError(f"{path} is not a Ruby Marshal v4.8 file")
        reader = CycleAwareReader(f, registry=global_registry)
        return reader.read()


def save_save(path: Path, obj, make_backup: bool = True) -> Path | None:
    backup_path = None
    if make_backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.name}.preedit-{stamp}.bak")
        shutil.copy2(path, backup_path)

    tmp_path = path.with_name(f"{path.name}.tmp")
    with tmp_path.open("wb") as f:
        marshal_write(f, obj, cls=SaveWriter)
    tmp_path.replace(path)
    return backup_path


def sanity_check_save_data(data: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(data, dict):
        return ["Top-level save data is not a Hash/dict."]

    required = ["player", "map_factory", "switches", "variables", "bag", "storage_system"]
    for key in required:
        if read_root_key(data, key) is None:
            issues.append(f"Missing top-level key: {key}")

    map_factory = read_root_key(data, "map_factory")
    if isinstance(map_factory, RubyObject):
        maps = read_attr(map_factory, "@maps", [])
        if not isinstance(maps, list) or not maps:
            issues.append("map_factory.@maps is missing or empty.")
        else:
            game_map = maps[0]
            if isinstance(game_map, RubyObject):
                events = read_attr(game_map, "@events", {})
                if isinstance(events, dict):
                    bad_events = []
                    for ev_id, game_event in events.items():
                        if not isinstance(game_event, RubyObject):
                            bad_events.append((ev_id, type(game_event).__name__))
                            continue
                        event_data = read_attr(game_event, "@event", None)
                        if not isinstance(event_data, RubyObject):
                            bad_events.append((ev_id, type(event_data).__name__))
                    if bad_events:
                        sample = ", ".join(f"{ev_id}:{typ}" for ev_id, typ in bad_events[:10])
                        issues.append(
                            "Invalid map event references (expected RubyObject). "
                            f"count={len(bad_events)} sample=[{sample}]"
                        )
                else:
                    issues.append("map_factory.@maps[0].@events is not a dict.")
            else:
                issues.append("map_factory.@maps[0] is not a RubyObject.")
    else:
        issues.append("map_factory is missing or invalid.")
    return issues


def validate_save_file(path: Path) -> list[str]:
    data = load_save(path)
    return sanity_check_save_data(data)


def default_save_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not available on this system.")
    return Path(appdata) / "Pokemon Anil"


def list_save_files(save_dir: Path) -> list[Path]:
    if not save_dir.exists():
        return []
    files = [p for p in save_dir.glob("*.rxdata") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def resolve_save_path(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    saves = list_save_files(default_save_dir())
    if not saves:
        raise RuntimeError("No .rxdata saves found in %APPDATA%\\Pokemon Anil")
    return saves[0]


def format_atom(value: Any) -> str:
    if isinstance(value, RubyString):
        return str(value)
    if isinstance(value, Symbol):
        return f":{value.name}"
    if isinstance(value, RubyObject):
        return f"<{value.ruby_class_name} attrs={len(value.attributes)}>"
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="replace")
    return repr(value)


def split_path(path: str) -> list[str]:
    if not path or path.strip() in {"/", "."}:
        return []
    parts = [p for p in path.strip().split(".") if p]
    out: list[str] = []
    for part in parts:
        # Allow foo[0][1] syntax in addition to foo.0.1
        m = re.finditer(r"([^\[\]]+)|\[(\d+)\]", part)
        matched = False
        for g in m:
            matched = True
            token = g.group(1) if g.group(1) is not None else g.group(2)
            out.append(token)
        if not matched:
            out.append(part)
    return out


def find_dict_key(d: dict, segment: str):
    if segment in d:
        return segment
    clean = segment[1:] if segment.startswith(":") else segment
    for key in d.keys():
        if isinstance(key, Symbol) and key.name == clean:
            return key
        if isinstance(key, str) and key == clean:
            return key
    raise KeyError(f"dict key not found: {segment}")


def find_attr_key(obj: RubyObject, segment: str) -> str:
    attrs = obj.attributes
    candidates = [segment]
    if segment.startswith("@"):
        candidates.append(segment[1:])
    else:
        candidates.append(f"@{segment}")
    for c in candidates:
        if c in attrs:
            return c
    raise KeyError(f"attribute not found: {segment}")


def step(container: Any, segment: str):
    if isinstance(container, RubyObject):
        key = find_attr_key(container, segment)
        return container.attributes[key], ("attr", container, key)
    if isinstance(container, dict):
        key = find_dict_key(container, segment)
        return container[key], ("dict", container, key)
    if isinstance(container, list):
        idx = int(segment)
        return container[idx], ("list", container, idx)
    if isinstance(container, tuple):
        idx = int(segment)
        return container[idx], ("tuple", container, idx)
    raise TypeError(f"Cannot traverse into {type(container).__name__} at segment {segment!r}")


def get_path_value(root: Any, path: str):
    cur = root
    for segment in split_path(path):
        cur, _ = step(cur, segment)
    return cur


def set_path_value(root: Any, path: str, value: Any):
    tokens = split_path(path)
    if not tokens:
        raise ValueError("Cannot assign root object; provide a non-empty path.")
    cur = root
    for segment in tokens[:-1]:
        cur, _ = step(cur, segment)
    _, where = step(cur, tokens[-1])
    kind, container, key = where
    if kind == "attr":
        container.attributes[key] = value
    elif kind == "dict":
        container[key] = value
    elif kind == "list":
        container[key] = value
    elif kind == "tuple":
        raise TypeError("Cannot assign into tuple path (immutable); edit parent object instead.")
    else:
        raise RuntimeError(f"Unexpected target kind: {kind}")


def describe(value: Any, depth: int = 2, indent: int = 0, seen: set[int] | None = None) -> str:
    if seen is None:
        seen = set()
    pad = "  " * indent
    atom = (str, int, float, bool, type(None), bytes, Symbol, RubyString)
    if isinstance(value, atom):
        return f"{pad}{format_atom(value)}"
    ident = id(value)
    if ident in seen:
        return f"{pad}<cycle>"
    if depth <= 0:
        return f"{pad}{format_atom(value)}"
    seen.add(ident)
    if isinstance(value, RubyObject):
        lines = [f"{pad}<{value.ruby_class_name}>"]
        for key in sorted(value.attributes.keys()):
            v = value.attributes[key]
            lines.append(f"{pad}  {key}:")
            lines.append(describe(v, depth - 1, indent + 2, seen))
        return "\n".join(lines)
    if isinstance(value, dict):
        lines = [f"{pad}dict(len={len(value)})"]
        for key, val in value.items():
            lines.append(f"{pad}  {format_atom(key)}:")
            lines.append(describe(val, depth - 1, indent + 2, seen))
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        lines = [f"{pad}{type(value).__name__}(len={len(value)})"]
        for idx, val in enumerate(value):
            lines.append(f"{pad}  [{idx}]")
            lines.append(describe(val, depth - 1, indent + 2, seen))
        return "\n".join(lines)
    return f"{pad}{repr(value)}"


def parse_bool(text: str) -> bool:
    val = text.strip().lower()
    if val in {"1", "true", "yes", "y", "on"}:
        return True
    if val in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Cannot parse bool: {text}")


def parse_value(raw: str, value_type: str, current_value: Any):
    if value_type == "auto":
        if isinstance(current_value, bool):
            return parse_bool(raw)
        if isinstance(current_value, int) and not isinstance(current_value, bool):
            return int(raw)
        if isinstance(current_value, float):
            return float(raw)
        if isinstance(current_value, Symbol):
            return Symbol(raw.lstrip(":"))
        if current_value is None:
            # Default nullable fields to string unless user picks explicit type.
            return raw
        return raw
    if value_type == "int":
        return int(raw)
    if value_type == "float":
        return float(raw)
    if value_type == "str":
        return raw
    if value_type == "bool":
        return parse_bool(raw)
    if value_type == "nil":
        return None
    if value_type == "symbol":
        return Symbol(raw.lstrip(":"))
    if value_type == "json":
        return json.loads(raw)
    raise ValueError(f"Unsupported --type: {value_type}")


def read_attr(obj: Any, name: str, default=None):
    if not isinstance(obj, RubyObject):
        return default
    if name in obj.attributes:
        return obj.attributes[name]
    with_at = f"@{name}" if not name.startswith("@") else name
    without_at = name[1:] if name.startswith("@") else name
    if with_at in obj.attributes:
        return obj.attributes[with_at]
    if without_at in obj.attributes:
        return obj.attributes[without_at]
    return default


def read_root_key(data: dict, key_name: str):
    for key in data.keys():
        if isinstance(key, Symbol) and key.name == key_name:
            return data[key]
        if isinstance(key, str) and key == key_name:
            return data[key]
    return None


def cmd_saves(_args):
    save_dir = default_save_dir()
    files = list_save_files(save_dir)
    if not files:
        print(f"No save files in {save_dir}")
        return 1
    print(f"Save directory: {save_dir}")
    for f in files:
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"- {f.name}  ({f.stat().st_size} bytes, {ts})")
    return 0


def cmd_summary(args):
    save_path = resolve_save_path(args.save)
    data = load_save(save_path)

    player = read_root_key(data, "player")
    stats = read_root_key(data, "stats")
    map_factory = read_root_key(data, "map_factory")
    game_player = read_root_key(data, "game_player")

    print(f"Save: {save_path}")
    print(f"Top-level sections: {', '.join(str(getattr(k, 'name', k)) for k in data.keys())}")

    if isinstance(player, RubyObject):
        name = read_attr(player, "@name")
        tid = read_attr(player, "@id")
        money = read_attr(player, "@money")
        bp = read_attr(player, "@battle_points")
        save_slot = read_attr(player, "@save_slot")
        last_saved = read_attr(player, "@last_time_saved")
        badges = read_attr(player, "@badges", [])
        party = read_attr(player, "@party", [])
        print(f"Player: {format_atom(name)}  (ID: {format_atom(tid)})")
        print(f"Money: {format_atom(money)}  BP: {format_atom(bp)}")
        print(f"Save Slot: {format_atom(save_slot)}  Last Saved: {format_atom(last_saved)}")
        if isinstance(badges, list):
            badge_count = sum(1 for b in badges if b)
            print(f"Badges: {badge_count}/{len(badges)}")
        if isinstance(party, list):
            print(f"Party ({len(party)}):")
            for i, pkmn in enumerate(party[:6], 1):
                if not isinstance(pkmn, RubyObject):
                    print(f"  {i}. {format_atom(pkmn)}")
                    continue
                species = read_attr(pkmn, "@species")
                level = read_attr(pkmn, "@level")
                hp = read_attr(pkmn, "@hp")
                total = read_attr(pkmn, "@totalhp")
                shiny = read_attr(pkmn, "@shiny")
                shiny_tag = " shiny" if shiny else ""
                print(
                    f"  {i}. {format_atom(species)} Lv{format_atom(level)} "
                    f"HP {format_atom(hp)}/{format_atom(total)}{shiny_tag}"
                )

    if isinstance(stats, RubyObject):
        play_time = read_attr(stats, "@play_time")
        wild_won = read_attr(stats, "@wild_battles_won")
        trainer_won = read_attr(stats, "@trainer_battles_won")
        print(
            "Stats: "
            f"play_time={format_atom(play_time)}, "
            f"wild_wins={format_atom(wild_won)}, "
            f"trainer_wins={format_atom(trainer_won)}"
        )

    if isinstance(map_factory, RubyObject):
        map_obj = read_attr(map_factory, "@map")
        map_id = read_attr(map_obj, "@map_id")
        if map_id is None and isinstance(game_player, RubyObject):
            map_id = read_attr(game_player, "@map_id")
        print(f"Current map_id: {format_atom(map_id)}")

    return 0


def cmd_validate(args):
    save_path = resolve_save_path(args.save)
    try:
        issues = validate_save_file(save_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Validation failed to load save: {exc}")
        return 1
    print(f"Save: {save_path}")
    if not issues:
        print("Validation: OK")
        return 0
    print("Validation: FAILED")
    for issue in issues:
        print(f"- {issue}")
    return 2


def cmd_repair(args):
    save_path = resolve_save_path(args.save)
    folder = save_path.parent
    name = save_path.name

    candidates: list[Path] = []
    if save_path.exists():
        candidates.append(save_path)
    candidates.extend(sorted(folder.glob(f"{name}.preedit-*.bak"), key=lambda p: p.stat().st_mtime, reverse=True))
    legacy = folder / f"{name}.bak"
    if legacy.exists():
        candidates.append(legacy)

    chosen = None
    for cand in candidates:
        try:
            issues = validate_save_file(cand)
            if not issues:
                chosen = cand
                break
        except Exception:
            continue

    if chosen is None:
        print("No valid backup candidate found.")
        return 1

    if chosen.resolve() == save_path.resolve():
        print(f"Current save is already valid: {save_path}")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    corrupt_backup = save_path.with_name(f"{save_path.name}.corrupt-{stamp}.bak")
    if save_path.exists():
        shutil.copy2(save_path, corrupt_backup)
    shutil.copy2(chosen, save_path)
    print(f"Restored save from: {chosen}")
    print(f"Current (possibly corrupt) copy saved to: {corrupt_backup}")
    print(f"Active save: {save_path}")
    return 0


def cmd_get(args):
    save_path = resolve_save_path(args.save)
    data = load_save(save_path)
    value = get_path_value(data, args.path)
    print(describe(value, depth=args.depth))
    return 0


def cmd_list(args):
    save_path = resolve_save_path(args.save)
    data = load_save(save_path)
    value = get_path_value(data, args.path) if args.path else data
    if isinstance(value, RubyObject):
        for key in sorted(value.attributes.keys()):
            print(key)
        return 0
    if isinstance(value, dict):
        for key in value.keys():
            print(format_atom(key))
        return 0
    if isinstance(value, (list, tuple)):
        for i in range(len(value)):
            print(i)
        return 0
    print(f"Path points to scalar: {format_atom(value)}")
    return 0


def cmd_set(args):
    save_path = resolve_save_path(args.save)
    data = load_save(save_path)
    current = get_path_value(data, args.path)
    new_value = parse_value(args.value, args.type, current)
    set_path_value(data, args.path, new_value)
    backup = save_save(save_path, data, make_backup=not args.no_backup)
    issues = validate_save_file(save_path)
    if issues:
        if backup and Path(backup).exists():
            shutil.copy2(backup, save_path)
        issue_text = "\n".join(f"- {x}" for x in issues)
        raise RuntimeError(
            "Save failed sanity check and was reverted from backup.\n"
            f"{issue_text}"
        )
    print(f"Updated {args.path}")
    print(f"Old: {describe(current, depth=1)}")
    print(f"New: {describe(new_value, depth=1)}")
    if backup:
        print(f"Backup: {backup}")
    print(f"Wrote: {save_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pokemon Indigo save editor for .rxdata (Ruby Marshal)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_saves = sub.add_parser("saves", help="List discovered save files.")
    p_saves.set_defaults(func=cmd_saves)

    p_summary = sub.add_parser("summary", help="Show a quick save summary.")
    p_summary.add_argument("--save", help="Path to .rxdata save file.")
    p_summary.set_defaults(func=cmd_summary)

    p_validate = sub.add_parser("validate", help="Run sanity checks on a save.")
    p_validate.add_argument("--save", help="Path to .rxdata save file.")
    p_validate.set_defaults(func=cmd_validate)

    p_repair = sub.add_parser("repair", help="Restore current save from latest valid backup.")
    p_repair.add_argument("--save", help="Path to .rxdata save file.")
    p_repair.set_defaults(func=cmd_repair)

    p_get = sub.add_parser("get", help="Read a value at path.")
    p_get.add_argument("--save", help="Path to .rxdata save file.")
    p_get.add_argument("--path", required=True, help="Path (e.g. player.@money)")
    p_get.add_argument("--depth", type=int, default=2, help="Print depth (default: 2)")
    p_get.set_defaults(func=cmd_get)

    p_list = sub.add_parser("list", help="List children at path (or root).")
    p_list.add_argument("--save", help="Path to .rxdata save file.")
    p_list.add_argument("--path", default="", help="Path to list.")
    p_list.set_defaults(func=cmd_list)

    p_set = sub.add_parser("set", help="Set value at path.")
    p_set.add_argument("--save", help="Path to .rxdata save file.")
    p_set.add_argument("--path", required=True, help="Path (e.g. player.@money)")
    p_set.add_argument("--value", required=True, help="New value text.")
    p_set.add_argument(
        "--type",
        default="auto",
        choices=["auto", "int", "float", "str", "bool", "nil", "symbol", "json"],
        help="Value parser type (default: auto)",
    )
    p_set.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create pre-edit backup file.",
    )
    p_set.set_defaults(func=cmd_set)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
