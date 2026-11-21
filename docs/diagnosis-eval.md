# Diagnosis eval: 40 gold conversations

`scripts/eval_diagnosis.py`. For each conversation in `data/diagnosis/gold_conversations.json`, Luna (gpt-6-luna) plays Debye through the real router and agent (fake WhatsApp send, fresh state). A simulated tenant (same model) answers only from the conversation's `tenant_facts` and follows the gold tenant turns (bursts are sent concurrently with the 2.5 s-style debounce, photos as real image messages). A judge (same model) checks invented facts, clarification, the edge case, tone and the `must_not` rules; code checks the cause, the outcome and the number of diagnostic questions. A conversation passes only if every check passes.

**Before** = `main` before this PR (KB v1, old prompt), 3 passes. **After** = this PR, 3 passes. Numbers are pooled over all passes (40 conversations per pass).

Per pass, right cause (after): 36/40, 34/40, 36/40; before: 28/40, 24/40, 28/40.

| | Before | After |
|---|---|---|
| Passed (all checks) | 24/120 (20%) | 78/120 (65%) |
| Right cause | 80/120 (67%) | 106/120 (88%) |
| Right cause, diverter ≈ tank | 84/120 (70%) | 112/120 (93%) |
| Right outcome | 90/120 | 113/120 |
| ≤ 3 diagnostic questions | 120/120 | 120/120 |
| Average diagnostic questions | 2.02 | 1.96 |
| No invented facts | 92/120 | 112/120 |
| Clarified when needed | 104/120 | 114/120 |
| Edge case handled | 44/96 | 68/99 |
| must_not rules kept | 44/120 | 86/120 |
| Tone (judge, 1-5) | 2.96 | 4.1 |
| Average turn time | 4.2 s | 3.1 s |

## Per conversation

Before/After columns show pass 1; 'Cause hits' counts the right cause over all after passes.

