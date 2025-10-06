import requests
import base64
import json
import statistics
from collections import defaultdict
from math import hypot
from pathlib import Path

# SQLAlchemy Image model for ORM updates
from models import Image


class ImageProcessor:
    """Process microscope image stacks, cache Roboflow predictions, and write
    droplet statistics back to the database.
    """

    def __init__(self, workflow_name: str, api_key: str, db_service, *, match_tolerance: int = 5):
        self.workflow_name = workflow_name
        self.api_key = api_key
        self.db = db_service
        self.url = f"http://localhost:9001/infer/workflows/{workflow_name}"
        self.match_tolerance = match_tolerance

    # ------------------------------------------------------------------
    # Low‑level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _distance(p1, p2):
        return hypot(p1[0] - p2[0], p1[1] - p2[1])

    @staticmethod
    def _is_touching_edge(pred: dict, img_w: int, img_h: int) -> bool:
        x, y, w, h = pred["x"], pred["y"], pred["width"], pred["height"]
        return (
            x - w / 2 <= 0 or y - h / 2 <= 0 or
            x + w / 2 >= img_w or y + h / 2 >= img_h
        )

    # ------------------------------------------------------------------
    # Roboflow interaction
    # ------------------------------------------------------------------

    def _parse_workflow_response(self, raw: str):
        """Return (predictions, annotated_bytes) from Roboflow raw text."""
        start = raw.find('{"outputs"')
        if start == -1:
            return [], None
        data = json.loads(raw[start:])
        output = data.get("outputs", [{}])[0]

        # Handle nested predictions dict
        pred_block = output.get("predictions", {})
        raw_preds = pred_block.get("predictions", [])
        parsed = []
        for p in raw_preds:
            if isinstance(p, str):
                try:
                    p = json.loads(p.replace("'", '"'))
                except json.JSONDecodeError:
                    continue
            parsed.append(p)

        img_b64 = output.get("output_image", {}).get("value")
        img_bytes = base64.b64decode(img_b64) if img_b64 else None
        return parsed, img_bytes

    def _infer_image(self, image_path: str):
        """Send one image to Roboflow, return (predictions, annotated_bytes)."""
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        payload = {
            "api_key": self.api_key,
            "inputs": {"image": {"type": "base64", "value": img_b64}}
        }
        resp = requests.post(self.url, json=payload, timeout=60)
        resp.raise_for_status()
        preds, anno = self._parse_workflow_response(resp.text)
        preds = [p for p in preds if p.get("confidence", 0) > 0.7]
        return preds, anno

    # ------------------------------------------------------------------
    # File utilities
    # ------------------------------------------------------------------

    def _save_annotated_image(self, raw_image_path: str, annotated_bytes: bytes, *, suffix: str = "_proc", ext: str = ".png") -> str:
        """Save annotated image alongside the raw image and return the new path."""
        p = Path(raw_image_path)
        out_path = p.with_name(f"{p.stem}{suffix}{ext}")
        with open(out_path, "wb") as f:
            f.write(annotated_bytes)
        return str(out_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, image_run_id: int):
        """Analyze all images for *image_run_id* and persist droplet stats."""
        images = self.db.get_images_by_image_run_id(image_run_id)
        if not images:
            print(f"No images for run {image_run_id}")
            return

        # Group by (sample_id, site_number)
        site_groups = defaultdict(list)
        for img in images:
            site_groups[(img.sample_id, img.image_site_number)].append(img)

        for (sample_id, site_no), img_list in site_groups.items():
            # ------------------------------------------------------------------
            # 1) Cache predictions for every image **once**
            # ------------------------------------------------------------------
            prediction_cache = {}
            for img in img_list:
                try:
                    preds, anno = self._infer_image(img.image_file_path)
                except Exception as exc:
                    print(f"Roboflow fail on {img.image_file_path}: {exc}")
                    preds, anno = [], None
                prediction_cache[img.id] = preds
                if anno:
                    self._save_annotated_image(img.image_file_path, anno)

            # ------------------------------------------------------------------
            # 2) Use best‑focus image per z‑stack to seed droplet centres
            # ------------------------------------------------------------------
            stack_groups = defaultdict(list)
            for img in img_list:
                stack_groups[img.image_stack_number].append(img)

            seed_droplets = []  # list[dict]: {x,y,max_width}
            for stack_imgs in stack_groups.values():
                best_img = max(stack_imgs, key=lambda im: im.image_focus_score or 0)
                w, h = best_img.image_dimension_x, best_img.image_dimension_y
                for p in prediction_cache[best_img.id]:
                    if self._is_touching_edge(p, w, h):
                        continue
                    seed_droplets.append({"x": p["x"], "y": p["y"], "max_width": p["width"]})

            # ------------------------------------------------------------------
            # 3) Scan entire site to update max width per droplet
            # ------------------------------------------------------------------
            for droplet in seed_droplets:
                for img in img_list:
                    for p in prediction_cache[img.id]:
                        if self._distance((droplet["x"], droplet["y"]), (p["x"], p["y"])) <= self.match_tolerance:
                            droplet["max_width"] = max(droplet["max_width"], p["width"])

            if not seed_droplets:
                print(f"No valid droplets for sample {sample_id} site {site_no}")
                continue

            widths = [d["max_width"] for d in seed_droplets]
            avg_w = statistics.mean(widths)
            std_w = statistics.pstdev(widths) if len(widths) > 1 else 0.0

            # ------------------------------------------------------------------
            # 4) Persist stats back into every image row for this site
            # ------------------------------------------------------------------
            with self.db.Session() as session:
                q = (
                    session.query(Image)
                    .filter(Image.image_run_id == image_run_id,
                            Image.sample_id == sample_id,
                            Image.image_site_number == site_no)
                )
                for db_img in q:
                    db_img.average_droplet_size = avg_w
                    db_img.standard_deviation_droplet_size = std_w
                session.commit()

            print(f"Sample {sample_id} site {site_no}: n={len(widths)} avg={avg_w:.2f} px  sd={std_w:.2f} px")
