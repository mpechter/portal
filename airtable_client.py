from datetime import datetime, timezone
import time
from pyairtable import Api

# Schema cache: {base_id: {"tables": [...], "timestamp": float}}
_schema_cache = {}
SCHEMA_CACHE_TTL = 300  # 5 minutes

# Airtable field types that are computed/formula-based and cannot be written to
COMPUTED_FIELD_TYPES = frozenset({
    "formula",
    "rollup",
    "count",
    "multipleLookupValues",
    "multipleRecordLinks",
    "autoNumber",
    "createdTime",
    "lastModifiedTime",
    "createdBy",
    "lastModifiedBy",
    "button",
})

# Subset of computed types that are link fields (shown with "link" badge in admin UI)
LINK_FIELD_TYPES = frozenset({"multipleRecordLinks"})


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
        """Get all tables in the base with their schema (cached)."""
        base_id = self.org.airtable_base_id

        # Check cache
        if base_id in _schema_cache:
            cached = _schema_cache[base_id]
            if time.time() - cached["timestamp"] < SCHEMA_CACHE_TTL:
                return cached["tables"]

        # Fetch fresh schema
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
                    if field.type in ("singleSelect", "multipleSelects"):
                        choices = []
                        if field.options:
                            choices = getattr(field.options, "choices", None)
                            if choices is None:
                                # Try dict access as fallback
                                choices = field.options.get("choices", []) if isinstance(field.options, dict) else []
                        field_info["options"] = [c.name if hasattr(c, "name") else c.get("name", c) for c in (choices or [])]
                    # Check if it's a linked record field
                    if field.type == "multipleRecordLinks" and field.options:
                        linked_table_id = getattr(field.options, "linked_table_id", None)
                        field_info["linked_table_id"] = linked_table_id
                        table_info["linked_fields"].append(field_info)
                    table_info["fields"].append(field_info)
                tables.append(table_info)

            # Store in cache
            _schema_cache[base_id] = {
                "tables": tables,
                "timestamp": time.time(),
            }
            return tables
        except Exception as e:
            print(f"Error fetching base schema: {e}", flush=True)
            return []

    @staticmethod
    def clear_schema_cache(base_id: str = None):
        """Clear the schema cache for a specific base or all bases."""
        if base_id:
            _schema_cache.pop(base_id, None)
        else:
            _schema_cache.clear()

    def get_table_by_name(self, table_name: str) -> dict | None:
        """Get a specific table's schema by name."""
        tables = self.get_base_tables()
        for table in tables:
            if table["name"] == table_name:
                return table
        return None

    def detect_link_field(self) -> str | None:
        """Auto-detect the field in records_table that links to users_table."""
        if not self.org.records_table or not self.org.users_table:
            return None

        tables = self.get_base_tables()

        # Find the users table ID
        users_table_id = None
        for table in tables:
            if table["name"] == self.org.users_table:
                users_table_id = table["id"]
                break

        if not users_table_id:
            return None

        # Find the linked field in records_table that points to users_table
        for table in tables:
            if table["name"] == self.org.records_table:
                for field in table.get("linked_fields", []):
                    if field.get("linked_table_id") == users_table_id:
                        return field["name"]

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

    def get_computed_field_names(self, table_name: str) -> set:
        """Return names of fields that are computed/formula types and cannot be edited."""
        table = self.get_table_by_name(table_name)
        if not table:
            return set()
        return {
            field["name"]
            for field in table.get("fields", [])
            if field.get("type") in COMPUTED_FIELD_TYPES
        }

    def get_user_by_email(self, email: str) -> dict | None:
        """Find a user by email address."""
        import re
        if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
            return None
        email_field = self.org.email_field or "Email"
        safe_email = email.replace("'", "\\'")
        records = self.users_table.all(formula=f"{{{email_field}}} = '{safe_email}'")
        if records:
            return records[0]
        return None

    def get_user_by_id(self, record_id: str) -> dict | None:
        """Get a user by Airtable record ID."""
        try:
            return self.users_table.get(record_id)
        except Exception:
            return None

    def get_records_for_user(self, user_id: str) -> list:
        """Get all records linked to a user.

        Records are fetched server-side by matching on the user's display name
        (primary field value) because Airtable's ARRAYJOIN formula returns display
        names, not record IDs. A post-filter then verifies ownership by checking
        the actual linked record ID array in each record's fields.
        """
        # Use configured link_field, or auto-detect from schema
        link_field = self.org.link_field or self.detect_link_field()
        if not link_field:
            return []

        # Get the user's name - Airtable's ARRAYJOIN on linked fields returns
        # display names (primary field values), not record IDs
        user = self.get_user_by_id(user_id)
        if not user:
            return []
        user_name = user.get("fields", {}).get("Name", "")
        if not user_name:
            return []

        # Escape single quotes in the name for the formula
        user_name_escaped = user_name.replace("'", "\\'")
        records = self.records_table.all(
            formula=f"FIND('{user_name_escaped}', ARRAYJOIN({{{link_field}}}))"
        )
        # Post-filter by record ID to eliminate false positives from name matches
        records = [r for r in records if user_id in r.get("fields", {}).get(link_field, [])]
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
        link_field = self.org.link_field or self.detect_link_field()
        if not link_field:
            print(f"Warning: cannot determine link field for org {self.org.org_code}, denying access", flush=True)
            return False
        user_ids = record.get("fields", {}).get(link_field, [])
        return user_id in user_ids

    def get_all_record_fields(self) -> list:
        """Get all field names from the Records table using schema API."""
        table_info = self.get_table_by_name(self.org.records_table)
        if not table_info:
            return []
        return sorted(field["name"] for field in table_info.get("fields", []))

    def get_all_user_fields(self) -> list:
        """Get all field names from the Users table using schema API."""
        table_info = self.get_table_by_name(self.org.users_table)
        if not table_info:
            return []
        return sorted(field["name"] for field in table_info.get("fields", []))

    def resolve_linked_fields(self, table_name: str, fields_dict: dict) -> dict:
        """Replace linked record ID arrays with primary field display names.

        For each multipleRecordLinks field in table_name, fetches the primary
        field value of each linked record so the UI shows names instead of IDs.
        """
        table = self.get_table_by_name(table_name)
        if not table:
            return fields_dict

        linked_field_map = {}  # field_name -> linked_table_id
        for field in table.get("fields", []):
            if field.get("type") == "multipleRecordLinks" and field.get("linked_table_id"):
                linked_field_map[field["name"]] = field["linked_table_id"]

        if not linked_field_map:
            return fields_dict

        all_tables = self.get_base_tables()
        table_id_to_name = {t["id"]: t["name"] for t in all_tables}
        table_id_to_primary_field = {
            t["id"]: t["fields"][0]["name"]
            for t in all_tables
            if t.get("fields")
        }

        resolved = dict(fields_dict)
        for field_name, linked_table_id in linked_field_map.items():
            record_ids = fields_dict.get(field_name)
            if not record_ids or not isinstance(record_ids, list):
                continue

            linked_table_name = table_id_to_name.get(linked_table_id)
            if not linked_table_name:
                continue

            primary_field = table_id_to_primary_field.get(linked_table_id)
            linked_table = self.base.table(linked_table_name)

            display_names = []
            for rid in record_ids:
                try:
                    linked_rec = linked_table.get(rid)
                    linked_fields = linked_rec.get("fields", {})
                    if primary_field and primary_field in linked_fields:
                        display_names.append(str(linked_fields[primary_field]))
                    elif linked_fields:
                        display_names.append(str(next(iter(linked_fields.values()))))
                    else:
                        display_names.append(rid)
                except Exception:
                    display_names.append(rid)

            resolved[field_name] = display_names

        return resolved

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