| Conversation | Expected | Before | After | Cause hits | Q (after) | Tone (after) | Judge note (after) |
|---|---|---|---|---|---|---|---|
| g01_hot_water_used_up | hot_water_used_up | ✗ hot_water_used_up | ✓ hot_water_used_up | 3/3 | 2 | 5 | Debye sensibly checked whether the problem affected other taps, identified the long shower as the likely cause, and gave brief self-help advice without violating any listed rule. |
| g02_simultaneous_use | simultaneous_use | ✗ simultaneous_use | ✓ simultaneous_use | 3/3 | 2 | 5 | Debye gave a relevant self-help tip and closed the resolved issue without asking more questions. |
| g03_switched_off_or_valve_closed | switched_off_or_valve_closed | ✗ diverter_valve_stuck | ✓ switched_off_or_valve_closed | 3/3 | 1 | 5 | Debye gave a concise, relevant check and sensible next step after the tenant reopened the valve. |
| g04_not_run_long_enough | not_run_long_enough | ✗ not_run_long_enough | ✓ not_run_long_enough | 2/3 | 3 | 5 | Debye sensibly checks the shower scope, handles the 20-second run with a low-cost self-help step, and closes after the tenant confirms it worked. |
| g05_shower_knob_or_limiter | shower_knob_or_limiter | ✗ shower_knob_or_limiter | ✓ shower_knob_or_limiter | 3/3 | 1 | 5 | Debye gave appropriate self-help for the 38°C stop and accepted the tenant’s confirmation that it worked. |
| g06_boiler_fault | boiler_fault | ✓ boiler_fault | ✗ boiler_fault | 3/3 | 2 | 3 | Debye asks an unnecessary question about the gas stove after the error code already identifies the boiler fault, and does not handle the tenant’s consent reply before asking again. |
| g07_low_system_pressure | low_system_pressure | ✓ low_system_pressure | ✓ low_system_pressure | 3/3 | 2 | 4 | Debye correctly identified low pressure, asked a relevant gauge question, and arranged the caretaker without asking the tenant to top it up or sending a technician. |
| g08_supply_valve_closed_after_work | supply_valve_closed_after_work | ✗ supply_valve_closed_after_work | ✓ supply_valve_closed_after_work | 3/3 | 0 | 4 | Debye correctly inferred a likely closed valve from the plumbing work and asked for consent to arrange a plumber. |
| g09_frozen_or_damaged_pipe | frozen_or_damaged_pipe | ✗ shower_mixer_faulty | ✓ frozen_or_damaged_pipe | 3/3 | 3 | 5 | Debye handled the cold, weak shower flow appropriately, warned against using an open flame, and asked for consent to share details with the plumber. |
| g10_shower_mixer_faulty | shower_mixer_faulty | ✗ shower_mixer_faulty | ✓ shower_mixer_faulty | 3/3 | 3 | 5 | Debye asks three sensible diagnostic questions, avoids repeating the sink question, and correctly suggests a plumber and asks for consent. |
| g11_boiler_schedule_or_settings | boiler_schedule_or_settings | ✗ circulation_pump_faulty | ✓ boiler_schedule_or_settings | 3/3 | 3 | 5 | Debye follows the intended diagnostic sequence and routes the issue to the caretaker without violating any listed rule. |
| g12_tank_thermostat_or_scale | tank_thermostat_or_scale | ✓ tank_thermostat_or_scale | ✓ tank_thermostat_or_scale | 3/3 | 3 | 5 | Debye asked three sensible diagnostic questions, then recommended a technician and requested consent to share the tenant’s details. |
| g13_diverter_valve_stuck | diverter_valve_stuck | ✗ tank_thermostat_or_scale | ✗ tank_thermostat_or_scale | 0/3 | 2 | 4 | Debye handles the initial answer and keeps the diagnosis concise, but gives the wrong likely cause instead of identifying a possibly stuck switch between heating and hot water. |
| g14_circulation_pump_faulty | circulation_pump_faulty | ✗ circulation_pump_faulty | ✓ circulation_pump_faulty | 3/3 | 3 | 5 | Debye asked three sensible diagnostic questions and correctly identified the likely pump issue before asking for consent to contact the technician. |
| g15_no_power_to_boiler | no_power_to_boiler | ✓ no_power_to_boiler | ✓ no_power_to_boiler | 3/3 | 2 | 5 | Debye correctly inferred a power issue from the dark boiler display and hallway lights, and gave the intended caretaker-first plan. |
| g16_electric_instant_heater | electric_instant_heater | ✗ electric_instant_heater | ✓ electric_instant_heater | 3/3 | 1 | 4 | Debye used the known heater type, gave a sensible check, and asked for consent to share details with the partner; it did not claim a visit was approved or booked. |
| g17_planned_maintenance | planned_maintenance | ✗ planned_maintenance | ✓ planned_maintenance | 3/3 | 0 | 5 | Debye correctly cited planned maintenance and avoided diagnostic questions or technician promises, though the reply is less specific than the gold. |
| g18_gas_supply_interrupted | gas_supply_interrupted | ✗ not_run_long_enough | ✓ gas_supply_interrupted | 3/3 | 2 | 5 | Debye correctly identified the likely gas-supply interruption and gave the expected update without violating any listed rule. |
| g19_ambiguous_everything | simultaneous_use | ✓ simultaneous_use | ✓ simultaneous_use | 3/3 | 1 | 5 | Debye clarified “everything,” then gave a brief self-help step and closed after the tenant said it worked. |
| g20_multi_fact_first_message | shower_mixer_faulty | ✗ shower_mixer_faulty | ✓ shower_mixer_faulty | 3/3 | 2 | 4 | Debye correctly used the information already given, asked sensible diagnostic questions, and sought consent to arrange a plumber. |
| g21_switched_off_resolved | switched_off_or_valve_closed | ✗ electric_instant_heater | ✓ switched_off_or_valve_closed | 3/3 | 1 | 5 | Debye offered a brief self-help check, confirmed the water was hot again, and did not ask further diagnostic questions. |
| g22_self_help_fails | tank_thermostat_or_scale | ✗ not_run_long_enough | ✗ tank_thermostat_or_scale | 3/3 | 3 | 4 | Debye asked the radiator question after the failed self-help tip and then recommended a technician, so it asked a fourth diagnostic question and closed the case. |
| g23_german_tenant | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 2/3 | 2 | 2 | Debye correctly identifies the F.28 fault and requests consent for a technician, but switches to English and uses formal “Sie” instead of informal “du”. |
| g24_voice_note_rambling | tank_thermostat_or_scale | ✗ tank_thermostat_or_scale | ✓ tank_thermostat_or_scale | 3/3 | 1 | 4 | Debye correctly handled the multi-fact message, asked for the display photo, and gave the likely cause and technician next step. |
| g25_photo_f28 | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 2/3 | 1 | 3 | Debye handled the burst in one reply but gave the error code after its meaning, then asked an unnecessary gas-stove question and repeated the boiler-fault diagnosis. |
| g26_central_heating_duplicate | boiler_fault | ✓ boiler_fault | ✓ boiler_fault | 3/3 | 0 | 4 | Debye correctly reports the building-wide issue and technician involvement without asking diagnostic questions or identifying the neighbour. |
| g27_gas_mention_mid_diagnosis | gas_smell | ✓ gas_smell | ✓ gas_smell | 3/3 | 1 | 5 | Debye gave the gas-safety instructions immediately and asked no further diagnostic questions. |
| g28_message_burst | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 3/3 | 3 | 3 | Debye repeatedly pursued the shower-versus-sinks question, then guessed simultaneous use instead of clarifying what “everything” meant. |
| g29_answers_different_question | diverter_valve_stuck | ✗ tank_thermostat_or_scale | ✗ tank_thermostat_or_scale | 0/3 | 3 | 4 | Debye correctly treats the radiator reply as an answer about the radiators and proceeds to technician consent, but it gives an unsupported diagnosis and does not ask the gold’s follow-up about hot-water use after the radiator answer. |
| g30_two_answers_at_once | frozen_or_damaged_pipe | ✗ shower_mixer_faulty | ✓ frozen_or_damaged_pipe | 3/3 | 2 | 5 | Debye handled the tenant’s combined answers without repeating the recent-work question and correctly recommended a plumber without suggesting heating the pipe. |
| g31_tenant_corrects_themselves | shower_knob_or_limiter | ✗ shower_knob_or_limiter | ✓ shower_knob_or_limiter | 3/3 | 3 | 4 | Debye followed the correction, offered the right self-help, and closed after the tenant confirmed it worked. |
| g32_off_topic_mid_diagnosis | circulation_pump_faulty | ✗ circulation_pump_faulty | ✗ circulation_pump_faulty | 3/3 | 3 | 4 | Debye ignored the tenant’s thanks but continued with diagnosis instead of acknowledging it and keeping the existing question open; the diagnosis and outcome were otherwise appropriate. |
| g33_hello_after_delay | hot_water_used_up | ✗ hot_water_used_up | ✗ boiler_fault | 2/3 | 3 | 3 | After the tenant said her son had a long shower, Debye should have treated the repeated question as answered and suggested waiting for the tank to reheat, rather than repeating the knob question and arranging a technician. |
| g34_dont_know_cant_check | boiler_fault | ✗ boiler_fault | ✓ boiler_fault | 3/3 | 3 | 4 | Debye reached the correct boiler-fault conclusion and technician outcome without exceeding the diagnostic-question limit or violating a listed rule. |
| g35_question_back | electric_instant_heater | ✗ boiler_schedule_or_settings | ✗ electric_instant_heater | 3/3 | 3 | 2 | Debye answered the safety and payment questions briefly but repeatedly ignored the tenant’s questions to resume its diagnostic prompt, and kept repeating the same self-help step after the tenant said they had not tried it. |
| g36_works_again_by_itself | not_run_long_enough | ✓ not_run_long_enough | ✗ shower_mixer_faulty | 1/3 | 3 | 3 | Debye escalated to a technician instead of first suggesting the cheap hot-tap test, and did not check whether the issue had resolved. |
| g37_language_switch | shower_knob_or_limiter | ✗ not_run_long_enough | ✗ shower_knob_or_limiter | 3/3 | 2 | 3 | Debye switched to German initially but reverted to English for the self-help step after the tenant had switched languages. |
| g38_typos_slang | supply_valve_closed_after_work | ✗ — | ✓ supply_valve_closed_after_work | 3/3 | 2 | 5 | Debye handled the replies sensibly, identified the likely cause, and asked for consent to share details without exceeding the diagnostic-question limit. |
| g39_rude_tenant | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 2/3 | 3 | 3 | After the tenant asked for someone, Debye repeated that a technician was needed and asked for consent, but did not provide the promised follow-up about the property manager approving the visit and sending an appointment. |
| g40_building_notice_active | planned_maintenance | ✓ planned_maintenance | ✓ planned_maintenance | 2/3 | 0 | 5 | Debye correctly cites the maintenance notice, answers the question without promising an earlier return, and has no diagnostic questions. |

