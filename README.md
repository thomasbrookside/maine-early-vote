# Maine absentee vote map: 2026 vs. 2020, same day

Town-level map of the Republican share of R+D accepted absentee ballots, 2026 vs. 2020 on the same number
of days before Election Day (both Nov 3). Layout follows the Ohio early-vote repo.

## One-time setup
    pip install -r requirements.txt
    python scripts/build_geometry.py          # downloads Maine GIS town/township boundaries -> data/maine_towns.topo.json
(If the download fails, export GeoJSON from the Maine GeoLibrary "Town and Township Boundary Polygons" page and
run `python scripts/build_geometry.py --input FILE.geojson`.)

## Each update
    python scripts/aggregate.py --y2020 "1120-absentee-voter-file_0.txt" --y2026 "11-3-26 AB Voter File as of 10-9-26.txt"
Writes `data/timeseries.json` and `data/match_report.txt`. Check the report's UNMATCHED section: any town name
listed there is missing from the map. Fix by adding `"File Name": "Map Name"` to `data/town_aliases.json`
(map names are in `data/geometry_names.txt`), then re-run. Use `--asof-2026 YYYY-MM-DD` if the file covers
a later day than its latest receive date.

## Counting rules
- One accepted ballot per voter (earliest accepted receive date). Accepted = ACC (2020) or ACT/ACU/ACH (2026).
- Dropped: blank municipality, accepted rows with no readable receive date, dates outside the voting window.
- Repaired: malformed years such as 10/10/820 -> 10/10/2020 (listed in the report).
- 2020 ballots received after Election Day are excluded so both years end on the same day.
- Share = R / (R + D); U, G, L and blank party are kept in raw totals only.

## Page tuning (top of index.html)
`MIN_SHIFT` / `MAX_SHIFT` set the color range, `MIN_TOTAL` the minimum R+D ballots per town in both years.
