# Portal - TODO

## Next Up

1. **Support additional Airtable field types**
   - Currently only handles text fields
   - Need to support:
     - Dates (date picker)
     - Single Select (dropdown)
     - Multiple Select (multi-select dropdown)
     - Checkboxes
     - Numbers
     - etc.
   - Render appropriate input controls based on field type
   - Handle field type metadata from Airtable schema API

2. Put into github

3. Switch to using UV

4. Remove any stale code.

5. Host!

---

## Completed Features

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
