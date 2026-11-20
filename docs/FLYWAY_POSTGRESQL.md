# PostgreSQL + Flyway

Flyway owns schema evolution. Application startup does not call SQLAlchemy `create_all()`.

## Local startup
1. Copy `.env.example` to `.env` and use development-only credentials.
2. Run `docker compose up -d postgres`.
3. Run `docker compose run --rm flyway` (or `docker compose up flyway`).
4. Confirm `data_ai.flyway_schema_history` and tables exist.
5. Configure `DATABASE_URL` with `search_path=data_ai` as shown in `.env.example`.
6. Start FastAPI.

Migrations are immutable after shared use. Add `V3__...sql` for later changes; do not edit a migration that has already run in another environment. Review SQL and backup the database before production migration.

For a shared database, agree with Backend on a single Flyway owner. Recommended: Backend/Platform owns Flyway execution; DATA-AI contributes reviewed SQL migrations for the `data_ai` schema. Do not run Alembic and Flyway against the same tables.

The included Docker Compose credentials are for local development only. Production must use secrets management, least-privilege DB roles, TLS, private networking, backup/restore and a controlled migration job.
