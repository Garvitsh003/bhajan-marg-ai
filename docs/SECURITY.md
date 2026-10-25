# Production security notes

## Rate limits

- `POST /api/chat`: 10 requests per IP per minute.
- Registration, login, password reset, and forgot-password: 5 requests per IP per minute.
- Google OAuth and session endpoints have route-specific limits.
- Voice-feedback transcription is limited to 5 requests per IP per minute.

Default storage is process-local (`memory://`). Before running multiple API
workers or instances, configure `RATE_LIMIT_STORAGE_URI` to a shared Redis-compatible
store. Ensure the hosting proxy passes the real client IP safely; do not trust
unvalidated forwarded headers.

## Registration and email verification

Registration returns the same generic message for new and existing addresses and
does not automatically create a session. Users sign in after submitting the form.
`email_verified` remains informational until a real verification-email flow exists;
enforcing it now would lock out password users because registration currently sends
no verification email. Add a complete verification-token/email flow before using it
as an authentication gate.

## Origins and headers

Set `CORS_ORIGINS` to exact frontend origins, comma-separated. Never use `*` in
production. The frontend and API set MIME-sniffing, clickjacking, referrer,
permissions, and CSP headers. The CSP permits inline script/style because the
current single-page frontend contains inline code; move those blocks into separate
files before tightening the policy further.

## Admin authorization

Admin routes must use `app.v1_api._require_admin`, which fails closed when the
secret is missing and compares tokens with `secrets.compare_digest`.
