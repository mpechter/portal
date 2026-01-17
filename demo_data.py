"""Mock data and client for demo mode testing."""

from datetime import datetime, timezone

# In-memory mock data for demo mode
DEMO_USERS = {
    "user_001": {
        "id": "user_001",
        "fields": {
            "Email": "parent@example.com",
            "Name": "Jane Smith",
            "Phone": "555-111-2222",
            "Address": "123 Main St, Anytown, USA",
            "Preferred Contact": "Email",
            "Login Code": "",
            "Code Expires": None,
        },
    },
    "user_002": {
        "id": "user_002",
        "fields": {
            "Email": "dad@example.com",
            "Name": "John Doe",
            "Phone": "555-333-4444",
            "Address": "456 Oak Ave, Somewhere, USA",
            "Preferred Contact": "Phone",
            "Login Code": "",
            "Code Expires": None,
        },
    },
}

# Mock table schema for demo mode
DEMO_TABLES = [
    {
        "id": "tbl_users",
        "name": "Parents",
        "fields": [
            {"id": "fld_email", "name": "Email", "type": "email"},
            {"id": "fld_name", "name": "Name", "type": "singleLineText"},
            {"id": "fld_phone", "name": "Phone", "type": "phoneNumber"},
            {"id": "fld_address", "name": "Address", "type": "singleLineText"},
            {"id": "fld_pref", "name": "Preferred Contact", "type": "singleSelect", "options": ["Email", "Phone", "Text"]},
            {"id": "fld_students", "name": "Students", "type": "multipleRecordLinks", "linked_table_id": "tbl_students"},
        ],
        "linked_fields": [
            {"id": "fld_students", "name": "Students", "type": "multipleRecordLinks", "linked_table_id": "tbl_students"},
        ],
    },
    {
        "id": "tbl_students",
        "name": "Students",
        "fields": [
            {"id": "fld_sname", "name": "Name", "type": "singleLineText"},
            {"id": "fld_grade", "name": "Grade", "type": "singleSelect", "options": ["Kindergarten", "1st Grade", "2nd Grade", "3rd Grade", "4th Grade", "5th Grade", "6th Grade"]},
            {"id": "fld_cphone", "name": "Contact Phone", "type": "phoneNumber"},
            {"id": "fld_medical", "name": "Medical Notes", "type": "multilineText"},
            {"id": "fld_emergency", "name": "Emergency Contact", "type": "singleLineText"},
            {"id": "fld_photo", "name": "Photo Permission", "type": "checkbox"},
            {"id": "fld_verified", "name": "Last Verified", "type": "date"},
            {"id": "fld_parent", "name": "User", "type": "multipleRecordLinks", "linked_table_id": "tbl_users"},
        ],
        "linked_fields": [
            {"id": "fld_parent", "name": "User", "type": "multipleRecordLinks", "linked_table_id": "tbl_users"},
        ],
    },
    {
        "id": "tbl_classes",
        "name": "Classes",
        "fields": [
            {"id": "fld_cname", "name": "Class Name", "type": "singleLineText"},
            {"id": "fld_teacher", "name": "Teacher", "type": "singleLineText"},
            {"id": "fld_room", "name": "Room", "type": "singleLineText"},
        ],
        "linked_fields": [],
    },
]

DEMO_RECORDS = {
    "rec_001": {
        "id": "rec_001",
        "fields": {
            "Name": "Emily Smith",
            "User": ["user_001"],
            "Grade": "5th Grade",
            "Contact Phone": "555-123-4567",
            "Medical Notes": "No known allergies",
            "Emergency Contact": "Grandma: 555-987-6543",
            "Photo Permission": True,
        },
    },
    "rec_002": {
        "id": "rec_002",
        "fields": {
            "Name": "Tommy Smith",
            "User": ["user_001"],
            "Grade": "3rd Grade",
            "Contact Phone": "555-123-4567",
            "Medical Notes": "Peanut allergy - carries EpiPen",
            "Emergency Contact": "Grandma: 555-987-6543",
            "Photo Permission": True,
        },
    },
    "rec_003": {
        "id": "rec_003",
        "fields": {
            "Name": "Sarah Doe",
            "User": ["user_002"],
            "Grade": "4th Grade",
            "Contact Phone": "555-222-3333",
            "Medical Notes": "",
            "Emergency Contact": "",
            "Photo Permission": False,
        },
    },
}


class DemoAirtableClient:
    """Mock Airtable client that uses in-memory data for demo purposes."""

    def __init__(self, org):
        self.org = org

    def get_base_tables(self) -> list:
        """Get all tables in the demo base."""
        return DEMO_TABLES

    def get_table_by_name(self, table_name: str) -> dict | None:
        """Get a specific table's schema by name."""
        for table in DEMO_TABLES:
            if table["name"] == table_name:
                return table
        return None

    def get_field_metadata(self, table_name: str, field_names: list) -> dict:
        """Get field metadata (type, options) for specified fields in a table."""
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
        email = email.lower()
        for user in DEMO_USERS.values():
            if user["fields"]["Email"].lower() == email:
                return user
        return None

    def get_user_by_id(self, record_id: str) -> dict | None:
        return DEMO_USERS.get(record_id)

    def save_login_code(self, user_id: str, code: str, expires: datetime):
        if user_id in DEMO_USERS:
            DEMO_USERS[user_id]["fields"]["Login Code"] = code
            DEMO_USERS[user_id]["fields"]["Code Expires"] = expires.isoformat()

    def clear_login_code(self, user_id: str):
        if user_id in DEMO_USERS:
            DEMO_USERS[user_id]["fields"]["Login Code"] = ""
            DEMO_USERS[user_id]["fields"]["Code Expires"] = None

    def get_records_for_user(self, user_id: str) -> list:
        records = []
        for record in DEMO_RECORDS.values():
            if user_id in record["fields"].get("User", []):
                records.append(record)
        return records

    def get_record_by_id(self, record_id: str) -> dict | None:
        return DEMO_RECORDS.get(record_id)

    def update_record(self, record_id: str, fields: dict):
        if record_id in DEMO_RECORDS:
            DEMO_RECORDS[record_id]["fields"].update(fields)

    def can_user_access_record(self, user_id: str, record_id: str) -> bool:
        record = self.get_record_by_id(record_id)
        if not record:
            return False
        user_ids = record.get("fields", {}).get("User", [])
        return user_id in user_ids

    def get_all_record_fields(self) -> list:
        """Get all field names from the demo Records."""
        field_names = set()
        for record in DEMO_RECORDS.values():
            field_names.update(record.get("fields", {}).keys())
        field_names.discard("User")
        return sorted(field_names)

    def get_all_user_fields(self) -> list:
        """Get all field names from the demo Users."""
        field_names = set()
        for user in DEMO_USERS.values():
            field_names.update(user.get("fields", {}).keys())
        # Remove system/auth fields that shouldn't be shown to users
        system_fields = {"Login Code", "Code Expires", "Email"}
        field_names -= system_fields
        return sorted(field_names)

    def update_user(self, user_id: str, fields: dict):
        """Update a user record with the provided fields."""
        if user_id in DEMO_USERS:
            DEMO_USERS[user_id]["fields"].update(fields)
