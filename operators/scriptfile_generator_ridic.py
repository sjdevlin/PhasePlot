import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, TYPE_CHECKING

from sqlalchemy import null

# -----------------------------------------------------------------------------
# Bring in the *real* domain classes from the user-supplied experiment module.
# -----------------------------------------------------------------------------
# They provide the experiment hierarchy we consume; the stub versions that were
# previously embedded here have been removed.
# -----------------------------------------------------------------------------

from models import Experiment, Sample  # type: ignore

# -----------------------------------------------------------------------------
# Main generator class
# -----------------------------------------------------------------------------

class ScriptfileGenerator:
    """Generate a Protocol-Designer-compatible schema-8 JSON protocol.

    Public API
    ----------
    ``generate(experiment, output_path)`` Build and write the JSON.
    """

    # ─────────────────────────── Fixed deck constants ──────────────────────── #

    DEST_PLATE_ID = "c73d08b6-c36c-4f99-985f-564eb93bf7dd"
    OIL_WATER_TUBERACK_ID = "159379a1-acd3-4e52-8ee8-ce60854d8b54"
    TIPRACK_20_ID = "b45af7b6-d0f8-455a-a42f-1b9036ecbd32"
    TIPRACK_300_ID = "b5586c1d-b012-4692-9194-f1274f5da576"
    TRASH_ID = "6307a18e-4b11-402d-862a-30c54ef3c35d"

    DEST_PLATE_URI = "custom_beta/thermoscientific_384_wellplate_120ul/1"
    OIL_WATER_TUBERACK_URI = "opentrons/opentrons_10_tuberack_nest_4x50ml_6x15ml_conical/1"
    TIPRACK_20_URI = "opentrons/opentrons_96_tiprack_20ul/1"
    TIPRACK_300_URI = "opentrons/opentrons_96_tiprack_300ul/1"
    TRASH_URI = "trashBin"


    # Deterministic pipette UUIDs (copied from the template for diff-friendly output)
    P20_ID = "dcb452fb-01a7-4b8f-835d-305e53990319"
    P300_ID = "650d5063-fc59-4707-ad95-f48af4767c1c"

    DECK_MAP = {
        TIPRACK_20_URI: "2",
        TIPRACK_300_URI: "5",
        DEST_PLATE_URI: "4",
        OIL_WATER_TUBERACK_URI: "1",
    }

    # Liquid metadata; edit volumes / colors as needed.
    LIQUIDS: Dict[str, Dict[str, Any]] = {
        "oil": {
            "liquidGroupId": "0",
            "displayName": "Oil",
            "description": "Oil phase",
            "displayColor": "#b925ff",
            "source_well": "A1",
            "volume_per_dest": 40,  # µL per well
            "pipette": P300_ID,
            "tipRack": f"{TIPRACK_300_ID}:{TIPRACK_300_URI}",
            "changeTip": "once",  # reuse for whole batch
            "aspirate_mmFromBottom": 5,
            "dispense_mmFromBottom": "1",
            "disposal_volume": "20"  # µL disposal volume
        },
        "water": {
            "liquidGroupId": "1",
            "displayName": "Water",
            "description": "Water phase",
            "displayColor": "#ffd600",
            "source_well": "A2",
            "volume_per_dest": 2,
            "pipette": P20_ID,
            "tipRack": f"{TIPRACK_20_ID}:{TIPRACK_20_URI}",
            "changeTip": "always",  # fresh tip every aspirate
            "aspirate_mmFromBottom": "5",
            "dispense_mmFromBottom": "0.5",
            "disposal_volume": "1"  # µL disposal volume
        },
    }

    MIX_DEFAULTS: Dict[str, Any] = {
        "mix_volume": 20,
        "mix_times": 10,
        "mix_depth": 0.2,
        "aspirate_flowRate": 10,
        "dispense_flowRate": 25,
        "changeTip": "always"
    }

    ROW_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


    def __init__(self, schema_version: int = 8, pd_version: str = "8.4.4") -> None:
        self.schema_version = schema_version
        self.pd_version = pd_version

    # ───────────────────────────── Public API ──────────────────────────────── #

    def _well_name(self, row: int, col: int) -> str:
        return f"{self.ROW_LETTERS[row]}{col + 1}"

    def generate(self, experiment: Experiment, output_path: str | Path = "protocol.json") -> Path:  # noqa: N802
        """Generate and save the JSON protocol representing *experiment*."""

        #this is the main protocol
        protocol_xml: Dict[str, Any] = {
            "$otSharedSchema": "#/protocol/schemas/8",
            "schemaVersion": self.schema_version,
            "metadata": self._build_metadata(experiment),
            "designerApplication": self._init_designer_app(),
            "robot": {"model": "OT-2 Standard", "deckId": "ot2_standard"},
            "labwareDefinitionSchemaId": "opentronsLabwareSchemaV2",

        }

        designer_data = protocol_xml["designerApplication"]["data"]
        designer_data.update(
            {
#                "pipettes": self._build_pipettes(),
#                "labware": self._build_labware_defs(),
                "ingredients": self._build_ingredients(),
                "ingredLocations": self._build_ingred_locations(),
            }
        )

        saved_step_forms: Dict[str, Any] = {
            "__INITIAL_DECK_SETUP_STEP__": self._build_deck_setup(),
        }
        ordered_step_ids: List[str] = []

        # ───── Oil & water multi-dispenses ────────────────────────────────── #
        for liquid_key in ("oil", "water"):
            step_id = self._uuid()
            destination_wells = [self._well_name(s.well_row, s.well_column) for s in experiment.sample]
            saved_step_forms[step_id] = self._build_multidispense_step(
                step_id=step_id,
                liquid_key=liquid_key,
                dest_wells=destination_wells
            )
            ordered_step_ids.append(step_id)

        # ───── Per-sample mix steps ───────────────────────────────────────── #
        for sample in experiment.sample:
            mix_step_id = self._uuid()
            saved_step_forms[mix_step_id] = self._build_mix_step(mix_step_id, sample)
            ordered_step_ids.append(mix_step_id)

        designer_data.update(
            {
                "savedStepForms": saved_step_forms,
                "orderedStepIds": ordered_step_ids,
                "pipettes": self._build_pipettes(),
                "labware": self._build_labware_defs(),

            }
        )

        # You may optionally inline full labware definitions here (omitted for brevity)
        protocol_xml["labwareDefinitions"] = {}

        path = Path(output_path)
        # Write with custom JSON encoder to convert Python booleans/None to lowercase
        json_str = json.dumps(protocol_xml, indent=2)
        json_str = json_str.replace('\"False\"', 'false').replace('\"True\"', 'true').replace('\"None\"', 'null')
        path.write_text(json_str)
        return path

    # ────────────────────────── Helper builders ───────────────────────────── #

    @staticmethod
    def _uuid() -> str:  # noqa: D401 – short helper
        return str(uuid.uuid4())

    @staticmethod
    def _timestamp_ms() -> int:
        return int(datetime.now().timestamp() * 1000)

    # ----- Top-level metadata ------------------------------------------------- #

    def _build_metadata(self, experiment: Experiment) -> Dict[str, Any]:
        ts = self._timestamp_ms()
        return {
            "protocolName": experiment.description,
            "author": "Auto-generated",
            "description": f"Generated from Experiment '{experiment.description}'",
            "created": ts,
            "lastModified": ts,
            "category": None,
            "subcategory": None,
            "tags": [],
        }

    def _init_designer_app(self) -> Dict[str, Any]:
        return {
            "name": "opentrons/protocol-designer",
            "version": self.pd_version,
            "data": {
                "_internalAppBuildDate": datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "pipetteTiprackAssignments": {
                    self.P20_ID: [self.TIPRACK_20_URI],
                    self.P300_ID: [self.TIPRACK_300_URI],
                },
                "dismissedWarnings": {"form": [], "timeline": []},
            },
        }

    # ----- Static sections ---------------------------------------------------- #

    def _build_pipettes(self) -> Dict[str, Any]:
        return {
            self.P20_ID: {"pipetteName": "p20_single_gen2"},
            self.P300_ID: {"pipetteName": "p300_single_gen2"},
        }

    def _build_labware_defs(self) -> Dict[str, Any]:
        # Minimal URIs – swap for full definitions if your automation pipeline requires them.
        return {
            f"{self.TIPRACK_20_ID}:{self.TIPRACK_20_URI}": {
                "displayName": "Opentrons OT-2 96 Tip Rack 20 µL",
                "labwareDefURI": self.TIPRACK_20_URI,
            },
            f"{self.TIPRACK_300_ID}:{self.TIPRACK_300_URI}": {
                "displayName": "Opentrons OT-2 96 Tip Rack 300 µL",
                "labwareDefURI": self.TIPRACK_300_URI,
            },
            f"{self.DEST_PLATE_ID}:{self.DEST_PLATE_URI}": {
                "displayName": "Ibidi 384-well plate",
                "labwareDefURI": self.DEST_PLATE_URI,
            },
            f"{self.OIL_WATER_TUBERACK_ID}:{self.OIL_WATER_TUBERACK_URI}": {
                "displayName": "Opentrons 10 Tube Rack with NEST 4x50 mL, 6x15 mL Conical",
                "labwareDefURI": self.OIL_WATER_TUBERACK_URI,
            },
        }

    def _build_ingredients(self) -> Dict[str, Any]:
        return {
            meta["liquidGroupId"]: {
                "displayName": meta["displayName"],
                "description": meta["description"],
                "displayColor": meta["displayColor"],
                "liquidGroupId": meta["liquidGroupId"],
            }
            for meta in self.LIQUIDS.values()
        }

    def _build_ingred_locations(self) -> Dict[str, Any]:
        labware_id = f"{self.OIL_WATER_TUBERACK_ID}:{self.OIL_WATER_TUBERACK_URI}"
        locs: Dict[str, Any] = {}
        for meta in self.LIQUIDS.values():
            locs.setdefault(labware_id, {}).setdefault(meta["source_well"], {})[
                meta["liquidGroupId"]
            ] = {"volume": 5000}
        return locs

    # ----- Deck setup form ---------------------------------------------------- #

    def _build_deck_setup(self) -> Dict[str, Any]:
        return {
            "labwareLocationUpdate": {
                f"{self.OIL_WATER_TUBERACK_ID}:{self.OIL_WATER_TUBERACK_URI}": "1",
                f"{self.TIPRACK_20_ID}:{self.TIPRACK_20_URI}": "2",
                f"{self.DEST_PLATE_ID}:{self.DEST_PLATE_URI}": "4",
                f"{self.TIPRACK_300_ID}:{self.TIPRACK_300_URI}": "5",
            },
            "moduleLocationUpdate": {},
            "pipetteLocationUpdate": {self.P20_ID: "left", self.P300_ID: "right"},
            "trashBinLocationUpdate": {f"{self.TRASH_ID}:{self.TRASH_URI}": "cutout12"},
            "wasteChuteLocationUpdate": {},
            "stagingAreaLocationUpdate": {},
            "gripperLocationUpdate": {},
            "stepType": "manualIntervention",
            "id": "__INITIAL_DECK_SETUP_STEP__"
        }

    # ----- Liquid handling step builders ------------------------------------- #

    # ----- Liquid handling step builders ------------------------------------- #

    def _build_multidispense_step(
        self,
        *,
        step_id: str,
        liquid_key: str,
        dest_wells: List[str]
    ) -> Dict[str, Any]:
        meta = self.LIQUIDS[liquid_key]
        return {
            "aspirate_airGap_checkbox": False,
            "aspirate_airGap_volume": None,
            "aspirate_delay_checkbox": True,
            "aspirate_delay_mmFromBottom": 100, #TODO: make this dynamic
            "aspirate_delay_seconds": "10",
            "aspirate_flowRate": "3",
            "aspirate_labware": f"{self.OIL_WATER_TUBERACK_ID}:{self.OIL_WATER_TUBERACK_URI}",
            "aspirate_mix_checkbox": False,
            "aspirate_mix_times": None,
            "aspirate_mix_volume": None,
            "aspirate_mmFromBottom": meta["aspirate_mmFromBottom"],
            "aspirate_touchTip_checkbox": True if liquid_key == "oil" else False,

            "aspirate_touchTip_mmFromBottom": None,
            "aspirate_wellOrder_first": "t2b",
            "aspirate_wellOrder_second": "l2r",
            "aspirate_wells_grouped": False,
            "aspirate_wells": [meta["source_well"]],
            "aspirate_x_position": 0,
            "aspirate_y_position": 0,
            "blowout_checkbox": False,
            "blowout_flowRate": 46.43,
            "blowout_location": None,
            "blowout_z_offset": 0,
            "changeTip": meta["changeTip"],
            "dispense_airGap_checkbox": False,
            "dispense_airGap_volume": None,
            "dispense_delay_checkbox": True,
            "dispense_delay_mmFromBottom": 10,
            "dispense_delay_seconds": "5",
            "dispense_flowRate": "10",
            "dispense_labware": f"{self.DEST_PLATE_ID}:{self.DEST_PLATE_URI}",
            "dispense_delay_checkbox": True if liquid_key == "oil" else False,
            "dispense_mix_checkbox": False,
            "dispense_mix_times": None,
            "dispense_mix_volume": None,
            "dispense_mmFromBottom": 0.5,
            "dispense_touchTip_checkbox": False,
            "dispense_touchTip_mmFromBottom": None,
            "dispense_wellOrder_first": "t2b",
            "dispense_wellOrder_second": "l2r",
            "dispense_wells": dest_wells,

            "dispense_x_position": 0,
            "dispense_y_position": 0,
            "disposalVolume_checkbox": True,
            "disposalVolume_volume": meta["disposal_volume"],
            "dropTip_location": f"{self.TRASH_ID}:{self.TRASH_URI}",
            "nozzles": None,
            "path": "multiDispense",
            "pipette": self.P300_ID if liquid_key == "oil" else self.P20_ID,
            "preWetTip": False,
            "tipRack": self.TIPRACK_300_URI if liquid_key == "oil" else self.TIPRACK_20_URI,#TODO: make this dynamic
            "volume": str(meta["volume_per_dest"]),
            "id": step_id,
            "stepType": "moveLiquid",
            "stepName": "transfer",
            "stepDetails": ""
        }

    def _build_mix_step(self, step_id: str, sample: Sample) -> Dict[str, Any]:
        """
        Build a single-well mix step. We condense multiple SampleDetail rows into one
        parameter set; adjust the merge policy if you need something fancier.
        """
        well_name = self._well_name(sample.well_row, sample.well_column)

        return {

            "aspirate_delay_checkbox": False,
            "aspirate_delay_seconds": "1",
            "aspirate_flowRate": str(sample.mix_aspirate),
            "blowout_checkbox": False,
            "blowout_flowRate": None,
            "blowout_location": None,
            "blowout_z_offset": 0,
            "changeTip": "always",
            "dispense_delay_checkbox": False,
            "dispense_delay_seconds": "1",
            "dispense_flowRate": str(sample.mix_dispense),
            "dropTip_location": f"{self.TRASH_ID}:{self.TRASH_URI}",
            "changeTip": "always",
            "labware": f"destplate:{self.DEST_PLATE_URI}",
            "labware": "c73d08b6-c36c-4f99-985f-564eb93bf7dd:custom_beta/thermoscientific_384_wellplate_120ul/1",
            "mix_mmFromBottom": sample.mix_height,
            "mix_touchTip_checkbox": False,
            "mix_touchTip_mmFromBottom": None,
            "mix_wellOrder_first": "t2b",
            "mix_wellOrder_second": "l2r",
            "mix_x_position": 0,
            "mix_y_position": 0,
            "nozzles": None,
            "pipette": self.P20_ID,
            "times": str(sample.mix_cycles),
            "tipRack": self.TIPRACK_20_URI,
            "volume": str(sample.mix_volume),
            "wells": [well_name],
            "id": step_id,
            "stepType": "mix",
            "stepName": f"Mix {well_name}",
            "stepDetails": "",

        }