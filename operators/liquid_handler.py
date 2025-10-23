from __future__ import annotations

"""
Operator for generating an Opentrons OT-2 Python protocol for a given Experiment
and persisting matching Sample records. Uses DatabaseService for DB ops and
AppConfig for output location.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict
import random

from services import AppConfig, Logger
from models import Experiment, Sample, LiquidProtocol

ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def well_to_rc(well: str) -> Tuple[int, int]:
    """Convert a well name like 'A1' -> (row_idx, col_idx) using 0-based indices."""
    well = well.strip().upper()
    row_letter = well[0]
    col_num = int(well[1:])
    return ROW_LETTERS.index(row_letter), col_num - 1


@dataclass
class LiquidHandler:
    """Generates a Python protocol script for the Opentrons OT-2.

    __init__(db, experiment):
      - Stores protocol_id from experiment
      - Retrieves Plate by id and stores plate.opentrons_name
    generate():
      - Writes a Python protocol file and stores its path in script_location
      - Determines destination wells for Samples and persists Sample records
    """

    db: object
    experiment: Experiment

    def __post_init__(self):
        self.logger = Logger()
        self.app_config = AppConfig()

        # 1) store protocol id
        self.protocol_id = getattr(self.experiment, "liquid_protocol_id", None)

        # 2) retrieve plate and 3) store opentrons_name
        plate = self.db.get_plate_by_id(self.experiment.plate_id)
        self.opentrons_name = getattr(plate, "opentrons_name", None)

        self.script_location: Path | None = None

    # convenience initializer because dataclass doesn't call __post_init__ unless used
    def __init__(self, db, experiment: Experiment):
        object.__setattr__(self, "db", db)
        object.__setattr__(self, "experiment", experiment)
        self.__post_init__()

    # ─────────────────────────────────────────────────────────────
    def _load_protocol(self) -> LiquidProtocol:
        """Fetch the LiquidProtocol row for this experiment."""
        # Use DatabaseService session via a small helper if not exposed directly
        # Prefer a dedicated accessor if available; here we fall back to ORM.
        try:
            # Try attribute first in case DatabaseService exposes this in future
            get_lp = getattr(self.db, "get_liquid_protocol_by_id", None)
            if callable(get_lp):
                lp = get_lp(self.protocol_id)
            else:
                # Direct session usage (contained) as a fallback
                session = self.db.Session()
                try:
                    lp = session.query(LiquidProtocol).filter_by(id=self.protocol_id).first()
                finally:
                    session.close()
            if lp is None:
                raise RuntimeError(f"LiquidProtocol id={self.protocol_id} not found")
            return lp
        except Exception as e:
            self.logger.error(f"Failed to load LiquidProtocol: {e}")
            raise

    # ─────────────────────────────────────────────────────────────
    def _choose_destinations(self, plate_rows: int, plate_cols: int, stocks: List[str]) -> Dict[str, List[str]]:
        """Pick random destination wells per stock based on experiment.repeats.
        Returns map of stock_well -> list[well_name].
        """
        all_wells = [f"{ROW_LETTERS[r]}{c+1}" for r in range(plate_rows) for c in range(plate_cols)]
        # Avoid using stock wells as destinations
        available = [w for w in all_wells if w not in stocks]
        repeats = max(1, int(getattr(self.experiment, "repeats", 1) or 1))

        mapping: Dict[str, List[str]] = {}
        for stock in stocks:
            if len(available) < repeats:
                # Refill pool if we run out; allow re-use to proceed
                available = [w for w in all_wells if w not in stocks]
            picks = random.sample(available, k=repeats)
            mapping[stock] = picks
            # Remove picks from availability
            available = [w for w in available if w not in picks]
        return mapping

    # ─────────────────────────────────────────────────────────────
    def _stock_fractions(self, emulsion_wells: List[str]) -> List[Tuple[str, float]]:
        """Return list of (well_name, fraction) for the 8 stock wells as per dyadic scheme.
        Indices mapping from spec: [0..7] with specific composition.
        Fractions correspond to: 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100.
        """
        # Using positions described in the prompt
        idx_map = {
            3: 0.50,
            1: 0.25,
            5: 0.75,
            0: 0.125,
            2: 0.375,
            4: 0.625,
            6: 0.875,
            7: 1.0,
        }
        pairs = []
        for i, frac in idx_map.items():
            if i < 0 or i >= len(emulsion_wells):
                raise ValueError("protocol.emulsion_locations must contain 8 wells")
            pairs.append((emulsion_wells[i], frac))
        return pairs

    # ─────────────────────────────────────────────────────────────
    def _write_script(self, out_path: Path, lp: LiquidProtocol, dest_map: Dict[str, List[str]]) -> None:
        """Emit a self-contained Opentrons v2 Python protocol script."""
        # Pipette names
        mix_pip = "p20_single_gen2" if "20" in (lp.mix_pipette or "p20") else "p300_single_gen2"
        disp_pip = "p20_single_gen2" if "20" in (lp.dispense_pipette or "p20") else "p300_single_gen2"

        emulsion_list = [w.strip() for w in (lp.emulsion_locations or "").split(',') if w.strip()]
        # Compose python
        script = f'''"""
