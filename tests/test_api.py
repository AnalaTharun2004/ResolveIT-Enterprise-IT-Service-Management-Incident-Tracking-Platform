from collections.abc import Generator
from datetime import datetime
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.models import TicketCategory, TicketPriority, User, UserRole


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add_all(
            [
                User(
                    name="Test Administrator",
                    email="admin@test.local",
                    password_hash=hash_password("AdminPass123!"),
                    role=UserRole.ADMIN,
                ),
                User(
                    name="Test Engineer",
                    email="agent@test.local",
                    password_hash=hash_password("AgentPass123!"),
                    role=UserRole.AGENT,
                ),
                TicketCategory(
                    name="Network",
                    description="Network support",
                    default_priority=TicketPriority.HIGH,
                ),
            ]
        )
        db.commit()
    application = create_app(database_engine=engine, seed_data=False)

    def override_db():
        with Session(engine) as db:
            yield db

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register_user(client: TestClient, email: str = "employee@test.local") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test Employee",
            "email": email,
            "password": "EmployeePass123!",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "USER"
    return response.json()


def login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_registration_login_and_token_identity(client: TestClient):
    user = register_user(client)
    token = login(client, "employee@test.local", "EmployeePass123!")
    response = client.get("/api/v1/auth/me", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["id"] == user["id"]
    assert response.json()["role"] == "USER"


def test_ticket_defaults_sla_assignment_comments_and_closure(client: TestClient):
    register_user(client)
    employee_token = login(client, "employee@test.local", "EmployeePass123!")
    admin_token = login(client, "admin@test.local", "AdminPass123!")
    agent_token = login(client, "agent@test.local", "AgentPass123!")

    created = client.post(
        "/api/v1/tickets",
        headers=auth(employee_token),
        json={
            "title": "Office network unavailable",
            "description": "I cannot connect to the office network from my laptop.",
            "category_id": 1,
        },
    )
    assert created.status_code == 201, created.text
    ticket = created.json()
    assert ticket["status"] == "OPEN"
    assert ticket["priority"] == "HIGH"
    assert ticket["assignee_id"] is None
    assert ticket["sla_due_at"]

    assigned = client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=auth(admin_token),
        json={"assignee_id": 2},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "ASSIGNED"
    assert assigned.json()["assignee_id"] == 2
    assert len(client.get("/api/v1/notifications", headers=auth(agent_token)).json()) == 1
    paged_notifications = client.get(
        "/api/v1/notifications?page=1&page_size=1", headers=auth(agent_token)
    )
    assert paged_notifications.json()["total"] == 1
    assert len(paged_notifications.json()["items"]) == 1

    agent_tickets = client.get("/api/v1/tickets", headers=auth(agent_token))
    assert agent_tickets.status_code == 200
    assert agent_tickets.json()["total"] == 1
    assert client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=auth(agent_token),
        json={"status": "IN_PROGRESS"},
    ).status_code == 200

    comment = client.post(
        f"/api/v1/tickets/{ticket['id']}/comments",
        headers=auth(agent_token),
        json={"body": "We are checking the office access point."},
    )
    assert comment.status_code == 201, comment.text
    assert comment.json()["author_name"] == "Test Engineer"
    assert len(client.get("/api/v1/notifications", headers=auth(employee_token)).json()) == 1

    resolved = client.patch(
        f"/api/v1/tickets/{ticket['id']}",
        headers=auth(agent_token),
        json={"status": "RESOLVED"},
    )
    assert resolved.status_code == 200
    closed = client.post(
        f"/api/v1/tickets/{ticket['id']}/close", headers=auth(employee_token)
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    assert client.get("/api/v1/admin/dashboard", headers=auth(admin_token)).json()["closed"] == 1
    assert client.get("/api/v1/admin/audit", headers=auth(admin_token)).json()


def test_employee_ticket_isolation_and_assignment_validation(client: TestClient):
    register_user(client, "owner@test.local")
    register_user(client, "other@test.local")
    owner_token = login(client, "owner@test.local", "EmployeePass123!")
    other_token = login(client, "other@test.local", "EmployeePass123!")
    admin_token = login(client, "admin@test.local", "AdminPass123!")

    created = client.post(
        "/api/v1/tickets",
        headers=auth(owner_token),
        json={
            "title": "My account cannot sign in",
            "description": "My account is locked and I cannot sign in.",
        },
    )
    ticket_id = created.json()["id"]
    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=auth(other_token)).status_code == 403
    assert client.patch(
        f"/api/v1/tickets/{ticket_id}",
        headers=auth(admin_token),
        json={"assignee_id": 9999},
    ).status_code == 422
    assert client.get("/api/v1/admin/dashboard", headers=auth(owner_token)).status_code == 403


