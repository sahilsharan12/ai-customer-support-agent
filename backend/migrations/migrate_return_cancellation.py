import sqlite3
from datetime import datetime, timezone
from backend.config import DATA_DIR

DB_PATH = DATA_DIR / "return_requests.db"


def migrate():

    connection = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=rw", uri=True)

    try:
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'return_requests'"
        ).fetchone()
        if schema is None:
            raise RuntimeError("Return requests table does not exist.")
        if "'CANCELLED'" in schema[0]:
            print("Return cancellation migration already applied.")
            return
        # 1. CREATE DATABASE BACKUP

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = DB_PATH.parent / f"return_requests_backup_{timestamp}.db"

        backup_connection = sqlite3.connect(backup_path)

        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()

        print(f"Backup created: {backup_path}")

        # 2. DISABLE FOREIGN KEY CHECKS BEFORE TRANSACTION

        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.cursor()

        # 3. COUNT EXISTING RECORDS

        original_count = cursor.execute("""
            SELECT COUNT(*) FROM return_requests
        """).fetchone()[0]

        # 4. CREATE NEW TABLE WITH CANCELLED STATUS
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(return_requests)")}
        pending_action = "pending_action_id" if "pending_action_id" in columns else "NULL"

        cursor.execute("""
            CREATE TABLE return_requests_new (

                request_id TEXT PRIMARY KEY,

                order_id TEXT NOT NULL,

                customer_unique_id TEXT,

                request_type TEXT NOT NULL,

                reason TEXT NOT NULL,

                description TEXT,

                evidence_reference TEXT,

                status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',

                created_at TEXT NOT NULL,

                reviewed_at TEXT,

                reviewer TEXT,

                review_notes TEXT,
                pending_action_id TEXT,

                CHECK (
                    request_type IN ('RETURN', 'REFUND')
                ),

                CHECK (
                    status IN (
                        'PENDING_REVIEW',
                        'APPROVED',
                        'REJECTED',
                        'PROCESSING',
                        'COMPLETED',
                        'CANCELLED'
                    )
                )
            )
        """)

        # 5. COPY EXISTING DATA

        cursor.execute(f"""
            INSERT INTO return_requests_new (
                request_id,
                order_id,
                customer_unique_id,
                request_type,
                reason,
                description,
                evidence_reference,
                status,
                created_at,
                reviewed_at,
                reviewer,
                review_notes,
                pending_action_id
            )
            SELECT
                request_id,
                order_id,
                customer_unique_id,
                request_type,
                reason,
                description,
                evidence_reference,
                status,
                created_at,
                reviewed_at,
                reviewer,
                review_notes,
                {pending_action}
            FROM return_requests
        """)

        # 6. REPLACE OLD TABLE

        cursor.execute("DROP TABLE return_requests")

        cursor.execute("""
            ALTER TABLE return_requests_new
            RENAME TO return_requests
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX idx_return_requests_pending_action_unique
            ON return_requests(pending_action_id) WHERE pending_action_id IS NOT NULL
        """)

        # 7. VERIFY RECORD COUNT

        migrated_count = cursor.execute("""
            SELECT COUNT(*) FROM return_requests
        """).fetchone()[0]

        if original_count != migrated_count:
            raise RuntimeError(
                "Record count mismatch during migration."
            )

        # 8. VERIFY FOREIGN KEY REFERENCES

        violations = cursor.execute("""
            PRAGMA foreign_key_check
        """).fetchall()

        if violations:
            raise RuntimeError(
                f"Foreign key violations detected: {violations}"
            )

        # 9. COMMIT

        connection.commit()

        connection.execute("PRAGMA foreign_keys = ON")

        print("Migration completed successfully.")
        print(f"Original records: {original_count}")
        print(f"Migrated records: {migrated_count}")
        print("Foreign key verification: passed")

        return True

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    migrate()
