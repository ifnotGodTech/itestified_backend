# Backend AGENTS.md

## Purpose

This folder is reserved for the `iTestified` backend API.

The backend will serve both existing clients in this repository:
- the Flutter mobile app in `mobile/`
- the admin/dashboard app in `dashboard/frontend/`

All contributors and coding agents working in `backend/` should follow this document.

Primary goals:
- correctness
- maintainability
- clear domain boundaries
- testability
- database integrity
- operational safety

When tradeoffs are unclear, prefer explicitness and long-term maintainability over short-term speed.

## Project Standards

- Framework: Django
- API style: Django REST Framework preferred
- Database: PostgreSQL
- Interface style: API-first
- Runtime: ASGI if async/background interaction is required; otherwise standard Django deployment is acceptable

Do not treat this backend as a thin mock server. It should become the source of truth for shared business data used by both UIs.

## Backend Scope

The backend is expected to own the shared business domain for:
- authentication and sessions
- users and profiles
- testimonies
- testimony moderation workflows
- donations
- notifications
- inspirational pictures
- scripture of the day
- reviews
- admin management
- analytics-ready reporting data
- home page curation rules

If the mobile and dashboard UIs currently model the same concept differently, the backend must define the canonical domain shape instead of copying UI-specific mock structures directly.

## Recommended Layout

Use a clear project/app split.

```text
backend/
├─ apps/
│  ├─ common/
│  ├─ users/
│  ├─ testimonies/
│  ├─ donations/
│  ├─ notifications/
│  ├─ media_library/
│  ├─ reviews/
│  └─ ...
├─ config/
│  ├─ settings/
│  │  ├─ base.py
│  │  ├─ local.py
│  │  ├─ test.py
│  │  └─ production.py
│  ├─ urls.py
│  ├─ asgi.py
│  └─ wsgi.py
├─ manage.py
├─ requirements/
├─ scripts/
├─ tests/
└─ AGENTS.md
```

Rules:
- `config/` contains project configuration only.
- `apps/` contains domain apps.
- Each app must own a well-defined business capability.
- Do not create dumping grounds like `misc`, `helpers`, or `utils`.
- Shared cross-cutting code belongs in `apps/common/` only when it is truly reusable and stable.

## Standard App Layout

Every non-trivial app should follow a structure close to this:

```text
apps/testimonies/
├─ admin.py
├─ apps.py
├─ models.py
├─ migrations/
├─ api/
│  ├─ urls.py
│  ├─ views.py
│  ├─ serializers.py
│  └─ permissions.py
├─ services/
│  ├─ commands.py
│  └─ queries.py
├─ selectors.py
├─ validators.py
├─ choices.py
├─ exceptions.py
└─ tests/
   ├─ factories.py
   ├─ test_models.py
   ├─ test_services.py
   └─ test_api.py
```

Responsibilities:
- `models.py`: persistence structure and lightweight model behavior only
- `api/`: transport layer only
- `services/commands.py`: state-changing business use cases
- `services/queries.py` or `selectors.py`: read/query logic
- `validators.py`: reusable validation
- `choices.py`: enums and domain constants
- `exceptions.py`: app-specific exception types
- `tests/`: app-local tests

Do not place complex business orchestration in:
- views
- serializers
- forms
- signals
- model `save()`
- admin actions

## Engineering Rules

### Domain and business logic

- Keep business rules explicit.
- Put business workflows in services, selectors, validators, and database constraints.
- Prefer simple, composable modules over clever abstractions.
- Avoid deep inheritance and generic helper layers that hide framework behavior.
- Keep cross-app dependencies intentional and minimal.

### Models and database design

- Models are the source of truth for stored data.
- Design for integrity first.
- For every model, explicitly consider:
  - required vs optional fields
  - uniqueness rules
  - lifecycle states
  - referential integrity
  - audit requirements
  - soft delete vs hard delete
  - concurrency-sensitive updates
- Use explicit constraints and indexes.
- Use `TextChoices` or `IntegerChoices` for statuses instead of magic strings.
- Keep model methods small and local to the model's own invariants.
- Never hardcode the built-in Django user model in relationships; use `AUTH_USER_MODEL`.

### Transactions and concurrency

- Wrap multi-write workflows in `transaction.atomic()`.
- Do not allow partially completed business operations to commit.
- Be explicit about idempotency where retries may happen.
- Use row locking such as `select_for_update()` when correctness depends on exclusive updates.
- Do not hide writes inside property access or lazy evaluation.

### Query discipline

