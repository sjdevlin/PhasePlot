
import cv2
import numpy as np
from skimage import filters, color
import argparse
import os

class CircleDetector:
    """
    A Python class for detecting complete, filled-in circles (bright on dark background)
    and drawing bounding rectangles around them using OpenCV and Scikit-image.
    """
    def __init__(self, image_path: str):
        """
        Initializes the CircleDetector with an image path.

        Args:
            image_path (str): Path to the input image file.
        """
        self.image_path = image_path
        self.original_image = None
        self.output_image = None # Image with drawn rectangles
        self._gray_blurred_image = None # Processed image for HoughCircles
        self._binary_image = None # Binary image from thresholding
        self.detected_circles_info = []# Stores {'center': (x,y), 'radius': r} for each circle
        self.load_image(image_path)

    def load_image(self, image_path: str):
        """
        Loads an image from the specified path. Converts to grayscale immediately.

        Args:
            image_path (str): Path to the image file.

        Raises:
            FileNotFoundError: If the image cannot be found or read.
        """
        self.image_path = image_path
        self.original_image = cv2.imread(self.image_path)
        if self.original_image is None:
            raise FileNotFoundError(f"Error: Image not found at {image_path}. Please check the path.")
        
        # Initialize output_image with a copy of the original for drawing
        self.output_image = self.original_image.copy()
        print(f"Image loaded: {image_path}")

    def preprocess_image(self, blur_sigma: float = 2.0):
        """
        Applies preprocessing steps: grayscale conversion, Gaussian blur, and Otsu's thresholding.

        Args:
            blur_sigma (float): Standard deviation for Gaussian kernel. Controls blur amount.
        
        Returns:
            np.ndarray: The binary image after thresholding (0 or 255).
        
        Raises:
            ValueError: If no image is loaded.
        """
        if self.original_image is None:
            raise ValueError("No image loaded. Call load_image() first.")
        
        # Convert to grayscale
        gray_image = cv2.cvtColor(self.original_image, cv2.COLOR_BGR2GRAY)
        print("Image converted to grayscale.")

        # Apply Gaussian blur for noise reduction
        # skimage.filters.gaussian works on float 
        blurred_image_float = filters.gaussian(gray_image / 255.0, sigma=blur_sigma)
        # Convert back to uint8 for OpenCV compatibility for HoughCircles param1/param2
        self._gray_blurred_image = (blurred_image_float * 255).astype(np.uint8)
        print(f"Image blurred with sigma={blur_sigma}.")

        # Apply Otsu's thresholding for bright objects on dark background
        # threshold_otsu works on float 
        thresh_val = filters.threshold_otsu(blurred_image_float)
        # Create binary mask: pixels > threshold become white (255), others black (0)
        self._binary_image = (blurred_image_float > thresh_val).astype(np.uint8) * 255
        print(f"Image thresholded using Otsu's method (threshold={thresh_val:.4f}).")
        
        return self._binary_image

    def detect_circles(self, min_radius: int, max_radius: int,
                       dp: float = 1.2, minDist_factor: float = 1.5, param1: int = 100, param2: int = 30):
        """
        Detects circles in the preprocessed image using Hough Circle Transform.

        Args:
            min_radius (int): Minimum circle radius in pixels.
            max_radius (int): Maximum circle radius in pixels.
            dp (float): Inverse ratio of the accumulator resolution to the image resolution.
                        1 means same resolution, 2 means half.
            minDist_factor (float): Factor to multiply min_radius by to set minDist.
                                    minDist = minDist_factor * min_radius.
            param1 (int): Upper threshold for the Canny edge detector.
            param2 (int): Accumulator threshold for circle centers. Lower value = more circles.
        
        Returns:
            list: A list of dictionaries, each containing 'center' (x,y) and 'radius' for detected circles.
        
        Raises:
            ValueError: If preprocessing has not been run.
        """
        if self._gray_blurred_image is None:
            raise ValueError("Image not preprocessed. Call preprocess_image() first.")

        # Ensure minRadius is at least 1 to avoid issues
        min_r = max(1, min_radius)
        
        # Calculate minDist based on min_r and minDist_factor
        min_dist = int(min_r * minDist_factor)
        
        print(f"Detecting circles with minRadius={min_r}, maxRadius={max_radius}, minDist={min_dist}")
        print(f"HoughCircles parameters: dp={dp}, param1={param1}, param2={param2}")

        # Apply HoughCircles
        circles = cv2.HoughCircles(
            self._gray_blurred_image, # Use the blurred grayscale image
            cv2.HOUGH_GRADIENT,
            dp=dp,                  
            minDist=min_dist,       
            param1=param1,          
            param2=param2,             
            minRadius=min_r,       
            maxRadius=max_radius        
        )

        self.detected_circles_info = []  # Initialize as empty list
        if circles is not None:
            # Convert circle coordinates and radii to integers
            circles = np.uint16(np.around(circles))
            for i in circles[0, :]:
                center = (i[0], i[1]) # Correctly extract x, y coordinates [3]
                radius = i[2]         # Correctly extract radius [3]
                self.detected_circles_info.append({'center': center, 'radius': radius})
                # print(f"Detected circle: Center={center}, Radius={radius}") # Uncomment for verbose output
            print(f"Detected {len(self.detected_circles_info)} circles.")
        else:
            print("No circles detected.")
        
        return self.detected_circles_info

    def draw_rectangles(self, rect_color=(0, 255, 0), rect_thickness: int = 2,
                        draw_circle_outline: bool = True, circle_color=(0, 0, 255), circle_thickness: int = 2,
                        draw_center_dot: bool = True, center_color=(255, 0, 0), center_radius: int = 2):
        """
        Draws bounding rectangles around the detected circles on the output image.
        Optionally draws circle outlines and center dots for visual verification.

        Args:
            rect_color (tuple): BGR color for the bounding rectangles.
            rect_thickness (int): Thickness of the rectangle lines.
            draw_circle_outline (bool): Whether to draw the detected circle outlines.
            circle_color (tuple): BGR color for the circle outlines.
            circle_thickness (int): Thickness of the circle outlines.
            draw_center_dot (bool): Whether to draw a dot at the circle center.
            center_color (tuple): BGR color for the center dot.
            center_radius (int): Radius of the center dot.
        """
        if self.original_image is None:
            raise ValueError("No image loaded. Call load_image() first.")
        print("1")
        # Create a fresh copy of the original image for drawing
        output_image_copy = self.original_image.copy()
        
        for circle_info in self.detected_circles_info:
            center = circle_info['center']
            radius = circle_info['radius']
            
            # Calculate bounding rectangle coordinates [5, 6]
            x, y = center
            x1 = int(x - radius)
            y1 = int(y - radius)
            x2 = int(x + radius)
            y2 = int(y + radius)
            
            # Ensure coordinates are within image bounds
            height, width = output_image_copy.shape[:2]
            print("2")
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(width, x2) # Corrected clamping [5, 6]
            y2 = min(height, y2) # Corrected clamping [5, 6]

            # Draw the rectangle [6]
            cv2.rectangle(output_image_copy, (x1, y1), (x2, y2), rect_color, rect_thickness)
            
            # Optionally, draw the circle outline and center for visual aid [3]
            if draw_circle_outline:
                cv2.circle(output_image_copy, center, radius, circle_color, circle_thickness)
            if draw_center_dot:
                cv2.circle(output_image_copy, center, center_radius, center_color, -1) # -1 for filled circle

        self.output_image = output_image_copy
        print(f"Drew bounding rectangles around {len(self.detected_circles_info)} circles.")

    def get_output_image(self) -> np.ndarray:
        """
        Returns the image with drawn rectangles.

        Returns:
            np.ndarray: The image with detected circles and bounding boxes.
        """
        if self.output_image is None:
            print("No output image available. Run detection and drawing steps first.")
            return self.original_image # Return original if no processing done
        return self.output_image

    def get_detected_circles_info(self) -> list:
        """
        Returns a list of detected circle properties.

        Returns:
            list: A list of dictionaries, each containing 'center' (x,y) and 'radius' for detected circles.
        """
        return self.detected_circles_info

    def save_output_image(self, output_filename: str):
        """
        Saves the processed image with drawn rectangles to a file.

        Args:
            output_filename (str): The path and filename to save the output image.
        """
        if self.output_image is None:
            raise ValueError("No output image to save. Run detection and drawing steps first.")
        
        cv2.imwrite(output_filename, self.output_image)
        print(f"Augmented image saved to: {output_filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detects circles in an image and draws bounding rectangles.")
    parser.add_argument("image_filename", type=str, help="Path to the input image file.")
    parser.add_argument("--minRadius", type=int, default=30, 
                        help="Minimum radius of circles to detect in pixels. (Default: 30)")
    parser.add_argument("--maxRadius", type=int, default=150, 
                        help="Maximum radius of circles to detect in pixels. (Default: 150)")
    parser.add_argument("--param2", type=int, default=25, 
                        help="Accumulator threshold for circle centers. Lower value detects more circles. (Default: 25)")
    parser.add_argument("--blur_sigma", type=float, default=1.5,
                        help="Standard deviation for Gaussian blur. Controls blur amount. (Default: 1.5)")
    parser.add_argument("--output_suffix", type=str, default="_augmented",
                        help="Suffix to add to the output image filename before extension. (Default: _augmented)")

    args = parser.parse_args()

    try:
        detector = CircleDetector(args.image_filename)
        
        # Step 1: Preprocess the image
        detector.preprocess_image(blur_sigma=args.blur_sigma)
        
        # Step 2: Detect circles using provided arguments
        detected_circles = detector.detect_circles(
            min_radius=args.minRadius, 
            max_radius=args.maxRadius, 
            param2=args.param2
        )
        
        # Step 3: Draw bounding rectangles
        detector.draw_rectangles()
        
        # Step 4: Save the result
        base_name, ext = os.path.splitext(args.image_filename)
        output_filename = f"{base_name}{args.output_suffix}{ext}"
        detector.save_output_image(output_filename)
        
        # Output the number of circles found
        print(f"\nTotal circles found: {len(detected_circles)}")

    except FileNotFoundError as e:
        print(e)
    except ValueError as e:
        print(f"Configuration Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")