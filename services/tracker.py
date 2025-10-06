import cv2
import numpy as np

def nothing(x):
    pass

cv2.namedWindow("Trackbar Test", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Trackbar Test", 400, 100)
cv2.createTrackbar("Value", "Trackbar Test", 127, 255, nothing)
cv2.createTrackbar("Cla", "Trackbar Test", 127, 255, nothing)
cv2.createTrackbar("Fuck", "Trackbar Test", 127, 255, nothing)

img = np.zeros((100, 400), dtype=np.uint8)

while True:
    val = cv2.getTrackbarPos("Value", "Trackbar Test")
    img[:] = val
    cv2.imshow("Trackbar Test", img)
    if cv2.waitKey(1) == ord('q'):
        break

cv2.destroyAllWindows()
