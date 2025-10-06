"""
populate_experiment.py
Populate DB with a 2^4 full-factorial DOE (3 replicates, 48 wells)
for Span 80 water-in-oil emulsion screening.

Assumes the model classes in experiment.py / plate.py live
in the same directory (or are import-able on your PYTHONPATH).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from itertools import product
from services import AppConfig, DatabaseService


# ── local model classes ─────────────────────────────────────────
from models import Plate, Experiment, Sample

config = AppConfig("./config.yaml")
db = DatabaseService(config.get("sqlite_db"))

LEVELS = {
    "pipette": ["P300"],
    "mix_volume": [30],
    "dispense_flowRate": [50.0, 100.0, 150.0],
    "times": [10, 20],
    "mix_mmFromBottom": [0.2, 0.8],
    "surfactant_fraction":  [2.00]
}
factor_order = list(LEVELS.keys())   # keep key order stable
factor_grid  = list(product(*(LEVELS[f] for f in factor_order)))   # 16 tuples
# ----------------------------------------------------------------

# 6. ── simple well-assignment helper ────────────────────────────
def next_well_coordinates(idx: int):
    """
    Returns (row, column) for a 384-well plate (using only 12 rows × 20 cols),
    filling rows A..H left-to-right, top-to-bottom.

    idx : 0-based linear index
    """
    row = 2 + idx // 20   # 3-22  (A-H)
    col = 2 + idx % 20    # 3-14 (1-12)
    return row, col    # store as integers

# 7. ── populate 48 wells (3 replicates × 16 conditions) ─────────
well_idx = 0
for rep in range(3):                     # replicate blocks
    for combo in factor_grid:            # 16 factorial points
        row, col = next_well_coordinates(well_idx)
        well_idx += 1

        sample = Sample(
            experiment_id=0,
            well_row=row,
            well_column=col,
            mix_cycles=combo[factor_order.index("times")],
            mix_aspirate=combo[factor_order.index("dispense_flowRate")],
            mix_dispense=combo[factor_order.index("dispense_flowRate")],
            mix_volume=combo[factor_order.index("mix_volume")],
            mix_height=combo[factor_order.index("mix_mmFromBottom")],
            pipette=combo[factor_order.index("pipette")],
            surfactant_percent=combo[factor_order.index("surfactant_fraction")]
        )

        sample.id = db.add_sample(sample)
        print(f"Adding sample {sample.id} at ({row}, {col}) with factors {combo}")


# 8. ── commit all objects ───────────────────────────────────────
print(f"✓  samples written")
