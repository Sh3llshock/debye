# Diagnosis eval: 40 gold conversations

`scripts/eval_diagnosis.py`. For each conversation in `data/diagnosis/gold_conversations.json`, Luna (gpt-6-luna) plays Debye through the real router and agent (fake WhatsApp send, fresh state). A simulated tenant (same model) answers only from the conversation's `tenant_facts` and follows the gold tenant turns (bursts are sent concurrently with the 2.5 s-style debounce, photos as real image messages). A judge (same model) checks invented facts, clarification, the edge case, tone and the `must_not` rules; code checks the cause, the outcome and the number of diagnostic questions. A conversation passes only if every check passes.

**Before** = `main` before this PR (KB v1, old prompt), 3 passes. **After** = this PR, 3 passes. Numbers are pooled over all passes (40 conversations per pass).

Per pass, right cause (after): 37/40, 39/40, 36/40; before: 28/40, 24/40, 28/40.

| | Before | After |
|---|---|---|
| Passed (all checks) | 24/120 (20%) | 80/120 (67%) |
| Right cause | 80/120 (67%) | 112/120 (93%) |
| Right cause, diverter ≈ tank | 84/120 (70%) | 114/120 (95%) |
| Right outcome | 90/120 | 114/120 |
| ≤ 3 diagnostic questions | 120/120 | 120/120 |
| Average diagnostic questions | 2.02 | 1.72 |
| No invented facts | 92/120 | 113/120 |
| Clarified when needed | 104/120 | 116/120 |
| Edge case handled | 44/96 | 70/93 |
| must_not rules kept | 44/120 | 87/120 |
| Tone (judge, 1-5) | 2.96 | 4.23 |
| Average turn time | 4.2 s | 2.9 s |

## Per conversation

Before/After columns show pass 1; 'Cause hits' counts the right cause over all after passes.

