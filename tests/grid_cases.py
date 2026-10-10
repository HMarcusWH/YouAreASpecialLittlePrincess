"""Synthetic geometry only. No personal handwriting or third-party specimens."""
import cv2
import numpy as np


def specimen(*, grid='blue', text=True, width=720, height=480, pitch=40, crossing=False):
    image = np.full((height, width, 3), 255, np.uint8)
    if grid != 'none':
        grid_bgr = {'blue': (230, 196, 167), 'gray': (190, 190, 190),
                    'black': (60, 60, 60)}[grid]
        for x in range(20, width, pitch):
            cv2.line(image, (x, 0), (x, height - 1), grid_bgr, 1)
        for y in range(20, height, pitch):
            cv2.line(image, (0, y), (width - 1, y), grid_bgr, 1)
    marks = np.zeros((height, width), np.uint8)
    if text:
        cv2.putText(marks, 'Hej hur mar du?', (95, 237), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
                    1.4, 255, 2, cv2.LINE_8)
        if crossing:
            cv2.line(marks, (180, 170), (180, 270), 255, 3)
            cv2.line(marks, (165, 203), (205, 203), 255, 3)
        image[marks > 0] = (24, 24, 24)
    return image, marks
