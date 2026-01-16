from datetime import datetime, timezone
from pyairtable import Api


class AirtableClient:
    """Multi-tenant Airtable client that connects to an org's specific base."""

    def __init__(self, org):
        """
        Initialize with an Organization model instance.

        Args:
            org: Organization model with airtable_api_key, airtable_base_id,
                 users_table, and records_table attributes.
        """
        self.org = org
        self.api = Api(org.airtable_api_key)
        self.base = self.api.base(org.airtable_base_id)
        # Only initialize table references if tables are configured
        if org.users_table:
            self.users_table = self.base.table(org.users_table)
        else:
            self.users_table = None
        if org.records_table:
            self.records_table = self.base.table(org.records_table)
        else:
            self.records_table = None

    def get_base_tables(self) -> list:
        """Get all tables in the base with their schema."""
        try:
            schema = self.base.schema()
            tables = []
            for table in schema.tables:
                table_info = {
                    "id": table.id,
                    "name": table.name,
                    "fields": [],
                    "linked_fields": [],
                }
                for field in table.fields:
                    field_info = {
                        "id": field.id,
                        "name": field.name,
                        "type": field.type,
                    }
                    # Add options for select fields
                    if field.type in ("singleSelect", "multipleSelects") and field.options:
                        choices = field.options.get("choices", [])
                        field_info["options"] = [c.get("name") for c in choices if c.get("name")]
                    # Check if it's a linked record field
                    if field.type == "multipleRecordLinks":
                        linked_table_id = field.options.get("linkedTableId") if field.options else None
                        field_info["linked_table_id"] = linked_table_id
                        table_info["linked_fields"].append(field_info)
                    table_info["fields"].append(field_info)
                tables.append(table_info)
            return tables
        except Exception as e:
            print(f"Error fetching base schema: {e}", flush=True)
            return []

    def get_table_by_name(self, table_name: str) -> dict | None:
        """Get a specific table's schema by name."""
        tables = self.get_base_tables()
        for table in tables:
            if table["name"] == table_name:
                return table
        return None

    def get_field_metadata(self, table_name: str, field_names: list) -> dict:
        """Get field metadata (type, options) for specified fields in a table.

        Returns a dict mapping field_name to {type, options}.
        """
        table = self.get_table_by_name(table_name)
        if not table:
            return {}

        metadata = {}
        for field in table.get("fields", []):
            if field["name"] in field_names:
                metadata[field["name"]] = {
                    "type": field.get("type", "singleLineText"),
                    "options": field.get("options", []),
                }
        return metadata

    def get_user_by_email(self, email: str) -> dict | None:
        """Find a user by email address."""
        records = self.users_table.all(formula=f"{{Email}} = '{email}'")
        if records:
            return records[0]
        return None

    def get_user_by_id(self, record_id: str) -> dict | None:
        """Get a user by Airtable record ID."""
        try:
            return self.users_table.get(record_id)
        except Exception:
            return None

    def save_login_code(self, user_id: str, code: str, expires: datetime):
        """Save a login code for a user."""
        self.users_table.update(
            user_id,
            {
                "Login Code": code,
                "Code Expires": expires.isoformat(),
            },
        )

    def clear_login_code(self, user_id: str):
        """Clear the login code after successful login."""
        self.users_table.update(
            user_id,
            {
                "Login Code": "",
                "Code Expires": None,
            },
        )

    def get_records_for_user(self, user_id: str) -> list:
        """Get all records linked to a user."""
        # Query records where the User field contains this user's ID
        records = self.records_table.all(
            formula=f"FIND('{user_id}', ARRAYJOIN(User))"
        )
        return records

    def get_record_by_id(self, record_id: str) -> dict | None:
        """Get a record by its ID."""
        try:
            return self.records_table.get(record_id)
        except Exception:
            return None

    def update_record(self, record_id: str, fields: dict):
        """Update a record with the provided fields."""
        self.records_table.update(record_id, fields)

    def can_user_access_record(self, user_id: str, record_id: str) -> bool:
        """Check if a user has access to a specific record."""
        record = self.get_record_by_id(record_id)
        if not record:
            return False

        # Get the linked user IDs
        user_ids = record.get("fields", {}).get("User", [])
        return user_id in user_ids

    def get_all_record_fields(self) -> list:
        """Get all field names from the Records table by sampling records."""
        # Fetch a few records to discover all fields
        records = self.records_table.all(max_records=10)
        field_names = set()
        for record in records:
            field_names.update(record.get("fields", {}).keys())
        # Remove system/link fields that shouldn't be configured
        field_names.discard("User")
        return sorted(field_names)

    def get_all_user_fields(self) -> list:
        """Get all field names from the Users table by sampling records."""
        records = self.users_table.all(max_records=10)
        field_names = set()
        for record in records:
            field_names.update(record.get("fields", {}).keys())
        # Remove system/auth fields that shouldn't be shown to users
        system_fields = {"Login Code", "Code Expires", "Email"}
        field_names -= system_fields
        return sorted(field_names)

    def update_user(self, user_id: str, fields: dict):
        """Update a user record with the provided fields."""
        self.users_table.update(user_id, fields)


def get_client_for_org(org):
    """Factory function to create an AirtableClient for an organization."""
    from config import Config
    if Config.DEMO_MODE:
        from demo_data import DemoAirtableClient
        return DemoAirtableClient(org)
    return AirtableClient(org)
