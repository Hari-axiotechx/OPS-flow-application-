# OPSFlow database (manual setup)

The backend NEVER creates or alters tables. Tables come only from `db/schema.sql`.

1. Create the DB container once:   `.\scripts\1_create_db_container.ps1`
2. Run `db/schema.sql` yourself:   pgAdmin / DBeaver (Query Tool -> open schema.sql -> F5)
                                   or `.\scripts\2_run_schema.ps1`
3. Start the backend:              `.\scripts\3_run_backend.ps1`  (inserts admin user + dropdown values only)

Connection: host localhost, port 5432, db opsflow, user opsflow, password opsflow.

`schema.sql` is SAFE to run again and again: it only uses CREATE ... IF NOT EXISTS.
It contains no DELETE, DROP or TRUNCATE, so your data is never touched.
