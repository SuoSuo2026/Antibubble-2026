Set-Location -LiteralPath $PSScriptRoot
python agent_loop.py --poll-interval 15 --intake-mode prompt