| Conversation | Expected | Before | After | Cause hits | Q (after) | Tone (after) | Judge note (after) |
|---|---|---|---|---|---|---|---|
| g01_hot_water_used_up | hot_water_used_up | ✗ hot_water_used_up | ✓ hot_water_used_up | 3/3 | 2 | 5 | Debye sensibly narrowed down the issue, suggested a short self-help wait, and closed after the tenant said it was working. |
| g02_simultaneous_use | simultaneous_use | ✗ simultaneous_use | ✓ simultaneous_use | 3/3 | 2 | 5 | Debye gave a sensible self-help tip, and the tenant confirmed it worked. |
| g03_switched_off_or_valve_closed | switched_off_or_valve_closed | ✗ diverter_valve_stuck | ✓ switched_off_or_valve_closed | 3/3 | 1 | 5 | Debye gave a sensible self-help check, followed the tenant’s valve discovery, and closed the resolved issue without breaking any listed rules. |
| g04_not_run_long_enough | not_run_long_enough | ✗ not_run_long_enough | ✓ not_run_long_enough | 3/3 | 2 | 4 | Debye handled the ambiguous answer by checking, then suggested a low-cost test; the tenant confirmed it worked. |
| g05_shower_knob_or_limiter | shower_knob_or_limiter | ✗ shower_knob_or_limiter | ✓ shower_knob_or_limiter | 3/3 | 1 | 5 | Debye gave a sensible self-help step, handled the tenant’s confirmation, and closed the resolved issue without violating any listed rule. |
| g06_boiler_fault | boiler_fault | ✓ boiler_fault | ✓ boiler_fault | 3/3 | 1 | 4 | Debye correctly interpreted F.28 and requested consent for a technician visit without promising a date or cost. |
| g07_low_system_pressure | low_system_pressure | ✓ low_system_pressure | ✓ low_system_pressure | 3/3 | 2 | 5 | Debye correctly identified low pressure, confirmed the gauge reading, and arranged the caretaker without suggesting a technician or asking about gas. |
| g08_supply_valve_closed_after_work | supply_valve_closed_after_work | ✗ supply_valve_closed_after_work | ✓ supply_valve_closed_after_work | 3/3 | 0 | 4 | Debye used the details already provided to identify a likely closed valve and ask for consent to send a plumber. |
| g09_frozen_or_damaged_pipe | frozen_or_damaged_pipe | ✗ shower_mixer_faulty | ✓ frozen_or_damaged_pipe | 3/3 | 0 | 5 | Debye correctly identifies a possible frozen or damaged pipe, warns against an open flame, and asks for consent to share details with the plumber. |
| g10_shower_mixer_faulty | shower_mixer_faulty | ✗ shower_mixer_faulty | ✓ shower_mixer_faulty | 3/3 | 3 | 5 | Debye asked three sensible diagnostic questions, correctly identified a likely mixer fault, and requested consent to share details with the plumber. |
| g11_boiler_schedule_or_settings | boiler_schedule_or_settings | ✗ circulation_pump_faulty | ✗ diverter_valve_stuck | 0/3 | 3 | 3 | Debye incorrectly diagnosed a stuck boiler switch and sent the tenant to a heating technician instead of identifying the likely schedule or temperature setting and notifying the caretaker. |
| g12_tank_thermostat_or_scale | tank_thermostat_or_scale | ✓ tank_thermostat_or_scale | ✗ tank_thermostat_or_scale | 3/3 | 3 | 4 | Debye correctly handled the answers and reached the technician outcome, but asked whether the sinks were cold after the tenant had already said there was no hot water anywhere. |
| g13_diverter_valve_stuck | diverter_valve_stuck | ✗ tank_thermostat_or_scale | ✗ diverter_valve_stuck | 2/3 | 3 | 4 | Debye correctly clarified the ambiguous “nope” and reached the right diagnosis, but asked whether it was only the shower despite the tenant already saying every tap was cold. |
| g14_circulation_pump_faulty | circulation_pump_faulty | ✗ circulation_pump_faulty | ✓ circulation_pump_faulty | 3/3 | 3 | 5 | Debye asked three sensible diagnostic questions, identified the likely pump issue, and requested consent without violating any listed rule. |
| g15_no_power_to_boiler | no_power_to_boiler | ✓ no_power_to_boiler | ✓ no_power_to_boiler | 2/3 | 2 | 5 | Debye follows the sensible diagnostic sequence and says the caretaker will check the fuse box before an electrician is sent. |
| g16_electric_instant_heater | electric_instant_heater | ✗ electric_instant_heater | ✓ electric_instant_heater | 3/3 | 1 | 4 | Debye used the known heater type and sensibly recommended an electrician after the tenant confirmed everything was on, though it did not mention that the property manager approves the visit first. |
| g17_planned_maintenance | planned_maintenance | ✗ planned_maintenance | ✓ planned_maintenance | 3/3 | 0 | 5 | Debye correctly cited the planned maintenance and did not ask diagnostic questions or send a technician. |
| g18_gas_supply_interrupted | gas_supply_interrupted | ✗ not_run_long_enough | ✓ gas_supply_interrupted | 3/3 | 0 | 4 | Debye correctly identifies a likely gas supply interruption and gives the expected update without asking unnecessary questions. |
| g19_ambiguous_everything | simultaneous_use | ✓ simultaneous_use | ✓ simultaneous_use | 3/3 | 2 | 5 | Debye clarified “everything,” identified simultaneous appliance use, offered a simple retry, and closed after the tenant said it was working. |
| g20_multi_fact_first_message | shower_mixer_faulty | ✗ shower_mixer_faulty | ✓ shower_mixer_faulty | 3/3 | 2 | 4 | Debye used the facts already given, asked sensible remaining diagnostic questions, and offered the right repair path. |
| g21_switched_off_resolved | switched_off_or_valve_closed | ✗ electric_instant_heater | ✓ switched_off_or_valve_closed | 3/3 | 1 | 5 | Debye gave a brief self-help check, confirmed the water was hot again, and closed without further diagnostics. |
| g22_self_help_fails | tank_thermostat_or_scale | ✗ not_run_long_enough | ✗ tank_thermostat_or_scale | 3/3 | 3 | 4 | Debye handled the failed self-help tip and reached the correct technician outcome, but stated it would get a technician before obtaining consent and arranging approval. |
| g23_german_tenant | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 3/3 | 1 | 3 | The initial request uses formal “Sie” instead of “du”; the diagnosis and technician handoff are otherwise appropriate. |
| g24_voice_note_rambling | tank_thermostat_or_scale | ✗ tank_thermostat_or_scale | ✓ tank_thermostat_or_scale | 3/3 | 1 | 5 | Debye handles the rambling multi-fact report, asks for the display photo, and gives a concise diagnosis and consent request without inventing facts. |
| g25_photo_f28 | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 3/3 | 0 | 3 | Debye replied separately to the burst and stated F.28 before explaining what it means. |
| g26_central_heating_duplicate | boiler_fault | ✓ boiler_fault | ✓ boiler_fault | 3/3 | 0 | 4 | Debye appropriately links the report to the building-wide issue and doesn’t ask diagnostic questions or identify another tenant. |
| g27_gas_mention_mid_diagnosis | gas_smell | ✓ gas_smell | ✓ gas_smell | 3/3 | 2 | 5 | Debye handled the gas smell safely, asked no further diagnostic questions, and did not downplay it or ask the tenant to check the boiler. |
| g28_message_burst | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 3/3 | 3 | 4 | Debye clarified the ambiguous answer and handled the burst, but added unsupported claims about the heating and the diagnosis. |
| g29_answers_different_question | diverter_valve_stuck | ✗ tank_thermostat_or_scale | ✗ tank_thermostat_or_scale | 1/3 | 3 | 3 | Debye asks about the radiators after the tenant has already reported they are warm, then fails to use that information to give the intended diagnosis. |
| g30_two_answers_at_once | frozen_or_damaged_pipe | ✗ shower_mixer_faulty | ✓ frozen_or_damaged_pipe | 3/3 | 2 | 5 | Debye handled both answers, identified the likely pipe issue, and asked for consent without repeating the recent-work or sink questions. |
| g31_tenant_corrects_themselves | shower_knob_or_limiter | ✗ shower_knob_or_limiter | ✓ shower_knob_or_limiter | 3/3 | 2 | 4 | Debye accepted the correction to a shower-only issue, offered the right self-help, and did not send a technician. |
| g32_off_topic_mid_diagnosis | circulation_pump_faulty | ✗ circulation_pump_faulty | ✗ circulation_pump_faulty | 3/3 | 3 | 3 | Debye handled the diagnosis and consent appropriately, but after the tenant’s “lol” it repeated the open question instead of keeping it open without asking again. |
| g33_hello_after_delay | hot_water_used_up | ✗ hot_water_used_up | ✓ hot_water_used_up | 3/3 | 1 | 4 | Debye briefly repeated the same question after “hello?”, correctly identified the likely depleted tank, and handled the tenant’s resolution without sending a technician. |
| g34_dont_know_cant_check | boiler_fault | ✗ boiler_fault | ✗ boiler_fault | 3/3 | 3 | 3 | Debye should have moved on after the tenant couldn’t check the valves, but instead asked for a boiler photo and cited an error code not provided in the conversation. |
| g35_question_back | electric_instant_heater | ✗ boiler_schedule_or_settings | ✓ electric_instant_heater | 3/3 | 1 | 5 | Debye correctly identified the likely heater fault and asked for consent to share the tenant’s details without promising a date or cost. |
| g36_works_again_by_itself | not_run_long_enough | ✓ not_run_long_enough | ✗ shower_mixer_faulty | 2/3 | 3 | 3 | Debye ignored the tenant’s update that nobody had used hot water and skipped the cheap run-the-tap self-help, instead diagnosing a mixer fault and offering a technician. |
| g37_language_switch | shower_knob_or_limiter | ✗ not_run_long_enough | ✓ shower_knob_or_limiter | 3/3 | 2 | 4 | Debye switched to German, clarified the shower issue, and gave the appropriate self-help step; the tenant confirmed it worked. |
| g38_typos_slang | supply_valve_closed_after_work | ✗ — | ✓ supply_valve_closed_after_work | 3/3 | 3 | 5 | Debye handled the typo-filled report naturally, asked three relevant diagnostic questions, and made a grounded referral with a consent request. |
| g39_rude_tenant | boiler_fault | ✗ boiler_fault | ✓ boiler_fault | 3/3 | 2 | 4 | Debye handled the rude request without further diagnosis or argument, and sought consent to share details with the named company. |
| g40_building_notice_active | planned_maintenance | ✓ planned_maintenance | ✓ planned_maintenance | 3/3 | 0 | 5 | Debye correctly cites planned maintenance and the notice time, without promising an earlier return or asking diagnostic questions. |

