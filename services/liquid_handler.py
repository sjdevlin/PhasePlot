from __future__ import annotations

"""
Operator for generating an Opentrons OT-2 Python protocol for a given Experiment
and persisting matching Sample records. Uses DatabaseService for DB ops and
AppConfig for output location.
"""

from pathlib import Path
from typing import List, Tuple, Dict
import random

from services import AppConfig, Logger
from models import Experiment, Sample, LiquidProtocol, Plate, PlateWell

ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

class LiquidHandler:
    """Generates a Python protocol script for the Opentrons OT-2.

    __init__(db, experiment):
      - Stores protocol_id from experiment
      - Retrieves Plate by id and stores plate.opentrons_name
    generate():
      - Writes a Python protocol file and stores its path in script_location
      - Determines destination wells for Samples and persists Sample records
    """

    def __init__(self, db, experiment: Experiment):
        self.db = db
        self.experiment = experiment
        self.logger = Logger()
        self.app_config = AppConfig()

        # 1) store protocol id
        self.protocol_id = getattr(self.experiment, "liquid_protocol_id", None)

        # 2) retrieve plate and 3) store opentrons_name
        self.plate = self.db.get_plate_by_id(self.experiment.plate_id)

        self.script_location: Path | None = None


    # ─────────────────────────────────────────────────────────────
    def _choose_destinations(self, available_well_list: List[PlateWell], stocks: Dict[str, float]) -> Dict[str, List[str]]:
        """Pick random destination wells per stock based on experiment.repeats.
        Returns map of stock_well -> list[well_name].
        """
        solution_to_well_mapping: Dict[str, List[str]] = {}

        for stock_location in stocks.keys():            
            chosen_wells = random.sample(available_well_list, k=self.experiment.repeats)
            solution_to_well_mapping[stock_location] = [w.well_row + str(w.well_column) for w in chosen_wells]
            # Remove picks from availability
            available_well_list = [w for w in available_well_list if w not in chosen_wells]
        return solution_to_well_mapping

    # ─────────────────────────────────────────────────────────────
    def _write_script(self, out_path: Path, lp: LiquidProtocol, dest_map: Dict[str, List[str]]) -> None:
        """Emit a self-contained Opentrons v2 Python protocol script."""
        # Pipette names
        mix_pip = "p20_single_gen2" if "P20" in (lp.mix_pipette) else "p300_single_gen2"
        disp_pip = "p20_single_gen2" if "P20" in (lp.dispense_pipette) else "p300_single_gen2"

        # Compose python
        script = f'''"""
    Auto-generated Opentrons protocol for Experiment {self.experiment.id}
    Plate labware: {self.plate.opentrons_name}
    """
    from opentrons import protocol_api

    metadata = {{"apiLevel": "2.14"}}

    # user-config from DB
    HOLD_TEMP_C = {lp.holding_temperature}
    BUFFER_LOC = "{lp.buffer_location}"
    NS_DENSE_LOC = "{lp.ns_dense_location}"
    OIL_LOC = "{lp.oil_location}"
    STOCK_LOCATION = {[list(dest_map.keys())]!r}
    MIX_ASPIRATE = {lp.mix_aspirate_speed}
    MIX_DISPENSE = {lp.mix_dispense_speed}
    MIX_CYCLES = {lp.number_mix_cycles}
    MIX_VOL = {lp.mix_volume}
    MIX_Z_MM = {lp.mix_height_from_bottom}
    FINAL_DISPENSE_UL = {lp.final_sample_dispense_volume}
    SRC_BUFFER_VOL = {lp.source_buffer_volume}
    SRC_NS_VOL = {lp.source_NS_dense_volume}
    SRC_OIL_VOL = {lp.source_oil_volume}
    PLATE_LABWARE = "{self.plate.opentrons_name}"

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
        pipette_right = protocol.load_instrument("{mix_pip}", "right", tip_racks=[tip_rack_2])
        pipette_left = protocol.load_instrument("{disp_pip}", "left", tip_racks=[tip_rack_1])

        # Define liquids (visual grouping only; optional in code-only context)

        BUFFER = aluminum_block_1.wells_by_name()[BUFFER_LOC]
        NS_DENSE = aluminum_block_1.wells_by_name()[NS_DENSE_LOC]
        OIL = aluminum_block_1.wells_by_name()[OIL_LOC]

        LIQUID_VOLUMES = {{
        "buffer_stock_ul": SRC_BUFFER_VOL,
        "ns_dense_stock_ul": SRC_NS_VOL,
        "oil_stock_ul": SRC_OIL_VOL,
        "final_dispense_ul": FINAL_DISPENSE_UL,
        }}

        # Simple helper that emits comments describing where key reagents are located.
        # Uses concatenation (no inner f-strings) to avoid evaluation at generation time.
        def describe_liquids():
        protocol.comment("Buffer at " + BUFFER_LOC + ", stock ~" + str(LIQUID_VOLUMES['buffer_stock_ul']) + " uL")
        protocol.comment("NS dense at " + NS_DENSE_LOC + ", stock ~" + str(LIQUID_VOLUMES['ns_dense_stock_ul']) + " uL")
        protocol.comment("Oil at " + OIL_LOC + ", stock ~" + str(LIQUID_VOLUMES['oil_stock_ul']) + " uL")

        # Describe liquids (useful when running in simulation / debug)
        describe_liquids()

        # Heat and hold
        temperature_module_1.set_temperature(HOLD_TEMP_C)
        protocol.delay(minutes=30)

        # Mix NS_Dense (80% of starting volume) with mix pipette
        ns_mix_vol = max(20.0, SRC_NS_VOL * 0.8)
        ns_well = aluminum_block_1.wells_by_name()[NS_DENSE_LOC]
        pipette_left.pick_up_tip()
        pipette_left.mix(5, ns_mix_vol, ns_well.bottom(2))
        pipette_left.blow_out(ns_well.top())
        # Not dropping tip yet - will reuse since only one solution type and no cross-contamination risk

        # Prepare references
        buffer_well = aluminum_block_1.wells_by_name()[BUFFER_LOC]
        oil_well = aluminum_block_1.wells_by_name()[OIL_LOC]

        # Helper to access plate wells by name
        def P(name: str):
            return well_plate_1.wells_by_name()[name]


        # Create dyadic dilution stocks using dispense pipette, single tip
        pl = pipette_left
        pl.pick_up_tip()
        # 50% at STOCK_LOCATION[3]: 20 uL Buffer + 20 uL NS_Dense
        pl.aspirate(20, buffer_well.bottom(2))
        pl.dispense(20, P(STOCK_LOCATION[3])) # not great.  hardcoded index for 50% should be a better way !
        pl.aspirate(20, ns_well.bottom(2))
        pl.dispense(20, P(STOCK_LOCATION[3]))
        pl.mix(3, 30, P(STOCK_LOCATION[3]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[3]).top())

        # 25% at STOCK_LOCATION[1]: 10 uL Buffer + 10 uL of 50%
        pl.aspirate(10, buffer_well.bottom(2))
        pl.dispense(10, P(STOCK_LOCATION[1]))
        pl.aspirate(10, P(STOCK_LOCATION[3]).bottom(1))
        pl.dispense(10, P(STOCK_LOCATION[1]))
        pl.mix(3, 20, P(STOCK_LOCATION[1]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[1]).top())

        # 75% at STOCK_LOCATION[5]: 10 uL of 50% + 10 uL NS_Dense
        pl.aspirate(10, P(STOCK_LOCATION[3]).bottom(1))
        pl.dispense(10, P(STOCK_LOCATION[5]))
        pl.aspirate(10, ns_well.bottom(2))
        pl.dispense(10, P(STOCK_LOCATION[5]))
        pl.mix(3, 20, P(STOCK_LOCATION[5]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[5]).top())

        # 12.5% at STOCK_LOCATION[0]: 5 uL Buffer + 5 uL of 25%
        pl.aspirate(5, buffer_well.bottom(2))
        pl.dispense(5, P(STOCK_LOCATION[0]))
        pl.aspirate(5, P(STOCK_LOCATION[1]).bottom(1))
        pl.dispense(5, P(STOCK_LOCATION[0]))
        pl.mix(3, 10, P(STOCK_LOCATION[0]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[0]).top())

        # 37.5% at STOCK_LOCATION[2]: 5 uL of 25% + 5 uL of 50%
        pl.aspirate(5, P(STOCK_LOCATION[1]).bottom(1))
        pl.dispense(5, P(STOCK_LOCATION[2]))
        pl.aspirate(5, P(STOCK_LOCATION[3]).bottom(1))
        pl.dispense(5, P(STOCK_LOCATION[2]))
        pl.mix(3, 10, P(STOCK_LOCATION[2]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[2]).top())

        # 62.5% at STOCK_LOCATION[4]: 5 uL of 50% + 5 uL of 75%
        pl.aspirate(5, P(STOCK_LOCATION[3]).bottom(1))
        pl.dispense(5, P(STOCK_LOCATION[4]))
        pl.aspirate(5, P(STOCK_LOCATION[5]).bottom(1))
        pl.dispense(5, P(STOCK_LOCATION[4]))
        pl.mix(3, 10, P(STOCK_LOCATION[4]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[4]).top())

        # 87.5% at STOCK_LOCATION[6]: 5 uL of 75% + 5 uL of 100%
        pl.aspirate(5, P(STOCK_LOCATION[5]).bottom(1))
        pl.dispense(5, P(STOCK_LOCATION[6]))
        pl.aspirate(5, ns_well.bottom(2))
        pl.dispense(5, P(STOCK_LOCATION[6]))
        pl.mix(3, 10, P(STOCK_LOCATION[6]).bottom(1))
        pl.blow_out(P(STOCK_LOCATION[6]).top())

        # Finally: 100% in STOCK_LOCATION[7]
        pl.aspirate(10, ns_well.bottom(2))
        pl.dispense(10, P(STOCK_LOCATION[7]))
        pl.blow_out(P(STOCK_LOCATION[7]).top())

        # Keep same tip for all the above as requested
        pl.drop_tip()

        # For each stock: add 200 uL Oil, mix, then distribute FINAL_DISPENSE_UL to destinations
        for stock_well, dests in DEST_MAP.items():
            # Add oil using mix pipette with new tip
            pipette_right.pick_up_tip()
            pipette_right.aspirate(200, oil_well.bottom(2))
            pipette_right.dispense(200, P(stock_well))
            # mix in-place
            pipette_right.flow_rate.aspirate = MIX_ASPIRATE
            pipette_right.flow_rate.dispense = MIX_DISPENSE
            for _ in range(int(MIX_CYCLES)):
                pipette_right.aspirate(MIX_VOL, P(stock_well).bottom(MIX_Z_MM))
                pipette_right.dispense(MIX_VOL, P(stock_well).bottom(MIX_Z_MM))

            # Use distribute mode to dispense to all destinations in one go
            dest_wells = [well_plate_1.wells_by_name()[d] for d in dests]
            pipette_right.distribute(
                FINAL_DISPENSE_UL,
                P(stock_well).bottom(1),
                dest_wells,
                new_tip='never',
                disposal_volume=0
            )
            pipette_right.drop_tip()
        '''
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(script)

        # ─────────────────────────────────────────────────────────────
        def generate(self) -> Path:
            """Generate protocol file and create Sample entries matching the dispense plan."""


            liquid_protocol = self.db.get_liquid_protocol_by_id(self.protocol_id)
            available_well_list = self.plate.well

            # Parse emulsion wells (8 positions expected)
            # it is assumed that the stock locations are in the order of 0%, 12.5%, 25%, 37.5%, 50%, 62.5%, 75%, 87.5%
            stock_wells_and_fractions= {"B1":0.125,"B2":0.25,"B3":0.375,"B4":0.50,"B5":0.625,"B6":0.75,"C1":0.875,"C2":1.0}

            solution_to_well_mapping = self._choose_destinations(available_well_list, stock_wells_and_fractions)

            # Emit the python protocol file
            script_dir = Path(self.app_config.get("script_output_path", "./opentrons_protocols/script"))
            out_path = script_dir / f"exp_{self.experiment.id}.py"
            self._write_script(out_path, liquid_protocol, solution_to_well_mapping)
            self.script_location = out_path

            # Create Sample records matching destinations

            created = 0
            max_ns = liquid_protocol.max_ns_concentration

            for stock_well, dests in solution_to_well_mapping.items():
                # Determine fraction from stock_well position
                frac = stock_wells_and_fractions[stock_well]
                ns_conc = frac * max_ns
                for dw in dests:
                    sample = Sample(
                        experiment_id=self.experiment.id,
                        well_row=dw[0],
                        well_column=int(dw[1:]),
                        ns_concentration=ns_conc,
                    )
                self.db.add_sample(sample)
                created += 1
            self.logger.info(f"Created {created} Sample rows for Experiment {self.experiment.id}")

        return out_path
