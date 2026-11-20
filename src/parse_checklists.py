"""Parse Lassonde 2026-27 degree checklists (.xlsx) into one requirements table.

Usage:
    python parse_checklists.py <checklist_dir> requirements.csv

Each output row is one course that can satisfy a requirement slot:
  program, year, term_hint, slot, kind, course_code, credits, title
kind = "required" when the slot names one course, "choice" when it names alternatives
("LE/EECS 1012 or LE/EECS 1015"). Elective pools ("6.00 credits from ...",
"Choose four technical electives from ...") and general-education placeholders are skipped: they don't pin a student to a course.
"""
import csv
import glob
import os
import re
import sys
import warnings

import openpyxl

warnings.filterwarnings("ignore", category=UserWarning)

YEARS = {"First Year": 1, "Second Year": 2, "Third Year": 3, "Fourth Year": 4}
CODE = re.compile(r"\b[A-Z]{2}/\s?([A-Z]{2,4})\s?(\d{4}[A-Z]?)\s+(\d\.\d\d)")
def norm_term(raw):
    """Map the checklists' free-text term labels onto F / W / Y / F or W / SU / Any."""
    t = re.sub(r"\s+", " ", str(raw)).strip()
    if t in {"F", "W", "Y", "Any"}:
        return t
    if t in {"F or W", "F/W"}:
        return "F or W"
    if t in {"SU", "Summer"}:
        return "SU"
    if t.startswith("W or Summer") or t.startswith("W, SU"):
        return "W"
    if "Offered in W term only" in t:
        return "W"
    return None  # headers, "Not currently offered", notes


def program_name(ws):
    for row in ws.iter_rows(min_row=1, max_row=4, values_only=True):
        for c in row:
            if isinstance(c, str) and ("Bachelor" in c or "Honours" in c):
                return re.sub(r"\s+", " ", c).strip()
    return ""


def parse_file(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    program = program_name(ws)
    year, slot, rows, last_term, in_elective_pool = None, 0, [], "Any", False
    for raw in ws.iter_rows(values_only=True):
        cells = [c if not isinstance(c, str) else c.strip() for c in raw]
        first = next((c for c in cells if c not in (None, "")), None)
        if isinstance(first, str) and first in YEARS:
            year = YEARS[first]
            in_elective_pool = False
            continue
        if isinstance(first, str) and re.search(r"(?i)technical electives|^choose ", first):
            in_elective_pool = True  # "Choose four technical electives from ..." lists: not required
            continue
        if in_elective_pool:
            continue
        if year is None or not cells:
            continue
        if cells[0] in (None, ""):
            cells[0] = last_term  # continuation row under the same term
        else:
            t = norm_term(cells[0])
            if t is None:
                continue
            cells[0] = last_term = t
        term, code_cell = cells[0], cells[1] if len(cells) > 1 else None
        title_cell = cells[2] if len(cells) > 2 else ""
        if not isinstance(code_cell, str) or not CODE.match(code_cell.strip()):
            continue  # elective pool, gen-ed placeholder, or blank continuation row
        codes = CODE.findall(code_cell)
        titles = [t.strip() for t in re.split(r"\n\s*or\s*\n", title_cell or "")] if title_cell else []
        slot += 1
        kind = "required" if len(codes) == 1 else "choice"
        for i, (dept, num, cr) in enumerate(codes):
            rows.append({
                "program": program, "year": year, "term_hint": term, "slot": slot, "kind": kind,
                "course_code": f"{dept} {num}", "credits": cr,
                "title": titles[i] if i < len(titles) else "",
                "source": os.path.basename(path).split("-", 1)[1] if re.match(r"^[0-9a-f]{8}-", os.path.basename(path)) else os.path.basename(path),
            })
    return rows


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "checklists"
    dst = sys.argv[2] if len(sys.argv) > 2 else "requirements.csv"
    rows = []
    for f in sorted(glob.glob(os.path.join(src, "*.xlsx"))):
        if "Winter-Start" in f:
            continue  # same courses as the regular first-year checklist, shifted a term
        rows += parse_file(f)
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows, {len({r['program'] for r in rows})} programs -> {dst}")
