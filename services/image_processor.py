import requests
import base64
import json
import statistics
from collections import defaultdict
from math import hypot
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

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
        self.high_confidence_threshold = float(
            self.app_config.get("image_processing_high_confidence_threshold", 0.9)
        )
        self.focus_selection_mode = str(
            self.app_config.get("image_processing_focus_selection_mode", "droplet_aware")
        ).strip().lower()
        self.focus_weight_edge = float(self.app_config.get("image_processing_focus_weight_edge", 0.55))
        self.focus_weight_count = float(self.app_config.get("image_processing_focus_weight_count", 0.20))
        self.focus_weight_conf = float(self.app_config.get("image_processing_focus_weight_conf", 0.20))
        self.focus_weight_global = float(self.app_config.get("image_processing_focus_weight_global", 0.05))
        self.focus_debug = bool(self.app_config.get("image_processing_focus_debug", False))

        self.workflow_name = self.app_config.get("image_processing_workflow_name")
        if not self.workflow_name:
            raise ValueError("image_processing_workflow_name is required")
        self.url = f"{self.inference_host}/infer/workflows/{self.workflow_name}"

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

    @staticmethod
    def _normalize_series(values: List[float]) -> List[float]:
        if not values:
            return []
        vmin = min(values)
        vmax = max(values)
        if vmax <= vmin:
            return [0.0 for _ in values]
        return [(v - vmin) / (vmax - vmin) for v in values]

    @staticmethod
    def _to_gray_uint8(arr: np.ndarray) -> np.ndarray:
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

    def _resolve_raw_path(self, base_image_dir: Path, db_file_path: str) -> Path:
        return (base_image_dir / db_file_path).resolve()

    def _droplet_edge_sharpness(self, gray: np.ndarray, pred: dict) -> float:
        h, w = gray.shape[:2]
        cx = float(pred.get("x", 0.0))
        cy = float(pred.get("y", 0.0))
        bw = float(pred.get("width", 0.0))
        bh = float(pred.get("height", 0.0))
        if bw < 6 or bh < 6:
            return 0.0

        x0 = max(0, int(cx - bw * 0.7))
        x1 = min(w, int(cx + bw * 0.7))
        y0 = max(0, int(cy - bh * 0.7))
        y1 = min(h, int(cy + bh * 0.7))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return 0.0

        roi = gray[y0:y1, x0:x1]
        roi_h, roi_w = roi.shape[:2]
        yy, xx = np.mgrid[0:roi_h, 0:roi_w]

        ecx = (cx - x0)
        ecy = (cy - y0)
        rx = max(1.0, bw * 0.5)
        ry = max(1.0, bh * 0.5)
        ellipse_r = np.sqrt(((xx - ecx) / rx) ** 2 + ((yy - ecy) / ry) ** 2)

        inner_mask = (ellipse_r >= 0.65) & (ellipse_r <= 0.85)
        edge_mask = (ellipse_r >= 0.90) & (ellipse_r <= 1.10)
        outer_mask = (ellipse_r >= 1.15) & (ellipse_r <= 1.35)
        if not np.any(edge_mask) or not np.any(inner_mask) or not np.any(outer_mask):
            return 0.0

        roi_f = roi.astype(np.float32)
        inner_mean = float(np.mean(roi_f[inner_mask]))
        outer_mean = float(np.mean(roi_f[outer_mask]))
        edge_contrast = abs(inner_mean - outer_mean)

        grad_x = cv2.Sobel(roi_f, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(roi_f, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = np.hypot(grad_x, grad_y)

        edge_vals = grad_mag[edge_mask]
        bg_vals = grad_mag[inner_mask | outer_mask]
        if edge_vals.size < 10 or bg_vals.size < 10:
            return 0.0

        edge_strength = float(np.percentile(edge_vals, 85))
        bg_strength = float(np.percentile(bg_vals, 85))
        boundary_specific_strength = max(0.0, edge_strength - bg_strength)

        # Weight gradient dominance more heavily than brightness contrast.
        return boundary_specific_strength + 0.5 * edge_contrast

    def _compute_image_focus_metrics(
        self,
        img: Image,
        preds: List[Dict],
        raw_path: Path,
    ) -> Dict[str, float]:
        high_conf_preds = [p for p in preds if float(p.get("confidence", 0.0)) >= self.high_confidence_threshold]
        chosen_preds = high_conf_preds if high_conf_preds else preds

        conf_sum = float(sum(float(p.get("confidence", 0.0)) for p in chosen_preds))
        high_conf_count = float(len(high_conf_preds))
        pred_count = float(len(preds))
        global_focus = float(img.focus_score or 0.0)

        edge_sharpness = 0.0
        try:
            arr = cv2.imread(str(raw_path), cv2.IMREAD_UNCHANGED)
            if arr is not None and chosen_preds:
                gray = self._to_gray_uint8(arr)
                valid_scores = []
                img_h, img_w = gray.shape[:2]
                for p in chosen_preds:
                    if self._is_touching_edge(p, img_w, img_h):
                        continue
                    valid_scores.append(self._droplet_edge_sharpness(gray, p))
                if valid_scores:
                    edge_sharpness = float(np.mean(valid_scores))
        except Exception:
            edge_sharpness = 0.0

        return {
            "high_conf_count": high_conf_count,
            "pred_count": pred_count,
            "conf_sum": conf_sum,
            "edge_sharpness": edge_sharpness,
            "global_focus": global_focus,
        }

    def _select_best_focus_image(
        self,
        img_list: List[Image],
        prediction_cache: Dict[int, List[Dict]],
        base_image_dir: Path,
    ) -> Image:
        if not img_list:
            raise ValueError("Cannot select focus image from empty image list.")

        if self.focus_selection_mode != "droplet_aware":
            return max(img_list, key=lambda im: im.focus_score or 0)

        metrics_per_image: List[Tuple[Image, Dict[str, float]]] = []
        for img in img_list:
            preds = prediction_cache.get(img.id, [])
            raw_path = self._resolve_raw_path(base_image_dir, img.file_path)
            metrics = self._compute_image_focus_metrics(img, preds, raw_path)
            metrics_per_image.append((img, metrics))

        edge_series = self._normalize_series([m["edge_sharpness"] for _, m in metrics_per_image])
        count_series = self._normalize_series([m["high_conf_count"] for _, m in metrics_per_image])
        conf_series = self._normalize_series([m["conf_sum"] for _, m in metrics_per_image])
        global_series = self._normalize_series([m["global_focus"] for _, m in metrics_per_image])

        best_idx = 0
        best_score = float("-inf")
        combined_scores: List[float] = []
        for idx, (img, metrics) in enumerate(metrics_per_image):
            combined = (
                self.focus_weight_edge * edge_series[idx]
                + self.focus_weight_count * count_series[idx]
                + self.focus_weight_conf * conf_series[idx]
                + self.focus_weight_global * global_series[idx]
            )
            combined_scores.append(combined)
            # Hard tie-break: higher high-confidence count then global focus.
            tie_break = (metrics["high_conf_count"], metrics["global_focus"])
            if combined > best_score:
                best_score = combined
                best_idx = idx
            elif combined == best_score:
                prev_metrics = metrics_per_image[best_idx][1]
                if tie_break > (prev_metrics["high_conf_count"], prev_metrics["global_focus"]):
                    best_idx = idx

        if self.focus_debug:
            for idx, (img, metrics) in enumerate(metrics_per_image):
                print(
                    "focus_rank "
                    f"img_id={img.id} stack={getattr(img, 'stack_number', None)} "
                    f"score={combined_scores[idx]:.4f} "
                    f"edge={metrics['edge_sharpness']:.2f} "
                    f"high_conf={metrics['high_conf_count']:.0f} "
                    f"conf_sum={metrics['conf_sum']:.2f} "
                    f"global={metrics['global_focus']:.2f}"
                )
            chosen = metrics_per_image[best_idx][0]
            print(
                "focus_selected "
                f"img_id={chosen.id} stack={getattr(chosen, 'stack_number', None)} "
                f"score={best_score:.4f}"
            )

        return metrics_per_image[best_idx][0]

    def _image_dimensions(self, img: Image, base_image_dir: Path) -> Tuple[int, int]:
        if (img.dimension_x or 0) > 0 and (img.dimension_y or 0) > 0:
            return int(img.dimension_x), int(img.dimension_y)
        try:
            raw_path = self._resolve_raw_path(base_image_dir, img.file_path)
            arr = cv2.imread(str(raw_path), cv2.IMREAD_UNCHANGED)
            if arr is not None:
                h, w = arr.shape[:2]
                return int(w), int(h)
        except Exception:
            pass
        return 0, 0



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

        return [], None

    def _infer_image(self, image_path: str):
        """Send *one* image to Roboflow and return predictions list (filtered by confidence)."""
        with open(image_path, "rb") as image_file:
            image_base64 = base64.b64encode(image_file.read()).decode('utf-8')

        payload = {
            "api_key": self.api_key,
            "inputs": {"image": {"type": "base64", "value": image_base64}},
        }

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
                    raw_path = str(self._resolve_raw_path(base_image_dir, img.file_path))
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
            best_img = self._select_best_focus_image(img_list, prediction_cache, base_image_dir)
            w, h = self._image_dimensions(best_img, base_image_dir)

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
