# Planner experiment: A/B (parked)

`PLANNER_ENABLED=1` (default off): a holding message, then gpt-6-sol (reasoning low) plans the diagnosis.
Gold eval, 40 conversations × 3 passes per arm, run one after the other on 2026-11-21.

| | Planner off | Planner on |
|---|---|---|
| Right cause | 105/120 (88%) | 104/120 (87%) |
| All checks passed | 86/120 (72%) | 66/120 (55%) |
| Right outcome | 112/120 | 111/120 |
| Average diagnostic questions | 1.72 | 1.74 |
| No invented facts | 113/120 | 111/120 |
| must_not clean | 90/120 | 82/120 |
| Tone (judge, 1-5) | 4.16 | 3.65 |
| First Debye message | 4.6 s | 0.08 s (holding message) |
| First real reply (first turn) | 5.2 s | 8.8 s |
| Average turn | 4.3 s | 5.9 s |
| Planner calls per conversation | 0 | 1.27 (incl. re-plans), 5.0 s each, 0 errors |
| Planner tokens per conversation | 0 | 5,704 in / 651 out |

Result: no gain in finding the cause, and worse tone, all-checks rate and latency. The holding message
makes the first message instant, but the first real answer comes 3.6 s later than without the planner.
Cost: 5.7k input + 0.65k output gpt-6-sol tokens per conversation (multiply by the account's price).
