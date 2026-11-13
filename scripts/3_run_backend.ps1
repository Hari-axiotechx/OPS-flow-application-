# Start the DB container (if stopped) and the backend. Run from the project root.
docker start opsflow-db
Set-Location backend
if (-not (Test-Path venv)) { py -3.12 -m venv venv }
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
