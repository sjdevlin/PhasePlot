import cv2
import math
import numpy as np
import argparse

class CircleDetector:
    def __init__(self, minArea, minCircularity, minInertiaRatio, minConvexity):
        # Store parameters for display purposes
        self._min_area = minArea
        self._min_circularity = minCircularity
        self._min_inertia = minInertiaRatio
        self._min_convexity = minConvexity
        
        # Initialize SimpleBlobDetector with given parameters
        params = cv2.SimpleBlobDetector_Params()
        # Filter by area (size)
        params.filterByArea = True
        params.minArea = minArea
        params.maxArea = 50000  # Reasonable upper bound for large circles (was 1e9 which might cause issues)
        # Filter by circularity (roundness)
        params.filterByCircularity = True
        params.minCircularity = minCircularity
        # Filter by convexity (shape must be largely convex)
        params.filterByConvexity = True
        params.minConvexity = minConvexity
        # Filter by inertia (not too elongated)
        params.filterByInertia = True
        params.minInertiaRatio = minInertiaRatio
        # Filter by color (look for bright (white) blobs on dark background)
        params.filterByColor = True
        params.blobColor = 255
        # Set threshold range for internal blob detection
        params.minThreshold = 10
        params.maxThreshold = 255
        params.thresholdStep = 10
        # Create the detector with the parameters
        self.detector = cv2.SimpleBlobDetector_create(params)
    
    def detect_and_draw(self, image_path, output_path=None, show=False, block_size=21, constant_c=2, force_invert=False, no_auto_invert=False, threshold_method="adaptive", detection_method="blob", hough_param1=100, hough_param2=50, max_circles=100):
        # Load the image
        image = cv2.imread(image_path)
        if image is None:
            raise FileNotFoundError(f"Input image '{image_path}' not found.")
        
        # Helper function to display image with processing info
        def show_processing_step(img, step_name, parameters="", wait_for_key=True):
            if not show:
                return
            
            # Create display image (convert grayscale to BGR if needed for text overlay)
            if len(img.shape) == 2:
                display_img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                display_img = img.copy()
            
            # Add title text
            cv2.putText(display_img, f"Step: {step_name}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            
            # Add parameters text if provided
            if parameters:
                # Split long parameter strings into multiple lines
                param_lines = parameters.split(', ')
                y_offset = 60
                for i, line in enumerate(param_lines):
                    if i > 0 and i % 2 == 0:  # New line every 2 parameters
                        y_offset += 25
                        line = param_lines[i-2] + ', ' + param_lines[i-1]
                        cv2.putText(display_img, line, (10, y_offset - 25),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
                        line = line if i == len(param_lines) - 1 else param_lines[i]
                    
                    if i % 2 == 0 or i == len(param_lines) - 1:
                        cv2.putText(display_img, line, (10, y_offset),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
                        if i % 2 == 0 and i < len(param_lines) - 1:
                            continue
                        y_offset += 25
            
            # Add instruction text
            cv2.putText(display_img, "Press any key to continue...", (10, display_img.shape[0] - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            cv2.imshow("Circle Detection Processing", display_img)
            if wait_for_key:
                cv2.waitKey(0)
        
        # Step 1: Show original image
        show_processing_step(image, "1. Original Image")
        
        # Step 2: Convert to grayscale for detection
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        show_processing_step(gray, "2. Grayscale Conversion")
        
        # Step 3: Apply Gaussian blur to reduce noise
        blur_ksize = (5, 5)
        blur_sigma = 0
        blurred = cv2.GaussianBlur(gray, blur_ksize, blur_sigma)
        show_processing_step(blurred, "3. Gaussian Blur", 
                           f"Kernel size: {blur_ksize}, Sigma: {blur_sigma}")

        # Step 4: Advanced Thresholding
        if threshold_method == "adaptive":
            # Original adaptive threshold
            thresh = cv2.adaptiveThreshold(
                blurred, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                block_size,
                constant_c
            )
            method_info = f"Adaptive Gaussian - Block: {block_size}, C: {constant_c}"
            
        elif threshold_method == "adaptive_mean":
            # Adaptive threshold with mean instead of Gaussian
            thresh = cv2.adaptiveThreshold(
                blurred, 255,
                cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY,
                block_size,
                constant_c
            )
            method_info = f"Adaptive Mean - Block: {block_size}, C: {constant_c}"
            
        elif threshold_method == "otsu":
            # Otsu's automatic threshold selection
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            method_info = "Otsu's automatic threshold"
            
        elif threshold_method == "triangle":
            # Triangle algorithm for automatic threshold
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_TRIANGLE)
            method_info = "Triangle algorithm threshold"
            
        elif threshold_method == "multi_otsu":
            # Multi-level Otsu thresholding (use middle threshold)
            try:
                from skimage.filters import threshold_multiotsu
                thresholds = threshold_multiotsu(blurred, classes=3)
                thresh = (blurred > thresholds[0]).astype(np.uint8) * 255
                method_info = f"Multi-Otsu threshold: {thresholds[0]:.1f}"
            except ImportError:
                # Fallback to regular Otsu if scikit-image not available
                _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                method_info = "Otsu's threshold (multi-Otsu unavailable)"
                
        elif threshold_method == "local_otsu":
            # Local Otsu thresholding for varying illumination
            try:
                from skimage.filters import rank
                from skimage.morphology import disk
                import numpy as np
                # Create a disk-shaped footprint for local thresholding
                footprint = disk(block_size // 2)
                local_thresh = rank.otsu(blurred, footprint)
                thresh = (blurred >= local_thresh).astype(np.uint8) * 255
                method_info = f"Local Otsu - Radius: {block_size // 2}"
            except ImportError:
                # Fallback to adaptive if scikit-image not available
                thresh = cv2.adaptiveThreshold(
                    blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, constant_c
                )
                method_info = f"Adaptive Gaussian (Local Otsu unavailable) - Block: {block_size}, C: {constant_c}"
                
        elif threshold_method == "percentile":
            # Percentile-based thresholding
            import numpy as np
            threshold_val = np.percentile(blurred, 85)  # Use 85th percentile as threshold
            _, thresh = cv2.threshold(blurred, threshold_val, 255, cv2.THRESH_BINARY)
            method_info = f"Percentile threshold: {threshold_val:.1f} (85th percentile)"
            
        elif threshold_method == "combination":
            # Combination of Otsu and adaptive for best of both worlds
            _, otsu_thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            adaptive_thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, constant_c
            )
            # Combine using bitwise AND to get intersection of both methods
            thresh = cv2.bitwise_and(otsu_thresh, adaptive_thresh)
            method_info = f"Combined Otsu + Adaptive - Block: {block_size}, C: {constant_c}"
            
        else:
            # Default to adaptive
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, constant_c
            )
            method_info = f"Default Adaptive - Block: {block_size}, C: {constant_c}"

        show_processing_step(thresh, "4. Threshold", method_info)

        # Step 4b: Handle threshold inversion
        if force_invert:
            thresh_inverted = cv2.bitwise_not(thresh)
            show_processing_step(thresh_inverted, "4b. Forced Inversion", 
                               "Threshold inverted (--force-invert)")
            thresh = thresh_inverted
        elif not no_auto_invert:
            # Auto-invert based on white pixel ratio
            white_pixels = cv2.countNonZero(thresh)
            total_pixels = thresh.shape[0] * thresh.shape[1]
            white_ratio = white_pixels / total_pixels
            
            # If more than 70% of pixels are white, likely need to invert
            if white_ratio > 0.7:
                thresh_inverted = cv2.bitwise_not(thresh)
                show_processing_step(thresh_inverted, "4b. Auto-Inverted Threshold", 
                                   f"Auto-inverted (white ratio: {white_ratio:.2f} > 0.7)")
                thresh = thresh_inverted
            else:
                show_processing_step(thresh, "4b. Threshold Check", 
                                   f"No inversion needed (white ratio: {white_ratio:.2f} <= 0.7)")
        else:
            show_processing_step(thresh, "4b. No Inversion", 
                               "Auto-inversion disabled (--no-auto-invert)")

        # Step 5: Morphological opening to remove noise
        kernel_shape = cv2.MORPH_ELLIPSE
        kernel_size = (3, 3)
        morph_iterations = 1
        kernel = cv2.getStructuringElement(kernel_shape, kernel_size)
        thresh_clean = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=morph_iterations)
        show_processing_step(thresh_clean, "5. Morphological Opening", 
                           f"Kernel: {kernel_size} ellipse, Iterations: {morph_iterations}")
        
        # Update variable name for consistency
        thresh = thresh_clean

        # Step 6: Circle Detection - Choose method based on user preference
        if detection_method == "hough":
            # Use Hough Circle Transform for overlapping circles
            circles = self._detect_hough_circles(blurred, thresh, show_processing_step, hough_param1, hough_param2, max_circles)
            keypoints = self._circles_to_keypoints(circles)
            
        elif detection_method == "combined":
            # Use both blob detection and Hough circles, then combine results
            blob_keypoints = self.detector.detect(thresh)
            circles = self._detect_hough_circles(blurred, thresh, show_processing_step, hough_param1, hough_param2, max_circles)
            hough_keypoints = self._circles_to_keypoints(circles)
            
            # Combine and remove duplicates
            keypoints = self._combine_detections(blob_keypoints, hough_keypoints, blurred, show_processing_step)
            
        else:
            # Default blob detection
            keypoints = self.detector.detect(thresh)
            
            # Show blob detection parameters
            detector_params = (f"Min Area: {self._min_area}, "
                              f"Min Circularity: {self._min_circularity}, "
                              f"Min Convexity: {self._min_convexity}, "
                              f"Min Inertia: {self._min_inertia}")
            
            # Create image with initial detections marked
            detection_img = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
            for kp in keypoints:
                x, y = int(kp.pt[0]), int(kp.pt[1])
                r = int(math.ceil(kp.size / 2.0))
                cv2.circle(detection_img, (x, y), r, (0, 255, 255), 2)  # Yellow circles
            
            show_processing_step(detection_img, "6. Blob Detection", 
                               f"Found {len(keypoints)} blobs, {detector_params}")
        
        # Step 7: Filter out keypoints that touch image borders (incomplete circles)
        h, w = gray.shape
        valid_keypoints = []
        filtered_keypoints = []
        for kp in keypoints:
            x, y, r = kp.pt[0], kp.pt[1], kp.size / 2.0
            if (x - r) < 0 or (y - r) < 0 or (x + r) > w - 1 or (y + r) > h - 1:
                filtered_keypoints.append(kp)  # Keep track of filtered ones
                continue  # skip incomplete blobs
            valid_keypoints.append(kp)
        
        # Show border filtering results
        border_filter_img = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        for kp in valid_keypoints:
            x, y = int(kp.pt[0]), int(kp.pt[1])
            r = int(math.ceil(kp.size / 2.0))
            cv2.circle(border_filter_img, (x, y), r, (0, 255, 0), 2)  # Green for valid
        for kp in filtered_keypoints:
            x, y = int(kp.pt[0]), int(kp.pt[1])
            r = int(math.ceil(kp.size / 2.0))
            cv2.circle(border_filter_img, (x, y), r, (0, 0, 255), 2)  # Red for filtered
        
        show_processing_step(border_filter_img, "7. Border Filtering", 
                           f"Valid: {len(valid_keypoints)}, Filtered: {len(filtered_keypoints)}")
        
        keypoints = valid_keypoints

        # Step 8: Draw final results - rectangles around detected circles
        draw_img = image.copy()
        for kp in keypoints:
            x, y = int(kp.pt[0]), int(kp.pt[1])
            r = int(math.ceil(kp.size / 2.0))
            cv2.rectangle(draw_img, (x - r, y - r), (x + r, y + r), (0, 255, 0), 2)

        # Overlay circle count
        count = len(keypoints)
        cv2.putText(draw_img, f"Circles: {count}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        show_processing_step(draw_img, "8. Final Results", 
                           f"Total circles detected: {count}", wait_for_key=False)

        # Save output image
        if output_path:
            out_path = output_path
        else:
            dot_index = image_path.rfind('.')
            out_path = image_path[:dot_index] + "_detected" + image_path[dot_index:]
        cv2.imwrite(out_path, draw_img)

        # Final display for non-show mode or cleanup
        if show:
            cv2.waitKey(0)  # Wait for final key press
            cv2.destroyAllWindows()
        
        return count
        
    def _detect_hough_circles(self, image):
        """Detect circles using HoughCircles transform."""
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Calculate radius range with debugging
        image_size = min(gray.shape)
        min_radius = max(10, image_size // 50)
        max_radius = image_size // self.args.max_radius_factor
        min_dist = max(min_radius, 20)
        
        # Debug information
        if hasattr(self.args, 'show_processing') and self.args.show_processing:
            print(f"Hough Circle Detection Parameters:")
            print(f"  Image size: {gray.shape}")
            print(f"  Radius range: {min_radius} - {max_radius}")
            print(f"  Min distance: {min_dist}")
            print(f"  Param1: {self.args.hough_param1}, Param2: {self.args.hough_param2}")
        
        # Apply HoughCircles
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1,
            minDist=min_dist,
            param1=self.args.hough_param1,
            param2=self.args.hough_param2,
            minRadius=min_radius,
            maxRadius=max_radius
        )
        
        keypoints = []
        if circles is not None:
            circles = np.round(circles[0, :]).astype("int")
            # Limit the number of circles
            circles = circles[:self.args.max_circles]
            
            # Debug information
            if hasattr(self.args, 'show_processing') and self.args.show_processing:
                print(f"  Found {len(circles)} circles")
                if len(circles) > 0:
                    radii = [c[2] for c in circles]
                    print(f"  Radius range found: {min(radii)} - {max(radii)}")
            
            # Convert to KeyPoints
            for (x, y, r) in circles:
                keypoint = cv2.KeyPoint(float(x), float(y), float(r * 2))  # diameter = 2 * radius
                keypoints.append(keypoint)
        else:
            if hasattr(self.args, 'show_processing') and self.args.show_processing:
                print(f"  No circles found")
                
        return keypoints
    
    def _circles_to_keypoints(self, circles):
        """Convert Hough circles to keypoints compatible with blob detector format"""
        keypoints = []
        if circles is not None and len(circles) > 0:
            for (x, y, r) in circles:
                # Create a keypoint with proper area and circularity
                area = math.pi * r * r
                if area >= self._min_area:  # Apply area filter
                    kp = cv2.KeyPoint(float(x), float(y), float(r * 2))  # size = diameter
                    keypoints.append(kp)
        return keypoints
    
    def _combine_detections(self, blob_keypoints, hough_keypoints, blurred, show_processing_step):
        """Combine blob and Hough detections, removing duplicates"""
        all_keypoints = list(blob_keypoints)
        
        # Add Hough keypoints that don't overlap significantly with blob keypoints
        for hough_kp in hough_keypoints:
            is_duplicate = False
            hough_x, hough_y = hough_kp.pt
            hough_r = hough_kp.size / 2.0
            
            for blob_kp in blob_keypoints:
                blob_x, blob_y = blob_kp.pt
                blob_r = blob_kp.size / 2.0
                
                # Calculate distance between centers
                distance = math.sqrt((hough_x - blob_x)**2 + (hough_y - blob_y)**2)
                overlap_threshold = min(hough_r, blob_r) * 0.5  # 50% radius overlap threshold
                
                if distance < overlap_threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                all_keypoints.append(hough_kp)
        
        # Visualize combined results
        combined_img = cv2.cvtColor(np.zeros_like(blurred), cv2.COLOR_GRAY2BGR)
        for i, kp in enumerate(all_keypoints):
            x, y = int(kp.pt[0]), int(kp.pt[1])
            r = int(math.ceil(kp.size / 2.0))
            color = (0, 255, 255) if i < len(blob_keypoints) else (255, 0, 255)  # Yellow for blob, Magenta for Hough
            cv2.circle(combined_img, (x, y), r, color, 2)
        
        show_processing_step(combined_img, "6. Combined Detection", 
                           f"Blob: {len(blob_keypoints)}, Hough: {len(hough_keypoints)}, Total: {len(all_keypoints)}")
        
        return all_keypoints

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect circles in an image using cv2.SimpleBlobDetector")
    parser.add_argument("--input", "-i", required=True, help="Path to the input image")
    parser.add_argument("--output", "-o", help="Path to save the output image with detected circles")
    parser.add_argument("--minArea", type=float, required=True, help="Minimum area of circles to detect (in pixels)")
    parser.add_argument("--minCircularity", type=float, required=True, help="Minimum circularity [0,1] to filter blobs")
    parser.add_argument("--minConvexity", type=float, required=True, help="Minimum convexity [0,1] to filter blobs")
    parser.add_argument("--minInertiaRatio", type=float, required=True, help="Minimum inertia ratio [0,1] to filter blobs")
    parser.add_argument("--show", action="store_true", help="Show step-by-step processing visualization")
    parser.add_argument("--no-show", action="store_true", help="Disable visualization (process silently)")
    parser.add_argument("--block-size", type=int, default=21, help="Block size for adaptive threshold (must be odd, default: 21)")
    parser.add_argument("--constant-c", type=int, default=2, help="Constant C for adaptive threshold (default: 2)")
    parser.add_argument("--threshold-method", default="adaptive", 
                       choices=["adaptive", "adaptive_mean", "otsu", "triangle", "multi_otsu", "local_otsu", "percentile", "combination"],
                       help="Thresholding method (default: adaptive)")
    parser.add_argument("--detection-method", default="blob",
                       choices=["blob", "hough", "combined"],
                       help="Circle detection method: blob (default), hough (better for overlapping), combined (both)")
    parser.add_argument("--hough-param1", type=int, default=100, help="Hough param1 - edge detection threshold (default: 100)")
    parser.add_argument("--hough-param2", type=int, default=50, help="Hough param2 - accumulator threshold, lower=more circles (default: 50)")
    parser.add_argument("--max-circles", type=int, default=100, help="Maximum number of circles to detect (default: 100)")
    parser.add_argument("--max-radius-factor", type=int, default=3, help="Max radius = image_size / this_factor (default: 3)")
    parser.add_argument("--force-invert", action="store_true", help="Force inversion of threshold (black circles on white background)")
    parser.add_argument("--no-auto-invert", action="store_true", help="Disable automatic threshold inversion")
    args = parser.parse_args()
    
    # Determine show mode: default to True unless --no-show is specified
    show_visualization = not args.no_show if args.no_show else args.show if args.show else True
    
    # Create detector with specified parameters
    detector = CircleDetector(args.minArea, args.minCircularity, args.minInertiaRatio, args.minConvexity)
    # Run detection and drawing
    count = detector.detect_and_draw(
        args.input, 
        args.output, 
        show=show_visualization,
        block_size=args.block_size,
        constant_c=args.constant_c,
        force_invert=args.force_invert,
        no_auto_invert=args.no_auto_invert,
        threshold_method=args.threshold_method,
        detection_method=args.detection_method,
        hough_param1=args.hough_param1,
        hough_param2=args.hough_param2,
        max_circles=args.max_circles
    )
    print(f"Detected {count} circles.")
