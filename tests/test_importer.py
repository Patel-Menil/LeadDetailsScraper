"""Tests for CSV/XLSX importer, normalization, and deduplication."""

import io
import pytest
from pathlib import Path
from src.lead_research.importer import (
    LeadImporter,
    detect_column_mapping,
    generate_lead_id,
    normalize_header,
    normalize_url,
)


def test_normalize_header_and_url():
    assert normalize_header("Full Name") == "full name"
    assert normalize_header("company_name ") == "company name"
    assert normalize_header("E-Mail") == "e mail"

    assert normalize_url("https://www.linkedin.com/in/john-doe/") == "linkedin.com/in/john-doe"
    assert normalize_url("http://acme.ai/") == "acme.ai"


def test_generate_lead_id_stability():
    id1 = generate_lead_id("alice@corp.com", "", "Alice Smith", "Corp")
    id2 = generate_lead_id("ALICE@corp.com ", "", "Alice", "Corp")
    assert id1 == id2
    assert id1.startswith("lead_")

    id3 = generate_lead_id("", "https://linkedin.com/in/bob", "Bob Jones", "Tech")
    id4 = generate_lead_id("", "http://www.linkedin.com/in/bob/", "Bob Jones", "Tech")
    assert id3 == id4


def test_column_mapping_detection():
    headers = ["Full Name", "Job Title", "Company Name", "Industry", "Email", "Company Website", "Linkedin Url"]
    mapping = detect_column_mapping(headers)
    assert mapping["name"] == "Full Name"
    assert mapping["job_title"] == "Job Title"
    assert mapping["company"] == "Company Name"
    assert mapping["professional_email"] == "Email"
    assert mapping["company_website"] == "Company Website"
    assert mapping["linkedin_url"] == "Linkedin Url"


def test_csv_import_with_duplicates_and_malformed():
    csv_content = """Name,Job Title,Company,Email,Linkedin Url
Alice Smith,Head of AI,Apex AI,alice@apex.ai,https://linkedin.com/in/alicesmith
Bob Jones,CTO,CyberShield,bob@cybershield.com,
Alice Duplicate,Director,Apex AI,alice@apex.ai,
,,,
Charlie Brown,VP Engineering,FinCloud,charlie@fincloud.com,
"""
    importer = LeadImporter()
    leads, summary = importer.import_leads(csv_content.encode("utf-8"), filename="test.csv")

    assert len(leads) == 3
    assert summary.total_input_rows == 5
    assert summary.valid_leads == 3
    assert summary.duplicate_records == 1
    assert summary.malformed_rows == 1

    # Check lead IDs
    assert leads[0].name == "Alice Smith"
    assert leads[1].name == "Bob Jones"
    assert leads[2].name == "Charlie Brown"


def test_xlsx_import(tmp_path: Path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Title", "Company", "Email"])
    ws.append(["Diana Prince", "CISO", "SecureGate", "diana@securegate.io"])
    ws.append(["Bruce Wayne", "CEO", "WayneTech", "bruce@waynetech.com"])

    excel_file = tmp_path / "leads.xlsx"
    wb.save(excel_file)

    importer = LeadImporter()
    leads, summary = importer.import_leads(excel_file, filename="leads.xlsx")

    assert len(leads) == 2
    assert leads[0].name == "Diana Prince"
    assert leads[0].company == "SecureGate"
    assert leads[1].name == "Bruce Wayne"
