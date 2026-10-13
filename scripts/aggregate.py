#!/usr/bin/env python3
"""Aggregate Maine absentee voter files (2020 + 2026) into data/timeseries.json.

Usage:
  python aggregate.py --y2020 FILE_2020.txt --y2026 FILE_2026.txt [--asof-2026 YYYY-MM-DD]

Counts ONE accepted, received ballot per voter (earliest accepted receive date), by town x party,
cumulative by days before Election Day, so the page can compare 2026 and 2020 "on this day".
Needs data/maine_towns.topo.json (from build_geometry.py) so towns can be matched to map shapes.
Writes data/timeseries.json and data/match_report.txt (name repairs, date repairs, unmatched towns).
"""
import argparse, csv, collections, datetime as dt, json, os, re, sys

ELECTIONS = {"2020": dt.date(2020, 11, 3), "2026": dt.date(2026, 11, 3)}
# column-name candidates (case-insensitive) -- the 2020 and 2026 layouts differ
COLS = {"muni": ("RES MUNICIPALITY", "MUNICIPALITY"), "party": ("P",),
        "voter": ("VOTER RECORD #", "VOTER ID"), "status": ("STATUS", "ACC OR REJ"),
        "recdate": ("REC DATE", "RECDATE")}
STATUS_FIX = {"ACC": "ACT", "ACU": "ACT", "ACH": "ACT"}   # all treated as accepted ("ACT")
PARTY = {"R": "gop", "D": "dem"}                          # everything else -> "oth" (U, G, L, blank)
HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "..", "data")

# ---------- date repair ----------
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{1,4})$")
def parse_date(raw, year, fixes):
    """Return a date or None. Repairs malformed years like '820', '1320', '0820' when they end in the
    election year's last two digits (e.g. 10/10/820 -> 10/10/2020); anything else unreadable is dropped."""
    parts = (raw or "").split()
    m = DATE_RE.match(parts[0]) if parts else None
    if not m: return None
    mo, d, ys = int(m[1]), int(m[2]), m[3]
    if not (len(ys) == 4 and 2000 <= int(ys) <= 2100):
        if not ys.endswith(f"{int(year) % 100:02d}"): return None
        fixes[(parts[0], f"{mo:02d}/{d:02d}/{year}")] += 1
        ys = year
    try: return dt.date(int(ys), mo, d)
    except ValueError: return None

# ---------- town-name matching ----------
def norm(s):
    s = (s or "").upper().replace("&", " AND ")
    s = re.sub(r"\(.*?\)", " ", s)                       # drop "(T17 R5)" style notes
    s = re.sub(r"^(ST|MT|FT)\.?\s+", lambda m: {"ST": "SAINT ", "MT": "MOUNT ", "FT": "FORT "}[m[1]], s.strip())
    s = re.sub(r"[^A-Z0-9 ]", " ", s)       # hyphens become spaces: Dover-Foxcroft == Dover Foxcroft
    s = re.sub(r"\bTOWNSHIP\b", "TWP", s); s = re.sub(r"\bPLANTATION\b", "PLT", s)
    return re.sub(r"\s+", " ", s).strip()
def trunc(k):                                            # "PRENTISS TWP T7 R3 NBPP" -> "PRENTISS TWP"
    m = re.match(r"^(.*?\s(?:TWP|PLT))\s", k + " ");  return m[1] if m else k
def strip_type(k): return re.sub(r"\s(?:TWP|PLT)$", "", k)

class Matcher:
    def __init__(self, names, aliases):
        self.exact, self.bystrip = {}, collections.defaultdict(set)
        for n in names:
            for k in {norm(n), trunc(norm(n))}: self.exact.setdefault(k, set()).add(n)
            self.bystrip[strip_type(trunc(norm(n)))].add(n)
        self.alias = {norm(k): v for k, v in aliases.items()}; self.names = set(names); self.cache = {}
    def one(self, s):
        return next(iter(s)) if len(s) == 1 else None
    def match(self, raw):
        if raw in self.cache: return self.cache[raw]
        k = norm(raw); out = self.alias.get(k)
        if out is None:
            for kk in (k, trunc(k)):
                out = self.one(self.exact.get(kk, set()))
                if out: break
        if out is None:                                  # renamed type: 2020 "DREW PLT" vs 2026 "Drew Twp"
            t = trunc(k); swap = t[:-3] + ("TWP" if t.endswith("PLT") else "PLT") if t[-3:] in ("TWP", "PLT") else None
            out = self.one(self.exact.get(swap, set())) if swap else None
        if out is None: out = self.one(self.bystrip.get(strip_type(trunc(k)), set()))
        self.cache[raw] = out; return out

