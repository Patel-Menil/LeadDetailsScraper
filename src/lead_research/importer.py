"""CSV and Excel lead list importer with validation, normalization, and deduplication."""

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .schemas import ImportSummary, LeadInput


STANDARD_COLUMN_KEYS = {
    "name": ["name", "full name", "lead name", "contact name", "person", "full_name"],
    "first_name": ["first name", "firstname", "first_name", "given name"],
    "last_name": ["last name", "lastname", "last_name", "surname"],
    "job_title": ["job title", "job_title", "title", "position", "role"],
    "company": ["company", "company name", "company_name", "organization", "account name"],
    "industry": ["industry", "vertical", "sector", "domain"],
    "linkedin_url": ["linkedin url", "linkedin", "linkedin_url", "person linkedin url", "profile url", "profile_url"],
    "company_website": ["company website", "company_website", "website", "company domain", "domain", "url"],
    "professional_email": ["professional email", "email", "email address", "work email", "contact email", "e-mail"],
    "city": ["city", "person city", "location city"],
    "state": ["state", "province", "region", "person state"],
    "country": ["country", "nation", "person country"],
}


def normalize_header(header: str) -> str:
    """Normalize a column header by stripping and lowercasing."""
    if not header:
        return ""
    # remove punctuation and spaces for matching
    cleaned = re.sub(r"[_\-\s]+", " ", header.strip().lower())
    return cleaned


def detect_column_mapping(headers: List[str]) -> Dict[str, str]:
    """Map detected file headers to standardized lead keys."""
    mapping: Dict[str, str] = {}
    normalized_headers = [(h, normalize_header(h)) for h in headers if h]

    # First pass: Exact match
    for std_key, aliases in STANDARD_COLUMN_KEYS.items():
        for orig, norm in normalized_headers:
            if norm in aliases:
                mapping[std_key] = orig
                break

    # Second pass: Fallback prefix/suffix matching only for unmapped keys
    for std_key, aliases in STANDARD_COLUMN_KEYS.items():
        if std_key in mapping:
            continue
        for orig, norm in normalized_headers:
            # Prevent linkedin url from matching company website
            if std_key == "company_website" and "linkedin" in norm:
                continue
            if any(norm == a or norm.startswith(a + " ") or norm.endswith(" " + a) for a in aliases if len(a) > 3):
                mapping[std_key] = orig
                break

    return mapping


def clean_str(val: Any) -> str:
    """Clean and strip a value."""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "null", "undefined") else s


def normalize_url(url: str) -> str:
    """Normalize URLs for consistent comparison."""
    u = clean_str(url)
    if not u:
        return ""
    u = u.lower().rstrip("/")
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u


def generate_lead_id(email: str, linkedin_url: str, name: str, company: str) -> str:
    """Generate a stable, deterministic lead ID based on identifiers."""
    norm_email = clean_str(email).lower()
    norm_li = normalize_url(linkedin_url)
    norm_name = clean_str(name).lower()
    norm_comp = clean_str(company).lower()

    if norm_email:
        seed = f"email:{norm_email}"
    elif norm_li:
        seed = f"linkedin:{norm_li}"
    elif norm_name and norm_comp:
        seed = f"name_comp:{norm_name}::{norm_comp}"
    elif norm_name:
        seed = f"name:{norm_name}"
    else:
        seed = f"raw:{hashlib.md5(f'{norm_name}:{norm_comp}:{norm_email}'.encode()).hexdigest()}"

    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"lead_{h}"


