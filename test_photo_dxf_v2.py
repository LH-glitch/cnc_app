#!/usr/bin/env python3
"""
Test script for the updated Photo-to-DXF functionality with optional smart geometry recognition
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

try:
    from gui import OPENCV_AVAILABLE, MATPLOTLIB_AVAILABLE
    print(f"OpenCV available: {OPENCV_AVAILABLE}")
    print(f"Matplotlib available: {MATPLOTLIB_AVAILABLE}")

    if OPENCV_AVAILABLE:
        import cv2
        import numpy as np
        from PIL import Image
        print("All dependencies loaded successfully")

        # Test basic functionality
        # Create a test image with various shapes
        img = np.ones((300, 400, 3), dtype=np.uint8) * 255

        # Rectangle
        cv2.rectangle(img, (50, 50), (150, 100), (0, 0, 0), 2)

        # Circle
        cv2.circle(img, (250, 75), 40, (0, 0, 0), 2)

        # Triangle
        pts = np.array([[300, 150], [350, 50], [400, 150]], np.int32)
        cv2.polylines(img, [pts], True, (0, 0, 0), 2)

        # Irregular shape (should remain as polyline)
        irregular_pts = np.array([[50, 200], [80, 180], [120, 190], [100, 230], [60, 220]], np.int32)
        cv2.polylines(img, [irregular_pts], True, (0, 0, 0), 2)

        # Save test image
        cv2.imwrite('test_shapes_v2.png', img)
        print("Test image 'test_shapes_v2.png' created with rectangle, circle, triangle, and irregular shape")

        # Test contour detection
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        print(f"Found {len(contours)} contours in test image")
        print("Photo-to-DXF functionality with optional smart geometry recognition should work!")

    else:
        print("OpenCV not available - Photo-to-DXF tab will show installation message")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()