## Transcripts (after)

<details><summary>✓ g01_hot_water_used_up: Shower went cold after flatmate's long shower</summary>

- **tenant**: my shower went cold halfway through
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everywhere, it's cold or lukewarm
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: yeah my flatmate had a really long shower right before me
- **debye**: Then the hot water tank is probably just empty. It reheats in about 30 to 45 minutes; try again then and tell me if it works.
- **tenant**: ok will try later
- **debye**: Sounds good. Tell me how it goes.
- **tenant**: tried again and it's working now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g02_simultaneous_use: Shower lukewarm while the dishwasher runs</summary>

- **tenant**: the shower keeps going lukewarm on me
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: cold or lukewarm everywhere
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
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
- **tenant**: Yep, working again now!
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g04_not_run_long_enough: Tenant only ran the shower for 20 seconds</summary>

- **tenant**: Shower water is cold. Heating is on and the radiators are warm.
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: No, I live alone.
- **debye**: Thanks. And is it only the shower, or the sinks too?  [Only the shower | Everywhere]
- **tenant**: Only the shower, I think?
- **debye**: Do you mean the sinks still have hot water, or are they cold too?
- **tenant**: I don't know, haven't checked the sinks.
- **debye**: Ok. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: I only gave it like 20 seconds tbh
- **debye**: Hot water can take a moment to reach the tap. Let it run for about two minutes and tell me if it gets warm.
- **tenant**: ok yes it's warm now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g05_shower_knob_or_limiter: Shower thermostat stuck at 38°C</summary>

