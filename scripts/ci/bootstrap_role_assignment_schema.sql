BEGIN;

CREATE TABLE users (
    id uuid PRIMARY KEY,
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    is_active boolean NOT NULL DEFAULT false,
    email_verified boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE groups (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL DEFAULT '',
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL DEFAULT ''
);

-- Deliberately omit UNIQUE(user_id, group_id). Production legacy generations may
-- not have that constraint, and the assignment hotfix must not depend on it.
CREATE TABLE user_group_map (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id),
    group_id uuid NOT NULL REFERENCES groups(id),
    role_id uuid NOT NULL REFERENCES roles(id),
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