## Transcripts (after)

<details><summary>✓ g01_hot_water_used_up: Shower went cold after flatmate's long shower</summary>

- **tenant**: my shower went cold halfway through
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: it's cold or lukewarm everywhere
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: yeah my flatmate had a really long shower right before me
- **debye**: Then the hot water tank is probably just empty. It reheats in about 30 to 45 minutes; try again then and tell me if it works.
- **tenant**: ok will try later
- **debye**: Sounds good. Tell me how it goes.

</details>

<details><summary>✓ g02_simultaneous_use: Shower lukewarm while the dishwasher runs</summary>

- **tenant**: the shower keeps going lukewarm on me
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: cold or lukewarm everywhere
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: the dishwasher was running the whole time actually
- **debye**: That's likely just the hot water being shared: if the dishwasher or another shower runs at the same time, there's less for you. Try again once it's off, and tell me if it stays cold.
- **tenant**: dishwasher's done, shower is hot now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g03_switched_off_or_valve_closed: Hot water valve closed before holiday</summary>

- **tenant**: No hot water anywhere since we got back from holiday.
- **debye**: Let's fix it. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: Found it, I closed the hot water valve before we left. Opened it again now.
- **debye**: That was probably it. Give it 10 to 15 minutes to heat up, then tell me if the water is warm again.

