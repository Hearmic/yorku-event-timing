"""Schedule model: from degree requirements + timetable to "when is a cohort in class / on campus".

All functions work on two tables:
  meetings      one row per section-meet-day (york_fw2026_meetings.csv)
  requirements  one row per course that can satisfy a requirement slot (requirements_all.csv)
"""
import numpy as np
import pandas as pd

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SLOT = 30                      # minutes per grid cell
DAY_START, DAY_END = 8 * 60, 22 * 60
N_SLOTS = (DAY_END - DAY_START) // SLOT
SLOT_LABELS = [f"{(DAY_START + i * SLOT) // 60:02d}:{(DAY_START + i * SLOT) % 60:02d}" for i in range(N_SLOTS)]

LECTURE_TYPES = {"LECT", "BLEN", "SEMR", "HYFX", "PRAC"}
SMALL_TYPES = {"LAB", "TUTR", "WKSP"}
ENG_SECTIONS = set("EFGHIVXYZ")  # EECS sections reserved for BEng students (checklist advising note)


def to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def load_meetings(path):
    """Timed, in-person, non-Markham Fall/Winter meetings with minute offsets and a simple F/W term."""
    m = pd.read_csv(path, dtype=str).fillna("")
    m = m[(m.start != "") & (m.end != "") & m.day.isin(DAYS)].copy()
    m = m[~m.type.isin({"ONLN", "ONCA"})]
    m = m[m.campus != "Markham"]  # Keele-focused: Markham-taught sections are out of scope
    m["start_m"] = m.start.map(to_min)
    m["end_m"] = m.end.map(to_min)
    # collapse sub-terms (F1..F4, FA, W2 ...) into F or W; Y runs both terms
    m["term_fw"] = m.term.str[0].map({"F": "F", "W": "W", "Y": "Y"})
    m = m[m.term_fw.notna()]
    return m


def is_engineering(program):
    return "(BEng)" in program


def offered_terms(meetings, code):
    t = set(meetings.loc[meetings.course_code == code, "term_fw"])
    if "Y" in t:
        return {"F", "W"}
    return t


def course_options(meetings, code, term, engineering):
    """Every way a student could take `code` in `term`: a list of (weight, meetings-dataframe).

    A section = one lecture-type meet (if any) + one meet of each small type (LAB, TUTR ...)
    inside that section. Weights are equal across sections and across small-meet choices.
    """
    c = meetings[(meetings.course_code == code) & (meetings.term_fw.isin({term, "Y"}))]
    if c.empty:
        return []
    if code.startswith("EECS"):
        eng = c[c.section.isin(ENG_SECTIONS)]
        non = c[~c.section.isin(ENG_SECTIONS)]
        pick = eng if engineering else non
        if not pick.empty:  # fall back to any section if the reserved set is empty
            c = pick
    options = []
    sections = sorted(c.section.unique())
    for s in sections:
        sec = c[c.section == s]
        lect = sec[sec.type.isin(LECTURE_TYPES)]
        small = sec[sec.type.isin(SMALL_TYPES)]
        groups = [g for _, g in small.groupby("type")]
        combos = [lect]
        for g in groups:  # choose one meet number per small type
            meets = [mg for _, mg in g.groupby("meet")]
            combos = [pd.concat([base, mg]) for base in combos for mg in meets]
        for combo in combos:
            options.append((1.0 / (len(sections) * len(combos)), combo))
    return options


def cohort_slots(requirements, program, year):
    """Requirement slots for one program-year: list of (kind, [course codes], term_hint)."""
    r = requirements[(requirements.program == program) & (requirements.year == year)]
    out = []
    for _, g in r.groupby("slot"):
        out.append((g.kind.iloc[0], list(g.course_code), g.term_hint.iloc[0]))
    return out


def term_weight(meetings, code, term_hint, term):
    """Probability that a student takes `code` in `term` (F or W), given the checklist hint."""
    offered = offered_terms(meetings, code)
    if term not in offered:
        return 0.0
    if term_hint == term or term_hint == "Y":
        return 1.0
    if term_hint in {"F or W", "Any"}:
        return 1.0 / len(offered & {"F", "W"})
    return 0.0  # hinted for the other term or summer


