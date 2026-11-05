from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import joinedload

from app.core.deps import CurrentUser, Database
from app.models.models import (
    Ticket,
    TicketAsset,
    TicketCategory,
    TicketComment,
    TicketPriority,
    TicketStatus,
    TicketSlaTracking,
    User,
    UserRole,
    Asset,
)
from app.schemas import (
    CommentCreate,
    CommentOut,
    TicketClassificationOut,
    TicketClassificationRequest,
    TicketCreate,
    TicketOut,
    TicketPage,
    TicketUpdate,
)
from app.services.audit import record_audit
from app.services.classification import classify_ticket
from app.services.notifications import create_notification
from app.services.sla import calculate_sla_deadline, get_sla_targets

router = APIRouter(prefix="/tickets", tags=["tickets"])


def can_view_ticket(ticket: Ticket, user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.AGENT:
        return ticket.assignee_id == user.id
    return ticket.requester_id == user.id


def get_visible_ticket(db: Database, ticket_id: int, user: User) -> Ticket:
    ticket = db.scalar(
        select(Ticket)
        .options(
            joinedload(Ticket.requester),
            joinedload(Ticket.assignee),
            joinedload(Ticket.category),
            joinedload(Ticket.sla_tracking),
        )
        .where(Ticket.id == ticket_id)
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not can_view_ticket(ticket, user):
        raise HTTPException(status_code=403, detail="You cannot access this ticket")
    return ticket


def serialize_ticket(ticket: Ticket) -> dict:
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status,
        "priority": ticket.priority,
        "requester_id": ticket.requester_id,
        "requester_name": ticket.requester.name,
        "assignee_id": ticket.assignee_id,
        "assignee_name": ticket.assignee.name if ticket.assignee else None,
        "category_id": ticket.category_id,
        "category_name": ticket.category.name if ticket.category else None,
        "response_due_at": ticket.sla_tracking.response_due_at if ticket.sla_tracking else None,
        "first_response_at": ticket.sla_tracking.first_response_at if ticket.sla_tracking else None,
        "sla_due_at": ticket.sla_due_at,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
    }


def ticket_snapshot(ticket: Ticket) -> dict:
    return {
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "assignee_id": ticket.assignee_id,
        "category_id": ticket.category_id,
        "sla_due_at": ticket.sla_due_at.isoformat(),
    }


@router.post("/classify", response_model=TicketClassificationOut)
def classify_ticket_request(
    payload: TicketClassificationRequest,
    user: CurrentUser,
    db: Database,
):
    categories = db.scalars(select(TicketCategory).order_by(TicketCategory.name)).all()
    return classify_ticket(payload.title, payload.description, categories)


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(payload: TicketCreate, user: CurrentUser, db: Database):
    category = None
    if payload.category_id is not None:
        category = db.get(TicketCategory, payload.category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="Ticket category not found")
    priority = payload.priority or (
        category.default_priority if category else TicketPriority.MEDIUM
    )
    response_minutes, resolution_minutes = get_sla_targets(db, priority)
    ticket = Ticket(
        title=payload.title.strip(),
        description=payload.description.strip(),
        requester_id=user.id,
        category_id=category.id if category else None,
        priority=priority,
        status=TicketStatus.OPEN,
        sla_due_at=calculate_sla_deadline(priority, target_minutes=resolution_minutes),
    )
    db.add(ticket)
    db.flush()
    ticket.sla_tracking = TicketSlaTracking(
        response_due_at=calculate_sla_deadline(priority, target_minutes=response_minutes)
    )
    record_audit(
        db,
        user,
        "CREATE",
        "Ticket",
        ticket.id,
        new_values=ticket_snapshot(ticket),
    )
    db.commit()
    db.refresh(ticket)
    ticket = get_visible_ticket(db, ticket.id, user)
    return serialize_ticket(ticket)


@router.get("", response_model=TicketPage)
def list_tickets(
    user: CurrentUser,
    db: Database,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    priority: TicketPriority | None = None,
    category_id: int | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    created_from: date | None = None,
    created_to: date | None = None,
    sort_by: Literal["date", "priority", "status"] = "date",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(status_code=422, detail="Start date must be on or before end date")
    query = select(Ticket)
    if user.role == UserRole.USER:
        query = query.where(Ticket.requester_id == user.id)
    elif user.role == UserRole.AGENT:
        query = query.where(Ticket.assignee_id == user.id)
    if status_filter is not None:
        query = query.where(Ticket.status == status_filter)
    if priority is not None:
        query = query.where(Ticket.priority == priority)
    if category_id is not None:
        query = query.where(Ticket.category_id == category_id)
    if q:
        search = f"%{q.strip()}%"
        query = query.where(
            or_(
                Ticket.title.ilike(search),
                Ticket.description.ilike(search),
                Ticket.requester.has(User.name.ilike(search)),
                Ticket.category.has(TicketCategory.name.ilike(search)),
                cast(Ticket.id, String).ilike(search),
            )
        )
    if created_from is not None:
        query = query.where(
            Ticket.created_at >= datetime.combine(created_from, time.min, timezone.utc)
        )
    if created_to is not None:
        query = query.where(
            Ticket.created_at < datetime.combine(
                created_to + timedelta(days=1), time.min, timezone.utc
            )
        )

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort_by == "priority":
        sort_column = case(
            {priority: rank for rank, priority in enumerate(TicketPriority)},
            value=Ticket.priority,
        )
    elif sort_by == "status":
        sort_column = case(
            {ticket_status: rank for rank, ticket_status in enumerate(TicketStatus)},
            value=Ticket.status,
        )
    else:
        sort_column = Ticket.created_at
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    tickets = db.scalars(
        query.options(
            joinedload(Ticket.requester),
            joinedload(Ticket.assignee),
            joinedload(Ticket.category),
        )
        .order_by(ordering, Ticket.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return TicketPage(
        items=[serialize_ticket(ticket) for ticket in tickets],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/analytics")
def ticket_analytics(user: CurrentUser, db: Database):
    query = select(Ticket)
    if user.role == UserRole.USER:
        query = query.where(Ticket.requester_id == user.id)
    elif user.role == UserRole.AGENT:
        query = query.where(Ticket.assignee_id == user.id)

    visible_tickets = query.subquery()
    total = db.scalar(select(func.count()).select_from(visible_tickets)) or 0
    statuses = db.execute(
        select(visible_tickets.c.status, func.count()).group_by(visible_tickets.c.status)
    ).all()
    priorities = db.execute(
        select(visible_tickets.c.priority, func.count()).group_by(visible_tickets.c.priority)
    ).all()
    return {
        "total": total,
        "statuses": {status.value: count for status, count in statuses},
        "priorities": {priority.value: count for priority, count in priorities},
    }


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, user: CurrentUser, db: Database):
    return serialize_ticket(get_visible_ticket(db, ticket_id, user))


@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, payload: TicketUpdate, user: CurrentUser, db: Database):
    ticket = get_visible_ticket(db, ticket_id, user)
    if user.role == UserRole.USER:
        raise HTTPException(status_code=403, detail="Employees cannot edit ticket details")
    if user.role == UserRole.AGENT and payload.assignee_id is not None:
        raise HTTPException(status_code=403, detail="Only administrators can change assignment")
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Closed tickets cannot be edited")

    previous = ticket_snapshot(ticket)
    updates = payload.model_dump(exclude_unset=True)
    assignee_id = updates.pop("assignee_id", None) if "assignee_id" in updates else ...
    requested_category = updates.pop("category_id", ...) if "category_id" in updates else ...

    if assignee_id is not ...:
        if assignee_id is None:
            ticket.assignee_id = None
        else:
            assignee = db.get(User, assignee_id)
            if assignee is None or not assignee.is_active or assignee.role not in {
                UserRole.ADMIN,
                UserRole.AGENT,
            }:
                raise HTTPException(status_code=422, detail="Assignee must be an active support user")
            ticket.assignee_id = assignee.id
            if ticket.status == TicketStatus.OPEN:
                ticket.status = TicketStatus.ASSIGNED
            if assignee.id != user.id:
                create_notification(
                    db, assignee.id, f"Ticket #{ticket.id} was assigned to you: {ticket.title}"
                )

    if requested_category is not ...:
        if requested_category is None:
            ticket.category_id = None
        else:
            category = db.get(TicketCategory, requested_category)
            if category is None:
                raise HTTPException(status_code=404, detail="Ticket category not found")
            ticket.category_id = category.id

    for field, value in updates.items():
        if value is not None:
            setattr(ticket, field, value)
    if ticket.priority != TicketPriority(previous["priority"]):
        response_minutes, resolution_minutes = get_sla_targets(db, ticket.priority)
        ticket.sla_due_at = calculate_sla_deadline(
            ticket.priority, target_minutes=resolution_minutes
        )
        if ticket.sla_tracking and ticket.sla_tracking.first_response_at is None:
            ticket.sla_tracking.response_due_at = calculate_sla_deadline(
                ticket.priority,
                start=datetime.now(timezone.utc),
                target_minutes=response_minutes,
            )

    ticket.updated_at = datetime.now(timezone.utc)
    current = ticket_snapshot(ticket)
    record_audit(db, user, "UPDATE", "Ticket", ticket.id, previous, current)
    db.commit()
    return serialize_ticket(get_visible_ticket(db, ticket.id, user))


@router.post("/{ticket_id}/close", response_model=TicketOut)
def close_ticket(ticket_id: int, user: CurrentUser, db: Database):
    ticket = get_visible_ticket(db, ticket_id, user)
    if ticket.requester_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only the requester can close this ticket")
    if ticket.status != TicketStatus.RESOLVED:
        raise HTTPException(status_code=409, detail="Only resolved tickets can be closed")
    previous = ticket_snapshot(ticket)
    ticket.status = TicketStatus.CLOSED
    ticket.updated_at = datetime.now(timezone.utc)
    record_audit(
        db, user, "CLOSE", "Ticket", ticket.id, previous, ticket_snapshot(ticket)
    )
    db.commit()
    return serialize_ticket(get_visible_ticket(db, ticket.id, user))


@router.get("/{ticket_id}/comments", response_model=list[CommentOut])
def list_comments(ticket_id: int, user: CurrentUser, db: Database):
    get_visible_ticket(db, ticket_id, user)
    comments = db.scalars(
        select(TicketComment)
        .options(joinedload(TicketComment.author))
        .where(TicketComment.ticket_id == ticket_id)
        .order_by(TicketComment.created_at, TicketComment.id)
    ).unique().all()
    return [
        {
            "id": comment.id,
            "ticket_id": comment.ticket_id,
            "author_id": comment.author_id,
            "author_name": comment.author.name,
            "body": comment.body,
            "created_at": comment.created_at,
        }
        for comment in comments
    ]


@router.get("/{ticket_id}/assets")
def list_ticket_assets(ticket_id: int, user: CurrentUser, db: Database):
    get_visible_ticket(db, ticket_id, user)
    assets = db.scalars(
        select(Asset)
        .join(TicketAsset, TicketAsset.asset_id == Asset.id)
        .options(joinedload(Asset.assigned_user))
        .where(TicketAsset.ticket_id == ticket_id)
        .order_by(Asset.asset_tag)
    ).unique().all()
    return [
        {
            "id": asset.id,
            "asset_tag": asset.asset_tag,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "assigned_user_name": asset.assigned_user.name if asset.assigned_user else None,
        }
        for asset in assets
    ]


@router.post("/{ticket_id}/assets/{asset_id}", status_code=status.HTTP_201_CREATED)
def link_ticket_asset(
    ticket_id: int,
    asset_id: int,
    user: CurrentUser,
    db: Database,
):
    ticket = get_visible_ticket(db, ticket_id, user)
    if user.role not in {UserRole.ADMIN, UserRole.AGENT}:
        raise HTTPException(status_code=403, detail="Only support staff can link assets")
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    existing = db.get(TicketAsset, (ticket_id, asset_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Asset is already linked to this ticket")
    db.add(TicketAsset(ticket_id=ticket.id, asset_id=asset.id, linked_by_id=user.id))
    record_audit(
        db,
        user,
        "LINK",
        "TicketAsset",
        ticket.id,
        new_values={"asset_id": asset.id, "asset_tag": asset.asset_tag},
    )
    db.commit()
    return {"ticket_id": ticket.id, "asset_id": asset.id, "asset_tag": asset.asset_tag}


@router.post(
    "/{ticket_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(ticket_id: int, payload: CommentCreate, user: CurrentUser, db: Database):
    ticket = get_visible_ticket(db, ticket_id, user)
    comment = TicketComment(
        ticket_id=ticket.id, author_id=user.id, body=payload.body.strip()
    )
    if (
        user.role in {UserRole.ADMIN, UserRole.AGENT}
        and ticket.sla_tracking
        and ticket.sla_tracking.first_response_at is None
    ):
        ticket.sla_tracking.first_response_at = datetime.now(timezone.utc)
    db.add(comment)
    db.flush()
    recipient_id = (
        ticket.assignee_id
        if user.id == ticket.requester_id
        else ticket.requester_id
    )
    if recipient_id is not None and recipient_id != user.id:
        create_notification(
            db, recipient_id, f"New comment on ticket #{ticket.id}: {ticket.title}"
        )
    record_audit(
        db,
        user,
        "COMMENT",
        "Ticket",
        ticket.id,
        new_values={"comment_id": comment.id},
    )
    db.commit()
    db.refresh(comment)
    db.refresh(comment, attribute_names=["author"])
    return {
        "id": comment.id,
        "ticket_id": comment.ticket_id,
        "author_id": comment.author_id,
        "author_name": comment.author.name,
        "body": comment.body,
        "created_at": comment.created_at,
    }
