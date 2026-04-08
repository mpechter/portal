# Portal - TODO

## Next Up

1. Implement trial period logic

3. **Organization logos (upload)**
   - Currently supports logo via URL
   - Future: Allow admins to upload directly
   - Would need cloud storage (S3, Cloudflare R2, etc.)

---

## Completed Features

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
- Admin panel with 3 tabs: Settings, Tables, Fields
- Table selection from Airtable base schema
- Optional linked records (parent → child relationship)
- Field permissions: Editable / Read-only / Hidden
- User profile editing (their own record)
- Linked record editing (e.g., students)
- Save button lights up green when changes detected
- Rate limiting on login attempts
