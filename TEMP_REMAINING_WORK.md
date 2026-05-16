# TEMP Remaining Work

## Single-Source Policy: Mobile Launch + Access (Phase 2)

This section is the source of truth for launch/auth behavior while implementing remaining Phase 2 work.

### Agreed Rules

1. Onboarding is first-run only and must not repeat for returning users.
2. Mobile supports limited guest access in parallel with authenticated access.
3. Returning users with a valid auth session/token should go directly to authenticated home.
4. Returning users without a valid auth session/token should still be able to continue in restricted guest mode.
5. Protected actions must prompt Create Account / Log In (not silently fail).
6. Manual logout must clear auth session/token and return user to unauthenticated state (guest + auth entry points available).

### Decision Table

| Case | has_seen_onboarding | auth_session/token | Expected start screen |
|---|---|---|---|
| Brand new install | `false` | none | Onboarding |
| Finished onboarding, never logged in | `true` | none | Guest Home (restricted) |
| Logged in previously, token valid | `true` | present + valid | Home (authenticated) |
| Logged in previously, token expired/invalid | `true` | present but invalid | Auth (Login) |
| User logged out manually | `true` | cleared | Unauthenticated state (guest + auth entry points) |
| App updated/restarted while logged in | `true` | present + valid | Home (authenticated) |
| App updated/restarted while guest mode only | `true` | none | Guest Home (restricted) |

## Immediate Implementation Checklist

- [x] Persist `has_seen_onboarding` and enforce one-time onboarding.
- [x] Add startup gate logic for onboarding/session/guest routing based on table above.
- [x] Ensure protected guest-restricted actions consistently open auth prompts.
- [x] Add/adjust tests for launch-routing matrix and guest restriction prompts.
- [x] Run full auth/profile/guest regression tests before closing Phase 2.

## References

- `mobile/TEMP_AUTH_LAUNCH_DECISION_TABLE.md`
- `mobile/plan.md`
- `backend/IMPLEMENTATION_PLAN.md`
- `backend/TESTING.md`

## Temporary Integration Audit (Dashboard + Mobile)

Purpose: track whether completed backend slices are truly wired in UI surfaces (not mock/fallback-driven).

### Ordered Fix List

1. Remove direct `mock-users` dependency from dashboard admin routes for identity rendering.
   - Status: done
   - Updated to use backend session fields (`email`/`full_name`) instead of lookup from mock registry.

2. Keep backend-wired routes on `FromApi`/`FromBackend` providers and verify no regression.
   - Status: done (existing wiring retained)
   - Routes confirmed: testimonies, donations, notifications history, home management, inspirational pictures, scripture of the day.

3. Replace mock-only dashboard route view models where backend endpoints already exist.
   - Status: done
   - Completed in this pass:
     - `users` now uses backend API (`getUsersViewModelFromApi`) and action routes call backend deactivate/reactivate endpoints.
     - `overview` now uses backend API-derived metrics (`getAdminOverviewViewModelFromApi`).
     - `my-profile` now uses backend profile endpoint (`getMyProfileViewModelFromApi`).
     - `notification-settings` now uses backend endpoint (`GET /api/v1/notifications/preferences/me/`) via `getNotificationSettingsViewModelFromApi`.
     - `notification-settings` save now persists via dashboard API proxy (`POST /api/admin/notifications/preferences` -> backend `PATCH /api/v1/notifications/preferences/me/`).

4. Replace dashboard mocks for Phase 8 surfaces.
   - Status: blocked intentionally
   - Block reason: Phase 8 backend remains deferred by instruction (`reviews`, `analytics`, `admin management` endpoints not started).

5. Remove/disable mobile auth mock fallback for non-test runtime.
   - Status: pending
   - Current behavior: fallback remains enabled in some non-prod paths by env/test bootstrap.

### Notes

- This temporary section should be removed after full backend parity is achieved across completed phases.

## Next Work Priority Queue

Priority order for remaining work (excluding Phase 8 by instruction):

1. High — Replace `auto_publish` side-effect in `GET` with a management command / cron.
   - Status: done
   - Implemented command: `./.venv/bin/python manage.py publish_due_scriptures`
   - Scheduling note: run via cron/worker at regular intervals (e.g., every 5-15 minutes) in deployed environments.
