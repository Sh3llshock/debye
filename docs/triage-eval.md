# Triage eval: 66 gold conversations, 1 pass(es)

`scripts/eval_triage.py` runs every conversation in `data/diagnosis/triage_gold_a.json` and `triage_gold_b.json` end to end: the real app on a temp database, Luna as Debye, a simulated tenant (same model) that answers only from the conversation's `tenant_facts` and follows the gold tenant turns, and a judge (same model). A conversation passes when the routed area, the cause, the outcome and the question limit match (for two problems: both), and the judge finds no invented fact, no missed clarification, the edge case handled, tone at least 4/5 and no `must_not` broken.

| | result |
|---|---|
| passed | **60/66 (91%)** |
| area routed right | 66/66 (100%) |
| cause | 66/66 (100%) |
| outcome | 66/66 |
| within the question limit | 66/66 (avg 0.65) |
| no invented facts | 65/66 |
| tone | 4.79/5 |
| must_not clean | 62/66 |
| avg turn | 4.8 s |

## Before / after, planner off / on (Luna as Debye, 1 pass each)

| run | passed | area | cause | outcome | no invented facts | tone | avg first turn |
|---|---|---|---|---|---|---|---|
| before the fixes (PR draft) | 59/66 (89%) | 66/66 | 66/66 | 66/66 | 65/66 | 4.79 | 2.7 s* |
| after the fixes, planner off (**default**) | **60/66 (91%)** | 66/66 | 66/66 | 66/66 | 65–66/66 | 4.79–4.85 | 3.7 s |
| after the fixes, planner on (gpt-6-sol) | 53/66 (80%) | 66/66 | 66/66 | 66/66 | 66/66 | 4.09 | 5.9 s |

\* average over all turns. The planner (`PLANNER_ENABLED=1`) sends "Let me look into it, one moment." and asks
gpt-6-sol for the area, the likeliest causes and 1–3 questions; Luna follows the plan. It routed every area right
but scored lower on tone and edge cases (the judge reads the holding message and plan-driven questions as extra
steps) and added ~2 s to the first reply, so it stays **off** by default.

Hot water stays as on main: `scripts/smoke_diagnosis.py` 15/15; the 40-gold hot-water eval 29/40 on this
branch vs 28/40 on origin/main in the same session (cause 36/40 on both). `scripts/smoke_triage.py`: 12/12
real-world openers, first reply 1.6–6.7 s.

## By area

| area | passed | cause |
|---|---|---|
| appliances | 4/4 | 4/4 |
| blocked_drain | 4/5 | 5/5 |
| electrics | 7/7 | 7/7 |
| intercom | 3/4 | 4/4 |
| lift | 4/5 | 5/5 |
| management | 4/4 | 4/4 |
| mold_damp | 2/3 | 3/3 |
| other | 7/7 | 7/7 |
| pests | 6/6 | 6/6 |
| roof_ceiling_leak | 5/5 | 5/5 |
| water_leak | 6/8 | 8/8 |
| windows_doors | 8/8 | 8/8 |

## By tag

| tag | passed |
|---|---|
| decisive_first | 25/27 |
| self_help_fails | 9/10 |
| self_help_works | 9/9 |
| german | 8/8 |
| emergency | 7/7 |
| two_problems | 5/5 |
| photo | 3/4 |
| clean | 4/4 |
| typos | 3/3 |
| burst | 2/3 |
| off_topic | 3/3 |
| vague_area | 3/3 |
| vague | 2/2 |
| dont_know | 1/2 |
| question_back | 0/2 |
| smoke_alarm | 2/2 |
| contradiction | 1/1 |
| frustrated | 1/1 |
| ceiling_not_flooding | 1/1 |
| hot_water_second | 1/1 |

## Conversations

