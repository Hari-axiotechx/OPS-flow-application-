from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ConfigValue, User
from .ids import generate_id
from .security import hash_password
from .config import settings
from . import logic


def _add_config_if_missing(db: Session, key: str, value: str):
    exists = db.query(ConfigValue).filter(
        ConfigValue.config_key == key, ConfigValue.config_value == value
    ).first()
    if not exists:
        db.add(ConfigValue(
            id=generate_id(db, "CONFIG"), config_key=key, config_value=value,
            created_by="system", created_at=logic.now(), deleted=False,
        ))


def run_seed():
    db = SessionLocal()
    try:
        for v in logic.DEFAULT_APPS:
            _add_config_if_missing(db, "APPLICATION", v)
        for v in logic.DEFAULT_ENVS:
            _add_config_if_missing(db, "ENVIRONMENT", v)
        for v in logic.DEFAULT_ACCESS_TYPES:
            _add_config_if_missing(db, "ACCESS_TYPE", v)

        existing_admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not existing_admin:
            record_id = generate_id(db, "USER")
            ts = logic.now()
            db.add(User(
                id=record_id, name=settings.ADMIN_NAME, email=settings.ADMIN_EMAIL,
                mobile=None, password_hash=hash_password(settings.ADMIN_PASSWORD),
                role="DevOps", requested_role="DevOps", power=True, active=True,
                status="APPROVED", created_by="system", created_at=ts,
                updated_by="system", updated_at=ts, deleted=False, preferences={},
            ))
            print(f"[opsflow] Created admin user {settings.ADMIN_EMAIL} "
                  f"with password '{settings.ADMIN_PASSWORD}' — change it after first login.")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