def test_priority_override_and_list_filters(client: TestClient):
    register_user(client)
    token = login(client, "employee@test.local", "EmployeePass123!")
    response = client.post(
        "/api/v1/tickets",
        headers=auth(token),
        json={
            "title": "Network request with override",
            "description": "The office network is slow for my workstation.",
            "category_id": 1,
            "priority": "LOW",
        },
    )
    assert response.status_code == 201
    assert response.json()["priority"] == "LOW"
    assert client.get("/api/v1/tickets?priority=LOW", headers=auth(token)).json()["total"] == 1
    assert client.get("/api/v1/tickets?status=RESOLVED", headers=auth(token)).json()["total"] == 0


def test_ticket_search_sort_date_filters_and_analytics(client: TestClient):
    register_user(client)
    token = login(client, "employee@test.local", "EmployeePass123!")
    tickets = []
    for title, priority in [
        ("VPN connection failure", "LOW"),
        ("VPN access blocked", "CRITICAL"),
    ]:
        response = client.post(
            "/api/v1/tickets",
            headers=auth(token),
            json={
                "title": title,
                "description": "The VPN is unavailable for my workstation.",
                "priority": priority,
            },
        )
        assert response.status_code == 201
        tickets.append(response.json())

    created_date = tickets[0]["created_at"][:10]
    result = client.get(
        f"/api/v1/tickets?q=VPN&created_from={created_date}&created_to={created_date}"
        "&sort_by=priority&sort_order=asc",
        headers=auth(token),
    )
    assert result.status_code == 200
    assert [ticket["priority"] for ticket in result.json()["items"]] == ["CRITICAL", "LOW"]
    admin_token = login(client, "admin@test.local", "AdminPass123!")
    for ticket, status in zip(tickets, ["RESOLVED", "IN_PROGRESS"], strict=True):
        updated = client.patch(
            f"/api/v1/tickets/{ticket['id']}",
            headers=auth(admin_token),
            json={"status": status},
        )
        assert updated.status_code == 200
    by_status = client.get(
        "/api/v1/tickets?q=VPN&sort_by=status&sort_order=asc",
        headers=auth(token),
    )
    assert [ticket["status"] for ticket in by_status.json()["items"]] == [
        "IN_PROGRESS",
        "RESOLVED",
    ]
    by_date = client.get(
        "/api/v1/tickets?q=VPN&sort_by=date&sort_order=asc",
        headers=auth(token),
    )
    dates = [datetime.fromisoformat(ticket["created_at"]) for ticket in by_date.json()["items"]]
    assert dates == sorted(dates)
    invalid_range = client.get(
        f"/api/v1/tickets?created_from={created_date}&created_to=2020-01-01",
        headers=auth(token),
    )
    assert invalid_range.status_code == 422

    analytics = client.get("/api/v1/tickets/analytics", headers=auth(token))
    assert analytics.status_code == 200
    assert analytics.json()["total"] == 2
    assert analytics.json()["priorities"] == {"CRITICAL": 1, "LOW": 1}


