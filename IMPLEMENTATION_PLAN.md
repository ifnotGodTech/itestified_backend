# Backend Implementation Plan

This file is the living execution plan for the `iTestified` backend.

It should be used together with:
- `backend/AGENTS.md`
- `backend/PHASE0_DOMAIN_DISCOVERY.md`
- `mobile/plan.md`
- the current mobile Flutter code in `mobile/`
- the current dashboard code in `dashboard/frontend/`

## Status

Current state: backend scaffold and Phase 1-2 foundations are implemented, with Phase 4-7 actively in delivery.

Current milestone goal:
- define the backend in a way that cleanly supports both the mobile app and the dashboard without inheriting either UI's temporary mock structures directly

## Working Mode

This plan should be executed in sequence.

Rules:
- complete a lightweight contract-lock step before schema work begins
- complete one phase at a time
- do not start later phases until the current phase is implemented and verified
- follow `backend/AGENTS.md` for architecture and engineering standards
- treat the backend as the canonical source of truth for shared business data
- prefer stable domain contracts over UI-shaped response shortcuts
- pause and resolve domain ambiguity before implementing irreversible schema decisions
- for feature phases, work as vertical slices instead of backend-only batches
- after a feature is implemented and verified in the backend, wire it into the relevant client before moving to the next phase
- do not leave completed backend features disconnected from the mobile or dashboard client they are meant to serve

Definition of complete for any phase:
- code for the phase exists and is organized according to `backend/AGENTS.md`
- schema, services, API boundaries, and tests are implemented for that phase
- migrations are reviewed
- the phase is locally verifiable
- the relevant UI client is integrated for that feature when integration is in scope for the phase
- backend and client behavior are validated together for the delivered slice
- no regressions are introduced in earlier phases
- for dashboard-facing/admin slices, dashboard integration + E2E auth/admin flow coverage must pass before sign-off

## Mandatory Cross-Client Test Gate

For any phase that touches `dashboard/frontend/` behavior (especially auth/admin flows), completion requires:

- backend API/service tests for the phase
- dashboard integration tests for backend contract usage in that phase
- dashboard E2E tests for the critical phase journey
- regression checks for previously completed phases impacted by the change

Phase status may not be moved to `Completed` until these checks are green.

## Delivery Model

This backend should be delivered using a vertical-slice workflow.

Default execution loop for any feature phase:

1. lock the domain contract for the feature
2. implement the backend models, services, permissions, and API endpoints
3. test the backend thoroughly for that feature
4. wire the relevant UI client
   - `mobile/` for consumer-facing flows
   - `dashboard/frontend/` for admin-facing flows
   - both clients when the feature spans both surfaces
5. verify the integrated flow end-to-end locally
6. only then move to the next feature phase

Important constraint:
- do not batch multiple unintegrated backend features ahead of client wiring
- the only exception is `Phase 0`, which exists to lock cross-cutting decisions before implementation begins
- `Phase 1` may also complete without client wiring because it is infrastructure-only, but it must leave the project ready for the first feature slice

## Phase Status

- Phase 0: Completed
- Phase 1: Completed
- Phase 2: Completed
- Phase 3: Completed
- Phase 4: In progress (Slices 1-11 implemented)
- Phase 5: In progress (Slices 1-7 implemented)
- Phase 6: In progress (Slices 1-7 implemented)
- Phase 7: In progress (Slices 1-8 implemented)
- Phase 8: Not started
- Phase 9: Not started

Current focus:
- next phase to implement: `Phase 8: Reviews, Analytics, And Operational Admin Features`

## Product Understanding

The backend will serve two internal clients in this repository:

- `mobile/`
  - Flutter consumer app for testimony browsing, submission, profile, giving, favorites, notifications, and related user flows
- `dashboard/frontend/`
  - Next.js admin application for moderation, content management, donations review, notifications history, analytics, settings, and admin operations

The backend must unify these into one shared domain model.

### Mobile Access Contract: Guest vs Authenticated

Backend execution and API permissions must follow the mobile capability split in `mobile/plan.md`:

- `Guest` (not a persisted user/account type):
  - can browse public content (home feed, testimonies, categories, inspirational pictures, scripture, search)
  - cannot perform authenticated writes (submit testimony, favorite, comment, giving, profile updates, notification read-state actions)
  - may see guest-specific restriction prompts in UI, but backend must still enforce access at API boundary

