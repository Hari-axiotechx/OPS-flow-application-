# Optional: runs db/schema.sql from the command line (you can also run it in pgAdmin / DBeaver).
# Run from the project root:  .\scripts\2_run_schema.ps1
docker cp db/schema.sql opsflow-db:/tmp/schema.sql
docker exec opsflow-db psql -U opsflow -d opsflow -f /tmp/schema.sql
docker exec opsflow-db psql -U opsflow -d opsflow -c "\dt"
