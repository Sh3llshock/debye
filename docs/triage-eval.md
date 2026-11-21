# Triage eval: 66 gold conversations, 1 pass(es)

`scripts/eval_triage.py` runs every conversation in `data/diagnosis/triage_gold_a.json` and `triage_gold_b.json` end to end: the real app on a temp database, Luna as Debye, a simulated tenant (same model) that answers only from the conversation's `tenant_facts` and follows the gold tenant turns, and a judge (same model). A conversation passes when the routed area, the cause, the outcome and the question limit match (for two problems: both), and the judge finds no invented fact, no missed clarification, the edge case handled, tone at least 4/5 and no `must_not` broken.

| | result |
|---|---|
| passed | **59/66 (89%)** |
| area routed right | 66/66 (100%) |
| cause | 66/66 (100%) |
| outcome | 66/66 |
| within the question limit | 66/66 (avg 0.59) |
| no invented facts | 65/66 |
| tone | 4.79/5 |
| must_not clean | 59/66 |
| avg turn | 2.7 s |

## By area

| area | passed | cause |
|---|---|---|
| appliances | 3/4 | 4/4 |
| blocked_drain | 4/5 | 5/5 |
| electrics | 7/7 | 7/7 |
| intercom | 4/4 | 4/4 |
| lift | 4/5 | 5/5 |
| management | 3/4 | 4/4 |
| mold_damp | 3/3 | 3/3 |
| other | 6/7 | 7/7 |
| pests | 6/6 | 6/6 |
| roof_ceiling_leak | 4/5 | 5/5 |
| water_leak | 7/8 | 8/8 |
| windows_doors | 8/8 | 8/8 |

## By tag

| tag | passed |
|---|---|
| decisive_first | 27/27 |
| self_help_fails | 10/10 |
| self_help_works | 9/9 |
| german | 8/8 |
| emergency | 7/7 |
| two_problems | 5/5 |
| photo | 4/4 |
| clean | 3/4 |
| typos | 3/3 |
| burst | 3/3 |
| off_topic | 2/3 |
| vague_area | 3/3 |
| vague | 2/2 |
| dont_know | 1/2 |
| question_back | 1/2 |
| smoke_alarm | 1/2 |
| contradiction | 0/1 |
| frustrated | 0/1 |
| ceiling_not_flooding | 1/1 |
| hot_water_second | 1/1 |

## Conversations

