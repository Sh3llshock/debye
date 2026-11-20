#!/usr/bin/env sh
# Stage reset: wipes cases, documents, conversations and agent memory, re-seeds, rewinds the demo clock.
#   scripts/demo_reset.sh                      # local (http://localhost:8000)
#   scripts/demo_reset.sh https://debye.onrender.com
curl -fsS -X POST "${1:-${DEBYE_BASE:-http://localhost:8000}}/demo/reset" && echo " reset ok"
