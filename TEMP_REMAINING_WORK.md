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
