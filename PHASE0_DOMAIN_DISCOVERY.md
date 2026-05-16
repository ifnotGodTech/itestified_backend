# Phase 0 Domain Discovery

This document is the Phase 0 contract baseline for the `iTestified` backend.

It is derived from:
- `backend/AGENTS.md`
- `backend/IMPLEMENTATION_PLAN.md`
- the current Flutter mobile app in `mobile/`
- the current Next.js dashboard in `dashboard/frontend/`

Its purpose is to lock the first-pass backend domain language before schema work begins.

Status:
- approved baseline

## Current Product Reality

The repository currently contains two mock-driven clients:

- `mobile/`
  - consumer-facing app for onboarding, auth, browsing testimonies, testimony detail, favorites, testimony submission, moderation status views, notifications, giving, and profile/settings
- `dashboard/frontend/`
  - admin-facing app for overview, testimonies, moderation-adjacent actions, inspirational pictures, scripture of the day, users, donations, notification history, reviews, analytics, profile/settings, and admin management

The backend must unify these into one canonical business model.

The backend must not copy either client's mock structures directly.

## Canonical Domain Vocabulary

Use the following vocabulary as the first-pass backend language:

- `User`
  - a persisted consumer identity for the mobile app and any authenticated end-user actions
- `Profile`
  - user-owned account and presentation data
- `AdminUser`
  - an authenticated staff/admin actor with explicit role assignments and audit visibility
- `AdminRole`
  - a named admin permission bundle
- `Testimony`
  - the canonical testimony aggregate
- `TestimonyMedia`
  - media attached to a testimony, such as video or thumbnail assets
- `TestimonyCategory`
  - a controlled category used for filtering, submission, analytics, and moderation
- `ModerationDecision`
  - an explicit admin action on a testimony, including outcome, actor, reason, and time
- `Comment`
  - a user-authored response on a testimony
- `Favorite`
  - a user-to-content saved relationship
- `Donation`
  - a giving record tied to a donor identity and payment status
- `Notification`
  - a user-facing or admin-facing delivered notification record
- `InspirationalPicture`
  - a managed visual content item for mobile consumption and admin publishing
- `ScriptureEntry`
  - a managed scripture-of-the-day content item
- `HomeCurationSlot`
  - a rule or placement record that determines what content appears on the home surface
- `Review`
  - user-submitted rating/review content if retained as a backend-owned feature
- `AnalyticsSnapshot`
  - derived read-oriented reporting output, never the source of truth

## Approved Core Decisions

### 1. Identity model

Use one shared base identity model for authenticated people, with explicit separation between consumer roles and admin roles.

Approved direction:
- one Django `AUTH_USER_MODEL`
- consumer capabilities expressed through user/profile state
- admin access expressed through explicit admin role assignments, not a completely separate auth system
- guest is not a persisted account type
- mobile auth should use token-based API authentication
- dashboard admin auth should use session-based authentication

Reason:
- both clients need identity, audit, and permissions
- one base identity model simplifies account recovery, audit references, and cross-domain ownership
- admin privileges still remain explicit through role assignment and permissions

### 2. Testimony model

Use one canonical `Testimony` aggregate, not separate root entities for text and video testimonies.

Approved direction:
- one `Testimony` model
- testimony type field such as `text` or `video`
- related media table for video file, thumbnail, or future attachments
- moderation status and publication status kept explicit on the aggregate
- comments and favorites belong in the first testimony slice

Reason:
- both clients treat testimonies as one business concept even though their screens differ
- a single aggregate avoids duplicate analytics, favorites, comments, and moderation logic
- text and video differences can be handled by subtype fields and validators

### 3. Notification model

Use one notification system with audience/type fields, not two unrelated implementations.

Approved direction:
- one `Notification` record model
- audience field such as `user` or `admin`
- event type field such as `comment`, `like`, `testimony_approved`, `donation_received`
- read state tracked per delivered record

Reason:
- mobile notifications and dashboard notification history describe different views over related operational events
- a shared model keeps delivery and audit logic coherent

### 4. Donations model

Treat guest giving as first-class from day one.

Approved direction:
- `Donation` may reference a `User` when authenticated
- `Donation` may also store donor name/email when user-linked identity is absent
- payment provider integration remains behind a clear gateway boundary

