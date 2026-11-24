from secrets import token_urlsafe

import pytest
from fastapi import HTTPException

from backend import auth


def test_registration_login_token_and_revocation(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setattr(auth, "SECRET_KEY", token_urlsafe(48))
    auth.initialize_auth_database()

    password = token_urlsafe(24)
    user = auth.register_user("customer@example.test", password)
    assert auth.authenticate_user(user["email"], token_urlsafe(24)) is None
    assert auth.authenticate_user(user["email"], password) == user
    token = auth.create_access_token(user)
    assert auth.get_current_user(token) == user

    with auth.get_auth_connection() as db:
        db.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user["user_id"],))
    with pytest.raises(HTTPException) as error:
        auth.get_current_user(token)
    assert error.value.status_code == 401
