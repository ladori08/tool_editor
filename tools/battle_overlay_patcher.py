#!/usr/bin/env python
"""In-game battle overlay installer.

The overlay is intentionally installed as a runtime script patch. It does not
write game data tables, save data, item data, or custom item manifests.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pokemon_indigo_ev_patcher as ev_patcher


MANIFEST_VERSION = 1
OVERLAY_VERSION = 1
SCRIPT_ENTRY_NAME = "ZZ_BattleStateOverlay"
OVERLAY_DIRNAME = "battle_overlay"
MANIFEST_FILENAME = "battle_overlay_state.json"
BACKUP_ROOT_DIRNAME = "backups"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _resolve_game_root(game_root: Path | str) -> Path:
    root = Path(game_root).expanduser().resolve()
    if not (root / "Data").is_dir():
        raise ValueError(f"Invalid game root (missing Data folder): {root}")
    return root


def _scripts_path(root: Path) -> Path:
    return root / "Data" / "Scripts.rxdata"


def _scripts_dir(root: Path) -> Path:
    return root / "Data" / "Scripts"


def _overlay_dir(root: Path) -> Path:
    return root / "tools" / OVERLAY_DIRNAME


def _manifest_path(root: Path) -> Path:
    return _overlay_dir(root) / MANIFEST_FILENAME


def _backup_root(root: Path) -> Path:
    return _overlay_dir(root) / BACKUP_ROOT_DIRNAME


def _relative_to_root(root: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except Exception:
        return Path("_external") / path.name


def _backup_path(root: Path, target_path: Path, kind: str, stamp: str) -> Path:
    rel = _relative_to_root(root, target_path)
    out_dir = _backup_root(root) / kind / rel.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{target_path.name}.{stamp}.bak"


def _copy_to_backup(root: Path, target_path: Path, kind: str, stamp: str) -> Path:
    backup = _backup_path(root, target_path, kind, stamp)
    shutil.copy2(target_path, backup)
    return backup


def _load_manifest(root: Path) -> dict[str, Any]:
    path = _manifest_path(root)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_manifest(root: Path, data: dict[str, Any]) -> None:
    path = _manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _entry_name(raw: Any) -> str:
    if isinstance(raw, bytes):
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _find_main_script_index(scripts_obj: list[Any]) -> int:
    for idx, entry in enumerate(scripts_obj):
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        if _entry_name(entry[1]).strip().lower() == "main":
            return idx
    return -1


def _find_script_entry(scripts_obj: list[Any], name: str = SCRIPT_ENTRY_NAME) -> tuple[int, list[Any] | None]:
    for idx, entry in enumerate(scripts_obj):
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        if _entry_name(entry[1]).strip() == name:
            return idx, entry
    return -1, None


def _decode_entry_source(entry: list[Any]) -> str:
    source, _encoding = ev_patcher._decode_script_source(bytes(entry[2]))
    return source


def _normalize_source(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").strip()


def _next_script_id(scripts_obj: list[Any]) -> int:
    next_id = 0
    for entry in scripts_obj:
        if not isinstance(entry, list) or not entry:
            continue
        try:
            next_id = max(next_id, int(entry[0]))
        except Exception:
            continue
    return next_id + 1


def _discover_adapter(root: Path) -> dict[str, Any]:
    scripts_file = _scripts_path(root)
    if scripts_file.exists():
        try:
            scripts_obj = ev_patcher._load_scripts_object(scripts_file)
        except Exception as exc:  # noqa: BLE001
            return {
                "adapter": "scripts_rxdata",
                "source_type": "rxdata",
                "can_apply": False,
                "target_path": str(scripts_file),
                "reason": f"Scripts.rxdata exists but could not be decoded: {exc}",
            }
        return {
            "adapter": "scripts_rxdata",
            "source_type": "rxdata",
            "can_apply": True,
            "target_path": str(scripts_file),
            "scripts_obj": scripts_obj,
            "reason": "Packed Scripts.rxdata adapter is available.",
        }
    scripts_folder = _scripts_dir(root)
    if scripts_folder.is_dir():
        rb_files = [p for p in scripts_folder.rglob("*.rb") if p.is_file()]
        return {
            "adapter": "rb_file",
            "source_type": "rb_file",
            "can_apply": False,
            "target_path": str(scripts_folder),
            "rb_file_count": len(rb_files),
            "reason": (
                "Loose Ruby script folder detected. This layout needs a per-game load-order "
                "adapter before the overlay can be installed safely."
            ),
        }
    return {
        "adapter": "unsupported",
        "source_type": "unsupported",
        "can_apply": False,
        "target_path": "",
        "reason": "No supported script layout found.",
    }


def _build_overlay_source() -> str:
    lines = [
        "# Auto-generated by Pokemon Indigo Save Editor Battle Overlay module.",
        "# Runtime UI overlay only; does not write game data or save data.",
        "module CustomBattleOverlay",
        f"  OVERLAY_VERSION = {OVERLAY_VERSION}",
        "  MODE_OFF = 0",
        "  MODE_COMPACT = 1",
        "  MODE_DETAIL = 2",
        "  @mode = MODE_COMPACT",
        "",
        "  STAT_LABELS = [",
        "    [:ATTACK, \"Atk\"],",
        "    [:DEFENSE, \"Def\"],",
        "    [:SPECIAL_ATTACK, \"SpA\"],",
        "    [:SPECIAL_DEFENSE, \"SpD\"],",
        "    [:SPEED, \"Spe\"],",
        "    [:ACCURACY, \"Acc\"],",
        "    [:EVASION, \"Eva\"]",
        "  ]",
        "",
        "  SIDE_EFFECTS = [",
        "    [:Reflect, \"Reflect\", \"Physical dmg x0.5 solo / x0.67 doubles\"],",
        "    [:LightScreen, \"Light Screen\", \"Special dmg x0.5 solo / x0.67 doubles\"],",
        "    [:AuroraVeil, \"Aurora Veil\", \"Physical+Special dmg x0.5 solo / x0.67 doubles\"],",
        "    [:Safeguard, \"Safeguard\", \"Blocks major status\"],",
        "    [:Mist, \"Mist\", \"Blocks stat drops\"],",
        "    [:Tailwind, \"Tailwind\", \"Speed x2\"],",
        "    [:Spikes, \"Spikes\", \"Entry hazard layers\"],",
        "    [:ToxicSpikes, \"Toxic Spikes\", \"Poison entry hazard\"],",
        "    [:StealthRock, \"Stealth Rock\", \"Rock entry damage\"],",
        "    [:StickyWeb, \"Sticky Web\", \"Speed drop on entry\"]",
        "  ]",
        "",
        "  BATTLER_EFFECTS = [",
        "    [:Substitute, \"Substitute\"],",
        "    [:Protect, \"Protect\"],",
        "    [:KingsShield, \"King's Shield\"],",
        "    [:SpikyShield, \"Spiky Shield\"],",
        "    [:BanefulBunker, \"Baneful Bunker\"],",
        "    [:Taunt, \"Taunt\"],",
        "    [:Encore, \"Encore\"],",
        "    [:Torment, \"Torment\"],",
        "    [:Disable, \"Disable\"],",
        "    [:LeechSeed, \"Leech Seed\"],",
        "    [:Confusion, \"Confusion\"],",
        "    [:Flinch, \"Flinch\"],",
        "    [:PerishSong, \"Perish Song\"],",
        "    [:AquaRing, \"Aqua Ring\"],",
        "    [:Ingrain, \"Ingrain\"]",
        "  ]",
        "",
        "  def self.mode",
        "    @mode ||= MODE_COMPACT",
        "    return @mode",
        "  end",
        "",
        "  def self.toggle_mode",
        "    @mode = (mode + 1) % 3",
        "  end",
        "",
        "  def self.update_for_scene(scene)",
        "    begin",
        "      toggle_mode if input_toggle?",
        "      sprite = ensure_sprite(scene)",
        "      return if !sprite || !sprite.bitmap",
        "      sprite.visible = (mode != MODE_OFF)",
        "      return if mode == MODE_OFF",
        "      draw_overlay(sprite.bitmap, scene)",
        "    rescue StandardError => e",
        "      echoln(\"Battle overlay error: #{e}\") if defined?(echoln)",
        "    end",
        "  end",
        "",
        "  def self.input_toggle?",
        "    return false if !defined?(Input)",
        "    return Input.triggerex?(:F7) if Input.respond_to?(:triggerex?)",
        "    return false",
        "  rescue StandardError",
        "    return false",
        "  end",
        "",
        "  def self.ensure_sprite(scene)",
        "    sprites = scene.instance_variable_get(:@sprites) rescue nil",
        "    viewport = scene.instance_variable_get(:@viewport) rescue nil",
        "    return nil if !sprites.is_a?(Hash)",
        "    sprite = sprites[\"custom_battle_overlay\"]",
        "    if !sprite || sprite.disposed?",
        "      sprite = BitmapSprite.new(Graphics.width, Graphics.height, viewport)",
        "      sprite.z = 260",
        "      sprites[\"custom_battle_overlay\"] = sprite",
        "    end",
        "    return sprite",
        "  rescue StandardError",
        "    return nil",
        "  end",
        "",
        "  def self.dispose_for_scene(scene)",
        "    sprites = scene.instance_variable_get(:@sprites) rescue nil",
        "    return if !sprites.is_a?(Hash)",
        "    sprite = sprites.delete(\"custom_battle_overlay\")",
        "    sprite.dispose if sprite && !sprite.disposed?",
        "  rescue StandardError",
        "  end",
        "",
        "  def self.draw_overlay(bitmap, scene)",
        "    bitmap.clear",
        "    battle = scene.instance_variable_get(:@battle) rescue nil",
        "    return if !battle",
        "    pbSetSmallFont(bitmap) rescue pbSetSystemFont(bitmap) rescue nil",
        "    if mode == MODE_COMPACT",
        "      draw_compact(bitmap, battle)",
        "    else",
        "      draw_detail(bitmap, battle)",
        "    end",
        "  end",
        "",
        "  def self.panel(bitmap, x, y, w, h)",
        "    bitmap.fill_rect(x, y, w, h, Color.new(0, 0, 0, 150))",
        "    bitmap.fill_rect(x, y, w, 1, Color.new(240, 240, 240, 190))",
        "    bitmap.fill_rect(x, y + h - 1, w, 1, Color.new(240, 240, 240, 120))",
        "  end",
        "",
        "  def self.text(bitmap, x, y, w, value, color = nil)",
        "    old = bitmap.font.color rescue nil",
        "    bitmap.font.color = color if color",
        "    bitmap.draw_text(x, y, w, 18, value.to_s)",
        "    bitmap.font.color = old if old",
        "  rescue StandardError",
        "  end",
        "",
        "  def self.header(bitmap, x, y, w, value)",
        "    text(bitmap, x, y, w, value, Color.new(255, 230, 120))",
        "  end",
        "",
        "  def self.draw_compact(bitmap, battle)",
        "    y = 6",
        "    text(bitmap, 8, y, 260, \"Battle Overlay: Compact (F7)\", Color.new(180, 220, 255))",
        "    battle.battlers.each_with_index do |battler, idx|",
        "      next if !visible_battler?(battler)",
        "      lines = compact_battler_lines(battler)",
        "      next if lines.empty?",
        "      x = battler.index.even? ? 18 : Graphics.width - 190",
        "      by = battler.index.even? ? Graphics.height - 180 - (idx * 18) : 52 + (idx * 18)",
        "      h = 18 + (lines.length * 16)",
        "      panel(bitmap, x, by, 172, h)",
        "      header(bitmap, x + 6, by + 2, 160, battler_name(battler))",
        "      lines.each_with_index { |line, i| text(bitmap, x + 6, by + 18 + (i * 16), 160, line, line_color(line)) }",
        "    end",
        "  end",
        "",
        "  def self.draw_detail(bitmap, battle)",
        "    text(bitmap, 8, 6, 260, \"Battle Overlay: Detail (F7)\", Color.new(180, 220, 255))",
        "    left = 8",
        "    right = Graphics.width - 228",
        "    y = 28",
        "    y = draw_column(bitmap, left, y, 212, \"Stats\", detail_stat_lines(battle))",
        "    draw_column(bitmap, left, y + 6, 212, \"Volatile\", detail_volatile_lines(battle))",
        "    y2 = 28",
        "    y2 = draw_column(bitmap, right, y2, 220, \"Weather / Terrain\", field_lines(battle))",
        "    y2 = draw_column(bitmap, right, y2 + 6, 220, \"Walls / Side\", side_lines(battle))",
        "    draw_column(bitmap, right, y2 + 6, 220, \"Custom Item\", custom_item_lines(battle))",
        "  end",
        "",
        "  def self.draw_column(bitmap, x, y, w, title, lines)",
        "    lines = [\"none\"] if !lines || lines.empty?",
        "    h = 22 + (lines.length * 16)",
        "    panel(bitmap, x, y, w, h)",
        "    header(bitmap, x + 6, y + 3, w - 12, title)",
        "    lines.each_with_index { |line, i| text(bitmap, x + 6, y + 22 + (i * 16), w - 12, line, line_color(line)) }",
        "    return y + h",
        "  end",
        "",
        "  def self.visible_battler?(battler)",
        "    return false if !battler",
        "    return false if battler.respond_to?(:fainted?) && battler.fainted?",
        "    return true",
        "  rescue StandardError",
        "    return false",
        "  end",
        "",
        "  def self.battler_name(battler)",
        "    return battler.name.to_s if battler.respond_to?(:name)",
        "    return \"Battler #{battler.index}\"",
        "  rescue StandardError",
        "    return \"Battler\"",
        "  end",
        "",
        "  def self.compact_battler_lines(battler)",
        "    lines = stat_lines(battler).first(3)",
        "    item = custom_item_name(battler)",
        "    lines << \"Custom: #{item}\" if item",
        "    lines.concat(volatile_lines_for_battler(battler).first(2))",
        "    return lines.first(5)",
        "  end",
        "",
        "  def self.detail_stat_lines(battle)",
        "    out = []",
        "    battle.battlers.each do |battler|",
        "      next if !visible_battler?(battler)",
        "      stats = stat_lines(battler)",
        "      next if stats.empty?",
        "      out << battler_name(battler)",
        "      stats.each { |line| out << \"  #{line}\" }",
        "    end",
        "    return out",
        "  end",
        "",
        "  def self.stat_lines(battler)",
        "    out = []",
        "    return out if !battler.respond_to?(:stages)",
        "    STAT_LABELS.each do |stat, label|",
        "      stage = battler.stages[stat] rescue 0",
        "      stage = stage.to_i",
        "      next if stage == 0",
        "      out << \"#{label} #{signed(stage)} = x#{stage_multiplier_text(stage)}\"",
        "    end",
        "    return out",
        "  end",
        "",
        "  def self.signed(value)",
        "    return \"+#{value}\" if value.to_i > 0",
        "    return value.to_s",
        "  end",
        "",
        "  def self.stage_multiplier_text(stage)",
        "    value = stage.to_i",
        "    mult = value >= 0 ? ((2.0 + value) / 2.0) : (2.0 / (2.0 - value))",
        "    return sprintf(\"%.2f\", mult)",
        "  end",
        "",
        "  def self.field_lines(battle)",
        "    out = []",
        "    field = battle.field rescue nil",
        "    return out if !field",
        "    weather = field.weather rescue nil",
        "    if weather && weather != :None",
        "      dur = field.weatherDuration rescue nil",
        "      out << duration_line(\"Weather\", weather, dur)",
        "      out.concat(weather_notes(weather))",
        "    end",
        "    terrain = field.terrain rescue nil",
        "    if terrain && terrain != :None",
        "      dur = field.terrainDuration rescue nil",
        "      out << duration_line(\"Terrain\", terrain, dur)",
        "      out.concat(terrain_notes(terrain))",
        "    end",
        "    room_effects(out, field)",
        "    return out",
        "  end",
        "",
        "  def self.duration_line(label, id, duration)",
        "    turns = duration.to_i",
        "    suffix = turns > 0 ? \" #{turns}t\" : \"\"",
        "    return \"#{label}: #{id}#{suffix}\"",
        "  end",
        "",
        "  def self.weather_notes(weather)",
        "    case weather",
        "    when :Rain, :HeavyRain",
        "      return [\"Water dmg x1.5\", \"Fire dmg x0.5\", \"Thunder/Hurricane always hit\"]",
        "    when :Sun, :HarshSun",
        "      return [\"Fire dmg x1.5\", \"Water dmg x0.5\", \"No freeze\"]",
        "    when :Sandstorm",
        "      return [\"Rock SpD x1.5\", \"End-turn chip\"]",
        "    when :Hail",
        "      return [\"Ice defense boost if game supports\", \"End-turn chip\"]",
        "    when :StrongWinds",
        "      return [\"Flying weaknesses reduced\"]",
        "    end",
        "    return []",
        "  end",
        "",
        "  def self.terrain_notes(terrain)",
        "    case terrain",
        "    when :Electric",
        "      return [\"Electric grounded dmg x1.3\", \"Grounded sleep blocked\"]",
        "    when :Grassy",
        "      return [\"Grass grounded dmg x1.3\", \"Grounded heal each turn\", \"Earthquake-style dmg x0.5\"]",
        "    when :Misty",
        "      return [\"Grounded status blocked\", \"Dragon dmg x0.5\"]",
        "    when :Psychic",
        "      return [\"Psychic grounded dmg x1.3\", \"Priority blocked vs grounded\"]",
        "    end",
        "    return []",
        "  end",
        "",
        "  def self.room_effects(out, field)",
        "    add_field_effect(out, field, :TrickRoom, \"Trick Room\", \"Speed order reversed\")",
        "    add_field_effect(out, field, :Gravity, \"Gravity\", \"Accuracy up / grounded\")",
        "    add_field_effect(out, field, :MagicRoom, \"Magic Room\", \"Held items suppressed\")",
        "    add_field_effect(out, field, :WonderRoom, \"Wonder Room\", \"Def/SpD swapped\")",
        "  end",
        "",
        "  def self.add_field_effect(out, field, const_name, label, note)",
        "    return if !defined?(PBEffects) || !PBEffects.const_defined?(const_name)",
        "    idx = PBEffects.const_get(const_name)",
        "    value = field.effects[idx] rescue 0",
        "    return if !effect_active?(value)",
        "    out << \"#{label}: #{value}\"",
        "    out << \"  #{note}\"",
        "  rescue StandardError",
        "  end",
        "",
        "  def self.side_lines(battle)",
        "    out = []",
        "    sides = battle.sides rescue []",
        "    sides.each_with_index do |side, idx|",
        "      lines = []",
        "      SIDE_EFFECTS.each do |const_name, label, note|",
        "        value = side_effect_value(side, const_name)",
        "        next if !effect_active?(value)",
        "        lines << \"#{label}: #{value}\"",
        "        lines << \"  #{note}\" if note && note.length > 0",
        "      end",
        "      next if lines.empty?",
        "      out << (idx == 0 ? \"Player side\" : \"Foe side\")",
        "      out.concat(lines.map { |line| \"  #{line}\" })",
        "    end",
        "    return out",
        "  end",
        "",
        "  def self.side_effect_value(side, const_name)",
        "    return 0 if !side || !defined?(PBEffects) || !PBEffects.const_defined?(const_name)",
        "    idx = PBEffects.const_get(const_name)",
        "    return side.effects[idx] rescue 0",
        "  rescue StandardError",
        "    return 0",
        "  end",
        "",
        "  def self.detail_volatile_lines(battle)",
        "    out = []",
        "    battle.battlers.each do |battler|",
        "      next if !visible_battler?(battler)",
        "      lines = volatile_lines_for_battler(battler)",
        "      next if lines.empty?",
        "      out << battler_name(battler)",
        "      out.concat(lines.map { |line| \"  #{line}\" })",
        "    end",
        "    return out",
        "  end",
        "",
        "  def self.volatile_lines_for_battler(battler)",
        "    out = []",
        "    BATTLER_EFFECTS.each do |const_name, label|",
        "      value = battler_effect_value(battler, const_name)",
        "      next if !effect_active?(value)",
        "      out << \"#{label}: #{value}\"",
        "    end",
        "    return out",
        "  end",
        "",
        "  def self.battler_effect_value(battler, const_name)",
        "    return 0 if !battler || !defined?(PBEffects) || !PBEffects.const_defined?(const_name)",
        "    idx = PBEffects.const_get(const_name)",
        "    return battler.effects[idx] rescue 0",
        "  rescue StandardError",
        "    return 0",
        "  end",
        "",
        "  def self.effect_active?(value)",
        "    return false if value.nil?",
        "    return value if value == true || value == false",
        "    return value.to_i > 0 if value.respond_to?(:to_i)",
        "    return !!value",
        "  rescue StandardError",
        "    return false",
        "  end",
        "",
        "  def self.custom_item_lines(battle)",
        "    out = []",
        "    battle.battlers.each do |battler|",
        "      next if !visible_battler?(battler)",
        "      item = custom_item_name(battler)",
        "      next if !item",
        "      out << \"#{battler_name(battler)}: #{item}\"",
        "      out.concat(custom_item_effect_lines(battler).map { |line| \"  #{line}\" })",
        "    end",
        "    return out",
        "  end",
        "",
        "  def self.custom_item_name(battler)",
        "    if defined?(CustomItemPatch) && CustomItemPatch.respond_to?(:runtime_item_name_for_battler)",
        "      name = CustomItemPatch.runtime_item_name_for_battler(battler)",
        "      return name.to_s if name && name.to_s.length > 0",
        "    end",
        "    return nil",
        "  rescue StandardError",
        "    return nil",
        "  end",
        "",
        "  def self.custom_item_effect_lines(battler)",
        "    lines = []",
        "    return lines if !defined?(CustomItemPatch) || !CustomItemPatch.respond_to?(:runtime_item_entry_for_battler)",
        "    entry = CustomItemPatch.runtime_item_entry_for_battler(battler)",
        "    pool = entry && (entry[:pool_effects] || entry[\"pool_effects\"])",
        "    if pool.is_a?(Array)",
        "      pool.first(4).each do |eff|",
        "        next if !eff.is_a?(Hash)",
        "        label = eff[:label] || eff[\"label\"] || eff[:id] || eff[\"id\"]",
        "        lines << label.to_s if label",
        "      end",
        "    end",
        "    abilities = entry && (entry[:ability_bridge_ids] || entry[\"ability_bridge_ids\"])",
        "    lines << \"Ability bridge: #{abilities.join(', ')}\" if abilities.is_a?(Array) && !abilities.empty?",
        "    return lines.first(6)",
        "  rescue StandardError",
        "    return []",
        "  end",
        "",
        "  def self.line_color(line)",
        "    text = line.to_s",
        "    return Color.new(120, 235, 150) if text.include?(\"+\") || text.include?(\"x1.\") || text.include?(\"x2\")",
        "    return Color.new(255, 145, 145) if text.include?(\"-\") || text.include?(\"x0.\")",
        "    return Color.new(220, 230, 255)",
        "  end",
        "end",
        "",
        "class Battle::Scene",
        "  unless method_defined?(:custom_battle_overlay_pbFrameUpdate)",
        "    alias custom_battle_overlay_pbFrameUpdate pbFrameUpdate",
        "  end",
        "",
        "  def pbFrameUpdate(cw = nil)",
        "    custom_battle_overlay_pbFrameUpdate(cw)",
        "    CustomBattleOverlay.update_for_scene(self) if defined?(CustomBattleOverlay)",
        "  end",
        "",
        "  unless method_defined?(:custom_battle_overlay_pbEndBattle)",
        "    alias custom_battle_overlay_pbEndBattle pbEndBattle",
        "  end",
        "",
        "  def pbEndBattle(result)",
        "    CustomBattleOverlay.dispose_for_scene(self) if defined?(CustomBattleOverlay)",
        "    custom_battle_overlay_pbEndBattle(result)",
        "  end",
        "end",
        "",
    ]
    return "\n".join(lines)


def inspect_overlay_status(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    adapter = _discover_adapter(root)
    status: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "overlay_version": OVERLAY_VERSION,
        "game_root": str(root),
        "adapter": adapter.get("adapter"),
        "source_type": adapter.get("source_type"),
        "can_apply": bool(adapter.get("can_apply")),
        "target_path": adapter.get("target_path", ""),
        "reason": adapter.get("reason", ""),
        "active": False,
        "installed_version": None,
        "entry_name": SCRIPT_ENTRY_NAME,
        "manifest_path": str(_manifest_path(root)),
    }
    if adapter.get("source_type") == "rxdata" and adapter.get("scripts_obj") is not None:
        scripts_obj = adapter["scripts_obj"]
        idx, entry = _find_script_entry(scripts_obj)
        status["entry_index"] = idx
        if entry is not None:
            source = _decode_entry_source(entry)
            status["active"] = True
            status["source_matches"] = _normalize_source(source) == _normalize_source(_build_overlay_source())
            status["installed_version"] = OVERLAY_VERSION if "OVERLAY_VERSION = 1" in source else "unknown"
        else:
            status["source_matches"] = False
    elif adapter.get("source_type") == "rb_file":
        status["rb_file_count"] = int(adapter.get("rb_file_count", 0))
    state = _load_manifest(root)
    if state:
        status["last_transaction"] = state.get("last_transaction", {})
    return status


def _upsert_rxdata_overlay(root: Path, scripts_obj: list[Any], source: str) -> None:
    patch_blob = ev_patcher._encode_script_source(source, "utf-8")
    target_index, current_entry = _find_script_entry(scripts_obj)
    patch_id: Any = None
    extras: list[Any] = []
    if target_index >= 0 and current_entry is not None:
        removed = scripts_obj.pop(target_index)
        patch_id = removed[0] if removed else None
        extras = list(removed[3:]) if len(removed) > 3 else []
    if patch_id is None:
        patch_id = _next_script_id(scripts_obj)
    patch_entry = [patch_id, SCRIPT_ENTRY_NAME, patch_blob]
    patch_entry.extend(extras)
    main_index = _find_main_script_index(scripts_obj)
    if main_index >= 0:
        scripts_obj.insert(main_index, patch_entry)
    else:
        scripts_obj.append(patch_entry)
    ev_patcher._write_scripts_object(_scripts_path(root), scripts_obj)


def apply_battle_overlay(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    adapter = _discover_adapter(root)
    if not adapter.get("can_apply"):
        raise ValueError(str(adapter.get("reason") or "No supported battle overlay adapter found."))
    if adapter.get("source_type") != "rxdata":
        raise ValueError("Only Scripts.rxdata battle overlay installation is enabled in this build.")
    scripts_obj = adapter["scripts_obj"]
    source = _build_overlay_source()
    idx, current_entry = _find_script_entry(scripts_obj)
    if current_entry is not None:
        current_source = _decode_entry_source(current_entry)
        if _normalize_source(current_source) == _normalize_source(source):
            status = inspect_overlay_status(root)
            status.update({"changed": False, "status": "already_current", "patched_files": []})
            return status
    stamp = _now_stamp()
    scripts_file = _scripts_path(root)
    backup = _copy_to_backup(root, scripts_file, kind="pre-battle-overlay", stamp=stamp)
    _upsert_rxdata_overlay(root, scripts_obj, source)
    transaction = {
        "stamp": stamp,
        "kind": "apply",
        "active": True,
        "overlay_version": OVERLAY_VERSION,
        "adapter": "scripts_rxdata",
        "path": str(scripts_file),
        "backup_path": str(backup),
        "updated_at_utc": _now_utc_iso(),
    }
    _write_manifest(
        root,
        {
            "version": MANIFEST_VERSION,
            "active": True,
            "overlay_version": OVERLAY_VERSION,
            "last_transaction": transaction,
        },
    )
    status = inspect_overlay_status(root)
    status.update({"changed": True, "status": "applied", "patched_files": [transaction]})
    return status


def remove_battle_overlay(game_root: Path | str) -> dict[str, Any]:
    root = _resolve_game_root(game_root)
    adapter = _discover_adapter(root)
    if adapter.get("source_type") != "rxdata" or adapter.get("scripts_obj") is None:
        raise ValueError(str(adapter.get("reason") or "Only Scripts.rxdata removal is enabled in this build."))
    scripts_obj = adapter["scripts_obj"]
    idx, _entry = _find_script_entry(scripts_obj)
    if idx < 0:
        status = inspect_overlay_status(root)
        status.update({"changed": False, "status": "not_installed", "patched_files": []})
        return status
    stamp = _now_stamp()
    scripts_file = _scripts_path(root)
    backup = _copy_to_backup(root, scripts_file, kind="pre-battle-overlay-remove", stamp=stamp)
    scripts_obj.pop(idx)
    ev_patcher._write_scripts_object(scripts_file, scripts_obj)
    transaction = {
        "stamp": stamp,
        "kind": "remove",
        "active": False,
        "overlay_version": OVERLAY_VERSION,
        "adapter": "scripts_rxdata",
        "path": str(scripts_file),
        "backup_path": str(backup),
        "updated_at_utc": _now_utc_iso(),
    }
    _write_manifest(
        root,
        {
            "version": MANIFEST_VERSION,
            "active": False,
            "overlay_version": OVERLAY_VERSION,
            "last_transaction": transaction,
        },
    )
    status = inspect_overlay_status(root)
    status.update({"changed": True, "status": "removed", "patched_files": [transaction]})
    return status


def format_status_report(status: dict[str, Any]) -> str:
    lines = [
        "Battle Overlay Status",
        "",
        f"Game root: {status.get('game_root', '')}",
        f"Adapter: {status.get('adapter', '')}",
        f"Target: {status.get('target_path', '')}",
        f"Can apply: {'Yes' if status.get('can_apply') else 'No'}",
        f"Active: {'Yes' if status.get('active') else 'No'}",
        f"Installed version: {status.get('installed_version') or 'none'}",
        f"Source current: {'Yes' if status.get('source_matches') else 'No'}",
    ]
    reason = str(status.get("reason", "") or "").strip()
    if reason:
        lines.extend(["", f"Note: {reason}"])
    tx = status.get("last_transaction")
    if isinstance(tx, dict) and tx:
        lines.extend(
            [
                "",
                "Last transaction:",
                f"- kind: {tx.get('kind', '')}",
                f"- stamp: {tx.get('stamp', '')}",
                f"- backup: {tx.get('backup_path', '')}",
            ]
        )
    return "\n".join(lines)

