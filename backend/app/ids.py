"""
Generates the same human-readable record IDs the Apps Script backend used
(e.g. DEP-000123), but backed by a row in `id_counters` that is locked
with SELECT ... FOR UPDATE so concurrent requests never hand out the same
number (Postgres does the job LockService used to do in Apps Script).
"""
from sqlalchemy.orm import Session
from sqlalchemy import text

from .models import IdCounter, DeploymentSeries

PREFIXES = {
    "USER": "USR",
    "DEPLOYMENT": "DEP",
    "ACCESS": "ACC",
    "ISSUE": "ISS",
    "AWS_ISSUE": "AWS",
    "AUDIT": "AUD",
    "CONFIG": "CFG",
    "NOTIFICATION": "NTF",
    "APPLICATION": "APP",
}


def generate_id(db: Session, record_type: str) -> str:
    prefix = PREFIXES[record_type]
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": prefix})
    counter = db.get(IdCounter, prefix)
    if counter is None:
        counter = IdCounter(prefix=prefix, current_value=0)
        db.add(counter)
        db.flush()
    counter.current_value += 1
    db.flush()
    return f"{prefix}-{counter.current_value:06d}"


# The four built-in applications keep a fixed series number; any application an admin adds later
# gets the next free number (5, 6, 7 ...) the first time a deployment is raised for it.
FIXED_SERIES = {"pg-desk": 1, "stylo-customer": 2, "stylo-captain": 3, "axiokidz": 4}
SERIES_SIZE = 1_000_000


def series_for_app(db: Session, project: str) -> int:
    """Series number of an application (created on first use). Caller holds the advisory lock."""
    key = str(project or "").strip().lower()
    row = db.get(DeploymentSeries, key)
    if row:
        return row.series
    if key in FIXED_SERIES:
        n = FIXED_SERIES[key]
    else:
        used = [r[0] for r in db.query(DeploymentSeries.series).all()]
        n = max([4] + used) + 1
    db.add(DeploymentSeries(app_key=key, app_name=str(project).strip(), series=n))
    db.flush()
    return n


def generate_deployment_id(db: Session, project: str) -> str:
    """Per-application deployment id:  PG-Desk -> DEP-1000001, DEP-1000002 ...
    Stylo-Customer -> DEP-2000001 ...  Safe under concurrency (advisory lock)."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:p))"), {"p": "DEPLOYMENT_SERIES"})
    n = series_for_app(db, project)
    prefix = f"DEP{n}"                      # id_counters key, e.g. DEP1, DEP2
    counter = db.get(IdCounter, prefix)
    if counter is None:
        counter = IdCounter(prefix=prefix, current_value=0)
        db.add(counter)
        db.flush()
    counter.current_value += 1
    db.flush()
    return f"DEP-{n * SERIES_SIZE + counter.current_value:07d}"


def type_from_id(record_id: str) -> str:
    prefix = str(record_id).split("-")[0]
    for t, p in PREFIXES.items():
        if p == prefix:
            return t
    raise ValueError(f"Unrecognized record id: {record_id}")