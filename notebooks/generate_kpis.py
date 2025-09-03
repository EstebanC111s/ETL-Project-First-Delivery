# notebooks/generate_kpis.py
# Purpose: Generate KPIs and export charts for the RUPS dataset (SDG 6 focus) using seaborn.
# - Builds per-row service flags (propagating "AAA" to the three services).
# - Exports CSVs to reports/ and PNGs to images/.
# - Expects a SQLite DB at database/rups.db with table 'prestadores'.

from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# ===================== Setup =====================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH      = PROJECT_ROOT / "database" / "rups.db"
REPORTS_DIR  = PROJECT_ROOT / "reports"
IMAGES_DIR   = PROJECT_ROOT / "images"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

sns.set_theme(style="whitegrid")

# Options:
EXCLUDE_BOGOTA_TOP_DEPTS = True
DEPT_RENAME = {
    # Shorter label for plotting
    "ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA": "San Andrés & Prov."
}

# ===================== Load data =====================
assert DB_PATH.exists(), f"SQLite DB not found at {DB_PATH}. Run `python main.py` first."
conn = sqlite3.connect(DB_PATH.as_posix())
df = pd.read_sql("SELECT * FROM prestadores", conn)

# Light normalization
df.columns = df.columns.str.strip()
df["DEPARTAMENTO_PRESTACION"] = df["DEPARTAMENTO_PRESTACION"].astype("string")
df["MUNICIPIO_PRESTACION"]    = df["MUNICIPIO_PRESTACION"].astype("string")
df["NOMBRE"]                  = df.get("NOMBRE", pd.Series(index=df.index, dtype="string")).astype("string")

# ===================== Per-row service flags =====================
serv = (
    df["SERVICIO"]
      .astype("string")
      .str.upper()
      .str.strip()
      .fillna("")
)

# Propagate AAA to the three services
df["has_acueducto"]      = serv.str.contains(r"\bACUEDUCTO\b|AAA", na=False).astype("int8")
df["has_alcantarillado"] = serv.str.contains(r"\bALCANTARILLADO\b|AAA", na=False).astype("int8")
df["has_aseo"]           = serv.str.contains(r"\bASEO\b|AAA", na=False).astype("int8")

# Classification per row
def classify_row(a, al, aseo):
    if a and al and aseo: return "AAA (Acueducto+Alcantarillado+Aseo)"
    if a and al and not aseo: return "Acueducto + Alcantarillado"
    if a and not al and aseo: return "Acueducto + Aseo"
    if not a and al and aseo: return "Alcantarillado + Aseo"
    if a and not al and not aseo: return "Only Acueducto"
    if not a and al and not aseo: return "Only Alcantarillado"
    if not a and not al and aseo: return "Only Aseo"
    return "No service"

df["clasificacion"] = df.apply(
    lambda r: classify_row(int(r["has_acueducto"]), int(r["has_alcantarillado"]), int(r["has_aseo"])),
    axis=1
)

# =========================================================
# KPI 1. Dataset summary (with AAA percentage at provider+location level)
# =========================================================
# Group by provider + location (in-memory; we don't drop raw rows on disk)
KEY = ["NIT", "NOMBRE", "DEPARTAMENTO_PRESTACION", "MUNICIPIO_PRESTACION"]
g = (df.groupby(KEY, dropna=False)[["has_acueducto", "has_alcantarillado", "has_aseo"]]
       .max()
       .reset_index())

# AAA = A=1 & Al=1 & Aseo=1
mask_AAA_group = (g["has_acueducto"] == 1) & (g["has_alcantarillado"] == 1) & (g["has_aseo"] == 1)
pct_AAA_groups = round(mask_AAA_group.mean() * 100, 2)

summary = {
    "rows_raw": len(df),
    "unique_providers_by_name": df["NOMBRE"].nunique(dropna=True),
    "departments_covered": df["DEPARTAMENTO_PRESTACION"].fillna("NO_DATA").nunique(),
    "municipalities_covered": df["MUNICIPIO_PRESTACION"].fillna("NO_DATA").nunique(),
    "pct_AAA_groups": pct_AAA_groups
}
pd.Series(summary, name="value").to_csv(REPORTS_DIR / "kpi_summary.csv", header=True, encoding="utf-8")

# =========================================================
# KPI 2. National coverage — HEAT MAPS
#   A) Departments: number of rows per department
#   B) Municipalities (AA only): top 15 municipalities with both Acueducto+Alcantarillado
# =========================================================

