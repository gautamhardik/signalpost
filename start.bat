@echo off
rem Serve the viewer of the latest run (out\run) at http://localhost:8000/viewer/
if not exist out\run\viewer\index.html (
  echo No run found in out\run. Run the agent first, for example:
  echo   uv run python scripts/run_competition_batch.py --organisations data/fresh_10.jsonl
  exit /b 1
)
start http://localhost:8000/viewer/
python -m http.server 8000 --directory out\run
