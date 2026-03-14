"""Object detector using YOLOv8 — detects target objects in camera frames."""

import logging

import cv2
import numpy as np
from ultralytics import YOLO

log = logging.getLogger(__name__)

# COCO class IDs for common targets
COCO_CLASSES = {
    "person": 0,
    "chair": 56,
    "couch": 57,
    "bed": 59,
    "table": 60,
    "tv": 62,
    "laptop": 63,
    "bottle": 39,
    "cup": 41,
    "backpack": 24,
    "suitcase": 28,
    "dog": 16,
    "cat": 15,
}


class ObjectDetector:
    """Detect objects in camera frames using YOLOv8."""

    def __init__(self, model_name: str = "yolov8n.pt", confidence: float = 0.5):
        self.model = YOLO(model_name)
        self.confidence = confidence

    def detect(
        self, frame: np.ndarray, target_class: str = "chair"
    ) -> dict | None:
        """Detect the target object in a frame.

        Returns the best detection as:
            {
                "class": "chair",
                "confidence": 0.87,
                "center_px": (u, v),     # pixel coordinates of center
                "bbox": (x1, y1, x2, y2),  # bounding box
                "bbox_width": w,
                "bbox_height": h,
            }
        or None if not found.
        """
        class_id = COCO_CLASSES.get(target_class)
        if class_id is None:
            log.error("Unknown target class: %s", target_class)
            return None

        results = self.model(frame, classes=[class_id], conf=self.confidence, verbose=False)

        if not results or len(results[0].boxes) == 0:
            return None

        # Pick the highest-confidence detection
        boxes = results[0].boxes
        best_idx = int(boxes.conf.argmax())
        box = boxes[best_idx]

        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
        cx, cy = box.xywh[0][:2].cpu().numpy()
        w, h = box.xywh[0][2:].cpu().numpy()

        return {
            "class": target_class,
            "confidence": float(box.conf[0]),
            "center_px": (float(cx), float(cy)),
            "bbox": (float(x1), float(y1), float(x2), float(y2)),
            "bbox_width": float(w),
            "bbox_height": float(h),
        }

    def detect_and_annotate(
        self, frame: np.ndarray, target_class: str = "chair"
    ) -> tuple[np.ndarray, dict | None]:
        """Detect and draw bounding box on the frame. Returns (annotated_frame, detection)."""
        detection = self.detect(frame, target_class)
        annotated = frame.copy()

        if detection:
            x1, y1, x2, y2 = detection["bbox"]
            cx, cy = detection["center_px"]
            conf = detection["confidence"]

            cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cv2.circle(annotated, (int(cx), int(cy)), 5, (0, 0, 255), -1)
            label = f"{target_class} {conf:.2f}"
            cv2.putText(
                annotated, label, (int(x1), int(y1) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
            )

        return annotated, detection
