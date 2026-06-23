@echo off
cd /d "%~dp0"
python agent_loop.py --poll-interval 15 --intake-mode prompt
