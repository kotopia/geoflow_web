BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    name_display text NULL,
    is_active boolean NOT NULL DEFAULT false,
    email_verified boolean NOT NULL DEFAULT false,
    is_staff boolean NOT NULL DEFAULT false,
    mfa_enabled boolean NOT NULL DEFAULT false,
    last_login timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS groups (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL DEFAULT '',
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS permissions (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id bigserial PRIMARY KEY,
    role_id uuid NOT NULL REFERENCES roles(id),
    permission_id uuid NOT NULL REFERENCES permissions(id),
    UNIQUE (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS user_group_map (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    group_id uuid NOT NULL REFERENCES groups(id),
    role_id uuid NOT NULL REFERENCES roles(id),
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, group_id)
);

CREATE TABLE IF NOT EXISTS group_db_config (
    group_id uuid PRIMARY KEY REFERENCES groups(id),
    db_alias text NOT NULL UNIQUE,
    db_name text NOT NULL,
    db_host text NOT NULL,
    db_port integer NOT NULL,
    db_user text NOT NULL,
    db_password text NOT NULL
);

CREATE TABLE IF NOT EXISTS join_requests (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    group_id uuid NOT NULL REFERENCES groups(id),
    requested_email text NOT NULL,
    requested_role_code text NULL,
    status text NOT NULL,
    decided_at timestamptz NULL,
    decided_by uuid NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, group_id, requested_email)
);

COMMIT;
