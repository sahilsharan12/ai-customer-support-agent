import runpy
from pathlib import Path

import pytest

from backend import return_requests


@pytest.mark.parametrize(
    "module",
    (
        "test_full_return_refund_audit",
        "test_product_inspection",
        "test_refund_approval",
        "test_refund_processing",
        "test_refund_records",
        "test_return_refund_audit",
        "test_return_requests",
    ),
)
def test_legacy_sqlite_workflows(tmp_path, monkeypatch, module):
    monkeypatch.setattr(return_requests, "DB_PATH", tmp_path / "returns.db")
    return_requests.initialize_database()
    script = Path(__file__).resolve().parents[1] / "backend" / "new" / f"{module}.py"
    runpy.run_path(str(script), run_name="__main__")
