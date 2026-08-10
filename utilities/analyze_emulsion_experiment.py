#!/usr/bin/env python3
"""
Analyze emulsion image data for a PhasePlot experiment.

Pipeline:
1) Select sharpest frame per (sample, site) from z-stack images.
2) Run Roboflow workflow inference on that frame.
3) Keep droplets above confidence threshold, near-square, and not edge-clipped.
4) Skip sites with zero valid droplets.
5) Compute per-site metrics and aggregate plots:
   - polydispersity by water volume (10 uL vs 20 uL)
   - droplet count by dispensing type
   - touching-droplet percentage by dispensing type

Usage example:
python utilities/analyze_emulsion_experiment.py \
  --result-run-id 88 \
  --protocol-file "/path/to/ot2_droplet_optimization.py" \
  --config config_mac.yaml
"""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Keep Matplotlib/font caches in writable temp dirs before importing Matplotlib.
os.environ.setdefault("MPLCONFIGDIR", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

import cv2
import matplotlib.pyplot as plt
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Experiment, Image, ResultRun, Sample
from services import AppConfig, DatabaseService


def discover_default_config() -> str:
    for candidate in ("config.yaml", "config_mac.yaml", "config_20X.yaml", "config_40X.yaml"):
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("No config file found.")


def parse_well(well: str) -> Tuple[str, int]:
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", str(well).strip())
    if not m:
        raise ValueError(f"Invalid well: {well}")
    return m.group(1).upper(), int(m.group(2))


def sort_wells(wells: Iterable[str]) -> List[str]:
    return sorted(set(wells), key=lambda w: parse_well(w))


def flatten_wells(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: List[str] = []
        for v in value:
            out.extend(flatten_wells(v))
        return out
    return []


def normalize_to_uint8(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    if arr.dtype == np.uint8:
        return arr
    arr_f = arr.astype(np.float32)
    lo, hi = np.percentile(arr_f, (1.0, 99.0))
    if hi <= lo:
        lo = float(np.min(arr_f))
        hi = float(np.max(arr_f))
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    arr_f = np.clip((arr_f - lo) / (hi - lo), 0.0, 1.0)
    return (arr_f * 255.0).astype(np.uint8)


def laplacian_sharpness(image_path: Path) -> float:
    arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if arr is None:
        return float("-inf")
    gray = normalize_to_uint8(arr)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def coerce_predictions(pred_list: Any) -> List[Dict[str, Any]]:
    if pred_list is None:
        return []
    if isinstance(pred_list, dict):
        pred_list = pred_list.get("predictions", [])
    if not isinstance(pred_list, list):
        return []
    out: List[Dict[str, Any]] = []
    for p in pred_list:
        if isinstance(p, dict):
            out.append(p)
        elif isinstance(p, str):
            try:
                parsed = json.loads(p.replace("'", '"'))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
    return out


def parse_inference_response(raw: str) -> List[Dict[str, Any]]:
    start = raw.find("{")
    if start < 0:
        return []
    data = json.loads(raw[start:])
    if not isinstance(data, dict):
        return []
    if "outputs" in data:
        outputs = data.get("outputs", [])
        output = outputs[0] if outputs else {}
        return coerce_predictions(output.get("predictions", {}))
    return []


def infer_workflow(
    image_path: Path,
    *,
    host: str,
    workflow_name: str,
    api_key: str,
    timeout_s: float = 90.0,
) -> List[Dict[str, Any]]:
    with open(image_path, "rb") as fh:
        payload_img = base64.b64encode(fh.read()).decode("utf-8")
    payload = {"api_key": api_key, "inputs": {"image": {"type": "base64", "value": payload_img}}}
    url = f"{host.rstrip('/')}/infer/workflows/{workflow_name}"
    resp = requests.post(url, json=payload, timeout=timeout_s)
    resp.raise_for_status()
    return parse_inference_response(resp.text)


@dataclass
class ProtocolAssignment:
    source_stock_well: str
    dispense_type: str  # P300 | P20/20 | P20/5 | P20/Middle
    dispense_subtype: str  # optional finer label
    water_volume_ul: Optional[float]
    mix_cycles: Optional[int]


@dataclass
class ProtocolMap:
    by_destination_well: Dict[str, ProtocolAssignment]
    assumptions: List[str]


def _extract_python_constants(protocol_file: Path) -> Dict[str, Any]:
    tree = ast.parse(protocol_file.read_text())
    constants: Dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        key = node.targets[0].id
        try:
            constants[key] = ast.literal_eval(node.value)
        except Exception:
            continue
    return constants


def _plate_wells_384_column_major() -> List[str]:
    rows = [chr(ord("A") + i) for i in range(16)]  # A..P
    out: List[str] = []
    for col in range(1, 25):
        for row in rows:
            out.append(f"{row}{col}")
    return out


def _contiguous_window_exact_start(plate_wells: Sequence[str], destination_wells: Sequence[str]) -> Optional[str]:
    target = set(destination_wells)
    n = len(destination_wells)
    if n == 0 or n > len(plate_wells):
        return None
    for i in range(0, len(plate_wells) - n + 1):
        window = plate_wells[i : i + n]
        if set(window) == target:
            return window[0]
    return None


def _destination_order_for_stocks(
    destination_wells: Sequence[str],
    start_well: Optional[str],
    *,
    required_count: int,
) -> Tuple[List[str], List[str]]:
    notes: List[str] = []
    plate_wells = _plate_wells_384_column_major()
    destination_set = set(destination_wells)

    if start_well and start_well in plate_wells:
        start_idx = plate_wells.index(start_well)
        span = plate_wells[start_idx : start_idx + required_count]
        if len(span) == required_count and set(span) == destination_set:
            return span, notes
        notes.append(
            f"Configured START_PLATE_WELL={start_well} did not match DB destination-well set; inferred start was used."
        )

    inferred_start = _contiguous_window_exact_start(plate_wells, destination_wells)
    if inferred_start is not None:
        idx = plate_wells.index(inferred_start)
        span = plate_wells[idx : idx + required_count]
        notes.append(f"Inferred destination block start well as {inferred_start} from DB well set.")
        return span, notes

    notes.append("Could not match destination wells as a contiguous OT block; used sorted well order.")
    return sort_wells(destination_wells), notes


def classify_dispense_type(step: Dict[str, Any], pipette_name: str) -> Tuple[str, str]:
    dispense_rate = float(step.get("dispense_flowRate") or 0.0)
    aspirate_mm = step.get("aspirate_mmFromBottom")
    aspirate_mm = float(aspirate_mm) if aspirate_mm is not None else None
    volume = float(step.get("volume") or 0.0)

    if pipette_name.startswith("p300"):
        return "P300", "p300_fast"
    if aspirate_mm is not None and aspirate_mm >= 4.0:
        return "P20/Middle", "middle_aspirate"
    if dispense_rate >= 10.0:
        return "P20/20", "p20_high_rate"
    if dispense_rate <= 5.0 or volume <= 1.5:
        return "P20/5", "p20_low_rate"
    return "P20/20", "p20_default_rate"


def _water_from_stock_well(stock_well: str) -> Optional[float]:
    row, _col = parse_well(stock_well)
    if row == "A":
        return 10.0
    if row == "B":
        return 20.0
    return None


def _default_mix_cycles(stock_well: str) -> Optional[int]:
    _row, col = parse_well(stock_well)
    col_to_cycles = {1: 10, 2: 10, 3: 15, 4: 20, 5: 20}
    return col_to_cycles.get(col)


def parse_opentrons_python_protocol(protocol_file: Path, destination_wells: Sequence[str]) -> ProtocolMap:
    constants = _extract_python_constants(protocol_file)
    row_a = [str(w) for w in constants.get("ROW_A_STOCKS", [f"A{i}" for i in range(1, 6)])]
    row_b = [str(w) for w in constants.get("ROW_B_STOCKS", [f"B{i}" for i in range(1, 6)])]
    all_stocks = row_a + row_b

    raw_cycles = constants.get("MIX_CYCLES_PER_ROW", [10, 10, 15, 20, 20])
    mix_cycles_per_col = [int(float(x)) for x in raw_cycles]
    if len(mix_cycles_per_col) < 5:
        mix_cycles_per_col = (mix_cycles_per_col + [10, 10, 15, 20, 20])[:5]

    start_plate_well = constants.get("START_PLATE_WELL")
    required = len(all_stocks) * 4
    ordered_dests, notes = _destination_order_for_stocks(
        destination_wells,
        str(start_plate_well) if start_plate_well else None,
        required_count=required,
    )

    assumptions: List[str] = []
    assumptions.extend(notes)
    if len(ordered_dests) < required:
        assumptions.append(
            f"Destination count is {len(ordered_dests)} but protocol expects {required}; mapping truncated."
        )

    # Matches OT script sequence for each stock:
    # [0] P300 fast 5 uL, [1] P20 slow single 5 uL at 20 uL/s,
    # [2] P20 slow square 1.5 uL x4 at 2 uL/s, [3] delayed/top aspirate 10 uL -> full dispense at 5 uL/s.
    dispense_profiles = [
        ("P300", "p300_fast_5ul"),
        ("P20/20", "p20_single_5ul_at_20uls"),
        ("P20/5", "p20_square_1p5ul_x4_at_2uls"),
        ("P20/Middle", "p20_top_aspirate_10ul_dispense_5uls"),
    ]

    by_destination: Dict[str, ProtocolAssignment] = {}
    idx = 0
    for stock in all_stocks:
        _row, col = parse_well(stock)
        cycles = mix_cycles_per_col[col - 1] if 1 <= col <= len(mix_cycles_per_col) else None
        for d_type, d_sub in dispense_profiles:
            if idx >= len(ordered_dests):
                break
            dest = ordered_dests[idx]
            by_destination[dest] = ProtocolAssignment(
                source_stock_well=stock,
                dispense_type=d_type,
                dispense_subtype=d_sub,
                water_volume_ul=_water_from_stock_well(stock),
                mix_cycles=cycles,
            )
            idx += 1

    return ProtocolMap(by_destination_well=by_destination, assumptions=assumptions)


def parse_opentrons_protocol(protocol_file: Path) -> ProtocolMap:
    data = json.loads(protocol_file.read_text())
    app_data = data.get("designerApplication", {}).get("data", {})
    step_forms = app_data.get("savedStepForms", {})
    ordered_ids = app_data.get("orderedStepIds", [])
    pipettes = app_data.get("pipettes", {})

    mix_cycles_by_well: Dict[str, int] = {}
    by_destination: Dict[str, ProtocolAssignment] = {}
    assumptions: List[str] = []

    for step_id in ordered_ids:
        step = step_forms.get(step_id, {})
        if step.get("stepType") != "mix":
            continue
        times = int(float(step.get("times") or 0))
        for w in flatten_wells(step.get("wells")):
            mix_cycles_by_well[w] = max(times, mix_cycles_by_well.get(w, 0))

    for step_id in ordered_ids:
        step = step_forms.get(step_id, {})
        if step.get("stepType") != "moveLiquid":
            continue
        src = flatten_wells(step.get("aspirate_wells"))
        dst = flatten_wells(step.get("dispense_wells"))
        if not src or not dst:
            continue

        pipette_id = step.get("pipette")
        pipette_name = str(pipettes.get(pipette_id, {}).get("pipetteName", "")).lower()
        dispense_type, dispense_subtype = classify_dispense_type(step, pipette_name)

        if len(src) == 1:
            source_for_each_dest = [src[0]] * len(dst)
        elif len(src) == len(dst):
            source_for_each_dest = src
        else:
            assumptions.append(
                f"Step {step_id}: source/destination cardinality mismatch ({len(src)} -> {len(dst)}). "
                "Used first source well for all destinations."
            )
            source_for_each_dest = [src[0]] * len(dst)

        for dest_well, source_well in zip(dst, source_for_each_dest):
            by_destination[dest_well] = ProtocolAssignment(
                source_stock_well=source_well,
                dispense_type=dispense_type,
                dispense_subtype=dispense_subtype,
                water_volume_ul=_water_from_stock_well(source_well),
                mix_cycles=mix_cycles_by_well.get(source_well, _default_mix_cycles(source_well)),
            )

    if not by_destination:
        assumptions.append("No moveLiquid mapping found in protocol; destination mapping unavailable.")
    return ProtocolMap(by_destination_well=by_destination, assumptions=assumptions)


def fallback_protocol_map(destination_wells: Sequence[str]) -> ProtocolMap:
    stock_wells = [f"A{i}" for i in range(1, 6)] + [f"B{i}" for i in range(1, 6)]
    dispense_order = [
        ("P300", "p300_fast"),
        ("P20/20", "slow_single"),
        ("P20/5", "slow_pattern"),
        ("P20/Middle", "middle_aspirate"),
    ]

    by_destination: Dict[str, ProtocolAssignment] = {}
    sorted_dests = sort_wells(destination_wells)

    idx = 0
    for stock in stock_wells:
        for d_type, d_sub in dispense_order:
            if idx >= len(sorted_dests):
                break
            well = sorted_dests[idx]
            by_destination[well] = ProtocolAssignment(
                source_stock_well=stock,
                dispense_type=d_type,
                dispense_subtype=d_sub,
                water_volume_ul=_water_from_stock_well(stock),
                mix_cycles=_default_mix_cycles(stock),
            )
            idx += 1

    assumptions = [
        "Used fallback destination mapping (sorted wells grouped in blocks of 4 assigned to A1..A5, B1..B5).",
        "Assumed within each 4-well block order = P300, P20/20, P20/5 (pattern), P20/Middle (middle aspirate).",
    ]
    return ProtocolMap(by_destination_well=by_destination, assumptions=assumptions)


def resolve_image_path(file_path: str, image_directory: Optional[str]) -> Optional[Path]:
    raw = Path(file_path).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        if image_directory:
            candidates.append((Path(image_directory) / raw).expanduser())
        candidates.append((Path.cwd() / raw).expanduser())
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def droplet_touching_flags(droplets: Sequence[Dict[str, float]]) -> List[bool]:
    n = len(droplets)
    touching = [False] * n
    for i in range(n):
        xi, yi, ri = droplets[i]["x"], droplets[i]["y"], droplets[i]["r"]
        for j in range(i + 1, n):
            xj, yj, rj = droplets[j]["x"], droplets[j]["y"], droplets[j]["r"]
            if math.hypot(xi - xj, yi - yj) <= (ri + rj):
                touching[i] = True
                touching[j] = True
    return touching


def _mean_sem(values: Sequence[float]) -> Tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    arr = np.array(values, dtype=float)
    mean = float(np.mean(arr))
    if len(arr) <= 1:
        return mean, 0.0
    sem = float(np.std(arr, ddof=1) / math.sqrt(len(arr)))
    return mean, sem


def plot_polydispersity(site_rows: Sequence[Dict[str, Any]], out_file: Path) -> bool:
    fig, ax = plt.subplots(figsize=(7, 5))
    groups = [10.0, 20.0]
    vals: List[np.ndarray] = []
    for g in groups:
        cur = []
        for row in site_rows:
            if float(row.get("water_volume_ul", np.nan)) == g:
                v = float(row.get("pdi_cv", np.nan))
                if np.isfinite(v):
                    cur.append(v)
        vals.append(np.array(cur, dtype=float))
    if not any(len(v) for v in vals):
        plt.close(fig)
        return False

    ax.boxplot(vals, tick_labels=[str(int(g)) for g in groups], showfliers=False)
    for i, g in enumerate(groups, start=1):
        y = vals[i - 1]
        x = np.random.normal(loc=i, scale=0.04, size=len(y))
        ax.scatter(x, y, s=20, alpha=0.6)
    ax.set_xlabel("Water Volume (uL)")
    ax.set_ylabel("Polydispersity (CV = std/mean)")
    ax.set_title("Polydispersity by Water Volume")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_file, dpi=220)
    plt.close(fig)
    return True


def plot_bar_with_points(
    site_rows: Sequence[Dict[str, Any]],
    y_col: str,
    y_label: str,
    title: str,
    out_file: Path,
    *,
    use_water_markers: bool = False,
) -> bool:
    order = ["P300", "P20/20", "P20/5", "P20/Middle"]
    grouped: Dict[str, List[float]] = {k: [] for k in order}
    for row in site_rows:
        k = str(row.get("dispense_type", ""))
        if k not in grouped:
            continue
        v = float(row.get(y_col, np.nan))
        if np.isfinite(v):
            grouped[k].append(v)
    if not any(grouped[k] for k in order):
        return False
    means = []
    sems = []
    for key in order:
        m, se = _mean_sem(grouped[key])
        means.append(m)
        sems.append(se)

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(order))
    ax.bar(x, means, yerr=sems, capsize=4, alpha=0.75)

    if use_water_markers:
        plotted_labels: set[str] = set()
        for i, key in enumerate(order):
            vals_10: List[float] = []
            vals_20: List[float] = []
            vals_other: List[float] = []
            for row in site_rows:
                if str(row.get("dispense_type", "")) != key:
                    continue
                val = float(row.get(y_col, np.nan))
                if not np.isfinite(val):
                    continue
                water = float(row.get("water_volume_ul", np.nan))
                if np.isfinite(water) and abs(water - 10.0) < 1e-6:
                    vals_10.append(val)
                elif np.isfinite(water) and abs(water - 20.0) < 1e-6:
                    vals_20.append(val)
                else:
                    vals_other.append(val)

            for vals, marker, lbl in (
                (vals_10, "o", "10 uL water"),
                (vals_20, "^", "20 uL water"),
                (vals_other, "x", "other/unknown water"),
            ):
                if not vals:
                    continue
                y = np.array(vals, dtype=float)
                jitter = np.random.normal(loc=i, scale=0.04, size=len(y))
                label = lbl if lbl not in plotted_labels else None
                ax.scatter(jitter, y, s=30, alpha=0.75, marker=marker, label=label)
                plotted_labels.add(lbl)
        if plotted_labels:
            ax.legend(loc="best", fontsize=9)
    else:
        for i, key in enumerate(order):
            y = np.array(grouped[key], dtype=float)
            jitter = np.random.normal(loc=i, scale=0.04, size=len(y))
            ax.scatter(jitter, y, s=22, alpha=0.65)
    ax.set_xticks(x)
    ax.set_xticklabels(order)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_file, dpi=220)
    plt.close(fig)
    return True