- `Authenticated user`:
  - can perform user-owned writes (submission, favorites, comments, giving, profile, notification actions)
  - can view private/user-owned data (my testimonies, favorites, giving history, personal notifications, profile)

Mandatory backend rule:
- UI restriction prompts are not security controls.
- Every protected endpoint must enforce auth/ownership/role checks regardless of client behavior.

### Shared business domains

These domains appear across one or both clients and should be treated as backend-owned:

- authentication and sessions
- users and profiles
- testimonies
- testimony moderation
- categories
- comments and engagement
- favorites
- notifications
- donations
- inspirational pictures
- scripture of the day
- home page curation
- reviews
- admin accounts and permissions
- analytics/reporting

### Important implementation principle

The backend should not mirror current mock data 1:1 from either UI.

Instead:
- identify the real domain entity
- define the canonical persisted shape
- expose API responses that each client can adapt to

## Recommended Initial App Map

This is the recommended starting split. It can evolve, but do not collapse unrelated areas into one large app.

- `common`
- `users`
- `authn`
- `testimonies`
- `moderation`
- `donations`
- `notifications`
- `content`
  - inspirational pictures
  - scripture of the day
  - home curation
- `reviews`
- `admins`
- `analytics`

## Cross-Cutting Decisions To Lock Early

These decisions should be made before schema work accelerates:

- auth approach for mobile and dashboard
  - token-based API auth for mobile
  - session and/or token support for dashboard-admin usage
- role model
  - regular user
  - guest is not a persisted account type
  - admin roles should be explicit
- testimony model strategy
  - one testimony aggregate with type/status fields vs separate written/video roots
- moderation workflow states
  - draft, pending, approved, rejected, scheduled, archived, or other final set
- donation lifecycle states
  - pending, successful, declined, reversed, refunded, or final approved set
- notification strategy
  - in-app only vs extensible event-driven notification model
- media storage approach
  - local dev storage vs cloud-compatible abstraction for production
- audit fields
  - created_by, updated_by, approved_by, deleted_by, timestamps, reason fields

## API Design Direction

Use an API-first approach.

Guidelines:
- version the API from the beginning, for example `/api/v1/`
- keep request and response shapes explicit
- paginate all collection endpoints
- keep write endpoints task-oriented where that improves clarity
- keep read endpoints optimized for client use
- define stable error envelopes

Recommended endpoint families:
- `/api/v1/auth/`
- `/api/v1/users/`
- `/api/v1/profile/`
- `/api/v1/testimonies/`
- `/api/v1/moderation/`
- `/api/v1/categories/`
- `/api/v1/comments/`
- `/api/v1/favorites/`
- `/api/v1/notifications/`
- `/api/v1/donations/`
- `/api/v1/content/`
- `/api/v1/admins/`
- `/api/v1/analytics/`

### Mobile Google Auth Contract (Phase 2)

Endpoint:
- `POST /api/v1/auth/mobile/google/`

Request body:
- `id_token` (required, string): Google identity token from the mobile client
- `platform` (optional, string): `android` or `ios` for telemetry/troubleshooting

Success response (`200`):
- `token` (string): backend mobile auth token
- `user` (object): authenticated user summary
  - `email` (string)
  - `full_name` (string)
  - `phone_number` (string|null)
  - `avatar_url` (string|null)
- `is_new_user` (boolean): whether account was created during this request

Failure responses:
- `400`: missing/invalid payload
- `401`: invalid/expired Google token or audience mismatch
- `403`: user exists but is inactive/blocked

Behavior rules:
- verify Google token signature, expiry, issuer, and audience against configured client IDs
- require verified email from Google identity payload
- if user does not exist, create user + profile using Google identity data
- if user exists, log into existing account (no duplicate account creation)
- issue the same backend auth token model used by normal mobile login

## Phases

### Phase 0: Domain Discovery And Contract Lock

Build:
- review the implemented mobile and dashboard flows again from a backend perspective
- list the core backend entities, lifecycles, and relationships
- identify where the two UIs describe the same concept differently
- define the canonical backend vocabulary
- define the first-pass API surface and auth strategy
- document assumptions, risks, and open questions

Deliverables:
- backend domain map
- initial entity list
- initial role and permission model
- first-pass endpoint map
- integration assumptions document if needed
- feature-slice rollout order tied to client integration points
- working draft captured in `backend/PHASE0_DOMAIN_DISCOVERY.md`

