# Run ONCE. Creates the PostgreSQL container (empty database, no tables).
docker run -d --name opsflow-db `
  -e POSTGRES_USER=opsflow `
  -e POSTGRES_PASSWORD=opsflow `
  -e POSTGRES_DB=opsflow `
  -p 5432:5432 `
  -v opsflow_pgdata:/var/lib/postgresql/data `
  postgres:16-alpine
docker ps --filter name=opsflow-db