Reason:
- mobile giving flow already collects donor identity without requiring login
- dashboard expects donation review and operational traceability

## Canonical Lifecycle States

These are the approved first-pass states to lock before implementation.

### User lifecycle

- `active`
- `deactivated`
- `deleted`

Notes:
- deleted should likely be soft-delete oriented at the account level
- deactivation and deletion should preserve audit context and reason fields

### Admin assignment lifecycle

- `invited`
- `active`
- `deactivated`

### Testimony publication lifecycle

Approved first-pass fields:
- `type`
  - `text`
  - `video`
- `submission_source`
  - `mobile_user`
  - `admin_upload`
  - extensible for future imports
- `moderation_status`
  - `pending`
  - `approved`
  - `rejected`
- `publication_status`
  - `draft`
  - `published`
  - `scheduled`
  - `archived`

Reason:
- mobile currently needs `pending`, `approved`, `rejected`
- dashboard already implies `draft`, `scheduled`, and uploaded/published behavior for admin-managed content
- separating moderation from publication avoids mixing approval state with release state

### Donation lifecycle

- `pending`
- `successful`
- `declined`
- `reversed`
- `refunded`

### Notification lifecycle

- `unread`
- `read`
- optional future archive/delete behavior should not be required in the first schema unless a client depends on it

### Content lifecycle

For `InspirationalPicture` and `ScriptureEntry`:
- `draft`
- `scheduled`
- `published`
- `archived`

## First-Pass Entity Map

### Identity and access

- `User`
  - fields:
    - id
    - email
    - password hash / auth credentials
    - is_active
    - account_status
    - created_at
    - updated_at
- `Profile`
  - belongs to `User`
  - fields:
    - full_name
    - avatar
    - phone_number
    - display preferences as needed
- `AdminRole`
  - fields:
    - name
    - code
    - description
- `AdminAssignment`
  - links `User` to `AdminRole`
  - fields:
    - status
    - invited_by
    - activated_at
    - deactivated_at

### Testimonies

- `TestimonyCategory`
- `Testimony`
  - belongs to submitting `User` when user-originated
  - may reference publishing `AdminUser` when admin-originated
  - fields:
    - title
    - body / narrative
    - type
    - category
    - moderation_status
    - publication_status
    - submission_source
    - published_at
    - scheduled_for
    - approved_by
    - rejected_by
    - rejection_reason
    - created_at
    - updated_at
- `TestimonyMedia`
  - belongs to `Testimony`
  - fields:
    - media_type
    - storage_key
    - external_url if needed
    - thumbnail_key
- `ModerationDecision`
  - belongs to `Testimony`
  - fields:
    - action
    - actor
    - reason
    - created_at

### Engagement

- `Comment`
  - belongs to `Testimony`
  - belongs to author `User`
  - optional parent comment for replies
- `Favorite`
  - belongs to `User`
  - references favorited content

### Donations

- `Donation`
  - optional `User`
  - fields:
    - donor_name
    - donor_email
    - amount
    - currency
    - status
    - provider
    - provider_reference
    - payment_method_summary
    - created_at
    - updated_at

### Notifications

- `Notification`
  - optional recipient `User`
  - optional recipient admin audience marker
  - fields:
    - audience_type
    - event_type
    - title
    - message
    - status
    - related object references where useful
    - created_at
    - read_at

### Managed content

- `InspirationalPicture`
  - fields:
    - title
    - image asset reference
    - caption
    - category
    - source
    - publication_status
    - scheduled_for
- `ScriptureEntry`
  - fields:
    - scripture_reference
    - scripture_text
    - prayer_text
    - bible_version
    - publication_status
    - scheduled_for
- `HomeCurationSlot`
  - fields:
    - surface
    - content_type
    - rule_type
    - sort_order
    - target object reference
    - active window

### Secondary domains

- `Review`
  - name
  - email
  - rating
  - review text
  - created_at

## Cross-Client Mappings

### Mobile app expectations

The backend should directly support:
- auth and account flows
- testimony browse/detail
- testimony submission
- moderation status visibility for a user's own submissions
- user notifications
- favorites
- giving and donation history
- inspirational pictures
- scripture/home content reads

### Dashboard expectations

The backend should directly support:
- admin auth and protected access
- testimony review, publishing, scheduling, and management
- donation operations and filtering
- user management and account status changes
- admin management and role assignment
- notifications history
- inspirational picture management
- scripture scheduling and management
- home page curation
- reviews
- analytics read models

