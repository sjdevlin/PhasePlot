import requests
import base64
import json
import statistics
from collections import defaultdict
from math import hypot
from pathlib import Path

# SQLAlchemy Image model is imported for type hinting / ORM updates
from models import Image
from services import AppConfig


class ImageProcessor:
    """Analyze microscope images for droplet statistics using a Roboflow workflow.

    Parameters
    ----------
    workflow_name : str
        The deployed Roboflow workflow identifier (e.g. ``"test-validation-set/detect-count-and-visualize-3``).
    api_key : str
        Roboflow API key.
    db_service : DatabaseService
        Instance of the application's DatabaseService (wraps SQLAlchemy sessions).
    match_tolerance : int, optional
        Pixel distance allowed when matching the same droplet across z–stack slices.
    """

    def __init__(self, db_service, match_tolerance: int = 5):
        self.db = db_service
        self.match_tolerance = match_tolerance
        self.app_config = AppConfig()
        self.image_directory = self.app_config.get("local_file_path")
        self.api_key = self.app_config.get("roboflow_api_key")

        workflow_name = self.app_config.get("image_processing_workflow_name") #TODO: need consistency on when to pass parameters and when to use app_config
        self.url = f"http://localhost:9001/infer/workflows/{workflow_name}"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _distance(self, p1, p2):
        return hypot(p1[0] - p2[0], p1[1] - p2[1])

    def _is_touching_edge(self, pred: dict, img_w: int, img_h: int) -> bool:
        x, y, w, h = pred["x"], pred["y"], pred["width"], pred["height"]
        return (
            x - w / 2 <= 0 or y - h / 2 <= 0 or
            x + w / 2 >= img_w or y + h / 2 >= img_h
        )



    # ------------------------------------------------------------------
    # Roboflow interaction
    # ------------------------------------------------------------------

    def _parse_workflow_response(self, raw: str):
        """Return ``(predictions, annotated_image_bytes)`` from raw response text."""
        # Find the start of the JSON object
        # This is a workaround for the Roboflow server response which may contain extra text before the JSON
        start_index = raw.find('{"outputs"')
        if start_index == -1:
            return [], None
 
        data       = json.loads(raw[start_index:])          # already OK
        output     = data.get("outputs", [{}])[0]           # first output item

        pred_block = output.get("predictions", {})          # <-- dict, **not** list
        pred_list  = pred_block.get("predictions", [])      # <-- the real list

        parsed = []
        for p in pred_list:
            parsed.append(p)                                # now p is the dict you expect


        img_b64 = output.get("output_image", {}).get("value")
        img_bytes = base64.b64decode(img_b64) if img_b64 else None
        return parsed, img_bytes

    def _infer_image(self, image_path: str):
        """Send *one* image to Roboflow and return predictions list (filtered by confidence)."""
        with open(image_path, "rb") as image_file:
            image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        payload = {
            "api_key": self.api_key,
            "inputs": {"image": {"type": "base64", "value": image_base64}}
        }

        response = requests.post(self.url, json=payload, timeout=60)

        response.raise_for_status()
        preds, anno = self._parse_workflow_response(response.text)

        preds = [p for p in preds if p.get("confidence", 0) > 0.8]
        return preds, anno

    # ------------------------------------------------------------------
    # File utilities
    # ------------------------------------------------------------------

    def _save_annotated_image(self, raw_image_path: str, annotated_bytes: bytes, *, suffix: str = "_proc", ext: str = ".png") -> str:
        """Save annotated image alongside *raw_image_path* or in *self.image_directory*.
        If ``self.image_directory`` is set (e.g. ``Path`` or ``str``), the image
        is saved there.  Otherwise it is saved next to the raw file.
        The new filename is ``<stem><suffix><ext>``.
        """

        p = Path(raw_image_path)
        target_dir = Path(getattr(self, "image_directory", p.parent))
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / f"{p.stem}{suffix}{ext}"
        with open(out_path, "wb") as fh:
            fh.write(annotated_bytes)
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
                    preds, anno = self._infer_image(f"{self.image_directory}{img.image_file_path}")
                except Exception as exc:
                    print(f"Roboflow fail on {img.image_file_path}: {exc}")
                    preds, anno = [], None
                prediction_cache[img.id] = preds
                if anno:
                    self._save_annotated_image(img.image_file_path, anno)

            # ------------------------------------------------------------------
            # 2) Pick **one** best‑focus slice for the whole site to seed droplet centres
            # ------------------------------------------------------------------
            best_img = max(img_list, key=lambda im: im.image_focus_score or 0)
            w, h = best_img.image_dimension_x, best_img.image_dimension_y

            seed_droplets = []  # list[dict]: {x,y,max_width}
            for p in prediction_cache[best_img.id]:
                if self._is_touching_edge(p, w, h):
                    continue
                seed_droplets.append({"x": p["x"], "y": p["y"], "max_width": p["width"]})

            # ------------------------------------------------------------------
            # 3) Scan entire site to update max width per droplet
            # ------------------------------------------------------------------ Scan entire site to update max width per droplet
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


            img.average_droplet_size = avg_w
            img.standard_deviation_droplet_size = std_w
            # Persist results back to DB

            self.db.update_image(img)

            print(f"Sample {sample_id} site {site_no}: n={len(widths)} avg={avg_w:.2f} stdev={std_w:.2f}")
