#!/usr/bin/env python3
"""Build data/maine_towns.topo.json: one map shape per Maine town / plantation / township.

Usage:
  python build_geometry.py                        # download from Maine GIS (ArcGIS REST), cache the raw GeoJSON
  python build_geometry.py --input towns.geojson  # or use a GeoJSON you downloaded yourself
Needs: pip install shapely topojson pyproj
Islands are merged into their town, tiny islands are dropped, and shared borders are simplified together.
"""
import argparse, json, math, os, sys, urllib.parse, urllib.request, warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely.ops import unary_union, transform
import topojson as tp

HERE = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(HERE, "..", "data")
SOURCES = [  # tried in order; both serve the Maine GIS town/township boundary layer
    "https://gis.maine.gov/mapservices/rest/services/escb/escbHigherGround/MapServer/23/query",
    "https://services1.arcgis.com/RbMX0mRVOFNTdLzd/ArcGIS/rest/services/LUPC_Towns/FeatureServer/0/query",
]
NAME_FIELDS = ("TOWN", "MUNICIPALITY", "TOWNNAME", "TOWN_NAME", "MUNICIPAL", "MUNI", "NAME")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

def fetch_json(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r: return json.load(r)

def download(dest):
    for base in SOURCES:
        feats, offset, page = [], 0, 500
        try:
            while True:
                gj = fetch_json(base, {"where": "1=1", "outFields": "*", "outSR": 4326, "returnGeometry": "true",
                                       "f": "geojson", "resultOffset": offset, "resultRecordCount": page})
                if "error" in gj: raise RuntimeError(gj["error"])
                got = gj.get("features", []); feats += got; offset += len(got)
                print(f"  {base.split('/')[-4]}: {len(feats)} features...", file=sys.stderr)
                if not got or (len(got) < page and not gj.get("exceededTransferLimit")): break
            if feats:
                json.dump({"type": "FeatureCollection", "features": feats}, open(dest, "w")); return dest
        except Exception as e:
            print(f"  source failed ({base}): {e}", file=sys.stderr)
    sys.exit("Could not download the boundaries. In a browser, open the Maine GeoLibrary page 'Maine Town and "
             "Township Boundary Polygons', export GeoJSON, then run:  python build_geometry.py --input FILE.geojson")

def first_xy(g):
    while isinstance(g, (list, tuple)) and isinstance(g[0], (list, tuple)): g = g[0]
    return g

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input"); ap.add_argument("--name-field")
    ap.add_argument("--src-crs", default="EPSG:26919", help="only used if the input is projected (not lon/lat)")
    ap.add_argument("--tolerance", type=float, default=0.0006, help="simplification in degrees (~65 m); raise for a smaller file")
    ap.add_argument("--min-island-km2", type=float, default=0.25)
    ap.add_argument("--out", default=os.path.join(DATA, "maine_towns.topo.json"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    src = a.input or download(os.path.join(DATA, "maine_towns_raw.geojson"))
    feats = json.load(open(src))["features"]; print(f"{len(feats)} source features", file=sys.stderr)
    props = feats[0]["properties"]
    field = a.name_field or next((k for c in NAME_FIELDS for k in props if k.upper() == c), None)
    if not field: sys.exit(f"Can't find the town-name field. Fields are: {list(props)}. Re-run with --name-field FIELD")
    print(f"name field: {field}", file=sys.stderr)
    xy = first_xy(feats[0]["geometry"]["coordinates"]); fix = None
    if abs(xy[0]) > 180:
        from pyproj import Transformer
        t = Transformer.from_crs(a.src_crs, "EPSG:4326", always_xy=True); fix = lambda x, y, z=None: t.transform(x, y)
    groups = {}
    for f in feats:
        name = (f["properties"].get(field) or "").strip()
        if not name or not f.get("geometry"): continue
        g = shape(f["geometry"]); g = transform(fix, g) if fix else g
        groups.setdefault(name, []).append(g if g.is_valid else g.buffer(0))
    km2 = lambda g: g.area * 111.32 * math.cos(math.radians(g.centroid.y)) * 110.57   # sq-degrees -> km^2
    out_feats, dropped = [], 0
    for name, gs in sorted(groups.items()):
        u = unary_union(gs); parts = list(u.geoms) if hasattr(u, "geoms") else [u]
        parts = [p for p in parts if isinstance(p, Polygon)]
        big = max(parts, key=lambda p: p.area)
        keep = [p for p in parts if p is big or km2(p) >= a.min_island_km2]; dropped += len(parts) - len(keep)
        geom = keep[0] if len(keep) == 1 else MultiPolygon(keep)
        out_feats.append({"type": "Feature", "properties": {"name": name}, "geometry": mapping(geom)})
    topo = tp.Topology({"type": "FeatureCollection", "features": out_feats}, object_name="towns",
                       prequantize=100000, toposimplify=a.tolerance)
    open(a.out, "w").write(topo.to_json())
    names = sorted(groups); open(os.path.join(os.path.dirname(a.out), "geometry_names.txt"), "w").write("\n".join(names) + "\n")
    print(f"{len(names)} towns/townships, dropped {dropped} tiny island pieces; wrote {a.out} ({os.path.getsize(a.out)//1024} KB)")
    if os.path.getsize(a.out) > 2_500_000: print("File is large; consider --tolerance 0.0012 for faster page loads.")

if __name__ == "__main__": main()
