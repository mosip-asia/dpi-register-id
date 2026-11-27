"""Step 3: build the SQL that loads MOSIP's identity schema into masterdata (mosip_master.identity_schema).

Source: github.com/mosip/mosip-data tag v1.2.0.1, mosip_master/xlsx/identity_schema.xlsx (downloaded by 01-download.sh).
That default schema requires proof documents and biometrics. The Sandbox Kit pins a schema whose required
list is the 16 demographic fields in register-id's fixture, so by default the `required` list is replaced
with that one. Pass --mosip-default to keep MOSIP's own required list.

Usage (from the register-id folder):
    uv run --with openpyxl python tools/real-idrepo/03-identity-schema.py [--mosip-default]
Writes seed/identity_schema.sql next to this script.
"""

import json
import sys
from pathlib import Path

import openpyxl

here = Path(__file__).resolve().parent
kit_fixture = Path("src/register_id/tests/fixtures/identity-required.json")

wb = openpyxl.load_workbook(here / "seed" / "identity_schema.xlsx")
rows = list(wb.active.iter_rows(values_only=True))
row = dict(zip(rows[0], rows[1]))
schema = json.loads(row["schema_json"])

if "--mosip-default" not in sys.argv:
    required = json.loads(kit_fixture.read_text(encoding="utf-8"))
    schema["properties"]["identity"]["required"] = required
    print("required = Kit list:", ", ".join(required))
else:
    print("required = MOSIP default:", ", ".join(schema["properties"]["identity"]["required"]))


# IDRepo asks masterdata for the schema whose version equals the request's IDSchemaVersion.
# register-id sends the Kit's version (identity_schema.SCHEMA_VERSION), so the local row uses it too.
version_line = next(
    line for line in Path("src/register_id/identity_schema.py").read_text(encoding="utf-8").splitlines()
    if line.startswith("SCHEMA_VERSION")
)
schema_version = float(version_line.split("=")[1].strip())
print(f"id_version = {schema_version} (register-id SCHEMA_VERSION; MOSIP seed has {row['id_version']})")
row["id_version"] = schema_version


def q(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


sql = (
    "DELETE FROM master.identity_schema;\n"
    "INSERT INTO master.identity_schema (id, id_version, title, description, schema_json, status_code, add_props,"
    " effective_from, lang_code, is_active, cr_by, cr_dtimes) VALUES ("
    f"{q(row['id'])}, {row['id_version']}, {q(row['title'])}, {q(row['description'])}, "
    f"{q(json.dumps(schema))}, {q(row['status_code'])}, {str(bool(row['add_props'])).lower()}, now(), "
    f"{q(row['lang_code'] or 'eng')}, true, 'local-setup', now());\n"
)
out = here / "seed" / "identity_schema.sql"
out.write_text(sql, encoding="utf-8")
print("wrote", out)
