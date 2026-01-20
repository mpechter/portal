# Portal - TODO

## Next Up

1. **Move login codes to Postgres (security)**
   - Currently stored in plaintext in Airtable (visible to anyone with base access)
   - Store hashed codes in Postgres instead
   - Keep Code Expires in Postgres too
   - Remove Login Code / Code Expires fields from Airtable requirements

2. **Use schema API for field discovery (robustness)**
   - `get_all_record_fields()` and `get_all_user_fields()` sample records to find fields
   - Fields with no data won't appear in admin Fields panel
   - Should use `get_table_by_name()` schema API instead (like we did for single select options)

3. Implement trial period logic

4. **Organization logos (upload)**
   - Currently supports logo via URL
   - Future: Allow admins to upload directly
   - Would need cloud storage (S3, Cloudflare R2, etc.)

5. Add Flask-Migrate for database schema migrations

---

## Completed Features

- Data confirmation field uses single select with value selection (instead of date)
- Document required Airtable token scopes in admin Settings
- Fly.io deployment with Postgres
- Resend email integration for login codes
- Validate Users table has required fields (Email, Login Code, Code Expires) during setup
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
- 6-digit login codes (no email provider required yet)
- Admin panel with 3 tabs: Settings, Tables, Fields
- Table selection from Airtable base schema
- Optional linked records (parent → child relationship)
- Field permissions: Editable / Read-only / Hidden
- User profile editing (their own record)
- Linked record editing (e.g., students)
- Save button lights up green when changes detected
- Rate limiting on login attempts
