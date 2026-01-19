# Portal - TODO

## Next Up

1. Change "updated" field to single select, select value
2. Implement trial period logic
3. Move login codes out of Airtable (security: codes visible to anyone with base access)
4. Host!

5. **Organization logos (upload)**
   - Currently supports logo via URL
   - Future: Allow admins to upload directly
   - Would need cloud storage (S3, Cloudflare R2, etc.)

6. Password strength requirements
7. Add Flask-Migrate for database schema migrations
8. Validate Users table has required fields (Email, Login Code, Code Expires) during setup
9. Prevent link fields from being Editable (could break user-record relationships)

---

## Completed Features

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
