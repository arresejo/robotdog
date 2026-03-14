"""Depth estimator — convert pixel coordinates to world position.

Uses bounding-box-based distance estimation (no LiDAR projection needed).
Can be upgraded to LiDAR projection later for higher accuracy.
"""

import logging
import math

from src.state_tracker import RobotPose

log = logging.getLogger(__name__)

# Go2 front camera approximate intrinsics (1280x720)
# These should be calibrated for your specific unit
CAMERA_FX = 640.0  # focal length x (pixels)
CAMERA_FY = 640.0  # focal length y (pixels)
CAMERA_CX = 640.0  # principal point x (image center)
CAMERA_CY = 360.0  # principal point y (image center)
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720

# Known real-world heights of common objects (meters)
OBJECT_HEIGHTS = {
    "chair": 0.85,
    "person": 1.70,
    "couch": 0.80,
    "table": 0.75,
    "bottle": 0.25,
    "cup": 0.12,
    "backpack": 0.50,
    "suitcase": 0.60,
    "dog": 0.50,
    "cat": 0.30,
    "tv": 0.50,
    "laptop": 0.25,
    "bed": 0.60,
}


def estimate_distance(
    bbox_height_px: float,
    target_class: str = "chair",
    real_height_override: float | None = None,
) -> float:
    """Estimate distance to object using bounding box height.

    Uses the pinhole camera model: distance = (real_height * focal_length) / bbox_height

    Returns distance in meters.
    """
    real_height = real_height_override or OBJECT_HEIGHTS.get(target_class, 0.85)

    if bbox_height_px < 10:
        log.warning("Bounding box too small (%d px), distance unreliable", bbox_height_px)
        return 10.0  # cap at 10m

    distance = (real_height * CAMERA_FY) / bbox_height_px
    return distance


def estimate_bearing(center_u: float) -> float:
    """Estimate horizontal bearing angle from pixel u coordinate.

    Returns angle in radians. Negative = left, Positive = right.
    """
    return math.atan2(center_u - CAMERA_CX, CAMERA_FX)


def pixel_to_world(
    center_u: float,
    center_v: float,
    bbox_height_px: float,
    robot_pose: RobotPose,
    target_class: str = "chair",
) -> tuple[float, float, float]:
    """Convert pixel detection to world coordinates.

    Args:
        center_u: Pixel x of detection center
        center_v: Pixel y of detection center
        bbox_height_px: Height of bounding box in pixels
        robot_pose: Current robot pose in map frame
        target_class: Object class for size estimation

    Returns:
        (world_x, world_y, distance) in meters, in the map frame
    """
    distance = estimate_distance(bbox_height_px, target_class)
    bearing = estimate_bearing(center_u)

    # Transform to world frame
    world_yaw = robot_pose.yaw + bearing
    world_x = robot_pose.x + distance * math.cos(world_yaw)
    world_y = robot_pose.y + distance * math.sin(world_yaw)

    log.debug(
        "Pixel (%.0f, %.0f) → distance=%.2fm, bearing=%.1f° → world (%.2f, %.2f)",
        center_u,
        center_v,
        distance,
        math.degrees(bearing),
        world_x,
        world_y,
    )

    return world_x, world_y, distance
