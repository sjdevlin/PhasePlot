#!/usr/bin/env python3

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Image
from services import AppConfig, DatabaseService

RESULT_RUN_ID = 86
TARGET_TEMPERATURE_C = 28.0
TEMPERATURE_TOLERANCE_C = 0.15
LED_CHANNELS = (5, 6)
STACK_GAP_SECONDS = 2.0
OUTPUT_DIR = Path("output/training")


def discover_default_config() -> str:
    for path in ("config.yaml", "config_mac.yaml", "config_20X.yaml", "config_40X.yaml"):
        if Path(path).exists():
            return path
    raise FileNotFoundError("No config file found.")


def resolve_image_path(file_path: str, image_directory: Optional[str]) -> Optional[Path]:
    raw = Path(file_path).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        if image_directory:
            candidates.append((Path(image_directory) / raw).expanduser())
        candidates.append((Path.cwd() / raw).expanduser())
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def to_uint8(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.dtype == np.uint8:
        return image
    image_f = image.astype(np.float32)
    lo, hi = np.percentile(image_f, (1.0, 99.0))
    if hi <= lo:
        lo, hi = float(np.min(image_f)), float(np.max(image_f))
    if hi <= lo:
        return np.zeros_like(image, dtype=np.uint8)
    image_f = np.clip((image_f - lo) / (hi - lo), 0.0, 1.0)
    return (image_f * 255.0).astype(np.uint8)


def sharpness_score(image_path: Path) -> float:
    arr = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if arr is None:
        return float("-inf")
    gray = to_uint8(arr)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def split_events(images: List[Image]) -> List[List[Image]]:
    if not images:
        return []
    images = sorted(
        images,
        key=lambda im: (
            im.timestamp if im.timestamp is not None else datetime.min,
            im.stack_number if im.stack_number is not None else -1,
            im.id,
        ),
    )
    events: List[List[Image]] = []
    current: List[Image] = []
    prev: Optional[Image] = None
    for image in images:
        new_event = False
        if prev is not None and prev.timestamp is not None and image.timestamp is not None:
            dt = abs((image.timestamp - prev.timestamp).total_seconds())
            if dt > STACK_GAP_SECONDS:
                new_event = True
        if new_event and current:
            events.append(current)
            current = []
        current.append(image)
        prev = image
    if current:
        events.append(current)
    return events


def main() -> int:
    config_path = discover_default_config()
    config = AppConfig(config_path)
    db = DatabaseService(config.get("sqlite_db"))
    image_directory = config.get("image_file_directory")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    copied_by_led = {int(ch): 0 for ch in LED_CHANNELS}
    any_images_found = False

    for led_channel in LED_CHANNELS:
        with db.Session() as session:
            images = (
                session.query(Image)
                .filter(
                    Image.result_run_id == RESULT_RUN_ID,
                    Image.led_number == int(led_channel),
                    func.abs(Image.temperature - TARGET_TEMPERATURE_C) <= TEMPERATURE_TOLERANCE_C,
                )
                .order_by(Image.sample_id, Image.site_number, Image.timestamp, Image.stack_number, Image.id)
                .all()
            )

        if not images:
            continue
        any_images_found = True

        by_site = {}
        for image in images:
            by_site.setdefault((int(image.sample_id), int(image.site_number)), []).append(image)

        for (sample_id, site_number), site_images in sorted(by_site.items()):
            events = split_events(site_images)
            for event_index, event_images in enumerate(events, start=1):
                scored_frames = []
                for image in event_images:
                    path = resolve_image_path(image.file_path, image_directory)
                    if path is None:
                        continue
                    score = sharpness_score(path)
                    scored_frames.append((image, path, score))

                if not scored_frames:
                    continue

                best_index = max(range(len(scored_frames)), key=lambda i: scored_frames[i][2])
                best_image, best_path, _best_score = scored_frames[best_index]

                out_name = (
                    f"run_{RESULT_RUN_ID}_temp_{TARGET_TEMPERATURE_C:.1f}_led_{int(led_channel)}_"
                    f"sample_{sample_id}_site_{site_number}_event_{event_index:02d}_"
                    f"stack_{int(best_image.stack_number if best_image.stack_number is not None else -1):03d}_"
                    f"{best_path.name}"
                )
                out_path = OUTPUT_DIR / out_name
                shutil.copy2(best_path, out_path)
                copied += 1
                copied_by_led[int(led_channel)] += 1

                # Also copy the 5th subsequent frame within this LED-only event, if present.
                plus5_index = best_index + 5
                if plus5_index < len(scored_frames):
                    _plus5_image, plus5_path, _plus5_score = scored_frames[plus5_index]
                    b_name = f"{out_path.stem}b{out_path.suffix}"
                    shutil.copy2(plus5_path, OUTPUT_DIR / b_name)
                    copied += 1
                    copied_by_led[int(led_channel)] += 1

    if not any_images_found:
        print("No matching images found.")
        return 1

    print(f"Copied {copied} sharpest images to {OUTPUT_DIR}")
    print(f"By LED channel: {copied_by_led}")
    return 0 if copied > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