- **tenant**: Only the shower is cold. The bathroom sink gets hot.
- **debye**: Let's fix it. Is the shower knob turned fully to hot? Some stop at 38°C until you press a small button.  [Stops at 38°C | Fully on hot]
- **tenant**: it does stop around 38 yeah
- **debye**: Most shower thermostats stop at 38°C: press the small button on the knob and turn further to go hotter. Try that and tell me if it works.
- **tenant**: oh ok that was it, hot now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g06_boiler_fault: Boiler shows F.28, radiators cold</summary>

- **tenant**: No hot water at all and the radiators are cold too.
- **debye**: Let's fix it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: it says F.28
- **debye**: That error means the boiler's ignition failed (error code F.28), so the heating won't start. Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

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
- **debye**: Weak flow at just one tap on an outside wall sounds like a frozen or damaged pipe. Please don't try to heat it with an open flame; it needs a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g10_shower_mixer_faulty: Only the shower cold, knob normal, no recent work</summary>

- **tenant**: my shower only gives cold water but the sink is hot
- **debye**: Let's fix it. Is the shower knob turned fully to hot? Some stop at 38°C until you press a small button.  [Stops at 38°C | Fully on hot]
- **tenant**: it's fully on hot and turns fine
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: no nothing
- **debye**: Got it. Is only a weak trickle coming out of the shower?  [Only a trickle | Normal flow]
- **tenant**: no, the flow is normal
- **debye**: Since only the shower stays cold, it's most likely the shower's mixer cartridge. That's a quick job for a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g11_boiler_schedule_or_settings: Lukewarm every evening, display normal</summary>

- **tenant**: Hot water is lukewarm again, kitchen and bathroom.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: no
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: No, the radiators are warm.
- **debye**: Got it. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: It's fine in the morning, but every evening it's lukewarm.
- **debye**: Since the radiators are warm but all the taps are cold, the boiler's switch between heating and hot water is probably stuck. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['send a heating technician']_

</details>

<details><summary>✗ g12_tank_thermostat_or_scale: Heating works, hot water stays cold everywhere</summary>

- **tenant**: No hot water anywhere in the flat, but the heating works fine.
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: No hot water anywhere in the flat, but the heating works fine.
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: No, I'm alone at home.
- **debye**: Okay. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: Stays cold, I let it run for ages.
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['ask whether the sinks are cold (already given)']_

</details>

<details><summary>✗ g13_diverter_valve_stuck: Radiators hot, every tap cold</summary>

- **tenant**: The radiators are toasty but every single tap is cold.
- **debye**: Let's fix it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: display's normal, no code
- **debye**: Got it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: nope
- **debye**: Do you mean only the shower is cold, or are the sinks cold too?
- **tenant**: cold or lukewarm everywhere. radiators are warm.
- **debye**: Got it. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: everything's on and open
- **debye**: Since the radiators are warm but all the taps are cold, the boiler's switch between heating and hot water is probably stuck. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ["ask whether it's only the shower (already given)"]_

</details>

<details><summary>✓ g14_circulation_pump_faulty: Only lukewarm after a long wait, everywhere</summary>

