
import sqlite3
from datetime import datetime, timezone
from backend.config import DATA_DIR

DB_PATH = DATA_DIR / "users.db"


def create_backup():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.with_name(
        f"users_backup_{timestamp}.db"
    )

    source = sqlite3.connect(DB_PATH)
    destination = sqlite3.connect(backup_path)

    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    return backup_path


def migrate():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    backup_path = create_backup()
    print(f"Database backup created: {backup_path}")

    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        schema = connection.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = 'users'
        """).fetchone()

        if schema is None:
            raise RuntimeError("Users table does not exist.")

        schema_sql = schema["sql"]

        if "'support_agent'" in schema_sql:
            print("Role migration already applied.")
            return

        if "'support'" not in schema_sql:
            raise RuntimeError("Unexpected users table schema.")

        original_rows = connection.execute(
            "SELECT * FROM users ORDER BY user_id"
        ).fetchall()

        original_count = len(original_rows)

        connection.execute("BEGIN IMMEDIATE")

        connection.execute("""
            CREATE TABLE users_new (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'customer',
                customer_unique_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                CHECK (
                    role IN ('customer', 'support_agent', 'admin')
                ),
                CHECK (is_active IN (0, 1))
            )
        """)

        connection.execute("""
            INSERT INTO users_new (
                user_id, username, email, password_hash,
                role, customer_unique_id, is_active, created_at
            )
            SELECT
                user_id, username, email, password_hash,
                CASE
                    WHEN role = 'support' THEN 'support_agent'
                    ELSE role
                END,
                customer_unique_id, is_active, created_at
            FROM users
        """)

        connection.execute("DROP TABLE users")
        connection.execute(
            "ALTER TABLE users_new RENAME TO users"
        )

        connection.execute("""
            CREATE INDEX idx_users_email ON users(email)
        """)

        new_rows = connection.execute(
            "SELECT * FROM users ORDER BY user_id"
        ).fetchall()

        if len(new_rows) != original_count:
            raise RuntimeError("User count mismatch.")

        # Verify every field, allowing only the intended role rename.
        for old, new in zip(original_rows, new_rows):
            old_data = dict(old)
            new_data = dict(new)

            if old_data["role"] == "support":
                old_data["role"] = "support_agent"

            if old_data != new_data:
                raise RuntimeError(
                    f"User data mismatch for user_id: {old['user_id']}"
                )

        index_exists = connection.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_users_email'
              AND tbl_name = 'users'
        """).fetchone()

        if not index_exists:
            raise RuntimeError("Email index was not preserved.")

        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(f"Integrity check failed: {integrity}")

        connection.commit()

        print("Migration completed successfully.")
        print(f"Users preserved: {original_count}")
        print("Password hashes and other user fields verified.")
        print("Email index verified.")
        print(f"SQLite integrity: {integrity}")

    except Exception:
        connection.rollback()
        print("Migration failed. Transaction rolled back.")
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    migrate()
