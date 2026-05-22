#!/usr/bin/env python
"""Hook-based Ruby compiler for the Custom Item Effect Engine (Phase 1 + Phase 2).

Converts normalized effect definitions from custom_effect_pool.json into Ruby
code blocks that are appended to ZZ_CustomItemPatch. Every generated block:
  - Is wrapped in begin/rescue StandardError to avoid hard crashes.
  - Guards every activation path with CustomItemPatch.custom_item_effect_item_active?
  - Preserves the original method return value where a method is wrapped.
  - Falls back silently when optional engine APIs (DamageCalcFromUser,
    SpeedCalc, WeatherExtender, TerrainStatBoost, etc.) are not present.

Note: sheer_force_modifier is NOT compiled here; it is routed through the
existing ability_active_bridge accumulation in patcher.py so that all
hasActiveAbility? overrides stay in a single alias chain.
"""

from __future__ import annotations

from typing import Any

SUPPORTED_HOOKS = [
    # Phase 1
    "end_of_round",
    "damage_calc",
    "after_damage_dealt",
    "after_move_use",
    "speed_calc",
    "on_switch_in",
    # Phase 2
    "damage_calc_from_target",
    "on_being_hit",
    "hp_heal",
    "status_cure",
    "end_of_round_effect",
    "crit_calc",
    "accuracy_calc",
    "evasion_calc",
    "weight_calc",
    "stat_loss_immunity",
    "on_being_intimidated",
    "terrain_stat_boost",
    "weather_extend",
    "stat_restore_after_move",
]

_RUBY_STAT_MAP = {
    "ATTACK": ":ATTACK",
    "DEFENSE": ":DEFENSE",
    "SPEED": ":SPEED",
    "SPECIAL_ATTACK": ":SPECIAL_ATTACK",
    "SPECIAL_DEFENSE": ":SPECIAL_DEFENSE",
    "ACCURACY": ":ACCURACY",
    "EVASION": ":EVASION",
}

_RUBY_WEATHER_MAP = {
    "Sun": ":Sun",
    "HarshSun": ":HarshSun",
    "Rain": ":Rain",
    "HeavyRain": ":HeavyRain",
    "Sandstorm": ":Sandstorm",
    "Hail": ":Hail",
    "Snow": ":Snow",
    "Fog": ":Fog",
    "ShadowSky": ":ShadowSky",
}

_RUBY_TERRAIN_MAP = {
    "Electric": ":Electric",
    "Grassy": ":Grassy",
    "Misty": ":Misty",
    "Psychic": ":Psychic",
}

_RUBY_TYPE_MAP = {
    "NORMAL": ":NORMAL",
    "FIRE": ":FIRE",
    "WATER": ":WATER",
    "GRASS": ":GRASS",
    "ELECTRIC": ":ELECTRIC",
    "ICE": ":ICE",
    "FIGHTING": ":FIGHTING",
    "POISON": ":POISON",
    "GROUND": ":GROUND",
    "FLYING": ":FLYING",
    "PSYCHIC": ":PSYCHIC",
    "BUG": ":BUG",
    "ROCK": ":ROCK",
    "GHOST": ":GHOST",
    "DRAGON": ":DRAGON",
    "DARK": ":DARK",
    "STEEL": ":STEEL",
    "FAIRY": ":FAIRY",
}

_RUBY_STATUS_MAP = {
    "BURN": ":BURN",
    "POISON": ":POISON",
    "TOXIC": ":POISON",  # Toxic uses :POISON status with toxic flag
    "PARALYSIS": ":PARALYSIS",
    "SLEEP": ":SLEEP",
    "FROZEN": ":FROZEN",
    "FROSTBITE": ":FROSTBITE",
}


def _safe_effect_id(effect_id: str) -> str:
    """Convert an effect ID to a safe Ruby local variable/instance var suffix."""
    return effect_id.lower().replace("-", "_").replace(" ", "_")


