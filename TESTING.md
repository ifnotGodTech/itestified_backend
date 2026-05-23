# Manual Testing Guide (User/Admin Flows by Phase)

This guide follows the phase structure in `backend/IMPLEMENTATION_PLAN.md`.
It is written for manual testing by a normal user, admin, QA tester, or product stakeholder.

## How to use this guide

- Run flows in phase order.
- For phases marked **Completed**, execute all flows now.
- For phases marked **Not started**, treat flows as acceptance criteria for when implementation begins.
- For every flow, validate:
  - happy path (works as expected)
  - failure path (invalid input or unauthorized access is handled safely)

## Layperson Test Pattern (Use This For Every Flow)

Use this format for each test step:

1. `Action`: what to click/type.
2. `Expected Result`: what you should see if it works.
3. `If It Fails`: what to record (screen name, error text, time, user type: guest/auth/admin).

Example:

1. `Action`: Open app as guest and tap a testimony.
2. `Expected Result`: Testimony detail opens and content loads from backend.
3. `If It Fails`: Note exact message (for example `PlatformException`), testimony title, and whether API logs show `4xx` or `5xx`.

## Quick Smoke Checklist (Non-Technical)

Run these first before full phase testing:

1. Guest can open home and see content cards (not blank, not mock-only).
2. Guest can open testimony detail and comments list.
3. Guest gets login prompt for protected actions (like, comment, submit).
4. Authenticated user can log in and open profile data.
5. Authenticated user can like/unlike and icon state updates immediately.
6. Authenticated user can add a comment and it appears immediately in comment sheet.
7. Video testimony opens and plays without platform error.
8. Admin can log in and open at least one protected admin page.

---

## Phase Status Snapshot (from Implementation Plan)

- Phase 0: Completed
- Phase 1: Completed
- Phase 2: Completed
- Phase 3: Completed
- Phase 4: In progress (Slices 1-9 implemented)
- Phase 5: In progress (Slices 1-7 implemented)
- Phase 6: In progress (Slices 1-7 implemented)
- Phase 7: In progress (Slices 1-8 implemented)
- Phase 8: Not started
- Phase 9: Not started

---

## Guest vs Authenticated Access Matrix (Mobile + API)

Use this as the first-pass check before running phase-by-phase flows.

### Guest user (unauthenticated)

- Allowed:
  - Browse testimonies, categories, search, and detail pages.
  - Read inspirational/scripture/public content.
- Blocked (must prompt login/signup in mobile; must return auth error in API):
  - Submit testimony.
  - Favorite/unfavorite testimony.
  - Create/delete comments.
  - Access `profile/me`.
  - Create donation or view donation history/detail.
  - Access notification inbox, mark-read actions, and preferences update.

### Authenticated user

- Allowed:
  - All guest read capabilities.
  - Submit testimony and interact (favorites/comments).
  - Access own profile data.
  - Create/view own donations only.
  - Access and manage own notifications only.
- Blocked:
  - Any admin-only endpoint.
  - Other users' private resources (for example, another user's donation detail).

### Admin users (role-scoped)

- Allowed:
  - Role-appropriate dashboard APIs (moderation, finance, user admin, notification history).
- Blocked:
  - Admin APIs outside assigned role scope.
  - Any action not covered by role + policy.

Pass criteria:
- Mobile no longer relies on mock responses for completed slices.
- Guest/auth/admin behavior matches this matrix in both UI and API responses.

---

## Phase 0 — Domain Discovery and Contract Lock
Status: Completed

This phase is documentation and decision quality, not UI behavior.

### Flow P0-1 — Product/domain alignment review
Goal: confirm backend language and boundaries match product reality.

Checks:
- Domain terms are consistent across mobile and admin experiences.
- Shared concepts (users, testimonies, moderation, donations, notifications) are defined once.
- No backend decisions are copied blindly from temporary UI mock data.

Pass criteria:
- Team can explain core entities and lifecycle states without contradiction.

