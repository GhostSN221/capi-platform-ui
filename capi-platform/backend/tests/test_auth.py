from jose import jwt

from app.config import settings
from app.services.auth import create_token, hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True


def test_wrong_password_is_rejected():
    hashed = hash_password("demo")
    assert verify_password("not-demo", hashed) is False


def test_token_contains_subject_and_admin_claim():
    token = create_token({"sub": "42", "admin": True})
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert payload["sub"] == "42"
    assert payload["admin"] is True
    assert "exp" in payload
