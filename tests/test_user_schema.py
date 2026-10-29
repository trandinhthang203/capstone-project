import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate


def valid_user_data(**overrides):
    data = {
        "full_name": "Editor Account",
        "email": "editor@example.com",
        "password": "secure123",
    }
    data.update(overrides)
    return data


def test_user_create_accepts_editor_role():
    user = UserCreate(**valid_user_data(role_code="editor"))

    assert user.role_code == "editor"


def test_user_create_rejects_unknown_role():
    with pytest.raises(ValidationError):
        UserCreate(**valid_user_data(role_code="unknown"))