def expected_grid(meetings, requirements, program, year, term="F", kinds=("lect", "small")):
    """Expected number of required classes in session per student, per day x slot (5 x N_SLOTS)."""
    grid = np.zeros((len(DAYS), N_SLOTS))
    eng = is_engineering(program)
    for kind, codes, hint in cohort_slots(requirements, program, year):
        for code in codes:
            w_code = (1.0 / len(codes)) * term_weight(meetings, code, hint, term)
            if w_code == 0:
                continue
            for w_opt, mt in course_options(meetings, code, term, eng):
                for _, row in mt.iterrows():
                    is_lect = row.type in LECTURE_TYPES
                    if ("lect" if is_lect else "small") not in kinds:
                        continue
                    d = DAYS.index(row.day)
                    s0 = max(0, (row.start_m - DAY_START) // SLOT)
                    s1 = min(N_SLOTS, -(-(row.end_m - DAY_START) // SLOT))
                    grid[d, s0:s1] += w_code * w_opt
    return grid


def _clashes(arr, taken):
    """arr: rows of (day, start_m, end_m). taken: dict day -> list of (s, e)."""
    for day, s, e in arr:
        for ts, te in taken.get(day, ()):
            if s < te and ts < e:
                return True
    return False


def _take(arr, taken):
    for day, s, e in arr:
        taken.setdefault(day, []).append((s, e))


def _student(slots, rng, term, opts_fn, meetings, tries=25):
    """Build one student's required timetable.

    Each try draws the alternatives and term placement, then places sections in a random course
    order, avoiding clashes. If a clash is unavoidable, retry (up to `tries`) and keep the
    schedule with the fewest clashes.
    Returns a list of (code, option_index) pairs.
    """
    best, best_clash = None, None
    for _ in range(tries):
        # re-draw alternatives and "F or W" term placement on every try: a student facing a
        # clash would move a flexible course to the other term
        chosen = []
        for kind, codes, hint in slots:
            code = codes[rng.integers(len(codes))]
            if rng.random() < term_weight(meetings, code, hint, term) and opts_fn(code):
                chosen.append(code)
        taken, picks, clash = {}, [], 0
        for code in rng.permutation(chosen):
            o = opts_fn(code)
            w = np.array([x[0] for x in o], dtype=float)
            order = np.argsort(-np.log(rng.random(len(w))) / w)  # weighted random order
            pick = next((i for i in order if not _clashes(o[i][1], taken)), None)
            if pick is None:
                pick, clash = order[0], clash + 1
            _take(o[pick][1], taken)
            picks.append((code, pick))
        if best is None or clash < best_clash:
            best, best_clash = picks, clash
        if clash == 0:
            break
    return best or []


def _opts_fn(meetings, term, eng, cache):
    def opts(code):
        key = (code, term, eng)
        if key not in cache:
            full = course_options(meetings, code, term, eng)
            cache[key] = [(w, mt[["day", "start_m", "end_m"]].to_numpy(), mt) for w, mt in full]
        return cache[key]
    return opts


def sample_student(meetings, requirements, program, year, term="F", seed=1, option_cache=None):
    """One plausible required-course timetable for a student in program-year (for illustration)."""
    rng = np.random.default_rng(seed)
    opts = _opts_fn(meetings, term, is_engineering(program), option_cache if option_cache is not None else {})
    picks = _student(cohort_slots(requirements, program, year), rng, term, opts, meetings)
    if not picks:
        return pd.DataFrame()
    return pd.concat([opts(c)[i][2] for c, i in picks])[
        ["course_code", "section", "type", "meet", "day", "start", "end", "room", "start_m", "end_m"]]


def simulate_cohort(meetings, requirements, program, year, term="F", n=400, arrive_early=15,
                    linger=60, buffer=10, seed=0, option_cache=None):
    """Monte Carlo: sample n students' required timetables.

    Works minute by minute, then averages into 30-min slots, so a half-hour that is partly
    class and partly free counts proportionally. Returns a dict of 5 x N_SLOTS arrays, each a
    share of the cohort:
      in_class   in a required class
      on_campus  from `arrive_early` min before the first class to `linger` min after the LAST class
      free       on campus and not in class: between classes, or within `linger` min of the last one
      done       the part of `free` after the last class of the day (nothing left to go to)
      last_end   the student's LAST class of the day ends inside that slot
      left       had class that day and has already gone home (`linger` min after the last class has passed)
      away       not on campus: not arrived yet, already gone home, or no required class that day.
                 in_class + free + away = 1 in every slot
    plus `no_class`, a length-5 array: share with no required class that day.
    A "class" is any required meeting (lecture, lab, tutorial): a lab after a lecture means the day isn't over.
    Every class is treated as running `buffer` minutes past its scheduled end (overruns, packing up,
    walking to wherever the event is): a 17:20 end frees students at 17:30.
    """
    rng = np.random.default_rng(seed)
    opts = _opts_fn(meetings, term, is_engineering(program), option_cache if option_cache is not None else {})
    slots = cohort_slots(requirements, program, year)
    minutes = DAY_END - DAY_START
    tot = {k: np.zeros((len(DAYS), minutes)) for k in ("in_class", "on_campus", "done", "left")}
    last_end = np.zeros((len(DAYS), N_SLOTS))
    no_class = np.zeros(len(DAYS))
    clip = lambda m: int(min(max(m - DAY_START, 0), minutes))
    for _ in range(n):
        busy = np.zeros((len(DAYS), minutes), dtype=bool)
        first = np.full(len(DAYS), np.inf)
        last = np.full(len(DAYS), -np.inf)
        for code, i in _student(slots, rng, term, opts, meetings):
            for day, s, e in opts(code)[i][1]:
                d = DAYS.index(day)
                e = e + buffer
                first[d] = min(first[d], s)
                last[d] = max(last[d], e)
                busy[d, clip(s):clip(e)] = True
        for d in range(len(DAYS)):
            if not np.isfinite(first[d]):
                no_class[d] += 1
                continue
            a, e, b = clip(first[d] - arrive_early), clip(last[d]), clip(last[d] + linger)
            tot["on_campus"][d, a:b] += 1
            tot["done"][d, e:b] += 1
            tot["left"][d, b:] += 1
            k = int((last[d] - DAY_START) // SLOT)
            if 0 <= k < N_SLOTS:
                last_end[d, k] += 1
        tot["in_class"] += busy
    to_slots = lambda x: x.reshape(len(DAYS), N_SLOTS, SLOT).mean(axis=2) / n
    out = {k: to_slots(v) for k, v in tot.items()}
    out["free"] = out["on_campus"] - out["in_class"]
    out["last_end"] = last_end / n
    out["no_class"] = no_class / n
    out["away"] = 1 - out["on_campus"]   # not arrived yet, already gone home, or no class that day
    return out
