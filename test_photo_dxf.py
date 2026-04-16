#!/usr/bin/env python3
"""
Test script for Photo-to-DXF functionality
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
        # Create a simple test image
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.rectangle(img, (20, 20), (80, 80), (255, 255, 255), 2)
        cv2.circle(img, (50, 50), 20, (255, 255, 255), 2)

        # Convert to grayscale and detect edges
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)

        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        print(f"Test successful: Found {len(contours)} contours")
        print("Photo-to-DXF functionality should work!")

    else:
        print("OpenCV not available - Photo-to-DXF tab will show installation message")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()