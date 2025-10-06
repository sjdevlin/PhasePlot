#!/usr/bin/env python3
"""
Visualise how three mixing parameters simultaneously affect droplet
mean size and variance, for experiment_id = 1.

Requires: pandas, plotly, sqlalchemy, database_service + ORM models.
"""

import pandas as pd
import plotly.express as px

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


PIXEL_TO_MICRON = 0.44
EXPERIMENT_ID   = 1

# Pull data ---------------------------------------------------------------------------------
session = db.Session()

rows = (
    session.query(
        Image.average_droplet_size.label("avg_px"),
        Image.standard_deviation_droplet_size.label("std_px"),
        Sample.mix_cycles,
        Sample.mix_height,
        Sample.mix_dispense,
    )
    .join(Sample, Image.sample_id == Sample.id)
    .filter(Sample.experiment_id == EXPERIMENT_ID, Image.average_droplet_size > 30.0)
    .all()
)
df = pd.DataFrame(rows)
session.close()

if df.empty:
    raise ValueError(f"No rows found for experiment_id = {EXPERIMENT_ID}")

# Convert to microns ------------------------------------------------------------------------
df["avg_um"] = df["avg_px"] * PIXEL_TO_MICRON
df["std_um"] = df["std_px"] * PIXEL_TO_MICRON


# ----------------------------------------------------------------------------
# AFTER you have your tidy dataframe `df` with columns
#   mix_cycles, mix_height, mix_dispense, avg_um, std_um
# ----------------------------------------------------------------------------
agg_df = (
    df
    .groupby(["mix_cycles", "mix_height", "mix_dispense"], as_index=False)
    .agg(
        avg_um=("avg_um", "mean"),      # mean of the means
        std_um=("std_um", "mean"),      # mean of the std-devs (or use .agg("median"))
        n=("avg_um", "size"),           # how many replicates went into each point
    )
)

print(f"{len(agg_df)} unique mixing settings found")   # should be 12
print (agg_df)



# Normalise bubble radius for nicer sizing
size_scale = 80 / agg_df["std_um"].max()          # tweak multiplier as needed
agg_df["bubble_radius"] = agg_df["std_um"] * size_scale

# 1) Colour = mean, size = std-dev ----------------------------------------------------------
fig_mean_colour = px.scatter_3d(
    agg_df,
    x="mix_cycles",
    y="mix_height",
    z="mix_dispense",
    color="avg_um",
    range_color=[agg_df["avg_um"].min(), agg_df["avg_um"].max()],
    color_continuous_scale="Viridis",
    size="bubble_radius",
    size_max=80,
    title=f"Experiment {EXPERIMENT_ID}: Mean droplet size (colour) & std-dev (bubble)",
    labels=dict(
        mix_cycles="Mix cycles",
        mix_height="Mix height",
        mix_dispense="Mix dispense",
        avg_um="Mean size (µm)",
    ),
)

fig_mean_colour.update_layout(scene=dict(
    xaxis=dict(range=[5, 25]),
    yaxis=dict(range=[0, 1]),
    zaxis=dict(range=[20, 200])
))

# 2) Colour = std-dev, size = mean ----------------------------------------------------------
size_scale2 = 80 / agg_df["avg_um"].max()
agg_df["bubble_radius2"] = agg_df["avg_um"] * size_scale2

fig_std_colour = px.scatter_3d(
    agg_df,
    x="mix_cycles",
    y="mix_height",
    z="mix_dispense",
    color="std_um",
    range_color=[agg_df["std_um"].min(), agg_df["std_um"].max()],
    color_continuous_scale="Plasma",
    size="bubble_radius2",
    size_max=80,
    title=f"Experiment {EXPERIMENT_ID}: Std-dev (colour) & mean size (bubble)",
    labels=dict(
        mix_cycles="Mix cycles",
        mix_height="Mix height",
        mix_dispense="Mix dispense",
        std_um="Std-dev (µm)",
    ),
)
fig_std_colour.update_layout(scene=dict(
    xaxis=dict(range=[5, 25]),
    yaxis=dict(range=[0, 1]),
    zaxis=dict(range=[20, 200]),
))

# Show both in browser (or save with fig.write_html)
fig_mean_colour.show()
fig_std_colour.show()