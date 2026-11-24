import sqlite3
from contextlib import closing

import pytest

from backend import return_requests


def test_application_audit_triggers(tmp_path, monkeypatch):
    monkeypatch.setattr(return_requests, "DB_PATH", tmp_path / "returns.db")
    return_requests.initialize_database()
    request = return_requests.create_return_request("order-demo", "RETURN", "Change of mind")

    with closing(return_requests.get_connection()) as db, db:
        for sql in (
            "UPDATE return_refund_audit_logs SET action = 'EDITED' WHERE request_id = ?",
            "DELETE FROM return_refund_audit_logs WHERE request_id = ?",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql, (request["request_id"],))

    logs = return_requests.get_return_refund_audit_logs(request_id=request["request_id"])
    assert [log["action"] for log in logs] == ["RETURN_REQUEST_CREATED"]
