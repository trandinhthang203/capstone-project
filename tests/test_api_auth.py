from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.api_auth import router
from app.core.security import decode_token
from app.services.user_service import UserService


def make_user(**overrides):
    values = {
        "id": uuid4(),
        "full_name": "Nguyễn Văn A",
        "email": "user@example.com",
        "phone": "0909000000",
        "is_active": True,
        "token_version": 0,
        "role": SimpleNamespace(code="user", name="User"),
        "created_at": datetime.now(timezone.utc),
        "last_login_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeUserService:
    def __init__(self):
        self.user = make_user()
        self.created_data = None
        self.created_role = None
        self.login_credentials = None
        self.create_error = None
        self.login_error = None

    def create_user(self, data, role_code="user"):
        if self.create_error:
            raise self.create_error
        self.created_data = data
        self.created_role = role_code
        self.user.full_name = data.full_name
        self.user.email = data.email
        self.user.phone = data.phone
        return self.user

    def authenticate(self, email, password):
        self.login_credentials = (email, password)
        if self.login_error:
            raise self.login_error
        if not self.user.is_active or password != "secure123":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email hoặc mật khẩu không đúng",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return self.user


@pytest.fixture
def auth_api():
    app = FastAPI()
    app.include_router(router, prefix="/auth")
    service = FakeUserService()
    app.dependency_overrides[UserService] = lambda: service
    with TestClient(app) as client:
        yield client, service


def test_register_returns_201_and_normalizes_input(auth_api):
    client, service = auth_api

    response = client.post(
        "/auth/register",
        json={
            "full_name": "  Nguyễn   Văn A  ",
            "email": " USER@Example.COM ",
            "password": "secure123",
            "phone": " 0909000000 ",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["email"] == "user@example.com"
    assert response.json()["full_name"] == "Nguyễn Văn A"
    assert "password" not in response.json()
    assert service.created_data.email == "user@example.com"
    assert service.created_role == "user"


def test_register_cannot_self_assign_admin_role(auth_api):
    client, service = auth_api

    response = client.post(
        "/auth/register",
        json={
            "full_name": "Nguyễn Văn A",
            "email": "user@example.com",
            "password": "secure123",
            "role_code": "admin",
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert service.created_role == "user"
    assert response.json()["role"]["code"] == "user"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "full_name": "Nguyễn Văn A",
            "email": "not-an-email",
            "password": "secure123",
        },
        {
            "full_name": "Nguyễn Văn A",
            "email": "user@example.com",
            "password": "onlyletters",
        },
        {
            "full_name": "Nguyễn Văn A",
            "email": "user@example.com",
            "password": "12345678",
        },
        {
            "full_name": "Nguyễn Văn A",
            "email": "user@example.com",
            "password": ("é" * 36) + "a1",
        },
        {
            "full_name": "   ",
            "email": "user@example.com",
            "password": "secure123",
        },
    ],
)
def test_register_rejects_invalid_payload(auth_api, payload):
    client, service = auth_api

    response = client.post("/auth/register", json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert service.created_data is None


def test_register_propagates_duplicate_email_conflict(auth_api):
    client, service = auth_api
    service.create_error = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Email đã được đăng ký",
    )

    response = client.post(
        "/auth/register",
        json={
            "full_name": "Nguyễn Văn A",
            "email": "user@example.com",
            "password": "secure123",
        },
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json() == {"detail": "Email đã được đăng ký"}


def test_login_returns_bearer_token_with_expected_claims(auth_api):
    client, service = auth_api
    service.user.token_version = 4

    response = client.post(
        "/auth/login",
        data={"username": "user@example.com", "password": "secure123"},
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["id"] == str(service.user.id)
    assert service.login_credentials == ("user@example.com", "secure123")

    payload = decode_token(body["access_token"])
    assert payload["sub"] == str(service.user.id)
    assert payload["type"] == "access"
    assert payload["ver"] == 4
    assert payload["jti"]
    assert payload["exp"] > payload["iat"]


@pytest.mark.parametrize("account_state", ["invalid_credentials", "inactive"])
def test_login_returns_generic_401_for_authentication_failure(auth_api, account_state):
    client, service = auth_api
    if account_state == "inactive":
        service.user.is_active = False
        password = "secure123"
    else:
        password = "wrong-password"

    response = client.post(
        "/auth/login",
        data={"username": "user@example.com", "password": password},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json() == {"detail": "Email hoặc mật khẩu không đúng"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_requires_oauth2_form_fields(auth_api):
    client, service = auth_api

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secure123"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert service.login_credentials is None