Test:
- no code tests required yet
- review output for consistency with `mobile/` and `dashboard/frontend/`
- confirm the locked decisions are sufficient to begin the first backend slice without likely schema churn

Status: completed

### Phase 1: Project Bootstrap And Infrastructure

Build:
- scaffold the Django project in `backend/`
- create the settings package: `base.py`, `local.py`, `test.py`, `production.py`
- configure PostgreSQL settings
- set up Django REST Framework
- set up app registration structure and project URLs
- add basic health endpoint
- add linting, formatting, and test configuration
- add environment variable loading strategy
- prepare the project for slice-by-slice client integration work

Test:
- project boots successfully
- base test runner works
- system checks pass
- health endpoint responds
- local developer workflow is ready for the first integrated feature slice

Status: completed

### Phase 2: Identity, Auth, And Admin Access

Build:
- implement user model strategy and profile baseline
- implement admin account and role model
- implement registration/login/password-reset foundations needed by the clients
- implement mobile auth strategy and dashboard admin auth strategy
- define session/token issuance and revocation behavior
- add permission classes and authorization boundaries
- wire the completed auth slice into the relevant client flows
  - `mobile/` auth flows if mobile auth is in initial scope
  - `dashboard/frontend/` admin auth flows
  - both if both auth surfaces are being activated together

Sub-slices:

#### Mobile User Flows

Mobile auth strategy note:
- Mobile supports a limited guest experience in parallel with authenticated flows.
- Onboarding is first-run only and should not repeat for returning users.
- Returning users with a valid auth session go directly to authenticated home; returning users without a valid session remain able to continue as guest with restrictions.
- Guest access is non-persisted and must never receive authenticated mobile endpoints by default.

- **Slice 1 — Register with email** — user enters their full name and email address to begin registration; the backend sends a one-time code to their email and the app advances to the OTP screen
- **Slice 2 — Verify registration OTP** — user enters the code received by email; the backend confirms the code is correct and not expired, and marks the registration challenge as verified
- **Slice 3 — Complete registration** — user sets a password; the backend creates the account and profile, issues an auth token, and the user is logged in immediately
- **Slice 4 — Log in** — returning user enters email and password; the backend validates credentials, confirms the account is active, and returns an auth token
- **Slice 5 — Sign in with Google** — mobile user taps Google sign-in; app sends Google identity token to backend; backend verifies token signature/audience/expiry, finds or creates the user, and issues the normal mobile auth token
- **Slice 6 — Request password reset** — user enters their email on the forgot-password screen; the backend sends a reset code without revealing whether the email exists
- **Slice 7 — Verify reset OTP** — user enters the reset code; the backend validates it and marks it as verified
- **Slice 8 — Set new password** — user enters a new password; the backend updates it, revokes all existing tokens and sessions, and the user must log in again with the new password
- **Slice 9 — View own profile** — authenticated user opens the profile screen and sees their full name, email, phone number, and avatar

#### Admin Flows

- **Slice 10 — Super admin bootstrap (no shared entry code)** — operator provisions the first super admin account out-of-band using a secure setup path; the backend creates an active `super_admin` assignment and issues temporary login credentials or one-time setup access
- **Slice 11 — Super admin login and session** — super admin enters email and password on the dashboard login screen; the backend validates credentials, confirms an active admin assignment exists, and establishes a session
- **Slice 12 — Invite admin by role** — authenticated super admin submits an email and role code (moderator, content admin, finance admin); the backend creates or refreshes an `invited` assignment, generates a single-use time-limited invite code, and sends it by email
- **Slice 13 — Accept admin invitation** — invitee verifies the email invite code and sets a password; the backend consumes the invite code, activates the assignment (`invited` -> `active`), and opens an authenticated admin session
- **Slice 14 — Verify active session** — dashboard calls the session endpoint on load; if a valid session cookie is present the backend returns the admin's email, full name, and role code; if not, the dashboard redirects to login
- **Slice 15 — Admin logout** — admin clicks sign out; the backend destroys the session and the dashboard returns to the login screen
- **Slice 16 — Admin forgot/reset password** — admin requests password reset, verifies the reset code, and sets a new password; backend must avoid account enumeration and revoke active sessions after successful password change

Test:
- model tests for user/admin relationships and constraints
- service tests for auth flows
- API tests for login/logout, registration, Google sign-in token verification, password reset, and protected routes
- API permission tests that explicitly prove guest/unauthenticated requests are blocked on authenticated mobile actions
- replace auth mocks in the client(s) covered by this slice
- verify sign-up, sign-in, Google sign-in, sign-out, protected-route, and password-reset behavior end-to-end in the connected UI(s)

