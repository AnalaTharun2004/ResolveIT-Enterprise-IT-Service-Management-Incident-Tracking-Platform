# ResolveIT Project Plan

## 1. Project summary
ResolveIT is an enterprise IT service management and incident tracking platform designed for internal support teams, service agents, and administrators. The product will provide secure authentication, role-aware workflows, ticket lifecycle management, SLA tracking, auditability, notifications, and operational dashboards.

This plan is based on the confirmed requirements in `.azure/requirements.json` and the existing FastAPI application structure in the repository.

## 2. Confirmed requirements

### Product and workflow requirements
- Python backend with FastAPI
- Lightweight HTML, CSS, and JavaScript frontend
- Local SQLite persistence via SQLAlchemy
- User registration and login
- JWT-based authentication and bcrypt password hashing
- Role-based authorization for users, agents, and administrators
- Ticket creation, assignment, tracking, updates, and resolution
- SLA calculation and deadline tracking
- Comments and collaboration on tickets
- Notifications for ticket activity and status changes
- Audit history for operational changes
- Dashboard statistics for overview and operational monitoring

### Priority implementation characteristics
- Secure-by-default design
- Fast local development without a separate service infrastructure
- Simple browser-based UI with low operational overhead
- Clean separation between API, models, services, and frontend assets

## 3. Solution architecture

### 3.1 Application stack
- Backend: Python + FastAPI
- Frontend: vanilla HTML, CSS, and JavaScript served from the FastAPI app
- Persistence: SQLite database with SQLAlchemy ORM
- Authentication: JWT access tokens + bcrypt password hashing
- Security model: user roles and permission checks on protected API routes

### 3.2 Functional architecture

#### API layer
- `app/api/auth.py`: registration, login, token issuance, password validation
- `app/api/tickets.py`: ticket CRUD, assignment, status updates, comment handling
- `app/api/admin.py`: dashboard statistics, user administration, operational oversight

#### Core services and configuration
- `app/core/config.py`: environment and application settings
- `app/core/security.py`: JWT and password security helpers
- `app/core/deps.py`: shared dependency injection for authenticated access and DB sessions
- `app/services/sla.py`: SLA calculation and deadline logic
- `app/services/notifications.py`: notification generation and delivery behavior
- `app/services/audit.py`: structured audit trail generation

#### Data model
The application model already reflects the domain structure:
- `User`: account information, role, status, timestamps
- `Ticket`: summary, description, status, priority, assignment, category, SLA due date
- `TicketCategory`: ticket classification and default priorities
- `TicketComment`: threaded discussion on tickets
- `Notification`: user-facing alerts
- `AuditLog`: action history and state change records

### 3.3 Frontend architecture
The frontend should be a static, lightweight browser experience served by FastAPI:
- `/` serves the main HTML shell
- `/static` provides CSS and JavaScript assets
- UI pages include login, registration, dashboard, ticket detail, support workflows, and administration screens
- JavaScript should interact with REST endpoints using fetch-based API calls

### 3.4 Runtime structure
The application entry point in `app/main.py` already establishes the expected runtime pattern:
- DB tables are created automatically at startup
- initial seed data is populated
- API routers are mounted under the application prefix
- static frontend files are served from the `frontend` directory
- health endpoint is exposed at `/health`

## 4. Work plan

### Phase 1: Project foundation and scaffolding
Objectives:
- confirm repo conventions and execution environment
- validate backend startup and dependency flow
- define module boundaries and configuration standards

Deliverables:
- working FastAPI app bootstrap
- environment configuration for local development
- SQLite initialization and seed routines
- health endpoint validation

Acceptance criteria:
- `uvicorn app.main:app --reload` starts successfully
- DB initializes without errors
- static frontend is served correctly

### Phase 2: Authentication and authorization
Objectives:
- implement registration, login, and secure token handling
- support user roles and protected endpoints

Deliverables:
- user model and secure password hashing
- JWT issuance and validation
- role-based access checks for agents and admins
- login and session flows in the frontend

Acceptance criteria:
- users can register and log in
- protected routes reject unauthorized access
- role-specific actions are enforced correctly

