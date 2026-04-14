import requests
import base64
import json
import statistics
from collections import defaultdict
from math import hypot
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        # Backward compatible: prefer current key, keep legacy fallback.
        self.image_directory = (
            self.app_config.get("image_file_directory")
            or self.app_config.get("local_file_path")
        )
        self.api_key = self.app_config.get("roboflow_api_key")
        self.inference_host = str(self.app_config.get("roboflow_inference_host", "http://localhost:9001")).rstrip("/")
        self.confidence_threshold = float(self.app_config.get("image_processing_confidence_threshold", 0.8))

        self.inference_mode = str(self.app_config.get("image_processing_mode", "workflow")).strip().lower()
        if self.inference_mode not in {"workflow", "model", "auto"}:
            raise ValueError(
                f"Invalid image_processing_mode='{self.inference_mode}'. "
                "Use one of: workflow, model, auto."
            )

        self.workflow_name = self.app_config.get("image_processing_workflow_name")
        self.model_id = self.app_config.get("image_processing_model_id")
        self.model_task = str(self.app_config.get("image_processing_task", "object_detection")).strip()
        self.model_confidence = self.app_config.get("image_processing_model_confidence")
        self.model_iou_threshold = self.app_config.get("image_processing_model_iou_threshold")

        if self.inference_mode == "auto":
            self.inference_mode = "model" if self.model_id else "workflow"

        if self.inference_mode == "workflow":
            if not self.workflow_name:
                raise ValueError("image_processing_workflow_name is required when image_processing_mode=workflow")
            self.url = f"{self.inference_host}/infer/workflows/{self.workflow_name}"
        else:
            if not self.model_id:
                # Small compatibility bridge: if user set phaseplotv2/5 in workflow field
                # while intending direct model inference.
                if self.workflow_name and self.workflow_name.count("/") == 1:
                    self.model_id = self.workflow_name
                else:
                    raise ValueError("image_processing_model_id is required when image_processing_mode=model")
            self.url = f"{self.inference_host}/infer/{self.model_task}"

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

    @staticmethod
    def _coerce_predictions(pred_list: Any) -> List[Dict]:
        if pred_list is None:
            return []
        if isinstance(pred_list, dict):
            pred_list = pred_list.get("predictions", [])
        if not isinstance(pred_list, list):
            return []

        parsed: List[Dict] = []
        for p in pred_list:
            if isinstance(p, dict):
                parsed.append(p)
            elif isinstance(p, str):
                try:
                    parsed_obj = json.loads(p.replace("'", '"'))
                    if isinstance(parsed_obj, dict):
                        parsed.append(parsed_obj)
                except json.JSONDecodeError:
                    continue
        return parsed

    @staticmethod
    def _decode_base64_image(image_obj: Any) -> Optional[bytes]:
        if not image_obj:
            return None
        if isinstance(image_obj, dict):
            b64_value = image_obj.get("value")
        elif isinstance(image_obj, str):
            b64_value = image_obj
        else:
            return None
        if not b64_value:
            return None
        try:
            return base64.b64decode(b64_value)
        except Exception:
            return None

    def _parse_inference_response(self, raw: str) -> Tuple[List[Dict], Optional[bytes]]:
        """Return ``(predictions, annotated_image_bytes)`` from workflow or model response."""
        # Some inference server responses may contain extra prefix text; be defensive.
        start_index = raw.find("{")
        if start_index == -1:
            return [], None
        data = json.loads(raw[start_index:])

        # Workflow route response shape:
        # {"outputs":[{"predictions":{"predictions":[...]}, "output_image":{"value":"..."}}]}
        if isinstance(data, dict) and "outputs" in data:
            outputs = data.get("outputs", [])
            output = outputs[0] if outputs else {}
            pred_block = output.get("predictions", {})
            parsed = self._coerce_predictions(pred_block)
            img_bytes = self._decode_base64_image(output.get("output_image")) or self._decode_base64_image(
                output.get("image")
            )
            return parsed, img_bytes

        # Direct model route response shape:
        # {"predictions":[...], "image":{"type":"base64","value":"..."}}
        if isinstance(data, dict):
            parsed = self._coerce_predictions(data.get("predictions", []))
            img_bytes = self._decode_base64_image(data.get("image"))
            return parsed, img_bytes

        return [], None

    def _infer_image(self, image_path: str):
        """Send *one* image to Roboflow and return predictions list (filtered by confidence)."""
        with open(image_path, "rb") as image_file:
            image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        if self.inference_mode == "workflow":
            payload = {
                "api_key": self.api_key,
                "inputs": {"image": {"type": "base64", "value": image_base64}},
            }
        else:
            payload = {
                "api_key": self.api_key,
                "model_id": self.model_id,
                "image": {"type": "base64", "value": image_base64},
            }
            if self.model_confidence is not None:
                payload["confidence"] = float(self.model_confidence)
            if self.model_iou_threshold is not None:
                payload["iou_threshold"] = float(self.model_iou_threshold)

        response = requests.post(self.url, json=payload, timeout=60)

        response.raise_for_status()
        preds, anno = self._parse_inference_response(response.text)

        preds = [p for p in preds if p.get("confidence", 0) > self.confidence_threshold]
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

    def analyze(self, result_run_id: int):
        """Analyze all images for *result_run_id* and persist droplet stats."""
        images = self.db.get_images_by_result_run_id(result_run_id)
        if not images:
            print(f"No images for run {result_run_id}")
            return

        base_image_dir = Path(self.image_directory or ".")

        # Group by (sample_id, site_number)
        site_groups = defaultdict(list)
        for img in images:
            site_groups[(img.sample_id, img.site_number)].append(img)

        for (sample_id, site_no), img_list in site_groups.items():
            # ------------------------------------------------------------------
            # 1) Cache predictions for every image **once**
            # ------------------------------------------------------------------
            prediction_cache = {}
            for img in img_list:
                try:
                    raw_path = str((base_image_dir / img.file_path).resolve())
                    preds, anno = self._infer_image(raw_path)
                except Exception as exc:
                    print(f"Roboflow fail on {img.file_path}: {exc}")
                    preds, anno = [], None
                prediction_cache[img.id] = preds
                if anno:
                    self._save_annotated_image(raw_path, anno)

            # ------------------------------------------------------------------
            # 2) Pick **one** best‑focus slice for the whole site to seed droplet centres
            # ------------------------------------------------------------------
            best_img = max(img_list, key=lambda im: im.focus_score or 0)
            w, h = best_img.dimension_x, best_img.dimension_y

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

            for img in img_list:
                img.average_droplet_size = avg_w
                img.standard_deviation_droplet_size = std_w
                self.db.update_image(img)

            print(f"Sample {sample_id} site {site_no}: n={len(widths)} avg={avg_w:.2f} stdev={std_w:.2f}")
