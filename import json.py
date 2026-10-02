import json
import re
import zipfile
from pathlib import Path
from datetime import datetime
from artifact_tool import Blob, SpreadsheetFile, Workbook

INPUT_XLSX = Path("/mnt/data/Table_Design_Mapping(1).xlsx")
OUT_DIR = Path("/mnt/data/PDF52_DDR_Generated")
VALIDATION_DIR = OUT_DIR / "Validation_PDF52_DDR"
OUT_DIR.mkdir(parents=True, exist_ok=True)
VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

# Read the uploaded mapping workbook with artifact_tool.
source_wb = SpreadsheetFile.import_xlsx(Blob.load(str(INPUT_XLSX)))

# Read ALL TABLE in bounded chunks to avoid truncated inspection output.
all_rows = []
for start, end in [(1, 40), (41, 80), (81, 122)]:
    inspected = source_wb.inspect({
        "kind": "table",
        "range": f"ALL TABLE!A{start}:AL{end}",
        "include": "values",
        "table_max_rows": 100,
        "table_max_cols": 38,
    })
    all_rows.extend(json.loads(inspected.ndjson)["values"])

# Extract dataset sections: marker row, column row, sample row.
datasets = []
for idx, row in enumerate(all_rows):
    first = row[0] if row else None
    if isinstance(first, str):
        match = re.match(r"df\d+:\s*(\S+)", first.strip())
        if match and idx + 1 < len(all_rows):
            table_name = match.group(1)
            columns = [value for value in all_rows[idx + 1] if value is not None]
            sample = all_rows[idx + 2][:len(columns)] if idx + 2 < len(all_rows) else [None] * len(columns)
            datasets.append({
                "table_name": table_name,
                "is_master": table_name.endswith("_master"),
                "columns": columns,
                "sample": sample,
            })

if len(datasets) != 20:
    raise RuntimeError(f"Expected 20 datasets from mapping, found {len(datasets)}")

def infer_sql_type(column: str, sample):
    col = column.lower()

    date_like = {
        "report_date", "date", "date_arrival", "depart",
        "created_date", "start_date", "end_date"
    }
    time_like = {"start_time", "end_time"}

    if col in date_like or col.endswith("_date"):
        return ("datetime", None)
    if col in time_like or col.endswith("_time"):
        return ("varchar", 20)
    if isinstance(sample, (int, float)) and not isinstance(sample, bool):
        return ("numeric", "(18,6)")
    if any(token in col for token in [
        "depth", "qty", "total", "cum_", "weight", "temp", "bbl", "hr",
        "rop", "incl", "azm", "tfa", "wob", "rpm", "flow", "spp", "lbf",
        "ppm", "percent", "volts", "receive", "used", "stock", "wave_",
        "wind_", "current_", "mbar", "kip", "on_loc", "interval", "duration"
    ]):
        return ("numeric", "(18,6)")
    if col in {"bit_run", "bha_run", "rpt_no", "seq"}:
        return ("int", None)
    if any(token in col for token in ["comment", "summary", "remark", "operation", "accidents", "safety_drills", "bha"]):
        return ("varchar", 4000)
    if col in {"file_name"}:
        return ("varchar", 500)
    if col in {"task_id"}:
        return ("varchar", 128)
    if col in {"run_id"}:
        return ("varchar", 20)
    if col in {"unit", "method", "code"}:
        return ("varchar", 100)
    return ("varchar", 500)

# Enrich datasets with ETL columns and inferred structures.
for dataset in datasets:
    business_cols = []
    for col, sample in zip(dataset["columns"], dataset["sample"]):
        sql_type, length = infer_sql_type(col, sample)
        business_cols.append({
            "name": col,
            "sql_type": sql_type,
            "length": length,
            "sample": sample,
        })

    if dataset["is_master"]:
        etl_cols = [
            {"name": "task_id", "sql_type": "varchar", "length": 128, "nullable": False, "pk": True},
            {"name": "file_name", "sql_type": "varchar", "length": 500, "nullable": False, "pk": True},
            {"name": "version", "sql_type": "int", "length": None, "nullable": False, "pk": False},
        ]
        # report_date is already supplied by the mapping.
        final_business = business_cols
        etl_tail = [
            {"name": "created_date", "sql_type": "datetime", "length": None, "nullable": False, "pk": False,
             "default": "'9999-01-31'"},
            {"name": "run_id", "sql_type": "varchar", "length": 20, "nullable": False, "pk": False,
             "default": "'999999999999'"},
        ]
        pk_cols = ["task_id", "file_name", "report_date"]
    else:
        etl_cols = [
            {"name": "task_id", "sql_type": "varchar", "length": 128, "nullable": False, "pk": True},
            {"name": "file_name", "sql_type": "varchar", "length": 500, "nullable": False, "pk": True},
            {"name": "seq", "sql_type": "int", "length": None, "nullable": False, "pk": True},
        ]
        final_business = business_cols
        etl_tail = [
            {"name": "run_id", "sql_type": "varchar", "length": 20, "nullable": False, "pk": False,
             "default": "'999999999999'"},
        ]
        pk_cols = ["task_id", "file_name", "seq"]

    final_cols = etl_cols[:]
    for col in final_business:
        final_cols.append({
            **col,
            "nullable": False if (dataset["is_master"] and col["name"] == "report_date") else True,
            "pk": dataset["is_master"] and col["name"] == "report_date",
        })
    final_cols.extend(etl_tail)

    dataset["final_columns"] = final_cols
    dataset["pk_cols"] = pk_cols