def write_csv(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Analyze emulsion experiment images and protocol-linked factors.")
    p.add_argument("--result-run-id", type=int, default=88)
    p.add_argument(
        "--experiment-id",
        type=int,
        default=None,
        help="Optional explicit experiment id. If omitted, derived from result run.",
    )
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--db-url", type=str, default=None, help="Override DB URL (e.g., sqlite:///sandbox.sqlite)")
    p.add_argument(
        "--protocol-file",
        type=str,
        default=None,
        help="Path to Opentrons protocol file (.py custom script or .json Protocol Designer export).",
    )
    p.add_argument("--output-dir", type=str, default=None)
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--square-tolerance", type=float, default=0.15, help="Allow width/height within ±this fraction.")
    p.add_argument("--edge-margin-px", type=int, default=2)
    p.add_argument("--led", type=int, default=None, help="Optional LED channel filter.")
    p.add_argument("--timeout-s", type=float, default=90.0)
    p.add_argument(
        "--exclude-dispense-types",
        type=str,
        default="",
        help="Comma-separated dispense types to exclude from outputs (e.g., 'P300').",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    config_path = args.config or discover_default_config()
    cfg = AppConfig(config_path)

    db_url = args.db_url or cfg.get("sqlite_db")
    db = DatabaseService(db_url)

    image_directory = cfg.get("image_file_directory")
    api_key = cfg.get("roboflow_api_key")
    host = str(cfg.get("roboflow_inference_host", "http://localhost:9001")).rstrip("/")
    workflow_name = cfg.get("image_processing_workflow_name")

    if not api_key or not workflow_name:
        raise RuntimeError("Roboflow config missing: need roboflow_api_key and image_processing_workflow_name.")

    with db.Session() as session:
        run = session.query(ResultRun).filter(ResultRun.id == args.result_run_id).first()
        if run is None:
            raise RuntimeError(f"ResultRun {args.result_run_id} not found in database: {db_url}")

        run_experiment_id = int(run.experiment_id)
        if args.experiment_id is not None and int(args.experiment_id) != run_experiment_id:
            raise RuntimeError(
                f"ResultRun {run.id} belongs to experiment {run_experiment_id}, "
                f"but --experiment-id {args.experiment_id} was supplied."
            )
        experiment_id = int(args.experiment_id) if args.experiment_id is not None else run_experiment_id

        exp = session.query(Experiment).filter(Experiment.id == experiment_id).first()
        if exp is None:
            raise RuntimeError(f"Experiment {experiment_id} not found in database: {db_url}")

        samples = session.query(Sample).filter(Sample.experiment_id == experiment_id).all()
        sample_by_id = {int(s.id): s for s in samples}

        q = session.query(Image).filter(Image.result_run_id == run.id)
        if args.led is not None:
            q = q.filter(Image.led_number == int(args.led))
        images = q.order_by(Image.sample_id, Image.site_number, Image.stack_number, Image.id).all()

    if not images:
        raise RuntimeError(f"No images found for ResultRun {run.id}.")

    output_dir = Path(args.output_dir or f"outputs/result_run_{run.id}_emulsion_analysis")
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded_types = {x.strip() for x in str(args.exclude_dispense_types).split(",") if x.strip()}

    destination_wells = []
    for s in samples:
        if s.well_row is None or s.well_column is None:
            continue
        destination_wells.append(f"{str(s.well_row).upper()}{int(s.well_column)}")

    protocol_map: Optional[ProtocolMap] = None
    assumptions: List[str] = []
    if args.protocol_file:
        pf = Path(args.protocol_file)
        if pf.exists():
            if pf.suffix.lower() == ".py":
                protocol_map = parse_opentrons_python_protocol(pf, destination_wells)
            else:
                protocol_map = parse_opentrons_protocol(pf)
            assumptions.extend(protocol_map.assumptions)
        else:
            assumptions.append(f"Protocol file not found: {pf}")

    # Group images by (sample, site)
    groups: Dict[Tuple[int, int], List[Image]] = {}
    for im in images:
        if im.sample_id is None or im.site_number is None:
            continue
        groups.setdefault((int(im.sample_id), int(im.site_number)), []).append(im)

    # If no protocol mapping available, prepare fallback using destination wells in this experiment.
    if protocol_map is None:
        protocol_map = fallback_protocol_map(destination_wells)
        assumptions.extend(protocol_map.assumptions)

    site_rows: List[Dict[str, Any]] = []
    droplet_rows: List[Dict[str, Any]] = []

    skipped_missing_image = 0
    skipped_no_droplets = 0
    inference_failures = 0

    for (sample_id, site_number), site_images in sorted(groups.items()):
        scored: List[Tuple[Image, Path, float]] = []
        for im in site_images:
            p = resolve_image_path(im.file_path, image_directory)
            if p is None:
                continue
            scored.append((im, p, laplacian_sharpness(p)))
        if not scored:
            skipped_missing_image += 1
            continue

        best_image, best_path, sharpness = max(scored, key=lambda x: x[2])
        try:
            predictions = infer_workflow(
                best_path,
                host=host,
                workflow_name=workflow_name,
                api_key=api_key,
                timeout_s=float(args.timeout_s),
            )
        except Exception:
            inference_failures += 1
            continue

        arr = cv2.imread(str(best_path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            skipped_missing_image += 1
            continue
        h, w = arr.shape[:2]

        valid: List[Dict[str, float]] = []
        for pred in predictions:
            conf = float(pred.get("confidence", 0.0))
            if conf < float(args.confidence):
                continue
            bw = float(pred.get("width", 0.0))
            bh = float(pred.get("height", 0.0))
            if bw <= 0 or bh <= 0:
                continue
            ratio = bw / bh if bh > 0 else 0.0
            if abs(ratio - 1.0) > float(args.square_tolerance):
                continue
            x = float(pred.get("x", 0.0))
            y = float(pred.get("y", 0.0))
            x0, x1 = x - bw / 2.0, x + bw / 2.0
            y0, y1 = y - bh / 2.0, y + bh / 2.0
            margin = int(args.edge_margin_px)
            if x0 <= margin or y0 <= margin or x1 >= (w - margin) or y1 >= (h - margin):
                continue
            d = 0.5 * (bw + bh)
            valid.append(
                {
                    "x": x,
                    "y": y,
                    "r": 0.5 * d,
                    "diameter_px": d,
                    "width_px": bw,
                    "height_px": bh,
                    "confidence": conf,
                }
            )

        if not valid:
            skipped_no_droplets += 1
            continue

        touching = droplet_touching_flags(valid)
        diameters = np.array([d["diameter_px"] for d in valid], dtype=float)
        mean_d = float(np.mean(diameters))
        std_d = float(np.std(diameters, ddof=0)) if len(diameters) > 1 else 0.0
        pdi_cv = float(std_d / mean_d) if mean_d > 0 else np.nan
        touching_fraction = float(np.mean(touching))

        sample = sample_by_id.get(sample_id)
        if sample is None:
            continue
        dest_well = f"{str(sample.well_row).upper()}{int(sample.well_column)}"
        assignment = protocol_map.by_destination_well.get(dest_well)

        row = {
            "experiment_id": int(experiment_id),
            "result_run_id": int(run.id),
            "sample_id": sample_id,
            "site_number": site_number,
            "destination_well": dest_well,
            "source_stock_well": assignment.source_stock_well if assignment else None,
            "water_volume_ul": assignment.water_volume_ul if assignment else np.nan,
            "mix_cycles": assignment.mix_cycles if assignment else np.nan,
            "dispense_type": assignment.dispense_type if assignment else "unknown",
            "dispense_subtype": assignment.dispense_subtype if assignment else "unknown",
            "image_id": int(best_image.id),
            "image_path": str(best_path),
            "sharpness": sharpness,
            "n_droplets": int(len(valid)),
            "mean_diameter_px": mean_d,
            "std_diameter_px": std_d,
            "pdi_cv": pdi_cv,
            "pct_touching": 100.0 * touching_fraction,
        }
        site_rows.append(row)

        for i, d in enumerate(valid):
            droplet_rows.append(
                {
                    "sample_id": sample_id,
                    "site_number": site_number,
                    "destination_well": dest_well,
                    "droplet_index": i + 1,
                    "diameter_px": d["diameter_px"],
                    "width_px": d["width_px"],
                    "height_px": d["height_px"],
                    "confidence": d["confidence"],
                    "touching": int(touching[i]),
                }
            )

    excluded_sites = 0
    excluded_droplets = 0
    if excluded_types:
        filtered_site_rows = [r for r in site_rows if str(r.get("dispense_type")) not in excluded_types]
        excluded_sites = len(site_rows) - len(filtered_site_rows)
        keep_keys = {
            (int(r["sample_id"]), int(r["site_number"]), str(r["destination_well"]))
            for r in filtered_site_rows
        }
        filtered_droplet_rows = [
            r
            for r in droplet_rows
            if (int(r["sample_id"]), int(r["site_number"]), str(r["destination_well"])) in keep_keys
        ]
        excluded_droplets = len(droplet_rows) - len(filtered_droplet_rows)
        site_rows = filtered_site_rows
        droplet_rows = filtered_droplet_rows

    if not site_rows:
        raise RuntimeError(
            "No valid sites after filtering. Check confidence threshold, protocol mapping, and image availability."
        )

    site_csv = output_dir / "site_metrics.csv"
    droplet_csv = output_dir / "droplet_metrics.csv"
    write_csv(site_csv, site_rows)
    write_csv(droplet_csv, droplet_rows)

    polyd_file = output_dir / "polydispersity_by_water_volume.png"
    count_file = output_dir / "droplet_count_by_dispense_type.png"
    touch_file = output_dir / "pct_touching_by_dispense_type.png"

    plot_polydispersity(site_rows, polyd_file)
    plot_bar_with_points(
        site_rows,
        y_col="n_droplets",
        y_label="Number of droplets (per site)",
        title="Droplet Count by Dispense Type",
        out_file=count_file,
        use_water_markers=True,
    )
    plot_bar_with_points(
        site_rows,
        y_col="pct_touching",
        y_label="Touching droplets (%)",
        title="Touching Fraction by Dispense Type",
        out_file=touch_file,
        use_water_markers=True,
    )

    summary_lines = [
        f"Experiment ID: {experiment_id}",
        f"ResultRun ID: {run.id}",
        f"Total (sample,site) groups: {len(groups)}",
        f"Valid analyzed sites: {len(site_rows)}",
        f"Skipped (missing image): {skipped_missing_image}",
        f"Skipped (zero valid droplets): {skipped_no_droplets}",
        f"Excluded sites by dispense filter: {excluded_sites}",
        f"Inference failures: {inference_failures}",
        f"Droplets analyzed: {len(droplet_rows)}",
        f"Excluded droplets by dispense filter: {excluded_droplets}",
        "",
        "Outputs:",
        f"- {site_csv}",
        f"- {droplet_csv}",
        f"- {polyd_file if polyd_file.exists() else '(not generated)'}",
        f"- {count_file if count_file.exists() else '(not generated)'}",
        f"- {touch_file if touch_file.exists() else '(not generated)'}",
    ]
    if assumptions:
        summary_lines.extend(["", "Assumptions / parser notes:"])
        summary_lines.extend([f"- {a}" for a in assumptions])
    if excluded_types:
        summary_lines.extend(["", "Applied output filters:"])
        summary_lines.append(f"- Excluded dispense types: {', '.join(sorted(excluded_types))}")

    summary_txt = output_dir / "summary.txt"
    summary_txt.write_text("\n".join(summary_lines) + "\n")

    print("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
