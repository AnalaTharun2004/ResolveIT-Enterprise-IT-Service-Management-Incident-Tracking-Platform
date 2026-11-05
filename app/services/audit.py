from sqlalchemy.orm import Session

from app.models.models import AuditLog, User


def record_audit(
    db: Session,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: int,
    previous_values: dict | None = None,
    new_values: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_values=previous_values,
            new_values=new_values,
        )
    )
