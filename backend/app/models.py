from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, JSON, BigInteger, Integer
)
from sqlalchemy.sql import func

from .database import Base


class IdCounter(Base):
    """One row per record-type prefix; used to generate sequential,
    zero-padded record IDs (USR-000001, DEP-000001, ...) the same way the
    original Apps Script backend did, but safely under concurrency via a
    row-level lock (see app/ids.py)."""
    __tablename__ = "id_counters"

    prefix = Column(String(10), primary_key=True)
    current_value = Column(Integer, nullable=False, default=0)


class DeploymentSeries(Base):
    """One row per application: the number its deployment IDs start from.
    Series 1 -> 1000001, 1000002 ...   Series 2 -> 2000001, 2000002 ...   (see app/ids.py)"""
    __tablename__ = "deployment_series"

    app_key = Column(String(255), primary_key=True)    # application name, lower-case
    app_name = Column(String(255), nullable=False)
    series = Column(Integer, nullable=False, unique=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String(20), primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    mobile = Column(String(20), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=True)          # Developer | QA | DevOps | '' until approved
    requested_role = Column(String(20), nullable=True)
    power = Column(Boolean, nullable=False, default=False)   # DevOps "Admin" flag
    active = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING|APPROVED|REJECTED
    reset_otp = Column(String(10), nullable=True)
    reset_otp_expiry = Column(BigInteger, nullable=True)  # epoch ms, matches original
    preferences = Column(JSON, nullable=False, default=dict)

    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(String(255))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted = Column(Boolean, nullable=False, default=False)
    deleted_by = Column(String(255), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(String(20), primary_key=True)
    project = Column(String(255))
    component = Column(String(255))
    environment = Column(String(50))
    date_time = Column(DateTime(timezone=True))
    github_url = Column(String(500))
    github_branch = Column(String(255))
    github_commit = Column(String(100))
    rollback_branch = Column(String(255))  # branch to roll back to if this deployment fails
    db_change = Column(Boolean, default=False)
    db_change_details = Column(Text)
    db_change_file_name = Column(String(255))
    db_change_file_data = Column(Text)  # base64-encoded file contents (data URL)
    env_var_change = Column(Boolean, default=False)
    env_var_details = Column(Text)  # JSON-encoded list of {key, value} pairs
    third_party_api_change = Column(Boolean, default=False)
    third_party_api_details = Column(Text)
    additional_info = Column(Text)
    application_change_details = Column(Text)
    attachments = Column(Text)  # JSON: dbFiles[], thirdPartyFiles[], thirdPartyPairs[], envFile, appChangeFile, additionalFile
    requester_id = Column(String(20))
    assigned_devops_id = Column(String(20), nullable=True)
    status = Column(String(30), default="REQUESTED")
    rejection_reason = Column(Text)
    failure_reason = Column(Text)
    rollback_reason = Column(Text)
    resolved_by = Column(String(255))
    resolved_at = Column(DateTime(timezone=True))

    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(String(255))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id = Column(String(20), primary_key=True)
    access_type = Column(String(100))
    project = Column(String(255))
    environment = Column(String(50))
    user_resource = Column(String(255))
    permission = Column(String(255))
    reason = Column(Text)
    expiry_date = Column(String(50))
    requester_id = Column(String(20))
    status = Column(String(30), default="REQUESTED")
    rejection_reason = Column(Text)
    resolved_by = Column(String(255))
    resolved_at = Column(DateTime(timezone=True))

    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(String(255))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class _IssueColumns:
    """Common record columns for Issue and AwsIssue."""
    id = Column(String(20), primary_key=True)
    project = Column(String(255))
    environment = Column(String(50))
    date_time = Column(DateTime(timezone=True))
    error_message = Column(Text)
    symptoms = Column(Text)
    impact = Column(Text)
    priority = Column(String(20))
    service = Column(String(255), nullable=True)  # AWS service the issue relates to (e.g. EC2, S3, RDS, or a custom value)
    linked_deployment_id = Column(String(20), nullable=True)
    requester_id = Column(String(20))
    status = Column(String(30), default="OPEN")
    root_cause = Column(Text)
    what_was_done = Column(Text)
    resolution = Column(Text)
    resolved_by = Column(String(255))
    resolved_at = Column(DateTime(timezone=True))

    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_by = Column(String(255))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Issue(Base, _IssueColumns):
    __tablename__ = "issues"
    deleted = Column(Boolean, nullable=False, default=False)
    deleted_by = Column(String(255), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class AwsIssue(Base, _IssueColumns):
    """AWS Issues — production incidents tied to an AWS service (EC2, S3,
    RDS, ...). Filed and managed exclusively by DevOps. Was previously
    called "Production Issue"; renamed (table included) to reflect that
    every issue here is filed against a specific AWS service."""
    __tablename__ = "aws_issues"

    # Optional files for the Error / Message and Impact boxes (used when the text is longer than
    # 500 words). base64 data URL, same idea as the deployment DB-change file.
    error_file_name = Column(String(255))
    error_file_data = Column(Text)
    impact_file_name = Column(String(255))
    impact_file_data = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String(20), primary_key=True)
    audit_action = Column(String(50))
    related_record_id = Column(String(20), index=True)
    performed_by = Column(String(255))
    previous_value = Column(Text)
    new_value = Column(Text)
    reason = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted = Column(Boolean, nullable=False, default=False)


class ConfigValue(Base):
    __tablename__ = "config"

    id = Column(String(20), primary_key=True)
    config_key = Column(String(50), index=True)
    config_value = Column(String(255))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted = Column(Boolean, nullable=False, default=False)

class Notification(Base):
    """In-app notification for one user (bell icon in the header).
    New table — created automatically on startup, no migration needed."""
    __tablename__ = "notifications"

    id = Column(String(20), primary_key=True)
    recipient_id = Column(String(20), index=True, nullable=False)
    kind = Column(String(30), default="info")      # deployment|access|aws|user|application|info
    title = Column(String(255), nullable=False)
    message = Column(Text)
    link = Column(String(255))
    record_id = Column(String(20), nullable=True)
    actor = Column(String(255))
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class Application(Base):
    """Applications added by a DevOps Admin from the Applications page.
    They are merged into config.applications, so they show up
    immediately in the Deployment / Access / AWS Issue dropdowns."""
    __tablename__ = "applications"

    id = Column(String(20), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    launch_date = Column(String(20))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