def _fmt_float(value: float) -> str:
    """Format a float trimming trailing zeros for Ruby literal output."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _ruby_stat(stat_key: str) -> str:
    return _RUBY_STAT_MAP.get(str(stat_key).upper().replace(" ", "_"), f":{stat_key}")


def _ruby_type(type_key: str) -> str:
    return _RUBY_TYPE_MAP.get(str(type_key).upper().replace(" ", "_"), f":{type_key}")


def _ruby_weather_list(raw: Any) -> list[str]:
    out: list[str] = []
    if isinstance(raw, list):
        for w in raw:
            out.append(_RUBY_WEATHER_MAP.get(str(w), f":{w}"))
    elif isinstance(raw, str):
        out.append(_RUBY_WEATHER_MAP.get(raw, f":{raw}"))
    return out

def _ruby_status_list(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else ([raw] if raw else [])
    out: list[str] = []
    for value in values:
        sym = _RUBY_STATUS_MAP.get(str(value).upper())
        if sym and sym not in out:
            out.append(sym)
    return out


# ---------------------------------------------------------------------------
# Phase 1 generators (kept from original file)
# ---------------------------------------------------------------------------

def _gen_heal_fraction_max_hp(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round / heal_fraction_max_hp."""
    num = max(1, int(params.get("fraction_numerator", 1)))
    den = max(1, int(params.get("fraction_denominator", 16)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::EndOfRoundHealing.add(:{item_id},",
        "    proc { |item, battler, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "      next unless battler.canHeal?",
        f"      hp = [(battler.totalhp.to_f * {num} / {den}).ceil, 1].max",
        "      battler.pbRecoverHP(hp)",
        f'      battle.pbDisplay(_INTL("{{1}}\'s {{2}} restored its HP!", battler.pbThis, battler.itemName))',
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_damage_multiplier(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """damage_calc / damage_multiplier — unconditional damage boost (Life Orb)."""
    mult_text = _fmt_float(float(params.get("multiplier", 1.3)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::DamageCalcFromUser)",
        f"    Battle::ItemEffects::DamageCalcFromUser.add(:{item_id},",
        "      proc { |item, user, target, move, mults, basePow, type|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(user)",
        "        next if move.statusMove? rescue next",
        f"        mults[:final_dmg_mult] = (mults[:final_dmg_mult].to_f * {mult_text}).round(4) if mults.respond_to?(:[]=)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_heal_percent_damage_dealt(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """after_damage_dealt / heal_percent_damage_dealt."""
    percent = max(1, min(100, int(params.get("percent", 75))))
    ratio_text = _fmt_float(percent / 100.0)
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::AfterMoveUseFromUser.add(:{item_id},",
        "    proc { |item, user, targets, move, numHits, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(user)",
        "      next unless user.canHeal?",
        "      targets.each do |target|",
        "        next if !target || !target.damageState",
        "        hp_lost = target.damageState.totalHPLost",
        "        next if hp_lost <= 0",
        f"        hp_gain = (hp_lost * {ratio_text}).round",
        "        next if hp_gain <= 0",
        '        user.pbRecoverHPFromDrain(hp_gain, target, _INTL("{1} regained HP with {2}!", user.pbThis, user.itemName))',
        "      end",
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_raise_user_stat_stage(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """after_move_use / raise_user_stat_stage."""
    stats_raw = params.get("stats")
    if isinstance(stats_raw, str):
        stats_raw = [stats_raw]
    if not isinstance(stats_raw, list) or not stats_raw:
        stats_raw = [params.get("stat", "ATTACK")]
    stat_symbols = ", ".join(_ruby_stat(str(stat).upper().replace(" ", "_")) for stat in stats_raw)
    stages = max(1, int(params.get("stages", 1)))
    direction = str(params.get("direction", "raise") or "raise").strip().lower()
    is_lower = direction == "lower"
    once_per_battle = bool(params.get("once_per_battle", True))
    per_hit = bool(params.get("per_hit", False))
    tracker_suffix = _safe_effect_id(effect_id)
    tracker_var = f":@custom_item_pool_once_{tracker_suffix}"
    lines = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::AfterMoveUseFromUser.add(:{item_id},",
        "    proc { |item, user, targets, move, numHits, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(user)",
    ]
    if once_per_battle:
        lines += [
            f"      tracker = {tracker_var}",
            "      next if user.instance_variable_defined?(tracker) && user.instance_variable_get(tracker)",
        ]
    lines += [f"      stats = [{stat_symbols}]", "      any_raised = false"]
    if per_hit:
        # Run the stat-change logic once per hit (numHits may be nil)
        lines += [
            "      hits = (numHits || 1)",
            "      hits.times do",
            "        stats.each do |stat|",
            (
                "          next unless user.pbCanLowerStatStage?(stat, user)"
                if is_lower
                else
                "          next unless user.pbCanRaiseStatStage?(stat, user)"
            ),
            (
                f"          user.pbLowerStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbLowerStatStage(stat, {stages}, user)"
                if is_lower
                else
                f"          user.pbRaiseStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbRaiseStatStage(stat, {stages}, user)"
            ),
            "          any_raised = true",
            "        end",
            "      end",
        ]
    else:
        lines += [
            "      stats.each do |stat|",
            (
                "        next unless user.pbCanLowerStatStage?(stat, user)"
                if is_lower
                else
                "        next unless user.pbCanRaiseStatStage?(stat, user)"
            ),
            (
                f"        user.pbLowerStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbLowerStatStage(stat, {stages}, user)"
                if is_lower
                else
                f"        user.pbRaiseStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbRaiseStatStage(stat, {stages}, user)"
            ),
            "        any_raised = true",
            "      end",
        ]
    if once_per_battle:
        lines += ["      user.instance_variable_set(tracker, true) if any_raised"]
    lines += [
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return lines


def _gen_speed_multiplier_if_weather(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """speed_calc / speed_multiplier_if_weather.

    Indigo's ItemEffects::SpeedCalc uses the item-speed signature:
      proc { |item, battler, mult| next new_mult }
    Older generated code used a damage-mults-style 4-arg proc and silently no-op'd.
    """
    weather_list = _ruby_weather_list(params.get("weather", []))
    if not weather_list:
        return [f"# --- pool effect: {effect_id} for {item_id} (skipped: no weather defined) ---", ""]
    mult_text = _fmt_float(float(params.get("multiplier", 2.0)))
    weather_ruby = "[" + ", ".join(weather_list) + "]"
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::SpeedCalc)",
        f"    Battle::ItemEffects::SpeedCalc.add(:{item_id},",
        "      proc { |item, battler, mult|",
        "        next mult unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "        battle = nil",
        "        begin",
        "          battle = battler.battle if battler.respond_to?(:battle)",
        "        rescue StandardError",
        "          battle = nil",
        "        end",
        "        weather = nil",
        "        begin",
        "          weather = battle.field.weather if battle && battle.respond_to?(:field) && battle.field.respond_to?(:weather)",
        "        rescue StandardError",
        "          weather = nil",
        "        end",
        f"        next mult unless weather && {weather_ruby}.include?(weather)",
        f"        next (mult.to_f * {mult_text}).round(4)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_after_move_use_combined(item_id: str, effects: list[dict[str, Any]]) -> list[str]:
    """Generate one combined AfterMoveUseFromUser handler per item.

    Handler hashes are keyed by item ID, so adding multiple
    AfterMoveUseFromUser handlers for the same item can overwrite previous
    entries. Combining all after-move style move-derived effects keeps one
    deterministic handler for drain, stat raise/drop, status, flinch, recoil,
    weather/terrain, and self-heal templates.
    """
    comments: list[str] = []
    drain_effects: list[tuple[str, float]] = []
    drain_multiplier = 1.0
    stat_raise_effects: list[dict[str, Any]] = []
    stat_drop_effects: list[dict[str, Any]] = []
    status_effects: list[dict[str, Any]] = []
    flinch_effects: list[dict[str, Any]] = []
    heal_self_effects: list[dict[str, Any]] = []
    recoil_effects: list[dict[str, Any]] = []
    weather_effects: list[dict[str, Any]] = []
    terrain_effects: list[dict[str, Any]] = []

    for effect in effects:
        if not isinstance(effect, dict):
            continue
        eid = str(effect.get("id", "UNKNOWN"))
        template = str(effect.get("template", ""))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        comments.append(eid)
        if template == "heal_percent_damage_dealt":
            percent = max(1, min(100, int(params.get("percent", 75))))
            drain_effects.append((eid, percent / 100.0))
        elif template == "drain_heal_multiplier":
            drain_multiplier *= float(params.get("multiplier", 1.0))
        elif template == "raise_user_stat_stage":
            stat_raise_effects.append(effect)
        elif template == "lower_target_stat_stage":
            stat_drop_effects.append(effect)
        elif template == "apply_status_target":
            status_effects.append(effect)
        elif template == "flinch_target":
            flinch_effects.append(effect)
        elif template == "heal_user_fraction":
            heal_self_effects.append(effect)
        elif template == "recoil_percent_damage_dealt":
            recoil_effects.append(effect)
        elif template == "start_weather":
            weather_effects.append(effect)
        elif template == "start_terrain":
            terrain_effects.append(effect)

    lines = [
        f"# --- combined after-move pool effects for {item_id}: {', '.join(comments)} ---",
        "begin",
        f"  Battle::ItemEffects::AfterMoveUseFromUser.add(:{item_id},",
        "    proc { |item, user, targets, move, numHits, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(user)",
        "      targets = [] if !targets",
    ]

    for eid, ratio in drain_effects:
        ratio_text = _fmt_float(ratio * drain_multiplier)
        lines += [
            f"      # pool effect: {eid} (drain multiplier: {_fmt_float(drain_multiplier)})",
            "      if user.canHeal?",
            "        targets.each do |target|",
            "          next if !target || !target.damageState",
            "          hp_lost = target.damageState.totalHPLost",
            "          next if hp_lost <= 0",
            f"          hp_gain = (hp_lost * {ratio_text}).round",
            "          next if hp_gain <= 0",
            '          user.pbRecoverHPFromDrain(hp_gain, target, _INTL("{1} regained HP with {2}!", user.pbThis, user.itemName))',
            "        end",
            "      end",
        ]

    for effect in stat_raise_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        per_hit = bool(params.get("per_hit", False))
        stats_raw = params.get("stats")
        if isinstance(stats_raw, str):
            stats_raw = [stats_raw]
        if not isinstance(stats_raw, list) or not stats_raw:
            stats_raw = [params.get("stat", "ATTACK")]
        stat_symbols = ", ".join(_ruby_stat(str(stat).upper().replace(" ", "_")) for stat in stats_raw)
        stages = max(1, int(params.get("stages", 1)))
        direction = str(params.get("direction", "raise") or "raise").strip().lower()
        is_lower = direction == "lower"
        once_per_battle = bool(params.get("once_per_battle", True))
        tracker_suffix = _safe_effect_id(eid)
        tracker_var = f":@custom_item_pool_once_{tracker_suffix}"
        lines += [f"      # pool effect: {eid}"]
        if once_per_battle:
            lines += [
                f"      tracker_{tracker_suffix} = {tracker_var}",
                f"      unless user.instance_variable_defined?(tracker_{tracker_suffix}) && user.instance_variable_get(tracker_{tracker_suffix})",
                f"        stats_{tracker_suffix} = [{stat_symbols}]",
                f"        any_raised_{tracker_suffix} = false",
            ]
            if per_hit:
                lines += [
                    f"        hits_{tracker_suffix} = (numHits || 1)",
                    f"        hits_{tracker_suffix}.times do",
                    f"          stats_{tracker_suffix}.each do |stat|",
                    (
                        "            next unless user.pbCanLowerStatStage?(stat, user)"
                        if is_lower else
                        "            next unless user.pbCanRaiseStatStage?(stat, user)"
                    ),
                    (
                        f"            user.pbLowerStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbLowerStatStage(stat, {stages}, user)"
                        if is_lower else
                        f"            user.pbRaiseStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbRaiseStatStage(stat, {stages}, user)"
                    ),
                    f"            any_raised_{tracker_suffix} = true",
                    "          end",
                    "        end",
                ]
            else:
                lines += [
                    f"        stats_{tracker_suffix}.each do |stat|",
                    (
                        "          next unless user.pbCanLowerStatStage?(stat, user)"
                        if is_lower else
                        "          next unless user.pbCanRaiseStatStage?(stat, user)"
                    ),
                    (
                        f"          user.pbLowerStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbLowerStatStage(stat, {stages}, user)"
                        if is_lower else
                        f"          user.pbRaiseStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbRaiseStatStage(stat, {stages}, user)"
                    ),
                    f"          any_raised_{tracker_suffix} = true",
                    "        end",
                ]
            lines += [f"        user.instance_variable_set(tracker_{tracker_suffix}, true) if any_raised_{tracker_suffix}", f"      end"]
        else:
            if per_hit:
                lines += [
                    f"      stats_{tracker_suffix} = [{stat_symbols}]",
                    f"      hits_{tracker_suffix} = (numHits || 1)",
                    f"      hits_{tracker_suffix}.times do",
                    f"        stats_{tracker_suffix}.each do |stat|",
                    (
                        "          next unless user.pbCanLowerStatStage?(stat, user)"
                        if is_lower else
                        "          next unless user.pbCanRaiseStatStage?(stat, user)"
                    ),
                    (
                        f"          user.pbLowerStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbLowerStatStage(stat, {stages}, user)"
                        if is_lower else
                        f"          user.pbRaiseStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbRaiseStatStage(stat, {stages}, user)"
                    ),
                    "        end",
                    "      end",
                ]
            else:
                lines += [
                    f"      stats_{tracker_suffix} = [{stat_symbols}]",
                    f"      stats_{tracker_suffix}.each do |stat|",
                    (
                        "        next unless user.pbCanLowerStatStage?(stat, user)"
                        if is_lower else
                        "        next unless user.pbCanRaiseStatStage?(stat, user)"
                    ),
                    (
                        f"        user.pbLowerStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbLowerStatStage(stat, {stages}, user)"
                        if is_lower else
                        f"        user.pbRaiseStatStageByCause(stat, {stages}, user, user.itemName) rescue user.pbRaiseStatStage(stat, {stages}, user)"
                    ),
                    "      end",
                ]

    for effect in stat_drop_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        stat_key = str(params.get("stat", "ATTACK")).upper().replace(" ", "_")
        ruby_stat = _ruby_stat(stat_key)
        stages = max(1, int(params.get("stages", 1)))
        chance = max(1, min(100, int(params.get("chance_percent", 100))))
        lines += [
            f"      # pool effect: {eid}",
            "      targets.each do |target|",
            "        next if !target || target.fainted?",
            f"        next if battle.pbRandom(100) >= {chance}",
            f"        if target.pbCanLowerStatStage?({ruby_stat}, user)",
            f"          target.pbLowerStatStageByCause({ruby_stat}, {stages}, user, user.itemName) rescue target.pbLowerStatStage({ruby_stat}, {stages}, user)",
            "        end",
            "      end",
        ]

    for effect in status_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        status = str(params.get("status", "POISON")).upper()
        chance = max(1, min(100, int(params.get("chance_percent", 100))))
        lines += [
            f"      # pool effect: {eid}",
            "      targets.each do |target|",
            "        next if !target || target.fainted?",
            f"        next if battle.pbRandom(100) >= {chance}",
        ]
        if status == "BURN":
            lines += ["        target.pbBurn(user) if target.pbCanBurn?(user, false)"]
        elif status in {"POISON", "TOXIC"}:
            toxic = "true" if status == "TOXIC" else "false"
            lines += [f"        target.pbPoison(user, nil, {toxic}) if target.pbCanPoison?(user, false)"]
        elif status == "PARALYSIS":
            lines += ["        target.pbParalyze(user) if target.pbCanParalyze?(user, false)"]
        elif status == "SLEEP":
            lines += ["        target.pbSleep if target.pbCanSleep?(user, false)"]
        elif status in {"FROZEN", "FREEZE"}:
            lines += ["        target.pbFreeze if target.respond_to?(:pbFreeze) && target.pbCanFreeze?(user, false)"]
        lines += ["      end"]

    for effect in flinch_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        chance = max(1, min(100, int(params.get("chance_percent", 100))))
        lines += [
            f"      # pool effect: {eid}",
            "      targets.each do |target|",
            "        next if !target || target.fainted?",
            f"        next if battle.pbRandom(100) >= {chance}",
            "        begin",
            "          target.pbFlinch(user)",
            "        rescue StandardError",
            "          target.effects[PBEffects::Flinch] = true if defined?(PBEffects)",
            "        end",
            "      end",
        ]

    for effect in heal_self_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        num = max(1, int(params.get("fraction_numerator", 1)))
        den = max(1, int(params.get("fraction_denominator", 2)))
        lines += [
            f"      # pool effect: {eid}",
            "      if user.canHeal?",
            f"        hp_gain = [(user.totalhp.to_f * {num} / {den}).ceil, 1].max",
            "        user.pbRecoverHP(hp_gain)",
            '        battle.pbDisplay(_INTL("{1} restored HP with {2}!", user.pbThis, user.itemName))',
            "      end",
        ]

    for effect in recoil_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        percent = max(1, min(100, int(params.get("percent", 25))))
        ratio = _fmt_float(percent / 100.0)
        lines += [
            f"      # pool effect: {eid}",
            "      total_lost = 0",
            "      targets.each do |target|",
            "        next if !target || !target.damageState",
            "        total_lost += target.damageState.totalHPLost.to_i",
            "      end",
            "      if total_lost > 0 && user.takesIndirectDamage?",
            f"        recoil = [(total_lost * {ratio}).round, 1].max",
            "        user.pbReduceHP(recoil, false) rescue user.pbTakeDamage(recoil, false, true, false)",
            '        battle.pbDisplay(_INTL("{1} was hurt by recoil from {2}!", user.pbThis, user.itemName))',
            "      end",
        ]

    for effect in weather_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        weather = _RUBY_WEATHER_MAP.get(str(params.get("weather", "Sun")), f":{params.get('weather', 'Sun')}")
        duration = max(1, int(params.get("duration", 5)))
        lines += [
            f"      # pool effect: {eid}",
            "      begin",
            f"        battle.pbStartWeather(user, {weather}, true) if battle.respond_to?(:pbStartWeather)",
            "      rescue StandardError",
            f"        battle.field.weather = {weather} if battle.respond_to?(:field) && battle.field.respond_to?(:weather=)",
            f"        battle.field.weatherDuration = {duration} if battle.respond_to?(:field) && battle.field.respond_to?(:weatherDuration=)",
            "      end",
        ]

    for effect in terrain_effects:
        eid = str(effect.get("id", "UNKNOWN"))
        params = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
        terrain = _RUBY_TERRAIN_MAP.get(str(params.get("terrain", "Electric")), f":{params.get('terrain', 'Electric')}")
        duration = max(1, int(params.get("duration", 5)))
        lines += [
            f"      # pool effect: {eid}",
            "      begin",
            f"        battle.field.terrain = {terrain}",
            f"        battle.field.terrainDuration = {duration}",
            "      rescue StandardError",
            "      end",
        ]

    lines += [
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [combined_after_move_use {item_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return lines

def _gen_raise_user_stat_stage_end_of_round(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round_effect / raise_user_stat_stage_end_of_round (Speed Boost style)."""
    stats_raw = params.get("stats")
    if isinstance(stats_raw, str):
        stats_raw = [stats_raw]
    if not isinstance(stats_raw, list) or not stats_raw:
        stats_raw = [params.get("stat", "SPEED")]
    stat_symbols = ", ".join(_ruby_stat(str(stat).upper().replace(" ", "_")) for stat in stats_raw)
    stages = max(1, int(params.get("stages", 1)))
    direction = str(params.get("direction", "raise") or "raise").strip().lower()
    is_lower = direction == "lower"
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::EndOfRoundEffect)",
        f"    Battle::ItemEffects::EndOfRoundEffect.add(:{item_id},",
        "      proc { |item, battler, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        stats = [{stat_symbols}]",
        "        stats.each do |stat|",
        (
            "          next unless battler.pbCanLowerStatStage?(stat, battler)"
            if is_lower else
            "          next unless battler.pbCanRaiseStatStage?(stat, battler)"
        ),
        (
            f"          battler.pbLowerStatStageByCause(stat, {stages}, battler, battler.itemName) rescue battler.pbLowerStatStage(stat, {stages}, battler)"
            if is_lower else
            f"          battler.pbRaiseStatStageByCause(stat, {stages}, battler, battler.itemName) rescue battler.pbRaiseStatStage(stat, {stages}, battler)"
        ),
        "        end",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


# ---------------------------------------------------------------------------
# Phase 2 generators
# ---------------------------------------------------------------------------

def _gen_damage_multiplier_conditional(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """damage_calc / damage_multiplier_conditional — physical/special/type/SE conditions."""
    mult_text = _fmt_float(float(params.get("multiplier", 1.2)))
    require_physical = bool(params.get("require_physical", False))
    require_special = bool(params.get("require_special", False))
    require_move_type = params.get("require_move_type")
    require_se = bool(params.get("require_super_effective", False))
    require_user_has_type = bool(params.get("require_user_has_type", False))
    max_base_power = params.get("max_base_power")
    require_user_status = params.get("require_user_status")
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::DamageCalcFromUser)",
        f"    Battle::ItemEffects::DamageCalcFromUser.add(:{item_id},",
        "      proc { |item, user, target, move, mults, basePow, type|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(user)",
        "        next if move.statusMove? rescue next",
    ]
    if require_physical:
        body.append("        next unless move.physicalMove? rescue next")
    if require_special:
        body.append("        next unless move.specialMove? rescue next")
    if require_move_type:
        body.append(f"        next unless type == {_ruby_type(str(require_move_type))}")
    if require_user_has_type:
        body.append("        next unless user.pbHasType?(type) rescue next")
    if max_base_power is not None:
        body += [
            "        begin",
            f"          next if (basePow || 0).to_i > {int(float(max_base_power))}",
            "        rescue StandardError",
            "          next",
            "        end",
        ]
    if require_user_status:
        statuses = _ruby_status_list(require_user_status)
        status_ruby = "[" + ", ".join(statuses) + "]" if statuses else "[]"
        body.append(f"        next unless {status_ruby}.include?(user.status) rescue next")
    if require_se:
        body += [
            "        begin",
            "          tm = move.pbCalcTypeMod(type, user, target)",
            "          if defined?(Effectiveness)",
            "            next if tm <= Effectiveness::NORMAL_EFFECTIVE",
            "          else",
            "            next if tm <= 8",
            "          end",
            "        rescue StandardError",
            "          next",
            "        end",
        ]
    body += [
        f"        mults[:final_dmg_mult] = (mults[:final_dmg_mult].to_f * {mult_text}).round(4) if mults.respond_to?(:[]=)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_damage_reduction_multiplier(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """damage_calc_from_target / damage_reduction_multiplier."""
    mult_text = _fmt_float(float(params.get("multiplier", 0.6667)))
    require_physical = bool(params.get("require_physical", False))
    require_special = bool(params.get("require_special", False))
    require_move_type = params.get("require_move_type")
    require_se = bool(params.get("require_super_effective", False))
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::DamageCalcFromTarget)",
        f"    Battle::ItemEffects::DamageCalcFromTarget.add(:{item_id},",
        "      proc { |item, user, target, move, mults, basePow, type|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(target)",
        "        next if move.statusMove? rescue next",
    ]
    if require_physical:
        body.append("        next unless move.physicalMove? rescue next")
    if require_special:
        body.append("        next unless move.specialMove? rescue next")
    if require_move_type:
        body.append(f"        next unless type == {_ruby_type(str(require_move_type))}")
    if require_se:
        body += [
            "        begin",
            "          tm = move.pbCalcTypeMod(type, user, target)",
            "          if defined?(Effectiveness)",
            "            next if tm <= Effectiveness::NORMAL_EFFECTIVE",
            "          else",
            "            next if tm <= 8",
            "          end",
            "        rescue StandardError",
            "          next",
            "        end",
        ]
    body += [
        "        if mults.respond_to?(:[]=) && mults.respond_to?(:[])",
        "          if mults[:defense_multiplier]",
        f"            mults[:defense_multiplier] = (mults[:defense_multiplier].to_f / {mult_text}).round(4)",
        "          elsif mults[:final_dmg_mult]",
        f"            mults[:final_dmg_mult] = (mults[:final_dmg_mult].to_f * {mult_text}).round(4)",
        "          end",
        "        end",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_contact_recoil_damage(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """on_being_hit / contact_recoil_damage."""
    num = max(1, int(params.get("fraction_numerator", 1)))
    den = max(2, int(params.get("fraction_denominator", 6)))
    require_contact = bool(params.get("require_contact", True))
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::OnBeingHit)",
        f"    Battle::ItemEffects::OnBeingHit.add(:{item_id},",
        "      proc { |item, user, target, move, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(target)",
        "        next if !user || user == target",
        "        next if user.fainted?",
    ]
    if require_contact:
        body += [
            "        is_contact = false",
            "        begin",
            "          is_contact = move.physicalMove? && (move.respond_to?(:contactMove?) ? move.contactMove? : true)",
            "        rescue StandardError",
            "          is_contact = false",
            "        end",
            "        next unless is_contact",
        ]
    body += [
        "        next if !user.takesIndirectDamage? rescue next",
        f"        dmg = [(user.totalhp.to_f * {num} / {den}).ceil, 1].max",
        "        begin",
        "          user.pbReduceHP(dmg, false)",
        "        rescue StandardError",
        "          user.pbTakeDamage(dmg, false, true, false) if user.respond_to?(:pbTakeDamage)",
        "        end",
        '        battle.pbDisplay(_INTL("{1} was hurt by the {2}!", user.pbThis, target.itemName))',
        "        user.pbItemHPHealCheck rescue nil",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_inflict_status_on_contact(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """on_being_hit / inflict_status_on_contact."""
    status = str(params.get("status", "POISON")).upper()
    chance = max(1, min(100, int(params.get("chance_percent", 30))))
    require_contact = bool(params.get("require_contact", True))
    inflict_block = []
    if status == "BURN":
        inflict_block = [
            "        if user.pbCanBurn?(target, false)",
            "          user.pbBurn(target)",
            "        end",
        ]
    elif status == "TOXIC":
        inflict_block = [
            "        if user.pbCanPoison?(target, false)",
            "          user.pbPoison(target, nil, true)",
            "        end",
        ]
    elif status == "POISON":
        inflict_block = [
            "        if user.pbCanPoison?(target, false)",
            "          user.pbPoison(target)",
            "        end",
        ]
    elif status == "PARALYSIS":
        inflict_block = [
            "        if user.pbCanParalyze?(target, false)",
            "          user.pbParalyze(target)",
            "        end",
        ]
    elif status == "SLEEP":
        inflict_block = [
            "        if user.pbCanSleep?(target, false)",
            "          user.pbSleep",
            "        end",
        ]
    else:
        inflict_block = [f"        # Unknown status {status}, skipped"]

    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::OnBeingHit)",
        f"    Battle::ItemEffects::OnBeingHit.add(:{item_id},",
        "      proc { |item, user, target, move, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(target)",
        "        next if !user || user == target || user.fainted?",
    ]
    if require_contact:
        body += [
            "        is_contact = false",
            "        begin",
            "          is_contact = move.physicalMove? && (move.respond_to?(:contactMove?) ? move.contactMove? : true)",
            "        rescue StandardError",
            "          is_contact = false",
            "        end",
            "        next unless is_contact",
        ]
    body += [
        f"        next if battle.pbRandom(100) >= {chance}",
    ]
    body.extend(inflict_block)
    body += [
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_stat_raise_on_hit(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """on_being_hit / stat_raise_on_hit (Weakness Policy, Absorb Bulb, etc.)."""
    stats_raw = params.get("stats")
    if isinstance(stats_raw, str):
        stats_raw = [stats_raw]
    if not isinstance(stats_raw, list) or not stats_raw:
        single = params.get("stat", "ATTACK")
        stats_raw = [single]
    stages = max(1, int(params.get("stages", 1)))
    require_se = bool(params.get("require_super_effective", False))
    require_move_type = params.get("require_move_type")
    tracker_suffix = _safe_effect_id(effect_id)
    tracker_var = f":@custom_item_pool_once_{tracker_suffix}"
    once_per_battle = bool(params.get("once_per_battle", True))
    stat_symbols = ", ".join(_ruby_stat(s) for s in stats_raw)

    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::OnBeingHit)",
        f"    Battle::ItemEffects::OnBeingHit.add(:{item_id},",
        "      proc { |item, user, target, move, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(target)",
    ]
    if once_per_battle:
        body += [
            f"        tracker = {tracker_var}",
            "        next if target.instance_variable_defined?(tracker) && target.instance_variable_get(tracker)",
        ]
    if require_move_type:
        body.append(f"        next unless move.calcType == {_ruby_type(str(require_move_type))}")
    if require_se:
        body += [
            "        begin",
            "          tm = move.pbCalcTypeMod(move.calcType, user, target)",
            "          if defined?(Effectiveness)",
            "            next if tm <= Effectiveness::NORMAL_EFFECTIVE",
            "          else",
            "            next if tm <= 8",
            "          end",
            "        rescue StandardError",
            "          next",
            "        end",
        ]
    body += [
        f"        stats = [{stat_symbols}]",
        "        any_raised = false",
        "        stats.each do |s|",
        "          if target.pbCanRaiseStatStage?(s, target)",
        f"            target.pbRaiseStatStageByCause(s, {stages}, target, target.itemName)",
        "            any_raised = true",
        "          end",
        "        end",
    ]
    if once_per_battle:
        body += [
            f"        target.instance_variable_set(tracker, true) if any_raised",
        ]
    body += [
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_heal_at_hp_threshold(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """hp_heal / heal_at_hp_threshold (Sitrus, Oran)."""
    th_num = max(1, int(params.get("threshold_numerator", 1)))
    th_den = max(2, int(params.get("threshold_denominator", 2)))
    heal_fixed = params.get("heal_fixed_hp")
    heal_num = params.get("heal_fraction_numerator")
    heal_den = params.get("heal_fraction_denominator")
    if heal_fixed is not None:
        heal_expr = f"{int(heal_fixed)}"
    elif heal_num is not None and heal_den is not None:
        heal_expr = f"[(battler.totalhp.to_f * {int(heal_num)} / {int(heal_den)}).ceil, 1].max"
    else:
        heal_expr = "[(battler.totalhp.to_f / 4).ceil, 1].max"

    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::HPHeal)",
        f"    Battle::ItemEffects::HPHeal.add(:{item_id},",
        "      proc { |item, battler, battle, forced|",
        "        next false unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "        next false if !battler.canHeal?",
        f"        next false if !forced && battler.hp > battler.totalhp * {th_num} / {th_den}",
        f"        hp = {heal_expr}",
        "        battler.pbRecoverHP(hp)",
        '        battle.pbDisplay(_INTL("{1} restored its HP using its {2}!", battler.pbThis, battler.itemName)) unless forced',
        "        next true",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_raise_stat_at_hp_threshold(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """hp_heal / raise_stat_at_hp_threshold (pinch berries: Salac, Petaya, etc.)."""
    stat_key = str(params.get("stat", "SPEED")).upper().replace(" ", "_")
    ruby_stat = _ruby_stat(stat_key)
    stages = max(1, int(params.get("stages", 1)))
    th_num = max(1, int(params.get("threshold_numerator", 1)))
    th_den = max(2, int(params.get("threshold_denominator", 4)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::HPHeal)",
        f"    Battle::ItemEffects::HPHeal.add(:{item_id},",
        "      proc { |item, battler, battle, forced|",
        "        next false unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next false if !forced && battler.hp > battler.totalhp * {th_num} / {th_den}",
        f"        next false unless battler.pbCanRaiseStatStage?({ruby_stat}, battler)",
        '        battle.pbCommonAnimation("UseItem", battler) unless forced',
        f"        battler.pbRaiseStatStageByCause({ruby_stat}, {stages}, battler, battler.itemName)",
        "        next true",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_status_cure(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """status_cure / status_cure (Lum, Pecha, Cheri, etc.)."""
    cures = params.get("cures_status", [])
    if isinstance(cures, str):
        cures = [cures]
    cures_upper = [str(c).upper() for c in cures]
    cures_any = "ANY" in cures_upper
    cures_confusion = "CONFUSION" in cures_upper

    status_symbols = []
    for c in cures_upper:
        if c in ("ANY", "CONFUSION"):
            continue
        sym = _RUBY_STATUS_MAP.get(c)
        if sym and sym not in status_symbols:
            status_symbols.append(sym)
    status_list_ruby = "[" + ", ".join(status_symbols) + "]" if status_symbols else "[]"

    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::StatusCure)",
        f"    Battle::ItemEffects::StatusCure.add(:{item_id},",
        "      proc { |item, battler, battle, forced|",
        "        next false unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "        cured = false",
    ]
    if cures_any:
        body += [
            "        if battler.status != :NONE",
            "          begin",
            "            battler.pbCureStatus(forced ? false : true)",
            "          rescue StandardError",
            "            battler.status = :NONE",
            "            battler.statusCount = 0",
            "          end",
            "          cured = true",
            "        end",
            "        if (battler.effects[PBEffects::Confusion] rescue 0) > 0",
            "          begin",
            "            battler.pbCureConfusion",
            "          rescue StandardError",
            "            battler.effects[PBEffects::Confusion] = 0",
            "          end",
            "          cured = true",
            "        end",
        ]
    else:
        if status_symbols:
            body += [
                f"        statuses = {status_list_ruby}",
                "        if battler.status != :NONE && statuses.include?(battler.status)",
                "          begin",
                "            battler.pbCureStatus(forced ? false : true)",
                "          rescue StandardError",
                "            battler.status = :NONE",
                "            battler.statusCount = 0",
                "          end",
                "          cured = true",
                "        end",
            ]
        if cures_confusion:
            body += [
                "        if (battler.effects[PBEffects::Confusion] rescue 0) > 0",
                "          begin",
                "            battler.pbCureConfusion",
                "          rescue StandardError",
                "            battler.effects[PBEffects::Confusion] = 0",
                "          end",
                "          cured = true",
                "        end",
            ]
    body += [
        "        next cured",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_inflict_status_end_of_round(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round_effect / inflict_status_end_of_round (Flame Orb, Toxic Orb)."""
    status = str(params.get("status", "BURN")).upper()
    if status == "BURN":
        inflict = [
            "        next if !battler.pbCanBurn?(battler, false)",
            '        battler.pbBurn(nil, _INTL("{1} was burned by its {2}!", battler.pbThis, battler.itemName))',
        ]
    elif status == "TOXIC":
        inflict = [
            "        next if !battler.pbCanPoison?(battler, false)",
            '        battler.pbPoison(nil, _INTL("{1} was badly poisoned by its {2}!", battler.pbThis, battler.itemName), true)',
        ]
    elif status == "POISON":
        inflict = [
            "        next if !battler.pbCanPoison?(battler, false)",
            '        battler.pbPoison(nil, _INTL("{1} was poisoned by its {2}!", battler.pbThis, battler.itemName))',
        ]
    elif status == "PARALYSIS":
        inflict = [
            "        next if !battler.pbCanParalyze?(battler, false)",
            '        battler.pbParalyze(nil, _INTL("{1} was paralyzed by its {2}!", battler.pbThis, battler.itemName))',
        ]
    elif status == "SLEEP":
        inflict = [
            "        next if !battler.pbCanSleep?(battler, false)",
            "        battler.pbSleep",
        ]
    else:
        inflict = [f"        # Unknown status {status}, skipped"]
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::EndOfRoundEffect)",
        f"    Battle::ItemEffects::EndOfRoundEffect.add(:{item_id},",
        "      proc { |item, battler, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
    ]
    body.extend(inflict)
    body += [
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_damage_fraction_end_of_round(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round_effect / damage_fraction_end_of_round (Black Sludge non-Poison, Sticky Barb)."""
    num = max(1, int(params.get("fraction_numerator", 1)))
    den = max(2, int(params.get("fraction_denominator", 8)))
    require_not_type = params.get("require_not_type", params.get("excluded_type"))
    require_type = params.get("require_type", params.get("required_type"))
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::EndOfRoundEffect)",
        f"    Battle::ItemEffects::EndOfRoundEffect.add(:{item_id},",
        "      proc { |item, battler, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "        next unless battler.takesIndirectDamage?",
    ]
    if require_not_type:
        body.append(f"        next if battler.pbHasType?({_ruby_type(str(require_not_type))})")
    if require_type:
        body.append(f"        next unless battler.pbHasType?({_ruby_type(str(require_type))})")
    body += [
        f"        dmg = [(battler.totalhp.to_f * {num} / {den}).ceil, 1].max",
        "        begin",
        "          battler.pbReduceHP(dmg, false)",
        "        rescue StandardError",
        "          battler.pbTakeDamage(dmg, false, true, false) if battler.respond_to?(:pbTakeDamage)",
        "        end",
        '        battle.pbDisplay(_INTL("{1} was hurt by its {2}!", battler.pbThis, battler.itemName))',
        "        battler.pbItemHPHealCheck rescue nil",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_heal_fraction_by_type(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round / heal_fraction_by_type (Black Sludge for Poison types)."""
    num = max(1, int(params.get("fraction_numerator", 1)))
    den = max(1, int(params.get("fraction_denominator", 16)))
    require_type = params.get("require_type", params.get("required_type", "POISON"))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::EndOfRoundHealing.add(:{item_id},",
        "    proc { |item, battler, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "      next unless battler.canHeal?",
        f"      next unless battler.pbHasType?({_ruby_type(str(require_type))})",
        f"      hp = [(battler.totalhp.to_f * {num} / {den}).ceil, 1].max",
        "      battler.pbRecoverHP(hp)",
        '      battle.pbDisplay(_INTL("{1} restored a little HP using its {2}!", battler.pbThis, battler.itemName))',
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_crit_stage_boost(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """crit_calc / crit_stage_boost (Scope Lens, Razor Claw)."""
    stages = max(1, int(params.get("stages", 1)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::CriticalCalcFromUser)",
        f"    Battle::ItemEffects::CriticalCalcFromUser.add(:{item_id},",
        "      proc { |item, user, target, c|",
        "        next c unless CustomItemPatch.custom_item_effect_item_active?(user)",
        f"        next c + {stages}",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_accuracy_multiplier(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """accuracy_calc / accuracy_multiplier (Wide Lens, Zoom Lens)."""
    mult_text = _fmt_float(float(params.get("multiplier", 1.1)))
    require_slower = bool(params.get("require_slower", False))
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::AccuracyCalcFromUser)",
        f"    Battle::ItemEffects::AccuracyCalcFromUser.add(:{item_id},",
        "      proc { |item, mods, user, target, move, type|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(user)",
    ]
    if require_slower:
        body.append("        next unless target.movedThisRound? rescue next")
    body += [
        f"        mods[:accuracy_multiplier] = (mods[:accuracy_multiplier].to_f * {mult_text}).round(4) if mods.respond_to?(:[]=)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_evasion_multiplier(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """evasion_calc / evasion_multiplier (Bright Powder, Lax Incense)."""
    mult_text = _fmt_float(float(params.get("multiplier", 0.9)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::AccuracyCalcFromTarget)",
        f"    Battle::ItemEffects::AccuracyCalcFromTarget.add(:{item_id},",
        "      proc { |item, mods, user, target, move, type|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(target)",
        f"        mods[:accuracy_multiplier] = (mods[:accuracy_multiplier].to_f * {mult_text}).round(4) if mods.respond_to?(:[]=)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_speed_multiplier(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """speed_calc / speed_multiplier (Choice Scarf, Iron Ball).

    Indigo's ItemEffects::SpeedCalc uses the item-speed signature:
      proc { |item, battler, mult| next new_mult }
    """
    mult_text = _fmt_float(float(params.get("multiplier", 1.5)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::SpeedCalc)",
        f"    Battle::ItemEffects::SpeedCalc.add(:{item_id},",
        "      proc { |item, battler, mult|",
        "        next mult unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next (mult.to_f * {mult_text}).round(4)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_weight_multiplier(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """weight_calc / weight_multiplier (Float Stone, Iron Ball)."""
    mult_text = _fmt_float(float(params.get("multiplier", 0.5)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::WeightCalc)",
        f"    Battle::ItemEffects::WeightCalc.add(:{item_id},",
        "      proc { |item, battler, w|",
        "        next w unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next [(w.to_f * {mult_text}).round, 1].max",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_stat_loss_immunity(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """stat_loss_immunity / stat_loss_immunity (Clear Amulet)."""
    show_message = bool(params.get("show_message", True))
    body = [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::StatLossImmunity)",
        f"    Battle::ItemEffects::StatLossImmunity.add(:{item_id},",
        "      proc { |item, battler, stat, battle, showMessages|",
        "        next false unless CustomItemPatch.custom_item_effect_item_active?(battler)",
    ]
    if show_message:
        body += [
            "        if showMessages",
            '          battle.pbDisplay(_INTL("{1}\'s {2} prevents stat reduction!", battler.pbThis, battler.itemName))',
            "        end",
        ]
    body += [
        "        next true",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]
    return body


def _gen_stat_raise_on_intimidated(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """on_being_intimidated / stat_raise_on_intimidated (Adrenaline Orb)."""
    stat_key = str(params.get("stat", "SPEED")).upper().replace(" ", "_")
    ruby_stat = _ruby_stat(stat_key)
    stages = max(1, int(params.get("stages", 1)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::OnIntimidated)",
        f"    Battle::ItemEffects::OnIntimidated.add(:{item_id},",
        "      proc { |item, battler, battle|",
        "        next false unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next false unless battler.pbCanRaiseStatStage?({ruby_stat}, battler)",
        '        battle.pbCommonAnimation("UseItem", battler)',
        f"        next battler.pbRaiseStatStageByCause({ruby_stat}, {stages}, battler, battler.itemName)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_terrain_stat_boost(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """terrain_stat_boost / terrain_stat_boost (terrain seeds)."""
    terrain = str(params.get("terrain", "Electric"))
    ruby_terrain = _RUBY_TERRAIN_MAP.get(terrain, f":{terrain}")
    stat_key = str(params.get("stat", "DEFENSE")).upper().replace(" ", "_")
    ruby_stat = _ruby_stat(stat_key)
    stages = max(1, int(params.get("stages", 1)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::TerrainStatBoost)",
        f"    Battle::ItemEffects::TerrainStatBoost.add(:{item_id},",
        "      proc { |item, battler, battle|",
        "        next false unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next false if (battle.field.terrain rescue nil) != {ruby_terrain}",
        f"        next false unless battler.pbCanRaiseStatStage?({ruby_stat}, battler)",
        '        battle.pbCommonAnimation("UseItem", battler)',
        f"        next battler.pbRaiseStatStageByCause({ruby_stat}, {stages}, battler, battler.itemName)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_extend_weather(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """weather_extend / extend_weather (Heat Rock, Damp Rock, etc.)."""
    weather_list = _ruby_weather_list(params.get("weather", []))
    if not weather_list:
        return [f"# --- pool effect: {effect_id} for {item_id} (skipped: no weather defined) ---", ""]
    extension = max(1, int(params.get("extension_turns", 3)))
    weather_ruby = "[" + ", ".join(weather_list) + "]"
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::WeatherExtender)",
        f"    Battle::ItemEffects::WeatherExtender.add(:{item_id},",
        "      proc { |item, weather, duration, battler, battle|",
        "        next duration unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next duration unless {weather_ruby}.include?(weather)",
        f"        next duration + {extension}",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_stat_restore_after_move(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """stat_restore_after_move / stat_restore_after_move (White Herb)."""
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::OnEndOfUsingMoveStatRestore)",
        f"    Battle::ItemEffects::OnEndOfUsingMoveStatRestore.add(:{item_id},",
        "      proc { |item, battler, battle, forced|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "        reducedStats = false",
        "        begin",
        "          GameData::Stat.each_battle do |s|",
        "            next if battler.stages[s.id] >= 0",
        "            battler.stages[s.id] = 0",
        "            battler.statsRaisedThisRound = true if battler.respond_to?(:statsRaisedThisRound=)",
        "            reducedStats = true",
        "          end",
        "        rescue StandardError",
        "          reducedStats = false",
        "        end",
        "        if reducedStats && !forced",
        '          battle.pbDisplay(_INTL("{1} restored its stats using its {2}!", battler.pbThis, battler.itemName))',
        "        end",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_stat_raise_on_switch_in(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """on_switch_in / stat_raise_on_switch_in."""
    stat_key = str(params.get("stat", "ATTACK")).upper().replace(" ", "_")
    ruby_stat = _ruby_stat(stat_key)
    stages = max(1, int(params.get("stages", 1)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        "  if defined?(Battle::ItemEffects::OnSwitchIn)",
        f"    Battle::ItemEffects::OnSwitchIn.add(:{item_id},",
        "      proc { |item, battler, battle|",
        "        next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        f"        next unless battler.pbCanRaiseStatStage?({ruby_stat}, battler)",
        f"        battler.pbRaiseStatStageByCause({ruby_stat}, {stages}, battler, battler.itemName)",
        "      }",
        "    )",
        "  end",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]



def _gen_heal_fraction_if_weather(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round / heal_fraction_if_weather (Rain Dish, Ice Body)."""
    weather_list = _ruby_weather_list(params.get("weather", []))
    if not weather_list:
        return [f"# --- pool effect: {effect_id} for {item_id} (skipped: no weather defined) ---", ""]
    num = max(1, int(params.get("fraction_numerator", 1)))
    den = max(1, int(params.get("fraction_denominator", 16)))
    weather_ruby = "[" + ", ".join(weather_list) + "]"
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::EndOfRoundHealing.add(:{item_id},",
        "    proc { |item, battler, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "      next unless battler.canHeal?",
        "      weather = nil",
        "      begin",
        "        weather = battle.pbWeather",
        "      rescue StandardError",
        "        weather = battle.field.weather rescue nil",
        "      end",
        f"      next unless {weather_ruby}.include?(weather)",
        f"      hp = [(battler.totalhp.to_f * {num} / {den}).ceil, 1].max",
        "      battler.pbRecoverHP(hp)",
        '      battle.pbDisplay(_INTL("{1} restored HP with {2}!", battler.pbThis, battler.itemName))',
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]


def _gen_heal_fraction_if_status(item_id: str, effect_id: str, params: dict[str, Any]) -> list[str]:
    """end_of_round / heal_fraction_if_status (Poison Heal-style)."""
    statuses = _ruby_status_list(params.get("require_status", []))
    if not statuses:
        return [f"# --- pool effect: {effect_id} for {item_id} (skipped: no status defined) ---", ""]
    status_ruby = "[" + ", ".join(statuses) + "]"
    num = max(1, int(params.get("fraction_numerator", 1)))
    den = max(1, int(params.get("fraction_denominator", 8)))
    return [
        f"# --- pool effect: {effect_id} for {item_id} ---",
        "begin",
        f"  Battle::ItemEffects::EndOfRoundHealing.add(:{item_id},",
        "    proc { |item, battler, battle|",
        "      next unless CustomItemPatch.custom_item_effect_item_active?(battler)",
        "      next unless battler.canHeal?",
        f"      next unless {status_ruby}.include?(battler.status)",
        f"      hp = [(battler.totalhp.to_f * {num} / {den}).ceil, 1].max",
        "      battler.pbRecoverHP(hp)",
        '      battle.pbDisplay(_INTL("{1} restored HP with {2}!", battler.pbThis, battler.itemName))',
        "    }",
        "  )",
        "rescue StandardError => e",
        f'  echoln("CustomItemPatch pool [{effect_id}]: #{{e}}") if defined?(echoln)',
        "end",
        "",
    ]

# ---------------------------------------------------------------------------
# Dispatch table for compile_pool_effects
# ---------------------------------------------------------------------------

def compile_pool_effects(item_pool_effects: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Generate Ruby lines for all pool-based effects.

    Parameters
    ----------
    item_pool_effects:
        {item_id: [effect_def, ...]} — each effect_def is a full pool entry dict.
        sheer_force_modifier entries must already be filtered out by the caller
        (routed through ability_active_bridge in patcher.py instead).

    Returns
    -------
    list[str]
        Ruby source lines to be appended to ZZ_CustomItemPatch.
    """
    if not item_pool_effects:
        return []

    lines: list[str] = ["# --- Pool-based Hook Effects (Phase 1 + Phase 2) ---", ""]

    for item_id in sorted(item_pool_effects.keys()):
        effects = item_pool_effects[item_id]

        # Several selected Dragon Soul effects share the same native handler bucket
        # (AfterMoveUseFromUser). Registering them separately can overwrite by
        # item ID, so compile them into one combined handler.
        combined_after_move_templates = {
            "heal_percent_damage_dealt",
            "drain_heal_multiplier",
            "raise_user_stat_stage",
            "lower_target_stat_stage",
            "apply_status_target",
            "flinch_target",
            "heal_user_fraction",
            "recoil_percent_damage_dealt",
            "start_weather",
            "start_terrain",
        }
        combined_after_move_effects = [
            e for e in effects
            if isinstance(e, dict) and (
                (str(e.get("hook", "")) in {"after_damage_dealt", "after_move_use"})
                and str(e.get("template", "")) in combined_after_move_templates
            )
        ]
        if combined_after_move_effects:
            lines.extend(_gen_after_move_use_combined(item_id, combined_after_move_effects))

        for effect in effects:
            if not isinstance(effect, dict):
                continue
            hook = str(effect.get("hook", ""))
            template = str(effect.get("template", ""))
            params: dict[str, Any] = effect.get("params", {}) if isinstance(effect.get("params"), dict) else {}
            effect_id = str(effect.get("id", "UNKNOWN"))

            # Already compiled as part of the combined AfterMoveUseFromUser handler.
            if effect in combined_after_move_effects:
                continue

            # Phase 1
            if hook == "end_of_round" and template == "heal_fraction_max_hp":
                lines.extend(_gen_heal_fraction_max_hp(item_id, effect_id, params))
            elif hook == "end_of_round" and template == "heal_fraction_by_type":
                lines.extend(_gen_heal_fraction_by_type(item_id, effect_id, params))
            elif hook == "end_of_round" and template == "heal_fraction_if_weather":
                lines.extend(_gen_heal_fraction_if_weather(item_id, effect_id, params))
            elif hook == "end_of_round" and template == "heal_fraction_if_status":
                lines.extend(_gen_heal_fraction_if_status(item_id, effect_id, params))
            elif hook == "damage_calc" and template == "damage_multiplier":
                lines.extend(_gen_damage_multiplier(item_id, effect_id, params))
            elif hook == "damage_calc" and template == "damage_multiplier_conditional":
                lines.extend(_gen_damage_multiplier_conditional(item_id, effect_id, params))
            elif hook == "speed_calc" and template == "speed_multiplier_if_weather":
                lines.extend(_gen_speed_multiplier_if_weather(item_id, effect_id, params))
            elif hook == "speed_calc" and template == "speed_multiplier":
                lines.extend(_gen_speed_multiplier(item_id, effect_id, params))
            elif hook == "end_of_round_effect" and template == "raise_user_stat_stage_end_of_round":
                lines.extend(_gen_raise_user_stat_stage_end_of_round(item_id, effect_id, params))
            # Phase 2
            elif hook == "damage_calc_from_target" and template == "damage_reduction_multiplier":
                lines.extend(_gen_damage_reduction_multiplier(item_id, effect_id, params))
            elif hook == "on_being_hit" and template == "contact_recoil_damage":
                lines.extend(_gen_contact_recoil_damage(item_id, effect_id, params))
            elif hook == "on_being_hit" and template == "inflict_status_on_contact":
                lines.extend(_gen_inflict_status_on_contact(item_id, effect_id, params))
            elif hook == "on_being_hit" and template == "stat_raise_on_hit":
                lines.extend(_gen_stat_raise_on_hit(item_id, effect_id, params))
            elif hook == "hp_heal" and template == "heal_at_hp_threshold":
                lines.extend(_gen_heal_at_hp_threshold(item_id, effect_id, params))
            elif hook == "hp_heal" and template == "raise_stat_at_hp_threshold":
                lines.extend(_gen_raise_stat_at_hp_threshold(item_id, effect_id, params))
            elif hook == "status_cure" and template == "status_cure":
                lines.extend(_gen_status_cure(item_id, effect_id, params))
            elif hook == "end_of_round_effect" and template == "inflict_status_end_of_round":
                lines.extend(_gen_inflict_status_end_of_round(item_id, effect_id, params))
            elif hook == "end_of_round_effect" and template == "damage_fraction_end_of_round":
                lines.extend(_gen_damage_fraction_end_of_round(item_id, effect_id, params))
            elif hook == "crit_calc" and template == "crit_stage_boost":
                lines.extend(_gen_crit_stage_boost(item_id, effect_id, params))
            elif hook == "accuracy_calc" and template == "accuracy_multiplier":
                lines.extend(_gen_accuracy_multiplier(item_id, effect_id, params))
            elif hook == "evasion_calc" and template == "evasion_multiplier":
                lines.extend(_gen_evasion_multiplier(item_id, effect_id, params))
            elif hook == "weight_calc" and template == "weight_multiplier":
                lines.extend(_gen_weight_multiplier(item_id, effect_id, params))
            elif hook == "stat_loss_immunity" and template == "stat_loss_immunity":
                lines.extend(_gen_stat_loss_immunity(item_id, effect_id, params))
            elif hook == "on_being_intimidated" and template == "stat_raise_on_intimidated":
                lines.extend(_gen_stat_raise_on_intimidated(item_id, effect_id, params))
            elif hook == "terrain_stat_boost" and template == "terrain_stat_boost":
                lines.extend(_gen_terrain_stat_boost(item_id, effect_id, params))
            elif hook == "weather_extend" and template == "extend_weather":
                lines.extend(_gen_extend_weather(item_id, effect_id, params))
            elif hook == "stat_restore_after_move" and template == "stat_restore_after_move":
                lines.extend(_gen_stat_restore_after_move(item_id, effect_id, params))
            elif hook == "on_switch_in" and template == "stat_raise_on_switch_in":
                lines.extend(_gen_stat_raise_on_switch_in(item_id, effect_id, params))
            else:
                lines.append(f"# --- pool effect: {effect_id} for {item_id} (hook={hook!r} template={template!r} not compiled) ---")
                lines.append("")

    return lines
