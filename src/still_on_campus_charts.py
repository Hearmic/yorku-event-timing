import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import campus_model as cm

INK, INK2 = "#1b1f24", "#5b6370"
CMAP = LinearSegmentedColormap.from_list("ramp", ["#f4f6f9", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "savefig.dpi": 170, "savefig.bbox": "tight"})

meetings = cm.load_meetings(ROOT / "data/york_fw2026_meetings.csv")
req = pd.read_csv(ROOT / "data/requirements_all.csv")
hc = pd.read_csv(ROOT / "data/headcount_keele_fall2025.csv")
P = "Bachelor of Engineering (BEng) Specialized Honours "
FOCUS = {  # cohort -> (requirements program, OIPA program, years held)
    "1st-year Engineering": (P + "Engineering", "Engineering", [1]),
    "Software Eng": (P + "Software Engineering - General Stream", "Software Engineering", [2, 3, 4]),
    "Computer Eng": (P + "Computer Engineering", "Computer Engineering", [2, 3, 4]),
    "Electrical Eng": (P + "Electrical Engineering", "Electrical Engineering", [2, 3, 4]),
    "Mechatronics Eng": (P + "Mechatronics Engineering", "Mechatronics", [2]),
    "Mechanical Eng": (P + "Mechanical Engineering", "Mechanical Engineering", [2, 3, 4]),
    "Civil Eng": (P + "Civil Engineering", "Civil Engineering", [2, 3, 4]),
    "CS": ("Bachelor of Science (BSc) Specialized Honours Computer Science", "Computer Science", [1, 2, 3, 4]),
    "Cybersecurity": ("Bachelor of Science (BSc) Specialized Honours Cybersecurity", "Computer Security", [1, 2, 3, 4]),
    "Digital Media": ("Bachelor of Arts (BA) Specialized Honours Digital Media - Digital Media Development", "Digital Media", [1, 2, 3, 4]),
    "Data Science": ("Bachelor of Science (BSc) Honours Data Science - Business Stream", "Data Science", [1, 2, 3]),
}
RET = 0.899; L23 = (1 - RET) / 2
SURV = {1: 1.0, 2: RET, 3: RET - L23, 4: RET - L23}

def people(linger):
    tot, cache, n_students = {k: np.zeros((5, cm.N_SLOTS)) for k in ("done", "left", "away")}, {}, 0
    for name, (prog, src, years) in FOCUS.items():
        total = hc.loc[hc.program == src, "headcount_fall2025"].item()
        for y in years:
            k = total * SURV[y] / sum(SURV[v] for v in years)
            out = cm.simulate_cohort(meetings, req, prog, y, "F", n=400, linger=linger, option_cache=cache)
            for key in tot:
                tot[key] += out[key] * k
            n_students += k
    return tot, n_students

p60, N = people(60)
p30, _ = people(30)
win = slice(6, 28)   # 11:00-22:00
labels = np.array(cm.SLOT_LABELS)[win]

def draw(grid, minutes, fname, vmax, title, sub, mark_peak=True):
    g = grid[:, win]
    fig, ax = plt.subplots(figsize=(6.4, 8.2))
    im = ax.imshow(g.T, aspect="auto", cmap=CMAP, vmin=0, vmax=vmax, interpolation="nearest")
    for d in range(5):
        for t in range(g.shape[1]):
            v = g[d, t]
            if v >= 15:
                ax.text(d, t, f"{v:,.0f}", ha="center", va="center", fontsize=8.5,
                        color="white" if v > vmax * 0.55 else INK)
    ax.set_xticks(range(5), cm.DAYS, fontsize=11); ax.xaxis.tick_top()
    nxt = lambda s: f"{(cm.to_min(s) + cm.SLOT) // 60:02d}:{(cm.to_min(s) + cm.SLOT) % 60:02d}"
    ax.set_yticks(range(len(labels)), [f"{s}–{nxt(s)}" for s in labels], fontsize=8.5)
    ax.tick_params(length=0); [s.set_visible(False) for s in ax.spines.values()]
    best = np.unravel_index(np.argmax(g), g.shape)
    if mark_peak:
        ax.add_patch(plt.Rectangle((best[0] - 0.5, best[1] - 0.5), 1, 1, fill=False, ec=INK, lw=2))
    sub_text = (sub + "\nClasses count as ending 10 min late (overruns, walking)"
                + f"\nEstimated people · Fall 2026 · {N:,.0f} Keele CS & engineering students"
                + (" · boxed = peak" if mark_peak else ""))
    ax.annotate(sub_text, (0, 1), xycoords="axes fraction", xytext=(-95, 28), textcoords="offset points",
                fontsize=9, color=INK2, ha="left", va="bottom", linespacing=1.45)
    ax.annotate(title, (0, 1), xycoords="axes fraction", xytext=(-95, 82), textcoords="offset points",
                fontsize=14, fontweight="bold", ha="left", va="bottom")
    cb = fig.colorbar(im, ax=ax, shrink=0.45, pad=0.03); cb.set_label("students"); cb.outline.set_visible(False)
    fig.savefig(fname); plt.close(fig)
    d, t = best
    print(f"{title}, {minutes} min: peak {cm.DAYS[d]} {labels[t]} = {g[d, t]:,.0f}")

out = ROOT / "figures"
vd = max(p60["done"].max(), p30["done"].max())
va = max(p60["away"].max(), p30["away"].max())
for m, p in [(60, p60), (30, p30)]:
    draw(p["done"], m, out / f"still_on_campus_{m}min.png", vd, "Done for the day, still on campus",
         f"Students who finished their last class within the past {m} minutes")
    draw(p["away"], m, out / f"already_left_{m}min.png", va, "Not on campus",
         f"Not arrived yet, left {m} min after their last class, or no class that day", mark_peak=False)
nc = p60["away"][:, -1] - p60["left"][:, -1]
print("no required class that day:", ", ".join(f"{d} {v:,.0f}" for d, v in zip(cm.DAYS, nc)))
for m, p in [(60, p60), (30, p30)]:
    g = p["done"][:, 6:24]
    idx = np.dstack(np.unravel_index(np.argsort(-g, axis=None), g.shape))[0][:6]
    print(f"--- {m} min top windows")
    for d, t in idx:
        k = t + 6
        print(f"{cm.DAYS[d]} {cm.SLOT_LABELS[k]}: done {p['done'][d,k]:,.0f} | gone after class {p['left'][d,k]:,.0f} | not on campus {p['away'][d,k]:,.0f}")
w = cm.DAYS.index("Wed")
print("Wed 20:00-21:30 done (60 min):", [round(p60["done"][w, cm.SLOT_LABELS.index(s)]) for s in ["20:00", "20:30", "21:00", "21:30"]])
