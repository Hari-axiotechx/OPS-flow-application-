# Run OPSFlow locally (manual database container)

Needs: Docker Desktop, Python 3.12, Node.js 18+, pgAdmin or DBeaver (optional).

1. Create the database container (once):      .\scripts\1_create_db_container.ps1
2. Connect pgAdmin/DBeaver: localhost:5432, db opsflow, user opsflow, password opsflow
3. Open db/schema.sql in the Query Tool and run it (F5)  -> tables are created (safe to re-run, never deletes data)
4. Backend (terminal 1):                      .\scripts\3_run_backend.ps1
   check:  curl "http://localhost:8000/api?action=ping"
5. Frontend (terminal 2):                     .\scripts\4_run_frontend.ps1
6. Open https://localhost:5173 (accept the browser warning) and log in with the admin from backend/.env

Next time: docker start opsflow-db, then steps 4 and 5.
backend/.env holds secrets - do not share it or commit it to git.
