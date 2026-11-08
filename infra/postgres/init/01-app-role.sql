-- Runs once, on first cluster initialisation, as the owner role.
--
-- Creates the application's database role. It owns nothing, is not a
-- superuser, and does not have BYPASSRLS. A table owner is exempt from its own
-- row-level policies unless the table is FORCEd *and* the connection is not
-- the owner, so this role split is half of the tenancy boundary; the other
-- half is FORCE ROW LEVEL SECURITY in the migration.
--
-- See docs/architecture/02-lld-data-model.md §8.

\set app_user `echo "${MAAIL_APP_USER:-maail_app}"`
\set app_password `echo "${MAAIL_APP_PASSWORD:-change_me_app}"`
\set db_name `echo "${POSTGRES_DB:-maail}"`

CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;

ALTER DATABASE :"db_name" SET row_security = on;

GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";

-- No CREATE on the schema: the application never issues DDL.
REVOKE CREATE ON SCHEMA public FROM :"app_user";

-- Existing objects (none yet on a fresh cluster) and everything the owner
-- creates later, so a migration cannot forget to grant.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_user";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO :"app_user";