</details>

<details><summary>✓ g04_not_run_long_enough: Tenant only ran the shower for 20 seconds</summary>

- **tenant**: Shower water is cold. Heating is on and the radiators are warm.
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: Only the shower is cold. Heating is on and the radiators are warm.
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: No, I live alone.
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: I only gave it like 20 seconds tbh
- **debye**: Hot water can take a moment to reach the tap. Let it run for about two minutes and tell me if it gets warm.
- **tenant**: ok yes it's warm now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g05_shower_knob_or_limiter: Shower thermostat stuck at 38°C</summary>

- **tenant**: Only the shower is cold. The bathroom sink gets hot.
- **debye**: Let's fix it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: it does stop around 38 yeah
- **debye**: Most shower thermostats stop at 38°C: press the small button on the knob and turn further to go hotter. Try that and tell me if it works.
- **tenant**: oh ok that was it, hot now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✗ g06_boiler_fault: Boiler shows F.28, radiators cold</summary>

- **tenant**: No hot water at all and the radiators are cold too.
- **debye**: Let's check. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: [photo] it says F.28
- **debye**: Thanks, that error means the boiler's ignition failed (error code F.28), so the heating won't start. If you have a gas stove: does it light normally?  [Yes | No | No gas stove]
- **tenant**: yes go ahead
- **debye**: Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address, floor and the photos with them?  [Yes, go ahead | No]

_judge:  ['ask about a gas smell']_

</details>

<details><summary>✓ g07_low_system_pressure: F.22 and pressure below 1 bar</summary>

- **tenant**: Hot water's gone and the heating isn't working either.
- **debye**: Let's fix it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: [photo] It shows F.22
- **debye**: Thanks, that error means the boiler's water pressure is too low (error code F.22), so the heating switches itself off for safety. On the boiler there's a small pressure gauge. Is the needle below 1 bar?  [Below 1 bar | 1 bar or more]
- **tenant**: yeah it's at about 0.5
- **debye**: Then our caretaker can top up the pressure in a few minutes, so no technician is needed for now. I've let them know.

</details>

<details><summary>✓ g08_supply_valve_closed_after_work: Shower cold since the plumber's visit</summary>

- **tenant**: Since the plumber fixed the leak in my bathroom on Monday, the shower only runs cold. The sink is fine.
- **debye**: Since it started right after the recent plumbing work, a hot-water valve was probably left closed. A plumber needs to reopen and test it.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g09_frozen_or_damaged_pipe: Trickle of cold water at a shower on the outside wall</summary>

- **tenant**: The shower is cold and only a trickle comes out. The sinks are fine.
- **debye**: Let's fix it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: Yes, it's fully on hot and turns normally.
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: No, no recent work.
- **debye**: Got it. Is it just this one tap, with very weak flow, maybe on an outside wall?  [Yes | No]
- **tenant**: Yes, just the shower. It’s on the outside wall, and it was freezing last night.
- **debye**: Weak flow at just one tap on an outside wall sounds like a frozen or damaged pipe. Please don't try to heat it with an open flame; it needs a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g10_shower_mixer_faulty: Only the shower cold, knob normal, no recent work</summary>