| id | area (expected → routed) | expected cause | got | q | tone | notes |
|---|---|---|---|---|---|---|
| ✓ ta01_burst_pipe_flooding | water_leak → water_leak | major_leak_flooding | major_leak_flooding | 0 | 5 | Debye gives the safety steps immediately without asking a question or promising an arrival time. |
| ✓ ta02_tap_not_closed_typos | water_leak → water_leak | tap_not_fully_closed | tap_not_fully_closed | 1 | 5 | Debye correctly clarified the drip, gave the simple self-help step, and closed the issue after it stopped. |
| ✓ ta03_tap_washer_after_tip | water_leak → water_leak | dripping_tap_washer | dripping_tap_washer | 1 | 5 | Debye gives a low-cost self-help check, then routes the recurring drip to the caretaker without closing the case or suggesting a plumber or washer replacement. |
| ✓ ta04_toilet_running_de | water_leak → water_leak | toilet_running | toilet_running | 0 | 5 | Debye answers in German, identifies the reported toilet issue, and gives the caretaker route and shutoff advice without violating the listed rules. |
| ✓ ta05_toilet_floor_photo_vague | water_leak → water_leak | toilet_leak_floor | toilet_leak_floor | 1 | 5 | Debye clarified the ambiguous answer, then correctly acted on the photos and included them in the consent question. |
| ✓ ta06_washing_machine_hose_fails | water_leak → water_leak | wall_valve_leak | wall_valve_leak | 0 | 5 | Debye correctly identified a likely wall-valve or pipe leak, advised containing the water, and asked consent to share the relevant details. |
| ✗ ta07_under_sink_dont_know | water_leak → water_leak | under_sink_leak | under_sink_leak | 0 | 2 | Debye correctly avoids asking the tenant to check the valve at work, but invents their name and awkwardly repeats the consent prompt rather than acknowledging it can be answered later. |
| ✗ ta08_radiator_valve_burst | water_leak → water_leak | radiator_valve_leak | radiator_valve_leak | 0 | 3 | Debye handled the burst and repair correctly, but added an unnecessary leak-severity question and conditional emergency advice after the repair consent request. |
| ✓ ta09_shower_hair_off_topic | blocked_drain → blocked_drain | shower_hair_clog | shower_hair_clog | 1 | 5 | Debye correctly treated “lol ok” as not answering the question, gave self-help, and closed after the tenant reported it worked. |
| ✓ ta10_kitchen_sink_de | blocked_drain → blocked_drain | sink_trap_clog | sink_trap_clog | 1 | 5 | Debye gives suitable self-help in German and closes naturally after the tenant says it worked. |
| ✓ ta11_toilet_clog_plunger_fails | blocked_drain → blocked_drain | stubborn_blockage | stubborn_blockage | 2 | 5 | Debye tried a low-cost fix, checked for a wider blockage, and arranged drain cleaning without closing the case or recommending chemicals. |
| ✓ ta12_main_stack_contradiction | blocked_drain → blocked_drain | main_stack_blockage | main_stack_blockage | 1 | 5 | Debye clarified the tenant’s contradictory answer before concluding a main-pipe blockage and arranging urgent service. |
| ✗ ta13_several_drains_question_back | blocked_drain → blocked_drain | several_drains_blocked | several_drains_blocked | 0 | 3 | Debye did not answer the cost question as the gold does, and repeated the consent request without acknowledging the tenant’s earlier consent. |
| ✓ ta14_burning_smell_socket | electrics → electrics | electrical_burning | electrical_burning | 0 | 5 | Debye gives the safety steps immediately and does not ask a question or tell the tenant to inspect the socket. |
| ✓ ta15_building_blackout | electrics → electrics | building_power_outage | building_power_outage | 0 | 5 | Debye gives immediate, appropriate safety steps for a whole-building outage and alerts the property manager without asking unnecessary questions. |
| ✓ ta16_kitchen_breaker_burst | electrics → electrics | tripped_breaker | tripped_breaker | 1 | 5 | Debye handled the burst as one issue, gave the self-help steps, and closed after the tenant confirmed it worked. |
| ✓ ta17_hall_light_bulb_de | electrics → electrics | bulb_blown | bulb_blown | 1 | 5 | Debye gave sensible bulb-replacement self-help and closed the issue after it worked, in concise German. |
| ✓ ta18_bathroom_light_fitting | electrics → electrics | light_fitting_fault | light_fitting_fault | 1 | 5 | Debye gives the cheap bulb check, then routes the failed fix to the caretaker as intended. |
| ✓ ta19_socket_fault_photo | electrics → electrics | socket_or_circuit_fault | socket_or_circuit_fault | 1 | 5 | Debye correctly diagnosed the likely socket or wiring fault, included the photos in the consent question, and arranged an electrician. |
| ✓ ta20_flat_supply_vague | electrics → electrics | flat_supply_fault | flat_supply_fault | 2 | 5 | Debye clarified the vague answer, then followed the fuse-check path and routed the issue to the caretaker. |
| ✓ ta21_break_in | windows_doors → windows_doors | break_in | break_in | 0 | 5 | Debye gives the safety steps immediately, asks no diagnostic question, and follows the intended emergency response. |
| ✓ ta22_locked_out_typos | windows_doors → windows_doors | locked_out | locked_out | 0 | 5 | Debye correctly handles the lockout, states the usual cost responsibility, and asks for consent to share the tenant’s details. |
| ✓ ta23_broken_glass_photo_burst | windows_doors → windows_doors | broken_glass | broken_glass | 0 | 5 | Debye handled the cracked glass and included the photos in the consent question before arranging the repair. |
| ✓ ta24_window_tilt_fails | windows_doors → windows_doors | window_wont_close | window_wont_close | 1 | 5 | Debye clarifies the window position, offers a self-help tip, and arranges the caretaker when it fails. |
| ✓ ta25_window_handle_de | windows_doors → windows_doors | window_handle_hinge | window_handle_hinge | 0 | 5 | Debye responds in German, correctly routes the broken handle to the caretaker, and asks no unnecessary questions. |
| ✓ ta26_building_door_wont_close | windows_doors → windows_doors | building_door_fault | building_door_fault | 0 | 5 | Debye correctly routes the reported entrance-door fault to the caretaker without asking an unnecessary question. |
| ✓ ta27_flat_door_lock_off_topic | windows_doors → windows_doors | flat_door_lock_broken | flat_door_lock_broken | 1 | 5 | Debye appropriately repeated the door-type question after the off-topic reply and handled the flat-door lock without violating any listed rule. |
| ✓ ta28_draughty_window | windows_doors → windows_doors | draughty_window | draughty_window | 0 | 5 | Debye correctly identifies the draught and routes it to the caretaker without asking unnecessary questions. |
| ✓ ta29_own_fridge_management | appliances → appliances | own_appliance | own_appliance | 1 | 5 | Debye correctly identifies the fridge as the tenant’s own and recommends contacting the manufacturer or a repair shop. |
| ✓ ta30_dishwasher_fuse_works | appliances → appliances | appliance_tripped_fuse | appliance_tripped_fuse | 2 | 5 | Debye gave the fuse-box self-help and closed the issue after the tenant confirmed the dishwasher worked again. |
| ✓ ta31_oven_fuse_fails | appliances → appliances | appliance_no_power | appliance_no_power | 2 | 5 | Debye followed the troubleshooting sequence, routed the failed self-help to an electrician, and sought consent before sharing details. |
| ✓ ta32_washing_machine_frustrated | appliances → appliances | appliance_fault | appliance_fault | 1 | 4 | Debye correctly identified the appliance repair and arranged a technician without asking another diagnostic question or arguing with the tenant. |
| ✓ tb01_bedroom_mould_dry_de | mold_damp → mold_damp | condensation_mould | condensation_mould | 0 | 4 | Debye gave appropriate self-help advice in German and closed the issue after the tenant said the spots were gone. |
| ✓ tb02_mould_back_after_cleaning | mold_damp → mold_damp | large_mould | large_mould | 2 | 5 | Debye correctly escalates the larger returning mould to a specialist and does not close the case or ask further diagnostic questions. |
| ✗ tb03_wet_wall_photo | mold_damp → mold_damp | damp_ingress | damp_ingress | 1 | 5 | Debye handled the wet wall appropriately, but the consent question omitted the floor from the requested details. |
| ✓ tb04_mouse_droppings | pests → pests | rodents | rodents | 0 | 5 | Debye recommends pest control without unnecessary questions, requests consent, and follows up as intended. |
| ✓ tb05_cockroaches_typos | pests → pests | cockroaches | cockroaches | 0 | 5 | Debye handled the cockroach report directly, avoided correcting the typos or recommending spray, and the tenant consented to the referral. |
| ✓ tb06_ants_few_works | pests → pests | ants_minor | ants_minor | 1 | 5 | Debye gave appropriate self-help and closed the issue after the tenant said the ants were gone. |
| ✓ tb07_ants_come_back_infestation | pests → pests | pest_infestation | pest_infestation | 1 | 5 | Debye gave a self-help tip, then escalated when it failed; it did not close the case or repeat the tip. |
| ✓ tb08_bites_vague_area | pests → pests | bedbugs | bedbugs | 0 | 5 | Debye asks what the vague report is about, then gives suitable bedbug advice and seeks consent to share the tenant’s details. |
| ✓ tb09_top_floor_rain_drip | roof_ceiling_leak → roof_ceiling_leak | roof_leak | roof_leak | 1 | 5 | Debye sensibly confirmed the floor, gave appropriate steps, and arranged a roofer without asking whether it happens in rain or treating it as an emergency. |
| ✓ tb10_ceiling_pouring_dry_day | roof_ceiling_leak → roof_ceiling_leak | neighbour_above_leak | neighbour_above_leak | 1 | 5 | Debye sensibly checked whether the leak occurs in dry weather, then gave the expected next steps without violating any listed rule. |
| ✓ tb11_window_frame_rain | roof_ceiling_leak → roof_ceiling_leak | window_frame_leak | window_frame_leak | 0 | 5 | Debye correctly identified a window-frame leak, offered a temporary measure, and arranged the technician without asking an unnecessary question. |
| ✓ tb12_outside_wall_off_topic | roof_ceiling_leak → roof_ceiling_leak | facade_leak | facade_leak | 2 | 4 | Debye clarified the leak location and routed it to a roofer; the tenant’s uncertainty was handled without guessing. |
| ✗ tb13_doorbell_muted_fails | intercom → intercom | flat_handset_fault | flat_handset_fault | 2 | 4 | Debye repeats the already answered neighbour question after the tenant gave that information in the burst. |
| ✓ tb14_doorbell_volume_dont_know | intercom → intercom | bell_muted | bell_muted | 1 | 4 | Debye correctly suggested checking the volume and handled the fix; closing the issue instead of inviting the tenant to message if it stops again is acceptable. |
| ✓ tb15_whole_building_intercom | intercom → intercom | building_intercom_fault | building_intercom_fault | 0 | 5 | Debye correctly treats the neighbour’s report as evidence of a building-wide fault and routes a technician without asking a redundant question. |
| ✓ tb16_neighbour_stuck_in_lift | lift → lift | person_trapped | person_trapped | 0 | 5 | Debye gave the lift safety steps immediately and did not ask a diagnostic question. |
| ✗ tb17_lift_not_coming_question_back | lift → lift | lift_out_of_service | lift_out_of_service | 1 | 5 | Debye handled the lift report and asked for consent, but missed the tenant’s question about how long the repair would take. |
| ✓ tb18_maintenance_sign_still_down | lift → lift | lift_out_of_service | lift_out_of_service | 1 | 5 | Debye followed up after the maintenance deadline, arranged a repair, and did not repeat the sign question or tell the tenant to keep waiting. |
| ✓ tb19_lift_jerks_vague_area | lift → lift | lift_fault_minor | lift_fault_minor | 0 | 5 | Debye correctly clarified the vague report, handled the lift issue, and did not ask whether it moves or claim it is safe to use. |
| ✓ tb20_utility_bill_de | management → management | rent_question | rent_question | 0 | 5 | Debye routes the bill question to the house manager in German, matching the gold response. |
| ✓ tb21_loud_music_nightly | management → management | noise_complaint | noise_complaint | 0 | 5 | Debye handled the clear noise complaint directly, without making a prohibited promise or telling the tenant to confront the neighbours. |
| ✓ tb22_notice_period | management → management | contract_question | contract_question | 0 | 5 | Debye correctly routes the clear contract question to the property manager without stating a notice period. |
| ✓ tb23_neighbour_problem_asked | management → management | neighbour_dispute | neighbour_dispute | 1 | 5 | Debye asks one useful question to identify the issue and routes it without taking sides or promising to warn the neighbour. |
| ✓ tb24_smoke_from_flat_below | other → other | fire_smoke | fire_smoke | 0 | 5 | Debye gives the emergency safety steps immediately without asking a question. |
| ✓ tb25_co_alarm | other → other | co_alarm | co_alarm | 0 | 5 | Debye gives the emergency safety steps immediately and does not ask a question. |
| ✓ tb26_smoke_alarm_short_beeps | other → other | smoke_alarm_battery | smoke_alarm_battery | 1 | 5 | Debye clarified the alarm pattern and correctly identified the low-battery issue without treating it as a fire or suggesting removal. |
| ✓ tb27_smoke_alarm_loud_no_smoke | other → other | smoke_alarm_sounding | smoke_alarm_sounding | 1 | 5 | Debye clarified the alarm type before giving safety guidance and did not treat it as a low battery or suggest removing it. |
| ✓ tb28_loose_tile_de_vague_area | other → other | in_flat_repair | in_flat_repair | 0 | 4 | Debye asks what the problem is, then gives the appropriate repair response in German without guessing an area or asking whether it is urgent. |
| ✓ tb29_balcony_railing_urgent | other → other | in_flat_urgent | in_flat_urgent | 1 | 5 | Debye appropriately checked urgency, then gave the caretaker response once the tenant said it was dangerous. |
| ✓ tb30_buzzer_and_mould | intercom → intercom | door_opener_fault | door_opener_fault + large_mould | 0 | 5 | Debye handles the buzzer first, then the mould, and asks the needed clarifying question before recommending treatment. |
| ✓ tb31_wasps_and_loose_tile | pests → pests | wasps_nest | wasps_nest + in_flat_repair | 0 | 5 | Debye handled the wasp nest first, obtained consent before addressing the loose tile, and then routed the repair appropriately. |
| ✓ tb32_hot_water_and_lift | lift → lift | lift_out_of_service | lift_out_of_service + shower_knob_or_limiter | 2 | 5 | Debye handled the lift first, then resolved the hot-water issue with a self-help step; the shorter consent request and closing are fine. |
| ✓ tb33_bins_and_parking_de | other → other | shared_area_repair | shared_area_repair + other_request | 0 | 5 | Debye handles the broken bins first, then routes the parking question to management without promising a parking space. |
| ✓ tb34_ceiling_leak_and_rent | roof_ceiling_leak → roof_ceiling_leak | ceiling_leak_lower_floor | ceiling_leak_lower_floor + rent_question | 1 | 4 | Debye handled the leak before the rent question and routed both correctly; the final message is a harmless repetition. |

