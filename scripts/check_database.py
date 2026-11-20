"""Check PostgreSQL connectivity and Flyway-managed DATA-AI tables."""
from sqlalchemy import text
from app.database import get_engine

REQUIRED_TABLES = {
    "customer_profiles", "customer_addresses", "customer_employments", "loan_applications",
    "staff_users", "access_roles", "staff_user_roles", "management_audit_logs",
    "cases", "documents", "extracted_fields", "transactions", "export_jobs",
}


def main():
    with get_engine().connect() as connection:
        latest = connection.execute(text(
            "SELECT version, description, success FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 1"
        )).mappings().first()
        if not latest or not latest["success"]:
            raise SystemExit("Flyway history missing or latest migration failed")
        rows = connection.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='data_ai'"
        )).scalars().all()
        missing = sorted(REQUIRED_TABLES - set(rows))
        if missing:
            raise SystemExit("Missing tables: " + ", ".join(missing))
        print(f"PostgreSQL OK. Latest Flyway version: {latest['version']} ({latest['description']})")
        print(f"Required DATA-AI tables present: {len(REQUIRED_TABLES)}")

if __name__ == "__main__":
    main()
