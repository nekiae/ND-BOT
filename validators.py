"""Photo validation utilities for pose detection."""

import cv2
import numpy as np
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def classify_pose(image_bytes: bytes) -> Tuple[str, float]:
    """
    Classify photo pose as front or profile based on yaw angle.
    
    Args:
        image_bytes: Raw image bytes
        
    Returns:
        Tuple of (pose_type, yaw_angle) where pose_type is 'front' or 'profile'
    """
    try:
        # Convert bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            raise ValueError("Could not decode image")
        
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Load face cascade
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        profile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')
        
        # Detect faces
        frontal_faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        profile_faces = profile_cascade.detectMultiScale(gray, 1.1, 4)
        
        # Simple heuristic based on detection confidence
        frontal_score = len(frontal_faces)
        profile_score = len(profile_faces)
        
        if frontal_score > profile_score:
            # Estimate yaw for frontal face (simplified)
            yaw_angle = estimate_yaw_simple(gray, frontal_faces)
            return "front", yaw_angle
        else:
            # Profile detected or no clear frontal
            return "profile", 60.0  # Assume profile angle
            
    except Exception as e:
        logger.error(f"Error in pose classification: {e}")
        # Fallback: assume front pose
        return "front", 0.0


def estimate_yaw_simple(gray_image: np.ndarray, faces: np.ndarray) -> float:
    """
    Simple yaw estimation based on face symmetry.
    
    Args:
        gray_image: Grayscale image
        faces: Detected face rectangles
        
    Returns:
        Estimated yaw angle in degrees
    """
    if len(faces) == 0:
        return 0.0
    
    # Take the largest face
    face = max(faces, key=lambda x: x[2] * x[3])
    x, y, w, h = face
    
    # Extract face region
    face_roi = gray_image[y:y+h, x:x+w]
    
    # Simple symmetry check
    left_half = face_roi[:, :w//2]
    right_half = cv2.flip(face_roi[:, w//2:], 1)
    
    # Resize to match if needed
    min_width = min(left_half.shape[1], right_half.shape[1])
    left_half = left_half[:, :min_width]
    right_half = right_half[:, :min_width]
    
    # Calculate difference
    if left_half.shape == right_half.shape:
        diff = np.mean(np.abs(left_half.astype(float) - right_half.astype(float)))
        # Convert difference to rough yaw estimate (0-30 degrees)
        yaw_angle = min(diff / 10.0, 30.0)
    else:
        yaw_angle = 15.0  # Default moderate angle
    
    return yaw_angle


def validate_front_photo(image_bytes: bytes) -> Tuple[bool, str]:
    """
    Validate that photo is suitable for frontal analysis.
    
    Args:
        image_bytes: Raw image bytes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        pose_type, yaw_angle = classify_pose(image_bytes)
        
        if pose_type != "front":
            return False, "Фото должно быть анфас (лицом к камере)"
        
        if yaw_angle > 15.0:
            return False, f"Поверните голову прямо к камере (текущий угол: {yaw_angle:.1f}°)"
        
        return True, ""
        
    except Exception as e:
        logger.error(f"Error validating front photo: {e}")
        return False, "Ошибка обработки фото. Попробуйте другое изображение."


def validate_profile_photo(image_bytes: bytes) -> Tuple[bool, str]:
    """
    Validate that photo is suitable for profile analysis.
    
    Args:
        image_bytes: Raw image bytes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        pose_type, yaw_angle = classify_pose(image_bytes)
        
        if pose_type == "front" and yaw_angle < 45.0:
            return False, "Фото должно быть в профиль (боком к камере)"
        
        # For profile, we're more lenient
        return True, ""
        
    except Exception as e:
        logger.error(f"Error validating profile photo: {e}")
        return False, "Ошибка обработки фото. Попробуйте другое изображение."


def validate_image_quality(image_bytes: bytes) -> Tuple[bool, str]:
    """
    Basic image quality validation.
    
    Args:
        image_bytes: Raw image bytes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        # Check file size (min 50KB, max 10MB)
        size_mb = len(image_bytes) / (1024 * 1024)
        if size_mb < 0.05:
            return False, "Изображение слишком маленькое. Минимум 50KB."
        if size_mb > 10:
            return False, "Изображение слишком большое. Максимум 10MB."
        
        # Try to decode
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            return False, "Не удалось обработать изображение. Проверьте формат файла."
        
        # Check dimensions
        height, width = image.shape[:2]
        if width < 200 or height < 200:
            return False, "Разрешение слишком низкое. Минимум 200x200 пикселей."
        
        return True, ""
        
    except Exception as e:
        logger.error(f"Error validating image quality: {e}")
        return False, "Ошибка проверки качества изображения."