## Transcripts of the failed conversations

<details><summary>✗ ta07_under_sink_dont_know: Pipe under the bathroom sink drips, tenant not at home</summary>

- **tenant**: my flatmate says the pipe under our bathroom sink is dripping
- **debye**: A connection under the sink is leaking, so a plumber needs to replace it. Keep the small valve closed if you can and put a bowl underneath.
- **debye**: I'd like to send Sanitär Esser GmbH over. Is it okay if I share your name, phone number and address with them?  [Yes, go ahead | No]
- **tenant**: can't check, I'm at work until 6
- **debye**: No problem, Jonas. The consent question is still there for when you’re able to check.

_judge: Debye says the tenant is named Jonas, which was not provided or listed as building data. []_

</details>

<details><summary>✗ ta08_radiator_valve_burst: Radiator valve leaking, several messages at once</summary>

- **tenant**: hi
- **tenant**: there's a small puddle of water under the radiator in the living room
- **tenant**: it's dripping from the valve thing on the side
- **debye**: A leaking radiator valve needs a heating technician. Put a towel and a bowl under it; please don't open or loosen anything on the radiator.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number and address with them? They only get the access details (key safe, intercom) on the day of the visit.  [Yes, go ahead | No]
- **debye**: Aylin, is water actively leaking from it, or just a few drops?
- **debye**: If water is flooding, turn off the main water tap and call 112.