# --- A) Heatmap by Department ---
dept_hm = (
    df["DEPARTAMENTO_PRESTACION"]
      .fillna("NO_DATA")
      .replace(DEPT_RENAME)
      .value_counts()
      .rename_axis("DEPARTAMENTO_PRESTACION")
      .reset_index(name="count")
)
if EXCLUDE_BOGOTA_TOP_DEPTS:
    dept_hm = dept_hm[~dept_hm["DEPARTAMENTO_PRESTACION"].str.contains("BOGOT", case=False, na=False)]

dept_hm = dept_hm.sort_values("count", ascending=True).set_index("DEPARTAMENTO_PRESTACION")

plt.figure(figsize=(9, max(6, len(dept_hm)*0.28)))
sns.heatmap(
    dept_hm[["count"]],
    cmap="YlGnBu",
    annot=True, fmt="d",
    cbar=False,
    linewidths=0.5, linecolor="#eee",
)
plt.title("National coverage — records per Department")
plt.xlabel("")
plt.ylabel("Department")
plt.tight_layout()
plt.savefig(IMAGES_DIR / "kpi_coverage_heatmap_department.png", dpi=150, bbox_inches="tight")
plt.close()


# --- B) Heatmap by Municipality (AA = Water + Sewer) — Bottom 10 ---
# Nota: agregamos temporalmente por prestador+ubicación para detectar AA real
KEY_AA = ["DEPARTAMENTO_PRESTACION", "MUNICIPIO_PRESTACION", "NIT"]

agg_aa = (
    df.assign(
        DEPARTAMENTO_PRESTACION=df["DEPARTAMENTO_PRESTACION"].fillna("NO_DATA").replace(DEPT_RENAME),
        MUNICIPIO_PRESTACION=df["MUNICIPIO_PRESTACION"].fillna("NO_DATA"),
    )
    .groupby(KEY_AA, dropna=False)[["has_acueducto", "has_alcantarillado"]]
    .max()  # OR lógico entre filas del mismo prestador-ubicación
    .reset_index()
)


agg_aa["AA_provider"] = (agg_aa["has_acueducto"] == 1) & (agg_aa["has_alcantarillado"] == 1)

muni_aa_counts = (
    agg_aa.groupby(["DEPARTAMENTO_PRESTACION", "MUNICIPIO_PRESTACION"], dropna=False)["AA_provider"]
          .sum()  # suma de True -> número de prestadores AA
          .astype(int)
          .reset_index(name="count")
)


if EXCLUDE_BOGOTA_TOP_DEPTS:
    muni_aa_counts = muni_aa_counts[~muni_aa_counts["DEPARTAMENTO_PRESTACION"]
                                     .str.contains("BOGOT", case=False, na=False)]


muni_aa_counts = muni_aa_counts[muni_aa_counts["count"] > 0]

# “Bottom 10” (los 10 con menor número de prestadores AA)
muni_aa_bottom10 = (
    muni_aa_counts.sort_values("count", ascending=True)
                  .head(10)
                  .copy()
)


muni_aa_bottom10["DEP_MUN"] = (
    muni_aa_bottom10["DEPARTAMENTO_PRESTACION"].astype(str) + " — " +
    muni_aa_bottom10["MUNICIPIO_PRESTACION"].astype(str)
)

# Si hay datos, graficamos
if not muni_aa_bottom10.empty:
    plot_df = (muni_aa_bottom10[["DEP_MUN", "count"]]
               .set_index("DEP_MUN")
               .sort_values("count", ascending=True))

    plt.figure(figsize=(10, max(5, len(plot_df) * 0.35)))  # alto dinámico
    sns.heatmap(
        plot_df[["count"]],
        cmap="YlOrRd",
        annot=True, fmt="d",
        cbar=False,
        linewidths=0.5, linecolor="#eee",
    )
    plt.title("National coverage — Bottom 10 municipalities with AA (Water + Sewer)")
    plt.xlabel("")
    plt.ylabel("Department — Municipality")
    plt.tight_layout()
    plt.savefig(IMAGES_DIR / "kpi_coverage_heatmap_municipality_bottom10_AA.png",
                dpi=150, bbox_inches="tight")
    plt.close()
else:
    print("Warning: No municipalities have AA (Water + Sewer) after grouping providers. Heatmap not generated.")

# =========================================================
# KPI 3. Density proxy by department (records per unique municipality)
#       (Bogotá D.C. excluded for scale; San Andrés label shortened)
# =========================================================
tmp = pd.DataFrame({
    "DEP": df["DEPARTAMENTO_PRESTACION"].fillna("NO_DATA").replace(DEPT_RENAME),
    "MUN": df["MUNICIPIO_PRESTACION"].fillna("NO_DATA"),
})
tmp_no_bogota = tmp[~tmp["DEP"].str.contains("BOGOT", case=False, na=False)].copy()
tmp_no_bogota["DEP"] = tmp_no_bogota["DEP"].replace(DEPT_RENAME)

