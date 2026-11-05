from sqlalchemy.orm import Session

from app.models.models import Notification


def create_notification(db: Session, user_id: int, message: str) -> None:
    db.add(Notification(user_id=user_id, message=message))
