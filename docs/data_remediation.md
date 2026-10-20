# Lead Data Protection & Remediation Guide

## 1. Remediation Scope & Background

In initial commits (`39d7b14`), real lead contact files and generated profiles were inadvertently committed to the Git repository under:
- Root datasets: `Leads.csv`, `Leads1.csv`, `newlead.csv`
- Output directories: `output/` (144 JSON profiles, prioritized CSV, errors CSV)
- Data output directories: `data/output/` (144 JSON profiles, enriched CSV, prioritized CSV, outreach ready CSV, summary/manifest)

These files contained real full names, email addresses, LinkedIn profile URLs, company affiliations, and telephone numbers.

---

## 2. Immediate Current-Tree Actions Taken

The following immediate protective steps have been executed in the active repository tree:

1. **Untracked from Git Index**:
   Executed `git rm --cached -r output/ data/output/ Leads.csv Leads1.csv newlead.csv`.
   This ensures that no real lead datasets, individual research profiles, or output CSVs remain tracked in Git on `main`.

2. **Strict `.gitignore` Patterns**:
   Updated `.gitignore` to prevent any future tracking of uploads, batches, exports, or CSV files:
   ```gitignore
   data/batches/
   data/uploads/
   data/output/
   data/input/
   output/
   *.csv
   *.xlsx
   *.xls
   !tests/fixtures/*.csv
   ```

3. **Isolated Test Fixtures**:
   All tests in `tests/` (`test_importer.py`, `test_v2_pipeline.py`, `test_identity.py`, etc.) utilize synthetic/mocked personas (e.g., "Alice Smith", "Apex AI", "CyberShield") created in-memory or in mock fixtures. No automated test or CI check depends on real lead data.

4. **Credential Audit**:
   Audited codebase for accidentally committed secrets, tokens, or private keys. No credentials, API tokens, or secrets were found in tracked files.

---

## 3. Recommended Git History Remediation for Maintainers

Because Git retains previous commit snapshots, historical commits (`39d7b14` through `2db00bb`) still contain past revisions of the untracked files in Git object history.

> [!CAUTION]
> Rewriting historical commits changes commit SHAs and requires a forced push (`git push --force`). This must only be run by the repository owner with team coordination.

### Step-by-Step History Cleanup (Using `git-filter-repo` or BFG)

#### Option A: Using `git-filter-repo` (Recommended by Git)

1. **Install tool**:
   ```bash
   pip install git-filter-repo
   ```

2. **Clone a fresh backup**:
   ```bash
   git clone --bare https://github.com/Patel-Menil/LeadDetailsScraper.git repo-backup.git
   ```

3. **Purge sensitive paths from all history**:
   ```bash
   git filter-repo --invert-paths \
     --path Leads.csv \
     --path Leads1.csv \
     --path newlead.csv \
     --path-glob "output/*" \
     --path-glob "data/output/*"
   ```

4. **Force-push cleaned history to remote**:
   ```bash
   git remote add origin https://github.com/Patel-Menil/LeadDetailsScraper.git
   git push origin --force --all
   git push origin --force --tags
   ```

#### Option B: Using BFG Repo-Cleaner

1. **Download BFG**:
   ```bash
   java -jar bfg.jar --delete-files "{Leads.csv,Leads1.csv,newlead.csv}"
   java -jar bfg.jar --delete-folders "{output,data/output}"
   git reflog expire --expire=now --all && git gc --prune=now --aggressive
   git push origin --force --all
   ```

---

## 4. Remediation Verification Checklist

- [x] All real CSV and JSON profile datasets untracked from active Git tree.
- [x] `.gitignore` updated to block all CSV, XLSX, `data/output`, `data/input`, and `output` files.
- [x] Test suite decoupled from real data (uses synthetic fixtures).
- [x] Codebase audited for credentials, tokens, and private keys.
- [x] History cleanup procedure documented for repository maintainers.
