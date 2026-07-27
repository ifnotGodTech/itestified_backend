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
- Phase 4: Completed (Slices 1-11 implemented)
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

Status: completed (with follow-up hardening in progress)

Phase 2 hardening draft note:
- Mobile forgot-password reliability hardening is being tracked as a follow-up pass after initial completion.
- Scope of this follow-up:
  - ensure reset OTP verify/complete flows remain stable when client in-memory auth state is recreated
  - validate social-login account compatibility with password reset/set-password expectations
  - re-run end-to-end mobile auth verification on production after deployment

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
- **Slice 17 — Edit own profile name and picture** — authenticated user updates their full name and/or profile picture from the Edit Profile screen; both changes are saved to the backend and persist across sessions and devices, on any device they log into
  - Reviewed 2026-07-26 — Confirmed gap, not yet built. The "Edit Profile" screen (`account_update_edit_profile_screen.dart`) has real, reachable UI for both — tap the avatar to open a "Choose Picture"/"Delete Picture" sheet, or tap "Full Name" to edit it — but neither persists anywhere. `ProfileAccountController.choosePicture()`/`deletePicture()`/`updateName()` only mutate local in-memory state; `CurrentProfileView` (`apps/users/api/views.py`) is GET-only, so there's no backend endpoint to save to even if the mobile side were wired up. "Delete Picture" additionally shows a "Profile Picture Deleted!" success snackbar despite nothing being deleted. Bundling both fields into one slice since they're the same screen, same controller, and the same root cause (no profile update endpoint) — not worth splitting.
  - Backend: extend `CurrentProfileView` with a `patch` accepting `full_name` and `avatar` (mirrors the existing `MyNotificationPreferencesView` GET/PATCH shape). For avatar upload itself, follow the existing Cloudinary direct-upload-signature pattern already used for testimony video/thumbnail uploads (`create_direct_upload_signature` in `apps/testimonies/services/media_uploads.py`) rather than proxying image bytes through Django — needs a new folder (e.g. `itestified/profile/avatars`); since this becomes shared between two unrelated domains, worth relocating that helper to `apps/common/` at implementation time rather than importing across app boundaries.
  - Mobile: needs an image-picker dependency added (none exists in `pubspec.yaml` today) to let the user actually select/take a photo, plus wiring `DeviceTokenController`-style real GET/PATCH persistence into `ProfileAccountController` in place of the current local-only mutations.
  - Explicitly out of scope: email (already has its own working, separately-designed OTP-verified update flow — do not touch) and phone number (model field exists and is exposed via the read-only GET, but no edit UI/flow exists in the app today, and none was requested).
  - Implemented 2026-07-26, exactly as scoped above. Backend: `CurrentProfileView.patch` (full_name + avatar via the existing `ProfileSerializer`, already-correct model-level validation — non-blank name, valid URL) and `ProfileAvatarUploadSignatureView` (`POST /profile/me/avatar-upload-signature/`, `IsAuthenticated`, mobile-only). Relocated the reusable half of `create_direct_upload_signature`/`CloudinaryUploadError`/`CloudinaryUploadSignature`/`configure_cloudinary` from `apps/testimonies/services/media_uploads.py` into `apps/common/services/media_uploads.py` (new `avatar` resource-type branch, folder `CLOUDINARY_PROFILE_AVATAR_FOLDER` / default `itestified/profile/avatars`); testimonies re-exports everything it used to export, so no existing testimony call site or test needed to change. 15 new backend tests (7 in `apps/common/tests/test_media_uploads.py` exercising the real folder-selection logic per resource type — `api_sign_request` is pure local HMAC hashing, no network I/O, so no Cloudinary mocking was needed; 8 in `apps/users/tests/test_api.py` covering patch auth/update/partial-update/validation and the signature endpoint). Full backend suite: 79 tests in the affected apps, `manage.py check` / `makemigrations --check` clean (no schema change — both fields already existed).
  - Mobile: added `image_picker` and a new `AvatarUploadSource` abstraction (`lib/features/profile/presentation/state/avatar_upload_source.dart`, same testable-wrapper pattern as `PushTokenSource`) — picks a gallery image, then uploads it directly to Cloudinary via `MultipartRequest` using the signed payload from the backend (mirrors the dashboard's existing `upload-video-screen.tsx` direct-upload approach, translated to Dart). `ProfileAccountController.choosePicture()`/`deletePicture()`/`updateName()` are now real, async, and optimistic — update local state immediately, PATCH the backend, and revert on failure so the UI never claims a save that didn't happen. `ProfileAvatarHeader` now renders the real photo via `NetworkImage` instead of a generic icon that never reflected an actual picture regardless of what "hasImage" claimed. Added iOS `NSPhotoLibraryUsageDescription` (Android's modern photo picker needs no manifest permission at all).
  - Tests: 9 tests in `profile_account_controller_test.dart` (hydration now asserts the real `avatarUrl` instead of a boolean; `updateName`/`choosePicture`/`deletePicture` each covered for success, revert-on-failure, and — for `choosePicture` — the user-cancels-the-picker case). `flutter analyze` clean. Regression batch (25 tests across profile/push/notification files) passed. Two pre-existing tests in `profile_flow_test.dart` (`email update flow validates and accepts OTP`, `logout keeps selected display mode`) failed during a full-file batch run — confirmed via `git stash` (this slice's changes fully reverted) that both reproduce identically: the whole file makes real calls to the live `itestified-backend.onrender.com` and the live backend was returning HTTP 400 for every endpoint at the time, unrelated to this slice.

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

Status: Completed, including Slice 17 (edit own profile name/picture), found during pre-store-submission review and implemented 2026-07-26 — see its notes above.

Post-completion fix, 2026-07-26 (mobile-only, found via user report of "home screen not showing content" that turned out to be intermittent): traced to two compounding client-side bugs in the cached-session validation flow (`app_flow_controller.dart` / `api_client.dart`), not the backend. `ApiClient._throwForHttpError` classified *any* non-2xx response with a non-empty body as `AuthException`, regardless of the real status code — a 500/502/503 error page (e.g. a gateway error while the deployed backend is still starting up after being idle) was indistinguishable from a genuine 401/403. `AppFlowController._validateCachedSession`'s `on AuthException` handler deletes the cached token on that signal, so a single transient server error at startup could permanently sign a user out and strand them in guest mode even though their token was perfectly valid — reproduced live: a fresh launch showed "Guest Mode" while `ApiClient` logs simultaneously showed `auth=true` on every request, proving the token was still present but the access-state layer had given up on it. Fixed both: only a real 401/403 is now classified as `AuthException` (everything else becomes `NetworkException`), and session validation retries once after 2s on a transient failure before falling back to guest, never clearing the token for anything short of a confirmed auth failure. New tests: 7 in `api_client_test.dart` (status-code classification matrix, including the 502-while-starting-up case), 3 in `app_flow_controller_test.dart` (transient-failure-then-retry-succeeds, real-401-clears-immediately-no-retry, repeated-failure-falls-back-to-guest-without-clearing-token).

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

Post-completion fix, 2026-07-26 (found via user report of "avatar doesn't show in my post"): `TestimonyListSerializer`/`TestimonyDetailSerializer`/`FavoriteTestimonySerializer` and `TestimonyCommentSerializer` computed `author_name` from `author.profile` but never exposed `author.profile.avatar` alongside it — no client could ever show a real author photo anywhere, only initials or generic icons. Added `author_avatar` to both, reusing the already-`select_related("author", "author__profile")` querysets (no new N+1). Mobile: `Testimony` gained `speakerAvatarUrl` (mapped in the single shared `_fromApiPayload` used by list/detail/search/favorites everywhere), rendered via `NetworkImage` in the testimony detail byline and home discover cards. `CommentThread.authorImageUrl` already existed and `comment_thread_card.dart` was already built to render it — it was simply never populated from real API data (`comment_thread_controller.dart::_fromApiComment`) until now. New tests: 3 backend (`test_api.py`), 2 mobile (`testimony_detail_remote_provider_test.dart`, `comment_threads_provider_test.dart`).

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

Status: Completed (Slices 1-11 implemented)

Post-implementation review note (2026-07-24): audited this phase against the
implemented code (`apps/testimonies/models.py`, `services/commands.py`,
`api/views.py`, `api/serializers.py`, `api/urls.py`, the scheduled-publish
cron job, and all tests). Findings addressed as part of the review:
- Transition-validity checks (e.g. "only pending testimonies can be
  approved") previously lived only in the views, not the services — any
  future caller of `approve_testimony`/`reject_testimony`/
  `schedule_testimony`/`archive_testimony` could have silently skipped the
  guard. Moved into `services/commands.py` itself, raising a new
  `TestimonyTransitionNotAllowedError` (`apps/testimonies/exceptions.py`),
  caught and translated to a 400 at the view layer — matching the existing
  `donations` app's exception-handling convention.
- Added the missing "blocked transition" tests the Test section above always
  called for (e.g. approving an already-approved testimony returns 400) —
  previously only the allowed side of each transition was tested.
- Added permission-denial tests for approve/reject/schedule/archive (only
  delete and video-upload had them before).
- `AdminUploadNowVideoTestimonyView` duplicated moderation-history-writing
  inline instead of going through a service; extracted into
  `upload_now_video_testimony()` alongside the other transition commands.
- Renamed `AdminDeleteVideoTestimonyView` / `admin-testimony-delete-video` to
  `AdminDeleteTestimonyView` / `admin-testimony-delete` — the endpoint always
  deleted both video and text testimonies (correct per Slice 11), the old
  name just implied video-only.

Open follow-up (not blocking): Slice 11's spec text calls for "role
enforcement" on delete. Today that's just `IsActiveAdmin` — any active admin
role (including finance_admin) can permanently delete a testimony record.
Left as-is since the plan doesn't specify which roles should be restricted;
revisit if delete should be limited to specific roles (e.g. content_admin/
super_admin only).

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
  - Reviewed 2026-07-24 — Confirmed bug, not fixed. Backend (`apps/donations/services/commands.py::create_donation`) is correct: creates a `pending` `Donation`, returns reference/`checkout_url`. Mobile (`mobile/lib/features/giving/presentation/state/giving_controller.dart`) calls the right endpoint with the right fields, but sends the raw digits the user typed as `amount` with **no minor-unit conversion** (`int.tryParse(amountText...)`, no `× 100` anywhere in the feature). See Slice 2 for the matching backend-side half of this bug.
  - Fixed 2026-07-24 — see post-implementation review note below.
  - Found and fixed 2026-07-24 (post-deploy report): on the deployed backend, `FLUTTERWAVE_SECRET_KEY` was unset, so `create_donation()` took a silent fallback path that fabricated `checkout_url` as `https://checkout.flutterwave.com/pay/{reference}` and returned 201 as if the donation were ready to pay. That URL was never issued by Flutterwave's API, so the mobile checkout WebView loaded it and got "Cannot GET /pay/{reference}" from Flutterwave's own server — reproduced live on an emulator against the deployed backend. Fixed `create_donation` to raise `DonationGatewayNotConfiguredError` when the key is missing (matching `verify_donation`'s existing behavior) instead of fabricating a non-functional URL; `DonationCreateView` now returns 503 with a clear message in that case. This is a code-level fix only — the underlying cause is that the deployed backend's `FLUTTERWAVE_SECRET_KEY` env var is still not set, which is an operator/deployment task, not something fixable from the codebase.
- **Slice 2 — Complete payment** — user is redirected to the payment provider and completes or cancels the transaction; the provider notifies the backend and the donation status updates to `successful` or `declined`
  - Reviewed 2026-07-24 — Confirmed bug, not fixed. `services/flutterwave.py::initialize()` forwards `donation.amount` (minor units) to Flutterwave's `amount` field unconverted; Flutterwave's API expects the major unit. Combined with Slice 1's missing mobile-side conversion, the amount convention is broken at both ends of the round trip — untested anywhere (no test mocks the Flutterwave call and asserts the payload). Separately, mobile's "complete payment" is not a real payment flow: no WebView/browser redirect to `checkout_url` exists anywhere in the app (`pubspec.yaml` has no `webview_flutter`/`url_launcher`/deep-link package); the user manually types in a transaction ID after paying elsewhere, and the verify response's status is never inspected (`giving_checkout_screen.dart` treats any non-throwing `POST /donations/verify/` as success, so a `declined` result would be silently shown as success).
  - Fixed 2026-07-24 — see post-implementation review note below.
- **Slice 3 — View giving history** — user opens the giving/history screen and sees a paginated list of their own donations with amount, date, and current status for each
  - Reviewed 2026-07-24 — Confirmed gap, not fixed. Backend pagination (`DonationMineListView` + `DonationPagination`) is correct. Mobile (`GiftHistoryController.refresh()`) never sends a `page` param and has no scroll-driven fetch — only page 1 is ever reachable. The date field is captured on the entity but not rendered on the list row (only used in the filter UI), so the row itself shows amount + status but not date as the slice requires.
  - Fixed 2026-07-24 — see post-implementation review note below.
- **Slice 4 — View a donation detail** — user taps a donation record and sees the full detail including payment reference and status
  - Reviewed 2026-07-24 — Confirmed gap, not fixed. Backend `GET /donations/mine/<pk>/` exists and returns the full record, but mobile never calls it — the detail view is a bottom sheet built from the list item already in memory, with no per-id endpoint used at all. Status and payment reference are shown as required, but amount is not shown anywhere in the detail view; "Recipient Details" (`'iTestified'`) and "Transaction Type" (`'Flutterwave'`) are hardcoded strings rather than derived from API data; "Report an issue"/"Share Receipt" buttons are non-functional stubs (`pop()` only).
  - Fixed 2026-07-24 — see post-implementation review note below. "Report an issue"/"Share Receipt" stubs were intentionally left as-is (out of the slice's stated scope — "full detail including payment reference and status").

Access-control contract for this phase:
- guest/unauthenticated users must be denied donation creation/history/detail endpoints
- authenticated users can act only on their own donation records
- Reviewed 2026-07-24 — Confirmed gap, not fixed. Backend enforces this correctly (`IsAuthenticated` + own-user filtering on all three endpoints, covered by `test_donation_endpoints_require_authentication`). Mobile does not enforce it client-side: no route guard on `/giving` or `/giving-history` in `app_router.dart`, and the feature doesn't reuse the app's own established guest-gating pattern ("Join Our Community" modal, used elsewhere for testimonies/home). A guest can reach both screens and attempt to donate; the resulting 401 only ever surfaces as a raw error string, not a deliberate prompt. The gift-history guest screen's "View Gift History" and "Create an Account" buttons are empty no-ops.
- Fixed 2026-07-24 — see post-implementation review note below. Note: there is still no route guard in `app_router.dart` itself; the fix is the in-screen "Join Our Community" prompt on both `giving_screen.dart` and `gift_history_screen.dart`, matching the existing testimony-submission pattern rather than adding a new router-level mechanism.

#### Admin Flows

- **Slice 5 — View all donations** — admin opens the donations list and sees all donations across all users; filters by status (pending, successful, declined, reversed, refunded), date range, and donor name
  - Reviewed 2026-07-24 — Solid. Implemented and tested end-to-end (`AdminDonationListView`, status/date-range/donor-name filters, admin-only via `IsActiveAdmin`, paginated). Dashboard integration confirmed working during this session's earlier B4/B9 passes.
- **Slice 6 — View donation detail** — admin opens a specific donation and sees the full record including donor identity, amount, payment reference, provider, and status history
  - Reviewed 2026-07-24 — Solid. `AdminDonationDetailView` + `AdminDonationDetailSerializer` return donor identity, amount, payment reference, provider, and full status history; tested.
  - Reviewed 2026-07-24 (later pass) — That review only checked the backend; it never checked whether `dashboard/frontend` actually called `AdminDonationDetailView`. It didn't: there was no `dashboard/frontend/src/app/api/admin/donations/[donationId]/route.ts` (only a `reverse/` sub-route existed), and the "Donation Detail" modal (`donations-overlays.tsx`) rendered only the fields already present on the list row from `AdminDonationListView` — donor, email, reference, amount, currency, status, date. `provider` and `status_history`, which this slice's own user story requires and which the backend correctly returns, were never fetched or shown anywhere in the dashboard. Same class of backend-solid/dashboard-disconnected gap as Slice 7, just not caught in the first pass.
  - Fixed 2026-07-24. Added `GET dashboard/frontend/src/app/api/admin/donations/[donationId]/route.ts`, proxying to `AdminDonationDetailView` with session cookies forwarded, and a `mapDonationDetail()` mapper (`get-donations-view-model.ts`) that surfaces `provider` and `status_history` alongside the existing fields. `donations-overlays.tsx`'s detail modal now fetches this endpoint on open (`DonationDetailBody`, keyed per donation id) instead of reusing the in-memory list row, showing a loading state, then donor identity/amount/reference/currency/provider/status/date plus a status-history list (from → to, reason, actor, date). Added regression tests: a `mapDonationDetail` unit test (`get-donations-view-model.test.ts`) asserting provider/status-history mapping, and a `donations-page.test.tsx` test asserting the modal calls `/api/admin/donations/<id>` and renders the fetched provider and status-history reason rather than only list-row fields. Full `dashboard/frontend` suite (152 tests) and typecheck/lint pass with no regressions. Live-verified 2026-07-24: ran the real backend against local Postgres, seeded a donation and reversed it through the actual `reverse_donation` service (real status-history row, real actor), logged into the dashboard as a real admin (not `E2E_BYPASS_AUTH`), and drove the browser with Playwright to open the donation's action menu → "View details". Confirmed via screenshot that the modal calls `GET /api/admin/donations/1` (200) and renders `Provider: flutterwave` and a `Status history` entry (`successful → reversed`, the real reason text, `by admin@itestified.app`) that were not visible before this fix. Verification donation and dev servers cleaned up afterward.
- **Slice 7 — Reverse a donation** — admin marks a successful donation as reversed and records a reason; the status updates and the record is preserved for audit purposes
  - Reviewed 2026-07-24 — Confirmed bug, not fixed, backend/frontend split. Backend (`reverse_donation`) is solid: validates the transition (`DonationNotReversibleError` unless `SUCCESSFUL`), uses `select_for_update()` row locking, records audit history, and has both allowed- and blocked-transition tests. `dashboard/frontend`'s reversal confirmation modal (`donations-overlays.tsx`, the `showReasonModal` step) does not match: it displays a hardcoded donor name/email/transaction ID instead of the real selected donation's fields (which are available and correctly used elsewhere on the same page), and "Reason for Reversal" — marked required in the UI — is a static label, not an input; every reversal is submitted with the same hardcoded reason string (`"Admin verification request"`) regardless of what the admin intends, defeating the audit-trail purpose the backend correctly built.
  - Fixed 2026-07-24. `donations-overlays.tsx`'s reason modal now renders `selectedRow.donor`/`.email`/`.reference`/`.amount` instead of hardcoded values, and "Reason for Reversal" is a real controlled `<textarea>` (extracted into a `ReversalReasonSection` subcomponent so its state resets per donation via a `key`); the submit URL now encodes the admin's typed reason instead of a fixed string, and the Confirm button is disabled until a reason is entered. Added a regression test (`donations-page.test.tsx`) asserting the real donation fields render, the old hardcoded values are absent, the button is disabled empty and enabled once typed, and the typed reason reaches the form's submit URL. Verified visually with a real browser (Playwright, `E2E_BYPASS_AUTH=1`) against the actual rendered modal, not just the test assertions. Full `dashboard/frontend` suite (149 tests) and typecheck/lint pass with no regressions.

Cross-cutting findings (not specific to one slice), reviewed 2026-07-24:
- Backend admin donation views (`AdminDonationListView`/`AdminDonationDetailView`/`AdminDonationReverseView`) don't pin `authentication_classes`, unlike the equivalent views in `testimonies`/`authn` (which explicitly restrict to `SessionAuthentication`). They fall through to the project default (Session **+ Token**), so a user holding both a mobile API token and an admin role could call `AdminDonationReverseView` via Token auth, bypassing the CSRF protection Session auth enforces on state-changing requests. Still open — Slice 7's dashboard bug (below) was the priority for this review pass, not this backend hardening item.
  - Fixed 2026-07-24. Pinned `authentication_classes = [SessionAuthentication]` on all three admin donation views (`apps/donations/api/views.py`), matching `testimonies`/`authn`. Updated the existing admin donation API tests to authenticate via `self.client.force_login(...)` instead of `Token`, and added `test_admin_donation_endpoints_reject_token_authentication` asserting all three endpoints now return 403 for Token-authenticated requests. `apps.donations` suite (21 tests) and the full backend suite pass (149 tests; the same pre-existing 10 failures/10 errors, all in `apps.authn`, unrelated SMTP config issues). `manage.py check` and `makemigrations --check` are clean. Live-verified against a running backend: a real admin API token now gets `403` on `GET /donations/admin/donations/`, `GET /donations/admin/donations/<id>/`, and `POST /donations/admin/donations/<id>/reverse/`, while a real cookie-based admin session still gets `200`/`200` on the same list/detail endpoints. Test token and verification server cleaned up afterward.
- Mobile had an entirely orphaned mock layer for this feature (`giving/data/datasources/giving_local_datasource.dart`, `giving_repository_impl.dart`, `giving_repository.dart`, `get_gift_history.dart`) — hardcoded `GiftRecord`s, never registered in DI, never called. Removed 2026-07-24 as part of the mobile Slice 1-4 rebuild; see post-implementation review note below.
- No mobile test exercised `startPayment()`, the amount conversion, the checkout/verify flow, guest denial, or pagination for this feature — the one relevant test (`test/features/part6/part6_flow_test.dart`) only asserted that `/giving` and `/giving-history` resolve to the right widget type. Fixed 2026-07-24 — see post-implementation review note below.

Test:
- model tests for donation invariants
- service tests for donation creation and status updates
- API tests for donation history, admin filtering, and permission enforcement
- replace giving and donation-history mocks in the connected UI scope
- verify giving submission/history in `mobile/` and donation review/filtering in `dashboard/frontend/`
- Reviewed 2026-07-24: backend model/service/API tests for slices 5-7 are solid, including blocked-transition coverage. No test anywhere (backend or mobile) covers the Flutterwave amount payload, which is exactly where the critical Slice 1/2 bug lives — this is the highest-priority test gap to close before fixing that bug.
- Closed 2026-07-24: added a backend regression test asserting the exact Flutterwave payload amount, and a mobile test suite for the giving feature (entity mapping, use cases, repository guard behavior, amount-conversion/truncation, controller `startPayment()`, and gift-history pagination/filtering) — see post-implementation review note below.

Status: Completed. Slices 1-7 are solid, (for the mobile slices) live-verified in production, and Slice 6's dashboard detail view plus the cross-cutting admin-auth hardening item (`authentication_classes` on the admin donation views) are now fixed and verified — see the post-implementation review notes below and the per-slice/cross-cutting notes above for what changed in this pass.

Post-implementation review note (2026-07-24): implemented Slices 1-4 for
real, backend first then mobile, following `mobile/AGENTS.md`'s Clean
Architecture spec.
- Backend: fixed `services/flutterwave.py::initialize()` to convert
  `amount` from minor units to major units (`amount / 100`, formatted
  `"%.2f"`) before sending it to Flutterwave — this was the critical bug
  spanning Slices 1-2, since Flutterwave's API expects major units but our
  internal convention (and the mobile client) used minor units. Added a
  regression test (`test_phase5_slice1_create_donation_sends_major_unit_amount_to_flutterwave`)
  asserting the exact payload sent to the gateway. Full backend suite still
  passes (146 tests; the pre-existing 10 failures/10 errors are unrelated
  SMTP config issues, confirmed via `git stash` before this work started).
- Mobile: rebuilt the `giving` feature from the ground up as Clean
  Architecture (`domain/{entities,repositories,usecases,failures}`,
  `data/{datasources,repositories}`, `presentation/{state,screens,widgets}`),
  replacing the old feature that mixed dead mock code with direct
  `ApiClient` calls from the UI layer. Removed the orphaned mock
  datasource/repository entirely.
  - Slice 1: `GivingState.setAmount()` now accepts digits and a single
    decimal point (max 2 decimal places) and converts to minor units via
    `(amountMajorUnits * 100).round()` — the raw-digit bug is fixed at the
    input boundary, not patched downstream.
  - Slice 2: added a real in-app WebView checkout (`webview_flutter`)
    that loads the donation's `checkout_url`, intercepts Flutterwave's
    redirect back via a navigation delegate, and calls
    `POST /donations/verify/` — the verified donation's `status` (not just
    "the request didn't throw") now determines whether the success or
    declined screen is shown.
  - Slice 3: `GiftHistoryController` now tracks `page`/`hasNextPage` and
    exposes `loadMore()`, wired to a scroll listener in
    `gift_history_screen.dart`; the list row shows the donation date
    alongside amount and status.
  - Slice 4: tapping a donation now calls
    `GET /donations/mine/<id>/` for the real record instead of reusing the
    in-memory list item; the detail sheet shows amount (previously
    missing entirely) alongside status, payment reference, and date.
    "Recipient Details"/"Transaction Type" remain hardcoded
    ("iTestified"/"Flutterwave") deliberately — this is a single-recipient,
    single-provider system, so those values are genuinely static, not a
    gap.
  - Access control: added the app's existing "Join Our Community" guest
    prompt to both `giving_screen.dart` and `gift_history_screen.dart`,
    matching the pattern already used for testimony submission.
  - Added `GiftStatus.reversed`/`GiftStatus.refunded` (previously missing
    from the entity entirely, so those donations would have silently
    rendered as "Pending").
  - Added 40 new mobile tests across entity mapping, all four use cases,
    repository guard behavior, amount-conversion/truncation edge cases,
    `GivingController.startPayment()`, and `GiftHistoryController`
    pagination/filtering, using the codebase's existing hand-rolled-fake
    pattern (no mocking library is installed). Full mobile suite and
    `flutter analyze` pass with no new regressions.

Open follow-up (not blocking Slices 1-4, tracked above as still-open
items): Slice 7's dashboard reversal-modal bug and the admin
donation-views `authentication_classes` hardening item are unchanged by
this pass.

Post-deploy live verification (2026-07-24): after pushing the Slice 1-4
fixes, ran the actual mobile app on an Android emulator against the live
Render backend (not just local tests) and found two more issues that only
showed up under real deployment conditions, both now fixed and pushed:
- The deployed backend had `FLUTTERWAVE_SECRET_KEY` unset (an env var gap,
  not a code bug — see Slice 1's note above) — once set, live-tested a full
  donation in both **NGN and USD** and confirmed the correct major-unit
  amount reached Flutterwave's real checkout page for both currencies, and
  confirmed USD is enabled on the Flutterwave merchant account (it was an
  open question, not a known gap).
- Discovered a client-side reliability gap by reproducing it live: if a
  user leaves the checkout WebView before Flutterwave's redirect fires
  (closes the app, backgrounds it, etc.), the donation stays `pending`
  forever, since redirect-based verification is the only path that updates
  it. Set up the Flutterwave webhook (`FLUTTERWAVE_SECRET_HASH` +
  `DonationProviderCallbackView`, which already existed from Phase 5's
  original build) as the fix — it lets Flutterwave notify the backend
  independently of the client. While wiring it up, found and fixed a real
  bug in the webhook itself: `DonationProviderCallbackSerializer.status`
  was a `ChoiceField` restricted to our own `DonationStatus` values
  (`"successful"`/`"declined"`), but Flutterwave's real webhook payload uses
  its own vocabulary (`"successful"`/`"failed"`) — a real failed-payment
  webhook would have been rejected with a 400 instead of ever marking the
  donation declined. Fixed by making `status` a plain `CharField` and
  normalizing once in the view regardless of Flutterwave's exact wording.
  Added a regression test using Flutterwave's real `"failed"` value.
  Verified live by sending real webhook calls (matching two donations stuck
  from manual testing) against the deployed backend — one correctly
  resolved to `successful`, the other to `declined`, both matching the
  transactions' true state on Flutterwave's side.
- Not yet live-verified: the guest-gating access-control fix (the "Join Our
  Community" prompts on `giving_screen.dart`/`gift_history_screen.dart`).
  All live testing this pass was done as a registered user; guest-path
  behavior is covered by the code change and existing pattern reuse but has
  not been exercised on-device.

### Phase 6: Notifications And User Activity

Build:
- implement notification model and delivery/read state
- support mobile notification list needs
- support dashboard notifications history needs
- decide whether notifications are direct records, event-derived, or hybrid
- implement unread/read and deletion/archive behavior if required
- wire user notifications into `mobile/` and admin notifications history into `dashboard/frontend/`
- added 2026-07-25 (not yet implemented): extend delivery beyond in-app polling to real push notifications (FCM), so users receive notifications while the app is backgrounded or fully closed, and tapping one opens the app to the relevant screen — see the new "Push Notifications" sub-slices below. This is additive: the existing in-app notification centre, polling, and everything already shipped for Slices 1-8 stays as-is and is not being removed or replaced.

Sub-slices:

#### Mobile User Flows

- **Slice 1 — Receive a notification on testimony approval** — when an admin approves the user's testimony, a notification appears in the user's notification centre with a title and message explaining the outcome
  - Reviewed 2026-07-24 — Solid. `notify_testimony_approved` (`apps/notifications/services.py:7-14`) sets a title/message; `NotificationsController.refresh()` calls the real `GET /notifications/` endpoint and `NotificationItem.fromApi` maps `notification_type: "testimony_approved"` and renders `title`/`message`. No gap found.
- **Slice 2 — Receive a notification on testimony rejection** — when an admin rejects a testimony, the user receives a notification that includes the rejection reason
  - Reviewed 2026-07-24 — Solid. `notify_testimony_rejected` embeds the reason directly in `message` (`services.py:17-25`); the mobile mapping/rendering path is the same as Slice 1, so the reason reaches the UI. No gap found.
- **Slice 3 — Receive a notification on new comment** — when another user comments on the user's approved testimony, the user receives a notification; commenting on one's own testimony does not generate a notification
  - Reviewed 2026-07-24 — Solid. The "not on own testimony" rule is enforced server-side by `notify_testimony_comment`'s callers; mobile has no logic that could violate it since it only renders whatever the API returns, and `testimony_comment` maps/renders correctly on mobile.
- **Slice 4 — View notification list** — user opens the notification centre and sees a paginated list of all their notifications, newest first, with an unread count badge visible
  - Reviewed 2026-07-24 — Confirmed gap, not fixed. The list loads and the unread badge is real (fed from the server's `unread_count`, not hardcoded — confirmed via `unreadNotificationCountProvider`). But pagination was not implemented: `NotificationsController.refresh()` called `Endpoints.notifications` with **no `page` param at all**, and `notifications_screen.dart`'s `ListView.builder` had no `ScrollController`/load-more trigger — same bug class as the gift-history pagination gap in Phase 5 Slice 3. Anyone with more than 20 notifications (the backend's page size) would never see the older ones.
  - Fixed 2026-07-24. Added `Endpoints.notificationsPage(int page)` (`core/network/endpoints.dart`), mirroring `donationsMinePage`. `NotificationsState` now tracks `page`/`hasNextPage`/`isLoadingMore`; `refresh()` fetches page 1 and reads `hasNextPage` from the paginated response's `next` field; added `loadMore()` guarding on `isLoadingMore || isLoading || !hasNextPage`, fetching `page + 1` and appending results. `notifications_screen.dart` now wires a `ScrollController` that calls `loadMore()` within 200px of the bottom and renders a trailing spinner row while `hasNextPage` is true. Added `notifications_pagination_test.dart` (controller-level, `MockClient`-backed) asserting `refresh()` requests page 1, `loadMore()` requests and appends page 2, and `loadMore()` is a no-op when there is no next page. `flutter analyze` is clean; the new tests and the pre-existing `notifications_controller_test.dart`/`notifications_screen_actions_test.dart` pass.
- **Slice 5 — Mark a notification as read** — user taps a single notification; it is marked as read and the unread count decreases
  - Reviewed 2026-07-24 — Solid. `NotificationTile.onTap` calls `markAsRead(id)`, which POSTs to `/notifications/<id>/read/` (an exact match for the backend route) and recomputes `unreadCount` locally, reflected immediately by the badge. Minor caveat: a failed POST is silently swallowed and the local mark-as-read still applies, so the badge can drift from the server until the next `refresh()` — not fixed in this pass, robustness-only, not a functional break.
  - Fixed 2026-07-24 (later pass). `markAsRead()` now applies the optimistic update first, and on a failed POST reverts `items`/`unreadCount` back to their pre-mutation values and rethrows, instead of silently keeping a write that never happened server-side. `notifications_screen.dart`'s tile `onTap` catches that rethrow and shows a `SnackBar` with the error. Added `notifications_controller_test.dart`'s `reverts the optimistic update and rethrows when the write fails` (stateful `MockClient` fake backend) and `notifications_write_failure_test.dart` (widget-level, asserts the `SnackBar` appears).
- **Slice 6 — Mark all notifications as read** — user clears all unread notifications in one action; unread count returns to zero
  - Reviewed 2026-07-24 — Solid, same swallowed-error caveat as Slice 5. `markAllRead()` POSTs to `Endpoints.notificationsMarkAllRead`, matching the backend route, and is wired from the AppBar's "Mark All Notifications as read" action.
  - Fixed 2026-07-24 (later pass). Same fix as Slice 5: `markAllRead()` reverts on failure and rethrows; the AppBar's "Mark All Notifications as read" action catches it and shows a `SnackBar`. Covered by `notifications_write_failure_test.dart`'s `shows an error when "mark all as read" fails`.

Access-control contract for this phase:
- guest/unauthenticated users must be denied notification list/read-state actions
- authenticated users can only read/update their own notifications
- Reviewed 2026-07-24 — Confirmed gap, not fixed. Backend is solid: `IsAuthenticated` on all three views, `get_queryset` filters `recipient=request.user` (`apps/notifications/api/views.py:24-31`), so cross-user access is impossible and unauthenticated calls get a real 401/403. Mobile had **no client-side guest gate at all** on `NotificationsScreen` — the only thing stopping a guest was that the bell icon isn't rendered in `GuestHeader` (`discover_screen.dart`) or in `_buildGuestItems` (`profile_screen.dart`), i.e. no navigational path exists today, but no defense either. If a guest ever reached the route (deep link, future nav change), `refresh()`'s 401 was silently swallowed into a blank "No Notifications Yet" screen — the error message was set on state but never displayed — worse than the raw-error pattern flagged for Phase 5's guest gap.
  - Fixed 2026-07-24. Added an explicit guest check to `NotificationsScreen` (`ref.watch(appFlowProvider).access`): a guest now sees a dedicated prompt card ("Create an account or log in to see your notifications.") with a "Create an Account or Log In" button that opens the same "Join Our Community" dialog used by `giving_screen.dart`/`gift_history_screen.dart`, instead of the search/filter/bulk-action AppBar and notification list. Added `notifications_guest_gate_test.dart` asserting the guest sees the prompt (not the search/filter/popup-menu controls, not a blank "No Notifications Yet") and that a registered user still sees the normal controls.
- Cross-cutting cleanup 2026-07-24: removed an orphaned Clean-Architecture layer for this feature (`domain/repositories/notifications_repository.dart`, `data/repositories/notifications_repository_impl.dart`, `domain/usecases/get_notifications.dart`) — never registered in DI, never referenced by any controller/screen/test (confirmed via `grep -rn "NotificationsRepositoryImpl\|GetNotifications\b\|NotificationsRepository\b" lib/ test/`), same dead-code pattern as the orphaned `giving_local_datasource.dart` layer removed in Phase 5. `NotificationsLocalDataSource` (used directly by the controller for seed/offline content) is real and stays.

#### Admin Flows

- **Slice 7 — View notification history** — admin opens the notifications history screen and sees all notifications sent across all users; filters by notification type, recipient, and read status to investigate delivery or user activity
- **Slice 8 — Manage notification preferences** — admin opens Notification Settings and toggles "Allow Email Notifications," "New Donation Received," and "Thank You Email"; changes are saved and reflected on reload
  - Reviewed 2026-07-24 — Confirmed gap, not fixed. The CRUD half is solid: `MyNotificationPreferencesView` (`GET`/`PATCH /notifications/preferences/me/`) + `UserNotificationPreferenceSerializer` persist `allow_email_notifications`, `notify_new_donation_received`, and `send_donation_thank_you_email` on `UserNotificationPreference`, and the dashboard's Notification Settings page (`notification-settings-page.tsx`, `get-notification-settings-view-model.ts`) correctly reads/writes all three toggles. But none of the three preferences gate any actual behavior anywhere in the codebase: `notify_new_donation_received` is never read — no notification is created for admins when a donation is submitted; `send_donation_thank_you_email` is never read — no thank-you email is sent to a donor after a successful donation; `allow_email_notifications` is never read either. `apps/donations/services/commands.py` (`create_donation`/`verify_donation`/`apply_provider_callback`/`reverse_donation`) never imports `apps.notifications`, and `apps/notifications/services.py` only has notification helpers for testimonies (approved/rejected/submitted/comment/new-video) — none for donations. The only real `send_mail`-style code in the backend lives in `apps/authn/services/commands.py` (OTP/password-reset/invite flows only). The settings page is a fully working, tested form for a set of switches that are currently disconnected from the system — flipping any of them has zero effect.
  - Correction 2026-07-25: the "only real `send_mail`-style code... in `apps/authn`" framing above was accurate about *location* but wrong about *mechanism* — it's not SMTP, it's a genuine HTTP API integration with Brevo (`https://api.brevo.com/v3/smtp/email`, dispatched via `EMAIL_PROVIDER=brevo` in `.env`), confirmed live/working. The unrelated SMTP (`EMAIL_HOST*`) and Resend (`RESEND_*`) settings/code paths are dead weight from earlier provider experiments, not the active path — noted here for the pending settings-cleanup follow-up, out of scope for this fix.
  - Fixed 2026-07-25. Extracted the provider-dispatch logic (`resend`/`brevo`/SMTP fallback) out of `apps/authn/services/commands.py::_send_email` into a new shared `apps/common/services/email.py::send_email` (+ `apps/common/exceptions.py::EmailProviderNotConfiguredError`), since it's now needed by two apps, not one; `apps/authn`'s `_send_email` is now a thin wrapper that re-raises as its own `EmailDeliveryError` for backward compatibility — `apps.authn`'s external behavior/exception contract is unchanged, confirmed by the full `apps.authn` suite still failing/passing on the exact same 20 tests as before the refactor (see Test section).
    - Added `NotificationType.DONATION_RECEIVED` (+ migration) and `apps/notifications/services.py::notify_admins_of_new_donation`, which bulk-creates a `UserNotification` for each active admin, honoring each admin's own `notify_new_donation_received` preference (default opted-in, matching the model default for admins with no preference row yet). Wired into `create_donation` via `transaction.on_commit(...)`, firing once the pending donation and its Flutterwave checkout are successfully created.
    - Added `apps/donations/services/notifications.py::maybe_send_donation_thank_you_email`, gated on the donor's own `send_donation_thank_you_email` **and** `allow_email_notifications` (both must be true; a user with no preference row yet gets the model defaults — email allowed, thank-you email off, i.e. no email). Wired into both `verify_donation` and `apply_provider_callback` via `transaction.on_commit(...)`, guarded by an explicit status-transition check (`from_status != SUCCESSFUL and donation.status == SUCCESSFUL`) so it fires exactly once, only on the pending→successful transition — not on every call, and not on reversal/decline.
    - Both new side effects are wrapped in try/except and logged rather than raised: a failed admin notification or a failed thank-you email (e.g. Brevo down) must never roll back or fail an otherwise-successful donation write. `transaction.on_commit` (not a direct call) was used deliberately so these side effects run only after the donation's DB transaction actually commits, and never hold that transaction open during the outbound HTTP call.
    - Added `apps/donations/tests/test_notifications.py` (14 tests): preference-gating truth table for both new behaviors (opted in/out, no preference row, master-switch-off-but-specific-switch-on and vice versa), donor-exclusion when the donor is themselves an admin, failure-swallowing, and — critically — wiring tests using Django's `TestCase.captureOnCommitCallbacks(execute=True)` to prove `create_donation`/`verify_donation`/`apply_provider_callback` actually schedule these callbacks at the right transition (not just that the standalone helper functions work in isolation). Full backend suite: 163 tests (149 baseline + 14 new), same pre-existing 10 failures/10 errors in `apps.authn` (unrelated live-Brevo-in-tests issue, tracked separately), zero new regressions. `manage.py check` and `makemigrations --check` clean.

#### Push Notifications (added 2026-07-25, not yet implemented)

Additive to everything above — the existing in-app notification centre, the 30s foreground polling in `NotificationsController`, and all of Slices 1-8 stay exactly as they are. Today's delivery mechanism only reaches a user while the app process is alive; it cannot wake a backgrounded or fully-closed app, and never opens the app to anything. These slices add a second delivery channel (push, via FCM) alongside the existing in-app one, not a replacement for it.

Current state, confirmed 2026-07-25: `firebase_core` is a mobile dependency and `Firebase.initializeApp()` is called in `lib/app/bootstrap.dart`, but nothing beyond that exists — no `firebase_messaging` package, no Android `POST_NOTIFICATIONS` permission, no iOS remote-notification background mode, no push-handling code anywhere in `mobile/lib/`, and the backend has zero device-token infrastructure (no model, no registration endpoint, nothing that could call FCM's send API). Firebase's presence is almost certainly leftover from Google Sign-In setup, not prior push work.

Domain decisions (locked 2026-07-25):
- **Preference toggle**: push gets its own new preference, not a reuse of `allow_email_notifications` (which stays scoped to email only — currently just the donation thank-you email). Working name: `allow_push_notifications` on `UserNotificationPreference`, default `True` to match the model's existing default pattern for the other opt-out-style toggles. Exact field name/default to be confirmed at migration time.
- **Which notification types push**: `NEW_VIDEO_TESTIMONY`, `TESTIMONY_APPROVED`, and `TESTIMONY_COMMENT` only. `TESTIMONY_REJECTED`, `TESTIMONY_SUBMITTED`, and `DONATION_RECEIVED` stay in-app-only for now (not pushed) — revisit if that turns out to be wrong once this ships.
- **Device token model, best practice locked**:
  - One user → many `DeviceToken` rows (a user can have a phone + tablet, or reinstall and get a fresh token on the same device); never a single token field on `User`.
  - Unique by the token string itself, not by (user, device). This is what makes device reassignment safe: if User A logs out and User B logs into the same physical device, the OS hands the app the same token going forward — registering it for B just reassigns that row's `user`, so A can never keep receiving B's pushes.
  - FCM tokens rotate independently of login/logout (`onTokenRefresh` in Flutter) — every refresh must re-register with the backend, not just the initial one at login.
  - Deregister (delete) the token row on logout, so a signed-out device stops receiving pushes for that account.
  - Self-clean on send failure: when FCM's send API returns `UNREGISTERED`/`NotRegistered` for a token, delete that row immediately rather than letting dead tokens accumulate and fail every future send.
  - Batch sends via FCM's multicast API when a recipient has multiple devices, rather than one HTTP call per token.
  - The token's owner is always derived from the authenticated request (`request.user`), never accepted as a user_id in the request body.
- **Still open, deferred**: who owns the Apple Developer account / APNs key Firebase needs for iOS push — required before iOS push can work at all, independent of any code written here.

- **Slice 9 — Register a device for push notifications** — when an authenticated user opens the app (or logs in), the app obtains an FCM device token and registers it with the backend against that user's account, so the backend knows where to deliver pushes for them; token refresh and logout deregistration are part of this slice's acceptance criteria, not a follow-up
  - Implemented 2026-07-25. Backend: new `DeviceToken` model (`apps/notifications/models.py`, migration `0007_devicetoken`) and `POST`/`DELETE /notifications/devices/` (`DeviceTokenView`, `TokenAuthentication`-only — mobile-only endpoint, matching `MyNotificationListView`'s pattern). Register is `update_or_create` keyed by the token string, so re-registering a token previously owned by a different user reassigns it (the shared-device scenario locked in the domain decisions above) instead of leaving a stale cross-account row; deregister is scoped to `token + request.user`, silently a no-op for tokens you don't own (doesn't leak whether they exist) or that don't exist at all. 8 new tests in `apps/notifications/tests/test_device_tokens.py` cover auth requirement, create, idempotent re-registration, cross-user reassignment, invalid platform rejection, own-token delete, cross-user delete no-op, and unknown-token delete no-op. Full backend suite: 171 tests, same pre-existing 10/10 `apps.authn` failures, zero new regressions.
  - Mobile: added `firebase_messaging`, Android `POST_NOTIFICATIONS` permission, iOS `UIBackgroundModes: remote-notification` in `Info.plist` (entitlements/APNs key upload are separate and still blocked on the deferred Apple Developer account question — without them `getToken()` on iOS will fail, caught gracefully, no crash). Added `PushTokenSource` (`lib/core/push/push_token_source.dart`) wrapping `FirebaseMessaging` behind a testable interface, and `DeviceTokenController` (`lib/core/push/device_token_controller.dart`) that requests permission, obtains a token, registers it, and listens for `onTokenRefresh` to re-register on rotation. Wired into `AppFlowController`: `continueAsRegisteredUser()` and a successfully validated cached session both trigger registration; `signOut()` calls `deregisterCurrentDevice()` as its first statement, before the API client's auth token is cleared, so the DELETE request still goes out authenticated as the user signing out (verified: `ApiClient`'s header map is built synchronously at call time, so firing the deregister call before mutating `_authToken` is race-free even though it's not awaited). Every Firebase-touching call is wrapped in try/catch — push registration must never block or crash login/logout.
  - Not done, deferred with the rest of the domain decisions: the `allow_push_notifications` preference field itself (added in Slice 10, where it's actually consumed — registration doesn't need to check it, only sending does) and iOS push capability/entitlements.
  - Tests: `test/core/push/device_token_controller_test.dart` (6 tests, `MockClient`-backed `ApiClient` + a fake `PushTokenSource`) covering register-and-store, no-op on a null token, token-refresh re-registration, failure-swallowing, deregister-and-clear, and no-op deregister when nothing was ever registered. Added a `signOut` deregistration test to the existing `app_flow_controller_test.dart` proving the real integration path (not just the standalone controller). `flutter analyze`: clean. Full related batch (35 tests across push/notifications/giving/part6 files) run 3x for determinism: 34/35 pass every time, the one failure being the same pre-existing baseline-flaky test already documented above (`shows registered home when onboarding seen and session token exists`, confirmed via `git stash` to reproduce identically without any of this slice's changes).
  - Bug found and fixed 2026-07-25, after live testing on real devices with a working `FIREBASE_CREDENTIALS_JSON`: the backend logs showed `notifications.push.sent ... invalid_count=0` (FCM accepted the token, send succeeded) for two real trigger events, but no notification appeared on either recipient's device. Root cause: `FirebasePushTokenSource.requestPermissionIfNeeded()` (`lib/core/push/push_token_source.dart`) only called `FirebaseMessaging.requestPermission()` on iOS/macOS, on the mistaken assumption that Android needed no explicit permission request for push to work. That's true for token issuance (`getToken()` works with no permission at all), but not for *visible display*: since Android 13 (API 33), the OS requires the `POST_NOTIFICATIONS` runtime permission to actually show a notification — declaring it in the manifest (already done) is necessary but not sufficient, and `FirebaseMessaging.requestPermission()` does not trigger that Android dialog. So FCM was delivering every message successfully to the device, and the OS was silently dropping the display because the app had never asked for permission. Fixed by adding `permission_handler` (`pubspec.yaml`) and requesting `Permission.notification` on Android in the same method. No test changes needed (`FirebasePushTokenSource` is the untestable platform-channel wrapper by design; its fake in tests was unaffected). `flutter analyze` clean, all 10 push tests still pass.
  - Caveat for anyone who tested before this fix shipped: on a device where the app already ran once and the OS recorded a default/denied notification-permission state, this fix alone won't retroactively grant it — Android only shows the permission dialog once per install unless the user has never been asked. Uninstall/reinstall (or manually enable via Settings → Apps → iTestified → Notifications) is needed to get a fresh prompt on such a device.
  - Live-verified fixed 2026-07-25: user confirmed a real push notification was received and visibly displayed on a real Android device after this fix, closing out the end-to-end push path (Slices 9-11) as genuinely working, not just backend-confirmed.
- **Slice 10 — Receive a push notification while the app is backgrounded or closed** — when a `NEW_VIDEO_TESTIMONY`, `TESTIMONY_APPROVED`, or `TESTIMONY_COMMENT` event occurs (the same events already flowing through `apps/notifications/services.py`) for a recipient with `allow_push_notifications` enabled, the backend sends a push via FCM in addition to creating the existing in-app `UserNotification` record, and the OS displays it even if the app isn't running
  - Implemented 2026-07-25. Added `allow_push_notifications` to `UserNotificationPreference` (migration `0008`, default `True`) and a Firebase Admin SDK integration: `apps/common/services/push.py::send_push_to_tokens` (multicast, up to 500 tokens/call via `messaging.send_each_for_multicast`, returns tokens FCM reports `UnregisteredError` for so the caller can self-clean) + `apps/notifications/services.py::send_push_to_users` (resolves eligible recipients' tokens, respecting each user's own preference — default opted-in, matching the model default for users with no preference row yet). Wired into exactly the three approved `notify_*` functions (`notify_testimony_approved`, `notify_testimony_comment`, `notify_new_video_testimony_published`); `notify_testimony_rejected`, `notify_testimony_submitted_to_admins`, and `notify_admins_of_new_donation` deliberately do not call it.
  - The actual send is deferred via `transaction.on_commit(...)` inside `send_push_to_users` itself (not at each call site) — safe regardless of whether the caller is inside an atomic block (`notify_testimony_approved`/`notify_new_video_testimony_published` are; `notify_testimony_comment`'s caller in `api/views.py` isn't) since `on_commit` fires immediately when there's no open transaction. This means a push can never fire for a write that ends up rolling back. Provider/send failures are logged (`logger.warning`/`logger.exception`), never raised.
  - Live-verified 2026-07-25 on the deployed Render backend with a real `FIREBASE_CREDENTIALS_JSON`: a testimony comment and a testimony approval both produced `notifications.push.scheduled` → `notifications.push.sent ... invalid_count=0` in production logs, confirming the full backend pipeline (credential load, token lookup, FCM multicast call) works end-to-end. (Before this key was configured, `send_push_to_tokens` raised `PushProviderNotConfiguredError`, caught and logged as a warning, so nothing crashed — this path is still in place as the fallback for any environment without the credential set.)
  - Tests: `apps/notifications/tests/test_push_notifications.py` (13 tests) — preference gating (opted out, opted in, no preference row), on-commit deferral (proven via `captureOnCommitCallbacks` vs. a plain call with no callback capture), no-tokens no-op, stale-token self-cleaning, failure-swallowing, and confirms all three approved `notify_*` functions call the send path while the three excluded ones don't. Full backend suite: 184 tests, same pre-existing 10/10 `apps.authn` failures, zero new regressions. `manage.py check` / `makemigrations --check` clean.
- **Slice 11 — Tap a notification to open the app** — tapping a push notification (from a backgrounded app, or a cold start from fully closed) opens the app and navigates directly to the relevant screen (the notification centre, or the specific content the notification refers to) via the app's existing router
  - Implemented 2026-07-25. Added `AppRouter.navigatorKey` (attached to `MaterialApp`) so code outside the widget tree can navigate, and `lib/core/push/push_tap_handler.dart::initializePushTapHandling()`, called once from `bootstrap.dart` after `configureDependencies()`/`runApp()`. Listens to `FirebaseMessaging.onMessageOpenedApp` (tap while backgrounded) and checks `getInitialMessage()` at startup (cold start from fully closed, via a `WidgetsBinding.addPostFrameCallback` + explicit `scheduleFrame()` since a callback registered after the tree has already settled otherwise never fires) — both push `AppRouter.notifications`. `PushTokenSource` extended with `onNotificationTapped`/`getInitialNotificationTap` so this is unit-testable the same way `DeviceTokenController` is.
  - Scope: always opens the notification centre, not a per-type deep link straight to a specific testimony — the push payload sent in Slice 10 carries only title/body, no routing data. Adding that is deferred to whenever it's actually consumed, rather than speculatively built now. `NotificationsScreen` already gates on guest/registered access itself, so no separate access check was needed here. A push arriving while the app is in the foreground produces no visible in-app indicator today (`FirebaseMessaging.onMessage` isn't handled) — out of scope for this slice, callable out as a gap if it matters later; the existing 30s poll eventually surfaces it once the user opens the notification centre.
  - Tests: `test/core/push/push_tap_handler_test.dart` (4 tests) covering backgrounded tap, cold-start tap, no-tap no-op, and no-op when `PushTokenSource` isn't registered. Broad regression batch (39 tests across push/notifications/giving/part6/widget_test files) run multiple times: consistently only the same two pre-existing baseline-flaky tests fail (`shows registered home when onboarding seen and session token exists`, `moves from onboarding into guest discovery` — both confirmed via `git stash` to reproduce identically with this slice's changes fully reverted; both are live-network-dependent, unrelated). `flutter analyze`: clean.
- **Slice 12 — Turn push notifications off** — a user can flip `allow_push_notifications` off/on from a real settings toggle, on both surfaces that expose `UserNotificationPreference` (dashboard and mobile), instead of the field being backend-only
  - Implemented 2026-07-25. Backend already fully supported this (`MyNotificationPreferencesView` GET/PATCH + `UserNotificationPreferenceSerializer` already included `allow_push_notifications` since Slice 10) — this slice is UI-only, closing the gap on both existing surfaces.
  - Dashboard: added a 4th toggle ("Allow Push Notifications") to `notification-settings-page.tsx` / `get-notification-settings-view-model.ts` / `api/admin/notifications/preferences/route.ts`. While adding it, replaced the existing position-based `index === 0 ? ... : index === 1 ? ...` toggle-to-field-name mapping (fragile — silently mismatches if the preferences array is ever reordered) with an explicit `name` field on `NotificationPreference`, used directly for both the checkbox's `name` attribute and the response-hydration lookup (`payload[preference.name]`).
  - Mobile: the existing `NotificationSettingsScreen` ("Profile → Notifications") had a toggle already, but it was **entirely disconnected from the backend** — `ProfileAccountController.notificationsEnabled`/`setNotificationsEnabled` was pure local state, always reset to `true` on every app start, never read or written anywhere over the network. Its copy ("Activity on my Posts... likes, comments, and shares") also didn't match anything the app actually does (no likes feature). Replaced with a new `NotificationPreferencesController` (`lib/features/profile/presentation/state/notification_preferences_controller.dart`) that GETs the real preference on load and PATCHes `allow_push_notifications` on toggle, optimistically updating the switch and reverting it if the PATCH fails. Added `Endpoints.notificationPreferences` and `ApiClient.patchJson` (mirroring the existing `postJson`/`getJson`/`deleteJson` shape) to support it. Removed the dead `notificationsEnabled`/`setNotificationsEnabled` fields from `ProfileAccountController` entirely (no other caller). Copy corrected to describe what push actually covers (testimony approved/commented/new video).
  - Tests: `test/features/profile/notification_preferences_controller_test.dart` (4 tests: loads from backend, keeps default on load failure, optimistic update + PATCH, reverts on PATCH failure) and `test/features/profile/notification_settings_screen_test.dart` (2 widget tests: reflects loaded backend value, tapping persists and updates UI). Dashboard: extended the existing `settings-pages.test.tsx` assertion from 3 switches to 4. `flutter analyze` and dashboard `tsc --noEmit` both clean.

Access-control contract for these slices:
- guests/unauthenticated users never receive push (no account to register a token against)
- a device token must be removed/invalidated on logout, so a signed-out device stops receiving another user's pushes

Test:
- tests for notification creation and read-state transitions
- API tests for list, mark-read, and admin history access
- replace notification mocks in the connected UI scope
- verify notification list/read behavior in `mobile/` and notification-history behavior in `dashboard/frontend/`
- Reviewed 2026-07-24: pre-existing mobile tests were shallow — only "does the route resolve to the right widget" checks, nothing exercising pagination, the actual HTTP calls for mark-read/mark-all-read, or guest-denial behavior (same pattern flagged for gift-history in Phase 5).
- Closed 2026-07-24 (partial): added `notifications_pagination_test.dart` (controller-level, `MockClient`-backed — asserts `refresh()`/`loadMore()` request the right pages and stop at the last one) and `notifications_guest_gate_test.dart` (widget-level — asserts the guest prompt renders instead of the notification list/controls).
- Note: the full `test/features/browse/` directory has pre-existing flakiness unrelated to this pass — several tests (`category_flow_test.dart`, two cases in `discovery_routes_test.dart`) call the live deployed backend (`itestified-backend.onrender.com`) with no mocking and fail/timeout depending on network conditions. Confirmed via `git stash` that these reproduce identically with this pass's changes fully reverted — not a regression introduced here.
- Closed 2026-07-24 (later pass): added `notifications_controller_test.dart`'s write-failure test and `notifications_write_failure_test.dart` (widget-level), closing the mark-read/mark-all-read HTTP-call and swallowed-error test gaps noted above. While doing so, found and fixed two more issues:
  - The Slice 4/access-control fix in the previous pass had silently broken the pre-existing `notifications_screen_actions_test.dart` when run in true isolation — it never overrode `appFlowProvider`, so `NotificationsScreen`'s new guest check picked up `AppFlowController`'s real default (guest, absent a cached session) and rendered the guest prompt instead of the list. It only "passed" before because it happened to always be run in a batch alongside another file that left ambient state as registered. Fixed by explicitly overriding `appFlowProvider` to `registered` and calling `configureDependencies`, matching the pattern used in the newer notification test files, so it's no longer order-dependent.
  - `notifications_screen_actions_test.dart`'s search assertion checked for `NotificationItem.subtitle` text (`"Building on what you said about resilience..."`) as a rendered widget — but `NotificationTile` never renders `subtitle` at all (it's search-index-only, combined into the haystack with `senderName`/`message`). The assertion could never have genuinely passed. Fixed to assert on the sender name that's actually visible on the surviving tile.
  - All five notification test files now pass individually in true isolation (`flutter test <single-file>`, not just batched), confirmed with repeated runs.

Status: Completed. All 12 slices (in-app notifications, mobile flows, admin flows, preference-driven donation notifications, the full push-notification path — device registration, sending, and tap-to-open — and a real push on/off toggle on both surfaces) are implemented and tested as of 2026-07-25 — see each slice's notes above for what was reviewed/fixed/built across the several passes in this phase, including a live-production diagnosis (Android `POST_NOTIFICATIONS` runtime permission was never requested, so FCM delivered successfully but the OS suppressed display — see Slice 9) and confirmed end-to-end on the deployed backend and a real device (Slice 10). Two things remain open, tracked separately, neither blocking this phase's completion since both are external-dependency gaps rather than missing code: (1) iOS push needs the Apple Developer account / APNs key question resolved (Slice 9) — Android is now confirmed working end-to-end, iOS `getToken()` still fails gracefully with no crash until that's resolved. (2) dead SMTP/Resend email-provider settings should be removed now that Brevo is confirmed as the sole live provider (`backend/.env` cleanup, to be discussed separately), and `config/settings/test.py` doesn't force a safe `EMAIL_PROVIDER` for tests, so `apps.authn`'s test suite unintentionally live-calls the real Brevo API and gets a 401 (10 pre-existing failures/errors, confirmed unrelated to this phase's changes) — worth a dedicated fix in a Phase 2/authn pass.

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

Naming note: this phase has two distinct entities both called "review" —
keep them separate, do not merge:
- the **testimony peer review** (Slices 1-2 below): an admin-authored
  quality note (rating + text) attached to one specific testimony, visible
  to other admins on that testimony's detail view.
- the **submitted review** (Slices 2a-2b below): the standalone `Review`
  entity from `PHASE0_DOMAIN_DISCOVERY.md` (`name`, `email`, `rating`,
  `review text`, `created_at` — no testimony reference at all). This is
  what `dashboard/frontend/src/features/admin/domain/entities/reviews.ts`
  and the `/reviews` admin page are already built against (see
  `dashboard/frontend/UI_UX_REVIEW_TODO.md` B6, now folded into this plan).

#### Admin Flows

- **Slice 1 — Review a testimony** — admin reads a testimony and leaves a rating (1–5) and written notes as an internal review record; each admin can review a given testimony only once but can update their own review
- **Slice 2 — View all reviews for a testimony** — admin opens a testimony detail and sees the list of all internal reviews left by other admins with ratings and notes
- **Slice 2a — View submitted reviews** — admin opens the reviews screen and sees a paginated list of submitted reviews (name, email, rating 1–5, review text, submission date); can search by name/email and filter by rating and date range
- **Slice 2b — Delete a submitted review** — admin removes a single submitted review, or bulk-deletes multiple selected reviews
- **Slice 3 — Deactivate an admin** — super admin deactivates an existing admin account; the deactivated user is immediately blocked from logging in and their session is revoked
- **Slice 4 — Reactivate an admin** — super admin reactivates a previously deactivated admin account so they can log in again
- **Slice 5 — View the admin list** — super admin views all admin accounts with their roles and current status (invited, active, deactivated), filterable by role
- **Slice 6 — View analytics overview** — admin opens the dashboard home and sees key metrics: total registered users, total testimonies, count pending moderation, and total donation amounts by currency
- **Slice 7 — View testimony analytics** — admin opens the testimony analytics screen, selects a time period (7, 30, or 90 days), and sees a breakdown of testimonies by status and by category for that period
- **Slice 8 — View donation analytics** — admin opens the donations analytics screen, selects a time period, and sees total donation amounts grouped by status and currency, including the period-over-period percentage change (trend) needed by the dashboard's donations hero card
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
