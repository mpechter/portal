# Portal - TODO

## Next Up

- **Conditional field visibility**
  - Only show certain fields to clients based on values in the record
  - e.g. only ask about bussing if grade > 4; only show a section if enrollment status = "Active"
  - Admin configures rules: field X is visible when field Y equals/contains value Z
  - Requires UI for building rules + client-side evaluation at render time

- **Multiple portals per account (Pro)**
  - Data model groundwork done: `portal_configs` table is separate from `organizations`; one org can have many PortalConfigs
  - Remaining: UI for creating/naming/switching portals; portal selector on client login; scoping admin table/field config to a specific portal

- **Encrypt Airtable API keys at rest (application-level)**
  - Keys are currently stored as plaintext in `portal_configs.airtable_api_key`
  - Fly.io encrypts the storage volume (protects against physical disk access), but a DB dump, backup file, or leaked `DATABASE_URL` exposes the keys in plain text
  - Fix: encrypt the column value with `cryptography.fernet` before INSERT, decrypt after SELECT; store the encryption key in an env var separate from `DATABASE_URL`
  - Risk if skipped: a misconfigured backup or compromised DB connection leaks all customer Airtable tokens

- **Organization logos (upload)**
  - Currently supports logo via URL
  - Future: Allow admins to upload directly
  - Would need cloud storage (S3, Cloudflare R2, etc.)

- **Database backups**
  - Set up nightly pg_dump to object storage (S3 or Backblaze B2)

---

## Completed Features

- PortalConfig table extracted from organizations (multi-portal groundwork)
  - `portal_configs` table holds all Airtable + portal-specific config; `organizations` holds account identity + billing
  - Organization proxies all portal fields transparently so no app logic changed
- Airtable base dropdown in signup and admin settings
  - New `POST /api/airtable-bases` endpoint fetches accessible bases from a PAT
  - Settings page auto-loads on page load if a stored key exists; signup prompts user to click "Load Bases"
  - Falls back to manual Base ID entry if the token lacks `schema.bases:read` or fetch fails
- Security hardening (signup flow + general)
  - Signup token no longer embeds bcrypt hash: `PendingSignup` table stores hash server-side; token carries only the row ID
  - Verification link is single-use: `claim()` sets `used_at` on first redemption and rejects replays
  - Rate limiting: `POST /signup` 10/hour per IP; `POST /api/airtable-bases` 20/minute per IP (flask-limiter, in-memory)
  - Admin sessions expire after 8 hours (`PERMANENT_SESSION_LIFETIME`)
  - Security headers on all responses: `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`
  - `portal_title` HTML-escaped before embedding in outgoing login emails
  - Error details no longer leaked from `/api/airtable-bases` 500 responses
- 7-day trial countdown with expiry enforcement (client portal deactivated, admin access preserved)
- Admin priority support form (emails info@airbud.app with org context)
- Contact form at /contact (sends to info@airbud.app via Resend)
- Signup notification email to info@airbud.app on new account creation
- Pro pricing tier with purple styling and "All features of Starter"
- CSS custom properties for all design tokens
- SVG Heroicons replacing emoji feature icons
- Marketing nav extracted to reusable Jinja2 macro
- Database favicon (SVG cylinder)
- Stripe billing integration with checkout and customer portal
- Admin email change with verification flow
- Admin password reset via email
- Field annotations (custom labels visible to clients)
- Field discovery uses schema API (all fields appear even if empty)
- Login codes stored securely in Postgres (hashed), not Airtable
- Rate limiting persisted in Postgres (works across server instances)
- Schema caching (5 min TTL) to reduce Airtable API calls
- Client Review feature with green checkmarks on dashboard
- Data confirmation field uses single select with value selection (instead of date)
- Document required Airtable token scopes in admin Settings
- Fly.io deployment with Postgres
- Resend email integration for login codes
- Custom domain (airbud.app) with Cloudflare + Fly.io TLS
- Transactional email verified via Resend (info@airbud.app)
- Validate Users table has required Email field during setup
- Prevent link fields from being Editable (hidden from admin Fields panel)
- Auto-detect link field from Airtable schema
- Simplified admin table configuration UI
- Organization logo URL support (displayed in navbar)
- UV package management with pyproject.toml
- Support for multiple Airtable field types (text, textarea, select, multi-select, checkbox, date, number, email, phone, URL)
- GitHub repo setup
- Stale code cleanup
- README with setup instructions
- Multi-tenant org support with org codes
- 6-digit login codes + magic links via Resend
- Admin panel with tabs: Settings, Tables, Fields, Billing, Support
- Table selection from Airtable base schema
- Optional linked records (parent → child relationship)
- Field permissions: Editable / Read-only / Hidden
- User profile editing (their own record)
- Linked record editing (e.g., students)
- Save button lights up green when changes detected
- Rate limiting on login attempts