## Places Where The Clients Differ Today

These differences must be normalized by the backend instead of copied.

### Testimony status language

Mobile currently assumes:
- `pending`
- `approved`
- `rejected`

Dashboard currently assumes:
- text testimonies:
  - `Pending`
  - `Approved`
  - `Rejected`
- video testimonies:
  - `Uploaded`
  - `Scheduled`
  - `Drafts`

Normalization:
- use canonical moderation status plus canonical publication status
- let each client map backend fields into its own UX wording

### Auth shape

Mobile currently assumes consumer auth flows.
Dashboard currently assumes admin-only auth.

Normalization:
- shared identity base
- explicit admin authorization layer
- separate client-facing auth endpoints or flows where necessary

### Notifications

Mobile notifications are personal activity notifications.
Dashboard notifications are operational/admin history entries.

Normalization:
- one notification domain
- multiple audience types and read models

### Donations

Mobile is giver-facing.
Dashboard is operations-facing.

Normalization:
- one donation source-of-truth record
- separate query models for donor history and admin review

## First-Pass API Surface

Recommended endpoint families:

- `/api/v1/auth/`
  - consumer registration/login/reset
  - admin login/logout/session checks
- `/api/v1/users/`
  - admin-managed user listing/status changes
- `/api/v1/profile/`
  - current user profile and settings
- `/api/v1/testimonies/`
  - browse, detail, create, update-own, and list-own submissions
- `/api/v1/moderation/`
  - admin review actions and moderation queues
- `/api/v1/categories/`
  - testimony/content categories
- `/api/v1/comments/`
  - testimony comments and replies
- `/api/v1/favorites/`
  - user saved content
- `/api/v1/notifications/`
  - user notification list/read actions
  - admin notification history views
- `/api/v1/donations/`
  - create donation, donor history, admin review/filtering
- `/api/v1/content/`
  - inspirational pictures
  - scripture of the day
  - home curation reads and management
- `/api/v1/admins/`
  - admin roles, assignments, invitations
- `/api/v1/analytics/`
  - read-only dashboard reporting endpoints

## Permissions Model

First-pass roles:

- anonymous guest
  - not persisted
  - read-only access to allowed public content
- authenticated user
  - manage own profile
  - submit testimonies
  - comment
  - favorite
  - donate
  - read own notifications and own submission statuses
- admin user
  - access dashboard-protected operations

Recommended admin roles to support early:

- `super_admin`
- `content_admin`
- `moderator`
- `finance_admin`
- optional later:
  - `analytics_admin`
  - `support_admin`

## Audit Requirements

These fields should be considered mandatory for admin-impacting records:

- `created_at`
- `updated_at`
- `created_by` where appropriate
- `updated_by` where appropriate
- `approved_by`
- `rejected_by`
- `deleted_by`
- reason fields for rejection, deactivation, reversal, refund, or deletion actions

For high-risk flows, store explicit action records instead of only overwriting status fields.

## Approved First Feature Slice

Start with `Phase 2: Identity, Auth, And Admin Access`.

Reason:
- every later slice depends on reliable identity and permissions
- both clients already contain auth flows
- admin authorization must be locked early before moderation and operations work
- audit ownership across testimonies, donations, and notifications depends on a stable user/admin model

Recommended order after that:

1. identity, auth, and admin access
2. testimonies core domain
3. moderation and review workflows
4. donations and giving
5. notifications and user activity
6. content management domains
7. reviews, analytics, and operational admin features
8. integration hardening

## Locked Decisions

The following decisions are now locked for implementation:

1. Use one shared base user model plus explicit admin role assignments.
2. Use one canonical `Testimony` aggregate with `type`, `moderation_status`, and `publication_status`.
3. Treat guest donations as first-class.
4. Use the lifecycle states defined in this document.
5. Include comments and favorites in the first testimony slice.
6. Use token-based auth for mobile and session-based auth for dashboard admin.

## Phase 0 Exit Criteria

Phase 0 is complete when:
- this document is accepted or revised into an approved baseline
- cross-cutting identity, testimony, moderation, donation, and notification decisions are locked
- the first feature slice is confirmed
- Phase 1 bootstrap can begin without likely foundational schema rework
