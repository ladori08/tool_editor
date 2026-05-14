# Custom Effect Builder Plan

## Purpose
- Add a reusable Custom Effect authoring system similar to Custom Item authoring.
- User should create effects by choosing clear fields from GUI dropdowns/wizard steps, not by editing raw `hook` / `template` / `params`.
- The tool compiles those user choices into safe internal runtime definitions.

## Core Model
- Store user-created effects in parallel data:
  - `tools/custom_item/data/custom_effect_manifest.json`
- Custom effects become reusable entries in the CustomItem normalized effect pool.
- Custom items can combine built-in pool effects and user-created custom effects.
- Custom effects must not modify vanilla item/move/ability data.

## Multi-Game Requirement
- Custom effects should be reusable across compatible Pokemon Essentials-style games.
- The effect manifest should store game-agnostic authoring fields where possible:
  - trigger timing
  - effect type/family
  - target
  - conditions
  - values
- A per-game compatibility layer should validate whether the current game supports the compiled hook/template.
- For each game root, the tool should report:
  - supported effects
  - partial effects
  - unsupported effects
  - missing runtime bridge/template coverage
- Unsupported effects may remain in the manifest for planning/reuse, but must not compile into runtime patches for that game.

## User-Facing Builder Flow

### 1. Basic
- Effect ID
- Name
- Description
- Category:
  - Damage
  - Healing
  - Stat
  - Status
  - Speed
  - Contact
  - End Turn
  - Battle Field

### 2. Trigger Timing
Dropdown examples:
- When holder uses a move
- After holder deals damage
- After holder is hit
- On contact
- End of turn
- Before damage calculation
- When HP below threshold
- When switching in
- Once per battle

### 3. Effect Type
Options should depend on the selected trigger:
- Multiply damage
- Heal holder
- Drain damage dealt
- Raise/lower stat stage
- Inflict status
- Cure status
- Flinch target
- Modify speed
- Activate ability-like behavior
- Trigger existing move additional effect

### 4. Target
- Holder
- Opponent / target
- Attacker
- Ally side
- Enemy side
- Field

### 5. Conditions
Field examples:
- Move type is X
- Move is super-effective
- Holder HP below X%
- Target has status
- Weather is X
- Once per battle
- Contact move only
- Physical/Special/Status move only

### 6. Values
Dynamic fields based on effect type:
- multiplier: `1.2x`, `1.5x`, custom number
- heal fraction: `1/16`, `1/8`, `50%`, `75%`
- stat: Attack/Defense/SpAtk/SpDef/Speed/Accuracy/Evasion
- stages: `+1`, `+2`, `-1`
- chance: `10%`, `30%`, `100%`
- status: Burn/Poison/Paralysis/Sleep/Freeze

## Explanation / Tooltip Requirement
- Each field label should have a short explanation immediately beside or below it when there is enough layout space.
- If there is not enough space, show the explanation as a tooltip.
- Tooltip content should explain:
  - what the field controls
  - what common choices mean
  - whether the choice affects compatibility
  - any gameplay caveat
- Dropdown list rows must also show tooltip descriptions while the user hovers/searches through the list before selecting an entry.
- This dropdown-hover tooltip requirement applies globally to all tooltip-enabled dropdowns in the tool, not only Custom Effect Builder.

## Internal Compiled Shape
Example user-created effect:

```json
{
  "id": "AURA_FIGHTING_BOOST",
  "name": "Aura Fighting Boost",
  "description": "Fighting-type moves deal 1.2x damage.",
  "trigger": "before_damage_calculation",
  "effect_type": "multiply_damage",
  "target": "holder_move",
  "conditions": {
    "move_type": "FIGHTING"
  },
  "values": {
    "multiplier": 1.2
  },
  "compiled": {
    "hook": "damage_calc",
    "template": "damage_multiplier_conditional",
    "params": {
      "require_move_type": "FIGHTING",
      "multiplier": 1.2
    }
  },
  "support_status": "supported",
  "risk_level": "safe"
}
```

## Support Status Rules
- `supported`: expected to compile and run in the current game.
- `partial`: can compile/run, but has known caveats.
- `unsupported`: visible for planning, but not compiled into runtime.
- `advanced`: requires special engine work or unsafe behavior, not auto-compiled.

## Implementation Milestones

### Builder v1
- Add `custom_effect_manifest.json`.
- Add loader/saver/validator.
- Add GUI builder for:
  - Damage multiplier
  - Heal holder
  - Drain damage dealt
  - Raise/lower stat stage
  - Speed multiplier
- Merge custom effects into CustomItem pool selector.
- Add field explanations/tooltips.
- Add dropdown-list hover tooltips for Custom Effect builder fields.

### Builder v2
- Add:
  - Status inflict/cure
  - HP threshold effects
  - Contact effects
  - End-turn effects
  - Berry-like effects
- Expand fixed runtime bridge coverage as needed.
- Add compatibility report per game root.

#### Builder v2 Category Expansion Matrix

Status category:
- Desired Effect Types:
  - Inflict status on hit
  - Inflict status on contact
  - Cure holder status
  - Status immunity while held
- Required hook/template (target):
  - `after_move_use` + `apply_status_target`
  - `on_being_hit` + `inflict_status_on_contact`
  - `status_cure` + `status_cure`
  - `end_of_round_effect` + `inflict_status_end_of_round` (for orb-like effects)
- Risk:
  - medium to high
- Why not in Builder v1:
  - needs strict gating for chance rolls, status immunity checks, and battle-engine side effects to avoid behavior drift.

Contact category:
- Desired Effect Types:
  - Recoil damage to contact attacker
  - Chance to inflict status on contact attacker
  - Stat raise when holder is hit
- Required hook/template (target):
  - `on_being_hit` + `contact_recoil_damage`
  - `on_being_hit` + `inflict_status_on_contact`
  - `on_being_hit` + `stat_raise_on_hit`
- Risk:
  - medium
- Why not in Builder v1:
  - requires robust contact detection + multi-hit handling + interaction checks (Magic Guard/Shield Dust-like paths) before exposing to Wizard.

Battle Field category:
- Desired Effect Types:
  - Start weather
  - Start terrain
  - Screen/veil-style side effects
  - Turn-order/room effects (advanced)
- Required hook/template (target):
  - `after_move_use` + `start_weather`
  - `after_move_use` + `start_terrain`
  - planned new safe templates for side screens/rooms once fixed bridge coverage is added
- Risk:
  - high
- Why not in Builder v1:
  - field/side state is global and high-blast-radius; requires extra safety checks, duration controls, and compatibility guards before enabling.

### Builder v3
- Add:
  - Ability-like bridge effects
  - Move additional effect bridge effects
  - More battle-field/side conditions
  - Optional expert/raw view for diagnostics only
- Apply dropdown-hover tooltip behavior across all existing tooltip-enabled dropdowns in the tool.

## Acceptance Criteria
- User can create a custom effect without seeing raw `hook` / `template` / `params`.
- Created effects appear in CustomItem effect pool selector.
- Custom item apply compiles supported custom effects into `custom_item_runtime.rb`.
- Unsupported/advanced custom effects remain visible but are not compiled.
- The same custom effect manifest can be inspected against another compatible game root.
- Field explanations are visible inline or via tooltip.
- Dropdown list hover tooltips work while browsing list entries before selection.