| id | area (expected → routed) | expected cause | got | q | tone | notes |
|---|---|---|---|---|---|---|
| ✓ ta01_burst_pipe_flooding | water_leak → water_leak | major_leak_flooding | major_leak_flooding | 0 | 5 | Debye gave the emergency safety steps immediately and did not ask a question or promise an arrival time. |
| ✓ ta02_tap_not_closed_typos | water_leak → water_leak | tap_not_fully_closed | tap_not_fully_closed | 1 | 5 | Debye asked the right clarifying question, gave the appropriate self-help, and closed the issue after it stopped dripping. |
| ✓ ta03_tap_washer_after_tip | water_leak → water_leak | dripping_tap_washer | dripping_tap_washer | 1 | 5 | Debye gives a self-help check, then routes the recurring drip to the caretaker without closing the case or asking the tenant to replace anything. |
| ✓ ta04_toilet_running_de | water_leak → water_leak | toilet_running | toilet_running | 0 | 5 | Debye answers in German, identifies the toilet issue, and gives the caretaker and shutoff advice without asking where the water comes from. |
| ✓ ta05_toilet_floor_photo_vague | water_leak → water_leak | toilet_leak_floor | toilet_leak_floor | 1 | 5 | Debye clarified the ambiguous answer, used the photos to identify the floor leak, and included them in the consent question. |
| ✓ ta06_washing_machine_hose_fails | water_leak → water_leak | wall_valve_leak | wall_valve_leak | 0 | 5 | Debye correctly identified the wall connection leak, advised containment and a plumber, and obtained consent without asking where the water came from or mentioning photos. |
| ✗ ta07_under_sink_dont_know | water_leak → water_leak | under_sink_leak | under_sink_leak | 0 | 4 | Debye gives appropriate leak steps and arranges a plumber, but tells the tenant to keep the valve closed without first establishing whether they can check it. |
| ✓ ta08_radiator_valve_burst | water_leak → water_leak | radiator_valve_leak | radiator_valve_leak | 0 | 5 | Debye handled the burst as one issue, gave appropriate safe advice, and arranged a heating technician. |
| ✓ ta09_shower_hair_off_topic | blocked_drain → blocked_drain | shower_hair_clog | shower_hair_clog | 1 | 4 | Debye correctly treated “lol ok” as not answering, gave a simple self-help fix, and closed after the tenant confirmed it worked. |
| ✓ ta10_kitchen_sink_de | blocked_drain → blocked_drain | sink_trap_clog | sink_trap_clog | 1 | 5 | Debye gave concise German self-help advice and closed naturally after the tenant confirmed it worked. |
| ✓ ta11_toilet_clog_plunger_fails | blocked_drain → blocked_drain | stubborn_blockage | stubborn_blockage | 2 | 5 | Debye gives the self-help step, checks for a related drain issue, and routes the failed blockage to drain cleaning with consent. |
| ✗ ta12_main_stack_contradiction | blocked_drain → blocked_drain | main_stack_blockage | main_stack_blockage | 1 | 4 | Debye treated the contradictory answer as confirmation and proceeded without checking whether water comes up in the shower. |
| ✓ ta13_several_drains_question_back | blocked_drain → blocked_drain | several_drains_blocked | several_drains_blocked | 0 | 4 | Debye avoids promising a cost and correctly keeps the consent request pending, though it does not directly answer the tenant’s question that they will not pay for repairs. |
| ✓ ta14_burning_smell_socket | electrics → electrics | electrical_burning | electrical_burning | 0 | 5 | Debye gives the emergency safety steps immediately without asking a question or directing the tenant to inspect the socket. |
| ✓ ta15_building_blackout | electrics → electrics | building_power_outage | building_power_outage | 0 | 5 | Debye gives immediate, appropriate safety steps for a whole-building outage without asking a question. |
| ✓ ta16_kitchen_breaker_burst | electrics → electrics | tripped_breaker | tripped_breaker | 1 | 5 | Debye addressed the burst as one issue, gave the self-help steps, and closed after the tenant confirmed it worked. |
| ✓ ta17_hall_light_bulb_de | electrics → electrics | bulb_blown | bulb_blown | 1 | 5 | Debye responds in German, gives the cheap bulb check, and closes the issue after the tenant says it works. |
| ✓ ta18_bathroom_light_fitting | electrics → electrics | light_fitting_fault | light_fitting_fault | 1 | 5 | Debye suggested a new bulb first and, when that failed, routed the tenant to the caretaker as intended. |
| ✓ ta19_socket_fault_photo | electrics → electrics | socket_or_circuit_fault | socket_or_circuit_fault | 1 | 5 | Debye handled the photos, recommended an electrician, and included them in the consent question. |
| ✓ ta20_flat_supply_vague | electrics → electrics | flat_supply_fault | flat_supply_fault | 2 | 5 | Debye clarified the vague answer, then correctly identified a likely flat supply fault and routed it to the caretaker. |
| ✓ ta21_break_in | windows_doors → windows_doors | break_in | break_in | 0 | 5 | Debye gives the break-in safety steps immediately, asks no diagnostic question, and does not mention cost. |
| ✓ ta22_locked_out_typos | windows_doors → windows_doors | locked_out | locked_out | 0 | 5 | Debye correctly recommends a locksmith, explains the likely cost, requests consent, and does not ask which door or correct the typos. |
| ✓ ta23_broken_glass_photo_burst | windows_doors → windows_doors | broken_glass | broken_glass | 0 | 5 | Debye gave the appropriate glass-safety advice and included the photos in the consent question before arranging a glazier. |
| ✓ ta24_window_tilt_fails | windows_doors → windows_doors | window_wont_close | window_wont_close | 1 | 5 | Debye asked one relevant clarifying question, offered a self-help tip, and arranged the caretaker after it failed. |
| ✓ ta25_window_handle_de | windows_doors → windows_doors | window_handle_hinge | window_handle_hinge | 0 | 5 | Debye responds in German, uses du, and correctly routes the broken window handle to the caretaker without unnecessary questions. |
| ✓ ta26_building_door_wont_close | windows_doors → windows_doors | building_door_fault | building_door_fault | 0 | 5 | Debye correctly routes the entrance-door fault to the caretaker without asking an unnecessary question. |
| ✓ ta27_flat_door_lock_off_topic | windows_doors → windows_doors | flat_door_lock_broken | flat_door_lock_broken | 1 | 5 | Debye correctly repeated the door-type question after the off-topic reply and handled the lock issue without violating any listed rule. |
| ✓ ta28_draughty_window | windows_doors → windows_doors | draughty_window | draughty_window | 0 | 5 | Debye correctly identifies the draught and says the caretaker will check it, matching the intended response. |
| ✓ ta29_own_fridge_management | appliances → appliances | own_appliance | own_appliance | 1 | 5 | Debye correctly identifies the fridge as the tenant’s own appliance and gives the appropriate repair route. |
| ✓ ta30_dishwasher_fuse_works | appliances → appliances | appliance_tripped_fuse | appliance_tripped_fuse | 2 | 4 | Debye gave sensible self-help steps and closed the issue after the tenant confirmed it worked. |
| ✓ ta31_oven_fuse_fails | appliances → appliances | appliance_no_power | appliance_no_power | 2 | 5 | Debye checked the fuse, continued to an electrician after the oven stayed dead, and requested consent before sharing details. |
| ✗ ta32_washing_machine_frustrated | appliances → appliances | appliance_fault | appliance_fault | 1 | 4 | Debye asked a diagnostic question after the tenant asked to just send someone, though it then arranged the technician without arguing. |
| ✓ tb01_bedroom_mould_dry_de | mold_damp → mold_damp | condensation_mould | condensation_mould | 0 | 4 | Debye gave the self-help advice and closed the conversation after the tenant reported the spots were gone. |
| ✓ tb02_mould_back_after_cleaning | mold_damp → mold_damp | large_mould | large_mould | 2 | 5 | Debye appropriately escalated the returning, larger mould patch and did not close the case, recommend cleaning it again, blame the tenant, or ask another diagnostic question. |
| ✓ tb03_wet_wall_photo | mold_damp → mold_damp | damp_ingress | damp_ingress | 1 | 5 | Debye clarified whether the wall was wet, then gave the appropriate advice and included the photos in the consent question. |
| ✓ tb04_mouse_droppings | pests → pests | rodents | rodents | 0 | 5 | Debye recommends pest control, gives practical precautions, and requests consent to share details without asking prohibited questions. |
| ✓ tb05_cockroaches_typos | pests → pests | cockroaches | cockroaches | 0 | 5 | Debye correctly identifies cockroaches, gives brief pest-control advice, and requests consent to share the tenant’s details. |
| ✓ tb06_ants_few_works | pests → pests | ants_minor | ants_minor | 1 | 5 | Debye asked a sensible clarifying question, suggested self-help, and closed the issue after the tenant confirmed it was resolved. |
| ✓ tb07_ants_come_back_infestation | pests → pests | pest_infestation | pest_infestation | 1 | 5 | Debye gave the self-help tip, then escalated to pest control when it failed without repeating the tip or asking what kind of pest it was. |
| ✓ tb08_bites_vague_area | pests → pests | bedbugs | bedbugs | 0 | 5 | Debye asks what the vague first report is about, then gives appropriate bedbug advice and arranges pest control. |
| ✓ tb09_top_floor_rain_drip | roof_ceiling_leak → roof_ceiling_leak | roof_leak | roof_leak | 1 | 5 | Debye sensibly confirmed the flat is directly under the roof, then gave appropriate steps and arranged a roofer. |
| ✓ tb10_ceiling_pouring_dry_day | roof_ceiling_leak → roof_ceiling_leak | neighbour_above_leak | neighbour_above_leak | 1 | 5 | Debye asks a relevant clarifying question, then gives the expected caretaker response and bucket advice. |
| ✓ tb11_window_frame_rain | roof_ceiling_leak → roof_ceiling_leak | window_frame_leak | window_frame_leak | 0 | 5 | Debye correctly identifies a window-frame leak, offers a practical temporary step, and arranges the repair without asking an unnecessary question. |
| ✗ tb12_outside_wall_off_topic | roof_ceiling_leak → roof_ceiling_leak | facade_leak | facade_leak | 0 | 4 | Debye guessed the leak was through an outside wall without clarifying, and the off-topic weather remark was not handled while keeping the open question. |
| ✓ tb13_doorbell_muted_fails | intercom → intercom | flat_handset_fault | flat_handset_fault | 2 | 5 | Debye checks the neighbour’s doorbell and the mute switch, then arranges a technician after the tip fails. |
| ✓ tb14_doorbell_volume_dont_know | intercom → intercom | bell_muted | bell_muted | 1 | 5 | Debye suggested a simple volume check and the tenant confirmed it worked; closing the issue was appropriate. |
| ✓ tb15_whole_building_intercom | intercom → intercom | building_intercom_fault | building_intercom_fault | 0 | 5 | Debye uses the neighbour’s report to identify a building-level fault, then appropriately requests consent to send the named electrician. |
| ✓ tb16_neighbour_stuck_in_lift | lift → lift | person_trapped | person_trapped | 0 | 5 | Debye gives the lift emergency safety steps immediately and asks no diagnostic questions. |
| ✗ tb17_lift_not_coming_question_back | lift → lift | lift_out_of_service | lift_out_of_service | 1 | 4 | Debye answered the timing question without promising a repair time, but failed to repeat the consent question after the tenant asked how long it would take. |
| ✓ tb18_maintenance_sign_still_down | lift → lift | lift_out_of_service | lift_out_of_service | 1 | 5 | Debye correctly moves from the expired maintenance notice to arranging a lift repair, without repeating the sign question or telling the tenant to keep waiting. |
| ✓ tb19_lift_jerks_vague_area | lift → lift | lift_fault_minor | lift_fault_minor | 0 | 5 | Debye first asks what the vague report is about, then handles the lift issue without guessing or asking whether it moves. |
| ✓ tb20_utility_bill_de | management → management | rent_question | rent_question | 0 | 5 | Debye responds in German, routes the question to the named property manager, and makes no prohibited claims. |
| ✓ tb21_loud_music_nightly | management → management | noise_complaint | noise_complaint | 0 | 5 | Debye handled the clear noise complaint concisely without making prohibited promises or telling the tenant to confront the neighbours. |
| ✓ tb22_notice_period | management → management | contract_question | contract_question | 0 | 5 | Debye correctly routed the clear contract question to the property manager without stating a notice period. |
| ✗ tb23_neighbour_problem_asked | management → management | neighbour_dispute | neighbour_dispute | 0 | 3 | Debye routed the vague neighbour problem without asking what it was about, so the tenant’s specific issue was never established. |
| ✓ tb24_smoke_from_flat_below | other → other | fire_smoke | fire_smoke | 0 | 5 | Debye gives the emergency safety steps immediately, without asking a question or suggesting the tenant investigate. |
| ✓ tb25_co_alarm | other → other | co_alarm | co_alarm | 0 | 5 | Debye gave the emergency safety steps immediately and did not ask a question. |
| ✓ tb26_smoke_alarm_short_beeps | other → other | smoke_alarm_battery | smoke_alarm_battery | 1 | 5 | Debye clarified the alarm pattern and gave the intended battery and caretaker guidance without treating it as a fire. |
| ✗ tb27_smoke_alarm_loud_no_smoke | other → other | smoke_alarm_sounding | smoke_alarm_sounding | 0 | 3 | Debye skipped the required question about whether the alarm was brief beeping or a continuous alarm and gave fire-safety advice before clarifying. |
| ✓ tb28_loose_tile_de_vague_area | other → other | in_flat_repair | in_flat_repair | 0 | 4 | Debye asks what the problem is, then routes the loose bathroom tile appropriately in German without asking whether it is urgent. |
| ✓ tb29_balcony_railing_urgent | other → other | in_flat_urgent | in_flat_urgent | 1 | 5 | Debye correctly treats the loose railing as urgent and says the caretaker will come today or tomorrow. |
| ✓ tb30_buzzer_and_mould | intercom → intercom | door_opener_fault | door_opener_fault + large_mould | 0 | 5 | Debye handled the buzzer first, then clarified the mould and arranged specialist treatment without violating the listed rules. |
| ✓ tb31_wasps_and_loose_tile | pests → pests | wasps_nest | wasps_nest + in_flat_repair | 0 | 5 | Debye handled the wasp nest first, waited for consent before addressing the loose tile, and followed up on both problems appropriately. |
| ✓ tb32_hot_water_and_lift | lift → lift | lift_out_of_service | lift_out_of_service + shower_knob_or_limiter | 2 | 5 | Debye handled the lift first, then resolved the shower issue with appropriate self-help. |
| ✓ tb33_bins_and_parking_de | other → other | shared_area_repair | shared_area_repair + other_request | 0 | 5 | Debye handles the broken bins first, then routes the parking question to management without promising a space. |
| ✓ tb34_ceiling_leak_and_rent | roof_ceiling_leak → roof_ceiling_leak | ceiling_leak_lower_floor | ceiling_leak_lower_floor + rent_question | 1 | 5 | Debye handled the leak first with one relevant question, then routed the rent question to the property manager without making a prohibited promise. |

