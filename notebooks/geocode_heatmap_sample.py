"""
Geocode municipality centroids (MUNICIPIO_PRESTACION, DEPARTAMENTO_PRESTACION)
and build a weighted heatmap for ALL rows. Much faster than per-address.

Outputs:
- reports/geo_municipios_unique.csv    (unique muni+dept with lat/lon)
- reports/geo_prestacion_all.csv       (all rows with muni lat/lon + weight)
- images/heatmap_prestacion_municipios.html
"""

from pathlib import Path
import sqlite3
import pandas as pd

# pip install geopy folium
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
import folium
from folium.plugins import HeatMap

# ---------------- Paths ----------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH      = PROJECT_ROOT / "database" / "rups.db"
REPORTS_DIR  = PROJECT_ROOT / "reports"
IMAGES_DIR   = PROJECT_ROOT / "images"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Params ----------------
ONLY_OPERATIONAL = True
REQUEST_TIMEOUT  = 10
MIN_DELAY        = 1.2    # cortesía para OSM
RETRY_MAX        = 3
RETRY_WAIT       = 8.0

# ---------------- Load ----------------
with sqlite3.connect(DB_PATH) as conn:
    df = pd.read_sql("SELECT * FROM prestadores;", conn)

if ONLY_OPERATIONAL and "ESTADO" in df.columns:
    df = df[df["ESTADO"].str.contains(r"OPERATIVA", case=False, na=False)].copy()

# Build unique municipality-of-service keys
df["DEP_PREST"] = df["DEPARTAMENTO_PRESTACION"].fillna("").astype(str).str.strip()
df["MUN_PREST"] = df["MUNICIPIO_PRESTACION"].fillna("").astype(str).str.strip()

# Keep only rows that have at least municipality or department
valid = (df["MUN_PREST"] != "") | (df["DEP_PREST"] != "")
df_valid = df[valid].copy()

uni = (
    df_valid
    .groupby(["DEP_PREST", "MUN_PREST"], dropna=False)
    .size()
    .reset_index(name="weight")
)

# Query string: "Municipio, Departamento, Colombia"
uni["query"] = (
    uni["MUN_PREST"].where(uni["MUN_PREST"] != "", other="") + ", " +
    uni["DEP_PREST"].where(uni["DEP_PREST"] != "", other="") + ", Colombia"
).str.replace(r",\s*,", ", ", regex=True).str.strip(", ").str.strip()

# ---------------- Cache ----------------
cache_path = REPORTS_DIR / "geo_cache_municipios.csv"
try:
    cache = pd.read_csv(cache_path)
    if "address" not in cache.columns:
        cache = cache.rename(columns={"full_address": "address"})
    for col in ["address","lat","lon","source"]:
        if col not in cache.columns:
            cache[col] = pd.NA
    cache = cache[["address","lat","lon","source"]]
except Exception:
    cache = pd.DataFrame(columns=["address","lat","lon","source"])

cache_map = {str(r["address"]): (r["lat"], r["lon"]) for _, r in cache.iterrows()}


# ---------------- Geocoder  ----------------
MIN_DELAY: float = 1.2
RETRY_MAX: int = 3
RETRY_WAIT: float = 8.0

geolocator = Nominatim(user_agent="rups_kpi_geocoder")

geocode = RateLimiter(
    geolocator.geocode,
    min_delay_seconds=MIN_DELAY,
    max_retries=RETRY_MAX,
    error_wait_seconds=RETRY_WAIT,
    swallow_exceptions=True,  # no revienta si falla un punto
)

def geocode_addr(q: str):
    loc = geocode(q)
    if loc is not None:
        return loc.latitude, loc.longitude, "nominatim"
    return None


# ---------------- Run (unique queries) ----------------
lats, lons, srcs = [], [], []
total = len(uni)
ok = 0

for i, q in enumerate(uni["query"], 1):
    lat = lon = None
    src = "cache"
    if q in cache_map and pd.notna(cache_map[q][0]) and pd.notna(cache_map[q][1]):
        lat, lon = cache_map[q]
    else:
        loc = geocode(q)
        if loc is not None:
            lat, lon = loc.latitude, loc.longitude
            src = "nominatim"
        else:
            src = "fail"
        # persist
        cache = pd.concat([cache, pd.DataFrame([{"address": q, "lat": lat, "lon": lon, "source": src}])], ignore_index=True)
        cache.drop_duplicates(subset=["address"], keep="last", inplace=True)
        cache.to_csv(cache_path, index=False, encoding="utf-8")

    if pd.notna(lat) and pd.notna(lon): ok += 1
    if i % 50 == 0:  # progreso cada 50
        print(f"[{i}/{total}] ok={ok}")

    lats.append(lat); lons.append(lon); srcs.append(src)

uni["lat"] = lats
uni["lon"] = lons
uni["source"] = srcs

# Guardar geocodificación única
uni.to_csv(REPORTS_DIR / "geo_municipios_unique.csv", index=False, encoding="utf-8")

# ---------------- Attach coords back to ALL rows ----------------
coord_map = uni.set_index(["DEP_PREST","MUN_PREST"])[["lat","lon"]]
df_out = df_valid.merge(coord_map, left_on=["DEP_PREST","MUN_PREST"], right_index=True, how="left")

# Export for analysis
df_out.to_csv(REPORTS_DIR / "geo_prestacion_all.csv", index=False, encoding="utf-8")

# ---------------- Heatmap (weighted by count) ----------------
pts = df_out.dropna(subset=["lat","lon"])
if not pts.empty:
    agg = pts.groupby(["lat","lon"], dropna=False).size().reset_index(name="weight")
    m = folium.Map(location=[4.5709, -74.2973], zoom_start=5, tiles="CartoDB positron")
    HeatMap(agg[["lat","lon","weight"]].values.tolist(), radius=14, blur=22, max_zoom=12).add_to(m)
    out_html = IMAGES_DIR / "heatmap_prestacion_municipios.html"
    m.save(out_html.as_posix())
    print(f"[DONE] muni geocoded: {ok}/{total}  → HTML: {out_html.as_posix()}")
else:
    print("No points geocoded. Check queries in geo_municipios_unique.csv")
