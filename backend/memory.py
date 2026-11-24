
import sqlite3
import uuid
import json
from contextlib import closing, contextmanager

from datetime import datetime, timedelta, timezone
from backend.config import DATA_DIR


# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================

DB_PATH = DATA_DIR / "conversations.db"


# ==========================================
# 2. DATABASE CONNECTION
# ==========================================

@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


# ==========================================
# 3. DATABASE INITIALIZATION
# ==========================================

def initialize_database():
    """Create tables and migrate existing conversations."""

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS reply_preferences (
                user_id TEXT PRIMARY KEY,
                style TEXT NOT NULL CHECK (style IN ('concise', 'detailed'))
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                customer_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration for existing conversations table
        existing_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(conversations)"
            ).fetchall()
        }

        if "customer_id" not in existing_columns:
            connection.execute("""
                ALTER TABLE conversations
                ADD COLUMN customer_id TEXT
            """)

        # Messages table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (conversation_id)
                REFERENCES conversations(conversation_id)
                ON DELETE CASCADE,

                CHECK (role IN ('user', 'assistant'))
            )
        """)

        # Customer memory table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS customer_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(conversation_id, memory_key),

                FOREIGN KEY (conversation_id)
                REFERENCES conversations(conversation_id)
                ON DELETE CASCADE
            )
        """)

        # Pending actions table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS pending_actions (
                action_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,

                FOREIGN KEY (conversation_id)
                REFERENCES conversations(conversation_id)
                ON DELETE CASCADE
            )
        """)

        # Indexes
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
            ON messages(conversation_id, id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_customer_id
            ON conversations(customer_id)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_customer_created
            ON conversations(customer_id, created_at DESC, conversation_id DESC)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_actions_conversation
            ON pending_actions(
                conversation_id,
                customer_id,
                action_type
            )
        """)


# ==========================================
# 4. CREATE CONVERSATION
# ==========================================

def create_conversation(customer_id: str = None):
    """Create a conversation linked to an authenticated customer."""

    conversation_id = str(uuid.uuid4())

    with get_connection() as connection:

        connection.execute(
            """
            INSERT INTO conversations (
                conversation_id,
                customer_id
            )
            VALUES (?, ?)
            """,
            (conversation_id, customer_id)
        )

    return conversation_id


# ==========================================
# 5. GET CONVERSATION OWNER
# ==========================================

def get_conversation_owner(conversation_id: str):
    """Return the customer ID associated with a conversation."""

    with get_connection() as connection:

        result = connection.execute(
            """
            SELECT customer_id
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,)
        ).fetchone()

    if result is None:
        return None

    return result["customer_id"]


def get_reply_preference(user_id: str) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT style FROM reply_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["style"] if row else None


def set_reply_preference(user_id: str, style: str | None) -> None:
    with get_connection() as connection:
        if style is None:
            connection.execute("DELETE FROM reply_preferences WHERE user_id = ?", (user_id,))
        else:
            connection.execute(
                """
                INSERT INTO reply_preferences (user_id, style) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET style = excluded.style
                """,
                (user_id, style),
            )


def conversation_statistics() -> dict:
    with get_connection() as connection:
        row = connection.execute("""
            SELECT
                (SELECT COUNT(*) FROM conversations) AS conversations,
                (SELECT COUNT(*) FROM messages WHERE role = 'user') AS customer_messages,
                (SELECT COUNT(*) FROM messages WHERE role = 'assistant') AS assistant_messages
        """).fetchone()
        return dict(row)


def list_customer_conversations(user_id: str, limit: int) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT conversation_id, created_at
            FROM conversations
            WHERE customer_id = ?
            ORDER BY created_at DESC, conversation_id DESC
            LIMIT ?
        """, (user_id, limit))
        return [dict(row) for row in rows]


def get_conversation_page(conversation_id: str, limit: int, offset: int) -> tuple[list[dict], int]:
    with get_connection() as connection:
        connection.execute("BEGIN")
        total = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
        messages = connection.execute("""
            SELECT role, content FROM messages WHERE conversation_id = ?
            ORDER BY id LIMIT ? OFFSET ?
        """, (conversation_id, limit, offset))
        return [dict(message) for message in messages], total


