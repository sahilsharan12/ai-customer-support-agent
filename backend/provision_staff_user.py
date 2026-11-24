
import getpass
import sqlite3
import uuid
from datetime import datetime, timezone

from backend.auth import (
    DB_PATH,
    ALLOWED_ROLES,
    hash_password,
    initialize_auth_database,
)


def create_staff_user():
    initialize_auth_database()
    print("\n=== Staff Account Provisioning ===")

    email = input("Enter staff email: ").strip().lower()
    username = input("Enter staff username: ").strip()

    if not email or "@" not in email:
        raise ValueError("Please enter a valid email address.")

    if not username:
        raise ValueError("Username cannot be empty.")

    role = input(
        "Enter role (support_agent/admin) [support_agent]: "
    ).strip().lower() or "support_agent"

    if role not in {"support_agent", "admin"}:
        raise ValueError("Invalid staff role.")

    if role not in ALLOWED_ROLES:
        raise ValueError("Role is not allowed by authentication config.")

    password = getpass.getpass("Enter password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if password != confirm_password:
        raise ValueError("Passwords do not match.")

    password_hash = hash_password(password)

    user_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    connection = sqlite3.connect(DB_PATH)

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        connection.execute("""
            INSERT INTO users (
                user_id,
                username,
                email,
                password_hash,
                role,
                customer_unique_id,
                is_active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, 1, ?)
        """, (
            user_id,
            username,
            email,
            password_hash,
            role,
            created_at
        ))

        connection.commit()

        print("\nStaff account created successfully.")
        print(f"Email: {email}")
        print(f"Role: {role}")
        print(f"User ID: {user_id}")

    except sqlite3.IntegrityError:
        connection.rollback()
        raise ValueError(
            "An account with this email already exists."
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    try:
        create_staff_user()
    except (ValueError, RuntimeError) as error:
        print(f"\nError: {error}")