- Write ORM code as if every query has a cost.
- Avoid N+1 queries.
- Use `select_related()` and `prefetch_related()` deliberately.
- Keep query construction in selectors or query services, not spread across views.
- Do not perform database work in loops when a set-based query is possible.
- Paginate all collection endpoints.
- Review indexes for hot filters, joins, and ordering fields.

### API layer

- The API layer is an interface boundary, not the business layer.
- Views must stay thin.
- Parse input, call a service or selector, and return a response.
- Use explicit request and response schemas.
- Return stable error shapes.
- Version public APIs when compatibility matters.

For mutation endpoints:
- validate input
- call a service command
- wrap critical state changes in transactions
- emit logs or events only after successful domain action

For read endpoints:
- use selectors or query services
- optimize queries for the endpoint shape
- avoid accidentally serializing large object graphs

### Signals

Default rule: do not use signals for core business logic.

Signals are acceptable only for:
- low-risk bookkeeping
- observability hooks
- clearly documented side effects with low coupling risk

Do not use signals for:
- payments
- moderation decisions
- notification-critical workflows
- authorization changes
- any flow where execution order and traceability matter

## Settings and Environment Rules

Use environment-specific settings files:
- `base.py`
- `local.py`
- `test.py`
- `production.py`

Rules:
- never commit secrets
- load environment-specific values from environment variables
- keep `base.py` portable
- define production security settings explicitly
- document third-party integration settings clearly

Minimum production expectations:
- `DEBUG = False`
- restricted `ALLOWED_HOSTS`
- secure secret management
- explicit logging
- static/media handling defined
- error reporting configured

## Testing Rules

Every app must have tests.

Minimum coverage categories:
- model tests for constraints and validation
- service tests for business workflows
- API tests for contracts and permissions
- integration tests for critical multi-app flows
- migration tests for risky schema or data transitions when needed

Rules:
- prefer fast tests by default
- use factories for readability
- one test should prove one behavior
- assert both success and failure paths
- for bug fixes, add a regression test first
- mock external services only at system boundaries
- do not over-mock internal code you own

## Migrations

Migrations are part of the production contract.

Rules:
- every schema change must ship through migrations
- do not edit old migrations once shared
- review generated migrations before committing
- name non-trivial migrations clearly
- keep schema migrations separate from large backfills when possible
- plan carefully for rollback and lock impact on large tables

## Security Rules

- Keep CSRF protection enabled for cookie-authenticated unsafe requests.
- Never disable CSRF globally.
- Validate all external input.
- Use Django authentication and authorization primitives unless there is a strong reason not to.
- Do not expose stack traces or secrets in API responses.
- Use signed or expiring tokens for sensitive flows.
- Review middleware order deliberately.
- Do not trust proxy headers unless deployment is configured for them.

## Observability and Operations

- Use structured logging where practical.
- Log business-significant events and failures.
- Separate expected domain failures from unexpected exceptions.
- Add health checks for app readiness and database connectivity.
- Add metrics around hot endpoints and background jobs if introduced.

Before production release:
- run the test suite
- run migrations check
- run Django system checks
- verify required environment variables
- verify static/media handling

## Code Style

- Use type hints on public functions and service boundaries.
- Keep functions small and named after business intent.
- Prefer explicit imports.
- Avoid circular imports by designing clearer boundaries.
- Keep constants and enums close to their domain.
- Add docstrings only when intent is not obvious from the code.
- Delete dead code aggressively.
- Do not introduce abstraction layers until the duplication is real.

Naming guidance:
- app names: plural nouns or clear domain units
- service functions: verb-first, domain-specific
- selector/query functions: read-oriented names

Examples:
- `create_testimony`
- `approve_testimony`
- `list_pending_testimonies`
- `get_user_by_email`

## Forbidden Practices

The following are not allowed without an explicit architectural exception:
- fat views
- business logic in serializers or forms
- hidden side effects in model `save()`
- critical workflows in signals
- raw SQL without clear justification
- broad `except Exception` without structured handling
- unbounded list endpoints
- committing secrets
- using `DEBUG=True` outside local development
- relying only on application validation for invariants that belong in the database

## Decision Pattern

When implementing a new feature, work in this order:

1. Define the domain language.
2. Design the data model.
3. Add constraints and indexes.
4. Design service commands and query selectors.
5. Expose API endpoints.
6. Add tests.
7. Add observability.
8. Review migration and deployment impact.

Do not start from the view layer.

## Final Instruction

If a requested implementation conflicts with this file, do not proceed silently.
Call out the conflict clearly and propose the compliant alternative.