dept_muni_nb = tmp_no_bogota.groupby("DEP", dropna=False)["MUN"].nunique().rename("unique_municipalities")
dept_regs_nb = tmp_no_bogota["DEP"].value_counts().rename("records")
density_nb = pd.concat([dept_regs_nb, dept_muni_nb], axis=1)
density_nb["records_per_municipality"] = density_nb["records"] / density_nb["unique_municipalities"].replace(0, np.nan)

density_nb.sort_values("records_per_municipality").to_csv(
    REPORTS_DIR / "density_department_excl_bogota.csv", encoding="utf-8"
)

dens_sorted_nb = density_nb["records_per_municipality"].sort_values(ascending=True).reset_index()
dens_sorted_nb.columns = ["DEPARTAMENTO_PRESTACION", "records_per_municipality"]
dens_sorted_nb["DEPARTAMENTO_PRESTACION"] = dens_sorted_nb["DEPARTAMENTO_PRESTACION"].replace({
    "ARCHIPIÉLAGO DE SAN ANDRÉS, PROVIDENCIA Y SANTA CATALINA": "San Andrés & Prov."
})

plt.figure(figsize=(12, 5))
sns.barplot(data=dens_sorted_nb, x="DEPARTAMENTO_PRESTACION", y="records_per_municipality")
plt.title("Density (records per municipality) by Department — Bogotá D.C. excluded")
plt.xlabel("Department")
plt.ylabel("Records / Municipality (proxy)")
plt.xticks(rotation=60, ha="right")
plt.tight_layout()
plt.savefig(IMAGES_DIR / "kpi_density_records_per_municipality_excl_bogota.png", dpi=150, bbox_inches="tight")
plt.close()


# =========================================================
# KPI 4. Water vs Sewer coverage by municipality (AA gap)
# =========================================================

# Optional focus: operational providers only (keeps all other nulls)
if "ESTADO" in df.columns:
    df_kpi = df[df["ESTADO"].str.contains(r"OPERATIVA", case=False, na=False)].copy()
else:
    df_kpi = df.copy()

# Group at municipality level: a municipality "has" a service if any provider there has it
muni_flags = (
    df_kpi
    .groupby(["DEPARTAMENTO_PRESTACION", "MUNICIPIO_PRESTACION"], dropna=False)[["has_acueducto", "has_alcantarillado"]]
    .max()
    .reset_index()
)

# Human-friendly labels (without destroying null information)
muni_flags["DEP_LABEL"] = muni_flags["DEPARTAMENTO_PRESTACION"].fillna("NO_DATA")
muni_flags["MUN_LABEL"] = muni_flags["MUNICIPIO_PRESTACION"].fillna("NO_DATA")

# Combo classification
def _combo(a, l):
    if a == 1 and l == 1: return "Both"
    if a == 1 and l == 0: return "Water only"
    if a == 0 and l == 1: return "Sewer only"
    return "None"

muni_flags["combo"] = muni_flags.apply(
    lambda r: _combo(int(r["has_acueducto"]), int(r["has_alcantarillado"])), axis=1
)

# Save final KPI result
muni_flags.to_csv(REPORTS_DIR / "kpi_water_vs_sewer_by_municipality_flags.csv", index=False, encoding="utf-8")

# Plot: summary of combo distribution
combo_summary = (
    muni_flags["combo"]
    .value_counts(dropna=False)
    .rename_axis("combo")
    .reset_index(name="municipalities")
    .sort_values("municipalities", ascending=False)
)

plt.figure(figsize=(8, 5))
sns.barplot(data=combo_summary, x="combo", y="municipalities")
plt.title("Municipalities by Service Combination (Water vs Sewer)")
plt.xlabel("Combination")
plt.ylabel("Number of Municipalities")
plt.tight_layout()
plt.savefig(IMAGES_DIR / "kpi_water_vs_sewer_by_municipality_combo_summary.png", dpi=200)
plt.close()



# =========================================================
# KPI 5. AA rate by department (% municipalities with Water & Sewer)
# =========================================================

# Focus on operational providers if present
if "ESTADO" in df.columns:
    df_kpi2 = df[df["ESTADO"].str.contains(r"OPERATIVA", case=False, na=False)].copy()
else:
    df_kpi2 = df.copy()

# Municipality-level flags (any provider in that municipality)
muni_flags_aa = (
    df_kpi2
    .groupby(["DEPARTAMENTO_PRESTACION", "MUNICIPIO_PRESTACION"], dropna=False)[
        ["has_acueducto", "has_alcantarillado"]
    ].max()
    .reset_index()
)

