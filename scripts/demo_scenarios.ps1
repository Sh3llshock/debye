# Reset and load the demo scenarios: 9 realistic cases (approval pending, requested, waiting for the
# technician, scheduled, closed + invoiced, self-help, caretaker, ...) so the staff and partner pages
# look alive. Luka's unit 4b and Jonas' unit 2a stay empty for the live WhatsApp demo.
#   .\scripts\demo_scenarios.ps1                                  # local (http://localhost:8000)
#   .\scripts\demo_scenarios.ps1 https://debye.onrender.com
param([string]$Base = $(if ($env:DEBYE_BASE) { $env:DEBYE_BASE } else { "http://localhost:8000" }))
$r = Invoke-RestMethod -Method Post -Uri "$Base/demo/scenarios"
$r.cases | Format-Table case_id, status, unit_id, partner_id, scenario -AutoSize
