\encoding UTF8
\getenv dev_login_password GEOFLOW_DEV_LOGIN_PASSWORD

-- GeoFlow non-production central/auth synthetic seed.
-- No real customer/user data. Password arrives only through a transient process environment variable.

BEGIN;

DO $$
BEGIN
    IF current_database() !~* '(dev|test)' THEN
        RAISE EXCEPTION 'Safety stop: central synthetic seed may run only in dev/test DB. Current DB=%', current_database();
    END IF;
    IF to_regclass('public.users') IS NULL
       OR to_regclass('public.groups') IS NULL
       OR to_regclass('public.roles') IS NULL
       OR to_regclass('public.permissions') IS NULL
       OR to_regclass('public.user_group_map') IS NULL
       OR to_regclass('public.group_db_config') IS NULL THEN
        RAISE EXCEPTION 'Central development schema is incomplete.';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM roles r
        JOIN role_permissions rp ON rp.role_id = r.id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE r.code='tenant_admin' AND p.code='maps.view'
    ) THEN
        RAISE EXCEPTION 'Copied authorization catalog does not provide tenant_admin -> maps.view.';
    END IF;
END
$$;

-- Synthetic verified user. bcrypt is accepted by the current login verifier and
-- the first successful login may rehash it to the current Django PBKDF2 format.
INSERT INTO users(
    id, email, password_hash, is_active, is_staff, email_verified, created_at, updated_at
)
VALUES (
    '90000000-0000-4000-8000-000000000101'::uuid,
    :'test_email',
    crypt(:'dev_login_password', gen_salt('bf', 12)),
    TRUE,
    TRUE,
    TRUE,
    now(), now()
)
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    password_hash = EXCLUDED.password_hash,
    is_active = TRUE,
    is_staff = TRUE,
    email_verified = TRUE,
    updated_at = now();

INSERT INTO groups(id, code, name, status, created_at, updated_at)
VALUES (
    '90000000-0000-4000-8000-000000000201'::uuid,
    'GIS_DEV',
    'GeoFlow GIS Development',
    'active',
    now(), now()
)
ON CONFLICT (id) DO UPDATE SET
    code = EXCLUDED.code,
    name = EXCLUDED.name,
    status = 'active',
    updated_at = now();

-- The test server uses the static tenant alias configured from environment.
-- Therefore no real tenant DB password is stored in central development metadata.
INSERT INTO group_db_config(
    group_id, db_alias, db_name, db_host, db_port, db_user, db_password
)
VALUES (
    '90000000-0000-4000-8000-000000000201'::uuid,
    :'tenant_db_alias',
    :'tenant_db_name',
    'STATIC_ENV_ONLY',
    5432,
    'STATIC_ENV_ONLY',
    'STATIC_ENV_ONLY'
)
ON CONFLICT (group_id) DO UPDATE SET
    db_alias = EXCLUDED.db_alias,
    db_name = EXCLUDED.db_name,
    db_host = EXCLUDED.db_host,
    db_port = EXCLUDED.db_port,
    db_user = EXCLUDED.db_user,
    db_password = EXCLUDED.db_password;

INSERT INTO user_group_map(
    id, user_id, group_id, role_id, status, created_at, updated_at
)
SELECT
    '90000000-0000-4000-8000-000000000301'::uuid,
    '90000000-0000-4000-8000-000000000101'::uuid,
    '90000000-0000-4000-8000-000000000201'::uuid,
    r.id,
    'active',
    now(), now()
FROM roles r
WHERE r.code='tenant_admin'
LIMIT 1
ON CONFLICT (user_id, group_id) DO UPDATE SET
    role_id = EXCLUDED.role_id,
    status = 'active',
    updated_at = now();

COMMIT;
