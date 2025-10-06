import cv2
import numpy as np

# Load image
image_path = '/Volumes/T7/Temika/Images/png/4_2_9_0_01.png'
image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

# Display original image
cv2.imshow("Original Image", image)
cv2.waitKey(0)

# Step 1: Apply Gaussian Blur
blurred = cv2.GaussianBlur(image, (3, 3), 0)
cv2.imshow("Gaussian Blurred", blurred)
cv2.waitKey(0)

# Step 2: Adaptive Thresholding (Otsu's Method)
_, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
cv2.imshow("Thresholded (Binary)", binary)
cv2.waitKey(0)


# Step 3: Distance Transform

#dist_transform = cv2.distanceTransform(cv2.bitwise_not(binary), cv2.DIST_L2, 5)

dist_transform = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
dist_display = cv2.normalize(dist_transform, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
cv2.imshow("Distance Transform", dist_display)
cv2.waitKey(0)

# Step 4: Peak detection (finding circle centers)
_, sure_fg = cv2.threshold(dist_transform, 0.3 * dist_transform.max(), 255, 0)
sure_fg = np.uint8(sure_fg)
cv2.imshow("Sure Foreground (Peaks)", sure_fg)
cv2.waitKey(0)

# Finding unknown region
sure_bg = cv2.dilate(binary, np.ones((3, 3), np.uint8), iterations=1)
unknown = cv2.subtract(sure_bg, sure_fg)

# Marker labelling
_, markers = cv2.connectedComponents(sure_fg)
markers = markers + 1
markers[unknown == 255] = 0

# Step 5: Watershed segmentation
color_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
markers = cv2.watershed(color_image, markers)
color_image[markers == -1] = [0, 0, 255]  # mark boundaries in red
cv2.imshow("Watershed Segmentation", color_image)
cv2.waitKey(0)

# Step 6: Extract and display circles
circles_image = color_image.copy()
for marker in range(2, markers.max() + 1):
    mask = np.uint8(markers == marker)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        c = max(contours, key=cv2.contourArea)
        ((x, y), radius) = cv2.minEnclosingCircle(c)
        cv2.circle(circles_image, (int(x), int(y)), int(radius), (0, 255, 0), 2)
        cv2.circle(circles_image, (int(x), int(y)), 3, (255, 0, 0), -1)

cv2.imshow("Detected Circles", circles_image)
cv2.waitKey(0)

cv2.destroyAllWindows()