Status: completed

### Phase 3: Testimonies Core Domain

Build:
- implement testimony categories
- implement testimony aggregate and related media/content structure
- implement submission flow for written testimonies (mobile) and admin-managed video testimonies
- implement read models for mobile browse/detail use cases
- implement comments and engagement counters if included in MVP backend scope
- implement favorites if the backend will own them at this stage
- wire the completed testimony slice into the relevant client flows
  - `mobile/` browse, detail, submission, favorites, and related user-facing flows
  - `dashboard/frontend/` testimony listing/upload views if included in this slice

Sub-slices:

#### Mobile User Flows

- **Slice 1 — Browse testimonies** — user opens the testimonies feed and sees a paginated list of approved testimonies; can filter by category and search by title
- **Slice 2 — View testimony detail** — user taps a testimony and sees the full title, body, media, author name, category, view count, and comment count
- **Slice 3 — Submit a written testimony** — authenticated user fills in title, body, and category and submits; testimony enters `pending_review` status immediately
- **Slice 4 — Track own submissions** — user opens "My Testimonies" and sees all their testimonies at every status with the current status label visible
- **Slice 5 — Save a testimony to favorites** — user taps the bookmark icon on any approved testimony; testimony is added to their favorites list
- **Slice 6 — Remove a testimony from favorites** — user removes a saved testimony from their favorites list
- **Slice 7 — View favorites list** — user opens the saved/favorites screen and sees all their bookmarked testimonies paginated
- **Slice 8 — Comment on a testimony** — authenticated user types and submits a comment on an approved testimony
- **Slice 9 — Delete own comment** — user removes a comment they previously posted; cannot remove another user's comment

Access-control contract for this phase:
- guest/unauthenticated users may read public browse/detail/category/search endpoints only
- authenticated users only may submit written testimonies, manage favorites, create/delete comments, and access "My Testimonies"
- video testimony creation and upload are admin-only actions

#### Admin Flows

- **Slice 10 — Manage categories** — admin creates a new category with name and description; edits name or description of an existing category; deactivates a category so it no longer appears to mobile users; reactivates it when needed
- **Slice 11 — View all testimonies** — admin opens the testimony list and sees all testimonies regardless of status; filters by status (pending, approved, rejected, etc.) and by category; opens a detail view for any testimony
- **Slice 12 — Upload a video testimony** — admin creates testimony records with title, category, and uploaded video (with optional thumbnail and summary/body), using upload status options: `upload_now`, `schedule_for_later`, or `draft`; created records enter the appropriate moderation lifecycle state and support single-video and multiple-video upload modes in dashboard UX
  - **Slice 12.1 — Upload mode selection** — admin can switch between `Single Video Upload` and `Multiple Video Upload` from the upload-mode dropdown
  - **Slice 12.2 — Multi-video composer controls** — in multiple mode, admin can add a new video card from an `Add new video` action and remove an unneeded card from its cancel/remove icon before submission
  - **Slice 12.3 — Required payload per card** — each video card enforces required fields (`title`, `category`, `video file`) with optional `source`, optional `summary/body`, and optional thumbnail
  - **Slice 12.4 — Upload status at create-time** — admin chooses `upload_now`, `schedule_for_later`, or `draft` during creation; selected status is persisted and aligned to testimony lifecycle states
  - **Slice 12.5 — Schedule metadata validation** — when `schedule_for_later` is selected, schedule date/time must be supplied and validated before record creation
  - **Slice 12.6 — Cloud media persistence** — backend uploads video (and optional thumbnail) to Cloudinary and stores returned secure URLs on testimony records
  - **Slice 12.7 — Security and permissions** — only authenticated admins can access upload endpoints and screen actions; non-admin attempts are denied

Test:
- model tests for testimony states and relationships
- service tests for create/update/detail behavior
- API tests for list/detail/create flows and pagination/filtering
- replace testimony-related mocks in the connected UI scope
- verify browse, detail, and submission flows end-to-end in the connected client(s)

Status: completed

### Phase 4: Moderation And Review Workflows

Build:
- implement moderation states and transitions
- implement approve/reject/schedule/edit/remove workflows
- implement admin review actions and audit trail fields
- implement dashboard-facing moderation query endpoints
- define what is visible to end users based on moderation status
- wire moderation workflows into the relevant dashboard views
- update mobile visibility behavior if moderation state changes affect user-facing read flows