2. High — Fix `comment_count` race condition with `F()` expression updates.
   - Status: done
   - Decrement path now uses single-statement atomic clamp: `Greatest(F("comment_count") - 1, 0)`.
3. Medium — Reconcile Phase 13 status contradiction in dashboard plan.
   - Status: done
   - `dashboard/IMPLEMENTATION_PLAN.md` updated: Phase 13 marked `In progress` with explicit backend-integration note.
4. Medium — Clarify or add Phase 7 Slice 9 in implementation plan.
   - Status: done
   - Clarified in `backend/IMPLEMENTATION_PLAN.md`: "Slice 9" content publish flow refers to Phase 9, not Phase 7.
5. Low — Document or fix donation amount integer convention.
   - Status: done
   - Convention documented at model/API level: amount is in minor currency units (`kobo`/`cents`).
6. Low — Move slug generation out of `TestimonyCategory.save()`.
   - Status: done
   - Confirmed slug generation is not in `save()`; handled outside via signal path.
7. Low — Fix `_invalidate_user_sessions` to avoid full-session scan.
   - Status: done
   - Added `UserSession` tracking and invalidation by tracked session keys (no global session decode scan).

## Phase 7 Progress Snapshot

Current state:
- Phase 7 slices 1-8 are implemented and wired into dashboard and mobile content surfaces.
- Verified with backend content API tests, dashboard component tests, and mobile browse/content tests.
- Phase 7 is complete at 8 slices; remaining work continues in later phases.

## Google Sign-In Readiness (Phase 2 Slice 5)

Current state: backend endpoint and tests are implemented, but end-to-end mobile Google login is not yet complete.

### Remaining Work

- [ ] Configure backend environment with real Google client IDs:
  - `GOOGLE_OAUTH_CLIENT_IDS`
  - `GOOGLE_OAUTH_ALLOWED_ISSUERS` (optional override)
- [x] Install backend dependencies in active environment (includes `google-auth`).
- [x] Wire mobile Google login button to obtain `id_token` and call:
  - `POST /api/v1/auth/mobile/google/`
- [x] Run backend auth test suite locally and confirm pass.
- [x] Run mobile integration test for successful Google sign-in and failure cases.

### Platform Configuration Checklist (Google Console + Mobile)

Current app identifiers in this repo:
- Android applicationId: `com.example.itestified` (from `mobile/android/app/build.gradle.kts`)
- iOS bundle id: `com.example.itestified` (from `mobile/ios/Runner.xcodeproj/project.pbxproj`)

Google Console / Firebase setup:
- [ ] Create Android OAuth client for package `com.example.itestified` with SHA-1 and SHA-256 of your signing cert.
- [ ] Create iOS OAuth client for bundle `com.example.itestified`.
- [ ] Keep the Web client ID as well if your Google setup requires it.
- [ ] Copy all required client IDs into backend env:
  - `GOOGLE_OAUTH_CLIENT_IDS=android-client-id,ios-client-id[,web-client-id]`

Android file setup:
- [ ] Download `google-services.json` and place it at:
  - `mobile/android/app/google-services.json`
- [ ] Verify package name in `google-services.json` matches `com.example.itestified`.

iOS file setup:
- [ ] Download `GoogleService-Info.plist` and place it at:
  - `mobile/ios/Runner/GoogleService-Info.plist`
- [ ] In Xcode, ensure `GoogleService-Info.plist` is added to Runner target.
- [ ] Add URL type in `mobile/ios/Runner/Info.plist` for `REVERSED_CLIENT_ID` from `GoogleService-Info.plist` if not auto-managed.

Local verification commands:
- [ ] Backend:
  - [x] `./.venv/bin/pip install -r backend/requirements/test.txt`
  - [x] `./.venv/bin/python backend/manage.py test apps.authn.tests`
- [ ] Mobile:
  - `cd mobile && flutter pub get`
  - `cd mobile && flutter test test/features/auth/domain/usecases/login_with_google_test.dart`

### Done Criteria

- Google sign-in succeeds from mobile UI and returns authenticated app state.
- Invalid/expired/wrong-audience tokens are rejected with safe errors.
- Slice 5 tests are passing and recorded in phase verification notes.