## Transcripts of the failed conversations

<details><summary>✗ ta07_under_sink_dont_know: Pipe under the bathroom sink drips, tenant not at home</summary>

- **tenant**: my flatmate says the pipe under our bathroom sink is dripping
- **debye**: A connection under the sink is leaking, so a plumber needs to replace it. Keep the small valve closed if you can and put a bowl underneath.
- **debye**: I'd like to send Sanitär Esser GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]
- **tenant**: yes thats fine
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ['insist the tenant checks the valve now']_

</details>

<details><summary>✗ ta12_main_stack_contradiction: Sink blocked, tenant says no backup then describes one</summary>

- **tenant**: Bathroom sink drains really slowly. I already used a plunger, didn't help.
- **debye**: Got it. Does dirty water come up in another drain, for example in the shower when you flush?  [Yes | No, only this one]
- **tenant**: No, only the sink. Although when I flush, dirty water comes up in the shower.
- **debye**: If water comes up in another drain, the building's main pipe is blocked. Please use as little water as possible; a drain cleaning service is needed urgently.
- **debye**: I'd like to send Rohr-Frei Aachen over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]
- **tenant**: yes, every time
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ["conclude a simple blocked sink after the first 'no'"]_

</details>

<details><summary>✗ ta32_washing_machine_frustrated: Washing machine won't spin, tenant wants someone sent</summary>