- **tenant**: No proper hot water in the kitchen or the bathroom.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: No, nobody.
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: No, they're warm.
- **debye**: Got it. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: After a few minutes it gets lukewarm, never really hot.
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

- **tenant**: No hot water and the heating is off. My gas stove won't light either.
- **debye**: Then the gas supply itself is probably interrupted. Your property manager is contacting the gas supplier now, and I'll keep you posted.

</details>

<details><summary>✓ g19_ambiguous_everything: Ambiguous 'everything' answer gets clarified</summary>

- **tenant**: Hot water ran out in the shower.
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everything
- **debye**: Do you mean the hot water is cold at the sinks as well as the shower?
- **tenant**: yeah, everywhere
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: like the dishwasher and the washing machine were both on while I showered
- **debye**: That's likely just the hot water being shared: if the dishwasher or another shower runs at the same time, there's less for you. Try again once it's off, and tell me if it stays cold.
- **tenant**: Tried again and it's working now, thanks!
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✓ g20_multi_fact_first_message: First message already answers three questions</summary>

- **tenant**: Hi, my shower's been cold since this morning. The bathroom sink is hot though, nobody else is home, and the knob is all the way on hot and turns normally.
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: No.
- **debye**: Ok. Is only a weak trickle coming out of the shower?  [Only a trickle | Normal flow]
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
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: no
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: no they're warm
- **debye**: Got it. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: haven't let it run that long
- **debye**: Hot water can take a moment to reach the tap. Let it run for about two minutes and tell me if it gets warm.
- **tenant**: ran it for 3 minutes, still ice cold
- **debye**: Thanks for letting me know, then I'll get a technician to look at it.
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['close the case after the failed tip']_

</details>

<details><summary>✗ g23_german_tenant: German tenant, boiler F.28</summary>

- **tenant**: Hallo, bei mir gibt es kein warmes Wasser und die Heizung ist auch kalt.
- **debye**: Lass uns das prüfen. Könnten Sie ein Foto vom Display des Heizkessels schicken? Dort wird bei einer Störung oft ein Fehlercode angezeigt.  [Zeigt einen Code | Sieht normal aus | Es ist dunkel]
- **tenant**: Da steht F.28
- **debye**: Danke, das heißt: die Zündung des Kessels ist fehlgeschlagen, deshalb startet die Heizung nicht (Fehlercode F.28). Da Heizung und Warmwasser beide aus sind, ist es höchstwahrscheinlich eine Störung am Kessel. Das muss sich ein Heizungstechniker ansehen.
- **debye**: Ich würde Heizung Schmidt GmbH schicken. Ist es okay, wenn ich deinen Namen, deine Telefonnummer, Adresse und dein Stockwerk weitergebe?  [Ja, gerne | Nein]

_judge:  ["use 'Sie' instead of 'du'"]_

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
- **debye**: That error means the boiler's ignition failed (error code F.28), so the heating won't start. Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address, floor and the photos with them?  [Yes, go ahead | No]

_judge:  ['reply separately to each message of the burst', 'give the code before its meaning']_

</details>

<details><summary>✓ g26_central_heating_duplicate: Neighbour reports while the boiler case is open</summary>

- **tenant**: Hi, no hot water in my flat since this morning.
- **debye**: Thanks, Jonas. The heating for the whole building is already reported and a technician is on it. I'll keep you posted.

</details>

<details><summary>✓ g27_gas_mention_mid_diagnosis: Tenant mentions a gas smell mid-diagnosis</summary>

- **tenant**: no hot water anywhere
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everywhere, cold or lukewarm at the sinks too
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: no. also there's kind of a weird gas smell near the boiler
- **debye**: Please leave the apartment now, don't use light switches or open flames, and call the gas emergency line 0800 2 26 77 89 from outside. I've alerted your property manager right away.

</details>

<details><summary>✗ g28_message_burst: Burst 'everything' + 'as I was cooking just now'</summary>

- **tenant**: the hot water just stopped
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everything
- **debye**: Do you mean the hot water is cold at all taps, including the sinks?
- **tenant**: all the taps went cold, I was the only one using water
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: yeah now that you say it, they're cold
- **debye**: Got it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: [photo] It says F.29
- **debye**: That error means the boiler's flame went out while running (error code F.29), so the heating keeps cutting out. Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address, floor and the photos with them?  [Yes, go ahead | No]

