#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Prevent Matplotlib/font cache writes in non-writable home directories.
os.environ.setdefault("MPLCONFIGDIR", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

from models import Image, ResultRun, Sample
from services import AppConfig, DatabaseService, PhaseDiagramAnalyzer


@dataclass
class SeedCandidate:
    x: float
    y: float
    radius: float
    confidence: float
    source: str


def _discover_default_config() -> str:
    candidates = [
        Path("config.yaml"),
        Path("config_mac.yaml"),
        Path("config_20X.yaml"),
        Path("config_40X.yaml"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "No config file found. Expected one of: config.yaml, config_mac.yaml, config_20X.yaml, config_40X.yaml."
    )


def _group_images_by_site_and_led(images: Sequence[Image]) -> Dict[int, Dict[int, List[Image]]]:
    grouped: Dict[int, Dict[int, List[Image]]] = {}
    for image in images:
        site_number = int(image.site_number)
        led_number = int(image.led_number)
        grouped.setdefault(site_number, {})
        grouped[site_number].setdefault(led_number, []).append(image)
    return grouped


def _normalize_to_uint8(gray_image: np.ndarray) -> np.ndarray:
    image_f = gray_image.astype(np.float32)
    lo, hi = np.percentile(image_f, (1.0, 99.0))
    if hi <= lo:
        lo = float(np.min(image_f))
        hi = float(np.max(image_f))
    if hi <= lo:
        return np.zeros_like(gray_image, dtype=np.uint8)
    scaled = (image_f - lo) / (hi - lo)
    scaled = np.clip(scaled, 0.0, 1.0)
    return (scaled * 255.0).astype(np.uint8)


def _compose_rgb(*, droplet_crop: np.ndarray, condensate_crop: np.ndarray) -> np.ndarray:
    green = _normalize_to_uint8(droplet_crop)
    red = _normalize_to_uint8(condensate_crop)
    if green.shape != red.shape:
        raise ValueError("Selected droplet and condensate crops have mismatched shapes.")
    blue = np.zeros_like(red, dtype=np.uint8)
    return np.stack([red, green, blue], axis=-1)


def _laplacian_sharpness(crop_uint8: np.ndarray) -> float:
    if crop_uint8.size == 0:
        return float("-inf")
    return float(cv2.Laplacian(crop_uint8, cv2.CV_64F).var())


def _edge_ring_strength(gray: np.ndarray, x: float, y: float, r: float) -> float:
    h, w = gray.shape[:2]
    if r < 4 or x < 2 or y < 2 or x >= w - 2 or y >= h - 2:
        return 0.0
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(grad_x, grad_y)

    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.hypot(xx - x, yy - y)
    ring = (rr >= 0.9 * r) & (rr <= 1.1 * r)
    if not np.any(ring):
        return 0.0
    vals = grad[ring]
    if vals.size < 12:
        return 0.0
    return float(np.percentile(vals, 90))


def _fallback_seed_detection(
    gray: np.ndarray,
    *,
    min_diameter_px: float,
    max_diameter_px: float,
    max_count: int,
) -> List[SeedCandidate]:
    blur = cv2.medianBlur(gray, 5)
    min_radius = max(4, int(round(min_diameter_px * 0.5)))
    max_radius = max(min_radius + 1, int(round(max_diameter_px * 0.5)))

    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(8, int(1.3 * min_radius)),
        param1=90,
        param2=16,
        minRadius=min_radius,
        maxRadius=max_radius,
    )

    if circles is None:
        return []

    h, w = gray.shape[:2]
    out: List[SeedCandidate] = []
    for c in np.round(circles[0, :]).astype(int):
        x, y, r = int(c[0]), int(c[1]), int(c[2])
        if x - r <= 1 or y - r <= 1 or x + r >= w - 1 or y + r >= h - 1:
            continue
        score = _edge_ring_strength(gray, float(x), float(y), float(r))
        out.append(
            SeedCandidate(
                x=float(x),
                y=float(y),
                radius=float(r),
                confidence=float(score),
                source="hough_fallback",
            )
        )

    if not out:
        return []
    max_score = max(s.confidence for s in out)
    if max_score > 0:
        out = [
            SeedCandidate(
                x=s.x,
                y=s.y,
                radius=s.radius,
                confidence=float(np.clip(s.confidence / max_score, 0.0, 1.0)),
                source=s.source,
            )
            for s in out
        ]
    out = sorted(out, key=lambda s: (s.confidence, s.radius), reverse=True)
    return out[:max_count]


def _select_seed_image_and_candidates(
    *,
    analyzer: PhaseDiagramAnalyzer,
    preferred_event: Sequence[Image],
    preferred_led: int,
) -> Tuple[Optional[Image], List[SeedCandidate], str, int, Optional[str]]:
    # Prefer deterministic fallback so stack processing remains reproducible
    # even when network inference is unavailable.
    best_image: Optional[Image] = None
    best_candidates: List[SeedCandidate] = []
    best_led = preferred_led
    best_sum = float("-inf")

    for image in preferred_event:
        image_path = analyzer._resolve_image_path(image.file_path)
        if image_path is None:
            continue
        arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            continue
        gray = analyzer._to_uint8(arr)
        h, w = gray.shape[:2]
        min_d = analyzer.min_droplet_width_fraction * w
        max_d = analyzer.max_droplet_width_fraction * w
        candidates = _fallback_seed_detection(
            gray,
            min_diameter_px=min_d,
            max_diameter_px=max_d,
            max_count=analyzer.max_droplets_per_site,
        )
        if not candidates:
            continue
        score_sum = float(sum(c.confidence for c in candidates))
        if score_sum > best_sum or (np.isclose(score_sum, best_sum) and len(candidates) > len(best_candidates)):
            best_sum = score_sum
            best_image = image
            best_candidates = candidates
            best_led = preferred_led

    if best_image is not None and best_candidates:
        return best_image, best_candidates, "hough_fallback", best_led, None

    # If fallback cannot find crops, try model-based detection as a backup.
    model_image, model_seeds, _model_gold, model_reason = analyzer._select_seed_image_and_crops(preferred_event)
    if model_image is not None and model_seeds:
        converted = [
            SeedCandidate(
                x=float(seed.x),
                y=float(seed.y),
                radius=float(seed.radius),
                confidence=float(seed.confidence),
                source=str(getattr(seed, "source", "model")),
            )
            for seed in model_seeds
        ]
        return model_image, converted, "model", preferred_led, None

    if best_image is None or not best_candidates:
        return (
            None,
            [],
            "none",
            preferred_led,
            (
                f"No seed droplets found in LED {preferred_led}. "
                f"Model reason: {model_reason or 'none'}."
            ),
        )

    return best_image, best_candidates, "hough_fallback", best_led, None


def _save_annotated_seed_image(
    *,
    analyzer: PhaseDiagramAnalyzer,
    seed_image: Image,
    crop_boxes: Sequence[Tuple[int, int, int, int]],
    seed_candidates: Sequence[SeedCandidate],
    out_path: Path,
) -> Optional[str]:
    image_path = analyzer._resolve_image_path(seed_image.file_path)
    if image_path is None:
        return None

    arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if arr is None:
        return None

    gray = analyzer._to_uint8(arr)
    canvas = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    for idx, (seed, box) in enumerate(zip(seed_candidates, crop_boxes), start=1):
        x0, y0, x1, y1 = box
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 255, 255), 2)
        cv2.circle(canvas, (int(round(seed.x)), int(round(seed.y))), int(round(seed.radius)), (0, 200, 0), 1)
        label = f"#{idx} conf={seed.confidence:.3f}"
        y_text = max(12, y0 - 6)
        cv2.putText(canvas, label, (x0, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, label, (x0, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), canvas):
        return None
    return str(out_path)


def _pick_best_stack_image_for_crop(
    *,
    analyzer: PhaseDiagramAnalyzer,
    image_gray_stack: Sequence[Tuple[Image, np.ndarray]],
    crop_box: Tuple[int, int, int, int],
) -> Tuple[Optional[np.ndarray], Optional[int], float, List[Dict[str, float]]]:
    x0, y0, x1, y1 = crop_box

    best_crop: Optional[np.ndarray] = None
    best_stack_number: Optional[int] = None
    best_fit_score = float("-inf")
    best_lap_score = float("-inf")
    have_fit = False
    stack_trace: List[Dict[str, float]] = []

    for image, gray in image_gray_stack:
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            continue

        measurement, _ = analyzer._measure_circle_centered(crop_gray=crop, max_diameter_px=None)
        fit_score = float(measurement["fit_score"]) if measurement is not None else float("-inf")
        lap_score = _laplacian_sharpness(crop)
        stack_no = int(image.stack_number if image.stack_number is not None else -1)

        stack_trace.append(
            {
                "stack_number": stack_no,
                "fit_score": None if not np.isfinite(fit_score) else fit_score,
                "laplacian_score": lap_score,
            }
        )

        if np.isfinite(fit_score):
            if (not have_fit) or (fit_score > best_fit_score) or (
                np.isclose(fit_score, best_fit_score) and lap_score > best_lap_score
            ):
                have_fit = True
                best_fit_score = fit_score
                best_lap_score = lap_score
                best_crop = crop.copy()
                best_stack_number = stack_no
        elif not have_fit and lap_score > best_lap_score:
            best_lap_score = lap_score
            best_crop = crop.copy()
            best_stack_number = stack_no

    final_score = best_fit_score if have_fit else best_lap_score
    return best_crop, best_stack_number, final_score, stack_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create RGB composite droplet/condensate crop images from z-stacks. "
            "LED5 (droplet) is written to green, LED6 (condensate) to red."
        )
    )
    parser.add_argument("result_run_id", type=int, help="Result run id")
    parser.add_argument("temperature", type=float, help="Target temperature in Celsius")
    parser.add_argument("sample_number", type=int, help="Sample id to process")
    parser.add_argument("output_dir", type=str, help="Directory to save composite PNG images")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (defaults to config.yaml/config_mac.yaml/config_20X.yaml/config_40X.yaml).",
    )
    parser.add_argument(
        "--temperature-tolerance",
        type=float,
        default=0.15,
        help="Allowed absolute temperature delta from target in Celsius (default: 0.15).",
    )
    parser.add_argument(
        "--max-crops",
        type=int,
        default=10,
        help="Maximum number of droplet crops to track per site (default: 10).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    config_path = args.config or _discover_default_config()
    config = AppConfig(config_path)
    db = DatabaseService(config.get("sqlite_db"))

    target_temperature = float(args.temperature)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    droplet_led = 5
    condensate_led = 6

    analyzer = PhaseDiagramAnalyzer(
        db_service=db,
        image_directory=config.get("image_file_directory"),
        output_directory=str(output_dir),
        temperature_tolerance=float(args.temperature_tolerance),
        max_droplets_per_site=int(args.max_crops),
        min_droplets_per_site=1,
        droplet_led_channel=droplet_led,
        condensate_led_channel=condensate_led,
    )

    with db.Session() as session:
        result_run = session.query(ResultRun).filter(ResultRun.id == int(args.result_run_id)).first()
        if result_run is None:
            print(f"Result run {args.result_run_id} not found.", file=sys.stderr)
            return 1

        experiment_id = int(result_run.experiment_id)

        images = (
            session.query(Image)
            .join(Sample, Sample.id == Image.sample_id)
            .filter(
                Sample.experiment_id == experiment_id,
                Image.result_run_id == int(args.result_run_id),
                Image.sample_id == int(args.sample_number),
                Image.led_number.in_([droplet_led, condensate_led]),
                func.abs(Image.temperature - target_temperature) <= float(args.temperature_tolerance),
            )
            .order_by(Image.site_number, Image.timestamp, Image.stack_number, Image.id)
            .all()
        )

    if not images:
        print(
            "No matching images found for the requested run/temperature/sample and LED channels 5/6.",
            file=sys.stderr,
        )
        return 1

    grouped = _group_images_by_site_and_led(images)
    total_written = 0
    summary_rows: List[Dict[str, object]] = []

    for site_number in sorted(grouped.keys()):
        by_led = grouped[site_number]
        droplet_images = by_led.get(droplet_led, [])
        condensate_images = by_led.get(condensate_led, [])
        if not droplet_images or not condensate_images:
            print(
                f"Skipping site {site_number}: missing LED {droplet_led} or LED {condensate_led} images.",
                flush=True,
            )
            continue

        droplet_events = analyzer._split_into_stack_events(droplet_images)
        condensate_events = analyzer._split_into_stack_events(condensate_images)
        if not droplet_events or not condensate_events:
            print(f"Skipping site {site_number}: no stack events after grouping.", flush=True)
            continue

        selected_droplet_event = min(
            droplet_events,
            key=lambda evt: (abs(analyzer._event_mean_temperature(evt) - target_temperature), -len(evt)),
        )
        selected_condensate_event = min(
            condensate_events,
            key=lambda evt: (
                abs(analyzer._event_mean_temperature(evt) - target_temperature),
                abs(
                    analyzer._event_mean_timestamp_seconds(evt)
                    - analyzer._event_mean_timestamp_seconds(selected_droplet_event)
                ),
                -len(evt),
            ),
        )

        selected_droplet_event = sorted(
            selected_droplet_event,
            key=lambda im: (im.stack_number if im.stack_number is not None else -1, im.id),
        )
        selected_condensate_event = sorted(
            selected_condensate_event,
            key=lambda im: (im.stack_number if im.stack_number is not None else -1, im.id),
        )

        seed_image, seed_candidates, seed_method, seed_led, failure_reason = _select_seed_image_and_candidates(
            analyzer=analyzer,
            preferred_event=selected_droplet_event,
            preferred_led=droplet_led,
        )
        if seed_image is None:
            print(f"Skipping site {site_number}: {failure_reason}", flush=True)
            continue

        seed_image_led = int(seed_image.led_number if seed_image.led_number is not None else -1)

        ref_path = analyzer._resolve_image_path(seed_image.file_path)
        if ref_path is None:
            print(f"Skipping site {site_number}: seed image path not found on disk.", flush=True)
            continue

        ref_arr = cv2.imread(str(ref_path), cv2.IMREAD_UNCHANGED)
        if ref_arr is None:
            print(f"Skipping site {site_number}: could not read seed image file.", flush=True)
            continue

        h, w = ref_arr.shape[:2]
        crop_boxes: List[Tuple[int, int, int, int]] = []
        valid_seed_candidates: List[SeedCandidate] = []
        for seed in seed_candidates:
            box = analyzer._make_crop_box(seed, width=w, height=h)
            if box is not None:
                crop_boxes.append(box)
                valid_seed_candidates.append(seed)

        if not crop_boxes:
            print(f"Skipping site {site_number}: no valid crop boxes generated.", flush=True)
            continue

        stem = (
            f"result_run_{int(args.result_run_id)}"
            f"_temp_{target_temperature:.2f}"
            f"_sample_{int(args.sample_number)}"
            f"_site_{int(site_number)}"
        )

        seed_annotation_path = output_dir / f"{stem}_seed_candidates.png"
        annotated_path = _save_annotated_seed_image(
            analyzer=analyzer,
            seed_image=seed_image,
            crop_boxes=crop_boxes,
            seed_candidates=valid_seed_candidates,
            out_path=seed_annotation_path,
        )

        print(
            f"Processing site {site_number}: {len(crop_boxes)} crop(s), "
            f"seed method={seed_method}, seed LED={seed_led}, seed stack={seed_image.stack_number}, "
            f"seed file={seed_image.file_path}",
            flush=True,
        )

        droplet_gray_stack: List[Tuple[Image, np.ndarray]] = []
        for image in selected_droplet_event:
            path = analyzer._resolve_image_path(image.file_path)
            if path is None:
                continue
            arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if arr is None:
                continue
            droplet_gray_stack.append((image, analyzer._to_uint8(arr)))

        condensate_gray_stack: List[Tuple[Image, np.ndarray]] = []
        for image in selected_condensate_event:
            path = analyzer._resolve_image_path(image.file_path)
            if path is None:
                continue
            arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if arr is None:
                continue
            condensate_gray_stack.append((image, analyzer._to_uint8(arr)))

        if not droplet_gray_stack or not condensate_gray_stack:
            print(f"Skipping site {site_number}: unreadable stack images.", flush=True)
            continue

        for crop_index, (seed, crop_box) in enumerate(zip(valid_seed_candidates, crop_boxes), start=1):
            best_droplet_crop, best_droplet_stack, best_droplet_score, droplet_trace = _pick_best_stack_image_for_crop(
                analyzer=analyzer,
                image_gray_stack=droplet_gray_stack,
                crop_box=crop_box,
            )
            best_condensate_crop, best_condensate_stack, best_condensate_score, condensate_trace = _pick_best_stack_image_for_crop(
                analyzer=analyzer,
                image_gray_stack=condensate_gray_stack,
                crop_box=crop_box,
            )

            if best_droplet_crop is None or best_condensate_crop is None:
                print(
                    f"  Site {site_number} crop {crop_index}: skipped (missing best crop in one channel).",
                    flush=True,
                )
                continue

            composite_rgb = _compose_rgb(
                droplet_crop=best_droplet_crop,
                condensate_crop=best_condensate_crop,
            )

            output_path = output_dir / f"{stem}_crop_{crop_index:02d}.png"
            saved = cv2.imwrite(str(output_path), cv2.cvtColor(composite_rgb, cv2.COLOR_RGB2BGR))
            if not saved:
                print(f"  Site {site_number} crop {crop_index}: failed to save {output_path}", flush=True)
                continue

            total_written += 1
            x0, y0, x1, y1 = crop_box
            summary_rows.append(
                {
                    "result_run_id": int(args.result_run_id),
                    "temperature_c": target_temperature,
                    "sample_number": int(args.sample_number),
                    "site_number": int(site_number),
                    "crop_index": int(crop_index),
                    "file_path": str(output_path),
                    "crop_box": [int(x0), int(y0), int(x1), int(y1)],
                    "seed_image_file": str(seed_image.file_path),
                    "seed_image_led_number": seed_image_led,
                    "seed_image_stack_number": int(seed_image.stack_number if seed_image.stack_number is not None else -1),
                    "seed_selection_method": seed_method,
                    "seed_led": int(seed_led),
                    "seed_confidence": float(seed.confidence),
                    "seed_source": seed.source,
                    "seed_annotation_path": annotated_path,
                    "droplet_led_number": int(droplet_led),
                    "condensate_led_number": int(condensate_led),
                    "droplet_best_stack_number": best_droplet_stack,
                    "droplet_sharpness_score": best_droplet_score,
                    "condensate_best_stack_number": best_condensate_stack,
                    "condensate_sharpness_score": best_condensate_score,
                    "droplet_stack_scores": droplet_trace,
                    "condensate_stack_scores": condensate_trace,
                }
            )
            print(
                f"  Site {site_number} crop {crop_index}: saved {output_path.name} "
                f"(droplet LED{droplet_led} stack {best_droplet_stack}, "
                f"condensate LED{condensate_led} stack {best_condensate_stack})",
                flush=True,
            )

    summary_path = output_dir / (
        f"result_run_{int(args.result_run_id)}"
        f"_temp_{target_temperature:.2f}"
        f"_sample_{int(args.sample_number)}"
        "_composite_summary.json"
    )
    summary_path.write_text(json.dumps(summary_rows, indent=2))

    print(f"Wrote {total_written} composite image(s).", flush=True)
    print(f"Summary: {summary_path}", flush=True)

    if total_written == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