- **tenant**: washing machine won't spin, the lights are on and it just beeps
- **debye**: Let's check. Did the appliance come with the flat, or is it your own?  [Came with the flat | It's my own]
- **tenant**: It came with the flat
- **debye**: Then the appliance itself needs a repair, so I'll get an appliance technician. Please don't open it or take it apart.
- **debye**: I'd like to send Hausgeräte-Service Meyer over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]
- **tenant**: yes
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ["ask another diagnostic question after 'just send someone'"]_

</details>

<details><summary>✗ tb12_outside_wall_off_topic: Wet patch on the outside wall when it rains, off-topic reply</summary>

- **tenant**: when it rains, a wet patch shows up on my living room wall
- **debye**: Rain coming through an outside wall points to the facade or a gutter, so a roofer needs to check the outside. Photos of the wet spot help.
- **debye**: I'd like to send Dachdeckerei Lambertz over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]
- **tenant**: yes
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ['treat the weather remark as an answer']_

</details>

<details><summary>✗ tb17_lift_not_coming_question_back: Lift not moving, no sign, tenant asks how long</summary>

- **tenant**: the lift hasn't come for 20 minutes, it's not moving at all
- **debye**: Got it. Is there a sign or notice at the lift, for example about maintenance?  [Yes, a sign | No sign]
- **tenant**: no, no sign anywhere
- **debye**: Then the lift company needs to come. If you or a neighbour can't manage the stairs, tell me and the property manager will help in the meantime.
- **debye**: I'd like to send Aufzugsdienst Rhein over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]
- **tenant**: how long will that take? I'm on the 6th floor
- **debye**: The lift company will confirm the timing. I’ll keep you updated.

_judge:  ['skip the consent question']_

</details>

<details><summary>✗ tb23_neighbour_problem_asked: Problem with a neighbour, one question splits it</summary>

- **tenant**: I have a problem with my neighbour
- **debye**: Thanks for telling me. I've passed it to your property manager, who will get in touch with you and, if needed, with the neighbour.

_judge:  ['ask a second question']_

</details>

<details><summary>✗ tb27_smoke_alarm_loud_no_smoke: Smoke alarm sounding continuously, no smoke seen</summary>

- **tenant**: my smoke alarm is going off and won't stop
- **debye**: A loud continuous alarm means it detects smoke. If you see or smell smoke, leave the flat now, close the door and call 112. If there's clearly no smoke, open a window; I've alerted your property manager.

_judge: Debye asserted a loud continuous alarm and that it had alerted the property manager, neither of which the tenant said or building data established. ["send the fire safety message before asking ('smoke alarm' alone is not a fire)"]_

</details>