_judge: Debye says the heating keeps cutting out, although the tenant only reported that the radiators are cold. It also says both heating and hot water are off and calls it most likely a boiler fault; those conclusions go beyond the facts provided. ["assume simultaneous use from 'everything'"]_

</details>

<details><summary>✗ g29_answers_different_question: Tenant answers about radiators instead of hot water use</summary>

- **tenant**: All the taps are cold, no hot water anywhere.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: no
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: the radiators are warm if that helps
- **debye**: Got it. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: I don't know, haven't tried that.
- **debye**: Hot water can take a moment to reach the tap. Let it run for about two minutes and tell me if it gets warm.
- **tenant**: All the taps are cold, no hot water anywhere.
- **debye**: Thanks for letting me know, then I'll get a technician to look at it.
- **debye**: The heating works but the hot water doesn't, so it's likely the hot water tank's thermostat or limescale. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge: Debye says the heating works, but the tenant only said the radiators are warm. It also attributes the issue to a hot water tank thermostat or limescale, rather than the likely stuck switch between heating and hot water in the gold. ['ask about the radiators later (already given)']_

</details>

<details><summary>✓ g30_two_answers_at_once: Tenant answers the knob and recent-work questions together</summary>

- **tenant**: only the shower is cold, the sinks are fine
- **debye**: Let's fix it. Is the shower knob turned fully to hot? Some stop at 38°C until you press a small button.  [Stops at 38°C | Fully on hot]
- **tenant**: fully on hot, turns fine. and nobody's touched the pipes lately
- **debye**: Got it. Is only a weak trickle coming out of the shower?  [Only a trickle | Normal flow]
- **tenant**: yes, barely a trickle, and it's on the outside wall
- **debye**: Weak flow at just one tap on an outside wall sounds like a frozen or damaged pipe. Please don't try to heat it with an open flame; it needs a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g31_tenant_corrects_themselves: Tenant corrects 'anywhere' to 'only the shower'</summary>

- **tenant**: no hot water anywhere in the flat
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: no
- **tenant**: actually the sink is warm, it's just the shower
- **debye**: Got it. Is the shower knob turned fully to hot? Some stop at 38°C until you press a small button.  [Stops at 38°C | Fully on hot]
- **tenant**: it stops at 38
- **debye**: Most shower thermostats stop at 38°C: press the small button on the knob and turn further to go hotter. Try that and tell me if it works.
- **tenant**: that was it, it's hot now
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✗ g32_off_topic_mid_diagnosis: 'thanks' and 'lol' in the middle of diagnosis</summary>

