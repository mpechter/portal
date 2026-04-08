# Portal

A self-service portal that lets users log in and edit their own records in Airtable. Built for scenarios like parent portals, client dashboards, or member directories where you want to give people controlled access to update their information.

## Features

- **Multi-tenant**: Support multiple organizations, each with their own Airtable base
- **Passwordless login**: Users receive a 6-digit code to log in (no passwords to remember)
- **Profile editing**: Users can edit fields on their own record
- **Linked records**: Optionally let users edit linked records (e.g., parents editing student info)
- **Admin-controlled permissions**: Set fields as Editable, Read-only, or Hidden
- **Simple admin UI**: Configure tables and field permissions without touching code

## Quick Start

### 1. Install dependencies

Using [uv](https://docs.astral.sh/uv/) (recommended):
```bash
uv sync
```

Or with pip:
```bash
pip install -r requirements.txt
```

### 2. Set up environment variables

Create a `.env` file:

```bash
SECRET_KEY=your-secret-key-here
DEMO_MODE=true  # Set to false for production with real Airtable
```

### 3. Initialize the database

```bash
flask init-db
```

### 4. Add an organization

```bash
flask add-org
```

You'll be prompted for:
- **Org code**: Short code users enter to identify their organization (e.g., `SCHOOL1`)
- **Organization name**: Display name
- **Airtable API key**: Your [personal access token](https://airtable.com/create/tokens)
- **Airtable Base ID**: Found in your base URL (starts with `app`)
- **Portal title**: Shown to users
- **Admin password**: For accessing the admin panel

### 5. Run the server

```bash
flask run
```

### 6. Configure in admin panel

1. Go to `http://localhost:5000/admin/login`
2. Enter your org code and admin password
3. **Settings tab**: Verify your Airtable connection
4. **Tables tab**: Select which table contains your users, and optionally select a linked records field
5. **Fields tab**: Configure which fields users can see and edit

## How It Works

### User Flow

1. User goes to the portal and enters their org code
2. User enters their email address
3. A 6-digit login code is generated (printed to console in dev mode)
4. User enters the code and is logged in
5. User sees their profile and any linked records
6. User can edit fields the admin has marked as "Editable"

### Admin Configuration

**Tables Tab**
- **Users Table**: The table where users log in (must have an Email field)
- **Linked Records**: Optionally select a field that links to another table (e.g., a "Students" field that links to a Students table)

**Fields Tab**
- **Editable**: User can view and modify
- **Read-only**: User can view but not modify
- **Hidden**: User cannot see the field

## Airtable Setup

Your Airtable base needs:

1. A **Users table** with at least:
   - `Email` field (email type) - used for login
   - Any other fields you want users to see/edit

2. Optionally, a **linked records table** with:
   - A link field back to the Users table (e.g., a "Parent" field)
   - Any fields you want users to see/edit

3. A **Personal Access Token** with these scopes:
   - `data.records:read`
   - `data.records:write`
   - `schema.bases:read`

## Project Structure

```
portal/
├── app.py              # Flask routes and main application
├── models.py           # Database models (Organization)
├── auth.py             # Login code generation and verification
├── airtable_client.py  # Airtable API wrapper
├── config.py           # Configuration from environment
├── demo_data.py        # Mock data for demo mode
├── templates/          # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── verify_code.html
│   ├── dashboard.html
│   ├── edit_record.html
│   ├── edit_profile.html
│   └── admin/
│       ├── login.html
│       ├── settings.html
│       ├── tables.html
│       └── fields.html
├── static/
│   └── style.css
├── requirements.txt
└── instance/
    └── portal.db       # SQLite database (created on init)
```

## Fly.io Deployment

### Initial Setup

1. Create the app and Postgres database:
   ```bash
   fly launch
   fly postgres create
   fly postgres attach <postgres-app-name>
   ```

2. Set required secrets:
   ```bash
   fly secrets set SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
   fly secrets set RESEND_API_KEY=your-resend-api-key
   ```

3. Deploy and initialize the database:
   ```bash
   fly deploy
   fly ssh console
   uv run python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Done')"
   exit
   ```

4. Create your organization through the signup flow at your app URL.

### Adding New Organizations

Organizations can be added in two ways:

**Option 1: Signup Flow (Recommended)**

Navigate to `/signup` on your deployed app and fill out the form. This creates the organization and admin account in one step.

**Option 2: Direct Database Insert**

Connect to Postgres and insert directly:

```bash
fly postgres connect -a <your-postgres-app-name>
\c <your-database-name>
```

```sql
INSERT INTO organizations (
    org_code, name, portal_title, admin_password_hash,
    airtable_api_key, airtable_base_id, created_at
) VALUES (
    'MYORG',
    'My Organization',
    'My Portal',
    -- Generate hash: python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('yourpassword'))"
    'scrypt:32768:8:1$...',
    'pat_xxxxx',
    'appXXXXXXXXXXXXXX',
    NOW()
);
```

After inserting, log into the admin panel at `/admin/login` to configure tables and fields.

### Database Migrations

Portal uses SQLAlchemy without a migration framework. When the schema changes:

**For new tables or columns:**

```bash
fly ssh console
uv run python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Done')"
```

Note: `db.create_all()` only creates new tables/columns—it won't modify existing columns or delete data.

**For column modifications (rare):**

Connect to Postgres and run ALTER TABLE manually:

```bash
fly postgres connect -a <your-postgres-app-name>
\c <your-database-name>
```

```sql
-- Example: Add a new column
ALTER TABLE organizations ADD COLUMN new_field VARCHAR(255);

-- Example: Change column type
ALTER TABLE organizations ALTER COLUMN some_field TYPE TEXT;

-- Example: Add an index
CREATE INDEX idx_login_codes_email ON login_codes(user_email);
```

**Listing current schema:**

```sql
\dt                          -- List all tables
\d organizations             -- Describe organizations table
\d login_codes               -- Describe login_codes table
```

**Current tables:**
- `organizations` - Multi-tenant org configuration
- `login_codes` - Hashed login codes with expiry
- `login_attempts` - Rate limiting for failed logins

## Demo Mode

Set `DEMO_MODE=true` in your `.env` to use mock data without connecting to Airtable. This is useful for development and testing.

Demo credentials:
- **Org code**: `DEMO`
- **Admin password**: `admin`
- **User email**: `parent@example.com`

Login codes are printed to the console.

## Email Setup (Resend)

Login codes are sent via [Resend](https://resend.com). Set these environment variables:

```bash
RESEND_API_KEY=re_xxxxx
EMAIL_FROM=noreply@yourdomain.com
```

In demo mode or when `RESEND_API_KEY` is not set, login codes are printed to the console instead.

## Services

| Service | Purpose | Required? |
|---------|---------|-----------|
| [Airtable](https://airtable.com) | Data store — user records live here | Yes |
| [Fly.io](https://fly.io) | App hosting and deployment | For production |
| [Fly.io Postgres](https://fly.io/docs/postgres/) | Persistent database for orgs, login codes, rate limiting | For production (SQLite locally) |
| [Resend](https://resend.com) | Transactional email — sends login codes and magic links | For production |
| [Cloudflare](https://cloudflare.com) | DNS and domain management | Optional |

### Notes

- **Airtable**: You need a Personal Access Token with `data.records:read`, `data.records:write`, and `schema.bases:read` scopes. Each organization has its own token and base.
- **Fly.io**: Handles TLS automatically. The app is configured to auto-stop when idle (`min_machines_running = 0`) to minimize cost.
- **Resend**: Required for email in production. Without it, login codes are printed to the console (useful in dev/demo mode). You must verify a sending domain in Resend and set `EMAIL_FROM` to an address on that domain.
- **Cloudflare**: Used for DNS if you have a custom domain. Not required — the app works on the default `fly.dev` subdomain.

## License

MIT
