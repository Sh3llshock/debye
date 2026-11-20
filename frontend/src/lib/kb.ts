// Generated from data/diagnosis/no_hot_water.json (the diagnosis KB). Fallback only:
// used when the API's diagnosis lacks outcome/cost or sends questions as ids ("q_scope=everywhere").
// Regenerate if the KB changes.
export const KB_CAUSES: Record<string, { outcome: string; trade: string | null; cost: number | null }> = {
  "hot_water_used_up": {
    "outcome": "self_help",
    "trade": null,
    "cost": null
  },
  "not_run_long_enough": {
    "outcome": "self_help",
    "trade": null,
    "cost": null
  },
  "shower_knob_or_limiter": {
    "outcome": "self_help",
    "trade": null,
    "cost": null
  },
  "shower_mixer_faulty": {
    "outcome": "technician",
    "trade": "plumbing",
    "cost": 180
  },
  "boiler_fault": {
    "outcome": "technician",
    "trade": "heating",
    "cost": 263
  },
  "low_system_pressure": {
    "outcome": "caretaker",
    "trade": "caretaker",
    "cost": 0
  },
  "circulation_pump_faulty": {
    "outcome": "technician",
    "trade": "heating",
    "cost": 320
  },
  "tank_thermostat_or_scale": {
    "outcome": "technician",
    "trade": "heating",
    "cost": 240
  },
  "no_power_to_boiler": {
    "outcome": "caretaker",
    "trade": "caretaker",
    "cost": null
  },
  "gas_supply_interrupted": {
    "outcome": "utility",
    "trade": "gas_utility",
    "cost": null
  },
  "planned_maintenance": {
    "outcome": "self_help",
    "trade": null,
    "cost": null
  },
  "frozen_or_damaged_pipe": {
    "outcome": "technician",
    "trade": "plumbing",
    "cost": 220
  },
  "simultaneous_use": {
    "outcome": "self_help",
    "trade": null,
    "cost": null
  },
  "diverter_valve_stuck": {
    "outcome": "technician",
    "trade": "heating",
    "cost": 290
  },
  "supply_valve_closed_after_work": {
    "outcome": "technician",
    "trade": "plumbing",
    "cost": 95
  },
  "boiler_schedule_or_settings": {
    "outcome": "caretaker",
    "trade": "caretaker",
    "cost": null
  },
  "electric_instant_heater": {
    "outcome": "technician",
    "trade": "electrical",
    "cost": 160
  }
}

export const KB_QUESTIONS: Record<string, { text: string; answers: Record<string, string> }> = {
  "q_scope": {
    "text": "Is it only the shower, or is the hot water cold at the sinks too?",
    "answers": {
      "only_shower": "only the shower is cold, sinks are hot",
      "everywhere": "cold or lukewarm everywhere"
    }
  },
  "q_radiators": {
    "text": "Are the radiators cold as well?",
    "answers": {
      "yes": "radiators cold too",
      "no": "radiators are warm"
    }
  },
  "q_recent_use": {
    "text": "Did someone else shower or use a lot of hot water just before you?",
    "answers": {
      "yes": "others used hot water just before",
      "no": "nobody used much hot water"
    }
  },
  "q_waited": {
    "text": "Did you let the hot water run for one or two minutes?",
    "answers": {
      "yes": "ran it 1–2 minutes",
      "no": "only briefly"
    }
  },
  "q_display": {
    "text": "Could you send a photo of the boiler's display? It usually shows an error code if something's wrong.",
    "answers": {
      "code": "display shows an error code (read from photo)",
      "normal": "display looks normal",
      "dark": "display is dark / off"
    }
  },
  "q_power": {
    "text": "Are the lights and other electrics working in your apartment?",
    "answers": {
      "yes": "power is on",
      "no": "power is off"
    }
  },
  "q_gas_stove": {
    "text": "If you have a gas stove: does it light normally?",
    "answers": {
      "yes": "gas stove works",
      "no": "gas stove doesn't light",
      "none": "no gas stove"
    }
  },
  "q_knob": {
    "text": "Could you check the shower's temperature knob: is it turned fully to warm, and is there a safety button at 38°C you need to press to go hotter?",
    "answers": {
      "was_wrong": "knob was set too cold / limiter",
      "correct": "knob is fully on warm"
    }
  },
  "q_pressure": {
    "text": "On the boiler there's a small pressure gauge. Is the needle below 1 bar?",
    "answers": {
      "low": "pressure below 1 bar",
      "ok": "pressure 1–2 bar"
    }
  },
  "q_timing": {
    "text": "Does the water eventually get warm if you wait longer, or does it stay cold?",
    "answers": {
      "slow": "gets lukewarm after a long wait",
      "stays_cold": "stays cold"
    }
  },
  "q_weather_pipe": {
    "text": "Is it just this one tap, with very weak flow, maybe on an outside wall?",
    "answers": {
      "yes": "one tap, weak flow, outside wall",
      "no": "flow is normal"
    }
  },
  "q_other_tap": {
    "text": "Was another shower, the dishwasher or a hot tap running at the same time?",
    "answers": {
      "yes": "another hot tap or appliance was running",
      "no": "nothing else was running"
    }
  },
  "q_recent_work": {
    "text": "Has a plumber or anyone worked on the bathroom or the pipes recently?",
    "answers": {
      "yes": "plumbing work happened recently",
      "no": "no recent work"
    }
  },
  "q_handle_feel": {
    "text": "When you turn the shower handle towards hot, does it feel normal, or does it slip or hit a hard stop early?",
    "answers": {
      "slips_or_stops": "handle slips or stops early",
      "normal": "handle turns normally"
    }
  },
  "q_heater_type": {
    "text": "Is there a small electric water heater box on the wall in your bathroom or kitchen?",
    "answers": {
      "yes": "electric instantaneous heater in the flat",
      "no": "no heater box"
    }
  }
}
