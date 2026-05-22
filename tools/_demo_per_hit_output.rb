# --- Pool-based Hook Effects (Phase 1 + Phase 2) ---

# --- combined after-move pool effects for DEMO_ITEM: DEMO_PER_HIT ---
begin
  Battle::ItemEffects::AfterMoveUseFromUser.add(:DEMO_ITEM,
    proc { |item, user, targets, move, numHits, battle|
      next unless CustomItemPatch.custom_item_effect_item_active?(user)
      targets = [] if !targets
      # pool effect: DEMO_PER_HIT
      tracker_demo_per_hit = :@custom_item_pool_once_demo_per_hit
      unless user.instance_variable_defined?(tracker_demo_per_hit) && user.instance_variable_get(tracker_demo_per_hit)
        stats_demo_per_hit = [:ATTACK]
        any_raised_demo_per_hit = false
        hits_demo_per_hit = (numHits || 1)
        hits_demo_per_hit.times do
          stats_demo_per_hit.each do |stat|
            next unless user.pbCanRaiseStatStage?(stat, user)
            user.pbRaiseStatStageByCause(stat, 1, user, user.itemName) rescue user.pbRaiseStatStage(stat, 1, user)
            any_raised_demo_per_hit = true
          end
        end
        user.instance_variable_set(tracker_demo_per_hit, true) if any_raised_demo_per_hit
      end
    }
  )
rescue StandardError => e
  echoln("CustomItemPatch pool [combined_after_move_use DEMO_ITEM]: #{e}") if defined?(echoln)
end
