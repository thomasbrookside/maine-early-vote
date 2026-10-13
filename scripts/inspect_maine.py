#!/usr/bin/env python3
"""Summarize a Maine absentee voter file so the layout can be compared across years.
Usage: python inspect_maine.py FILE > summary.txt      (then paste summary.txt into chat)
Reads the whole file once; no data is modified or sent anywhere."""
import csv, sys, re, collections

DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}")
MAX_DISTINCT = 40          # columns with fewer distinct values get a full value count
path = sys.argv[1]

with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
    head = f.readline(); f.seek(0)
    delim = max("|\t,;", key=head.count)
    rdr = csv.reader(f, delimiter=delim)
    header = next(rdr)
    names = [h.strip() for h in header]
    print(f"FILE: {path}\nDELIMITER: {delim!r}\nHEADER ({len(names)} cols): {names}\n")

    n = 0; bad_len = 0
    vals = [collections.Counter() for _ in names]
    dmin = {}; dmax = {}; years = collections.defaultdict(collections.Counter)
    sample = []; towns = collections.Counter()
    find = lambda *c: next((i for i, h in enumerate(names) if h.strip().upper() in c), None)
    ti = find("RES MUNICIPALITY", "MUNICIPALITY"); pi = find("P"); si = find("STATUS", "ACC OR REJ")
    ri = find("REC DATE", "RECDATE"); vi = find("VOTER RECORD #", "VOTER ID")
    combo = collections.Counter(); voter_rows = collections.Counter()
    for row in rdr:
        n += 1
        if len(row) != len(names): bad_len += 1
        row = (row + [""] * len(names))[:len(names)]
        if len(sample) < 5: sample.append(row)
        for i, v in enumerate(row):
            v = v.strip()
            c = vals[i]
            if len(c) <= MAX_DISTINCT * 5: c[v] += 1
            if DATE.match(v):
                m, d, y = v[:10].split("/")
                key = (int(y), int(m), int(d))
                dmin[i] = min(dmin.get(i, key), key); dmax[i] = max(dmax.get(i, key), key)
                years[i][y] += 1
        if ti is not None: towns[row[ti].strip()] += 1
        if None not in (pi, si, ri):
            combo[(row[pi].strip(), row[si].strip(), "has_rec_date" if row[ri].strip() else "no_rec_date")] += 1
        if vi is not None: voter_rows[row[vi].strip()] += 1

print(f"ROWS: {n}   rows with wrong column count: {bad_len}\n")
print("FIRST 5 RAW ROWS:")
for r in sample: print("  " + "|".join(r))

print("\nCOLUMNS:")
for i, h in enumerate(names):
    if not h: continue
    c = vals[i]
    if i in dmin:
        f = lambda k: f"{k[1]:02d}/{k[2]:02d}/{k[0]}"
        print(f"\n{h}: dates {f(dmin[i])} to {f(dmax[i])}; years {dict(years[i].most_common(6))}; blank={c.get('', 0)}")
    elif len(c) <= MAX_DISTINCT:
        print(f"\n{h}: " + ", ".join(f"{a!r}={b}" for a, b in c.most_common()))
    else:
        print(f"\n{h}: (many distinct values, e.g. {[a for a, _ in c.most_common(3)]})")

if combo:
    print("\nPARTY x STATUS x HAS-REC-DATE (the cells that drive the map):")
    for k, v in sorted(combo.items()): print(f"  {k}: {v}")
if vi is not None:
    dup = sum(1 for v in voter_rows.values() if v > 1)
    print(f"\nDISTINCT VOTER IDs: {len(voter_rows)}; IDs appearing on more than one row: {dup}")
if ti is not None:
    print(f"\nDISTINCT MUNICIPALITIES: {len(towns)}")
    odd = [t for t in towns if re.search(r"\b(twp|plt|gore|ti|tws|unorg|ut|island|isle|grant)\b", t, re.I) or not t.replace(" ", "").isalpha()]
    print("Names with suffixes/punctuation:", sorted(odd)[:60])
    print("First 15 alphabetically:", sorted(towns)[:15])