- **tenant**: my shower only gives cold water but the sink is hot
- **debye**: Let's fix it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: it's fully on hot and turns fine
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: no nothing
- **debye**: Ok. Is it just this one tap, with very weak flow, maybe on an outside wall?  [Yes | No]
- **tenant**: no, the flow is normal
- **debye**: Since only the shower stays cold, it's most likely the shower's mixer cartridge. That's a quick job for a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g11_boiler_schedule_or_settings: Lukewarm every evening, display normal</summary>

- **tenant**: Hot water is lukewarm again, kitchen and bathroom.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: no
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: It's fine in the morning, but every evening it's lukewarm.
- **debye**: Got it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: no error, display looks normal
- **debye**: It sounds like the boiler's hot-water schedule or temperature is set wrong. Our caretaker can fix that in a few minutes, so no technician needed. I've let them know.

</details>

<details><summary>✓ g12_tank_thermostat_or_scale: Heating works, hot water stays cold everywhere</summary>

- **tenant**: No hot water anywhere in the flat, but the heating works fine.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: No, I'm alone at home.
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: Stays cold, I let it run for ages.
- **debye**: Got it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: nothing on it, looks normal
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g13_diverter_valve_stuck: Radiators hot, every tap cold</summary>

- **tenant**: The radiators are toasty but every single tap is cold.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: nope
- **debye**: Do you mean nobody used hot water just before or at the same time?
- **tenant**: yep, nobody used hot water
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: stays cold
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge: Debye says the fault is likely the hot-water tank’s thermostat or limescale, though neither is established by the tenant or building data. []_

</details>

<details><summary>✓ g14_circulation_pump_faulty: Only lukewarm after a long wait, everywhere</summary>

- **tenant**: No proper hot water in the kitchen or the bathroom.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: No, nobody.
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: After a few minutes it gets lukewarm, never really hot.
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: No, they're warm.
- **debye**: If the water only gets lukewarm after a long wait everywhere, the hot water circulation pump is probably failing. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g15_no_power_to_boiler: Boiler display dark, lights out</summary>

- **tenant**: No hot water and the radiators are cold.
- **debye**: Let's fix it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: The display is completely dark.
- **debye**: Got it. Are the lights and other electrics working in your apartment?  [Yes | No]
- **tenant**: Actually no, the lights in the hallway are off too.
- **debye**: Then the boiler seems to have no power. Our caretaker will check the fuse box first, and if that's not it, an electrician will.

</details>

<details><summary>✓ g16_electric_instant_heater: Electric heater in 3b, everything on</summary>

- **tenant**: There's no hot water at all since this morning.
- **debye**: Let's fix it. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: Checked, everything is on and the valves are open.
- **debye**: Your flat's hot water comes from the small electric heater, and since it's switched on, the heater itself most likely needs an electrician.
- **debye**: I'd like to send Elektro Klein GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g17_planned_maintenance: No hot water during planned maintenance</summary>

- **tenant**: Hi, no hot water this morning?
- **debye**: There's planned maintenance in your building today; hot water should be back by the time in the notice.
- **tenant**: ah ok thanks
- **debye**: You’re welcome, Luka.

</details>

<details><summary>✓ g18_gas_supply_interrupted: Boiler F.28 and the gas stove won't light</summary>

- **tenant**: No hot water and the heating is off.
- **debye**: Let's fix it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: [photo] It shows F.28
- **debye**: Thanks, that error means the boiler's ignition failed (error code F.28), so the heating won't start. If you have a gas stove: does it light normally?  [Yes | No | No gas stove]
- **tenant**: No, the stove won't light either.
- **debye**: Then the gas supply itself is probably interrupted. Your property manager is contacting the gas supplier now, and I'll keep you posted.

</details>

<details><summary>✓ g19_ambiguous_everything: Ambiguous 'everything' answer gets clarified</summary>

