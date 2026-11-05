from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import SlaPolicy, TicketPriority

SLA_DEFAULTS = {
    TicketPriority.CRITICAL: (15, 120),
    TicketPriority.HIGH: (30, 240),
    TicketPriority.MEDIUM: (240, 480),
    TicketPriority.LOW: (480, 1440),
}


def ensure_sla_policies(db: Session) -> None:
    existing = set(db.scalars(select(SlaPolicy.priority)).all())
    for priority, (response_minutes, resolution_minutes) in SLA_DEFAULTS.items():
        if priority not in existing:
            db.add(
                SlaPolicy(
                    priority=priority,
                    response_minutes=response_minutes,
                    resolution_minutes=resolution_minutes,
                )
            )


def get_sla_targets(db: Session, priority: TicketPriority) -> tuple[int, int]:
    policy = db.scalar(select(SlaPolicy).where(SlaPolicy.priority == priority))
    if policy is None:
        return SLA_DEFAULTS[priority]
    return policy.response_minutes, policy.resolution_minutes


def calculate_sla_deadline(
    priority: TicketPriority,
    start: datetime | None = None,
    target_minutes: int | None = None,
) -> datetime:
    base = start or datetime.now(timezone.utc)
    minutes = target_minutes or SLA_DEFAULTS[priority][1]
    return base + timedelta(minutes=minutes)
