@echo off
rem One click: research a 10-company sample if no run exists yet, then open the viewer.
setlocal
cd /d "%~dp0"

if not exist out\run\viewer\index.html (
  where uv >nul 2>nul || (
    echo uv is not installed. Install it from https://docs.astral.sh/uv/ and run this again.
    pause
    exit /b 1
  )
  echo No run found yet. Researching the 10-company sample in data\fresh_10.jsonl - this takes a few minutes the first time...
  uv run python scripts\run_competition_batch.py --organisations data\fresh_10.jsonl --output-dir out\run
  if not exist out\run\viewer\index.html (
    echo The run did not produce a viewer. See the messages above.
    pause
    exit /b 1
  )
)

echo Opening the viewer at http://localhost:8000/viewer/ - close this window to stop it.
rem Give the local server a moment to start before the browser asks for the page.
start "" /min cmd /c "ping -n 3 127.0.0.1 >nul & start http://localhost:8000/viewer/"
uv run python -m http.server 8000 --directory out\run