---

## Phase 1 — Project Bootstrap and Infrastructure
Status: Completed

### Flow P1-1 — System health is visible
Goal: environment is up and health status is inspectable.

Steps:
1. Start the backend environment.
2. Open the health endpoint via browser or API client.

Expected result:
- Service responds.
- Database health is reported.
- Team can quickly tell if system is healthy/degraded.

### Flow P1-2 — Basic operational safety
Goal: baseline configuration is suitable for continued feature work.

Checks:
- App starts with local settings.
- Logging is visible.
- Auth framework and app modules load without startup errors.

Pass criteria:
- Team can run and debug the backend reliably in local/dev workflow.

---

## Phase 2 — Identity, Auth, and Admin Access
Status: Completed

Cross-flow policy for mobile in this phase:
- Onboarding is first-run only.
- Returning users with valid session go straight to authenticated home.
- Returning users without a valid session can still continue in guest mode (restricted), and must authenticate for protected actions.

## Mobile User Flows

### Flow P2-M0 — Guest access remains available but limited
Goal: unauthenticated users can still use allowed parts of the app.

Steps:
1. Open app as a new/unauthenticated user and continue without logging in.
2. Navigate guest-allowed surfaces (for example discover/browse).
3. Attempt protected actions (for example save favorites, reply/comment, unlimited video behavior where restricted).

Expected result:
- Guest can continue in the app and access allowed content.
- Protected actions prompt for Create Account / Log In instead of silently failing.

### Flow P2-M1 — Create a new account
Goal: a new person can sign up and enter the app.

Steps:
1. Open app and choose `Create account`.
2. Enter name and email.
3. Check your email inbox for the verification code (also check spam/junk).
4. Enter code.
5. Set password and complete signup.

Expected result:
- Signup succeeds.
- User can access authenticated area.

Failure checks:
- Existing email cannot be re-registered.
- Wrong code is rejected.
- Completing signup without verification is blocked.

### Flow P2-M2 — Log in and access own profile
Goal: returning user can authenticate and access personal details.

Steps:
1. Open `Log in`.
2. Enter valid email/password.
3. Navigate to profile/account screen.

Expected result:
- Login succeeds.
- Profile shows correct user identity data.

Failure checks:
- Wrong password fails with clear message.
- Protected profile area is blocked when logged out.

### Flow P2-M3 — Sign in with Google
Goal: user can authenticate with Google and enter authenticated app state.

Steps:
1. On mobile login screen, tap `Continue with Google`.
2. Complete Google account selection/consent.
3. Return to app and open profile/account screen.

Expected result:
- Google sign-in succeeds.
- App receives normal authenticated session/token from backend.
- Profile shows correct user identity data.

Failure checks:
- Invalid Google token is rejected safely.
- Expired token is rejected and user remains logged out.
- Token for wrong audience/client-id is rejected.

### Flow P2-M4 — Reset forgotten password
Goal: user can recover account safely.

Steps:
1. Choose `Forgot password`.
2. Enter email.
3. Check your email inbox for the reset code (also check spam/junk), then submit it.
4. Set new password.
5. Try old password (should fail), then new password (should work).

Expected result:
- Password reset succeeds.
- Old credentials no longer work.

Failure checks:
- Wrong reset code is rejected.
- Unregistered email does not reveal account existence.

## Admin User Flows

### Flow P2-A1 — Super admin bootstrap (operator-run)
Goal: operator can provision the first super admin without shared public entry code.

Steps:
1. Run the bootstrap command with super admin email.
2. Capture the temporary password output.
3. Log in with the generated credentials.

Expected result:
- Super admin account exists with active assignment.
- Login succeeds using generated credentials.

Failure checks:
- Non-bootstrap paths cannot create super admin arbitrarily.
- Bootstrap output is required to complete first login.

### Flow P2-A2 — Super admin login/session/logout
Goal: admin session lifecycle works end-to-end.

