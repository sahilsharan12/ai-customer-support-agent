
import os
import sqlite3
import uuid
from contextlib import closing, contextmanager

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from backend.config import DATA_DIR


# ==========================================
# CONFIGURATION
# ==========================================

DB_PATH = DATA_DIR / "users.db"

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)

ALLOWED_ROLES = {"customer", "support_agent", "admin"}


def signing_key() -> str:
    if not SECRET_KEY or len(SECRET_KEY.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes.")
    return SECRET_KEY


# ==========================================
# DATABASE CONNECTION
# ==========================================

@contextmanager
def get_auth_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.row_factory = sqlite3.Row
        yield connection


# ==========================================
# DATABASE INITIALIZATION
# ==========================================

def initialize_auth_database():

    with get_auth_connection() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (

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
            CREATE INDEX IF NOT EXISTS idx_users_email
            ON users(email)
        """)


# ==========================================
# PASSWORD UTILITIES
# ==========================================

def hash_password(password: str):

    if not isinstance(password, str) or len(password) < 8:
        raise ValueError(
            "Password must contain at least 8 characters."
        )

    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError("Password must be at most 72 bytes in UTF-8.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str):

    encoded = plain_password.encode("utf-8")
    if len(encoded) > 72:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed_password.encode("ascii"))
    except ValueError:
        return False


# ==========================================
# USER SERIALIZATION
# ==========================================

def serialize_user(user):

    if user is None:
        return None

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "customer_unique_id": user["customer_unique_id"],
        "is_active": bool(user["is_active"]),
        "created_at": user["created_at"]
    }


# ==========================================
# REGISTER USER
# ==========================================

def register_user(
    email: str,
    password: str,
    username: str = None,
    role: str = "customer",
    customer_unique_id: str = None
):
    """
    Register a new user.

    Public customer registration must not assign an
    arbitrary Olist customer_unique_id.
    """

    if not isinstance(email, str) or not email.strip():
        raise ValueError("Valid email address is required.")

    if not isinstance(password, str):
        raise ValueError("Password is required.")

    email = email.strip().lower()

    if username is None:
        username = email.split("@")[0]

    if not isinstance(username, str) or not username.strip():
        raise ValueError("Valid username is required.")

    # Public registration only creates customer accounts.
    # Staff roles must be provisioned by an administrator.
    if role != "customer":
        raise ValueError(
            "Public registration is only allowed for customers."
        )

    # Do not allow public registration to claim an Olist identity.
    if customer_unique_id is not None:
        raise ValueError(
            "Customer identity must be linked through a verified process."
        )

    password_hash = hash_password(password)

    user_id = str(uuid.uuid4())

    created_at = datetime.now(timezone.utc).isoformat()

    try:

        with get_auth_connection() as connection:

            connection.execute(
                """
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username.strip(),
                    email,
                    password_hash,
                    "customer",
                    None,
                    1,
                    created_at
                )
            )

            user = connection.execute(
                """
                SELECT *
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            ).fetchone()

        return serialize_user(user)

    except sqlite3.IntegrityError:
        raise ValueError(
            "An account with this email already exists."
        )


# ==========================================
# GET USER BY EMAIL
# ==========================================

def get_user_by_email(email: str):

    if not isinstance(email, str) or not email.strip():
        return None

    with get_auth_connection() as connection:

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email.strip().lower(),)
        ).fetchone()

    return serialize_user(user)


# ==========================================
# GET USER BY ID
# ==========================================

def get_user_by_id(user_id: str):

    if not isinstance(user_id, str) or not user_id.strip():
        return None

    with get_auth_connection() as connection:

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id.strip(),)
        ).fetchone()

    return serialize_user(user)


def link_customer_identity(user_id: str, customer_unique_id: str) -> dict:
    """Link an account after support staff verify ownership independently."""
    with get_auth_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        user = connection.execute(
            "SELECT * FROM users WHERE user_id = ? AND role = 'customer' AND is_active = 1",
            (user_id,),
        ).fetchone()
        if user is None:
            return {"success": False, "message": "Active customer account not found."}
        if user["customer_unique_id"] == customer_unique_id:
            return serialize_user(user)
        if user["customer_unique_id"] is not None:
            return {"success": False, "message": "Customer account is already linked."}
        if connection.execute(
            "SELECT 1 FROM users WHERE customer_unique_id = ?",
            (customer_unique_id,),
        ).fetchone():
            return {"success": False, "message": "Order profile is already linked."}
        connection.execute(
            "UPDATE users SET customer_unique_id = ? WHERE user_id = ?",
            (customer_unique_id, user_id),
        )
        return {**serialize_user(user), "customer_unique_id": customer_unique_id}


# ==========================================
# AUTHENTICATE USER
# ==========================================

def authenticate_user(email: str, password: str):
    """Verify email and password."""

    if not isinstance(email, str) or not isinstance(password, str):
        return None

    with get_auth_connection() as connection:

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email.strip().lower(),)
        ).fetchone()

    if user is None:
        return None

    if not user["is_active"]:
        return None

    if not verify_password(password, user["password_hash"]):
        return None

    return serialize_user(user)


# ==========================================
# CREATE JWT ACCESS TOKEN
# ==========================================

def create_access_token(
    data: dict,
    expires_delta: timedelta = None
):

    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    encoded_token = jwt.encode(
        {"sub": str(data["user_id"]), "exp": expire},
        signing_key(),
        algorithm=ALGORITHM
    )

    return encoded_token


# ==========================================
# GET CURRENT AUTHENTICATED USER
# ==========================================

def get_current_user(
    token: str = Depends(oauth2_scheme)
):
    """Decode JWT and retrieve the authenticated user."""

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"}
    )

    try:

        payload = jwt.decode(
            token,
            signing_key(),
            algorithms=[ALGORITHM],
            options={"require_exp": True, "require_sub": True}
        )

        user_id = payload.get("sub")

        if not user_id:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = get_user_by_id(user_id)

    if user is None or not user["is_active"]:
        raise credentials_exception

    return user


# ==========================================
# ROLE-BASED ACCESS CONTROL
# ==========================================

def require_roles(*allowed_roles):

    def role_checker(
        current_user: dict = Depends(get_current_user)
    ):

        if current_user["role"] not in allowed_roles:

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource."
            )

        return current_user

    return role_checker
