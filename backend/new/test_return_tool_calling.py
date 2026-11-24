"""Manual end-to-end check of Ollama return preparation and confirmation."""

from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import auth, database_tools, memory, return_requests
from backend.main import app
from database.create_demo_db import DEMO_ORDERS, DEMO_PROFILE, create_demo_db


def main() -> None:
    with TemporaryDirectory(prefix="qwen-support-") as folder:
        data_dir = Path(folder)
        order_db = data_dir / "orders.db"
        create_demo_db(order_db)
        with (
            patch.object(auth, "DB_PATH", data_dir / "users.db"),
            patch.object(auth, "SECRET_KEY", token_urlsafe(48)),
            patch.object(memory, "DB_PATH", data_dir / "conversations.db"),
            patch.object(return_requests, "DB_PATH", data_dir / "returns.db"),
            patch.object(database_tools, "DB_PATH", order_db),
            TestClient(app) as client,
        ):
            customer = auth.register_user("smoke@example.test", token_urlsafe(24))
            auth.link_customer_identity(customer["user_id"], DEMO_PROFILE)
            headers = {"Authorization": "Bearer " + auth.create_access_token(customer)}
            order_id = DEMO_ORDERS[0]
            reply = client.post(
                "/chat", headers=headers,
                json={"message": f"Please prepare a return request for order {order_id} because I changed my mind."},
            )
            reply.raise_for_status()
            draft = reply.json()
            print(draft["assistant_response"])
            if "Reply 'confirm'" not in draft["assistant_response"]:
                raise RuntimeError("The model did not prepare a return draft.")
            assert not return_requests.get_all_return_requests()

            reply = client.post(
                "/chat", headers=headers,
                json={"message": "confirm", "conversation_id": draft["conversation_id"]},
            )
            reply.raise_for_status()
            (saved_request,) = return_requests.get_all_return_requests()
            assert saved_request["order_id"] == order_id
            print(reply.json()["assistant_response"])


if __name__ == "__main__":
    main()
