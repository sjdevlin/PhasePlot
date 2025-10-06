# scriptfile_generator.py
import json
import uuid
from pathlib import Path
from typing import Dict

from models import Experiment
from services import AppConfig, Logger

ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class ScriptfileGenerator:
    """Generate an Opentrons JSON protocol for one Experiment."""

    # ─────────────────────────────────────────────────────────────
    def __init__(self, experiment: Experiment):
        self.experiment = experiment
        self.app_config = AppConfig()
        self.logger = Logger()

        self.template_path = Path(self.app_config.get("script_template"))
        self.script_path = (
            Path(self.app_config.get("script_output_path"))
            / f"exp_{experiment.id}.json"
        )

        # ── load template once ─────────────────────────────────
        with self.template_path.open() as f:
            self.proto = json.load(f)

        data = self.proto["designerApplication"]["data"]
        self.saved_steps: Dict[str, dict] = data["savedStepForms"]
        self.ordered_ids = data["orderedStepIds"]

        # handy IDs
        self.p20_id = next(
            pid for pid, spec in data["pipettes"].items()
            if spec["pipetteName"].startswith("p20")
        )

        self.p300_id = next(
            pid for pid, spec in data["pipettes"].items()
            if spec["pipetteName"].startswith("p300")
        )

        self.tube_rack_id = next(k for k in data["ingredLocations"] if "tuberack" in k)
        self.plate_id = next(k for k in data["labware"] if "wellplate" in k)

        # ── locate & store a *master* water step ───────────────
        self._stash_master_water_step()
        self._stash_master_oil_step()
        self._stash_master_mix_step()

    # ─────────────────────────────────────────────────────────────
    def _stash_master_water_step(self) -> None:
        water_step = next(
            (sid, s) for sid, s in self.saved_steps.items()
            if s.get("aspirate_wells") == ["A2"]  # A2 is the water source well
        )
        if not water_step:
            raise RuntimeError(
                "Template must contain at least one water step from A2."
            )
        self.water_step_id, self.distribute_water_step = water_step

    def _stash_master_oil_step(self) -> None:
        oil_step = next(
            (sid, s) for sid, s in self.saved_steps.items()
            if s.get("aspirate_wells") == ["A1"]  # A1 is the oil source well
        )
        if not oil_step:
            raise RuntimeError(
                "Template must contain at least one oil step from A1."
            )
        self.oil_step_id, self.distribute_oil_step = oil_step

    def _stash_master_mix_step(self) -> None:
        mix_step = next(
            (sid, s) for sid, s in self.saved_steps.items()
            if s.get("mix_mmFromBottom") is not None  # First step with mix_mmFromBottom value
        )
        if not mix_step:
            raise RuntimeError(
                "Template must contain at least one mix step"
            )
        self.mix_step_id, self.master_step = mix_step


    # ─────────────────────────────────────────────────────────────
    def _well_name(self, row: int, col: int) -> str:
        return f"{ROW_LETTERS[row]}{col + 1}"

    # ─────────────────────────────────────────────────────────────

    def _extend_water_step(
        self, wells) -> dict:
        """Clone master step → update target well + mixing params."""
        new = json.loads(json.dumps(self.distribute_water_step))  # deep copy
        new.update(
            {
                "dispense_wells": [wells],
                "disposalVolume_checkbox": True,
                "disposalVolume_volume": "2",
                "path": "multiDispense"
            }
        )
        return new

    def _extend_oil_step(
        self, wells) -> dict:
        """Clone master step → update target well + mixing params."""
        new = json.loads(json.dumps(self.distribute_oil_step))  # deep copy
        new.update(
            {
                "dispense_wells": [wells],
                "disposalVolume_checkbox": True,
                "disposalVolume_volume": "20",
                "path": "multiDispense"
            }
        )
        return new


    def _clone_mix_step(
        self, well: str, cycles: int, dis_speed: float, asp_speed: float, from_bottom: float, mix_volume: float
    ) -> dict:
        """Clone master step → update target well + mixing params."""
        new = json.loads(json.dumps(self.master_step))  # deep copy
        new_id = str(uuid.uuid4())
        new.update(
            {
                "id": new_id,
                "wells": [well],
                "times": str(cycles),
                "dispense_flowRate": str(dis_speed),
                "aspirate_flowRate": str(asp_speed),
                "mix_mmFromBottom": from_bottom,
            }
        )
        return new_id, new

    # ─────────────────────────────────────────────────────────────
    def generate(self) -> Path:
        """Build 48 water‑dispense steps (one per Sample) & write JSON."""

        # Collect all wells from samples
        all_wells = []
        for sample in self.experiment.sample:
            target_well = self._well_name(sample.well_row, sample.well_column)
            all_wells.append(target_well)

        # Replace master oil step with extended version
        extended_oil_step = self._extend_oil_step(all_wells)
        self.saved_steps[self.oil_step_id] = extended_oil_step

        # Replace master water step with extended version  
        extended_water_step = self._extend_water_step(all_wells)
        self.saved_steps[self.water_step_id] = extended_water_step

        # Add individual mix steps for each sample
        for sample in self.experiment.sample:
            target_well = self._well_name(sample.well_row, sample.well_column)
            dispense_speed = sample.mix_dispense
            aspirate_speed = sample.mix_aspirate
            num_cycles = sample.mix_cycles
            z_mm = sample.mix_height
            volume = sample.mix_volume

            step_id, step = self._clone_mix_step(well=target_well,
                                             cycles=num_cycles,
                                             dis_speed=dispense_speed,
                                             asp_speed=aspirate_speed,
                                             from_bottom=z_mm,
                                             mix_volume=volume)

            self.saved_steps[step_id] = step
            self.ordered_ids.append(step_id)

        # save finished protocol
        self.script_path.parent.mkdir(parents=True, exist_ok=True)
        with self.script_path.open("w") as f:
            json.dump(self.proto, f, indent=2)

        self.logger.info(f"Protocol written → {self.script_path}")
        return self.script_path