class LeadImporter:
    """Imports, validates, and normalizes leads from CSV and XLSX files."""

    def __init__(self, custom_mapping: Optional[Dict[str, str]] = None):
        self.custom_mapping = custom_mapping or {}

    def read_file_rows(self, file_path_or_bytes: Union[str, Path, bytes], filename: str = "") -> Tuple[List[str], List[Dict[str, Any]]]:
        """Read raw rows and headers from either a CSV or XLSX source."""
        fn = str(filename or file_path_or_bytes).lower()
        is_excel = fn.endswith(".xlsx") or fn.endswith(".xls")

        if is_excel:
            return self._read_excel(file_path_or_bytes)
        else:
            return self._read_csv(file_path_or_bytes)

    def _read_csv(self, source: Union[str, Path, bytes]) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Read CSV data with encoding fallback."""
        if isinstance(source, (str, Path)):
            with open(source, "rb") as f:
                content = f.read()
        else:
            content = source

        # Try UTF-8, then UTF-8-sig, then latin-1
        text = None
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            text = content.decode("utf-8", errors="replace")

        f_io = io.StringIO(text)
        reader = csv.reader(f_io)
        try:
            raw_headers = next(reader)
        except StopIteration:
            return [], []

        headers = [clean_str(h) for h in raw_headers if clean_str(h)]
        f_io.seek(0)
        dict_reader = csv.DictReader(f_io)
        rows = list(dict_reader)
        return headers, rows

    def _read_excel(self, source: Union[str, Path, bytes]) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Read Excel data using openpyxl."""
        import openpyxl

        if isinstance(source, (str, Path)):
            wb = openpyxl.load_workbook(source, data_only=True)
        else:
            wb = openpyxl.load_workbook(io.BytesIO(source), data_only=True)

        ws = wb.active
        iter_rows = ws.iter_rows(values_only=True)
        try:
            raw_headers = next(iter_rows)
        except StopIteration:
            return [], []

        headers = [clean_str(h) for h in raw_headers if clean_str(h)]
        rows: List[Dict[str, Any]] = []
        for r_values in iter_rows:
            if not any(r_values):
                continue
            row_dict = {}
            for i, h in enumerate(headers):
                val = r_values[i] if i < len(r_values) else ""
                row_dict[h] = clean_str(val)
            rows.append(row_dict)

        return headers, rows

    def inspect_file(self, file_path_or_bytes: Union[str, Path, bytes], filename: str = "", preview_limit: int = 5) -> Dict[str, Any]:
        """Generate a quick preview of headers, mapping, and first few rows."""
        headers, rows = self.read_file_rows(file_path_or_bytes, filename)
        mapping = detect_column_mapping(headers)
        if self.custom_mapping:
            mapping.update(self.custom_mapping)

        preview_rows = rows[:preview_limit]
        return {
            "total_raw_rows": len(rows),
            "headers": headers,
            "detected_mapping": mapping,
            "preview_rows": preview_rows,
        }

    def import_leads(
        self,
        file_path_or_bytes: Union[str, Path, bytes],
        filename: str = "",
        mapping_override: Optional[Dict[str, str]] = None,
        max_leads: Optional[int] = None,
    ) -> Tuple[List[LeadInput], ImportSummary]:
        """Import, validate, deduplicate, and normalize lead records."""
        headers, raw_rows = self.read_file_rows(file_path_or_bytes, filename)
        mapping = detect_column_mapping(headers)
        if self.custom_mapping:
            mapping.update(self.custom_mapping)
        if mapping_override:
            mapping.update(mapping_override)

        valid_leads: List[LeadInput] = []
        seen_lead_ids: Dict[str, int] = {}
        seen_emails: Dict[str, int] = {}
        seen_linkedin: Dict[str, int] = {}
        seen_name_company: Dict[Tuple[str, str], int] = {}

        summary = ImportSummary(
            total_input_rows=len(raw_rows),
            column_mapping=mapping,
            sample_preview=raw_rows[:5]
        )

        for row_idx, raw_row in enumerate(raw_rows, start=1):
            if max_leads and len(valid_leads) >= max_leads:
                break

            # Helper to extract using mapping
            def get_field(k: str) -> str:
                mapped_header = mapping.get(k)
                if mapped_header and mapped_header in raw_row:
                    return clean_str(raw_row[mapped_header])
                # Direct lookup if present
                for alt in STANDARD_COLUMN_KEYS.get(k, []):
                    for rh in raw_row:
                        if normalize_header(rh) == alt:
                            return clean_str(raw_row[rh])
                return ""

            name = get_field("name")
            first_name = get_field("first_name")
            last_name = get_field("last_name")

            if not name and (first_name or last_name):
                name = f"{first_name} {last_name}".strip()
            elif name and not first_name and not last_name:
                parts = name.split()
                if len(parts) == 1:
                    first_name = parts[0]
                elif len(parts) > 1:
                    first_name = parts[0]
                    last_name = " ".join(parts[1:])

            job_title = get_field("job_title")
            company = get_field("company")
            industry = get_field("industry")
            linkedin_url = get_field("linkedin_url")
            company_website = get_field("company_website")
            email = get_field("professional_email")
            city = get_field("city")
            state = get_field("state")
            country = get_field("country")

            # Check for empty / malformed row
            if not name and not email and not linkedin_url and not company:
                summary.malformed_rows += 1
                summary.validation_errors.append({
                    "row_index": row_idx,
                    "error": "Completely empty or missing identifying fields (name, email, linkedin, company)",
                    "raw_row": raw_row
                })
                continue

            # Generate stable lead ID
            lead_id = generate_lead_id(email, linkedin_url, name, company)

            # Deduplication checks
            is_dup = False
            dup_reason = ""

            norm_email = email.lower() if email else ""
            norm_li = normalize_url(linkedin_url)
            name_comp = (name.lower(), company.lower()) if (name and company) else None

            if norm_email and norm_email in seen_emails:
                is_dup = True
                dup_reason = f"Duplicate email '{norm_email}' already seen at row {seen_emails[norm_email]}"
            elif norm_li and norm_li in seen_linkedin:
                is_dup = True
                dup_reason = f"Duplicate LinkedIn URL '{norm_li}' already seen at row {seen_linkedin[norm_li]}"
            elif name_comp and name_comp in seen_name_company:
                is_dup = True
                dup_reason = f"Duplicate Name+Company '{name} at {company}' already seen at row {seen_name_company[name_comp]}"
            elif lead_id in seen_lead_ids:
                is_dup = True
                dup_reason = f"Duplicate Lead ID '{lead_id}'"

            if is_dup:
                summary.duplicate_records += 1
                summary.validation_errors.append({
                    "row_index": row_idx,
                    "error": dup_reason,
                    "lead_id": lead_id,
                    "type": "duplicate"
                })
                continue

            # Record seen keys
            seen_lead_ids[lead_id] = row_idx
            if norm_email:
                seen_emails[norm_email] = row_idx
            if norm_li:
                seen_linkedin[norm_li] = row_idx
            if name_comp:
                seen_name_company[name_comp] = row_idx

            lead = LeadInput(
                lead_id=lead_id,
                name=name or "Unknown Lead",
                first_name=first_name,
                last_name=last_name,
                job_title=job_title,
                company=company,
                industry=industry,
                linkedin_url=linkedin_url,
                company_website=company_website,
                professional_email=email,
                city=city,
                state=state,
                country=country,
                raw_data=dict(raw_row)
            )
            valid_leads.append(lead)

        summary.valid_leads = len(valid_leads)
        return valid_leads, summary
