import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.models import TicketCategory, TicketPriority, User, UserRole
from app.services.sla import ensure_sla_policies

DEFAULT_CATEGORIES = (
    ("Hardware", "Laptops, peripherals, and physical devices", TicketPriority.HIGH),
    ("Software", "Business applications and software installation", TicketPriority.MEDIUM),
    ("Network", "Connectivity, VPN, and office network issues", TicketPriority.HIGH),
    ("Access", "Accounts, permissions, and sign-in issues", TicketPriority.MEDIUM),
)


def seed_initial_data(db: Session) -> None:
    admin_email = os.getenv("RESOLVEIT_ADMIN_EMAIL", "admin@resolveit.local").lower()
    agent_email = os.getenv("RESOLVEIT_AGENT_EMAIL", "agent@resolveit.local").lower()
    if db.scalar(select(User).where(User.email == admin_email)) is None:
        db.add(
            User(
                name="ResolveIT Administrator",
                email=admin_email,
                password_hash=hash_password(
                    os.getenv("RESOLVEIT_ADMIN_PASSWORD", "Admin123!")
                ),
                role=UserRole.ADMIN,
            )
        )
    if db.scalar(select(User).where(User.email == agent_email)) is None:
        db.add(
            User(
                name="Support Engineer",
                email=agent_email,
                password_hash=hash_password(
                    os.getenv("RESOLVEIT_AGENT_PASSWORD", "Agent123!")
                ),
                role=UserRole.AGENT,
            )
        )
    for name, description, priority in DEFAULT_CATEGORIES:
        exists = db.scalar(
            select(TicketCategory).where(TicketCategory.name == name)
        )
        if exists is None:
            db.add(
                TicketCategory(
                    name=name,
                    description=description,
                    default_priority=priority,
                )
            )
    ensure_sla_policies(db)
    db.commit()
