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

## Demo Mode

Set `DEMO_MODE=true` in your `.env` to use mock data without connecting to Airtable. This is useful for development and testing.

Demo credentials:
- **Org code**: `DEMO`
- **Admin password**: `admin`
- **User email**: `parent@example.com`

Login codes are printed to the console.

## Adding Email

Currently, login codes are printed to the console. To send actual emails, integrate your email provider in `auth.py`:

```python
def send_login_code(org, user_email: str, user_id: str) -> bool:
    code = generate_login_code()
    # ... save code to Airtable ...

    # Add your email sending logic here
    # e.g., SendGrid, AWS SES, Postmark, etc.

    return True
```

## License

MIT
