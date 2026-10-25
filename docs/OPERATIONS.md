# Operations and error monitoring

## Error monitoring

The API optionally reports unhandled errors to Sentry. Configure the Render
environment variable `SENTRY_DSN` to enable it. Optional variables:
`SENTRY_ENVIRONMENT` and `SENTRY_RELEASE`. Without a DSN, the app continues
normally and logs that monitoring is disabled.

The integration is error-only (trace sampling is zero), disables default PII,
and scrubs request bodies, cookies, headers, query strings, user identity, and
common sensitive breadcrumb fields before sending an event. This is defense in
depth, not a guarantee that arbitrary exception messages never contain sensitive
text; do not put user questions, answers, credentials, or transcript text into
exception messages. Verify the configured Sentry project, retention, region, and
access controls before production use.

## Health and statistics

`GET /api/health` returns only `{"ok": true}` for load-balancer checks. The
public `/api/stats` endpoint returns corpus processing counts and total chunks,
not user-level analytics or chat content. Keep detailed user/quality analytics
behind the existing admin-token endpoints.

## Ingestion alerts

The daily GitHub Actions workflow writes indexed/skipped/failed counts to its run
summary. Configure the optional `INGESTION_ALERT_WEBHOOK` secret for a webhook
notification when a scheduled run fails. Also monitor the Actions run history;
scheduled workflows can be delayed by GitHub and should not be treated as a
real-time scheduler.
