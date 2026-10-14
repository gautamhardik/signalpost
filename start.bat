@echo off
rem One click: start local server and open the Signalpost workspace viewer.
setlocal
cd /d "%~dp0"

echo Starting Signalpost Workspace at http://localhost:8000/ ...
start "" /min cmd /c "ping -n 2 127.0.0.1 >nul & start http://localhost:8000/"

where uv >nul 2>nul && (
  uv run python -m http.server 8000 --directory ui
) || (
  python -m http.server 8000 --directory ui
)