Sub-slices:

#### Admin Flows

- **Slice 1 — Review the pending queue** — admin opens the moderation queue and sees all testimonies awaiting review, ordered oldest first, with author name, category, and submission date visible
- **Slice 2 — Approve a testimony** — admin reads a pending testimony and approves it; testimony immediately becomes visible to all mobile users in the browse feed
- **Slice 3 — Reject a testimony** — admin rejects a pending testimony and is required to provide a written reason; the author is informed and can see the reason in their "My Testimonies" view
- **Slice 4 — Schedule a testimony** — admin approves a testimony but sets a future publish date; testimony is not visible on mobile until that date is reached
- **Slice 5 — Archive a testimony** — admin removes an approved testimony from the public feed by archiving it; the testimony is no longer visible to mobile users but is not deleted
- **Slice 6 — View moderation history** — admin opens a testimony's detail view and sees a full chronological audit trail of every moderation action taken, who took it, when, and any reason recorded
- **Slice 10 — Edit video testimony metadata** — admin opens a video testimony edit modal and updates title/category; for scheduled video testimonies, admin can also update future publish datetime with validation
- **Slice 11 — Delete testimony record from admin list** — admin can delete a testimony from the moderation list (video and text), with confirmation modal and role enforcement

#### Mobile User Flows

- **Slice 7 — See approval status in real time** — after submitting, user checks "My Testimonies" and sees their testimony move from `pending_review` to `approved` or `rejected` with the rejection reason visible if applicable
- **Slice 8 — Approved testimony appears in browse** — once approved, the testimony is visible to all users in the main feed without any action required from the author
- **Slice 9 — Scheduled testimony publishes automatically** — a scheduled testimony becomes visible in the browse feed at the scheduled time without any admin action needed at that moment

Test:
- transition tests for allowed and blocked state changes
- API tests for moderation actions, filtering, and permissions
- audit-field verification tests
- API permission tests that verify guest access to public reads and denial for authenticated writes
- replace moderation mocks in the connected UI scope
- verify moderation actions in `dashboard/frontend/` and confirm resulting visibility in `mobile/` where applicable

Status: in progress (Slices 1-9 implemented)

### Phase 5: Donations And Giving

Build:
- implement donation records and status lifecycle
- support donor identity rules for registered and guest-like flows where required
- define payment-provider integration boundary, even if real gateway integration is deferred
- implement donation history and dashboard donation-review endpoints
- implement reversal/refund bookkeeping model where in scope
- wire the giving slice into `mobile/` and the donation-review slice into `dashboard/frontend/`

Sub-slices:

#### Mobile User Flows

- **Slice 1 — Give a donation** — authenticated user enters an amount and currency and submits; the backend creates a donation record in `pending` status and returns a payment reference or redirect URL from the payment provider
  - Amount convention: `amount` is in minor currency units (`kobo` for NGN, `cents` for USD).
- **Slice 2 — Complete payment** — user is redirected to the payment provider and completes or cancels the transaction; the provider notifies the backend and the donation status updates to `successful` or `declined`
- **Slice 3 — View giving history** — user opens the giving/history screen and sees a paginated list of their own donations with amount, date, and current status for each
- **Slice 4 — View a donation detail** — user taps a donation record and sees the full detail including payment reference and status

Access-control contract for this phase:
- guest/unauthenticated users must be denied donation creation/history/detail endpoints
- authenticated users can act only on their own donation records

#### Admin Flows

- **Slice 5 — View all donations** — admin opens the donations list and sees all donations across all users; filters by status (pending, successful, declined, reversed, refunded), date range, and donor name
- **Slice 6 — View donation detail** — admin opens a specific donation and sees the full record including donor identity, amount, payment reference, provider, and status history
- **Slice 7 — Reverse a donation** — admin marks a successful donation as reversed and records a reason; the status updates and the record is preserved for audit purposes

Test:
- model tests for donation invariants
- service tests for donation creation and status updates
- API tests for donation history, admin filtering, and permission enforcement
- replace giving and donation-history mocks in the connected UI scope
- verify giving submission/history in `mobile/` and donation review/filtering in `dashboard/frontend/`

Status: in progress (Slices 1-7 implemented)

### Phase 6: Notifications And User Activity

