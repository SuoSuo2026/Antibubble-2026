@echo off
cd /d "%~dp0"
python run_dashboard.py --host 127.0.0.1 --port 8765
