#!/usr/bin/env python3
"""
Create a test image for Photo-to-DXF functionality
"""

import cv2
import numpy as np

# Create a white background
img = np.ones((400, 600, 3), dtype=np.uint8) * 255

# Draw some shapes to test contour detection
# Rectangle
cv2.rectangle(img, (50, 50), (200, 150), (0, 0, 0), 3)

# Circle
cv2.circle(img, (350, 100), 60, (0, 0, 0), 3)

# Triangle
pts = np.array([[450, 200], [500, 50], [550, 200]], np.int32)
cv2.polylines(img, [pts], True, (0, 0, 0), 3)

# Add some text
cv2.putText(img, 'Test Shapes for CNC', (50, 350), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)

# Save the image
cv2.imwrite('test_shapes.png', img)
print("Test image 'test_shapes.png' created successfully!")
print("Use this image to test the Photo-to-DXF feature.")