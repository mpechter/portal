# Portal - common tasks

# Deploy to Fly.io
deploy:
    fly deploy

# Run database migrations (creates new tables/columns)
migrate:
    fly ssh console -C "uv run flask migrate-db"

# View application logs
logs:
    fly logs

# Open SSH console on Fly.io
console:
    fly ssh console

# Connect to Postgres database
db:
    fly postgres connect -a solitary-sun-1157

# Run locally in demo mode
dev:
    DEMO_MODE=true uv run flask run --debug

# Run locally with real Airtable (requires .env)
run:
    uv run flask run

# Check app status
status:
    fly status

# Open app in browser
open:
    fly open