# 1) Document config draft.
dataset_names = [d["table_name"] for d in datasets]
document_config = {
    "Name": "PDF52_DDR",
    "SourceType": "Email",
    "FileType": "PDF",
    "Classify": {
        "FileNamePattern": [
            ".*(?:Daily[_ -]?Drilling[_ -]?Report|DDR).*\\.pdf$"
        ]
    },
    "PDFExtraction": {
        "ModelID": "prebuilt-layout"
    },
    "DatasetList": dataset_names,
    "SinkSecretName": "JVETL-DBConnectionString",
    "VersionKey": ["report_date"]
}
config_path = OUT_DIR / "document_config_append_pdf52_ddr.json"
config_path.write_text(json.dumps(document_config, indent=4, ensure_ascii=False), encoding="utf-8")

# 2) Validation JSON files.
defs = {
    "nullable_number": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    "nullable_string": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    "nullable": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}]},
}

def json_type_for_sql(sql_type: str, nullable: bool):
    if sql_type in {"int", "numeric", "decimal", "float", "bigint"}:
        return {"$ref": "#/$defs/nullable_number"} if nullable else {"type": "number"}
    return {"$ref": "#/$defs/nullable_string"} if nullable else {"type": "string"}

for dataset in datasets:
    properties = {}
    required = []
    checknull = {}

    for col in dataset["final_columns"]:
        name = col["name"]
        nullable = bool(col.get("nullable", True))
        properties[name] = json_type_for_sql(col["sql_type"], nullable)
        if not nullable:
            required.append(name)
            checknull[name] = 0
        else:
            checknull[name] = 99

    schema = {
        "$defs": defs,
        "type": "array",
        "minItems": 0,
        "items": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }

    schema_file = VALIDATION_DIR / f"schema_{dataset['table_name']}.json"
    checknull_file = VALIDATION_DIR / f"checknull_{dataset['table_name']}.json"
    schema_file.write_text(json.dumps(schema, indent=4, ensure_ascii=False), encoding="utf-8")
    checknull_file.write_text(json.dumps(checknull, indent=4, ensure_ascii=False), encoding="utf-8")

# 3) Create-table SQL.
def sql_decl(col):
    sql_type = col["sql_type"]
    length = col.get("length")
    if sql_type in {"varchar", "nvarchar"}:
        declaration = f"{sql_type}({length})"
    elif sql_type in {"numeric", "decimal"}:
        declaration = f"{sql_type}{length or '(18,6)'}"
    else:
        declaration = sql_type

    default = f" DEFAULT {col['default']}" if col.get("default") else ""
    nullability = "NULL" if col.get("nullable", True) else "NOT NULL"
    return f"    [{col['name']}] {declaration}{default} {nullability}"

sql_lines = [
    "/*",
    "Generated from Table_Design_Mapping(1).xlsx / sheet ALL TABLE.",
    "Draft assumptions:",
    "- Database: JVETL-DB-01",
    "- Schema: dbo",
    "- Transaction tables use seq in the primary key because several datasets contain multiple rows per file.",
    "- Business columns are nullable unless they are part of the master version key.",
    "- Data types are inferred from column names and sample values and should be reviewed before deployment.",
    "*/",
    "",
]

for dataset in datasets:
    table = dataset["table_name"]
    sql_lines.append(f"-- DROP TABLE [JVETL-DB-01].[dbo].[{table}];")
    sql_lines.append(f"CREATE TABLE [JVETL-DB-01].[dbo].[{table}] (")
    declarations = [sql_decl(c) for c in dataset["final_columns"]]
    constraint = (
        f"    CONSTRAINT [pk_{table}] PRIMARY KEY "
        f"({', '.join(f'[{c}]' for c in dataset['pk_cols'])})"
    )
    sql_lines.append(",\n".join(declarations + [constraint]))
    sql_lines.append(");")
    sql_lines.append("GO")
    sql_lines.append("")

sql_path = OUT_DIR / "create_tables_pdf52_ddr.sql"
sql_path.write_text("\n".join(sql_lines), encoding="utf-8")

