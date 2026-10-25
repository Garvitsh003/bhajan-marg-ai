# Privacy and terms — draft for legal/product review

**Do not publish this draft unchanged.** Confirm the operator name, contact address,
retention practices, hosting regions, processors, and legal basis with the project
owner and qualified counsel before making it public.

## Data the service may process

- Account details such as name and email, password hashes, session metadata, and
  authentication-provider identifiers.
- Chat questions and answers, source excerpts/links, language preferences, quality
  feedback (including optional typed or transcribed voice feedback), and analytics.
- Security and operational logs and request metadata.

Faith and personal reflections can be sensitive. Collect only what is needed,
restrict staff access, protect backups, and avoid sending chat content or credentials
to general-purpose error telemetry.

## Providers to verify

The current architecture includes a Vercel frontend, Render API, PostgreSQL/Neon
for accounts and saved chats, Qdrant Cloud for retrieval, Google Gemini for answer
generation and optional audio transcription, and optional Google OAuth / Resend
email integrations. Confirm the deployed configuration, purposes, regions, retention
settings, and contractual terms for every enabled provider before publication.

## Retention and deletion

Signed-in users can request deletion from Profile & preferences. The backend removes
the account and linked conversations, messages, feedback, analytics, and quality
cases, including the legacy SQLite chat trace. Verify database cascades, backups,
provider logs, and exported evaluation artifacts before claiming complete erasure.
Define backup expiry and handling for records that must be retained by law.

Guest browser history and locally stored preferences may remain on the device after
account deletion; explain and provide controls for local data separately. Do not
promise deletion from third-party systems until their retention behavior is verified.

## Content rights

Transcript indexing, excerpt display, and timestamp linking require appropriate
permission/legal basis and compliance with applicable platform terms. Public
availability alone is not a redistribution license. Automated ingestion remains
disabled until the owner confirms authorization.

## Terms topics that need review

- AI-generated answers may be incomplete or inaccurate and are not direct quotations
  unless explicitly shown as transcript excerpts.
- Source links should direct users to the original video and timestamp where possible.
- Define acceptable use, abuse prevention, account security, service availability,
  and limitations of liability with counsel.
- Include effective date, operator identity, privacy contact, complaint/grievance
  process if applicable, and applicable jurisdiction.

## Release checklist

- [ ] Confirm operator legal name and privacy contact.
- [ ] Inventory actual production providers and data regions.
- [ ] Set retention periods for chats, logs, feedback, audio, and backups.
- [ ] Test deletion across relational data, vector payloads, logs, exports, and backups.
- [ ] Publish reviewed Privacy Policy and Terms pages with effective dates.
- [ ] Review India DPDP requirements and other applicable privacy laws with counsel.
