from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, Database, require_roles
from app.core.security import hash_password
from app.models.models import (
    AuditLog,
    Notification,
    SlaPolicy,
    Ticket,
    TicketPriority,
    TicketCategory,
    TicketStatus,
    User,
    UserRole,
)
from app.schemas import (
    AdminUserCreate,
    CategoryCreate,
    CategoryOut,
    DashboardOut,
    NotificationOut,
    SlaPolicyOut,
    SlaPolicyUpdate,
    UserOut,
)
from app.services.audit import record_audit
from app.services.sla import ensure_sla_policies

router = APIRouter(tags=["administration"])


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Database, user: CurrentUser):
    return list(
        db.scalars(select(TicketCategory).order_by(TicketCategory.name)).all()
    )


@router.post(
    "/admin/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: AdminUserCreate,
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=password_hash,
        role=payload.role,
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        admin,
        "CREATE",
        "User",
        user.id,
        new_values={"email": user.email, "role": user.role.value},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/admin/support-users", response_model=list[UserOut])
def list_support_users(
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return list(
        db.scalars(
            select(User)
            .where(User.role.in_([UserRole.ADMIN, UserRole.AGENT]))
            .order_by(User.role, User.name)
        ).all()
    )


@router.get("/admin/users", response_model=list[UserOut])
def list_users(
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return list(db.scalars(select(User).order_by(User.name)).all())


@router.post(
    "/admin/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    payload: CategoryCreate,
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    name = payload.name.strip()
    if db.scalar(select(TicketCategory).where(func.lower(TicketCategory.name) == name.lower())):
        raise HTTPException(status_code=409, detail="A category with this name already exists")
    category = TicketCategory(
        name=name,
        description=payload.description.strip() if payload.description else None,
        default_priority=payload.default_priority,
    )
    db.add(category)
    db.flush()
    record_audit(
        db,
        admin,
        "CREATE",
        "TicketCategory",
        category.id,
        new_values={
            "name": category.name,
            "default_priority": category.default_priority.value,
        },
    )
    db.commit()
    db.refresh(category)
    return category


@router.get("/admin/sla-policies", response_model=list[SlaPolicyOut])
def list_sla_policies(
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    ensure_sla_policies(db)
    db.commit()
    return list(db.scalars(select(SlaPolicy).order_by(SlaPolicy.priority)).all())


@router.put("/admin/sla-policies/{priority}", response_model=SlaPolicyOut)
def update_sla_policy(
    priority: TicketPriority,
    payload: SlaPolicyUpdate,
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    ensure_sla_policies(db)
    policy = db.scalar(select(SlaPolicy).where(SlaPolicy.priority == priority))
    previous = {
        "response_minutes": policy.response_minutes,
        "resolution_minutes": policy.resolution_minutes,
    }
    policy.response_minutes = payload.response_minutes
    policy.resolution_minutes = payload.resolution_minutes
    record_audit(
        db,
        admin,
        "UPDATE",
        "SlaPolicy",
        policy.id,
        previous,
        {
            "priority": priority.value,
            "response_minutes": policy.response_minutes,
            "resolution_minutes": policy.resolution_minutes,
        },
    )
    db.commit()
    db.refresh(policy)
    return policy


@router.get("/admin/dashboard", response_model=DashboardOut)
def dashboard(
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    counts = {
        item: db.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.status == item)
        )
        or 0
        for item in TicketStatus
    }
    return {
        "total": sum(counts.values()),
        "open": counts[TicketStatus.OPEN],
        "assigned": counts[TicketStatus.ASSIGNED],
        "in_progress": counts[TicketStatus.IN_PROGRESS],
        "waiting_for_user": counts[TicketStatus.WAITING_FOR_USER],
        "resolved": counts[TicketStatus.RESOLVED],
        "closed": counts[TicketStatus.CLOSED],
    }


@router.get("/admin/audit")
def list_audit_logs(
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
    limit: int = Query(default=50, ge=1, le=100),
):
    records = db.scalars(
        select(AuditLog)
        .where(AuditLog.actor_id == admin.id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "actor_id": item.actor_id,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "previous_values": item.previous_values,
            "new_values": item.new_values,
            "created_at": item.created_at,
        }
        for item in records
    ]


@router.get("/admin/notifications")
@router.get("/notifications")
def list_notifications(
    db: Database,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=50),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = select(Notification).where(Notification.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordered_query = query.order_by(Notification.created_at.desc(), Notification.id.desc())
    ordered_query = (
        ordered_query.offset((page - 1) * page_size).limit(page_size)
        if page is not None
        else ordered_query.limit(limit)
    )
    items = list(db.scalars(ordered_query).all())
    if page is None:
        return items
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(notification_id: int, db: Database, user: CurrentUser):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification
