# scriptfile_generator.py
import json
import uuid
from pathlib import Path
from typing import Dict

from models import Experiment, Parameter
from services import AppConfig, Logger

ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class ScriptfileGenerator:
    """Generate an Opentrons JSON protocol for one Experiment."""

    # ─────────────────────────────────────────────────────────────
    def __init__(self, db, experiment: Experiment):
        self.db = db
        self.experiment = experiment
        self.app_config = AppConfig()
        self.logger = Logger()

        self.template_path = Path(self.app_config.get("script_template_path"))
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
        self.tube_rack_id = next(k for k in data["ingredLocations"] if "tuberack" in k)
        self.plate_id = next(k for k in data["labware"] if "wellplate" in k)

        # ── cache Parameter.id → name for fast lookup ─────────
        self.param_name = {
            p.id: p.name for p in self.db.get_all_parameters()
        }



        # ── locate & store a *master* water step ───────────────
        self._stash_master_water_step()

    # ─────────────────────────────────────────────────────────────
    def _stash_master_water_step(self) -> None:
        """Keep first A3→C3 water step; delete all water placeholders."""
        water_steps = [
            (sid, s)
            for sid, s in self.saved_steps.items()
            if s.get("aspirate_wells") == ["A3"] and s.get("volume") == "3"
        ]
        if not water_steps:
            raise RuntimeError(
                "Template must contain at least one 3 µL water step from A3."
            )

        # first one is our archetype
        self.master_id, self.master_step = water_steps[0]

        # remove every placeholder step (they include C3 & C4)
        for sid, _ in water_steps:
            self.saved_steps.pop(sid, None)
            if sid in self.ordered_ids:
                self.ordered_ids.remove(sid)

    # ─────────────────────────────────────────────────────────────
    def _well_name(self, row: int, col: int) -> str:
        return f"{ROW_LETTERS[row]}{col + 1}"

    # ─────────────────────────────────────────────────────────────
    def _clone_step(
        self, target: str, cycles: int, flow: float, z_mm: float
    ) -> dict:
        """Clone master step → update target well + mixing params."""
        new = json.loads(json.dumps(self.master_step))  # deep copy
        new_id = str(uuid.uuid4())
        new.update(
            {
                "id": new_id,
                "dispense_wells": [target],
                "dispense_mix_times": str(cycles),
                "dispense_flowRate": str(flow),
                "dispense_mmFromBottom": z_mm,
            }
        )
        return new_id, new

    # ─────────────────────────────────────────────────────────────
    def generate(self) -> Path:
        """Build 48 water‑dispense steps (one per Sample) & write JSON."""
        for sample in self.experiment.sample:
            target = self._well_name(sample.well_row, sample.well_column)

            details = {
                self.param_name[d.parameter_id]: float(d.value)
                for d in sample.sample_detail
            }

            flow = details.get("dispense_flowRate", 12.5)
            cycles = int(details.get("dispense_mix_times", 5))
            z_mm = details.get("dispense_mmFromBottom", 0.5)

            step_id, step = self._clone_step(target, cycles, flow, z_mm)

            self.saved_steps[step_id] = step
            self.ordered_ids.append(step_id)

        # save finished protocol
        self.script_path.parent.mkdir(parents=True, exist_ok=True)
        with self.script_path.open("w") as f:
            json.dump(self.proto, f, indent=2)

        self.logger.info(f"Protocol written → {self.script_path}")
        return self.script_path
