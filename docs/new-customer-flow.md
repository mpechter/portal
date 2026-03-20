# New Customer Flow

A walkthrough of how a new customer discovers, signs up, and starts using the portal.

---

## 1. Discovery — Marketing Page (`/`)

The customer lands on the public homepage. It explains:
- What the product is: a simple client portal that connects to their Airtable base
- Who it's for: small teams, schools, nonprofits, service businesses — anyone already using Airtable who wants to give clients a clean self-service view of their data
- What it does: clients (parents, customers, members) log in with their email and can view/edit their own records — no Airtable access required

**CTA:** "Get Started" button → takes them to `/signup`

---

## 2. Registration — Get Started Page (`/signup`)

A clean form. Fields:

| Field | Notes |
|-------|-------|
| Organization name | e.g. "Sunshine Daycare", "Smith Law" |
| Your email | Stored as `admin_email` — used for password recovery |
| Organization code | Short slug clients use to log in (e.g. `SUNSHINE`). Auto-suggested from org name, editable. Validated as unique via `GET /api/check-org-code` with a debounced inline check as you type. |
| Airtable API key | Personal access token — an inline guide shows required scopes |
| Airtable Base ID | The base to connect |
| Admin password | Sets the admin login password (with confirmation) |

**Airtable permission validation at signup:**
- On submit, we call Airtable's schema endpoint — this validates `schema.bases:read` and that the key + base ID are correct
- `data.records:read/write` are validated at Step 3 (table selection) when we attempt a test record read

On submit:
- Validates org code is unique (server-side, in addition to the async check)
- Tests Airtable credentials (validates `schema.bases:read`)
- Creates the `Organization` record with `plan = "trial"`
- Logs the admin in
- Redirects to → **Step 3**

---

## 3. Setup — Table Configuration (`/admin/tables`)

Admin selects which Airtable table contains their **users/clients** (e.g. "Parents", "Customers") and optionally a second **linked records** table (e.g. "Students", "Cases").

On save:
- Attempts a test record read (`data.records:read` validation)
- If 403: shows a warning banner — "your token is missing data.records:read"
- Setup continues regardless (warning, not a blocker)

After saving → redirects to **Step 4**.

---

## 4. Setup — Field Permissions (`/admin/fields`)

Admin chooses, per field:
- **Editable** — clients can view and change it
- **Read-only** — clients can see it but not edit it
- **Hidden** — not shown to clients at all

They can also add helper text (annotations) to any field.

After saving → redirects to **Step 5**.

---

## 5. Ready — Admin Dashboard (`/admin`)

Admin sees a summary of their setup. They're given:
- Their **portal URL**: `https://app.domain.com/login?org=SUNSHINE`
- Their **org code**: `SUNSHINE`
- Instructions: share the portal URL with clients; they log in with their email and receive a magic link

At this point the portal is live. No payment required (trial plan).

---

## 6. Client Login Flow (already built)

1. Visit the portal URL (or go to `/login` and enter their org code)
2. Enter their email address
3. Receive a 6-digit code + magic link via email
4. Click the link (or enter the code) → logged in
5. See their profile and any linked records
6. View/edit fields as configured by the admin

---

## Password Recovery — Admin (`/admin/forgot-password`)

If an admin forgets their password:

1. Go to `/admin/login`
2. Click "Forgot password?"
3. Enter their org code
4. System looks up `admin_email` for that org
5. Sends a reset link (signed token, 15-minute expiry) to that email — always shows the same success message regardless of whether the org/email exists (security best practice)
6. Admin clicks link → `/admin/reset-password/<token>`
7. Enters and confirms new password
8. Redirected to `/admin/login`

> Note: If `admin_email` is not set for an org, no email is sent — the response message is the same either way.

---

## Database Migration Note

The `admin_email` and `plan` columns were added to the `organizations` table after initial schema creation. For existing databases, run:

```
flask add-admin-columns
```

New databases (`flask init-db`) will include them automatically.

---

## Future: Payment (model ready, not built)

The `Organization` model has a `plan` field (`trial`, `active`, `suspended`). When payment is added (e.g. Stripe):

- Trial orgs get a banner in admin: "You're on a free trial — add billing to keep access"
- Checkout flow added to `/billing`
- Webhook updates `plan` to `active` on successful payment
- `suspended` orgs see a lock screen instead of the portal

No changes to the registration flow needed — it already sets `plan = "trial"`.
