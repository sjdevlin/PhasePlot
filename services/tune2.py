import cv2
import numpy as np
from skimage.feature import peak_local_max
from scipy import ndimage

def nothing(x):
    pass

# Load image
image_path = '/Volumes/T7/Temika/Images/png/4_2_9_0_01.png'
image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

# Create windows for tuning
cv2.namedWindow("Thresholding", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Thresholding", 600, 100)

cv2.createTrackbar("Thresh", "Thresholding", 127, 255, nothing)
cv2.createTrackbar("Clahex", "Thresholding", 1, 10, nothing)
cv2.createTrackbar("Dist %", "Thresholding", 30, 100, nothing)

while True:
    thresh_value = cv2.getTrackbarPos("Thresh", "Thresholding")
    dist_percent = cv2.getTrackbarPos("Dist %", "Thresholding") / 100.0
    clahe = cv2.getTrackbarPos("Clahex", "Thresholding")

    clahe_thing = cv2.createCLAHE(clipLimit=clahe, tileGridSize=(8,8))

    enhanced = clahe_thing.apply(image)
    # Step 1: Apply Gaussian Blur
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)

    # Step 2: Manual Thresholding
    _, binary = cv2.threshold(blurred, thresh_value, 255, cv2.THRESH_BINARY)

    # Display Thresholded image
    cv2.imshow("Thresholding", binary)

    key = cv2.waitKey(1)
    if key == ord('q'):
        break

cv2.destroyWindow("Thresholding")

# Distance Transform
dist_transform = cv2.distanceTransform(binary, cv2.DIST_L2, 5)

# Peak detection using local maxima
coordinates = peak_local_max(dist_transform, min_distance=5, labels=binary)


coordinates = peak_local_max(
    dist_transform,
    min_distance=5,
    threshold_abs=dist_percent * dist_transform.max(),
    labels=binary
)
local_max = np.zeros_like(dist_transform, dtype=bool)
local_max[tuple(coordinates.T)] = True

markers, _ = ndimage.label(local_max)

# Convert markers to integer and add 1 for watershed
markers = markers + 1

# Define unknown region
sure_bg = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=1)
unknown = cv2.subtract(sure_bg, np.uint8(local_max) * 255)
markers[unknown == 255] = 0

# Watershed segmentation
color_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
markers = cv2.watershed(color_image, markers)
color_image[markers == -1] = [0, 0, 255]

# Extract and display circles
circles_image = color_image.copy()
for marker in range(2, markers.max() + 1):
    mask = np.uint8(markers == marker)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        ((x, y), radius) = cv2.minEnclosingCircle(c)
        if radius > 2:  # filter very small noise blobs
            cv2.circle(circles_image, (int(x), int(y)), int(radius), (0, 255, 0), 2)
            cv2.circle(circles_image, (int(x), int(y)), 3, (255, 0, 0), -1)

cv2.imshow("Detected Circles", circles_image)
cv2.waitKey(0)
cv2.destroyAllWindows()
