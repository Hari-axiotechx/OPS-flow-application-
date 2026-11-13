from mangum import Mangum
from app.main import app

# lifespan="off": startup tasks are skipped on Lambda (tables come from db/schema.sql,
# admin user is seeded once from EC2 with: python -c "from app.seed import run_seed; run_seed()")
handler = Mangum(app, lifespan="off")