- **tenant**: Kitchen tap and shower are both cold.
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: thanks for the quick reply
- **tenant**: nobody used any
- **debye**: No problem. Are the radiators cold as well?  [Yes | No]
- **tenant**: no, warm
- **debye**: Got it. If you let the hot tap run for about two minutes, does it get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: lol
- **debye**: When you can. And after two minutes of running, does the hot tap get warm?  [Haven't tried | Warms up slowly | Stays cold]
- **tenant**: ok after a few minutes it's lukewarm, never hot
- **debye**: If the water only gets lukewarm after a long wait everywhere, the hot water circulation pump is probably failing. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ["repeat the open question after 'thanks' or 'lol'", "treat 'lol' as an answer", 'ask a new question after an off-topic message']_

</details>

<details><summary>✓ g33_hello_after_delay: 'hello?' after a delay, question repeated briefly</summary>

- **tenant**: shower is cold
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: hello?
- **debye**: No problem. And is it only the shower, or the sinks too?  [Only the shower | Everywhere]
- **tenant**: oh sorry, yes my son had a 30 minute shower before me
- **debye**: Then the hot water tank is probably just empty. It reheats in about 30 to 45 minutes; try again then and tell me if it works.
- **tenant**: It works again now, thanks!
- **debye**: Good to hear. I'll close this then.

</details>

<details><summary>✗ g34_dont_know_cant_check: 'can't check right now' moves on to the next question</summary>

- **tenant**: the hot water is gone, everywhere
- **debye**: Let's fix it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: no
- **debye**: Got it. Are the radiators cold as well?  [Yes | No]
- **tenant**: yes, cold too
- **debye**: Got it. Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.  [Shows a code | Looks normal | It's dark]
- **tenant**: [photo] [photo]
- **debye**: That error means the boiler's ignition failed (error code F.28), so the heating won't start. Since the heating and the hot water are both off, it's most likely a fault in the boiler. That needs a heating technician.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address, floor and the photos with them?  [Yes, go ahead | No]

_judge:  ['ask a fourth diagnostic question', 'mention an error code (none given)']_

</details>

<details><summary>✓ g35_question_back: 'is it dangerous?' and 'do I have to pay?'</summary>

- **tenant**: no hot water in the flat
- **debye**: Let's fix it. Quick check: is anything switched off, like the water heater's switch or fuse, the boiler's hot-water mode, a holiday or timer mode, or a valve under the sink?  [Something was off | All on | Can't check]
- **tenant**: everything's on, I checked
- **debye**: Your flat's hot water comes from the small electric heater, and since it's switched on, the heater itself most likely needs an electrician.
- **debye**: I'd like to send Elektro Klein GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✗ g36_works_again_by_itself: 'never mind, it works again' while waiting</summary>

- **tenant**: my shower is cold
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: no
- **debye**: Do you mean only the shower is cold, or are the sinks cold too?
- **tenant**: only the shower
- **debye**: Got it. Is the shower knob turned fully to hot? Some stop at 38°C until you press a small button.  [Stops at 38°C | Fully on hot]
- **tenant**: fully on hot
Also nobody used hot water just before or at the same time.
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: no, nobody's worked on it recently.
- **debye**: Since only the shower stays cold, it's most likely the shower's mixer cartridge. That's a quick job for a plumber.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

_judge:  ['send a technician']_

</details>

<details><summary>✓ g37_language_switch: Tenant switches from English to German</summary>

- **tenant**: no hot water in the shower
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: Sorry, kann ich auf Deutsch schreiben? Nein, niemand hat vorher Wasser benutzt.
- **debye**: Ja, gern. Und ist es nur die Dusche oder auch die Waschbecken?  [Nur die Dusche | Überall]
- **tenant**: Nur die Dusche, das Waschbecken ist heiß.
- **debye**: Gut. Ist der Duschregler ganz auf heiß gestellt? Manche Regler stoppen bei 38 °C, bis man einen kleinen Knopf drückt.  [Stoppt bei 38 °C | Ganz auf heiß]
- **tenant**: Der stoppt bei 38.
- **debye**: Die meisten Duschthermostate stoppen bei 38 °C: Drück den kleinen Knopf am Regler und dreh weiter, dann wird es heißer. Probier das und sag mir, ob es klappt.
- **tenant**: Ja, jetzt ist es heiß, danke.
- **debye**: Schön, dann schließe ich das hier.

</details>

<details><summary>✓ g38_typos_slang: 'showr cold af' with typos and slang</summary>

- **tenant**: showr cold af
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: sink hot tho
- **debye**: Got it. Is the shower knob turned fully to hot? Some stop at 38°C until you press a small button.  [Stops at 38°C | Fully on hot]
- **tenant**: its on max n turns fine
- **debye**: Got it. Has a plumber or anyone worked on the bathroom or the pipes recently?  [Yes | No]
- **tenant**: ya plumber was here last wk
- **debye**: Since it started right after the recent plumbing work, a hot-water valve was probably left closed. A plumber needs to reopen and test it.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g39_rude_tenant: 'this is useless, just send someone'</summary>

- **tenant**: no hot water AGAIN
- **debye**: Let's fix it. Is it only the shower, or is the hot water cold at the sinks too?  [Only the shower | Everywhere]
- **tenant**: everywhere
- **debye**: Got it. Did anyone use hot water just before or at the same time, like another shower, the dishwasher or the kitchen tap?  [Yes, just before | Yes, same time | No]
- **tenant**: seriously? this is useless, just send someone
- **debye**: Understood. I'll get a technician to look at it.
- **debye**: A heating technician needs to look at it.
- **debye**: I'd like to send Heizung Schmidt GmbH over. Is it okay if I share your name, phone number, address and floor with them?  [Yes, go ahead | No]

</details>

<details><summary>✓ g40_building_notice_active: Active maintenance notice, tenant asks if it takes longer</summary>

- **tenant**: why is there no hot water?? I need to shower before work
- **debye**: There's planned maintenance in your building today; hot water should be back by the time in the notice.
- **tenant**: is it going to take longer than that?
- **debye**: The notice says hot water should be off until 1 pm today; I don’t have an update on whether it will take longer.

</details>

