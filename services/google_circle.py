import argparse
import cv2
import numpy as np

class CircleDetector:
    """
    A class to detect circles in monochromatic 8-bit PNG images,
    specifically designed for fluorescence microscopy images of droplets.
    """

    def __init__(self, image_path):
        """
        Initializes the CircleDetector with the path to the image.

        Args:
            image_path (str): The path to the input image file.
        """
        self.image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if self.image is None:
            raise ValueError("Image not found or could not be opened.")

    def detect_circles(self, blur_ksize=5, threshold_method='simple', threshold_value=127, adaptive_block_size=11, adaptive_c=2, hough_param1=50, hough_param2=30, min_dist=20, min_radius=10, max_radius=100, return_intermediate=False):
        """
        Detects circles in the image using a combination of Gaussian blur,
        a selected thresholding method, and the Hough Circle Transform.

        Args:
            blur_ksize (int): The kernel size for the Gaussian blur. Must be an odd number.
            threshold_method (str): The thresholding method to use ('simple', 'otsu', 'adaptive').
            threshold_value (int): The threshold value for 'simple' thresholding.
            adaptive_block_size (int): Block size for 'adaptive' thresholding. Must be an odd number.
            adaptive_c (int): Constant subtracted from the mean in 'adaptive' thresholding.
            hough_param1 (int): The first parameter for the Hough Circle Transform.
            hough_param2 (int): The second parameter for the Hough Circle Transform.
            min_dist (int): The minimum distance between the centers of detected circles.
            min_radius (int): The minimum radius of the circles to be detected.
            max_radius (int): The maximum radius of the circles to be detected.
            return_intermediate (bool): If True, returns intermediate processing images.

        Returns:
            A tuple containing:
            - A list of detected circles, where each circle is represented by (x, y, radius).
            - A dictionary of intermediate images if return_intermediate is True.
        """
        # Step 1: Apply Gaussian blur to reduce noise
        blurred_image = cv2.GaussianBlur(self.image, (blur_ksize, blur_ksize), 0)

        # Step 2: Apply the selected thresholding method
        if threshold_method == 'simple':
            _, thresholded_image = cv2.threshold(blurred_image, threshold_value, 255, cv2.THRESH_BINARY)
        elif threshold_method == 'otsu':
            # Otsu's method automatically calculates the threshold value
            _, thresholded_image = cv2.threshold(blurred_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif threshold_method == 'adaptive':
            thresholded_image = cv2.adaptiveThreshold(blurred_image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                      cv2.THRESH_BINARY, adaptive_block_size, adaptive_c)
        else:
            raise ValueError(f"Unknown threshold method: {threshold_method}")

        # Step 3: Detect circles using the Hough Circle Transform
        circles = cv2.HoughCircles(
            thresholded_image,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=min_dist,
            param1=hough_param1,
            param2=hough_param2,
            minRadius=min_radius,
            maxRadius=max_radius
        )

        detected_circles = []
        if circles is not None:
            detected_circles = np.uint16(np.around(circles[0, :])).tolist()

        if return_intermediate:
            intermediate_steps = {
                '1_Blurred': blurred_image,
                '2_Thresholded': thresholded_image
            }
            return detected_circles, intermediate_steps
        
        return detected_circles, {}

    def suggest_parameters(self):
        """
        Analyzes the image and suggests optimal parameters for circle detection.
        This is a basic implementation and may need further refinement.
        """
        # Suggest blur kernel size
        blur_ksize = 5

        # Suggest threshold value for 'simple' method using Otsu's as a starting point
        otsu_thresh_val, _ = cv2.threshold(self.image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return {
            "blur_ksize": blur_ksize,
            "threshold_value": int(otsu_thresh_val),
            "adaptive_block_size": 11,
            "adaptive_c": 2,
            "hough_param1": 50,
            "hough_param2": 30,
            "min_dist": 20,
            "min_radius": 10,
            "max_radius": 100,
        }

def main():
    """
    Command-line interface for the CircleDetector.
    """
    parser = argparse.ArgumentParser(description="Detect circles in an image using various thresholding methods.")
    parser.add_argument("image_path", help="Path to the input image file.")
    parser.add_argument("--suggest", action="store_true", help="Suggest optimal parameters for the image.")
    parser.add_argument("--visualize", action="store_true", help="Show image after each preprocessing step.")
    
    # Thresholding arguments
    parser.add_argument("--threshold_method", type=str, default='simple', choices=['simple', 'otsu', 'adaptive'], help="Thresholding method to use.")
    parser.add_argument("--threshold", type=int, default=127, help="Binary threshold value (for 'simple' method).")
    parser.add_argument("--adaptive_block_size", type=int, default=11, help="Block size for adaptive thresholding. Must be an odd number.")
    parser.add_argument("--adaptive_c", type=int, default=2, help="Constant subtracted from the mean for adaptive thresholding.")

    # Blur and Hough arguments
    parser.add_argument("--blur", type=int, default=5, help="Gaussian blur kernel size.")
    parser.add_argument("--param1", type=int, default=50, help="Hough transform param1.")
    parser.add_argument("--param2", type=int, default=30, help="Hough transform param2.")
    parser.add_argument("--min_dist", type=int, default=20, help="Minimum distance between circles.")
    parser.add_argument("--min_radius", type=int, default=10, help="Minimum circle radius.")
    parser.add_argument("--max_radius", type=int, default=100, help="Maximum circle radius.")
    
    parser.add_argument("--output", help="Path to save the output image with detected circles.")

    args = parser.parse_args()

    try:
        detector = CircleDetector(args.image_path)

        if args.suggest:
            suggested_params = detector.suggest_parameters()
            print("Suggested Parameters:")
            for key, value in suggested_params.items():
                print(f"  {key}: {value}")
            return

        circles, intermediate_steps = detector.detect_circles(
            blur_ksize=args.blur,
            threshold_method=args.threshold_method,
            threshold_value=args.threshold,
            adaptive_block_size=args.adaptive_block_size,
            adaptive_c=args.adaptive_c,
            hough_param1=args.param1,
            hough_param2=args.param2,
            min_dist=args.min_dist,
            min_radius=args.min_radius,
            max_radius=args.max_radius,
            return_intermediate=args.visualize
        )
        
        if args.visualize:
            print("Showing intermediate processing steps. Press any key in the image window to continue.")
            for name, image in sorted(intermediate_steps.items()):
                cv2.imshow(name, image)
                cv2.waitKey(0)

        print(f"Detected {len(circles)} circles:")
        for x, y, r in circles:
            print(f"  Center: ({x}, {y}), Radius: {r}")

        if args.output or args.visualize:
            output_image = cv2.cvtColor(detector.image, cv2.COLOR_GRAY2BGR)
            for x, y, r in circles:
                cv2.circle(output_image, (x, y), r, (0, 255, 0), 2)
                cv2.circle(output_image, (x, y), 2, (0, 0, 255), 3)

            if args.visualize:
                cv2.imshow('Final Result', output_image)
                print("Showing final result. Press any key to close all windows.")
                cv2.waitKey(0)

            if args.output:
                cv2.imwrite(args.output, output_image)
                print(f"Output image saved to {args.output}")

    except ValueError as e:
        print(f"Error: {e}")
    finally:
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