- **tenant**: Hot water ran out in the shower.
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everything
- **debye**: Do you mean the sinks are cold too, or that hot water ran out everywhere at once?
- **tenant**: like the dishwasher and the washing machine were both on while I showered
- **debye**: That's likely just the hot water being shared: if the dishwasher or another shower runs at the same time, there's less for you. Try again once it's off, and tell me if it stays cold.
- **tenant**: Tried again and it works now, thanks!
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g20_multi_fact_first_message: First message already answers three questions</summary>

- **tenant**: Hi, my shower's been cold since this morning. The bathroom sink is hot though, nobody else is home, and the knob is all the way on hot and turns normally.
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: No.
- **debye**: Ok. Is it just this one tap, with very weak flow, maybe on an outside wall?  [Yes | No]
- **tenant**: No, normal flow.
- **debye**: Since only the shower stays cold, it's most likely the shower's mixer cartridge. That's a quick job for a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g21_switched_off_resolved: Heater fuse was down, flipped back, works</summary>

- **tenant**: No hot water at all since this morning
- **debye**: Let's fix it. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: the fuse for it was down. flipped it back up
- **debye**: That was probably it. Give it 10 to 15 minutes to heat up, then tell me if the water is warm again.
- **tenant**: yes it's hot again, thanks
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✗ g22_self_help_fails: Let it run two minutes, still cold, technician</summary>

- **tenant**: No hot water in the kitchen or the shower.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: no
- **debye**: Ok. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: haven't let it run that long
- **debye**: Hot water can take a moment to reach the tap. Let it run for about two minutes and tell me if it gets warm.
- **tenant**: ran it for 3 minutes, still ice cold
- **debye**: Thanks for checking. Are the radiators cold as well?  [Yes | No]
- **tenant**: no they're warm
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['ask a fourth diagnostic question', 'close the case after the failed tip']_

</details>

<details><summary>✗ g23_german_tenant: German tenant, boiler F.28</summary>

- **tenant**: Hallo, bei mir gibt es kein warmes Wasser und die Heizung ist auch kalt.
- **debye**: Let's check. Könnten Sie ein Foto vom Display des Heizkessels schicken? Wenn etwas nicht stimmt, wird dort oft ein Fehlercode angezeigt.  [Shows a code | Looks normal | It's dark]
- **tenant**: Da steht F.28
- **debye**: Thanks, that error means the boiler's ignition failed (error code F.28), so the heating won't start. Falls Sie einen Gasherd haben: Zündet er normal?  [Yes | No | No gas stove]
- **tenant**: Ja, klar.
- **debye**: Der Heizkessel hat eine Zündstörung (Fehlercode F.28), deshalb funktionieren Heizung und Warmwasser nicht. Die Heizungsfirma muss den Kessel prüfen.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['answer in English', "use 'Sie' instead of 'du'"]_

</details>

<details><summary>✓ g24_voice_note_rambling: Rambling voice-note message with four facts</summary>

- **tenant**: ok so um, I'm just recording this quickly, uh, basically I got in the shower like ten minutes ago and it was freezing, and then I checked the kitchen tap and that's cold too, and my girlfriend hasn't showered or anything today, she's at work, and the heating is on, the radiators are warm, so it's not that, and I let the tap run for like five minutes and it never got warm, so yeah, no idea
- **debye**: Got it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: display looks normal, no code
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g25_photo_f28: Tenant sends a photo of the display showing F.28</summary>

- **tenant**: no hot water
- **tenant**: [photo] this is what it shows
- **debye**: Thanks, that error means the boiler's ignition failed (error code F.28), so the heating won't start. If you have a gas stove: does it light normally?  [Yes | No | No gas stove]
- **tenant**: yes, freezing in here
- **debye**: Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address, floor and the photos with them?  [Yes, go ahead | No]

_judge:  ['give the code before its meaning']_

</details>

<details><summary>✓ g26_central_heating_duplicate: Neighbour reports while the boiler case is open</summary>

- **tenant**: Hi, no hot water in my flat since this morning.
- **debye**: Thanks, Jonas. The heating for the whole building is already reported and a technician is on it. I'll keep you posted.

</details>

<details><summary>✓ g27_gas_mention_mid_diagnosis: Tenant mentions a gas smell mid-diagnosis</summary>

- **tenant**: no hot water anywhere
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: no. also there's kind of a weird gas smell near the boiler
- **debye**: Please leave the apartment now, don't use light switches or open flames, and call the gas emergency line 0800 2 26 77 89 from outside. I've alerted your property manager right away.