# Label for display (keep nulls in original columns; only fill for labels)
muni_flags_aa["DEP_LABEL"] = (
    muni_flags_aa["DEPARTAMENTO_PRESTACION"].fillna("NO_DATA")
)

# Department summary:
# denom = unique municipalities seen for that department (incl. NO_DATA)
# numer = municipalities with both services (AA)
dept_den = (
    muni_flags_aa.groupby("DEP_LABEL", dropna=False)["MUNICIPIO_PRESTACION"]
    .nunique(dropna=False)
    .rename("municipalities_total")
)
dept_num = (
    muni_flags_aa[(muni_flags_aa["has_acueducto"] == 1) & (muni_flags_aa["has_alcantarillado"] == 1)]
    .groupby("DEP_LABEL", dropna=False)["MUNICIPIO_PRESTACION"]
    .nunique(dropna=False)
    .rename("municipalities_AA")
)

dept_aa_rate = (
    pd.concat([dept_den, dept_num], axis=1).fillna(0)
    .assign(aa_rate_pct=lambda d: (d["municipalities_AA"] / d["municipalities_total"].replace(0, np.nan) * 100))
    .reset_index()
    .rename(columns={"DEP_LABEL": "DEPARTAMENTO_PRESTACION"})
)

# Sort descending by AA rate (then by total municipalities for stability)
dept_aa_rate = dept_aa_rate.sort_values(
    by=["aa_rate_pct", "municipalities_total"], ascending=[False, False]
)

# Save final KPI result (single CSV)
dept_aa_rate.to_csv(REPORTS_DIR / "kpi_aa_rate_by_department.csv", index=False, encoding="utf-8")

# Plot: AA rate by department — horizontal bar chart, sorted descending
sorted_data = dept_aa_rate.sort_values("aa_rate_pct", ascending=False)

plt.figure(figsize=(10, 12))
sns.barplot(
    data=sorted_data,
    y="DEPARTAMENTO_PRESTACION",
    x="aa_rate_pct",
    palette="Blues_d"
)
plt.title("AA Rate by Department (% of municipalities with Water & Sewer)")
plt.xlabel("AA Rate (%)")
plt.ylabel("Department")
plt.xlim(0, 100)
plt.tight_layout()
plt.savefig(IMAGES_DIR / "kpi_aa_rate_by_department.png", dpi=200)
plt.close()


# =========================================================
# KPI 6. Services by Department (sum of per-row flags) — top 12
# =========================================================
dept_flags = pd.DataFrame({
    "DEP": df["DEPARTAMENTO_PRESTACION"].fillna("NO_DATA").replace(DEPT_RENAME),
    "has_acueducto": df["has_acueducto"],
    "has_alcantarillado": df["has_alcantarillado"],
    "has_aseo": df["has_aseo"],
})
agg = dept_flags.groupby("DEP")[["has_acueducto", "has_alcantarillado", "has_aseo"]].sum()
agg = agg.sort_values("has_acueducto", ascending=False).head(12)
agg_long = agg.reset_index().melt(id_vars="DEP", var_name="service", value_name="count")
plt.figure(figsize=(12, 5))
sns.barplot(data=agg_long, x="DEP", y="count", hue="service")
plt.title("Services by Department — top 12 (sum of row flags)")
plt.xlabel("Department")
plt.ylabel("Counts (sum of row flags)")
plt.xticks(rotation=45, ha="right")
plt.legend(title="Service")
plt.tight_layout()
plt.savefig(IMAGES_DIR / "kpi_services_by_department_top12.png", dpi=150, bbox_inches="tight")
plt.close()

# =========================================================
# KPI 7. STATUS × Service (per row) — if ESTADO present
# =========================================================


# =========================================================
# Extra: Department-level map-friendly table (row sums)
# =========================================================
dept_totals_rows = dept_flags.groupby("DEP").agg(
    records=("DEP", "count"),
    acueducto=("has_acueducto", "sum"),
    alcantarillado=("has_alcantarillado", "sum"),
    aseo=("has_aseo", "sum"),
).sort_values("records", ascending=False)
dept_totals_rows.to_csv(REPORTS_DIR / "map_input_department_rows.csv", encoding="utf-8")

# ===================== Console output =====================
print("\n--- KPIs generated ---")
print("Raw rows:", len(df))
print("Departments (any value incl. NO_DATA):", summary["departments_covered"])
print("Municipalities (any value incl. NO_DATA):", summary["municipalities_covered"])
print("CSVs ->", REPORTS_DIR.as_posix())
print("PNGs ->", IMAGES_DIR.as_posix())

