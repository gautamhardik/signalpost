@echo off
echo Starting Signalpost local server...
start http://localhost:8000/
python -m http.server 8000 --directory ui
