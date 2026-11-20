# Diagnosis: "my shower is cold"

Debye doesn't send a technician for every complaint. It diagnoses first, using the knowledge base in [`data/diagnosis/no_hot_water.json`](../data/diagnosis/no_hot_water.json): 12 causes, the questions that tell them apart, and the outcome for each.

| Outcome | Causes | Who acts |
|---|---|---|
| Emergency | gas smell | tenant leaves + gas emergency line, staff alerted |
| Self-help, no technician | tank used up, not run long enough, shower knob/limiter, planned maintenance | Debye gives the tip and checks back |
| Caretaker | low system pressure (F.22), boiler has no power | reltix caretaker; escalates to heating/electrician if it recurs |
| Plumber | shower mixer cartridge, frozen/damaged pipe | partner with trade `plumbing` |
| Heating installer | boiler fault (F.28…), circulation pump, tank thermostat/scale | partner with trade `heating` (+ boiler brand) |
| Gas utility | gas supply interrupted | staff contacts the supplier |

Strategy: safety question first → use centrix context (neighbour already reported, building notice, boiler model) → ask the one question that splits the remaining causes best → stop when one cause is clear (≤ 3 questions typical, never > 5) → tell the tenant the likely cause in plain words → record the diagnosis with its reasoning on the case → for technician outcomes, staff approve before the partner is contacted.
