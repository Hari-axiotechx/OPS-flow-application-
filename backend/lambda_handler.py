import os
from urllib.parse import quote_plus

# Build DATABASE_URL before the app is imported.
# 1) If DATABASE_URL is already set in Lambda environment variables, use it as is.
# 2) Otherwise build it from DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMA.
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "postgresql+psycopg2://"
        f"{quote_plus(os.environ['DB_USER'])}:{quote_plus(os.environ['DB_PASSWORD'])}"
        f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', '5432')}"
        f"/{os.environ['DB_NAME']}"
        f"?options=-csearch_path%3D{os.environ.get('DB_SCHEMA', 'opsflow')}"
    )

from mangum import Mangum
from app.main import app

# lifespan="off": startup tasks are skipped on Lambda (tables come from db/schema.sql,
# admin user is seeded once from EC2 with: python -c "from app.seed import run_seed; run_seed()")
handler = Mangum(app, lifespan="off")