Steps:
1. Log in as admin.
2. Open protected admin pages.
3. Refresh and confirm session persists.
4. Log out.
5. Retry protected page.

Expected result:
- Logged-in admin can access protected areas.
- Logged-out admin is blocked and returned to login/unauthorized state.

Failure checks:
- Wrong password fails.
- Unauthenticated access to admin-protected pages is blocked.

### Flow P2-A3 — Super admin invites admin by role
Goal: active super admin can invite another admin using email + role.

Steps:
1. Log in as super admin.
2. Submit invite request with target email and role code.
3. Check invitee inbox for invite code (or otp hint in non-production test envs).

Expected result:
- Invite request succeeds.
- Invite challenge is generated as single-use and time-limited.
- Target assignment is created/refreshed in `invited` status.

Failure checks:
- Non-super-admin cannot invite.
- Invalid role code is rejected.

### Flow P2-A4 — Invite acceptance activates assignment
Goal: invited admin can verify code, set password, and start authenticated session.

Steps:
1. Submit invite email + invite code.
2. Set password in invite-complete step.
3. Call/get admin session.

Expected result:
- Invite verify succeeds for valid code.
- Invite complete activates assignment (`invited` -> `active`).
- Admin session is established.

Failure checks:
- Expired/wrong invite code is rejected.
- Completing invite without verify is blocked.

### Flow P2-A5 — Admin forgot/reset password
Goal: admin can recover account safely.

Steps:
1. Submit forgot-password request with email.
2. Verify reset code.
3. Set new password.
4. Confirm old password fails and new password succeeds.

Expected result:
- Reset flow succeeds.
- Existing sessions are revoked after reset.

Failure checks:
- Wrong reset code is rejected.
- Unknown email does not leak account existence.

---

## Phase 3 — Testimonies Core Domain

### QA Seed For Phase 3

Run this before manual QA to create reusable Phase 3 data:

- `./.venv/bin/python backend/manage.py seed_phase3_testimonies`

Seeded QA users:

- `qa.author1@example.com` / `TestPass#123`
- `qa.author2@example.com` / `TestPass#123`
- `qa.viewer@example.com` / `TestPass#123`
Status: In progress (Slices 1-10 implemented)

Current verification scope:
- Implemented now: `Flow P3-M1` through `Flow P3-M5` (including favorites list parity and comment add/delete)
- Pending in later slices: `Flow P3-A1`, `Flow P3-A2`, `Flow P3-A3`

## Mobile User Flows

### Flow P3-M1 — Browse approved testimonies
Goal: user can discover published testimonies.

Expected behavior:
- List is visible and paginated.
- Search/filter works (for fields that product supports).
- Only approved/published testimonies appear in public browse.

### Flow P3-M2 — View testimony details
Goal: user can open one testimony and consume full content.

Expected behavior:
- Detail page opens with title/content/media/author context.
- Engagement counters or metadata render correctly (if part of design).

### Flow P3-M3 — Submit testimony (written)
Goal: user can create testimony submission.

Expected behavior:
- Written submission form accepts valid input.
- Submitted testimony enters moderation state (for example pending review).

Failure checks:
- Invalid/missing fields are clearly rejected.
- Guest/unauthenticated submission is blocked if auth is required.

### Flow P3-M4 — Track own submissions
Goal: user can see status of own testimonies.

Expected behavior:
- User can view own submissions with status labels.
- Rejected items show actionable feedback/reason when available.

### Flow P3-M5 — Favorites and comments
Goal: user can engage with testimonies.

Expected behavior:
- User can favorite/unfavorite.
- User can add comments and remove own comments.
- User cannot delete another user's comment.

## Admin Flows

### Flow P3-A1 — Manage testimony categories
Goal: admin can create/update/deactivate categories.

Expected behavior:
- Category changes reflect in user-facing submission/browse where applicable.
- Non-admin users cannot access admin category controls.