</details>

<details><summary>✗ g28_message_burst: Burst 'everything' + 'as I was cooking just now'</summary>

- **tenant**: the hot water just stopped
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everything
- **debye**: Do you mean the shower and sinks are all cold?
- **tenant**: everything
- **debye**: Are the sinks cold too, or is it only the shower?
- **tenant**: everything
- **tenant**: as I was cooking just now
- **debye**: That's likely just the hot water being shared: if the dishwasher or another shower runs at the same time, there's less for you. Try again once it's off, and tell me if it stays cold.
- **tenant**: all the taps went cold, I was the only one using water
- **debye**: Thanks for checking. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: All on, can't see anything switched off.
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: Stays cold. And yeah now that you say it, the radiators are cold too.
- **debye**: Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge: “That's likely just the hot water being shared” assumes simultaneous use despite the tenant’s ambiguous “everything” replies. ['reply to the burst messages one by one', "assume simultaneous use from 'everything'", "ask whether it's only the shower after the clarification"]_

</details>

<details><summary>✗ g29_answers_different_question: Tenant answers about radiators instead of hot water use</summary>

- **tenant**: All the taps are cold, no hot water anywhere.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: no
- **debye**: Ok. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: stays cold
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: the radiators are warm if that helps
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge: Debye states the flat has a hot water tank; the tenant did not provide that information, and it is not listed as known building data. ['treat the radiator answer as an answer to q_hot_water_use']_

</details>

<details><summary>✓ g30_two_answers_at_once: Tenant answers the knob and recent-work questions together</summary>

- **tenant**: only the shower is cold, the sinks are fine
- **debye**: Let's fix it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: fully on hot, turns fine. and nobody's touched the pipes lately
- **debye**: Got it. Is it just this one tap, with very weak flow, maybe on an outside wall?  [Yes | No]
- **tenant**: yes, barely a trickle, and it's on the outside wall
- **debye**: Weak flow at just one tap on an outside wall sounds like a frozen or damaged pipe. Please don't try to heat it with an open flame; it needs a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g31_tenant_corrects_themselves: Tenant corrects 'anywhere' to 'only the shower'</summary>

- **tenant**: no hot water anywhere in the flat
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: no
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: actually the sink is warm, it's just the shower
- **debye**: Got it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: it stops at 38
- **debye**: Most shower thermostats stop at 38°C: press the small button on the knob and turn further to go hotter. Try that and tell me if it works.
- **tenant**: that was it, it's hot now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✗ g32_off_topic_mid_diagnosis: 'thanks' and 'lol' in the middle of diagnosis</summary>

- **tenant**: Kitchen tap and shower are both cold.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: thanks for the quick reply
- **tenant**: nobody used any
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: ok after a few minutes it's lukewarm, never hot
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: no, warm
- **debye**: If the water only gets lukewarm after a long wait everywhere, the hot water circulation pump is probably failing. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ["repeat the open question after 'thanks' or 'lol'", "treat 'lol' as an answer", 'ask a new question after an off-topic message']_

</details>

<details><summary>✗ g33_hello_after_delay: 'hello?' after a delay, question repeated briefly</summary>

- **tenant**: shower is cold
- **debye**: Let's fix it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: hello?
- **debye**: No problem. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: oh sorry, yes my son had a 30 minute shower before me
- **debye**: Got it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: it’s cold or lukewarm everywhere, not just the shower. radiators are warm though.
- **debye**: Got it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: I don’t know where the boiler display is or how to check it.
- **debye**: That’s fine. On the boiler there's a small pressure gauge. Is the needle below 1 bar?  [Below 1 bar | 1 bar or more]
- **tenant**: I don't know where the boiler is, sorry.
- **debye**: Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge: Debye says both heating and hot water are off, but the tenant said the radiators were warm. ['send a technician']_

</details>

<details><summary>✓ g34_dont_know_cant_check: 'can't check right now' moves on to the next question</summary>

- **tenant**: the hot water is gone, everywhere
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: no
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: Stays cold. It's cold or lukewarm everywhere.
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: yes, cold too
- **debye**: Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g35_question_back: 'is it dangerous?' and 'do I have to pay?'</summary>

