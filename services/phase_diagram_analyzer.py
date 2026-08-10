from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import matplotlib
import numpy as np
from sqlalchemy import func

from models import Image, ResultRun, Sample
from services.image_processor import ImageProcessor

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


@dataclass
class DropletSeed:
    x: float
    y: float
    radius: float
    source: str
    confidence: float = 1.0


@dataclass
class MeasurementCandidate:
    diameter_px: float
    radius_px: float
    center_x: float
    center_y: float
    fit_score: float
    inlier_fraction: float
    radial_std_px: float
    edge_strength: float
    crop_index: int
    image_id: int
    stack_number: int
    image_file_name: str
    crop_box: Tuple[int, int, int, int]
    image_path: str


class PhaseDiagramAnalyzer:
    """Estimate dense and dilute concentrations for one result-run/temperature.

    Workflow:
    1. Use the requested result run id.
    2. Pull stack images at the target temperature for both LED channels.
    3. In LED5, pick the seed image with the highest total confidence among >=N
       goldilocks-zone droplets and take top crops from that image.
    4. For each crop across both stacks, perform center-constrained circle fitting and
       pick the slice with the highest fit score per channel.
    5. Keep the best paired crop (one droplet channel slice + one condensate channel slice)
       and convert diameters to dense-phase volume fraction.
    6. Convert diameters into dense-phase volume fraction, fit a straight line vs concentration,
       and estimate dilute/dense concentrations from lever-rule intercepts.
    """

    def __init__(
        self,
        db_service,
        *,
        image_directory: Optional[str] = None,
        output_directory: str = "outputs/phase_diagrams",
        temperature_tolerance: float = 0.15,
        max_droplets_per_site: int = 10,
        crop_padding_fraction: float = 0.05,
        stack_gap_seconds: float = 2.0,
        droplet_led_channel: int = 5,
        condensate_led_channel: int = 6,
        min_droplets_per_site: int = 5,
        min_droplet_width_fraction: float = 0.05,
        max_droplet_width_fraction: float = 0.15,
        axis_consistency_tolerance: float = 0.05,
        center_offset_penalty_weight: float = 2.0,
        max_center_offset_over_radius: float = 0.95,
        min_circle_fit_score: float = 12.0,
        debug_save_crops: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.db = db_service
        self.image_directory = Path(image_directory).expanduser() if image_directory else None
        self.output_directory = Path(output_directory).expanduser()
        self.temperature_tolerance = float(temperature_tolerance)
        self.max_droplets_per_site = int(max_droplets_per_site)
        self.crop_padding_fraction = float(crop_padding_fraction)
        self.stack_gap_seconds = float(stack_gap_seconds)
        self.droplet_led_channel = int(droplet_led_channel)
        self.condensate_led_channel = int(condensate_led_channel)
        self.min_droplets_per_site = int(min_droplets_per_site)
        self.min_droplet_width_fraction = float(min_droplet_width_fraction)
        self.max_droplet_width_fraction = float(max_droplet_width_fraction)
        self.axis_consistency_tolerance = float(axis_consistency_tolerance)
        self.center_offset_penalty_weight = float(center_offset_penalty_weight)
        self.max_center_offset_over_radius = float(max_center_offset_over_radius)
        self.min_circle_fit_score = float(min_circle_fit_score)
        self.debug_save_crops = bool(debug_save_crops)
        self.image_processor = ImageProcessor(self.db)
        self.progress_callback = progress_callback

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        *,
        result_run_id: int,
        target_temperature: float,
        sample_id: Optional[int] = None,
    ) -> Dict:
        target_temperature = float(target_temperature)
        result_run_id = int(result_run_id)
        sample_id = None if sample_id is None else int(sample_id)
        self._progress(
            f"[PhaseDiagramAnalyzer] Start: result_run={result_run_id}, target_temp={target_temperature:.2f} C, "
            f"sample_filter={sample_id if sample_id is not None else 'ALL'}"
        )

        with self.db.Session() as session:
            result_run = session.query(ResultRun).filter(ResultRun.id == result_run_id).first()
            if result_run is None:
                raise ValueError(f"Result run {result_run_id} not found.")
            experiment_id = int(result_run.experiment_id)

            sample_rows = (
                session.query(Sample.id, Sample.ns_concentration)
                .filter(Sample.experiment_id == experiment_id)
                .all()
            )
            sample_concentration = {
                row.id: (float(row.ns_concentration) if row.ns_concentration is not None else None)
                for row in sample_rows
            }

            image_query = (
                session.query(Image)
                .join(Sample, Sample.id == Image.sample_id)
                .filter(
                    Sample.experiment_id == experiment_id,
                    Image.result_run_id == result_run_id,
                    Image.led_number.in_([self.droplet_led_channel, self.condensate_led_channel]),
                    func.abs(Image.temperature - target_temperature) <= self.temperature_tolerance,
                )
            )
            if sample_id is not None:
                image_query = image_query.filter(Image.sample_id == sample_id)
            selected_images = (
                image_query
                .order_by(Image.sample_id, Image.site_number, Image.timestamp, Image.stack_number, Image.id)
                .all()
            )

        if not selected_images:
            raise ValueError(
                f"No images found for result run {result_run_id} "
                f"temperature {target_temperature:.2f}±{self.temperature_tolerance:.2f} C "
                f"for LED {self.droplet_led_channel}/{self.condensate_led_channel}."
            )
        self._progress(
            f"[PhaseDiagramAnalyzer] Loaded {len(selected_images)} images within tolerance "
            f"(LED {self.droplet_led_channel}/{self.condensate_led_channel})."
        )

        output_root = (
            self.output_directory
            / f"experiment_{experiment_id}"
            / f"result_run_{result_run_id}"
            / f"temp_{target_temperature:.2f}"
        )
        output_root.mkdir(parents=True, exist_ok=True)

        site_groups = self._group_images_by_site_dual(selected_images)
        self._progress(f"[PhaseDiagramAnalyzer] Found {len(site_groups)} site(s) to process.")

        site_measurements: List[Dict] = []
        dropped_sites: List[Dict] = []
        for site_index, ((sample_id, site_number), site_channels) in enumerate(site_groups.items(), start=1):
            self._progress(
                f"[PhaseDiagramAnalyzer] Site {site_index}/{len(site_groups)}: sample={sample_id}, site={site_number}"
            )
            site_dir = output_root / f"sample_{sample_id}" / f"site_{site_number}"
            site_dir.mkdir(parents=True, exist_ok=True)

            droplet_images = site_channels.get(self.droplet_led_channel, [])
            condensate_images = site_channels.get(self.condensate_led_channel, [])
            if not droplet_images or not condensate_images:
                dropped_sites.append(
                    {
                        "sample_id": sample_id,
                        "site_number": site_number,
                        "reason": (
                            f"missing one or both LED channels "
                            f"({self.droplet_led_channel}, {self.condensate_led_channel})"
                        ),
                    }
                )
                self._progress(
                    f"[PhaseDiagramAnalyzer] Dropped sample={sample_id}, site={site_number}: "
                    f"{dropped_sites[-1]['reason']}"
                )
                continue

            droplet_events = self._split_into_stack_events(droplet_images)
            condensate_events = self._split_into_stack_events(condensate_images)
            if not droplet_events or not condensate_events:
                dropped_sites.append(
                    {
                        "sample_id": sample_id,
                        "site_number": site_number,
                        "reason": "no stack events after grouping",
                    }
                )
                self._progress(
                    f"[PhaseDiagramAnalyzer] Dropped sample={sample_id}, site={site_number}: no stack events"
                )
                continue

            selected_droplet_event = min(
                droplet_events,
                key=lambda evt: (abs(self._event_mean_temperature(evt) - target_temperature), -len(evt)),
            )
            selected_condensate_event = min(
                condensate_events,
                key=lambda evt: (
                    abs(self._event_mean_temperature(evt) - target_temperature),
                    abs(self._event_mean_timestamp_seconds(evt) - self._event_mean_timestamp_seconds(selected_droplet_event)),
                    -len(evt),
                ),
            )

            measurement, failure_reason = self._measure_site_stack_dual_channel(
                sample_id=sample_id,
                site_number=site_number,
                concentration=sample_concentration.get(sample_id),
                droplet_event_images=selected_droplet_event,
                condensate_event_images=selected_condensate_event,
                site_output_dir=site_dir,
            )
            if measurement is None:
                dropped_sites.append(
                    {
                        "sample_id": sample_id,
                        "site_number": site_number,
                        "reason": failure_reason or "no clear condensate detected in cropped stack",
                    }
                )
                self._progress(
                    f"[PhaseDiagramAnalyzer] Dropped sample={sample_id}, site={site_number}: "
                    f"{dropped_sites[-1]['reason']}"
                )
                continue
            site_measurements.append(measurement)
            self._progress(
                f"[PhaseDiagramAnalyzer] Completed sample={sample_id}, site={site_number}: "
                f"valid_crops={measurement.get('valid_crop_count', 0)}"
            )

        if not site_measurements:
            reason_counts: Dict[str, int] = {}
            for item in dropped_sites:
                reason = str(item.get("reason", "unknown"))
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            reasons_text = ", ".join([f"{reason} (n={count})" for reason, count in reason_counts.items()])
            raise RuntimeError(
                "No valid site measurements were produced. "
                f"Check image paths and condensate visibility for this temperature. Details: {reasons_text}"
            )

        sample_summary = self._aggregate_by_sample(site_measurements)
        fit_result = self._fit_dense_fraction_line(sample_summary)
        self._progress(
            f"[PhaseDiagramAnalyzer] Aggregated {len(site_measurements)} valid site(s) across "
            f"{len(sample_summary)} sample concentration point(s)."
        )
        plot_path = self._save_ratio_plot(
            sample_summary=sample_summary,
            fit_result=fit_result,
            target_temperature=target_temperature,
            output_root=output_root,
        )

        summary = {
            "experiment_id": experiment_id,
            "result_run_id": result_run_id,
            "sample_filter_id": sample_id,
            "target_temperature_c": target_temperature,
            "temperature_tolerance_c": self.temperature_tolerance,
            "axis_consistency_tolerance": self.axis_consistency_tolerance,
            "debug_save_crops": self.debug_save_crops,
            "droplet_led_channel": self.droplet_led_channel,
            "condensate_led_channel": self.condensate_led_channel,
            "selected_image_count": len(selected_images),
            "valid_site_count": len(site_measurements),
            "dropped_site_count": len(dropped_sites),
            "fit": fit_result,
            "site_measurements": site_measurements,
            "sample_summary": sample_summary,
            "dropped_sites": dropped_sites,
            "plot_path": str(plot_path),
        }

        summary_path = output_root / "analysis_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))
        summary["summary_json_path"] = str(summary_path)
        self._progress(
            f"[PhaseDiagramAnalyzer] Done. valid_sites={len(site_measurements)}, "
            f"dropped_sites={len(dropped_sites)}, plot={plot_path}"
        )
        return summary

    def get_image_names(
        self,
        *,
        result_run_id: int,
        target_temperature: float,
    ) -> List[str]:
        """Return selected image file names for the request."""
        target_temperature = float(target_temperature)
        result_run_id = int(result_run_id)
        with self.db.Session() as session:
            result_run = session.query(ResultRun).filter(ResultRun.id == result_run_id).first()
            if result_run is None:
                return []
            experiment_id = int(result_run.experiment_id)
            rows = (
                session.query(Image.file_path)
                .join(Sample, Sample.id == Image.sample_id)
                .filter(
                    Sample.experiment_id == experiment_id,
                    Image.result_run_id == result_run_id,
                    Image.led_number.in_([self.droplet_led_channel, self.condensate_led_channel]),
                    func.abs(Image.temperature - target_temperature) <= self.temperature_tolerance,
                )
                .all()
            )
        return [row.file_path for row in rows]

    # ------------------------------------------------------------------
    # Query and grouping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_images_by_site_dual(images: Sequence[Image]) -> Dict[Tuple[int, int], Dict[int, List[Image]]]:
        grouped: Dict[Tuple[int, int], Dict[int, List[Image]]] = {}
        for img in images:
            key = (int(img.sample_id), int(img.site_number))
            grouped.setdefault(key, {})
            grouped[key].setdefault(int(img.led_number), []).append(img)
        return grouped

    def _split_into_stack_events(self, images: Sequence[Image]) -> List[List[Image]]:
        if not images:
            return []
        sorted_images = sorted(
            images,
            key=lambda im: (
                im.timestamp if im.timestamp is not None else datetime.min,
                im.stack_number if im.stack_number is not None else -1,
                im.id,
            ),
        )

        events: List[List[Image]] = []
        current_event: List[Image] = []
        previous_image: Optional[Image] = None
        for image in sorted_images:
            start_new_event = False
            if previous_image is not None:
                dt = self._seconds_between(previous_image.timestamp, image.timestamp)
                temp_delta = abs(float(image.temperature or 0.0) - float(previous_image.temperature or 0.0))
                if dt > self.stack_gap_seconds or temp_delta > 0.05:
                    start_new_event = True
            if start_new_event and current_event:
                events.append(current_event)
                current_event = []
            current_event.append(image)
            previous_image = image

        if current_event:
            events.append(current_event)
        return events

    @staticmethod
    def _seconds_between(ts_a: Optional[datetime], ts_b: Optional[datetime]) -> float:
        if ts_a is None or ts_b is None:
            return 0.0
        return abs((ts_b - ts_a).total_seconds())

    @staticmethod
    def _event_mean_temperature(event_images: Sequence[Image]) -> float:
        values = [float(img.temperature) for img in event_images if img.temperature is not None]
        if not values:
            return float("nan")
        return float(np.mean(values))

    @staticmethod
    def _event_mean_timestamp_seconds(event_images: Sequence[Image]) -> float:
        values = [img.timestamp.timestamp() for img in event_images if img.timestamp is not None]
        if not values:
            return float("inf")
        return float(np.mean(values))

    # ------------------------------------------------------------------
    # Site measurement
    # ------------------------------------------------------------------

    def _measure_site_stack_dual_channel(
        self,
        *,
        sample_id: int,
        site_number: int,
        concentration: Optional[float],
        droplet_event_images: Sequence[Image],
        condensate_event_images: Sequence[Image],
        site_output_dir: Path,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        if not droplet_event_images:
            return None, f"no LED {self.droplet_led_channel} images in selected stack event"
        if not condensate_event_images:
            return None, f"no LED {self.condensate_led_channel} images in selected stack event"

        droplet_event = sorted(
            droplet_event_images,
            key=lambda im: (im.stack_number if im.stack_number is not None else -1, im.id),
        )
        condensate_event = sorted(
            condensate_event_images,
            key=lambda im: (im.stack_number if im.stack_number is not None else -1, im.id),
        )

        seed_image, selected_seeds, seed_goldilocks_count, seed_reason = self._select_seed_image_and_crops(droplet_event)
        if seed_image is None:
            return None, seed_reason or "failed to select seed image in droplet channel"
        if len(selected_seeds) < self.max_droplets_per_site:
            return (
                None,
                f"only {len(selected_seeds)} droplets available in seed image, required {self.max_droplets_per_site}",
            )

        ref_path = self._resolve_image_path(seed_image.file_path)
        if ref_path is None:
            return None, f"reference LED {self.droplet_led_channel} image missing on disk: {seed_image.file_path}"
        ref_arr = cv2.imread(str(ref_path), cv2.IMREAD_UNCHANGED)
        if ref_arr is None:
            return None, f"unable to read reference LED {self.droplet_led_channel} image: {ref_path}"
        max_h, max_w = ref_arr.shape[:2]

        crop_boxes: List[Tuple[int, int, int, int]] = []
        for seed in selected_seeds:
            crop_box = self._make_crop_box(seed, width=max_w, height=max_h)
            if crop_box is not None:
                crop_boxes.append(crop_box)
        if not crop_boxes:
            return None, "droplet crops could not be generated"
        self._progress(
            f"[PhaseDiagramAnalyzer] sample={sample_id} site={site_number}: "
            f"seed_stack={int(seed_image.stack_number if seed_image.stack_number is not None else -1)}, "
            f"goldilocks_candidates={seed_goldilocks_count}, selected_crops={len(crop_boxes)}"
        )
        crop_best: Dict[int, Dict[str, Optional[MeasurementCandidate]]] = {
            idx: {"droplet": None, "condensate": None} for idx in range(len(crop_boxes))
        }
        debug_rows: List[Dict[str, object]] = []
        missing_droplet_image_count = 0
        missing_condensate_image_count = 0

        # First pass: for each crop, pick the LED5 slice with best circle fit score.
        for image_idx, image in enumerate(droplet_event, start=1):
            if image_idx == 1 or image_idx == len(droplet_event) or image_idx % 5 == 0:
                self._progress(
                    f"[PhaseDiagramAnalyzer] sample={sample_id} site={site_number}: "
                    f"LED{self.droplet_led_channel} stack {image_idx}/{len(droplet_event)}"
                )
            image_path = self._resolve_image_path(image.file_path)
            if image_path is None:
                missing_droplet_image_count += 1
                continue
            arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if arr is None:
                missing_droplet_image_count += 1
                continue
            gray = self._to_uint8(arr)

            for crop_idx, crop_box in enumerate(crop_boxes):
                x0, y0, x1, y1 = crop_box
                crop = gray[y0:y1, x0:x1]
                if crop.size == 0:
                    continue

                droplet_measurement, droplet_reject_reason = self._measure_circle_centered(
                    crop_gray=crop,
                    max_diameter_px=None,
                )
                score = None
                if droplet_measurement is not None:
                    droplet_candidate = self._build_candidate(
                        image=image,
                        image_path=image_path,
                        crop_box=crop_box,
                        crop_index=crop_idx,
                        measurement=droplet_measurement,
                    )
                    best_droplet = crop_best[crop_idx]["droplet"]
                    if (
                        best_droplet is None
                        or droplet_candidate.fit_score > best_droplet.fit_score
                        or (
                            np.isclose(droplet_candidate.fit_score, best_droplet.fit_score)
                            and droplet_candidate.diameter_px > best_droplet.diameter_px
                        )
                    ):
                        crop_best[crop_idx]["droplet"] = droplet_candidate
                    score = droplet_candidate.fit_score

                debug_rows.append(
                    {
                        "channel_key": "droplet",
                        "led_number": self.droplet_led_channel,
                        "sample_id": sample_id,
                        "site_number": site_number,
                        "crop_index": crop_idx,
                        "image_id": int(image.id),
                        "stack_number": int(image.stack_number if image.stack_number is not None else -1),
                        "image_file_name": Path(image.file_path).name,
                        "fit_score": score,
                        "fit_score_raw": (
                            float(droplet_measurement["fit_score_raw"]) if droplet_measurement is not None else None
                        ),
                        "measurement_ok": int(droplet_measurement is not None),
                        "reject_reason": "" if droplet_measurement is not None else (droplet_reject_reason or "unknown"),
                        "diameter_px": float(droplet_measurement["diameter_px"]) if droplet_measurement is not None else None,
                        "center_x": float(droplet_measurement["center_x"]) if droplet_measurement is not None else None,
                        "center_y": float(droplet_measurement["center_y"]) if droplet_measurement is not None else None,
                        "radius_px": float(droplet_measurement["radius_px"]) if droplet_measurement is not None else None,
                        "inlier_fraction": (
                            float(droplet_measurement["inlier_fraction"]) if droplet_measurement is not None else None
                        ),
                        "radial_std_px": (
                            float(droplet_measurement["radial_std_px"]) if droplet_measurement is not None else None
                        ),
                        "edge_strength": (
                            float(droplet_measurement["edge_strength"]) if droplet_measurement is not None else None
                        ),
                        "center_offset_px": (
                            float(droplet_measurement["center_offset_px"]) if droplet_measurement is not None else None
                        ),
                        "center_offset_over_radius": (
                            float(droplet_measurement["center_offset_over_radius"])
                            if droplet_measurement is not None
                            else None
                        ),
                    }
                )

        # Second pass: for each crop, pick the LED6 slice with best circle fit score.
        for image_idx, image in enumerate(condensate_event, start=1):
            if image_idx == 1 or image_idx == len(condensate_event) or image_idx % 5 == 0:
                self._progress(
                    f"[PhaseDiagramAnalyzer] sample={sample_id} site={site_number}: "
                    f"LED{self.condensate_led_channel} stack {image_idx}/{len(condensate_event)}"
                )
            image_path = self._resolve_image_path(image.file_path)
            if image_path is None:
                missing_condensate_image_count += 1
                continue
            arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if arr is None:
                missing_condensate_image_count += 1
                continue
            gray = self._to_uint8(arr)

            for crop_idx, crop_box in enumerate(crop_boxes):
                x0, y0, x1, y1 = crop_box
                crop = gray[y0:y1, x0:x1]
                if crop.size == 0:
                    continue

                best_droplet_for_crop = crop_best[crop_idx]["droplet"]
                if best_droplet_for_crop is None:
                    continue
                condensate_measurement, condensate_reject_reason = self._measure_circle_centered(
                    crop_gray=crop,
                    max_diameter_px=0.92 * best_droplet_for_crop.diameter_px,
                )
                score = None
                if condensate_measurement is not None:
                    condensate_candidate = self._build_candidate(
                        image=image,
                        image_path=image_path,
                        crop_box=crop_box,
                        crop_index=crop_idx,
                        measurement=condensate_measurement,
                    )
                    best_condensate = crop_best[crop_idx]["condensate"]
                    if (
                        best_condensate is None
                        or condensate_candidate.fit_score > best_condensate.fit_score
                        or (
                            np.isclose(condensate_candidate.fit_score, best_condensate.fit_score)
                            and condensate_candidate.diameter_px > best_condensate.diameter_px
                        )
                    ):
                        crop_best[crop_idx]["condensate"] = condensate_candidate
                    score = condensate_candidate.fit_score

                debug_rows.append(
                    {
                        "channel_key": "condensate",
                        "led_number": self.condensate_led_channel,
                        "sample_id": sample_id,
                        "site_number": site_number,
                        "crop_index": crop_idx,
                        "image_id": int(image.id),
                        "stack_number": int(image.stack_number if image.stack_number is not None else -1),
                        "image_file_name": Path(image.file_path).name,
                        "fit_score": score,
                        "fit_score_raw": (
                            float(condensate_measurement["fit_score_raw"]) if condensate_measurement is not None else None
                        ),
                        "measurement_ok": int(condensate_measurement is not None),
                        "reject_reason": (
                            "" if condensate_measurement is not None else (condensate_reject_reason or "unknown")
                        ),
                        "diameter_px": (
                            float(condensate_measurement["diameter_px"]) if condensate_measurement is not None else None
                        ),
                        "center_x": (
                            float(condensate_measurement["center_x"]) if condensate_measurement is not None else None
                        ),
                        "center_y": (
                            float(condensate_measurement["center_y"]) if condensate_measurement is not None else None
                        ),
                        "radius_px": (
                            float(condensate_measurement["radius_px"]) if condensate_measurement is not None else None
                        ),
                        "inlier_fraction": (
                            float(condensate_measurement["inlier_fraction"])
                            if condensate_measurement is not None
                            else None
                        ),
                        "radial_std_px": (
                            float(condensate_measurement["radial_std_px"]) if condensate_measurement is not None else None
                        ),
                        "edge_strength": (
                            float(condensate_measurement["edge_strength"]) if condensate_measurement is not None else None
                        ),
                        "center_offset_px": (
                            float(condensate_measurement["center_offset_px"]) if condensate_measurement is not None else None
                        ),
                        "center_offset_over_radius": (
                            float(condensate_measurement["center_offset_over_radius"])
                            if condensate_measurement is not None
                            else None
                        ),
                    }
                )

        debug_csv_path = self._save_site_debug_csv(
            site_output_dir=site_output_dir,
            debug_rows=debug_rows,
            crop_best=crop_best,
        )

        any_droplet = any(item["droplet"] is not None for item in crop_best.values())
        if not any_droplet:
            if missing_droplet_image_count == len(droplet_event):
                return None, (
                    f"all LED {self.droplet_led_channel} stack images missing or unreadable for this site "
                    f"(debug_csv={debug_csv_path})"
                )
            return None, f"unable to estimate droplet diameter from LED 5 crops (debug_csv={debug_csv_path})"

        valid_pairs: List[Dict] = []
        dropped_crop_measurements: List[Dict] = []
        for crop_idx in sorted(crop_best.keys()):
            best_droplet = crop_best[crop_idx]["droplet"]
            best_condensate = crop_best[crop_idx]["condensate"]
            if best_droplet is None or best_condensate is None:
                dropped_crop_measurements.append(
                    {
                        "crop_index": crop_idx,
                        "reason": "missing_best_candidate_in_one_or_both_channels",
                        "droplet_diameter_x_px": (
                            None if best_droplet is None else float(best_droplet.diameter_px)
                        ),
                        "droplet_diameter_y_px": (
                            None if best_droplet is None else float(best_droplet.diameter_px)
                        ),
                        "condensate_diameter_x_px": (
                            None if best_condensate is None else float(best_condensate.diameter_px)
                        ),
                        "condensate_diameter_y_px": (
                            None if best_condensate is None else float(best_condensate.diameter_px)
                        ),
                    }
                )
                continue

            if best_condensate.diameter_px > best_droplet.diameter_px:
                clamped_diameter = best_droplet.diameter_px
                best_condensate = MeasurementCandidate(
                    diameter_px=clamped_diameter,
                    radius_px=0.5 * clamped_diameter,
                    center_x=best_condensate.center_x,
                    center_y=best_condensate.center_y,
                    fit_score=best_condensate.fit_score,
                    inlier_fraction=best_condensate.inlier_fraction,
                    radial_std_px=best_condensate.radial_std_px,
                    edge_strength=best_condensate.edge_strength,
                    crop_index=best_condensate.crop_index,
                    image_id=best_condensate.image_id,
                    stack_number=best_condensate.stack_number,
                    image_file_name=best_condensate.image_file_name,
                    crop_box=best_condensate.crop_box,
                    image_path=best_condensate.image_path,
                )

            dense_fraction = (best_condensate.diameter_px / best_droplet.diameter_px) ** 3
            dense_fraction = float(np.clip(dense_fraction, 0.0, 1.0))
            inverse_ratio = float(1.0 / dense_fraction) if dense_fraction > 0 else None

            valid_pairs.append(
                {
                    "crop_index": crop_idx,
                    "droplet": best_droplet,
                    "condensate": best_condensate,
                    "pair_score": float(best_droplet.fit_score + best_condensate.fit_score),
                    "droplet_stack_number": int(best_droplet.stack_number),
                    "condensate_stack_number": int(best_condensate.stack_number),
                    "dense_phase_fraction": dense_fraction,
                    "droplet_to_condensate_volume_ratio": inverse_ratio,
                }
            )

        if not valid_pairs:
            details = []
            for row in dropped_crop_measurements:
                details.append(
                    "crop{crop}: dx_d={dxd} dy_d={dyd} dx_c={dxc} dy_c={dyc}".format(
                        crop=int(row.get("crop_index", -1)) + 1,
                        dxd=(
                            "NA"
                            if row.get("droplet_diameter_x_px") is None
                            else f"{float(row.get('droplet_diameter_x_px')):.2f}"
                        ),
                        dyd=(
                            "NA"
                            if row.get("droplet_diameter_y_px") is None
                            else f"{float(row.get('droplet_diameter_y_px')):.2f}"
                        ),
                        dxc=(
                            "NA"
                            if row.get("condensate_diameter_x_px") is None
                            else f"{float(row.get('condensate_diameter_x_px')):.2f}"
                        ),
                        dyc=(
                            "NA"
                            if row.get("condensate_diameter_y_px") is None
                            else f"{float(row.get('condensate_diameter_y_px')):.2f}"
                        ),
                    )
                )
            detail_text = "; ".join(details) if details else "no per-crop values available"
            if missing_condensate_image_count == len(condensate_event):
                return None, (
                    f"all LED {self.condensate_led_channel} stack images missing or unreadable for this site "
                    f"(debug_csv={debug_csv_path})"
                )
            return None, (
                "no crop passed robust circle-fitting criteria in both channels "
                f"(details: {detail_text}) "
                f"(debug_csv={debug_csv_path})"
            )

        per_crop_measurements = sorted(valid_pairs, key=lambda row: int(row["crop_index"]))
        dense_values = [float(row["dense_phase_fraction"]) for row in per_crop_measurements]
        ratio_values = [
            float(row["droplet_to_condensate_volume_ratio"])
            for row in per_crop_measurements
            if row.get("droplet_to_condensate_volume_ratio") is not None
        ]
        site_dense_fraction = float(np.mean(dense_values))
        site_inverse_ratio = float(np.mean(ratio_values)) if ratio_values else None

        used_crop_dir: Optional[Path] = None
        crop_debug_paths: Dict[int, Dict[str, Optional[str]]] = {}
        if self.debug_save_crops:
            used_crop_dir = site_output_dir / "selected_crops"
            used_crop_dir.mkdir(parents=True, exist_ok=True)
            for row in per_crop_measurements:
                crop_idx = int(row["crop_index"])
                droplet = row["droplet"]
                condensate = row["condensate"]
                droplet_name = (
                    f"crop_{crop_idx + 1:02d}_droplet_led_{self.droplet_led_channel}_"
                    f"stack_{int(droplet.stack_number):03d}_{Path(droplet.image_file_name).stem}.png"
                )
                condensate_name = (
                    f"crop_{crop_idx + 1:02d}_condensate_led_{self.condensate_led_channel}_"
                    f"stack_{int(condensate.stack_number):03d}_{Path(condensate.image_file_name).stem}.png"
                )
                crop_debug_paths[crop_idx] = {
                    "droplet": self._save_candidate_crop(
                        droplet,
                        used_crop_dir / droplet_name,
                        channel_key="droplet",
                    ),
                    "condensate": self._save_candidate_crop(
                        condensate,
                        used_crop_dir / condensate_name,
                        channel_key="condensate",
                    ),
                }

        droplet_overlay_path = self._save_site_overlay_montage(
            candidates=[row["droplet"] for row in per_crop_measurements],
            out_path=site_output_dir / f"droplet_sizing_montage_led_{self.droplet_led_channel}.png",
            channel_key="droplet",
        )
        condensate_overlay_path = self._save_site_overlay_montage(
            candidates=[row["condensate"] for row in per_crop_measurements],
            out_path=site_output_dir / f"condensate_sizing_montage_led_{self.condensate_led_channel}.png",
            channel_key="condensate",
        )

        return {
            "sample_id": sample_id,
            "site_number": site_number,
            "ns_concentration_uM": concentration,
            "seed_image_id": int(seed_image.id),
            "seed_stack_number": int(seed_image.stack_number if seed_image.stack_number is not None else -1),
            "seed_image_file_name": Path(seed_image.file_path).name,
            "stack_image_count_led5": len(droplet_event),
            "stack_image_count_led6": len(condensate_event),
            "missing_stack_image_count_led5": missing_droplet_image_count,
            "missing_stack_image_count_led6": missing_condensate_image_count,
            "droplet_candidate_count_in_range": seed_goldilocks_count,
            "selected_droplet_count": len(selected_seeds),
            "crop_count": len(crop_boxes),
            "valid_crop_count": len(per_crop_measurements),
            "event_mean_temperature_led5_c": self._event_mean_temperature(droplet_event),
            "event_mean_temperature_led6_c": self._event_mean_temperature(condensate_event),
            "per_crop_measurements": [
                {
                    "crop_index": row["crop_index"],
                    "droplet": asdict(row["droplet"]),
                    "condensate": asdict(row["condensate"]),
                    "droplet_stack_number": row["droplet_stack_number"],
                    "condensate_stack_number": row["condensate_stack_number"],
                    "dense_phase_fraction": row["dense_phase_fraction"],
                    "droplet_to_condensate_volume_ratio": row["droplet_to_condensate_volume_ratio"],
                    "droplet_crop_path": (
                        crop_debug_paths.get(int(row["crop_index"]), {}).get("droplet")
                        if self.debug_save_crops
                        else None
                    ),
                    "condensate_crop_path": (
                        crop_debug_paths.get(int(row["crop_index"]), {}).get("condensate")
                        if self.debug_save_crops
                        else None
                    ),
                }
                for row in per_crop_measurements
            ],
            "dropped_crop_measurements": dropped_crop_measurements,
            "dense_phase_fraction": site_dense_fraction,
            "droplet_to_condensate_volume_ratio": site_inverse_ratio,
            "droplet_overlay_path": droplet_overlay_path,
            "condensate_overlay_path": condensate_overlay_path,
            "selected_crop_directory": (str(used_crop_dir) if used_crop_dir is not None else None),
            "debug_crop_directory": None,
            "debug_csv_path": str(debug_csv_path),
        }, None

    def _select_seed_image_and_crops(
        self,
        droplet_event_images: Sequence[Image],
    ) -> Tuple[Optional[Image], List[DropletSeed], int, Optional[str]]:
        best_image: Optional[Image] = None
        best_seeds: List[DropletSeed] = []
        best_confidence_sum = float("-inf")
        any_readable = False

        for image in droplet_event_images:
            image_path = self._resolve_image_path(image.file_path)
            if image_path is None:
                continue
            arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if arr is None:
                continue
            any_readable = True
            img_h, img_w = arr.shape[:2]
            seeds = self._seed_droplets(arr, image_path)
            seeds = self._filter_goldilocks_seeds(seeds, img_w=img_w, img_h=img_h)
            seeds = self._deduplicate_droplet_seeds(seeds)
            if len(seeds) < self.min_droplets_per_site:
                continue

            confidence_sum = float(sum(float(seed.confidence) for seed in seeds))
            if (
                confidence_sum > best_confidence_sum
                or (
                    np.isclose(confidence_sum, best_confidence_sum)
                    and len(seeds) > len(best_seeds)
                )
            ):
                best_confidence_sum = confidence_sum
                best_image = image
                best_seeds = seeds

        if not any_readable:
            return None, [], 0, f"all LED {self.droplet_led_channel} images missing or unreadable for this site"
        if best_image is None:
            return (
                None,
                [],
                0,
                f"no LED {self.droplet_led_channel} image contains at least {self.min_droplets_per_site} "
                "goldilocks-zone droplets",
            )

        selected = sorted(best_seeds, key=lambda s: (s.confidence, s.radius), reverse=True)[: self.max_droplets_per_site]
        return best_image, selected, len(best_seeds), None

    def _filter_goldilocks_seeds(
        self,
        seeds: Sequence[DropletSeed],
        *,
        img_w: int,
        img_h: int,
    ) -> List[DropletSeed]:
        min_d = self.min_droplet_width_fraction * img_w
        max_d = self.max_droplet_width_fraction * img_w
        filtered: List[DropletSeed] = []
        for seed in seeds:
            diameter = 2.0 * seed.radius
            if diameter < min_d or diameter > max_d:
                continue
            if seed.x - seed.radius <= 1 or seed.y - seed.radius <= 1:
                continue
            if seed.x + seed.radius >= img_w - 1 or seed.y + seed.radius >= img_h - 1:
                continue
            filtered.append(seed)
        return filtered

    def _deduplicate_droplet_seeds(self, seeds: Sequence[DropletSeed]) -> List[DropletSeed]:
        ordered = sorted(seeds, key=lambda s: (s.confidence, s.radius), reverse=True)
        kept: List[DropletSeed] = []
        for seed in ordered:
            duplicate = False
            for existing in kept:
                d = float(np.hypot(seed.x - existing.x, seed.y - existing.y))
                tol = max(8.0, 0.5 * min(seed.radius, existing.radius))
                if d <= tol:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(seed)
        return kept

    def _seed_droplets(self, image_array: np.ndarray, image_path: Path) -> List[DropletSeed]:
        h, w = image_array.shape[:2]
        seeds: List[DropletSeed] = []

        try:
            predictions, _ = self.image_processor._infer_image(str(image_path))
        except Exception:
            return []

        for pred in predictions:
            if self.image_processor._is_touching_edge(pred, w, h):
                continue
            radius = 0.5 * float(max(pred.get("width", 0.0), pred.get("height", 0.0)))
            if radius <= 20:
                continue
            seeds.append(
                DropletSeed(
                    x=float(pred["x"]),
                    y=float(pred["y"]),
                    radius=radius,
                    source="image_processor",
                    confidence=float(pred.get("confidence", 1.0)),
                )
            )
        return sorted(seeds, key=lambda s: (s.confidence, s.radius), reverse=True)

    def _make_crop_box(self, seed: DropletSeed, *, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
        padded_radius = seed.radius * (1.0 + self.crop_padding_fraction)
        x0 = int(max(0, np.floor(seed.x - padded_radius)))
        y0 = int(max(0, np.floor(seed.y - padded_radius)))
        x1 = int(min(width, np.ceil(seed.x + padded_radius)))
        y1 = int(min(height, np.ceil(seed.y + padded_radius)))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return (x0, y0, x1, y1)

    def _build_candidate(
        self,
        *,
        image: Image,
        image_path: Path,
        crop_box: Tuple[int, int, int, int],
        crop_index: int,
        measurement: Dict[str, float],
    ) -> MeasurementCandidate:
        diameter_px = float(measurement["diameter_px"])
        return MeasurementCandidate(
            diameter_px=diameter_px,
            radius_px=float(measurement["radius_px"]),
            center_x=float(measurement["center_x"]),
            center_y=float(measurement["center_y"]),
            fit_score=float(measurement["fit_score"]),
            inlier_fraction=float(measurement["inlier_fraction"]),
            radial_std_px=float(measurement["radial_std_px"]),
            edge_strength=float(measurement["edge_strength"]),
            crop_index=int(crop_index),
            image_id=int(image.id),
            stack_number=int(image.stack_number if image.stack_number is not None else -1),
            image_file_name=Path(image.file_path).name,
            crop_box=crop_box,
            image_path=str(image_path),
        )

    @staticmethod
    def _sample_image_values(image_f32: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        map_x = xs.astype(np.float32).reshape(1, -1)
        map_y = ys.astype(np.float32).reshape(1, -1)
        sampled = cv2.remap(
            image_f32,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )
        return sampled.reshape(-1)

    def _measure_circle_centered(
        self,
        *,
        crop_gray: np.ndarray,
        max_diameter_px: Optional[float],
    ) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
        h, w = crop_gray.shape[:2]
        min_dim = float(min(h, w))
        if min_dim < 16:
            return None, "crop_too_small"

        # Preprocess to improve robustness under uneven illumination + shot noise.
        denoise = cv2.medianBlur(crop_gray, 3)
        bg_sigma = max(6.0, 0.08 * min_dim)
        background = cv2.GaussianBlur(denoise, (0, 0), bg_sigma)
        flat_f = denoise.astype(np.float32) - background.astype(np.float32)
        flat = cv2.normalize(flat_f, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(flat)
        # Final light smoothing before gradient extraction.
        blur = cv2.GaussianBlur(enhanced, (5, 5), 0)
        blur_f32 = blur.astype(np.float32)
        sobel_x = cv2.Sobel(blur_f32, cv2.CV_32F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(blur_f32, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = cv2.magnitude(sobel_x, sobel_y)

        r_min = max(6.0, 0.10 * min_dim)
        r_max_default = 0.60 * min_dim
        if max_diameter_px is not None:
            r_max = min(r_max_default, 0.5 * float(max_diameter_px))
        else:
            r_max = r_max_default
        if r_max <= r_min + 2.0:
            return None, "invalid_radius_search_range"

        base_cx = 0.5 * (w - 1)
        base_cy = 0.5 * (h - 1)
        shift_max = max(1, int(round(0.12 * min_dim)))
        shift_step = max(1, shift_max // 3)
        shifts = list(range(-shift_max, shift_max + 1, shift_step))
        if 0 not in shifts:
            shifts.append(0)
        center_candidates: List[Tuple[float, float]] = []
        for dx in shifts:
            for dy in shifts:
                cx = base_cx + float(dx)
                cy = base_cy + float(dy)
                if cx < 2 or cy < 2 or cx > w - 3 or cy > h - 3:
                    continue
                center_candidates.append((cx, cy))
        if not center_candidates:
            center_candidates = [(base_cx, base_cy)]

        radii = np.arange(r_min, r_max + 0.1, 1.0, dtype=np.float32)
        if radii.size < 3:
            return None, "insufficient_radius_candidates"

        best: Optional[Dict[str, float]] = None
        for cx, cy in center_candidates:
            for r in radii:
                n_theta = max(180, int(round(2.0 * np.pi * float(r))))
                theta = np.linspace(0.0, 2.0 * np.pi, n_theta, endpoint=False, dtype=np.float32)
                cos_t = np.cos(theta)
                sin_t = np.sin(theta)

                x_edge = cx + r * cos_t
                y_edge = cy + r * sin_t
                if np.any(x_edge < 1) or np.any(y_edge < 1) or np.any(x_edge >= (w - 1)) or np.any(y_edge >= (h - 1)):
                    continue

                edge_vals = self._sample_image_values(grad_mag, x_edge, y_edge)
                edge_strength = float(np.percentile(edge_vals, 85.0))

                # Add a weak contrast term to prefer bright interior objects over background rings.
                delta = max(2.0, 0.08 * float(r))
                r_in = max(2.0, float(r) - delta)
                r_out = min(r_max + delta, float(r) + delta)
                x_in = cx + r_in * cos_t
                y_in = cy + r_in * sin_t
                x_out = cx + r_out * cos_t
                y_out = cy + r_out * sin_t
                in_vals = self._sample_image_values(blur_f32, x_in, y_in)
                out_vals = self._sample_image_values(blur_f32, x_out, y_out)
                contrast = max(0.0, float(np.mean(in_vals) - np.mean(out_vals)))

                center_offset = float(np.hypot(cx - base_cx, cy - base_cy))
                center_offset_over_radius = center_offset / max(float(r), 1.0)
                center_penalty = 1.0 + self.center_offset_penalty_weight * (center_offset_over_radius ** 2)
                coarse_score_raw = edge_strength + 0.25 * contrast
                coarse_score = coarse_score_raw / center_penalty
                if best is None or coarse_score > float(best["coarse_score"]):
                    best = {
                        "coarse_score": coarse_score,
                        "coarse_score_raw": coarse_score_raw,
                        "center_x": float(cx),
                        "center_y": float(cy),
                        "radius_px": float(r),
                        "center_offset_px": center_offset,
                        "center_offset_over_radius": center_offset_over_radius,
                    }

        if best is None:
            return None, "no_valid_circle_candidate"

        cx = float(best["center_x"])
        cy = float(best["center_y"])
        radius = float(best["radius_px"])
        n_theta = max(180, int(round(2.0 * np.pi * radius)))
        theta = np.linspace(0.0, 2.0 * np.pi, n_theta, endpoint=False, dtype=np.float32)
        cos_t = np.cos(theta)
        sin_t = np.sin(theta)

        radial_band = max(2, int(round(0.08 * radius)))
        radial_offsets = np.arange(-radial_band, radial_band + 1, 1, dtype=np.float32)
        r_grid = radius + radial_offsets
        r_grid = np.clip(r_grid, 2.0, r_max + 2.0)

        refined_r = np.zeros(n_theta, dtype=np.float32)
        refined_edge = np.zeros(n_theta, dtype=np.float32)
        for i in range(n_theta):
            x_line = cx + r_grid * cos_t[i]
            y_line = cy + r_grid * sin_t[i]
            line_vals = self._sample_image_values(grad_mag, x_line, y_line)
            best_idx = int(np.argmax(line_vals))
            refined_r[i] = float(r_grid[best_idx])
            refined_edge[i] = float(line_vals[best_idx])

        radial_std_px = float(np.std(refined_r))
        tol_px = max(2.0, float(self.axis_consistency_tolerance) * radius)
        inlier_fraction = float(np.mean(np.abs(refined_r - radius) <= tol_px))
        edge_strength = float(np.percentile(refined_edge, 80.0))
        center_offset_px = float(np.hypot(cx - base_cx, cy - base_cy))
        center_offset_over_radius = center_offset_px / max(radius, 1.0)

        if inlier_fraction < 0.22:
            return None, "low_circle_inlier_fraction"
        if radial_std_px > max(4.0, 0.35 * radius):
            return None, "high_radial_variance"
        if edge_strength <= 0.5:
            return None, "weak_circle_edge_strength"
        if center_offset_over_radius > self.max_center_offset_over_radius:
            return None, "center_offset_too_large"

        fit_score_raw = float((edge_strength * inlier_fraction) / (1.0 + (radial_std_px / max(radius, 1.0))))
        center_penalty = 1.0 + self.center_offset_penalty_weight * (center_offset_over_radius ** 2)
        fit_score = fit_score_raw / center_penalty
        diameter_px = float(2.0 * radius)
        if diameter_px < 6.0:
            return None, "diameter_too_small"
        if max_diameter_px is not None and diameter_px > float(max_diameter_px):
            return None, "diameter_exceeds_limit"
        if fit_score < self.min_circle_fit_score:
            return None, "fit_score_too_low"

        return (
            {
                "diameter_px": diameter_px,
                "radius_px": radius,
                "center_x": cx,
                "center_y": cy,
                "fit_score": fit_score,
                "fit_score_raw": fit_score_raw,
                "inlier_fraction": inlier_fraction,
                "radial_std_px": radial_std_px,
                "edge_strength": edge_strength,
                "center_offset_px": center_offset_px,
                "center_offset_over_radius": center_offset_over_radius,
            },
            None,
        )

    @staticmethod
    def _save_site_debug_csv(
        *,
        site_output_dir: Path,
        debug_rows: Sequence[Dict[str, object]],
        crop_best: Dict[int, Dict[str, Optional[MeasurementCandidate]]],
    ) -> Path:
        out_path = site_output_dir / "sizing_debug.csv"
        droplet_selected = {
            (int(idx), int(item["droplet"].image_id))
            for idx, item in crop_best.items()
            if item.get("droplet") is not None
        }
        condensate_selected = {
            (int(idx), int(item["condensate"].image_id))
            for idx, item in crop_best.items()
            if item.get("condensate") is not None
        }

        fieldnames = [
            "channel_key",
            "led_number",
            "sample_id",
            "site_number",
            "crop_index",
            "image_id",
            "stack_number",
            "image_file_name",
            "fit_score",
            "fit_score_raw",
            "selected_for_sizing",
            "measurement_ok",
            "reject_reason",
            "diameter_px",
            "center_x",
            "center_y",
            "radius_px",
            "inlier_fraction",
            "radial_std_px",
            "edge_strength",
            "center_offset_px",
            "center_offset_over_radius",
        ]

        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in debug_rows:
                channel_key = str(row.get("channel_key", ""))
                crop_index = int(row.get("crop_index", -1))
                image_id = int(row.get("image_id", -1))
                if channel_key == "droplet":
                    selected = (crop_index, image_id) in droplet_selected
                elif channel_key == "condensate":
                    selected = (crop_index, image_id) in condensate_selected
                else:
                    selected = False
                out_row = {k: row.get(k) for k in fieldnames}
                out_row["selected_for_sizing"] = int(selected)
                writer.writerow(out_row)
        return out_path

    def _save_candidate_crop(
        self,
        candidate: MeasurementCandidate,
        out_path: Path,
        *,
        channel_key: str,
    ) -> Optional[str]:
        vis = self._render_candidate_overlay(candidate, channel_key=channel_key)
        if vis is None:
            return None
        if cv2.imwrite(str(out_path), vis):
            return str(out_path)
        return None

    def _render_candidate_overlay(
        self,
        candidate: MeasurementCandidate,
        *,
        channel_key: str,
    ) -> Optional[np.ndarray]:
        image = cv2.imread(candidate.image_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            return None
        gray = self._to_uint8(image)
        x0, y0, x1, y1 = candidate.crop_box
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        vis = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        if channel_key == "droplet":
            circle_color = (0, 220, 0)   # green
        else:
            circle_color = (0, 220, 220)  # yellow
        center = (int(round(candidate.center_x)), int(round(candidate.center_y)))
        radius = max(1, int(round(candidate.radius_px)))
        cv2.circle(vis, center, radius, circle_color, 1, cv2.LINE_AA)
        cross = max(4, int(round(0.08 * radius)))
        cv2.line(
            vis,
            (center[0] - cross, center[1]),
            (center[0] + cross, center[1]),
            circle_color,
            1,
            cv2.LINE_AA,
        )
        cv2.line(
            vis,
            (center[0], center[1] - cross),
            (center[0], center[1] + cross),
            circle_color,
            1,
            cv2.LINE_AA,
        )

        text = (
            f"d={candidate.diameter_px:.2f}px "
            f"fit={candidate.fit_score:.2f} "
            f"inlier={candidate.inlier_fraction:.2f}"
        )
        cv2.putText(vis, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1, cv2.LINE_AA)
        return vis

    def _save_site_overlay_montage(
        self,
        *,
        candidates: Sequence[MeasurementCandidate],
        out_path: Path,
        channel_key: str,
    ) -> Optional[str]:
        if not candidates:
            return None
        tiles: List[np.ndarray] = []
        for candidate in candidates:
            tile = self._render_candidate_overlay(candidate, channel_key=channel_key)
            if tile is not None:
                tiles.append(tile)
        if not tiles:
            return None

        cols = min(3, len(tiles))
        rows = int(np.ceil(len(tiles) / cols))
        tile_h = max(tile.shape[0] for tile in tiles)
        tile_w = max(tile.shape[1] for tile in tiles)
        canvas = np.zeros((rows * tile_h, cols * tile_w, 3), dtype=np.uint8)

        for idx, tile in enumerate(tiles):
            r = idx // cols
            c = idx % cols
            h, w = tile.shape[:2]
            y0 = r * tile_h
            x0 = c * tile_w
            canvas[y0:y0 + h, x0:x0 + w] = tile

        if cv2.imwrite(str(out_path), canvas):
            return str(out_path)
        return None

    # ------------------------------------------------------------------
    # Aggregation, fit, plotting
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_by_sample(site_measurements: Sequence[Dict]) -> List[Dict]:
        per_sample: Dict[int, List[Dict]] = {}
        for item in site_measurements:
            per_sample.setdefault(int(item["sample_id"]), []).append(item)

        summary: List[Dict] = []
        for sample_id, rows in per_sample.items():
            conc_values = [r.get("ns_concentration_uM") for r in rows if r.get("ns_concentration_uM") is not None]
            concentration = float(np.mean(conc_values)) if conc_values else None

            # Use all accepted per-crop measurements (stack-derived readings) to
            # estimate central tendency and uncertainty for each concentration point.
            dense_fractions: List[float] = []
            inverse_ratios: List[float] = []
            for row in rows:
                per_crop = row.get("per_crop_measurements", []) or []
                if per_crop:
                    for crop_row in per_crop:
                        if crop_row.get("dense_phase_fraction") is not None:
                            dense_fractions.append(float(crop_row["dense_phase_fraction"]))
                        if crop_row.get("droplet_to_condensate_volume_ratio") is not None:
                            inverse_ratios.append(float(crop_row["droplet_to_condensate_volume_ratio"]))
                else:
                    if row.get("dense_phase_fraction") is not None:
                        dense_fractions.append(float(row["dense_phase_fraction"]))
                    if row.get("droplet_to_condensate_volume_ratio") is not None:
                        inverse_ratios.append(float(row["droplet_to_condensate_volume_ratio"]))

            dense_std = float(np.std(dense_fractions)) if len(dense_fractions) > 1 else 0.0
            dense_sem = float(dense_std / np.sqrt(len(dense_fractions))) if dense_fractions else 0.0
            mean_dense_fraction = float(np.mean(dense_fractions)) if dense_fractions else None
            summary.append(
                {
                    "sample_id": sample_id,
                    "ns_concentration_uM": concentration,
                    "site_count": len(rows),
                    "reading_count": len(dense_fractions),
                    "mean_dense_phase_fraction": mean_dense_fraction,
                    "std_dense_phase_fraction": dense_std,
                    "sem_dense_phase_fraction": dense_sem,
                    "mean_droplet_to_condensate_volume_ratio": (
                        float(np.mean(inverse_ratios)) if inverse_ratios else None
                    ),
                }
            )

        summary.sort(key=lambda row: (float("inf") if row["ns_concentration_uM"] is None else row["ns_concentration_uM"]))
        return summary

    @staticmethod
    def _fit_dense_fraction_line(sample_summary: Sequence[Dict]) -> Dict:
        x_vals: List[float] = []
        y_vals: List[float] = []
        for row in sample_summary:
            concentration = row.get("ns_concentration_uM")
            fraction = row.get("mean_dense_phase_fraction")
            if concentration is None or fraction is None:
                continue
            x_vals.append(float(concentration))
            y_vals.append(float(fraction))

        if len(x_vals) < 2:
            return {
                "success": False,
                "reason": "At least two concentration points are required for linear fit.",
                "n_points": len(x_vals),
            }

        x_arr = np.array(x_vals, dtype=float)
        y_arr = np.array(y_vals, dtype=float)
        slope, intercept = np.polyfit(x_arr, y_arr, 1)
        y_fit = slope * x_arr + intercept
        ss_res = float(np.sum((y_arr - y_fit) ** 2))
        ss_tot = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
        r_squared = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else float("nan")

        if abs(slope) < 1e-12:
            return {
                "success": False,
                "reason": "Fitted slope is too close to zero for lever-rule intercepts.",
                "n_points": len(x_vals),
                "slope": float(slope),
                "intercept": float(intercept),
                "r_squared": r_squared,
            }

        c_dilute = float(-intercept / slope)
        c_dense = float((1.0 - intercept) / slope)
        return {
            "success": True,
            "n_points": len(x_vals),
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": r_squared,
            "dense_concentration_uM": c_dense,
            "dilute_concentration_uM": c_dilute,
        }

    def _save_ratio_plot(
        self,
        *,
        sample_summary: Sequence[Dict],
        fit_result: Dict,
        target_temperature: float,
        output_root: Path,
    ) -> Path:
        x_vals: List[float] = []
        y_vals: List[float] = []
        y_err_vals: List[float] = []
        for row in sample_summary:
            concentration = row.get("ns_concentration_uM")
            fraction = row.get("mean_dense_phase_fraction")
            if concentration is None or fraction is None:
                continue
            x_vals.append(float(concentration))
            y_vals.append(float(fraction))
            y_err_vals.append(float(row.get("std_dense_phase_fraction") or 0.0))

        fig, ax = plt.subplots(figsize=(9, 6))
        ax.errorbar(
            x_vals,
            y_vals,
            yerr=y_err_vals,
            fmt="o",
            color="tab:blue",
            ecolor="tab:blue",
            elinewidth=1.2,
            capsize=3,
            alpha=0.9,
            label="Measured mean ±1 SD",
        )

        for row in sample_summary:
            c = row.get("ns_concentration_uM")
            f = row.get("mean_dense_phase_fraction")
            n = row.get("site_count", 0)
            n_read = row.get("reading_count", 0)
            if c is None or f is None:
                continue
            ax.text(float(c), float(f), f" sites={n}, reads={n_read}", fontsize=8, va="bottom")

        if fit_result.get("success", False):
            slope = float(fit_result["slope"])
            intercept = float(fit_result["intercept"])
            x_min = min(x_vals) * 0.95
            x_max = max(x_vals) * 1.05
            fit_x = np.linspace(x_min, x_max, 200)
            fit_y = slope * fit_x + intercept
            ax.plot(fit_x, fit_y, "--", color="tab:red", label="Linear fit")

            txt = (
                f"y = {slope:.5f}x + {intercept:.5f}\n"
                f"R² = {fit_result['r_squared']:.4f}\n"
                f"Dilute = {fit_result['dilute_concentration_uM']:.3f} uM\n"
                f"Dense = {fit_result['dense_concentration_uM']:.3f} uM"
            )
            ax.text(
                0.02,
                0.98,
                txt,
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=9,
                bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85},
            )

        ax.axhline(0.0, color="gray", lw=1, ls=":")
        ax.axhline(1.0, color="gray", lw=1, ls=":")
        ax.set_xlabel("Starting concentration (uM)")
        ax.set_ylabel("Dense-phase volume fraction (condensate/droplet)")
        ax.set_title(
            "Experiment volume ratio fit at "
            f"{target_temperature:.2f} C (LED {self.droplet_led_channel} droplet, "
            f"LED {self.condensate_led_channel} condensate)"
        )
        ax.set_ylim(-0.05, 1.05)
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend(loc="best")

        plot_path = output_root / "ratio_vs_concentration.png"
        fig.tight_layout()
        fig.savefig(plot_path, dpi=200)
        plt.close(fig)
        return plot_path

    # ------------------------------------------------------------------
    # Image path / conversion helpers
    # ------------------------------------------------------------------

    def _resolve_image_path(self, file_path: str) -> Optional[Path]:
        if not file_path:
            return None
        raw = Path(file_path).expanduser()
        candidates = [raw]
        if not raw.is_absolute():
            if self.image_directory is not None:
                candidates.append((self.image_directory / raw).expanduser())
            candidates.append((Path.cwd() / raw).expanduser())
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return None

    @staticmethod
    def _to_uint8(image: np.ndarray) -> np.ndarray:
        if image is None:
            raise ValueError("Cannot convert an empty image.")
        if len(image.shape) == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.dtype == np.uint8:
            return image
        image_f = image.astype(np.float32)
        lo, hi = np.percentile(image_f, (1.0, 99.0))
        if hi <= lo:
            lo = float(np.min(image_f))
            hi = float(np.max(image_f))
        if hi <= lo:
            return np.zeros_like(image, dtype=np.uint8)
        norm = (image_f - lo) / (hi - lo)
        norm = np.clip(norm, 0.0, 1.0)
        return (norm * 255.0).astype(np.uint8)