def test_admin_can_configure_sla_targets_and_new_tickets_use_them(client: TestClient):
    admin_token = login(client, "admin@test.local", "AdminPass123!")
    employee = register_user(client)
    employee_token = login(client, employee["email"], "EmployeePass123!")

    policies = client.get("/api/v1/admin/sla-policies", headers=auth(admin_token))
    assert policies.status_code == 200
    assert len(policies.json()) == 4

    configured = client.put(
        "/api/v1/admin/sla-policies/LOW",
        headers=auth(admin_token),
        json={"response_minutes": 60, "resolution_minutes": 90},
    )
    assert configured.status_code == 200
    assert configured.json()["response_minutes"] == 60
    assert configured.json()["resolution_minutes"] == 90

    created = client.post(
        "/api/v1/tickets",
        headers=auth(employee_token),
        json={"title": "Install design software", "description": "Please install the design software on my workstation.", "priority": "LOW"},
    )
    assert created.status_code == 201
    deadline = datetime.fromisoformat(created.json()["sla_due_at"])
    created_at = datetime.fromisoformat(created.json()["created_at"])
    assert 89 <= (deadline - created_at).total_seconds() / 60 <= 91
    response_deadline = datetime.fromisoformat(created.json()["response_due_at"])
    assert 59 <= (response_deadline - created_at).total_seconds() / 60 <= 61

    first_response = client.post(
        f"/api/v1/tickets/{created.json()['id']}/comments",
        headers=auth(admin_token),
        json={"body": "We have received your request and will follow up."},
    )
    assert first_response.status_code == 201
    updated = client.get(
        f"/api/v1/tickets/{created.json()['id']}", headers=auth(admin_token)
    )
    assert updated.json()["first_response_at"] is not None


def test_asset_permissions_assignment_and_ticket_link(client: TestClient):
    admin_token = login(client, "admin@test.local", "AdminPass123!")
    employee = register_user(client)
    employee_token = login(client, employee["email"], "EmployeePass123!")

    payload = {
        "asset_tag": "ast-100",
        "name": "Employee laptop",
        "asset_type": "Laptop",
        "serial_number": "SN-100",
        "assigned_user_id": employee["id"],
        "status": "ACTIVE",
        "warranty_expires_at": "2027-12-31",
    }
    created_asset = client.post("/api/v1/assets", headers=auth(admin_token), json=payload)
    assert created_asset.status_code == 201, created_asset.text
    assert created_asset.json()["asset_tag"] == "AST-100"
    assert created_asset.json()["assigned_user_name"] == "Test Employee"
    assert client.post("/api/v1/assets", headers=auth(employee_token), json=payload).status_code == 403
    assert len(client.get("/api/v1/assets", headers=auth(employee_token)).json()) == 1
    paged_assets = client.get("/api/v1/assets?page=1&page_size=1", headers=auth(employee_token))
    assert paged_assets.json()["total"] == 1
    assert len(paged_assets.json()["items"]) == 1
    duplicate_tag = client.post(
        "/api/v1/assets",
        headers=auth(admin_token),
        json={**payload, "serial_number": "SN-101"},
    )
    assert duplicate_tag.status_code == 409

    created_ticket = client.post(
        "/api/v1/tickets",
        headers=auth(employee_token),
        json={
            "title": "Laptop needs repair",
            "description": "The laptop battery will not charge.",
        },
    )
    ticket_id = created_ticket.json()["id"]
    link = client.post(
        f"/api/v1/tickets/{ticket_id}/assets/{created_asset.json()['id']}",
        headers=auth(admin_token),
    )
    assert link.status_code == 201
    linked_assets = client.get(
        f"/api/v1/tickets/{ticket_id}/assets", headers=auth(employee_token)
    )
    assert linked_assets.status_code == 200
    assert linked_assets.json()[0]["asset_tag"] == "AST-100"


def test_ai_ticket_classification_returns_suggestions_without_creating_ticket(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from app.core.config import settings
    from app.services import classification

    token = login(client, "admin@test.local", "AdminPass123!")
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.example.test/v1")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "category_id": 1,
                                    "priority": "HIGH",
                                    "department": "IT Support",
                                    "suggested_assignment": "Network Support",
                                }
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(classification.httpx, "post", lambda *args, **kwargs: FakeResponse())
    response = client.post(
        "/api/v1/tickets/classify",
        headers=auth(token),
        json={"title": "Office Wi-Fi is down", "description": "Several users cannot connect to office Wi-Fi."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["category_name"] == "Network"
    assert response.json()["priority"] == "HIGH"
    assert response.json()["suggested_assignment"] == "Network Support"
    assert client.get("/api/v1/tickets", headers=auth(token)).json()["total"] == 0


def test_invalid_credentials_and_missing_token_are_rejected(client: TestClient):
    assert client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.local", "password": "incorrect"},
    ).status_code == 401
    assert client.get("/api/v1/tickets").status_code == 401