</details>

<details><summary>✗ ta13_several_drains_question_back: Kitchen sink and shower blocked, tenant asks about cost</summary>

- **tenant**: the kitchen sink and the shower are both blocked since this morning
- **debye**: When several drains block at once, the shared pipe is usually the problem, so a drain cleaning service needs to come. Please use as little water as possible until then.
- **debye**: I'd like to send Rohr-Frei Aachen over. Is it okay if I share your name, phone number and address with them?  [Yes, go ahead | No]
- **tenant**: will I have to pay for this?
- **debye**: The property manager can confirm any costs. Do you consent to the repair visit?
- **debye**: I'd like to send Rohr-Frei Aachen over. Is it okay if I share your name, phone number and address with them?  [Yes, go ahead | No]

_judge:  ['say the tenant has to pay', 'promise a date or a cost']_

</details>

<details><summary>✗ tb03_wet_wall_photo: Mould behind the sofa, photo shows a wet wall</summary>

- **tenant**: there's mould on the living room wall behind the sofa
- **debye**: Let's fix it. Is the wall wet to the touch or does it have water stains, or is it dry with just spots?  [Wet / stains | Dry, just spots]
- **tenant**: [photo] it feels wet and there's a brown water stain above it
- **tenant**: [photo] 
- **debye**: A wet wall means water is getting in from somewhere, so a damp specialist needs to measure it and find the source. Please don't paint over it; photos of it help.
- **debye**: I'd like to send Trocknungstechnik Aachen over. Is it okay if I share your name, phone number, address and the photos with them?  [Yes, go ahead | No]
- **tenant**: yes go ahead
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ['leave out the photos in the consent question']_