### Flow P3-A2 — View testimonies across statuses
Goal: admin can list and filter testimonies for operations.

Expected behavior:
- Admin can view all relevant statuses.
- Filters (status/category/date if provided) work correctly.

### Flow P3-A3 — Upload video testimony (admin-only)
Goal: admin can create video testimony records for review/publishing.

Expected behavior:
- Admin upload/create form accepts valid video testimony payload.
- Admin can choose upload status at creation time: `upload_now`, `schedule_for_later`, or `draft`.
- Created record appears in admin list with expected status matching selected upload status.
- Dashboard supports both `Single Video Upload` and `Multiple Video Upload` modes, with add-new-video action in multiple mode.
- In multiple mode, each additional video card can be removed by its cancel/remove icon before submission.
- Video renders/playbacks in admin detail using stored source.

Sub-flow checks:
- `Flow P3-A3.1` Upload mode: switching between single and multiple updates the upload composer correctly.
- `Flow P3-A3.2` Multi-video controls: `Add new video` creates another card; remove icon removes only the selected card.
- `Flow P3-A3.3` Per-card validation: each card enforces required fields (`title`, `category`, `video file`).
- `Flow P3-A3.4` Status mapping: `upload_now`, `schedule_for_later`, and `draft` each create records with correct lifecycle status.
- `Flow P3-A3.5` Schedule validation: schedule date/time required and validated when `schedule_for_later` is selected.
- `Flow P3-A3.6` Cloud media persistence: created records store Cloudinary-backed video URL (and thumbnail URL when provided).
- `Flow P3-A3.7` Authorization: admin-only endpoint enforcement blocks non-admin requests.

Failure checks:
- Invalid video input is rejected with clear validation.
- Invalid schedule payload is rejected when `schedule_for_later` is selected.
- Non-admin users cannot access this flow.

---

## Phase 4 — Moderation and Review Workflows
Status: In progress (Slices 1-9 implemented)

## Admin Flows

### Flow P4-A1 — Review moderation queue
Goal: admin can process pending testimonies in a clear queue.

Expected behavior:
- Pending queue is visible.
- Queue ordering is predictable.

### Flow P4-A2 — Approve testimony
Goal: admin approval publishes testimony appropriately.

Expected behavior:
- Status changes to approved.
- Approved testimony becomes visible in user browse.

### Flow P4-A3 — Reject testimony with reason
Goal: admin rejection is explicit and traceable.

Expected behavior:
- Rejection requires/records reason (as designed).
- Rejected testimony is hidden from public browse.
- Owner sees updated status and reason where applicable.

### Flow P4-A4 — Schedule and archive
Goal: admin can time publication and retire content.

Expected behavior:
- Scheduled items remain hidden until publish time.
- Archived items are removed from active user browse.

### Flow P4-A5 — Moderation history/audit trail
Goal: moderation actions are auditable.

Expected behavior:
- History shows who did what and when.
- Status transitions are coherent (no illegal jumps).

## Mobile User Flow

### Flow P4-M1 — Real-time moderation outcomes reflected
Goal: users see up-to-date status/results of moderation actions.

Expected behavior:
- Own submission statuses update accurately.
- Newly approved items appear in browse without manual data fixes.

---

## Phase 5 — Donations and Giving
Status: In progress (Slices 1-7 implemented)

## Mobile User Flows

### Flow P5-M1 — Make a donation
Goal: user can complete giving flow.

Expected behavior:
- User can enter donation details and initiate payment.
- Donation record enters expected lifecycle state.
- Amount convention is consistent: `amount` is interpreted and persisted in minor units (`kobo`/`cents`).

Failure checks:
- Invalid amounts are rejected.
- Unauthorized users cannot submit protected donation actions.

### Flow P5-M2 — View giving history and details
Goal: user can review own donations.

Expected behavior:
- User sees only their own donation history.
- Donation detail shows amount, status, date, and reference info.