# ==========================================
# 6. ADD MESSAGE
# ==========================================

def add_message(conversation_id: str, role: str, content: str):
    """Store a customer or assistant message."""

    if role not in ("user", "assistant"):
        raise ValueError("Invalid message role.")

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Message content cannot be empty.")

    with get_connection() as connection:

        conversation = connection.execute(
            """
            SELECT 1
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,)
        ).fetchone()

        if conversation is None:
            raise ValueError("Conversation not found.")

        connection.execute(
            """
            INSERT INTO messages (
                conversation_id,
                role,
                content
            )
            VALUES (?, ?, ?)
            """,
            (conversation_id, role, content)
        )


# ==========================================
# 7. GET COMPLETE CONVERSATION
# ==========================================

def get_conversation(conversation_id: str):
    """Retrieve complete conversation history."""

    with get_connection() as connection:

        conversation = connection.execute(
            """
            SELECT conversation_id
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,)
        ).fetchone()

        if conversation is None:
            return None

        messages = connection.execute(
            """
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,)
        ).fetchall()

    return [
        {
            "role": message["role"],
            "content": message["content"]
        }
        for message in messages
    ]


# ==========================================
# 8. GET RECENT HISTORY
# ==========================================

def get_recent_history(conversation_id: str, limit: int = 10):
    """Retrieve recent messages in chronological order."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("Limit must be a positive integer.")

    with get_connection() as connection:

        messages = connection.execute(
            """
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, limit)
        ).fetchall()

    return [
        {
            "role": message["role"],
            "content": message["content"]
        }
        for message in reversed(messages)
    ]


# ==========================================
# 9. CUSTOMER MEMORY
# ==========================================

def save_customer_memory(
    conversation_id: str,
    memory_key: str,
    memory_value: str
):
    """Save or update customer memory."""

    with get_connection() as connection:

        connection.execute(
            """
            INSERT INTO customer_memory (
                conversation_id,
                memory_key,
                memory_value
            )
            VALUES (?, ?, ?)

            ON CONFLICT(conversation_id, memory_key)
            DO UPDATE SET
                memory_value = excluded.memory_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (conversation_id, memory_key, memory_value)
        )


def get_customer_memory(conversation_id: str):
    """Retrieve customer memory."""

    with get_connection() as connection:

        memories = connection.execute(
            """
            SELECT memory_key, memory_value
            FROM customer_memory
            WHERE conversation_id = ?
            """,
            (conversation_id,)
        ).fetchall()

    return {
        memory["memory_key"]: memory["memory_value"]
        for memory in memories
    }


def delete_customer_memory(conversation_id: str, memory_key: str):
    """Delete a specific customer memory."""

    with get_connection() as connection:

        connection.execute(
            """
            DELETE FROM customer_memory
            WHERE conversation_id = ?
            AND memory_key = ?
            """,
            (conversation_id, memory_key)
        )


# ==========================================
# 10. SAVE PENDING ACTION
# ==========================================

def save_pending_action(
    conversation_id: str,
    customer_id: str,
    action_type: str,
    payload: dict,
    expiry_minutes: int = 10
):
    """
    Save an action awaiting explicit customer confirmation.

    Example:
        action_type = CREATE_RETURN

        payload = {
            "order_id": "...",
            "request_type": "RETURN",
            "reason": "Damaged product",
            "description": None,
            "evidence_reference": None
        }
    """

    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary.")

    if not isinstance(customer_id, str) or not customer_id.strip():
        raise ValueError("Valid customer ID is required.")

    if not isinstance(action_type, str) or not action_type.strip():
        raise ValueError("Action type is required.")

    if (
        isinstance(expiry_minutes, bool)
        or not isinstance(expiry_minutes, int)
        or expiry_minutes <= 0
    ):
        raise ValueError("Expiry must be a positive integer.")

    action_id = str(uuid.uuid4())

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=expiry_minutes)
    ).isoformat()

    with get_connection() as connection:

        # Verify that this conversation belongs to this customer.
        conversation = connection.execute(
            """
            SELECT 1
            FROM conversations
            WHERE conversation_id = ?
            AND customer_id = ?
            """,
            (conversation_id, customer_id)
        ).fetchone()

        if conversation is None:
            raise ValueError("Conversation ownership verification failed.")

        # Remove any previous pending action for this conversation.
        connection.execute(
            """
            DELETE FROM pending_actions
            WHERE conversation_id = ?
            AND customer_id = ?
            AND action_type = ?
            """,
            (conversation_id, customer_id, action_type)
        )

        # Store the new pending action.
        connection.execute(
            """
            INSERT INTO pending_actions (
                action_id,
                conversation_id,
                customer_id,
                action_type,
                payload,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                action_id,
                conversation_id,
                customer_id,
                action_type,
                json.dumps(payload),
                expires_at
            )
        )

    return action_id


# ==========================================
# 11. GET PENDING ACTION
# ==========================================

def get_pending_action(
    conversation_id: str,
    customer_id: str,
    action_type: str
):
    """
    Retrieve a valid pending action without consuming it.
    Expired actions are automatically deleted.
    """

    if not customer_id or not conversation_id or not action_type:
        return None

    with get_connection() as connection:

        result = connection.execute(
            """
            SELECT
                action_id,
                payload,
                expires_at
            FROM pending_actions
            WHERE conversation_id = ?
            AND customer_id = ?
            AND action_type = ?
            """,
            (
                conversation_id,
                customer_id,
                action_type
            )
        ).fetchone()

        if result is None:
            return None

        expires_at = datetime.fromisoformat(result["expires_at"])

        if datetime.now(timezone.utc) >= expires_at:

            connection.execute(
                """
                DELETE FROM pending_actions
                WHERE action_id = ?
                """,
                (result["action_id"],)
            )

            return None

        try:
            payload = json.loads(result["payload"])
        except (json.JSONDecodeError, TypeError):
            connection.execute(
                """
                DELETE FROM pending_actions
                WHERE action_id = ?
                """,
                (result["action_id"],)
            )
            return None

    return {
        "action_id": result["action_id"],
        "payload": payload
    }


# ==========================================
# 12. CONSUME PENDING ACTION
# ==========================================

def consume_pending_action(
    action_id: str,
    conversation_id: str,
    customer_id: str
):
    """
    Atomically consume a pending action exactly once.

    Returns the saved payload if successful.
    Returns None if the action is missing, expired,
    or has already been consumed.
    """

    if not action_id or not conversation_id or not customer_id:
        return None

    with get_connection() as connection:

        # Acquire a write lock before reading and deleting.
        connection.execute("BEGIN IMMEDIATE")

        result = connection.execute(
            """
            SELECT payload, expires_at
            FROM pending_actions
            WHERE action_id = ?
            AND conversation_id = ?
            AND customer_id = ?
            """,
            (
                action_id,
                conversation_id,
                customer_id
            )
        ).fetchone()

        if result is None:
            return None

        expires_at = datetime.fromisoformat(result["expires_at"])

        if datetime.now(timezone.utc) >= expires_at:

            connection.execute(
                """
                DELETE FROM pending_actions
                WHERE action_id = ?
                """,
                (action_id,)
            )

            return None

        try:
            payload = json.loads(result["payload"])
        except (json.JSONDecodeError, TypeError):
            connection.execute(
                """
                DELETE FROM pending_actions
                WHERE action_id = ?
                """,
                (action_id,)
            )

            return None

        connection.execute(
            """
            DELETE FROM pending_actions
            WHERE action_id = ?
            AND conversation_id = ?
            AND customer_id = ?
            """,
            (
                action_id,
                conversation_id,
                customer_id
            )
        )

    return payload


# ==========================================
# 13. DELETE CONVERSATION
# ==========================================

def delete_conversation(conversation_id: str):
    """Delete a conversation and its associated records."""

    with get_connection() as connection:

        connection.execute(
            """
            DELETE FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,)
        )