# Assumptions/readme.
readme = """PDF52 DDR generated package

Source
- Table_Design_Mapping(1).xlsx, sheet ALL TABLE
- 20 datasets detected: 1 master and 19 transaction datasets

Draft values that require confirmation
1. Document Name: PDF52_DDR
2. FileNamePattern: .* (Daily Drilling Report or DDR) *.pdf
3. ModelID: prebuilt-layout
4. SinkSecretName: JVETL-DBConnectionString
5. VersionKey: report_date
6. Database in SQL: JVETL-DB-01

Design rules used
- Master ETL columns: task_id, file_name, version, created_date, run_id
- Master PK: task_id, file_name, report_date
- Transaction ETL columns: task_id, file_name, seq, run_id
- Transaction PK: task_id, file_name, seq
- PK/ETL/version-key fields are required and checknull=0
- Other business fields are nullable and checknull=99
- SQL data types are inferred from sample data and column names

Please confirm the six draft values and any mandatory business columns before production deployment.
"""
readme_path = OUT_DIR / "README_assumptions.txt"
readme_path.write_text(readme, encoding="utf-8")

# 4) Reusable Excel input template.
template_wb = Workbook.create()
doc_sheet = template_wb.worksheets.add("Document")
datasets_sheet = template_wb.worksheets.add("Datasets")
columns_sheet = template_wb.worksheets.add("Columns")
rules_sheet = template_wb.worksheets.add("Validation Rules")
instructions_sheet = template_wb.worksheets.add("Instructions")

header_fmt = {
    "fill": "#1F4E78",
    "font": {"bold": True, "color": "#FFFFFF"},
    "horizontal_alignment": "center",
    "vertical_alignment": "center",
}
section_fmt = {
    "fill": "#D9EAF7",
    "font": {"bold": True},
}

doc_rows = [
    ["Field", "Value", "Required", "Description / Example"],
    ["Name", "PDF52_DDR", "Yes", "Document Type; maps to class/function naming"],
    ["SourceType", "Email", "Yes", "Default: Email"],
    ["FileType", "PDF", "Yes", "PDF / Excel / RTF"],
    ["FileNamePattern", ".*(?:Daily[_ -]?Drilling[_ -]?Report|DDR).*\\.pdf$", "Yes", "One regex per row or pipe-delimited"],
    ["ModelID", "prebuilt-layout", "PDF only", "Azure AI Document Intelligence model"],
    ["ConfigTemplate", "", "Excel only", "Example: Config/Excel/document_name.json"],
    ["SinkSecretName", "JVETL-DBConnectionString", "Yes", "JVETL / CorpOpETL / SubsurfaceETL"],
    ["VersionKey", "report_date", "Yes", "Comma-separated master columns"],
    ["DatabaseName", "JVETL-DB-01", "Yes", "Used in CREATE TABLE script"],
    ["SchemaName", "dbo", "Yes", "Default: dbo"],
]
doc_sheet.get_range(f"A1:D{len(doc_rows)}").values = doc_rows
doc_sheet.get_range("A1:D1").format = header_fmt
doc_sheet.freeze_panes.freeze_rows(1)
doc_sheet.get_range("A1:D20").format.wrap_text = True
doc_sheet.get_range("A:D").format.column_width = 25
doc_sheet.get_range("D:D").format.column_width = 48

dataset_rows = [["DatasetName", "DatasetType", "IncludeSeq", "PrimaryKeyOverride", "Notes"]]
for d in datasets:
    dataset_rows.append([
        d["table_name"],
        "Master" if d["is_master"] else "Transaction",
        "No" if d["is_master"] else "Yes",
        ",".join(d["pk_cols"]),
        "",
    ])
datasets_sheet.get_range(f"A1:E{len(dataset_rows)}").values = dataset_rows
datasets_sheet.get_range("A1:E1").format = header_fmt
datasets_sheet.freeze_panes.freeze_rows(1)
datasets_sheet.get_range("A:E").format.column_width = 26

column_rows = [[
    "DatasetName", "ColumnName", "SQLType", "Length/Precision",
    "Nullable", "PrimaryKey", "DefaultValue", "JSONType",
    "CheckNull", "SampleValue", "Description"
]]
for d in datasets:
    for col in d["final_columns"]:
        sql_type = col["sql_type"]
        nullable = bool(col.get("nullable", True))
        json_type = "number" if sql_type in {"int", "numeric", "decimal", "float", "bigint"} else "string"
        column_rows.append([
            d["table_name"],
            col["name"],
            sql_type,
            col.get("length") or "",
            "Yes" if nullable else "No",
            "Yes" if col["name"] in d["pk_cols"] else "No",
            col.get("default", ""),
            json_type,
            99 if nullable else 0,
            "" if col.get("sample") is None else str(col.get("sample")),
            "",
        ])