### Phase 3: Ticket management and workflow state
Objectives:
- implement the core incident ticket lifecycle
- support assignment, status transitions, priority handling, and categorization

Deliverables:
- CRUD ticket endpoints
- ticket filter/search behavior by status or assignee
- assignment workflows for agents and admins
- ticket comments and updates

Acceptance criteria:
- tickets can be created, assigned, updated, and resolved
- status transitions are consistent with business rules
- comments are persisted with author metadata

### Phase 4: SLA, notifications, and audit trail
Objectives:
- make operational support reliable and traceable
- surface actionable alerts and structured change history

Deliverables:
- SLA calculation service and due-date tracking
- notification events for assignment, updates, and ticket closure
- audit log capture for user actions and state changes
- dashboard metrics based on ticket state and workload

Acceptance criteria:
- SLA due dates are calculated consistently
- notifications are generated for relevant events
- audit records capture meaningful state transitions

### Phase 5: Frontend UX and operational polish
Objectives:
- deliver a complete user-facing experience for support operations
- ensure role-aware workflows and dashboard clarity

Deliverables:
- login/registration pages
- dashboard summary cards and workload views
- ticket creation and detail pages
- admin support pages and user management screens
- responsive styling and basic validation feedback

Acceptance criteria:
- all core user flows are accessible from the browser
- users see only role-appropriate menus and actions
- dashboards reflect live backend data

### Phase 6: Validation, hardening, and release readiness
Objectives:
- verify app behavior end-to-end
- ensure security, consistency, and maintainability before release

Deliverables:
- end-to-end API validation and smoke tests
- security review of auth and authorization paths
- error-handling improvements and edge-case validation
- release checklist and operational runbook

Acceptance criteria:
- app functions correctly in a clean local environment
- auth and RBAC are verified under normal and restricted flows
- readiness checklist is documented for handoff to the next phase

## 5. Functional modules and expected behavior

### User management
- Create users with name, email, password, and role
- Restrict admin-only operations to authorized personnel
- Support active/inactive user status and auditability

### Ticket management
- Create tickets with title, description, category, and priority
- Auto-assign or manual assignment workflows
- Update status through business-appropriate transitions
- Track due dates and escalation based on SLA logic

### Collaboration and communication
- Add comments to tickets
- Alert users or agents on assignment and resolution
- Maintain a clear record of event history and user actions

### Administration and oversight
- Show operational metrics and workload summaries
- Allow management review of ticket throughput and resolution activity
- Provide access control for support administration tasks

## 6. Risks and mitigations

### Risk: security gaps in auth and authorization
Mitigation:
- use bcrypt for password hashing
- validate JWT claims on all protected endpoints
- enforce role checks on admin and agent actions

### Risk: incomplete SLA logic
Mitigation:
- centralize SLA calculations in dedicated service module
- define due date behavior and validation early in implementation

### Risk: UI drift from backend contracts
Mitigation:
- keep API contracts simple and documented
- validate frontend integration with structured responses and smoke tests

### Risk: scope creep around admin and operational features
Mitigation:
- prioritize MVP workflow first: auth, tickets, comments, dashboards, notifications
- defer advanced enhancements until core functionality is stable

## 7. Suggested release milestones
- Milestone 1: Basic secure backend and local SQLite setup
- Milestone 2: Authenticated user workflow and protected API access
- Milestone 3: End-to-end ticket lifecycle and assignment
- Milestone 4: SLA, notifications, and dashboard analytics
- Milestone 5: Frontend completion and validation
- Milestone 6: Production-ready hardening and handoff

## 8. Acceptance summary
The project will be considered ready for the next implementation phase when:
- the FastAPI app runs locally and serves the browser UI
- authentication and authorization are implemented and tested
- ticket workflows support creation, assignment, updates, and resolution
- SLA logic, notifications, and audit records are functioning
- admin dashboards reflect operational data accurately
- the app is stable enough for a demo or validation pass with representative users

## 9. Next step
Proceed with the implementation of the backend and frontend modules in the sequence defined above, starting with authentication and secure ticket workflows, then adding SLA, notification, and administrative analytics layers.