# ---------- one year ----------
def load_year(path, year, matcher, max_days, asof, report):
    election = ELECTIONS[year]; lo = election - dt.timedelta(days=120); hi = election + dt.timedelta(days=30)
    fixes = collections.Counter(); drops = collections.Counter(); stats = collections.Counter()
    best = {}                                            # voter -> (date, town, party): earliest accepted ballot
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rdr = csv.reader(f, delimiter="|"); header = [h.strip().upper() for h in next(rdr)]
        ix = {}
        for key, cands in COLS.items():
            hit = [header.index(c) for c in cands if c in header]
            if not hit: sys.exit(f"{path}: no column found for {key} (looked for {cands}); header = {header}")
            ix[key] = hit[0]
        for n, row in enumerate(rdr):
            stats["rows"] += 1
            row = (row + [""] * len(header))[:len(header)]
            town = row[ix["muni"]].strip()
            if not town: stats["dropped: blank municipality"] += 1; continue
            st = row[ix["status"]].strip().upper(); st = STATUS_FIX.get(st, st)
            if st != "ACT": stats["skipped: not accepted"] += 1; continue
            d = parse_date(row[ix["recdate"]], year, fixes)
            if d is None:
                stats["dropped: accepted but no/unreadable receive date"] += 1
                if row[ix["recdate"]].strip(): drops[row[ix["recdate"]].strip()] += 1
                continue
            if not (lo <= d <= hi): stats["dropped: receive date outside window"] += 1; drops[d.isoformat()] += 1; continue
            if d > election: stats["excluded: received after Election Day"] += 1; continue
            if asof and d > asof: stats["excluded: after as-of date"] += 1; continue
            vid = row[ix["voter"]].strip() or f"row{n}"
            if vid in best:
                stats["duplicate accepted rows (voter counted once)"] += 1
                if d >= best[vid][0]: continue
            best[vid] = (d, town, PARTY.get(row[ix["party"]].strip().upper(), "oth"))
    last_day = max(v[0] for v in best.values()) if best else None
    asof = asof or last_day
    last_out = (election - asof).days
    length = max_days - last_out + 1                     # index 0 = max_days before; last index = asof
    counts = collections.defaultdict(lambda: {p: [0] * length for p in ("gop", "dem", "oth")})
    unmatched = collections.Counter(); matched_ballots = 0
    for d, town, p in best.values():
        name = matcher.match(town)
        if name is None: unmatched[(town, p in ("gop", "dem"))] += 1; continue
        i = max_days - min((election - d).days, max_days)   # earlier-than-window ballots roll into index 0
        counts[name][p][i] += 1; matched_ballots += 1
    series = {}
    for name, c in counts.items():
        for p, arr in c.items():                         # cumulative through each day
            run = 0
            for i in range(len(arr)): run += arr[i]; arr[i] = run
        series[name] = c
    report.append(f"===== {year} ({path}) =====")
    report += [f"{k}: {v}" for k, v in sorted(stats.items())]
    report.append(f"accepted ballots counted (one per voter): {len(best)}; matched to map towns: {matched_ballots}; as-of date used: {asof}")
    if fixes: report.append("date repairs: " + "; ".join(f"{a} -> {b} (x{c})" for (a, b), c in fixes.items()))
    if drops: report.append("dropped dates: " + "; ".join(f"{a} (x{c})" for a, c in drops.most_common(20)))
    um = collections.Counter()
    for (t, two), c in unmatched.items(): um[t] += c
    report.append(f"UNMATCHED town names: {len(um)} ({sum(um.values())} ballots)")
    report += [f"   {t!r}: {c} ballots" for t, c in um.most_common()]
    return series, asof, length

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--y2020", required=True); ap.add_argument("--y2026", required=True)
    ap.add_argument("--asof-2026", help="last day covered by the 2026 file (default: latest receive date in it)")
    ap.add_argument("--max-days", type=int, default=60, help="days before Election Day where the series starts")
    ap.add_argument("--geometry", default=os.path.join(DATA, "maine_towns.topo.json"))
    ap.add_argument("--aliases", default=os.path.join(DATA, "town_aliases.json"))
    ap.add_argument("--out", default=os.path.join(DATA, "timeseries.json"))
    a = ap.parse_args()
    if not os.path.exists(a.geometry): sys.exit(f"missing {a.geometry} -- run build_geometry.py first")
    topo = json.load(open(a.geometry)); obj = topo["objects"].get("towns") or next(iter(topo["objects"].values()))
    names = [g["properties"]["name"] for g in obj["geometries"]]
    aliases = json.load(open(a.aliases)) if os.path.exists(a.aliases) else {}
    matcher = Matcher(names, aliases); report = []
    s20, asof20, len20 = load_year(a.y2020, "2020", matcher, a.max_days, ELECTIONS["2020"], report)
    asof26 = dt.date.fromisoformat(a.asof_2026) if a.asof_2026 else None
    s26, asof26, len26 = load_year(a.y2026, "2026", matcher, a.max_days, asof26, report)
    towns = {}
    for n in names:
        e = {}
        if n in s20: e["2020"] = s20[n]
        if n in s26: e["2026"] = s26[n]
        if e: towns[n] = e
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "elections": {y: d.isoformat() for y, d in ELECTIONS.items()},
           "asof": {"2020": ELECTIONS["2020"].isoformat(), "2026": asof26.isoformat()},
           "days_out": list(range(a.max_days, -1, -1)), "lengths": {"2020": len20, "2026": len26}, "towns": towns}
    json.dump(out, open(a.out, "w"), separators=(",", ":"))
    rp = os.path.join(os.path.dirname(a.out), "match_report.txt"); open(rp, "w").write("\n".join(report) + "\n")
    print("\n".join(report)); print(f"\nwrote {a.out} ({os.path.getsize(a.out)//1024} KB) and {rp}")

if __name__ == "__main__": main()
