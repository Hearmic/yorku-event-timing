"""Parse a saved York "View Active Course Timetables by Faculty" page into a flat CSV.

Usage:
    python parse_timetable.py FW2026LE.html meetings.csv

One output row per (section, meet, weekday). Row shapes in the source:
  * course header:  Fac | Dept | Term | Title (colspan=8)
  * first meet:     (colspan=3 blank) | "1011 3.00 E" | LOI | Type | Meet | Cat.No | [meetings] | Instructors | Notes
  * extra meet:     (colspan=5 blank) | Type | Meet | Cat.No | [meetings] | Instructors | Notes
where [meetings] is a nested table of Day | Time | Dur(min) | Campus | Room rows.
"""
import csv
import re
import sys

from bs4 import BeautifulSoup

DAY_NAMES = {"M": "Mon", "T": "Tue", "W": "Wed", "R": "Thu", "F": "Fri", "S": "Sat", "U": "Sun"}
FIELDS = [
    "fac", "dept", "term", "course", "credits", "section", "title", "loi",
    "type", "meet", "cat_no", "day", "start", "dur_min", "end", "campus",
    "building", "room", "instructors", "notes",
]


def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fmt(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        soup = BeautifulSoup(fh.read(), "lxml")

    outer = soup.find("table")
    course = {}   # current course header
    section = {}  # current section (course number, credits, section letter, LOI)
    rows = []

    for tr in outer.find("tbody").find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if not tds or tr.get("bgcolor") == "#000000":
            continue

        first_span = tds[0].get("colspan")

        if first_span is None and len(tds) == 4:  # course header
            course = {
                "fac": clean(tds[0].text), "dept": clean(tds[1].text),
                "term": clean(tds[2].text), "title": clean(tds[3].text),
            }
            continue

        if first_span == "3":  # first meet of a new section
            parts = clean(tds[1].text).split()
            section = {
                "course": parts[0] if parts else "",
                "credits": parts[1] if len(parts) > 1 else "",
                "section": parts[2] if len(parts) > 2 else "",
                "loi": clean(tds[2].text),
            }
            meet_cells = tds[3:]
        elif first_span == "5":  # additional meet (LAB/TUTR) of the same section
            meet_cells = tds[1:]
        else:
            continue

        mtype, meet_no, cat_no, sched = (clean(meet_cells[0].text), clean(meet_cells[1].text),
                                         clean(meet_cells[2].text), meet_cells[3])
        instructors = "; ".join(clean(x) for x in meet_cells[4].stripped_strings) if len(meet_cells) > 4 else ""
        notes = clean(meet_cells[5].text) if len(meet_cells) > 5 else ""

        slots = []
        inner = sched.find("table")
        if inner:
            for itr in inner.find_all("tr"):
                c = [clean(x.text) for x in itr.find_all("td")]
                if len(c) >= 5 and c[0]:
                    slots.append(c[:5])
        if not slots:  # online/async or TBA: keep one row with no time
            slots = [["", "", "", "", ""]]

        for day, start, dur, campus, room in slots:
            start_m = to_min(start) if re.fullmatch(r"\d{1,2}:\d{2}", start) else None
            dur_m = int(dur) if dur.isdigit() else None
            room_parts = room.split()
            rows.append({
                **course, **section,
                "type": mtype, "meet": meet_no, "cat_no": cat_no,
                "day": DAY_NAMES.get(day, day),
                "start": fmt(start_m) if start_m is not None else "",
                "dur_min": dur_m if dur_m is not None else "",
                "end": fmt(start_m + dur_m) if start_m is not None and dur_m else "",
                "campus": campus,
                "building": room_parts[0] if room_parts else "",
                "room": " ".join(room_parts),
                "instructors": instructors, "notes": notes,
            })
    return rows


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "FW2026LE.html"
    dst = sys.argv[2] if len(sys.argv) > 2 else "meetings.csv"
    rows = parse(src)
    with open(dst, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} meeting rows -> {dst}")