- **tenant**: no hot water in the flat
- **debye**: Let's fix it. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: everything's on, I checked
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: is it dangerous?
- **debye**: Cold water alone isn't dangerous.
- **debye**: Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: sure. do I have to pay for this?
- **debye**: Repairs to the building’s system are usually covered by the landlord; the property manager can confirm.
- **debye**: Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: No, I don't think so.
- **debye**: Do you mean nobody used hot water just before or at the same time?
- **tenant**: Yes, nobody used hot water just before or at the same time.
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: I don't know, I haven't tried.
- **debye**: Hot water can take a moment to reach the tap. Let it run for about two minutes and tell me if it gets warm.
- **tenant**: I don't know, I haven't tried.
- **debye**: It may just need longer to reach the tap. Try running the hot tap for two minutes, then tell me if it warms up.
- **tenant**: I don't know, I haven't tried.
- **debye**: Please try running the hot tap for two minutes and let me know whether it warms up.
- **tenant**: cold or lukewarm everywhere. there's an electric instantaneous heater in the flat, and the power's on.
- **debye**: Thanks for letting me know, then I'll get a technician to look at it.
- **debye**: Your flat's hot water comes from the small electric heater, and since it's switched on, the heater itself most likely needs an electrician.
- **debye**: I'd like to send Elektro Klein GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g36_works_again_by_itself: 'never mind, it works again' while waiting</summary>

- **tenant**: my shower is cold
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: no
- **debye**: Do you mean only the shower is cold, or are the sinks cold too?
- **tenant**: only the shower, sorry
- **debye**: Got it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: Fully hot, turns normally. No one used hot water just before or at the same time.
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: I don't know.
- **debye**: Since only the shower stays cold, it's most likely the shower's mixer cartridge. That's a quick job for a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['send a technician']_

</details>

<details><summary>✗ g37_language_switch: Tenant switches from English to German</summary>

- **tenant**: no hot water in the shower
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: Sorry, kann ich auf Deutsch schreiben? Nein, niemand hat vorher Wasser benutzt.
- **debye**: Ja, gern. Ist nur die Dusche betroffen, oder ist das Wasser auch an den Waschbecken kalt?  [Only the shower | Everywhere]
- **tenant**: Nur die Dusche, das Waschbecken ist heiß.
- **debye**: Alles klar. Ist der Duschregler ganz auf heiß gestellt (manche stoppen bei 38 °C, bis man einen kleinen Knopf drückt), und lässt er sich normal drehen?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: Der stoppt bei 38.
- **debye**: Most shower thermostats stop at 38°C: press the small button on the knob and turn further to go hotter. Try that and tell me if it works.
- **tenant**: Ja, jetzt ist es heiß, danke.
- **debye**: Good to hear. I'll close this then.

_judge:  ['keep answering in English after the switch']_

</details>

<details><summary>✓ g38_typos_slang: 'showr cold af' with typos and slang</summary>

- **tenant**: showr cold af
- **debye**: Let's fix it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: sink hot tho
- **debye**: Got it. Is the shower knob turned fully to hot (some stop at 38°C until you press a small button), and does it turn normally?  [Stops at 38°C | Slips or stuck | Fully hot, normal]
- **tenant**: its on max n turns fine
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: ya plumber was here last wk
- **debye**: Since it started right after the recent plumbing work, a hot-water valve was probably left closed. A plumber needs to reopen and test it.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g39_rude_tenant: 'this is useless, just send someone'</summary>

- **tenant**: no hot water AGAIN
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everywhere
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, at the same tim | No]
- **tenant**: nobody used hot water
- **debye**: Got it. If you let the hot tap run for two minutes, does it warm up slowly, stay cold, or is it only cold at certain times of day?  [Haven't tried | Warms up slowly | Stays cold | At certain times]
- **tenant**: stays cold. seriously? this is useless, just send someone.
- **debye**: Understood. I'll get a technician to look at it.
- **debye**: A heating technician needs to look at it.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['ask more diagnostic questions after the complaint']_

</details>

<details><summary>✓ g40_building_notice_active: Active maintenance notice, tenant asks if it takes longer</summary>

- **tenant**: why is there no hot water?? I need to shower before work
- **debye**: There's planned maintenance in your building today; hot water should be back by the time in the notice.
- **tenant**: is it going to take longer than that?
- **debye**: The notice says hot water is off until 13:00 today; I don’t have an update on whether it will take longer.

</details>

