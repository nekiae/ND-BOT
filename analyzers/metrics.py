"""Facial metrics extraction and analysis."""

import numpy as np
from typing import Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)


def parse_landmark106(landmark_data: List[Dict[str, float]]) -> np.ndarray:
    """
    Parse AILab landmark106 data to numpy array.
    
    Args:
        landmark_data: List of landmark points with x, y coordinates
        
    Returns:
        Numpy array of shape (106, 2)
    """
    landmarks = np.zeros((106, 2))
    
    for i, point in enumerate(landmark_data[:106]):
        landmarks[i, 0] = point.get('x', 0)
        landmarks[i, 1] = point.get('y', 0)
    
    return landmarks


def calculate_distance(p1: np.ndarray, p2: np.ndarray) -> float:
    """Calculate Euclidean distance between two points."""
    return np.linalg.norm(p1 - p2)


def calculate_angle(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> float:
    """
    Calculate angle at p2 formed by p1-p2-p3.
    
    Returns angle in degrees.
    """
    v1 = p1 - p2
    v2 = p3 - p2
    
    cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    cos_angle = np.clip(cos_angle, -1.0, 1.0)
    
    angle_rad = np.arccos(cos_angle)
    return np.degrees(angle_rad)


def extract_canthal_tilt(landmarks: np.ndarray) -> float:
    """
    Extract canthal tilt angle.
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Canthal tilt angle in degrees (positive = upward tilt)
    """
    try:
        # Approximate eye corner positions (adjust indices based on landmark106 format)
        left_outer = landmarks[36]  # Left outer corner
        left_inner = landmarks[39]  # Left inner corner
        right_inner = landmarks[42]  # Right inner corner  
        right_outer = landmarks[45]  # Right outer corner
        
        # Calculate tilt for each eye
        left_tilt = np.degrees(np.arctan2(
            left_outer[1] - left_inner[1],
            left_outer[0] - left_inner[0]
        ))
        
        right_tilt = np.degrees(np.arctan2(
            right_inner[1] - right_outer[1],
            right_inner[0] - right_outer[0]
        ))
        
        # Average tilt
        avg_tilt = (left_tilt + right_tilt) / 2
        
        return avg_tilt
        
    except Exception as e:
        logger.error(f"Error calculating canthal tilt: {e}")
        return 0.0


def extract_gonial_angle(landmarks: np.ndarray) -> float:
    """
    Extract gonial (jaw) angle.
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Gonial angle in degrees
    """
    try:
        # Approximate jaw points (adjust indices based on landmark106 format)
        jaw_left = landmarks[0]   # Left jaw point
        jaw_bottom = landmarks[8]  # Bottom jaw point
        jaw_right = landmarks[16]  # Right jaw point
        
        # Calculate angle at bottom jaw point
        angle = calculate_angle(jaw_left, jaw_bottom, jaw_right)
        
        return angle
        
    except Exception as e:
        logger.error(f"Error calculating gonial angle: {e}")
        return 120.0  # Default average


def extract_midface_ratio(landmarks: np.ndarray) -> float:
    """
    Extract midface ratio (nose length / face width).
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Midface ratio
    """
    try:
        # Approximate points
        nose_top = landmarks[27]    # Nose bridge
        nose_bottom = landmarks[33] # Nose tip
        face_left = landmarks[0]    # Left face edge
        face_right = landmarks[16]  # Right face edge
        
        nose_length = calculate_distance(nose_top, nose_bottom)
        face_width = calculate_distance(face_left, face_right)
        
        if face_width > 0:
            return nose_length / face_width
        else:
            return 0.5  # Default ratio
            
    except Exception as e:
        logger.error(f"Error calculating midface ratio: {e}")
        return 0.5


def extract_facial_thirds(landmarks: np.ndarray) -> Dict[str, float]:
    """
    Extract facial thirds proportions.
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Dictionary with upper, middle, lower third ratios
    """
    try:
        # Approximate key points
        forehead_top = landmarks[24]    # Hairline approximation
        eyebrow = landmarks[19]         # Eyebrow
        nose_base = landmarks[33]       # Nose base
        chin = landmarks[8]             # Chin
        
        # Calculate distances
        upper_third = calculate_distance(forehead_top, eyebrow)
        middle_third = calculate_distance(eyebrow, nose_base)
        lower_third = calculate_distance(nose_base, chin)
        
        total_height = upper_third + middle_third + lower_third
        
        if total_height > 0:
            return {
                "upper": upper_third / total_height,
                "middle": middle_third / total_height,
                "lower": lower_third / total_height
            }
        else:
            return {"upper": 0.33, "middle": 0.33, "lower": 0.33}
            
    except Exception as e:
        logger.error(f"Error calculating facial thirds: {e}")
        return {"upper": 0.33, "middle": 0.33, "lower": 0.33}


def extract_chin_projection(landmarks: np.ndarray) -> float:
    """
    Extract chin projection relative to face.
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Chin projection ratio
    """
    try:
        # Approximate points
        nose_tip = landmarks[33]  # Nose tip
        chin = landmarks[8]       # Chin point
        face_center = landmarks[30]  # Face center approximation
        
        # Calculate projection
        nose_to_center = calculate_distance(nose_tip, face_center)
        chin_to_center = calculate_distance(chin, face_center)
        
        if nose_to_center > 0:
            return chin_to_center / nose_to_center
        else:
            return 1.0
            
    except Exception as e:
        logger.error(f"Error calculating chin projection: {e}")
        return 1.0


def extract_nasofrontal_angle(landmarks: np.ndarray) -> float:
    """
    Extract nasofrontal angle.
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Nasofrontal angle in degrees
    """
    try:
        # Approximate points
        forehead = landmarks[24]  # Forehead point
        nose_bridge = landmarks[27]  # Nose bridge
        nose_tip = landmarks[33]  # Nose tip
        
        # Calculate angle
        angle = calculate_angle(forehead, nose_bridge, nose_tip)
        
        return angle
        
    except Exception as e:
        logger.error(f"Error calculating nasofrontal angle: {e}")
        return 130.0  # Default angle


def calculate_symmetry_score(landmarks: np.ndarray) -> float:
    """
    Calculate facial symmetry score.
    
    Args:
        landmarks: 106-point landmarks array
        
    Returns:
        Symmetry score (0-1, higher is more symmetric)
    """
    try:
        # Find face center
        face_center_x = np.mean(landmarks[:, 0])
        
        # Calculate symmetry for key points
        symmetry_scores = []
        
        # Check eye symmetry
        left_eye = landmarks[36:42]  # Left eye points
        right_eye = landmarks[42:48]  # Right eye points
        
        for i in range(len(left_eye)):
            left_dist = abs(left_eye[i][0] - face_center_x)
            right_dist = abs(right_eye[i][0] - face_center_x)
            
            if left_dist + right_dist > 0:
                symmetry = 1 - abs(left_dist - right_dist) / (left_dist + right_dist)
                symmetry_scores.append(symmetry)
        
        # Average symmetry score
        if symmetry_scores:
            return np.mean(symmetry_scores)
        else:
            return 0.8  # Default good symmetry
            
    except Exception as e:
        logger.error(f"Error calculating symmetry: {e}")
        return 0.8


def extract_all_metrics(
    facepp_result: Dict[str, Any], 
    ailab_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Extract all facial metrics from API results.
    
    Args:
        facepp_result: Face++ API response
        ailab_result: AILab API response
        
    Returns:
        Dictionary with all extracted metrics
    """
    metrics = {}
    
    try:
        # Extract Face++ metrics
        if "faces" in facepp_result and len(facepp_result["faces"]) > 0:
            face = facepp_result["faces"][0]
            
            # Beauty score
            if "attributes" in face and "beauty" in face["attributes"]:
                beauty = face["attributes"]["beauty"]
                metrics["beauty_male"] = beauty.get("male_score", 50)
                metrics["beauty_female"] = beauty.get("female_score", 50)
                metrics["beauty_avg"] = (metrics["beauty_male"] + metrics["beauty_female"]) / 2
            
            # Head pose
            if "attributes" in face and "headpose" in face["attributes"]:
                headpose = face["attributes"]["headpose"]
                metrics["yaw"] = headpose.get("yaw_angle", 0)
                metrics["pitch"] = headpose.get("pitch_angle", 0)
                metrics["roll"] = headpose.get("roll_angle", 0)
        
        # Extract AILab landmarks
        if "data" in ailab_result and "landmark106" in ailab_result["data"]:
            landmark_data = ailab_result["data"]["landmark106"]
            landmarks = parse_landmark106(landmark_data)
            
            # Calculate geometric metrics
            metrics["canthal_tilt"] = extract_canthal_tilt(landmarks)
            metrics["gonial_angle"] = extract_gonial_angle(landmarks)
            metrics["midface_ratio"] = extract_midface_ratio(landmarks)
            metrics["chin_projection"] = extract_chin_projection(landmarks)
            metrics["nasofrontal_angle"] = extract_nasofrontal_angle(landmarks)
            metrics["symmetry_score"] = calculate_symmetry_score(landmarks)
            
            # Facial thirds
            thirds = extract_facial_thirds(landmarks)
            metrics.update({f"third_{k}": v for k, v in thirds.items()})
        
        # Calculate composite ratings
        beauty_score = metrics.get("beauty_avg", 50) / 10  # Convert to 0-10 scale
        metrics["base_rating"] = beauty_score
        
        # Composite rating with weights
        canthal_score = max(0, min(10, 5 + metrics.get("canthal_tilt", 0) / 2))  # Positive tilt is better
        gonial_score = max(0, min(10, 10 - abs(metrics.get("gonial_angle", 120) - 120) / 10))  # 120° is ideal
        symmetry_score = metrics.get("symmetry_score", 0.8) * 10
        midface_score = max(0, min(10, 10 - abs(metrics.get("midface_ratio", 0.5) - 0.5) * 20))
        
        composite = (
            beauty_score * 0.4 +
            canthal_score * 0.25 +
            gonial_score * 0.2 +
            symmetry_score * 0.1 +
            midface_score * 0.05
        )
        
        metrics["composite_rating"] = composite
        
        # Determine category
        if composite <= 3:
            category = "Sub-5"
        elif composite <= 4.5:
            category = "LTN"
        elif composite <= 6:
            category = "HTN"
        elif composite <= 7.5:
            category = "Chad-Lite"
        elif composite <= 8.5:
            category = "PSL-God-Candidate"
        else:
            category = "PSL-God"
        
        metrics["category"] = category
        
    except Exception as e:
        logger.error(f"Error extracting metrics: {e}")
        # Return default metrics on error
        metrics = {
            "beauty_avg": 50,
            "base_rating": 5.0,
            "composite_rating": 5.0,
            "category": "HTN",
            "canthal_tilt": 0,
            "gonial_angle": 120,
            "symmetry_score": 0.8
        }
    
    return metrics
