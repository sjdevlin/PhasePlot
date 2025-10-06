import json
import uuid
from pathlib import Path
from typing import Dict, List

ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Mocked imports; replace with your actual implementations.
from models import Experiment  # Your model
from services import AppConfig  # Your service to load configurations

class ScriptfileGenerator:
    """Generate an Opentrons JSON protocol for one Experiment."""

    def __init__(self, db, experiment: 'Experiment'):
        self.db = db
        self.experiment = experiment
        self.app_config = AppConfig("./config.yaml")  # Load your app config
        self.param_name = {p.id: p.name for p in self.db.get_all_parameters()}

        # Load file paths from config
        self.template_path = Path(self.app_config.get("script_template"))
        self.script_path = Path(f"{self.app_config.get('script_output_path')}/{self.experiment.id}.json")

        with self.template_path.open() as f:
            self.proto = json.load(f)

        data = self.proto["designerApplication"]["data"]
        self.saved_steps: Dict[str, dict] = data["savedStepForms"]
        self.ordered_ids = data["orderedStepIds"]

        # pipette and labware IDs
        self.p20_id = next(pid for pid, spec in data["pipettes"].items() if spec["pipetteName"].startswith("p20"))
        self.p300_id = next(pid for pid, spec in data["pipettes"].items() if spec["pipetteName"].startswith("p300"))
        self.tube_rack_id = next(k for k in data["ingredLocations"] if "tuberack" in k)
        self.plate_id = next(k for k in data["labware"] if "wellplate" in k)

        # Get master steps from the template and remove them from protocol
        self._stash_master_steps()

    def _stash_master_steps(self):
        oil_steps = [
            (sid, s) for sid, s in self.saved_steps.items()
            if s.get("aspirate_wells") == ["A1"] and s.get("volume") == "40"
        ]
        self.master_oil_id, self.master_oil_step = oil_steps[0]

        water_steps = [
            (sid, s) for sid, s in self.saved_steps.items()
            if s.get("aspirate_wells") == ["A2"] and s.get("volume") == "2"
        ]
        self.master_water_id, self.master_water_step = water_steps[0]

        mix_steps = [
            (sid, s) for sid, s in self.saved_steps.items()
            if s.get("stepType") == "mix"
        ]
        self.master_mix_id, self.master_mix_step = mix_steps[0]

        # Remove master/template steps
        for sid, _ in oil_steps + water_steps + mix_steps:
            self.saved_steps.pop(sid, None)
            if sid in self.ordered_ids:
                self.ordered_ids.remove(sid)

    def _well_name(self, row: int, col: int) -> str:
        return f"{ROW_LETTERS[row]}{col + 1}"

    def generate(self):
        samples = self.experiment.sample  # List of sample objects with .well_row, .well_column, .sample_detail
        wells = [self._well_name(s.well_row, s.well_column) for s in samples]

        # ---- OIL multi-dispense ----
        oil_step = self._make_multi_dispense_step(
            master_step=self.master_oil_step,
            pipette_id=self.p300_id,
            source_well="A1",
            dest_wells=wells,
            per_well_vol=40,
            tiprack=self.master_oil_step.get("tipRack"),
            change_tip="once",
            disposal_volume="20"
        )

        # ---- WATER multi-dispense ----
        water_step = self._make_multi_dispense_step(
            master_step=self.master_water_step,
            pipette_id=self.p20_id,
            source_well="A2",
            dest_wells=wells,
            per_well_vol=2,
            tiprack=self.master_water_step.get("tipRack"),
            change_tip="always",
            disposal_volume="1"
        )

        # ---- MIX steps ----
        mix_steps = []
        for s in samples:
            well = self._well_name(s.well_row, s.well_column)
            param_dict = {
                self.param_name[d.parameter_id]: d.value
                for d in s.sample_detail
            }
            mix_steps.append(self._make_mix_step(self.master_mix_step, well, param_dict))

        # ---- Add new steps to protocol ----
        step_ids = []
        for step in [oil_step, water_step] + mix_steps:
            step_id = str(uuid.uuid4())
            self.saved_steps[step_id] = step
            step_ids.append(step_id)

        self.ordered_ids[:] = step_ids

        with self.script_path.open("w") as f:
            json.dump(self.proto, f, indent=2)

    def _make_multi_dispense_step(
        self, master_step, pipette_id, source_well, dest_wells, per_well_vol, tiprack, change_tip, disposal_volume
    ):
        step = master_step.copy()
        step["id"] = str(uuid.uuid4())
        step["pipette"] = pipette_id
        step["aspirate_labware"] = self.tube_rack_id
        step["aspirate_wells"] = [source_well]
        step["dispense_labware"] = self.plate_id
        step["dispense_wells"] = dest_wells
        step["volume"] = str(per_well_vol)
        step["path"] = "multiDispense"
        step["changeTip"] = change_tip
        step["tipRack"] = tiprack
        step["disposalVolume_checkbox"] = True
        step["disposalVolume_volume"] = str(disposal_volume)
        # For oil (p300) and water (p20), you may want to set additional fields if needed for your deck setup
        return step

    def _make_mix_step(self, master_mix_step, well, param_dict):
        step = master_mix_step.copy()
        step["id"] = str(uuid.uuid4())
        step["wells"] = [well]
        step["pipette"] = self.p20_id
        step["tipRack"] = master_mix_step.get("tipRack")
        step["times"] = str(param_dict.get("mix_cycles", 10))
        step["mix_mmFromBottom"] = float(param_dict.get("mix_mmFromBottom", 0.5))
        step["aspirate_flowRate"] = 10.0
        step["dispense_flowRate"] = 25.0
        step["changeTip"] = "always"
        # The protocol designer uses "volume" for mix volume; if needed, pull from param_dict
        step["volume"] = str(param_dict.get("mix_volume", 20))
        return step