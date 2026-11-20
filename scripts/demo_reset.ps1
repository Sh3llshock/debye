# Stage reset: wipes cases, documents, conversations and agent memory, re-seeds, rewinds the demo clock.
#   .\scripts\demo_reset.ps1                                  # local (http://localhost:8000)
#   .\scripts\demo_reset.ps1 https://debye.onrender.com
param([string]$Base = $(if ($env:DEBYE_BASE) { $env:DEBYE_BASE } else { "http://localhost:8000" }))
Invoke-RestMethod -Method Post -Uri "$Base/demo/reset" | ConvertTo-Json -Compress
