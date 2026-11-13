-- =====================================================================
-- OPSFlow  -  PostgreSQL database schema  (size-limited, production style)
-- File   : opsflow/db/schema.sql
-- Matches: opsflow/backend/app/models.py (table + column names; no code changed)
-- Safe to run many times: only CREATE ... IF NOT EXISTS. It NEVER deletes rows,
-- NEVER drops columns/tables, so running it again cannot touch existing data.
-- PostgreSQL 12+.
--
-- DELETE RULES
--   deployments, access_requests, aws_issues, applications : no 'deleted' columns
--   (applications are removed with a real DELETE from the app).
--
-- SIZE RULES
--   e-mail (email, created_by, updated_by, deleted_by,
--           resolved_by, performed_by) ........ VARCHAR(50)
--   mobile number (digits only) ............... VARCHAR(10)
--   application name ......................... VARCHAR(30)
--   project (holds the application name) ..... VARCHAR(30)
--   environment .............................. VARCHAR(10)
--   person name .............................. VARCHAR(50)
--   record ids (USR-000001, DEP-000001 ...) .. VARCHAR(20)
-- =====================================================================

-- ---------- ID generators ----------
CREATE TABLE IF NOT EXISTS id_counters (
    prefix         VARCHAR(10) PRIMARY KEY,
    current_value  INTEGER     NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deployment_series (
    app_key   VARCHAR(30) PRIMARY KEY,            -- application name, lower-case
    app_name  VARCHAR(30) NOT NULL,
    series    INTEGER     NOT NULL,
    CONSTRAINT deployment_series_series_key UNIQUE (series)
);

-- ---------- Users ----------
CREATE TABLE IF NOT EXISTS users (
    id                VARCHAR(20)  PRIMARY KEY,
    name              VARCHAR(50)  NOT NULL,
    email             VARCHAR(50)  NOT NULL,
    mobile            VARCHAR(11),                         -- 10 digits
    password_hash     VARCHAR(100) NOT NULL,               -- bcrypt = 60 chars
    role              VARCHAR(10),                         -- Developer | QA | DevOps
    requested_role    VARCHAR(10),
    power             BOOLEAN      NOT NULL DEFAULT FALSE, -- DevOps "Admin" flag
    active            BOOLEAN      NOT NULL DEFAULT FALSE,
    status            VARCHAR(20)  NOT NULL DEFAULT 'PENDING', -- PENDING | APPROVED | REJECTED
    reset_otp         VARCHAR(10),
    reset_otp_expiry  BIGINT,                              -- epoch milliseconds
    preferences       JSON         NOT NULL DEFAULT '{}'::json,
    created_by        VARCHAR(50),                         -- e-mail
    created_at        TIMESTAMPTZ  DEFAULT now(),
    updated_by        VARCHAR(50),
    updated_at        TIMESTAMPTZ  DEFAULT now(),
    deleted           BOOLEAN      NOT NULL DEFAULT FALSE,
    deleted_by        VARCHAR(50),
    deleted_at        TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email  ON users (email);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_mobile ON users (mobile);

-- ---------- Deployments ----------
CREATE TABLE IF NOT EXISTS deployments (
    id                         VARCHAR(20)  PRIMARY KEY,
    project                    VARCHAR(30),                -- application name
    component                  VARCHAR(50),
    environment                VARCHAR(10),                -- DEV | QA | UAT | PROD
    date_time                  TIMESTAMPTZ,
    github_url                 VARCHAR(300),
    github_branch              VARCHAR(100),
    github_commit              VARCHAR(64),                -- SHA-1 = 40, SHA-256 = 64
    rollback_branch            VARCHAR(100),
    db_change                  BOOLEAN DEFAULT FALSE,
    db_change_details          TEXT,
    db_change_file_name        VARCHAR(100),
    db_change_file_data        TEXT,                       -- base64 data URL
    env_var_change             BOOLEAN DEFAULT FALSE,
    env_var_details            TEXT,                       -- JSON list of {key, value}
    third_party_api_change     BOOLEAN DEFAULT FALSE,
    third_party_api_details    TEXT,
    additional_info            TEXT,
    application_change_details TEXT,
    attachments                TEXT,                       -- JSON
    requester_id               VARCHAR(20),
    assigned_devops_id         VARCHAR(20),
    status                     VARCHAR(30) DEFAULT 'REQUESTED',
    rejection_reason           TEXT,
    failure_reason             TEXT,
    rollback_reason            TEXT,
    resolved_by                VARCHAR(50),                -- e-mail
    resolved_at                TIMESTAMPTZ,
    created_by                 VARCHAR(50),
    created_at                 TIMESTAMPTZ DEFAULT now(),
    updated_by                 VARCHAR(50),
    updated_at                 TIMESTAMPTZ DEFAULT now()
);

-- ---------- Access requests ----------
CREATE TABLE IF NOT EXISTS access_requests (
    id               VARCHAR(20)  PRIMARY KEY,
    access_type      VARCHAR(20),                          -- RDS, IAM, "AWS Permissions" ...
    project          VARCHAR(30),
    environment      VARCHAR(10),
    user_resource    VARCHAR(100),
    permission       VARCHAR(100),
    reason           TEXT,
    expiry_date      VARCHAR(50),
    requester_id     VARCHAR(20),
    status           VARCHAR(30) DEFAULT 'REQUESTED',
    rejection_reason TEXT,
    resolved_by      VARCHAR(50),
    resolved_at      TIMESTAMPTZ,
    created_by       VARCHAR(50),
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_by       VARCHAR(50),
    updated_at       TIMESTAMPTZ DEFAULT now()
);

-- ---------- Issues (same base shape as aws_issues, with soft-delete fields) ----------
CREATE TABLE IF NOT EXISTS issues (
    id                   VARCHAR(20) PRIMARY KEY,
    project              VARCHAR(30),
    environment          VARCHAR(10),
    date_time            TIMESTAMPTZ,
    error_message        TEXT,
    symptoms             TEXT,
    impact               TEXT,
    priority             VARCHAR(20),
    service              VARCHAR(30),
    linked_deployment_id VARCHAR(20),
    requester_id         VARCHAR(20),
    status               VARCHAR(30) DEFAULT 'OPEN',
    root_cause           TEXT,
    what_was_done        TEXT,
    resolution           TEXT,
    resolved_by          VARCHAR(50),
    resolved_at          TIMESTAMPTZ,
    created_by           VARCHAR(50),
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_by           VARCHAR(50),
    updated_at           TIMESTAMPTZ DEFAULT now(),
    deleted              BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_by           VARCHAR(50),
    deleted_at           TIMESTAMPTZ
);

-- ---------- AWS issues ----------
CREATE TABLE IF NOT EXISTS aws_issues (
    id                   VARCHAR(20) PRIMARY KEY,
    project              VARCHAR(30),
    environment          VARCHAR(10),
    date_time            TIMESTAMPTZ,
    error_message        TEXT,
    symptoms             TEXT,
    impact               TEXT,
    priority             VARCHAR(20),
    service              VARCHAR(30),                      -- EC2, S3, RDS, API Gateway, custom ...
    linked_deployment_id VARCHAR(20),
    requester_id         VARCHAR(20),
    status               VARCHAR(30) DEFAULT 'OPEN',
    root_cause           TEXT,
    what_was_done        TEXT,
    resolution           TEXT,
    resolved_by          VARCHAR(50),
    resolved_at          TIMESTAMPTZ,
    created_by           VARCHAR(50),
    created_at           TIMESTAMPTZ DEFAULT now(),
    updated_by           VARCHAR(50),
    updated_at           TIMESTAMPTZ DEFAULT now(),
    error_file_name      VARCHAR(100),
    error_file_data      TEXT,
    impact_file_name     VARCHAR(100),
    impact_file_data     TEXT
);

-- ---------- Audit log ----------
CREATE TABLE IF NOT EXISTS audit_log (
    id                VARCHAR(20) PRIMARY KEY,
    audit_action      VARCHAR(50),
    related_record_id VARCHAR(20),
    performed_by      VARCHAR(50),                         -- e-mail
    previous_value    TEXT,
    new_value         TEXT,
    reason            TEXT,
    created_by        VARCHAR(50),
    created_at        TIMESTAMPTZ DEFAULT now(),
    deleted           BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_audit_log_related_record_id ON audit_log (related_record_id);

-- ---------- Config (dropdown values: APPLICATION, ENVIRONMENT, ACCESS_TYPE) ----------
CREATE TABLE IF NOT EXISTS config (
    id           VARCHAR(20) PRIMARY KEY,
    config_key   VARCHAR(50),
    config_value VARCHAR(30),                              -- app name (30) / env (10) / access type
    created_by   VARCHAR(50),
    created_at   TIMESTAMPTZ DEFAULT now(),
    deleted      BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_config_config_key ON config (config_key);

-- ---------- In-app notifications ----------
CREATE TABLE IF NOT EXISTS notifications (
    id           VARCHAR(20)  PRIMARY KEY,
    recipient_id VARCHAR(20)  NOT NULL,
    kind         VARCHAR(30)  DEFAULT 'info',              -- deployment|access|aws|user|application|info
    title        VARCHAR(100) NOT NULL,
    message      TEXT,
    link         VARCHAR(100),
    record_id    VARCHAR(20),
    actor        VARCHAR(50),                              -- person's name
    read         BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_notifications_recipient_id ON notifications (recipient_id);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at   ON notifications (created_at);

-- ---------- Applications (added by DevOps Admin) ----------
CREATE TABLE IF NOT EXISTS applications (
    id          VARCHAR(20)  PRIMARY KEY,
    name        VARCHAR(30)  NOT NULL,
    launch_date VARCHAR(20),
    created_by  VARCHAR(50),
    created_at  TIMESTAMPTZ  DEFAULT now(),
    CONSTRAINT applications_name_key UNIQUE (name)
);

-- ---------- Performance indexes ----------
CREATE INDEX IF NOT EXISTS ix_deployments_status           ON deployments     (status);
CREATE INDEX IF NOT EXISTS ix_deployments_requester_id     ON deployments     (requester_id);
CREATE INDEX IF NOT EXISTS ix_deployments_created_at       ON deployments     (created_at);
CREATE INDEX IF NOT EXISTS ix_access_requests_status       ON access_requests (status);
CREATE INDEX IF NOT EXISTS ix_access_requests_requester_id ON access_requests (requester_id);
CREATE INDEX IF NOT EXISTS ix_access_requests_created_at   ON access_requests (created_at);
CREATE INDEX IF NOT EXISTS ix_aws_issues_status            ON aws_issues      (status);
CREATE INDEX IF NOT EXISTS ix_aws_issues_requester_id      ON aws_issues      (requester_id);
CREATE INDEX IF NOT EXISTS ix_aws_issues_created_at        ON aws_issues      (created_at);
CREATE INDEX IF NOT EXISTS ix_issues_status                ON issues          (status);
CREATE INDEX IF NOT EXISTS ix_issues_requester_id          ON issues          (requester_id);
CREATE INDEX IF NOT EXISTS ix_issues_created_at            ON issues          (created_at);
