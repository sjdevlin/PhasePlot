import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple


class CircleDetector:
    """Detect (nearly) perfect bubbles in monochromatic micrographs.

    The detector supports *aggressive* contrast‑boosting presets—handy for
    dim, low‑contrast bubble micrographs—before handing the image to OpenCV’s
    Hough‑circle transform.  Optionally saves an annotated PNG with bright
    green bounding boxes so you can visually sanity‑check the detections.
    """

    # ------------------------------------------------------------------
    # Construction & tunables
    # ------------------------------------------------------------------
    def __init__(
        self,
        # --- pre‑processing ------------------------------------------------
        contrast_method: str = "clahe",  # "clahe", "gamma", "hist_eq", "stretch", "none"
        gamma: float = 1.8,
        clahe_clip_limit: float = 2.0,
        clahe_tile_grid_size: Tuple[int, int] = (8, 8),
        stretch_low_pct: float = 2.0,
        stretch_high_pct: float = 98.0,
        blur_kernel_size: int = 9,
        # --- Hough transform ----------------------------------------------
        canny_threshold1: int = 50,
        canny_threshold2: int = 150,
        hough_dp: float = 1.2,
        hough_min_dist: int = 60,  # Increased from 50 - prevents nearby circles
        hough_param1: int = 85,    # Increased from 50 - higher edge threshold
        hough_param2: int = 45,     # Increased from 30 - higher accumulator threshold
        min_radius: int = 30,       # Increased from 10 - ignore very small circles
        max_radius: int = 300,      # Set a reasonable max instead of 0 (unlimited)
    ) -> None:
        self.contrast_method = contrast_method.lower()
        self.gamma = gamma
        self.clahe_clip_limit = clahe_clip_limit
        self.clahe_tile_grid_size = clahe_tile_grid_size
        self.stretch_low_pct = stretch_low_pct
        self.stretch_high_pct = stretch_high_pct

        self.blur_kernel_size = blur_kernel_size
        self.canny_threshold1 = canny_threshold1
        self.canny_threshold2 = canny_threshold2
        self.hough_dp = hough_dp
        self.hough_min_dist = hough_min_dist
        self.hough_param1 = hough_param1
        self.hough_param2 = hough_param2
        self.min_radius = min_radius
        self.max_radius = max_radius

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _enhance_contrast(self, gray: np.ndarray) -> np.ndarray:
        """Apply the requested global or local contrast expansion."""
        if self.contrast_method == "none":
            return gray

        if self.contrast_method == "gamma":
            inv_gamma = 1.0 / self.gamma
            table = (np.linspace(0, 1, 256) ** inv_gamma * 255).astype(np.uint8)
            return cv2.LUT(gray, table)

        if self.contrast_method == "hist_eq":
            return cv2.equalizeHist(gray)

        if self.contrast_method == "stretch":
            p_low, p_high = np.percentile(gray, [self.stretch_low_pct, self.stretch_high_pct])
            scale = 255.0 / max(p_high - p_low, 1)
            stretched = np.clip((gray.astype(np.float32) - p_low) * scale, 0, 255)
            return stretched.astype(np.uint8)

        # default / "clahe"
        clahe = cv2.createCLAHE(
            clipLimit=self.clahe_clip_limit, tileGridSize=self.clahe_tile_grid_size
        )
        return clahe.apply(gray)

    @staticmethod
    def _is_complete_circle(
        x: int, y: int, r: int, width: int, height: int
    ) -> bool:
        return (
            x - r >= 0 and y - r >= 0 and x + r < width and y + r < height
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process(self, image_file_path: str, augment: bool = False) -> List[float]:
        """Detect complete bubbles and optionally save an annotated PNG.

        Parameters
        ----------
        image_file_path : str
            Path to a 3208×2200 (approx.) monochromatic TIFF micrograph.
        augment : bool, default=False
            If *True*, draw bright‑green bounding boxes around *complete*
            circles and save the result alongside the original.

        Returns
        -------
        List[float]
            Diameters (in pixels) of every complete circle discovered.
        """
        img_path = Path(image_file_path)
        if not img_path.exists():
            raise FileNotFoundError(img_path)

        gray = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError("Failed to load image or wrong path/format")

        # --------------------------------------------------------------
        # 1. Contrast expansion (gamma / CLAHE / …)
        # --------------------------------------------------------------
        gray = self._enhance_contrast(gray)

        # --------------------------------------------------------------
        # 2. De‑noise / smooth (Gaussian blur)
        # --------------------------------------------------------------
        gray_blurred = cv2.GaussianBlur(gray, (self.blur_kernel_size, self.blur_kernel_size), 0)

        # --------------------------------------------------------------
        # 3. Circle detection (Hough GRADIENT)
        # --------------------------------------------------------------
        circles = cv2.HoughCircles(
            gray_blurred,
            cv2.HOUGH_GRADIENT,
            dp=self.hough_dp,
            minDist=self.hough_min_dist,
            param1=self.hough_param1,
            param2=self.hough_param2,
            minRadius=self.min_radius,
            maxRadius=self.max_radius,
        )

        diameters: List[float] = []
        bgr = None
        if circles is not None:
            circles = np.uint16(np.around(circles[0]))
            h, w = gray.shape
            for x, y, r in circles:
                if self._is_complete_circle(x, y, r, w, h):
                    diameters.append(float(2 * r))
                    if augment:
                        if bgr is None:
                            bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
                        cv2.rectangle(
                            bgr,
                            (x - r, y - r),
                            (x + r, y + r),
                            (0, 255, 0),
                            2,
                        )

        # --------------------------------------------------------------
        # 4. Optional save‑out
        # --------------------------------------------------------------
        if augment and diameters:
            if bgr is None:  # safety
                bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            out_path = img_path.with_name(f"{img_path.stem}_annotated.png")
            cv2.imwrite(str(out_path), bgr)

        return diameters


if __name__ == "__main__":
    import argparse, sys

    p = argparse.ArgumentParser(description="Bubble micrograph circle finder")
    p.add_argument("image", help="Path to TIFF micrograph")
    p.add_argument("--augment", action="store_true", help="Save annotated PNG")
    p.add_argument("--contrast", default="clahe", choices=["clahe", "gamma", "hist_eq", "stretch", "none"], help="Contrast method")
    p.add_argument("--gamma", type=float, default=1.8, help="Gamma for gamma correction (>1 brightens)")
    args = p.parse_args()

    detector = CircleDetector(contrast_method=args.contrast, gamma=args.gamma)
    try:
        diams = detector.process(args.image, augment=args.augment)
        print("Diameters (px):", diams if diams else "No complete circles found")
    except Exception as e:
        print (f"Error: {e}", file=sys.stderr)
        sys.exit(str(e))
