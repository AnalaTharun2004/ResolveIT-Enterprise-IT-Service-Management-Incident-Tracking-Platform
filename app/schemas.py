from datetime import date, datetime

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.models import AssetStatus, TicketPriority, TicketStatus, UserRole


def validate_app_email(value: str) -> str:
    local_part, separator, domain = value.rpartition("@")
    if not separator:
        raise ValueError("Invalid email address")

    local_domain_suffix = next(
        (suffix for suffix in (".local", ".test") if domain.lower().endswith(suffix)),
        None,
    )
    candidate = value
    if local_domain_suffix:
        candidate = f"{local_part}@{domain[:-len(local_domain_suffix)]}.example.com"

    try:
        validated = validate_email(candidate, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc

    if local_domain_suffix:
        return f"{validated.local_part}@{domain.lower()}"
    return validated.normalized


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return validate_app_email(value)


class AdminUserCreate(UserCreate):
    role: UserRole = UserRole.USER


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str) -> str:
        return validate_app_email(value)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    default_priority: TicketPriority = TicketPriority.MEDIUM


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    default_priority: TicketPriority


class SlaPolicyUpdate(BaseModel):
    response_minutes: int = Field(ge=1, le=43200)
    resolution_minutes: int = Field(ge=1, le=43200)


class SlaPolicyOut(SlaPolicyUpdate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    priority: TicketPriority


class AssetCreate(BaseModel):
    asset_tag: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    asset_type: str = Field(min_length=2, max_length=80)
    serial_number: str | None = Field(default=None, max_length=120)
    assigned_user_id: int | None = None
    status: AssetStatus = AssetStatus.IN_STOCK
    warranty_expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=5000)


class AssetUpdate(BaseModel):
    asset_tag: str | None = Field(default=None, min_length=2, max_length=40)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    asset_type: str | None = Field(default=None, min_length=2, max_length=80)
    serial_number: str | None = Field(default=None, max_length=120)
    assigned_user_id: int | None = None
    status: AssetStatus | None = None
    warranty_expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class AssetOut(BaseModel):
    id: int
    asset_tag: str
    name: str
    asset_type: str
    serial_number: str | None
    assigned_user_id: int | None
    assigned_user_name: str | None
    status: AssetStatus
    warranty_expires_at: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TicketCreate(BaseModel):
    title: str = Field(min_length=4, max_length=160)
    description: str = Field(min_length=8, max_length=10000)
    category_id: int | None = None
    priority: TicketPriority | None = None


class TicketClassificationRequest(BaseModel):
    title: str = Field(min_length=4, max_length=160)
    description: str = Field(min_length=8, max_length=10000)


class TicketClassificationOut(BaseModel):
    category_id: int | None
    category_name: str | None
    priority: TicketPriority
    department: str
    suggested_assignment: str | None


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=4, max_length=160)
    description: str | None = Field(default=None, min_length=8, max_length=10000)
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignee_id: int | None = None
    category_id: int | None = None

    @model_validator(mode="after")
    def require_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class TicketOut(BaseModel):
    id: int
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    requester_id: int
    requester_name: str
    assignee_id: int | None
    assignee_name: str | None
    category_id: int | None
    category_name: str | None
    response_due_at: datetime | None = None
    first_response_at: datetime | None = None
    sla_due_at: datetime
    created_at: datetime
    updated_at: datetime


class TicketPage(BaseModel):
    items: list[TicketOut]
    total: int
    page: int
    page_size: int


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CommentOut(BaseModel):
    id: int
    ticket_id: int
    author_id: int
    author_name: str
    body: str
    created_at: datetime


class NotificationOut(BaseModel):
    id: int
    message: str
    is_read: bool
    created_at: datetime


class DashboardOut(BaseModel):
    total: int
    open: int
    assigned: int
    in_progress: int
    waiting_for_user: int
    resolved: int
    closed: int
