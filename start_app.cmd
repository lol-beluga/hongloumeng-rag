@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment missing. See README.md for installation.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m streamlit run streamlit_app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
pause
