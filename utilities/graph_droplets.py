#!/usr/bin/env python3
"""
Plot droplet-size metrics for experiment_id = 1.

Graphs produced (all in microns):
  1. average_droplet_size   vs mix_cycles
  2. average_droplet_size   vs mix_height
  3. average_droplet_size   vs mix_dispense
  4. std_dev_droplet_size   vs mix_cycles
  5. std_dev_droplet_size   vs mix_height
  6. std_dev_droplet_size   vs mix_dispense
"""

import pandas as pd
import matplotlib.pyplot as plt
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --------------------------------------------------------------------------- #
# 1️⃣  Database session & models
# --------------------------------------------------------------------------- #
from models import Sample, Image            # noqa: F401 (imported for completeness)
from services import AppConfig, DatabaseService

config = AppConfig("./config.yaml")
db = DatabaseService(config.get("sqlite_db"))

PIXEL_TO_MICRON = 0.44  # µm per pixel
EXPERIMENT_ID   = 1

# Get a live SQLAlchemy session

# --------------------------------------------------------------------------- #
# 2️⃣  Pull data
# --------------------------------------------------------------------------- #
session = db.Session()
rows = (
    session.query(
        Image.average_droplet_size.label("avg_px"),
        Image.standard_deviation_droplet_size.label("std_px"),
        Sample.mix_cycles.label("mix_cycles"),
        Sample.mix_height.label("mix_height"),
        Sample.mix_dispense.label("mix_dispense"),
    )
    .join(Sample, Image.sample_id == Sample.id)
    .filter(Sample.experiment_id == EXPERIMENT_ID, Image.average_droplet_size > 30.0)  # filter out noise
    .all()
)

df = pd.DataFrame(rows)
if df.empty:
    raise RuntimeError(f"No data found for experiment_id={EXPERIMENT_ID}")

# --------------------------------------------------------------------------- #
# 3️⃣  Unit conversion & housekeeping
# --------------------------------------------------------------------------- #
df["avg_um"] = df["avg_px"]  * PIXEL_TO_MICRON
df["std_um"] = df["std_px"]  * PIXEL_TO_MICRON

# ----------------------------------------------------------------------------
# AFTER you have your tidy dataframe `df` with columns
#   mix_cycles, mix_height, mix_dispense, avg_um, std_um
# ----------------------------------------------------------------------------
# Aggregate replicates + compute SEMs
agg_df = (
    df.groupby(["mix_cycles", "mix_height", "mix_dispense"], as_index=False)
      .agg(
          avg_um      = ("avg_um",  "mean"),
          std_um      = ("std_um",  "mean"),
          sem_avg_um  = ("avg_um",  "sem"),   # ± error bars for the mean
          sem_std_um  = ("std_um",  "sem"),   # ± error bars for the std-dev
          n           = ("avg_um",  "size"),  # replication count (sanity-check)
      )
)

print(f"{len(agg_df)} unique mixing settings found")   # should be 12
print (agg_df)

# Axis limits (µm) per user-supplied pixel ranges × 0.44
AX_LIM = {
    "avg_um": (100 * PIXEL_TO_MICRON, 300 * PIXEL_TO_MICRON),   # (44, 132)
    "std_um": (50  * PIXEL_TO_MICRON, 200 * PIXEL_TO_MICRON),   # (22,  88)
    "mix_cycles":   (5,   25),
    "mix_height":   (0,    1),
    "mix_dispense": (20, 200),
}

# --------------------------------------------------------------------------- #
# 4️⃣  Plotting
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 4️⃣  Plotting with error bars & trend lines - Save as separate PNG files
# --------------------------------------------------------------------------- #

plots = [
    ("mix_cycles",   "avg_um", "sem_avg_um",
     "Mix cycles",            "Average droplet size (µm)", "avg_vs_cycles"),
    ("mix_height",   "avg_um", "sem_avg_um",
     "Mix height (mm)",        "Average droplet size (µm)", "avg_vs_height"),
    ("mix_dispense", "avg_um", "sem_avg_um",
     "Mix dispense (µL/s)",   "Average droplet size (µm)", "avg_vs_dispense"),
    ("mix_cycles",   "std_um", "sem_std_um",
     "Mix cycles",            "Std-dev droplet size (µm)", "std_vs_cycles"),
    ("mix_height",   "std_um", "sem_std_um",
     "Mix height (mm)",        "Std-dev droplet size (µm)", "std_vs_height"),
    ("mix_dispense", "std_um", "sem_std_um",
     "Mix dispense (µL/s)",   "Std-dev droplet size (µm)", "std_vs_dispense"),
]

import numpy as np

for xcol, ycol, errcol, xlabel, ylabel, filename in plots:
    # Create individual figure for each plot
    fig, ax = plt.subplots(figsize=(8, 6))
    
    # scatter with vertical error bars
    ax.errorbar(agg_df[xcol], agg_df[ycol],
                yerr=agg_df[errcol], fmt="o", capsize=4, label="data")

    # 1st-order least-squares fit
    coeffs = np.polyfit(agg_df[xcol], agg_df[ycol], deg=1)
    xfit   = np.linspace(AX_LIM[xcol][0], AX_LIM[xcol][1], 100)
    yfit   = np.polyval(coeffs, xfit)
    ax.plot(xfit, yfit, "--", color="tab:red",
            label=f"fit: y = {coeffs[0]:.3g}x + {coeffs[1]:.3g}")

    # R²
    ss_res = np.sum((agg_df[ycol] - np.polyval(coeffs, agg_df[xcol]))**2)
    ss_tot = np.sum((agg_df[ycol] - agg_df[ycol].mean())**2)
    r2     = 1 - ss_res/ss_tot
    ax.text(0.05, 0.95, f"$R^2$ = {r2:.3f}",
            transform=ax.transAxes, ha="left", va="top",
            fontsize=9, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none"))

    # cosmetics
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(f"Experiment {EXPERIMENT_ID}: {ylabel} vs {xlabel}", fontsize=14)
    ax.set_xlim(*AX_LIM[xcol])
    ax.set_ylim(*AX_LIM["avg_um"] if "avg" in ycol else AX_LIM["std_um"])
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(loc="lower right", fontsize=10)
    
    # Save as PNG file
    output_file = f"experiment_{EXPERIMENT_ID}_{filename}.png"
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()  # Close the figure to free memory

print("All graphs saved successfully!")