Build:
- implement notification model and delivery/read state
- support mobile notification list needs
- support dashboard notifications history needs
- decide whether notifications are direct records, event-derived, or hybrid
- implement unread/read and deletion/archive behavior if required
- wire user notifications into `mobile/` and admin notifications history into `dashboard/frontend/`

Sub-slices:

#### Mobile User Flows

- **Slice 1 — Receive a notification on testimony approval** — when an admin approves the user's testimony, a notification appears in the user's notification centre with a title and message explaining the outcome
- **Slice 2 — Receive a notification on testimony rejection** — when an admin rejects a testimony, the user receives a notification that includes the rejection reason
- **Slice 3 — Receive a notification on new comment** — when another user comments on the user's approved testimony, the user receives a notification; commenting on one's own testimony does not generate a notification
- **Slice 4 — View notification list** — user opens the notification centre and sees a paginated list of all their notifications, newest first, with an unread count badge visible
- **Slice 5 — Mark a notification as read** — user taps a single notification; it is marked as read and the unread count decreases
- **Slice 6 — Mark all notifications as read** — user clears all unread notifications in one action; unread count returns to zero

Access-control contract for this phase:
- guest/unauthenticated users must be denied notification list/read-state actions
- authenticated users can only read/update their own notifications

#### Admin Flows

- **Slice 7 — View notification history** — admin opens the notifications history screen and sees all notifications sent across all users; filters by notification type, recipient, and read status to investigate delivery or user activity

Test:
- tests for notification creation and read-state transitions
- API tests for list, mark-read, and admin history access
- replace notification mocks in the connected UI scope
- verify notification list/read behavior in `mobile/` and notification-history behavior in `dashboard/frontend/`

Status: in progress (Slices 1-7 implemented)

### Phase 7: Content Management Domains

Build:
- implement inspirational pictures
- implement scripture of the day
- implement home page curation and featured content rules
- implement scheduling and publish windows where required
- expose mobile-facing read endpoints and dashboard-facing management endpoints
- wire content reads into `mobile/` and content-management flows into `dashboard/frontend/`

Sub-slices:

#### Admin Flows

- **Slice 1 — Upload an inspirational picture** — admin uploads a picture with a title, caption, and image URL; sets whether it is published immediately or held as a draft; optionally sets a future publish date and an expiry date after which it stops appearing
- **Slice 2 — Edit or unpublish an inspirational picture** — admin updates the caption or image URL of an existing picture, or unpublishes it so it no longer appears to mobile users
- **Slice 3 — Schedule the scripture of the day** — admin creates a scripture entry with a Bible reference, full text, and a specific calendar date; the entry is published automatically when that date is reached; no two entries can share the same date
- **Slice 4 — Edit a scripture entry** — admin updates the text or reference of a previously created scripture entry before its publish date
- **Slice 5 — Curate the home feed** — admin selects which approved testimonies appear in the featured section on the home screen and sets the display order of sections (featured testimonies, inspirational picture, scripture)

#### Mobile User Flows

- **Slice 6 — View the home feed** — user opens the app and sees the curated home screen: featured testimonies selected by the admin, the current active inspirational picture, and the scripture of the day, each in their admin-defined order
- **Slice 7 — Browse inspirational pictures** — user scrolls the inspirational pictures feed and sees all currently published and non-expired pictures ordered by the admin-defined sequence
- **Slice 8 — Read the scripture of the day** — user opens the scripture screen and sees today's published scripture entry; if no entry exists for today, the screen shows an appropriate empty state

Phase 7 slice-count note:
- Phase 7 intentionally contains 8 slices total (5 admin + 3 mobile). There is no Phase 7 Slice 9.
- Clarification: when planning references mention a "Slice 9" content publish flow, that refers to **Phase 9 / Slice 9**, not Phase 7.

Test:
- model tests for scheduling/publish invariants
- API tests for content CRUD, filtering, and visibility rules
- replace content mocks in the connected UI scope
- verify dashboard publishing/curation actions and resulting mobile content visibility

Status: in progress (Slices 1-8 implemented)

### Phase 8: Reviews, Analytics, And Operational Admin Features

Build:
- implement reviews domain if it remains a backend-owned feature
- implement admin management endpoints
- implement analytics-oriented query endpoints or reporting summaries
- keep analytics queries read-only and optimized for dashboard needs
- wire the completed admin slices into `dashboard/frontend/`

Sub-slices:

#### Admin Flows

