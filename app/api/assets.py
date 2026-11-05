from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.core.deps import CurrentUser, Database, require_roles
from app.models.models import Asset, AssetStatus, User, UserRole
from app.schemas import AssetCreate, AssetOut, AssetUpdate
from app.services.audit import record_audit

router = APIRouter(prefix="/assets", tags=["assets"])


def serialize_asset(asset: Asset) -> dict:
    return {
        "id": asset.id,
        "asset_tag": asset.asset_tag,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "serial_number": asset.serial_number,
        "assigned_user_id": asset.assigned_user_id,
        "assigned_user_name": asset.assigned_user.name if asset.assigned_user else None,
        "status": asset.status,
        "warranty_expires_at": asset.warranty_expires_at,
        "notes": asset.notes,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
    }


def validate_assignee(db: Database, user_id: int | None) -> None:
    if user_id is None:
        return
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=422, detail="Assignee must be an active user")


@router.get("")
def list_assets(
    db: Database,
    user: CurrentUser,
    q: str | None = Query(default=None, min_length=1, max_length=160),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    query = select(Asset).options(joinedload(Asset.assigned_user))
    if user.role == UserRole.USER:
        query = query.where(Asset.assigned_user_id == user.id)
    if q:
        search = f"%{q.strip()}%"
        query = query.where(
            or_(
                Asset.asset_tag.ilike(search),
                Asset.name.ilike(search),
                Asset.asset_type.ilike(search),
                Asset.serial_number.ilike(search),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    ordered_query = query.order_by(Asset.asset_tag)
    if page is not None:
        ordered_query = ordered_query.offset((page - 1) * page_size).limit(page_size)
    assets = db.scalars(ordered_query).unique().all()
    items = [serialize_asset(asset) for asset in assets]
    if page is None:
        return items
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: AssetCreate,
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    asset_tag = payload.asset_tag.strip().upper()
    if db.scalar(select(Asset).where(Asset.asset_tag == asset_tag)):
        raise HTTPException(status_code=409, detail="An asset with this tag already exists")
    if payload.serial_number and db.scalar(
        select(Asset).where(Asset.serial_number == payload.serial_number.strip())
    ):
        raise HTTPException(status_code=409, detail="An asset with this serial number already exists")
    validate_assignee(db, payload.assigned_user_id)
    asset = Asset(
        asset_tag=asset_tag,
        name=payload.name.strip(),
        asset_type=payload.asset_type.strip(),
        serial_number=payload.serial_number.strip() if payload.serial_number else None,
        assigned_user_id=payload.assigned_user_id,
        status=payload.status,
        warranty_expires_at=payload.warranty_expires_at,
        notes=payload.notes.strip() if payload.notes else None,
    )
    db.add(asset)
    db.flush()
    record_audit(
        db,
        admin,
        "CREATE",
        "Asset",
        asset.id,
        new_values={"asset_tag": asset.asset_tag, "name": asset.name},
    )
    db.commit()
    return serialize_asset(db.scalar(
        select(Asset).options(joinedload(Asset.assigned_user)).where(Asset.id == asset.id)
    ))


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    db: Database,
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("asset_tag") is not None:
        updates["asset_tag"] = updates["asset_tag"].strip().upper()
        duplicate = db.scalar(select(Asset).where(Asset.asset_tag == updates["asset_tag"]))
        if duplicate is not None and duplicate.id != asset.id:
            raise HTTPException(status_code=409, detail="An asset with this tag already exists")
    if updates.get("serial_number"):
        updates["serial_number"] = updates["serial_number"].strip()
        duplicate = db.scalar(
            select(Asset).where(Asset.serial_number == updates["serial_number"])
        )
        if duplicate is not None and duplicate.id != asset.id:
            raise HTTPException(status_code=409, detail="An asset with this serial number already exists")
    elif "serial_number" in updates:
        updates["serial_number"] = None
    validate_assignee(db, updates.get("assigned_user_id"))
    previous = {key: getattr(asset, key) for key in updates}
    for key, value in updates.items():
        if isinstance(value, str):
            value = value.strip()
        if key == "asset_tag" and value:
            value = value.upper()
        setattr(asset, key, value)
    record_audit(
        db,
        admin,
        "UPDATE",
        "Asset",
        asset.id,
        {key: str(value) if value is not None else None for key, value in previous.items()},
        {key: str(getattr(asset, key)) if getattr(asset, key) is not None else None for key in updates},
    )
    db.commit()
    asset = db.scalar(
        select(Asset).options(joinedload(Asset.assigned_user)).where(Asset.id == asset_id)
    )
    return serialize_asset(asset)