columns_sheet.get_range(f"A1:K{len(column_rows)}").values = column_rows
columns_sheet.get_range("A1:K1").format = header_fmt
columns_sheet.freeze_panes.freeze_rows(1)
columns_sheet.get_range("A:K").format.column_width = 18
columns_sheet.get_range("A:A").format.column_width = 38
columns_sheet.get_range("B:B").format.column_width = 34
columns_sheet.get_range("J:K").format.column_width = 28
columns_sheet.get_range(f"E2:E{len(column_rows)}").data_validation = {
    "rule": {"type": "list", "values": ["Yes", "No"]}
}
columns_sheet.get_range(f"F2:F{len(column_rows)}").data_validation = {
    "rule": {"type": "list", "values": ["Yes", "No"]}
}
columns_sheet.get_range(f"C2:C{len(column_rows)}").data_validation = {
    "rule": {"type": "list", "values": ["varchar", "nvarchar", "int", "bigint", "numeric", "decimal", "float", "date", "datetime"]}
}
columns_sheet.get_range(f"H2:H{len(column_rows)}").data_validation = {
    "rule": {"type": "list", "values": ["string", "number", "boolean"]}
}

rules_rows = [
    ["Rule", "Recommended Default", "Explanation"],
    ["Master count", "Exactly 1", "Each document should have one _master dataset"],
    ["Master ETL columns", "task_id,file_name,version,created_date,run_id", "report_date comes from mapping/business columns"],
    ["Transaction ETL columns", "task_id,file_name,seq,run_id", "Use seq where the dataset can contain multiple rows"],
    ["Master PK", "task_id,file_name,VersionKey", "Example: task_id,file_name,report_date"],
    ["Transaction PK", "task_id,file_name,seq", "Override only when the program guarantees one row per file"],
    ["Required JSON fields", "All NOT NULL columns", "Also reflected by checknull=0"],
    ["Optional JSON fields", "Nullable columns", "checknull=99"],
    ["Additional properties", "false", "Reject unexpected extraction columns"],
]
rules_sheet.get_range(f"A1:C{len(rules_rows)}").values = rules_rows
rules_sheet.get_range("A1:C1").format = header_fmt
rules_sheet.get_range("A:C").format.column_width = 35
rules_sheet.get_range("C:C").format.column_width = 60
rules_sheet.get_range("A1:C20").format.wrap_text = True

instructions_rows = [
    ["How to use this template"],
    ["1. Fill the Document sheet first, especially Name, FileNamePattern, ModelID/ConfigTemplate, database and VersionKey."],
    ["2. Add one row per output dataset in Datasets. Mark exactly one dataset as Master."],
    ["3. Add all business and ETL columns in Columns. Use one row per column."],
    ["4. Set Nullable, PrimaryKey, JSONType and CheckNull explicitly; do not rely only on inference."],
    ["5. Include sample values because they improve SQL type and JSON type generation."],
    ["6. For transaction datasets with multiple rows, include seq and use it in the primary key."],
    ["7. Ensure DatasetName exactly matches the Python datasets dictionary key and database table name."],
    ["8. Ensure VersionKey columns exist in the master dataset."],
    [""],
    ["Naming recommendation"],
    ["Use 'Extraction' as the parent object and 'PDFExtraction'/'ExcelExtraction' as format-specific configuration blocks."],
    ["For 'FileNamePattern', the term 'classification criterion' or 'classifier rule' is clearer than sub-schema in documentation."],
]
instructions_sheet.get_range(f"A1:A{len(instructions_rows)}").values = instructions_rows
instructions_sheet.get_range("A1").format = header_fmt
instructions_sheet.get_range("A:A").format.column_width = 110
instructions_sheet.get_range(f"A1:A{len(instructions_rows)}").format.wrap_text = True

template_path = OUT_DIR / "Document_Onboarding_Input_Template.xlsx"
SpreadsheetFile.export_xlsx(template_wb).save(str(template_path))

# Compact verification.
verification = {
    "datasets": len(datasets),
    "master": sum(1 for d in datasets if d["is_master"]),
    "validation_files": len(list(VALIDATION_DIR.glob("*.json"))),
    "sql_tables": sum(1 for line in sql_lines if line.startswith("CREATE TABLE")),
}
if verification != {"datasets": 20, "master": 1, "validation_files": 40, "sql_tables": 20}:
    raise RuntimeError(f"Verification failed: {verification}")

# Package everything.
zip_path = Path("/mnt/data/PDF52_DDR_Generated_Package.zip")
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for file_path in OUT_DIR.rglob("*"):
        if file_path.is_file():
            zf.write(file_path, file_path.relative_to(OUT_DIR.parent))

print("Created:", zip_path)
print("Config:", config_path)
print("SQL:", sql_path)
print("Template:", template_path)
print("Validation JSON files:", verification["validation_files"])
