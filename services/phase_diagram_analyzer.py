from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

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


@dataclass
class MeasurementCandidate:
    diameter_px: float
    radius_px: float
    center_x: float
    center_y: float
    crop_index: int
    image_id: int
    stack_number: int
    image_file_name: str
    crop_box: Tuple[int, int, int, int]
    image_path: str


class PhaseDiagramAnalyzer:
    """Estimate dense and dilute concentrations for one result-run/temperature/channel.

    Workflow:
    1. Use the requested result run id.
    2. Pull stack images at the target temperature and LED channel.
    3. For each sample/site, pick the best-focus image, seed droplets via ImageProcessor,
       build cropped stacks, and use classical CV to detect droplet + condensate diameters.
    4. Convert diameters into dense-phase volume fraction, fit a straight line vs concentration,
       and estimate dilute/dense concentrations from lever-rule intercepts.
    """

    def __init__(
        self,
        db_service,
        *,
        image_directory: Optional[str] = None,
        output_directory: str = "outputs/phase_diagrams",
        temperature_tolerance: float = 0.15,
        max_droplets_per_site: int = 5,
        crop_padding_fraction: float = 0.15,
        stack_gap_seconds: float = 2.0,
    ):
        self.db = db_service
        self.image_directory = Path(image_directory).expanduser() if image_directory else None
        self.output_directory = Path(output_directory).expanduser()
        self.temperature_tolerance = float(temperature_tolerance)
        self.max_droplets_per_site = int(max_droplets_per_site)
        self.crop_padding_fraction = float(crop_padding_fraction)
        self.stack_gap_seconds = float(stack_gap_seconds)
        try:
            self.image_processor = ImageProcessor(self.db)
        except Exception:
            # Allow pure-classical fallback when ImageProcessor cannot be constructed
            # (for example when AppConfig has not been initialised yet).
            self.image_processor = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        *,
        result_run_id: int,
        target_temperature: float,
        led_channel: int,
    ) -> Dict:
        target_temperature = float(target_temperature)
        led_channel = int(led_channel)
        result_run_id = int(result_run_id)

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

            selected_images = (
                session.query(Image)
                .join(Sample, Sample.id == Image.sample_id)
                .filter(
                    Sample.experiment_id == experiment_id,
                    Image.result_run_id == result_run_id,
                    Image.led_number == led_channel,
                    func.abs(Image.temperature - target_temperature) <= self.temperature_tolerance,
                )
                .order_by(Image.sample_id, Image.site_number, Image.timestamp, Image.stack_number, Image.id)
                .all()
            )

        if not selected_images:
            raise ValueError(
                f"No images found for result run {result_run_id} "
                f"temperature {target_temperature:.2f}±{self.temperature_tolerance:.2f} C, LED {led_channel}."
            )

        output_root = (
            self.output_directory
            / f"experiment_{experiment_id}"
            / f"result_run_{result_run_id}"
            / f"temp_{target_temperature:.2f}_led_{led_channel}"
        )
        output_root.mkdir(parents=True, exist_ok=True)

        site_groups = self._group_images_by_site(selected_images)

        site_measurements: List[Dict] = []
        dropped_sites: List[Dict] = []
        for (sample_id, site_number), site_images in site_groups.items():
            site_dir = output_root / f"sample_{sample_id}" / f"site_{site_number}"
            site_dir.mkdir(parents=True, exist_ok=True)

            events = self._split_into_stack_events(site_images)
            if not events:
                dropped_sites.append(
                    {
                        "sample_id": sample_id,
                        "site_number": site_number,
                        "reason": "no stack events after grouping",
                    }
                )
                continue

            selected_event = min(
                events,
                key=lambda evt: (abs(self._event_mean_temperature(evt) - target_temperature), -len(evt)),
            )
            measurement, failure_reason = self._measure_site_stack(
                sample_id=sample_id,
                site_number=site_number,
                concentration=sample_concentration.get(sample_id),
                event_images=selected_event,
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
                continue
            site_measurements.append(measurement)

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
        plot_path = self._save_ratio_plot(
            sample_summary=sample_summary,
            fit_result=fit_result,
            target_temperature=target_temperature,
            led_channel=led_channel,
            output_root=output_root,
        )

        summary = {
            "experiment_id": experiment_id,
            "result_run_id": result_run_id,
            "target_temperature_c": target_temperature,
            "temperature_tolerance_c": self.temperature_tolerance,
            "led_channel": led_channel,
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
        return summary

    def get_image_names(
        self,
        *,
        result_run_id: int,
        target_temperature: float,
        led_channel: int,
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
                    Image.led_number == led_channel,
                    func.abs(Image.temperature - target_temperature) <= self.temperature_tolerance,
                )
                .all()
            )
        return [row.file_path for row in rows]

    # ------------------------------------------------------------------
    # Query and grouping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_images_by_site(images: Sequence[Image]) -> Dict[Tuple[int, int], List[Image]]:
        grouped: Dict[Tuple[int, int], List[Image]] = {}
        for img in images:
            key = (int(img.sample_id), int(img.site_number))
            grouped.setdefault(key, []).append(img)
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

    # ------------------------------------------------------------------
    # Site measurement
    # ------------------------------------------------------------------

    def _measure_site_stack(
        self,
        *,
        sample_id: int,
        site_number: int,
        concentration: Optional[float],
        event_images: Sequence[Image],
        site_output_dir: Path,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        if not event_images:
            return None, "no images in selected stack event"

        sorted_event = sorted(
            event_images,
            key=lambda im: (im.stack_number if im.stack_number is not None else -1, im.id),
        )
        best_focus_image = max(sorted_event, key=lambda im: float(im.focus_score or 0.0))
        best_focus_path = self._resolve_image_path(best_focus_image.file_path)
        if best_focus_path is None:
            return None, f"best-focus image missing on disk: {best_focus_image.file_path}"

        best_focus_arr = cv2.imread(str(best_focus_path), cv2.IMREAD_UNCHANGED)
        if best_focus_arr is None:
            return None, f"unable to read best-focus image: {best_focus_path}"

        seeds = self._seed_droplets(best_focus_arr, best_focus_path)
        if not seeds:
            return None, "unable to identify droplets in best-focus image"
        seeds = seeds[: self.max_droplets_per_site]

        max_h, max_w = best_focus_arr.shape[:2]
        crop_boxes: List[Tuple[int, int, int, int]] = []
        for seed in seeds:
            crop_box = self._make_crop_box(seed, width=max_w, height=max_h)
            if crop_box is not None:
                crop_boxes.append(crop_box)
        if not crop_boxes:
            return None, "droplet crops could not be generated"

        temp_crop_dir = site_output_dir / "crops"
        temp_crop_dir.mkdir(parents=True, exist_ok=True)

        crop_best: Dict[int, Dict[str, Optional[MeasurementCandidate]]] = {
            idx: {"droplet": None, "condensate": None} for idx in range(len(crop_boxes))
        }
        missing_image_count = 0

        for image in sorted_event:
            image_path = self._resolve_image_path(image.file_path)
            if image_path is None:
                missing_image_count += 1
                continue
            arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if arr is None:
                missing_image_count += 1
                continue
            gray = self._to_uint8(arr)

            for crop_idx, crop_box in enumerate(crop_boxes):
                x0, y0, x1, y1 = crop_box
                crop = gray[y0:y1, x0:x1]
                if crop.size == 0:
                    continue

                crop_name = (
                    f"stack_{int(image.stack_number or 0):03d}_droplet_{crop_idx + 1:02d}_"
                    f"{Path(image.file_path).name}"
                )
                cv2.imwrite(str(temp_crop_dir / crop_name), crop)

                droplet_circle = self._detect_outer_droplet(crop)
                if droplet_circle is not None:
                    droplet_candidate = self._build_candidate(
                        image=image,
                        image_path=image_path,
                        crop_box=crop_box,
                        crop_index=crop_idx,
                        circle=droplet_circle,
                    )
                    best_droplet = crop_best[crop_idx]["droplet"]
                    if best_droplet is None or droplet_candidate.diameter_px > best_droplet.diameter_px:
                        crop_best[crop_idx]["droplet"] = droplet_candidate

                condensate_circle = self._detect_condensate(crop, droplet_circle=droplet_circle)
                if condensate_circle is not None:
                    condensate_candidate = self._build_candidate(
                        image=image,
                        image_path=image_path,
                        crop_box=crop_box,
                        crop_index=crop_idx,
                        circle=condensate_circle,
                    )
                    best_condensate = crop_best[crop_idx]["condensate"]
                    if best_condensate is None or condensate_candidate.diameter_px > best_condensate.diameter_px:
                        crop_best[crop_idx]["condensate"] = condensate_candidate

        any_droplet = any(item["droplet"] is not None for item in crop_best.values())
        if not any_droplet:
            if missing_image_count == len(sorted_event):
                return None, "all stack images missing or unreadable for this site"
            return None, "unable to estimate outer droplet diameter from crops"

        valid_per_crop: List[Dict] = []
        for crop_idx in sorted(crop_best.keys()):
            best_droplet = crop_best[crop_idx]["droplet"]
            best_condensate = crop_best[crop_idx]["condensate"]
            if best_droplet is None or best_condensate is None:
                continue

            if best_condensate.diameter_px > best_droplet.diameter_px:
                best_condensate = MeasurementCandidate(
                    diameter_px=best_droplet.diameter_px,
                    radius_px=best_droplet.radius_px,
                    center_x=best_condensate.center_x,
                    center_y=best_condensate.center_y,
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

            valid_per_crop.append(
                {
                    "crop_index": crop_idx,
                    "droplet": best_droplet,
                    "condensate": best_condensate,
                    "dense_phase_fraction": dense_fraction,
                    "droplet_to_condensate_volume_ratio": inverse_ratio,
                }
            )

        if not valid_per_crop:
            if missing_image_count == len(sorted_event):
                return None, "all stack images missing or unreadable for this site"
            return None, "no clear condensate detected in any crop of this stack"

        droplet_overlay_path = site_output_dir / "droplet_max_overlay.png"
        condensate_overlay_path = site_output_dir / "condensate_max_overlay.png"
        droplet_candidates = [row["droplet"] for row in valid_per_crop]
        condensate_candidates = [row["condensate"] for row in valid_per_crop]
        self._save_site_overlay_montage(droplet_candidates, droplet_overlay_path, "Droplet")
        self._save_site_overlay_montage(condensate_candidates, condensate_overlay_path, "Condensate")

        dense_fractions = [float(row["dense_phase_fraction"]) for row in valid_per_crop]
        inverse_ratios = [
            float(row["droplet_to_condensate_volume_ratio"])
            for row in valid_per_crop
            if row["droplet_to_condensate_volume_ratio"] is not None
        ]
        site_dense_fraction = float(np.mean(dense_fractions)) if dense_fractions else 0.0
        site_inverse_ratio = float(np.mean(inverse_ratios)) if inverse_ratios else None

        return {
            "sample_id": sample_id,
            "site_number": site_number,
            "ns_concentration_uM": concentration,
            "stack_image_count": len(sorted_event),
            "missing_stack_image_count": missing_image_count,
            "crop_count": len(crop_boxes),
            "valid_crop_count": len(valid_per_crop),
            "event_mean_temperature_c": self._event_mean_temperature(sorted_event),
            "per_crop_measurements": [
                {
                    "crop_index": row["crop_index"],
                    "droplet": asdict(row["droplet"]),
                    "condensate": asdict(row["condensate"]),
                    "dense_phase_fraction": row["dense_phase_fraction"],
                    "droplet_to_condensate_volume_ratio": row["droplet_to_condensate_volume_ratio"],
                }
                for row in valid_per_crop
            ],
            "dense_phase_fraction": site_dense_fraction,
            "droplet_to_condensate_volume_ratio": site_inverse_ratio,
            "droplet_overlay_path": str(droplet_overlay_path),
            "condensate_overlay_path": str(condensate_overlay_path),
            "temp_crop_directory": str(temp_crop_dir),
        }, None

    def _seed_droplets(self, image_array: np.ndarray, image_path: Path) -> List[DropletSeed]:
        h, w = image_array.shape[:2]
        seeds: List[DropletSeed] = []

        try:
            if self.image_processor is not None:
                predictions, _ = self.image_processor._infer_image(str(image_path))
                for pred in predictions:
                    if self.image_processor._is_touching_edge(pred, w, h):
                        continue
                    radius = 0.5 * float(max(pred.get("width", 0.0), pred.get("height", 0.0)))
                    if radius <= 2:
                        continue
                    seeds.append(
                        DropletSeed(
                            x=float(pred["x"]),
                            y=float(pred["y"]),
                            radius=radius,
                            source="image_processor",
                        )
                    )
        except Exception:
            seeds = []

        if seeds:
            seeds = sorted(seeds, key=lambda s: s.radius, reverse=True)
            return seeds

        fallback = self._detect_droplets_classical(image_array)
        return fallback

    def _detect_droplets_classical(self, image_array: np.ndarray) -> List[DropletSeed]:
        gray = self._to_uint8(image_array)
        blur = cv2.GaussianBlur(gray, (9, 9), 1.5)
        h, w = blur.shape[:2]
        min_radius = max(20, int(min(h, w) * 0.02))
        max_radius = max(min_radius + 5, int(min(h, w) * 0.18))
        circles = cv2.HoughCircles(
            blur,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=2.2 * min_radius,
            param1=80,
            param2=30,
            minRadius=min_radius,
            maxRadius=max_radius,
        )
        seeds: List[DropletSeed] = []
        if circles is not None:
            for c in circles[0]:
                x, y, r = float(c[0]), float(c[1]), float(c[2])
                if x - r <= 1 or y - r <= 1 or x + r >= (w - 1) or y + r >= (h - 1):
                    continue
                seeds.append(DropletSeed(x=x, y=y, radius=r, source="classical_fallback"))
        return sorted(seeds, key=lambda s: s.radius, reverse=True)

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
        circle: Tuple[float, float, float],
    ) -> MeasurementCandidate:
        cx, cy, radius = circle
        return MeasurementCandidate(
            diameter_px=2.0 * float(radius),
            radius_px=float(radius),
            center_x=float(cx),
            center_y=float(cy),
            crop_index=int(crop_index),
            image_id=int(image.id),
            stack_number=int(image.stack_number if image.stack_number is not None else -1),
            image_file_name=Path(image.file_path).name,
            crop_box=crop_box,
            image_path=str(image_path),
        )

    # ------------------------------------------------------------------
    # Classical CV measurement on crops
    # ------------------------------------------------------------------

    def _detect_outer_droplet(self, crop_gray: np.ndarray) -> Optional[Tuple[float, float, float]]:
        h, w = crop_gray.shape[:2]
        if min(h, w) < 12:
            return None

        blur = cv2.GaussianBlur(crop_gray, (7, 7), 1.5)
        min_radius = int(max(6, min(h, w) * 0.30))
        max_radius = int(max(min_radius + 2, min(h, w) * 0.52))
        circles = cv2.HoughCircles(
            blur,
            cv2.HOUGH_GRADIENT,
            dp=1.1,
            minDist=min(h, w) * 0.5,
            param1=90,
            param2=22,
            minRadius=min_radius,
            maxRadius=max_radius,
        )
        if circles is not None and len(circles[0]) > 0:
            cx, cy, radius = circles[0][0]
            return float(cx), float(cy), float(radius)

        edges = cv2.Canny(blur, 30, 120)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < 40:
            return None
        (cx, cy), radius = cv2.minEnclosingCircle(largest)
        if radius < 4:
            return None
        return float(cx), float(cy), float(radius)

    def _detect_condensate(
        self,
        crop_gray: np.ndarray,
        *,
        droplet_circle: Optional[Tuple[float, float, float]],
    ) -> Optional[Tuple[float, float, float]]:
        h, w = crop_gray.shape[:2]
        if min(h, w) < 12:
            return None

        blur = cv2.GaussianBlur(crop_gray, (5, 5), 0)
        percentile_threshold = int(np.percentile(blur, 96))
        _, mask = cv2.threshold(blur, percentile_threshold, 255, cv2.THRESH_BINARY)

        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        centre_x = w * 0.5
        centre_y = h * 0.5
        best_score = None
        best_circle = None
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 12:
                continue
            (cx, cy), radius = cv2.minEnclosingCircle(contour)
            if radius < 2:
                continue
            circularity = area / (np.pi * radius * radius + 1e-8)
            if circularity < 0.40:
                continue

            if droplet_circle is not None:
                _, _, droplet_r = droplet_circle
                if radius >= droplet_r * 0.92:
                    continue

            dist = float(np.hypot(cx - centre_x, cy - centre_y))
            score = float(area) - 2.0 * dist
            if best_score is None or score > best_score:
                best_score = score
                best_circle = (float(cx), float(cy), float(radius))

        return best_circle

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
            dense_fractions = [float(r["dense_phase_fraction"]) for r in rows]
            inverse_ratios = [
                float(r["droplet_to_condensate_volume_ratio"])
                for r in rows
                if r.get("droplet_to_condensate_volume_ratio") is not None
            ]
            summary.append(
                {
                    "sample_id": sample_id,
                    "ns_concentration_uM": concentration,
                    "site_count": len(rows),
                    "mean_dense_phase_fraction": float(np.mean(dense_fractions)),
                    "std_dense_phase_fraction": float(np.std(dense_fractions)) if len(dense_fractions) > 1 else 0.0,
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
        led_channel: int,
        output_root: Path,
    ) -> Path:
        x_vals: List[float] = []
        y_vals: List[float] = []
        for row in sample_summary:
            concentration = row.get("ns_concentration_uM")
            fraction = row.get("mean_dense_phase_fraction")
            if concentration is None or fraction is None:
                continue
            x_vals.append(float(concentration))
            y_vals.append(float(fraction))

        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter(x_vals, y_vals, color="tab:blue", label="Measured (mean per sample)")

        for row in sample_summary:
            c = row.get("ns_concentration_uM")
            f = row.get("mean_dense_phase_fraction")
            n = row.get("site_count", 0)
            if c is None or f is None:
                continue
            ax.text(float(c), float(f), f" n={n}", fontsize=8, va="bottom")

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
            f"Experiment volume ratio fit at {target_temperature:.2f} C (LED {led_channel})"
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
    # Overlay output
    # ------------------------------------------------------------------

    def _render_overlay_tile(self, candidate: MeasurementCandidate, label: str) -> Optional[np.ndarray]:
        image = cv2.imread(candidate.image_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            return None
        gray = self._to_uint8(image)
        x0, y0, x1, y1 = candidate.crop_box
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        vis = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)

        cx = int(round(candidate.center_x))
        cy = int(round(candidate.center_y))
        radius = int(round(candidate.radius_px))
        cv2.circle(vis, (cx, cy), max(radius, 1), (0, 255, 255), 2)
        cv2.line(vis, (cx - radius, cy), (cx + radius, cy), (0, 220, 0), 2)
        text = f"Crop {candidate.crop_index + 1} {label}: {candidate.diameter_px:.2f}px"
        cv2.putText(vis, text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(
            vis,
            f"stack={candidate.stack_number} file={candidate.image_file_name}",
            (10, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        return vis

    def _save_site_overlay_montage(
        self,
        candidates: Sequence[MeasurementCandidate],
        out_path: Path,
        label: str,
    ) -> None:
        tiles: List[np.ndarray] = []
        for candidate in candidates:
            tile = self._render_overlay_tile(candidate, label=label)
            if tile is not None:
                tiles.append(tile)
        if not tiles:
            return

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

        cv2.imwrite(str(out_path), canvas)

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
