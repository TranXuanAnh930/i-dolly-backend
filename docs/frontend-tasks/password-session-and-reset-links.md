# Frontend task: keep the session after a password change; reset links work once

English | [日本語](password-session-and-reset-links_JP.md)

**Backend change:** `docs/bugs.md` #18 and #19 (branch `fix/password-sessions-and-reset-links`).
**Type:** not breaking, but Task 1 is needed to avoid a surprise logout. Without it a fan who
changes their password is logged out when their current access token expires, instead of staying
logged in.
**Reference:** `docs/api-spec.md` has the exact request and response shapes. File names below are
in `i-dolly-frontend`.

## 1. What changed on the backend

### 1a. Changing the password rotates the session (#18)

`PUT /profile/change-password` now revokes every refresh token the account has, then issues a new
pair to the caller. The response looks like `POST /account/refresh`:

| | Before | After |
|---|---|---|
| Body | `{"msg": "Password changed succesfully"}` | `{"msg": "...", "access_token": "<new JWT>"}` |
| Cookie | unchanged | new `refresh_token` cookie (httpOnly, Secure, SameSite=None) |
| Old refresh token | still valid | revoked: `POST /account/refresh` with it answers `401` |

A wrong `old_password` still answers `400 incorrect_password` and changes nothing.

### 1b. Reset links are single-use (#19)

`POST /profile/set-password` answers `401 invalid_token` for a token that was already used, or
that was issued before the password changed some other way. Links emailed before this backend
deploy are rejected too (they'd have expired soon anyway).

## 2. Frontend tasks

### Task 1: keep the session after a password change

`UsersService.changePassword` (`src/services/auth/users.service.js`) sends the request without
credentials, so the browser ignores the new cookie, and nothing picks up the new access token.

- Send the request with `withCredentials: true`, the same way `AuthService.refreshTokens` calls
  `POST /account/refresh`. Without it the `Set-Cookie` header is dropped.
- On success, store `response.data.access_token` the same way `refreshTokens` does (bearer and
  expiry date). `_setAuthData` in `src/services/auth/auth.service.js` is private; expose a small
  `AuthService.applyAccessToken(accessToken)` (or similar) rather than duplicating it.
- `AccountSettingsPage.vue` needs no change beyond that: the success toast stays as it is.

### Task 2: reset page message

`src/pages/auth/ResetPasswordPage.vue` already shows `error.message` for `invalid_token`
("This link has expired. Please request a new one."). A used link now gets the same code, so
widen the wording in `src/i18n/locales/en.js` and `ja.js`, for example "This link has expired or
has already been used. Please request a new one.", and keep the link to the forgot-password page.

## 3. Acceptance checklist

- [ ] Change the password in account settings, then keep using the app past the access-token
      lifetime: no logout, and the network tab shows `POST /account/refresh` succeeding.
- [ ] A second browser that was logged in to the same account is logged out at its next refresh.
- [ ] A wrong current password shows the existing error, and the session is unaffected.
- [ ] A reset link opened a second time shows the expired-or-used message with a way to request
      a new link.
- [ ] A reset link requested, then followed after changing the password in account settings,
      shows the same message.

## 4. Out of scope

- One session per account is unchanged: logging in anywhere still ends the other sessions.
- Refresh tokens are still stored in plain text in the database (`docs/bugs.md` #20).