## Admin Flows

### Flow P5-A1 — Review all donations
Goal: admin can monitor donation activity globally.

Expected behavior:
- Admin list supports operational filters (status/date/etc as designed).
- Admin can open full details per donation.

### Flow P5-A2 — Donation reversal/refund operations
Goal: admin can perform corrective financial actions safely.

Expected behavior:
- Reversal/refund actions require clear intent.
- Resulting status transitions are correct and auditable.

---

## Phase 6 — Notifications and Engagement
Status: In progress (Slices 1-7 implemented)

## Mobile User Flows

### Flow P6-M1 — Receive in-app notifications
Goal: users are informed about relevant events.

Expected behavior:
- Notification appears for triggered events.
- Read/unread state behaves consistently.

### Flow P6-M2 — Manage notification inbox
Goal: user can inspect and maintain notification history.

Expected behavior:
- List notifications.
- Open details.
- Mark read/clear/delete based on product rules.

## Admin/Operations Flow

### Flow P6-A1 — Trigger/administer notifications
Goal: operational users can send or trigger notifications as designed.

Expected behavior:
- Intended audience receives notification.
- Unauthorized users cannot trigger admin-only notification actions.

---

## Phase 7 — Content Operations
Status: In progress (Slices 1-8 implemented)

## Admin Flows

### Flow P7-A1 — Manage inspirational pictures
Goal: admin can create/edit/schedule/publish picture content.

Expected behavior:
- Content lifecycle states behave correctly.
- Published content appears on mobile surfaces where expected.

### Flow P7-A2 — Manage scripture of the day
Goal: admin can curate scripture content.

Expected behavior:
- Scripture entries can be created/updated/scheduled.
- Correct item appears based on schedule/state.

### Flow P7-A3 — Home page curation
Goal: admin can control featured/curated content on home surfaces.

Expected behavior:
- Curation changes are reflected on mobile/dashboard consuming surfaces.

## Mobile User Flow

### Flow P7-M1 — Consume published content
Goal: user sees current published inspirational/scripture/home content.

Expected behavior:
- Only published/currently active items are visible.
- Content freshness aligns with admin scheduling rules.

---

## Phase 8 — Admin Management and Settings
Status: Not started

## Admin Flows

### Flow P8-A1 — Admin identity and settings management
Goal: admin can manage own profile and credentials safely.

Expected behavior:
- Profile updates persist correctly.
- Password updates require valid current flow and remain secure.

### Flow P8-A2 — Admin account lifecycle management
Goal: privileged admins can deactivate/reactivate and manage existing admin lifecycle state.

Expected behavior:
- Lifecycle actions are role-gated.
- Deactivated admins lose protected access.
- Reactivated admins regain access appropriately.

### Flow P8-A3 — Permission boundary enforcement
Goal: role model is correctly enforced.

Expected behavior:
- Non-super-admin roles cannot perform restricted actions.
- Permission errors are explicit and safe.

---

## Phase 9 — Analytics and Reporting
Status: Not started

## Admin Flows

### Flow P9-A1 — View analytics dashboards
Goal: admin can see high-level platform insights.

Expected behavior:
- Core metrics load reliably.
- Values are internally consistent.

### Flow P9-A2 — Filter and slice reports
Goal: admin can analyze trends using supported filters.

Expected behavior:
- Date/status/category filters produce expected changes.
- Empty states are handled clearly.

### Flow P9-A3 — Validate reporting correctness
Goal: reports are trustworthy for operational decisions.

Expected behavior:
- Sampled report values reconcile with source records.
- Any export/report output matches on-screen data definitions.

---

## Ongoing Maintenance Rule

Whenever a phase moves from Not started to implementation:
1. Keep these plain-language flows as acceptance criteria.
2. Add concrete execution notes for QA (screens, test accounts, environment assumptions).
3. Add known edge cases discovered during implementation.
4. Mark each flow as Pass/Fail during test cycles.