Auto-generated Opentrons protocol for Experiment {self.experiment.id}
Plate labware: {self.opentrons_name}
"""
from opentrons import protocol_api

metadata = {{"apiLevel": "2.14"}}

# user-config from DB
HOLD_TEMP_C = {lp.holding_temperature}
BUFFER_LOC = "{lp.buffer_location}"
NS_DENSE_LOC = "{lp.ns_dense_location}"
OIL_LOC = "{lp.oil_location}"
EMULSION_WELLS = {emulsion_list!r}
MIX_ASPIRATE = {lp.mix_aspirate_speed}
MIX_DISPENSE = {lp.mix_dispense_speed}
MIX_CYCLES = {lp.number_mix_cycles}
MIX_VOL = {lp.mix_volume}
MIX_Z_MM = {lp.mix_height_from_bottom}
FINAL_DISPENSE_UL = {lp.final_sample_dispense_volume}
SRC_BUFFER_VOL = {lp.source_buffer_volume}
SRC_NS_VOL = {lp.source_NS_dense_volume}
SRC_OIL_VOL = {lp.source_oil_volume}
PLATE_LABWARE = "{self.opentrons_name}"

# precomputed destinations for each stock well
DEST_MAP = {dest_map!r}


def run(protocol: protocol_api.ProtocolContext):
    # Load modules
    temperature_module_1 = protocol.load_module("temperatureModuleV1", "10")

    # Load labware
    tip_rack_1 = protocol.load_labware("opentrons_96_tiprack_20ul", location="2", namespace="opentrons", version=1)
    tip_rack_2 = protocol.load_labware("opentrons_96_tiprack_300ul", location="5", namespace="opentrons", version=1)
    well_plate_1 = protocol.load_labware(PLATE_LABWARE, location="8")
    aluminum_block_1 = temperature_module_1.load_labware("opentrons_24_aluminumblock_generic_2ml_screwcap", namespace="opentrons", version=3)

    # Load pipettes
    pipette_left = protocol.load_instrument("{mix_pip}", "left", tip_racks=[tip_rack_1])
    pipette_right = protocol.load_instrument("{disp_pip}", "right", tip_racks=[tip_rack_2])

    # Define liquids (visual grouping only; optional in code-only context)
    # Not strictly necessary for execution, but included for clarity

    # Heat and hold
    temperature_module_1.set_temperature(HOLD_TEMP_C)
    protocol.delay(minutes=30)

    # Mix NS_Dense (80% of starting volume) with mix pipette
    ns_mix_vol = max(1.0, SRC_NS_VOL * 0.8)
    ns_well = aluminum_block_1.wells_by_name()[NS_DENSE_LOC]
    pipette_left.pick_up_tip()
    pipette_left.mix(5, ns_mix_vol, ns_well.bottom(2))
    pipette_left.drop_tip()

    # Prepare references
    buffer_well = aluminum_block_1.wells_by_name()[BUFFER_LOC]
    oil_well = aluminum_block_1.wells_by_name()[OIL_LOC]

    # Helper to access plate wells by name
    def P(name: str):
        return well_plate_1.wells_by_name()[name]

    # Create dyadic dilution stocks using dispense pipette, single tip
    pr = pipette_right
    pr.pick_up_tip()
    # 50% at EMULSION_WELLS[3]: 20 uL Buffer + 20 uL NS_Dense
    pr.aspirate(20, buffer_well.bottom(2))
    pr.dispense(20, P(EMULSION_WELLS[3]))
    pr.aspirate(20, ns_well.bottom(2))
    pr.dispense(20, P(EMULSION_WELLS[3]))
    pr.mix(3, 30, P(EMULSION_WELLS[3]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[3]].top())

    # 25% at EMULSION_WELLS[1]: 10 uL Buffer + 10 uL of 50%
    pr.aspirate(10, buffer_well.bottom(2))
    pr.dispense(10, P(EMULSION_WELLS[1]))
    pr.aspirate(10, P(EMULSION_WELLS[3]].bottom(1))
    pr.dispense(10, P(EMULSION_WELLS[1]))
    pr.mix(3, 20, P(EMULSION_WELLS[1]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[1]].top())

    # 75% at EMULSION_WELLS[5]: 10 uL of 50% + 10 uL NS_Dense
    pr.aspirate(10, P(EMULSION_WELLS[3]].bottom(1))
    pr.dispense(10, P(EMULSION_WELLS[5]))
    pr.aspirate(10, ns_well.bottom(2))
    pr.dispense(10, P(EMULSION_WELLS[5]))
    pr.mix(3, 20, P(EMULSION_WELLS[5]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[5]].top())

    # 12.5% at EMULSION_WELLS[0]: 5 uL Buffer + 5 uL of 25%
    pr.aspirate(5, buffer_well.bottom(2))
    pr.dispense(5, P(EMULSION_WELLS[0]))
    pr.aspirate(5, P(EMULSION_WELLS[1]].bottom(1))
    pr.dispense(5, P(EMULSION_WELLS[0]))
    pr.mix(3, 10, P(EMULSION_WELLS[0]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[0]].top())

    # 37.5% at EMULSION_WELLS[2]: 5 uL of 25% + 5 uL of 50%
    pr.aspirate(5, P(EMULSION_WELLS[1]].bottom(1))
    pr.dispense(5, P(EMULSION_WELLS[2]))
    pr.aspirate(5, P(EMULSION_WELLS[3]].bottom(1))
    pr.dispense(5, P(EMULSION_WELLS[2]))
    pr.mix(3, 10, P(EMULSION_WELLS[2]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[2]].top())

    # 62.5% at EMULSION_WELLS[4]: 5 uL of 50% + 5 uL of 75%
    pr.aspirate(5, P(EMULSION_WELLS[3]].bottom(1))
    pr.dispense(5, P(EMULSION_WELLS[4]))
    pr.aspirate(5, P(EMULSION_WELLS[5]].bottom(1))
    pr.dispense(5, P(EMULSION_WELLS[4]))
    pr.mix(3, 10, P(EMULSION_WELLS[4]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[4]].top())

    # 87.5% at EMULSION_WELLS[6]: 5 uL of 75% + 5 uL of 100%
    pr.aspirate(5, P(EMULSION_WELLS[5]].bottom(1))
    pr.dispense(5, P(EMULSION_WELLS[6]))
    pr.aspirate(5, ns_well.bottom(2))
    pr.dispense(5, P(EMULSION_WELLS[6]))
    pr.mix(3, 10, P(EMULSION_WELLS[6]).bottom(1))
    pr.blow_out(P(EMULSION_WELLS[6]].top())

    # Finally: 100% in EMULSION_WELLS[7]
    pr.aspirate(10, ns_well.bottom(2))
    pr.dispense(10, P(EMULSION_WELLS[7]))
    pr.blow_out(P(EMULSION_WELLS[7]].top())

    # Keep same tip for all the above as requested
    pr.drop_tip()

    # For each stock: add 200 uL Oil, mix, then distribute FINAL_DISPENSE_UL to destinations
    for stock_well, dests in DEST_MAP.items():
        # Add oil using mix pipette with new tip
        pipette_left.pick_up_tip()
        pipette_left.aspirate(200, oil_well.bottom(2))
        pipette_left.dispense(200, P(stock_well))
        # mix in-place
        pipette_left.flow_rate.aspirate = MIX_ASPIRATE
        pipette_left.flow_rate.dispense = MIX_DISPENSE
        for _ in range(int(MIX_CYCLES)):
            pipette_left.aspirate(MIX_VOL, P(stock_well).bottom(MIX_Z_MM))
            pipette_left.dispense(MIX_VOL, P(stock_well).bottom(MIX_Z_MM))
        pipette_left.touch_tip(P(stock_well))
        pipette_left.drop_tip()

        # Distribute final volumes with right pipette
        pipette_right.pick_up_tip()
        for d in dests:
            pipette_right.aspirate(FINAL_DISPENSE_UL, P(stock_well).bottom(1))
            pipette_right.dispense(FINAL_DISPENSE_UL, P(d))
            pipette_right.blow_out(P(d).top())
        pipette_right.drop_tip()
'''
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(script)

    # ─────────────────────────────────────────────────────────────
    def generate(self) -> Path:
        """Generate protocol file and create Sample entries matching the dispense plan."""
        lp = self._load_protocol()

        # Parse emulsion wells (8 positions expected)
        emul_wells = [w.strip().upper() for w in (lp.emulsion_locations or "").split(',') if w.strip()]
        if len(emul_wells) != 8:
            raise ValueError("LiquidProtocol.emulsion_locations must list 8 wells, comma-separated")

        # Determine destination mapping per stock well
        # Infer plate grid from Plate size if available, else default to 6x6 for 36‑well
        # Attempt to read Plate from DB again to get num_rows/num_cols
        plate = self.db.get_plate_by_id(self.experiment.plate_id)
        rows = int(getattr(plate, "num_rows", 6) or 6)
        cols = int(getattr(plate, "num_cols", 6) or 6)

        stock_pairs = self._stock_fractions(emul_wells)
        stock_wells_order = [w for w, _ in stock_pairs]
        dest_map = self._choose_destinations(rows, cols, stock_wells_order)

        # Emit the python protocol file
        script_dir = Path(self.app_config.get("script_output_path", "./opentrons_protocols/script"))
        out_path = script_dir / f"exp_{self.experiment.id}.py"
        self._write_script(out_path, lp, dest_map)
        self.script_location = out_path

        # Create Sample records matching destinations
        max_ns = float(getattr(self.experiment, "max_ns_concentration", 0.0) or 0.0)
        # Map stock well -> fraction
        frac_by_stock = {w: frac for (w, frac) in stock_pairs}
        created = 0
        for stock_well, dests in dest_map.items():
            frac = frac_by_stock.get(stock_well, 0.0)
            ns_conc = frac * max_ns
            for dw in dests:
                r, c = well_to_rc(dw)
                sample = Sample(
                    experiment_id=self.experiment.id,
                    well_row=r,
                    well_column=c,
                    ns_concentration=ns_conc,
                )
                self.db.add_sample(sample)
                created += 1
        self.logger.info(f"Created {created} Sample rows for Experiment {self.experiment.id}")

        return out_path