- **Slice 1 — Review a testimony** — admin reads a testimony and leaves a rating (1–5) and written notes as an internal review record; each admin can review a given testimony only once but can update their own review
- **Slice 2 — View all reviews for a testimony** — admin opens a testimony detail and sees the list of all internal reviews left by other admins with ratings and notes
- **Slice 3 — Deactivate an admin** — super admin deactivates an existing admin account; the deactivated user is immediately blocked from logging in and their session is revoked
- **Slice 4 — Reactivate an admin** — super admin reactivates a previously deactivated admin account so they can log in again
- **Slice 5 — View the admin list** — super admin views all admin accounts with their roles and current status (invited, active, deactivated), filterable by role
- **Slice 6 — View analytics overview** — admin opens the dashboard home and sees key metrics: total registered users, total testimonies, count pending moderation, and total donation amounts by currency
- **Slice 7 — View testimony analytics** — admin opens the testimony analytics screen, selects a time period (7, 30, or 90 days), and sees a breakdown of testimonies by status and by category for that period
- **Slice 8 — View donation analytics** — admin opens the donations analytics screen, selects a time period, and sees total donation amounts grouped by status and currency
- **Slice 9 — View user registration trend** — admin sees a chart of new user registrations over time with a period filter

Test:
- API tests for admin-only access
- query tests for reporting correctness
- replace review, admin-management, and analytics mocks in dashboard scope
- verify the connected dashboard flows end-to-end

Status: not started

### Phase 9: Integration Hardening And Client Wiring Support

Build:
- add API documentation
- add seed/dev data strategy
- add stronger observability and structured logging
- validate error shapes and pagination consistency
- support staged integration of `mobile/` and `dashboard/frontend/`
- add deployment-readiness items

Sub-slices:

#### Developer / Operator Flows

- **Slice 1 — Browse the API documentation** — a developer opens `/api/v1/docs/` in a browser and sees a complete, interactive Swagger UI listing every endpoint, its parameters, request body schema, and example responses; all apps are tagged and grouped clearly
- **Slice 2 — Seed a local environment** — a developer runs `python manage.py seed_dev_data` on a fresh database and gets a fully populated local environment: admin account, categories, approved testimonies, inspirational pictures, a scripture entry for today, and sample donations; running it again does not produce duplicates or errors
- **Slice 3 — Observe a request in logs** — every inbound request produces a structured log line with method, path, authenticated user identity, response status code, and duration; key domain events (testimony submitted, testimony approved, donation created) produce their own log lines
- **Slice 4 — Diagnose an API error** — every error response from any endpoint returns the same envelope shape so clients and developers can parse failures consistently without special-casing per endpoint
- **Slice 5 — Page through any list endpoint** — every collection endpoint returns the same pagination envelope so clients can implement pagination once and reuse it across all resource types
- **Slice 6 — Verify production readiness** — an operator runs `manage.py check --deploy` with production settings and receives no errors; all required environment variables are documented in `.env.example`

#### End-to-End Verified Flows

- **Slice 7 — Full testimony lifecycle** — user registers, submits a testimony, admin approves it, testimony appears in the mobile browse feed, author receives an approval notification, another user comments and the author receives a comment notification
- **Slice 8 — Full donation lifecycle** — user initiates a donation, payment provider marks it successful, admin views it in the donations list, admin reverses it, status is updated and visible to both user and admin
- **Slice 9 — Content publish flow** — admin creates a scripture entry and an inspirational picture, both appear in the mobile home feed and on their respective screens without a server restart

Test:
- integration tests for critical cross-domain flows
- smoke tests for major endpoint families
- migration checks
- release checklist validation
- verify both clients run against the backend with the agreed slice coverage and without falling back to retired mocks for completed phases

Status: not started

## Risks To Watch Early

- building schema directly from UI mocks instead of real domain needs
- mixing mobile-user auth and dashboard-admin auth carelessly
- creating separate models for every screen instead of stable domain entities
- unclear moderation state definitions leading to migration churn
- under-specifying audit requirements for admin actions
- postponing permissions design until too late
- storing derived analytics as source-of-truth data without clear rules

## Default Delivery Pattern

For each feature area:

1. define the domain language
2. model the data and constraints
3. add service commands and query selectors
4. expose API endpoints
5. add backend tests
6. wire the relevant UI client
7. verify the integrated flow end-to-end
8. review migration and operational impact

Do not start from serializers or views.