</details>

<details><summary>✗ tb13_doorbell_muted_fails: Doorbell silent, mute switch was off, still silent</summary>

- **tenant**: my doorbell doesn't ring anymore, the courier left a note again
- **debye**: Let's check. Many handsets have a small volume or mute switch on the side or bottom. Is it turned off or down?  [It was off | It's on / none]
- **tenant**: found a little switch on the side, it was off, it's on now
- **debye**: Then it was just muted. Leave it on and tell me if the bell still doesn't ring next time someone comes.
- **tenant**: a friend just tried it, it still doesn't ring
- **tenant**: no, my neighbour's works fine
- **debye**: Thanks for checking. Do your neighbours have the same problem?  [Yes, them too | No, only me]
- **tenant**: no, my neighbour's works fine
- **debye**: If it's only your flat, the handset or its wiring is faulty, so an electrician needs to replace or repair it.
- **debye**: I'd like to send Elektro Klein GmbH over. Is it okay if I share your name, phone number and address with them?  [Yes, go ahead | No]
- **tenant**: yes
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ["ask what isn't working (already given)"]_

</details>

<details><summary>✗ tb17_lift_not_coming_question_back: Lift not moving, no sign, tenant asks how long</summary>

- **tenant**: the lift hasn't come for 20 minutes, it's not moving at all
- **debye**: Got it. Is there a sign or notice at the lift, for example about maintenance?  [Yes, a sign | No sign]
- **tenant**: no, no sign anywhere
- **debye**: Then the lift company needs to come. If you or a neighbour can't manage the stairs, tell me and the property manager will help in the meantime.
- **debye**: I'd like to send Aufzugsdienst Rhein over. Is it okay if I share your name, phone number and address with them?  [Yes, go ahead | No]
- **tenant**: yes, go ahead
- **debye**: Thanks. Your property manager is confirming the repair, I'll update you shortly.

_judge:  ['skip the consent question']_

</details>

