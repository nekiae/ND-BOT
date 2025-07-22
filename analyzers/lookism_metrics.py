"""Lookism-specific facial metrics calculated from Face++ 83-point landmarks.

Indices follow Face++ landmark chart (0-82). Adjust if API changes.
This module only performs pure geometry; no API calls. All values are floats.
"""
from __future__ import annotations

from typing import Dict, Tuple
import math

# --- Basic helpers -----------------------------------------------------------

def get_point(landmarks: Dict, key: str) -> Tuple[float, float]:
    """Get landmark point coordinates."""
    try:
        point = landmarks[key]
        return (point['x'], point['y'])
    except (KeyError, TypeError):
        return (0.0, 0.0)

def compute_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Compute Euclidean distance between two points."""
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def compute_angle_3points(p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float]) -> float:
    """Compute angle at p2 formed by p1-p2-p3 in degrees."""
    v1 = (p1[0] - p2[0], p1[1] - p2[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])
    
    dot_product = v1[0] * v2[0] + v1[1] * v2[1]
    mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
    mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
    
    if mag1 == 0 or mag2 == 0:
        return 0
    
    cos_angle = dot_product / (mag1 * mag2)
    cos_angle = max(-1, min(1, cos_angle))
    return math.degrees(math.acos(cos_angle))

# --- Landmark index shortcuts (Face++ 83-pt) ----------------------------------
LANDMARK_INDICES = {
    'left_eye_outer': 'left_eye_left_corner',
    'left_eye_inner': 'left_eye_right_corner', 
    'right_eye_inner': 'right_eye_left_corner',
    'right_eye_outer': 'right_eye_right_corner',
    'left_pupil': 'left_eye_pupil',
    'right_pupil': 'right_eye_pupil',
    'nose_tip': 'nose_tip',
    'subnasale': 'nose_contour_lower_middle',
    'stomion': 'mouth_upper_lip_top',
    'menton': 'contour_chin',
    'glabella': 'left_eyebrow_upper_middle',  # approximate
    'trichion': 'contour_chin',  # will offset
    'gonion_left': 'contour_left9',
    'gonion_right': 'contour_right9',
    'zygion_left': 'contour_left7',
    'zygion_right': 'contour_right7'
}

# --- Metric calculations ------------------------------------------------------

def compute_canthal_tilt(landmarks: Dict) -> float:
    """Canthal tilt: atan2[(outer_canthus – inner_canthus).y / dx] → °"""
    try:
        # Left eye
        left_outer = get_point(landmarks, 'left_eye_left_corner')
        left_inner = get_point(landmarks, 'left_eye_right_corner')
        
        # Right eye  
        right_inner = get_point(landmarks, 'right_eye_left_corner')
        right_outer = get_point(landmarks, 'right_eye_right_corner')
        
        # Calculate tilt for each eye
        left_dx = left_outer[0] - left_inner[0]
        left_dy = left_outer[1] - left_inner[1]
        left_tilt = math.degrees(math.atan2(left_dy, left_dx)) if left_dx != 0 else 0
        
        right_dx = right_inner[0] - right_outer[0] 
        right_dy = right_inner[1] - right_outer[1]
        right_tilt = math.degrees(math.atan2(right_dy, right_dx)) if right_dx != 0 else 0
        
        return (left_tilt + right_tilt) / 2
    except Exception:
        return 0.0

def compute_interpupil_distance(landmarks: Dict) -> float:
    """IBI: dist(pupil_L, pupil_R)"""
    try:
        left_pupil = get_point(landmarks, 'left_eye_pupil')
        right_pupil = get_point(landmarks, 'right_eye_pupil')
        return compute_distance(left_pupil, right_pupil)
    except Exception:
        return 60.0

def compute_mid_face_ratio(landmarks: Dict) -> float:
    """Mid-face ratio: dist(subnasale, stomion) ÷ dist(glabella, menton)"""
    try:
        subnasale = get_point(landmarks, 'nose_contour_lower_middle')
        stomion = get_point(landmarks, 'mouth_upper_lip_top')
        glabella = get_point(landmarks, 'left_eyebrow_upper_middle')  # approximate
        menton = get_point(landmarks, 'contour_chin')
        
        mid_face_height = compute_distance(subnasale, stomion)
        total_face_height = compute_distance(glabella, menton)
        
        return mid_face_height / total_face_height if total_face_height > 0 else 0.65
    except Exception:
        return 0.65

def compute_gonial_angle(landmarks: Dict) -> float:
    """Gonial angle: ∠(jaw_left, gonion, ramus)"""
    try:
        jaw_left = get_point(landmarks, 'contour_left9')
        gonion = get_point(landmarks, 'contour_chin')
        jaw_right = get_point(landmarks, 'contour_right9')
        
        return compute_angle_3points(jaw_left, gonion, jaw_right)
    except Exception:
        return 120.0

def compute_bizygomatic_width(landmarks: Dict) -> float:
    """Bizygomatic width: dist(zygion_L, zygion_R)"""
    try:
        zygion_left = get_point(landmarks, 'contour_left7')
        zygion_right = get_point(landmarks, 'contour_right7')
        return compute_distance(zygion_left, zygion_right)
    except Exception:
        return 130.0

def compute_bigonial_width(landmarks: Dict) -> float:
    """Bigonial width: dist(gonion_L, gonion_R)"""
    try:
        gonion_left = get_point(landmarks, 'contour_left9')
        gonion_right = get_point(landmarks, 'contour_right9')
        return compute_distance(gonion_left, gonion_right)
    except Exception:
        return 110.0

def compute_facial_width_height_ratio(landmarks: Dict) -> float:
    """FWHR: bizygo ÷ height"""
    try:
        bizygo = compute_bizygomatic_width(landmarks)
        
        # Face height approximation
        top = get_point(landmarks, 'left_eyebrow_upper_middle')
        bottom = get_point(landmarks, 'contour_chin')
        height = compute_distance(top, bottom)
        
        return bizygo / height if height > 0 else 0.85
    except Exception:
        return 0.85

def compute_facial_thirds(landmarks: Dict) -> Tuple[float, float, float]:
    """Facial thirds: (trichion‑glabella, g–subnas, subnas–menton)"""
    try:
        # Approximate points
        chin = get_point(landmarks, 'contour_chin')
        trichion = (chin[0], chin[1] - 200)  # estimated hairline
        glabella = get_point(landmarks, 'left_eyebrow_upper_middle')
        subnasale = get_point(landmarks, 'nose_contour_lower_middle')
        menton = chin
        
        upper_third = compute_distance(trichion, glabella)
        middle_third = compute_distance(glabella, subnasale)
        lower_third = compute_distance(subnasale, menton)
        
        total = upper_third + middle_third + lower_third
        if total == 0:
            return (33.3, 33.3, 33.3)
        
        return (
            (upper_third / total) * 100,
            (middle_third / total) * 100,
            (lower_third / total) * 100
        )
    except Exception:
        return (33.3, 33.3, 33.3)

def compute_symmetry_score(landmarks: Dict) -> float:
    """Symmetry score: Σ asymmetries normalized"""
    try:
        center_x = get_point(landmarks, 'nose_tip')[0]
        
        symmetry_pairs = [
            ('left_eye_pupil', 'right_eye_pupil'),
            ('left_eyebrow_upper_middle', 'right_eyebrow_upper_middle'),
            ('mouth_left_corner', 'mouth_right_corner'),
            ('contour_left9', 'contour_right9')
        ]
        
        total_asymmetry = 0
        valid_pairs = 0
        
        for left_key, right_key in symmetry_pairs:
            try:
                left_point = get_point(landmarks, left_key)
                right_point = get_point(landmarks, right_key)
                
                left_dist = abs(left_point[0] - center_x)
                right_dist = abs(right_point[0] - center_x)
                
                if max(left_dist, right_dist) > 0:
                    asymmetry = abs(left_dist - right_dist) / max(left_dist, right_dist)
                    total_asymmetry += asymmetry
                    valid_pairs += 1
            except Exception:
                continue
        
        if valid_pairs == 0:
            return 0.8
        
        avg_asymmetry = total_asymmetry / valid_pairs
        return max(0, 1 - avg_asymmetry)
    except Exception:
        return 0.8

def compute_eye_whr(landmarks: Dict) -> float:
    """Eye WHR: avg(eye_h)/avg(eye_w)"""
    try:
        # Left eye dimensions
        left_width = compute_distance(
            get_point(landmarks, 'left_eye_left_corner'),
            get_point(landmarks, 'left_eye_right_corner')
        )
        left_height = compute_distance(
            get_point(landmarks, 'left_eye_upper_left_quarter'),
            get_point(landmarks, 'left_eye_lower_left_quarter')
        )
        
        # Right eye dimensions
        right_width = compute_distance(
            get_point(landmarks, 'right_eye_left_corner'),
            get_point(landmarks, 'right_eye_right_corner')
        )
        right_height = compute_distance(
            get_point(landmarks, 'right_eye_upper_right_quarter'),
            get_point(landmarks, 'right_eye_lower_right_quarter')
        )
        
        avg_width = (left_width + right_width) / 2
        avg_height = (left_height + right_height) / 2
        
        return avg_height / avg_width if avg_width > 0 else 0.33
    except Exception:
        return 0.33

def compute_lip_fullness(landmarks: Dict) -> float:
    """Lip fullness: vermillion_h ÷ bizygo"""
    try:
        upper_lip = get_point(landmarks, 'mouth_upper_lip_top')
        lower_lip = get_point(landmarks, 'mouth_lower_lip_bottom')
        lip_height = compute_distance(upper_lip, lower_lip)
        
        bizygo = compute_bizygomatic_width(landmarks)
        
        return lip_height / bizygo if bizygo > 0 else 0.12
    except Exception:
        return 0.12

def compute_jaw_prominence(landmarks: Dict) -> float:
    """Jaw prominence: bigonial ÷ bizygo"""
    try:
        bigonial = compute_bigonial_width(landmarks)
        bizygo = compute_bizygomatic_width(landmarks)
        
        return bigonial / bizygo if bizygo > 0 else 0.85
    except Exception:
        return 0.85

def compute_skin_score(face_data: Dict) -> float:
    """Skin score: 100 - (acne+stain)*0.5 - (100-health)"""
    try:
        skin_status = face_data.get('skinstatus', {})
        acne = skin_status.get('acne', 0)
        stain = skin_status.get('stain', 0) 
        health = skin_status.get('health', 80)
        
        score = 100 - (acne + stain) * 0.5 - (100 - health)
        return max(0, min(100, score))
    except Exception:
        return 75.0

def compute_overall_quality(face_data: Dict) -> float:
    """Overall quality: min(facequality, skin_score)"""
    try:
        face_quality = face_data.get('facequality', {}).get('value', 80)
        skin_score = compute_skin_score(face_data)
        return min(face_quality, skin_score)
    except Exception:
        return 75.0

def compute_all(front_data: Dict, profile_data: Dict) -> Dict:
    """Compute all looksmax metrics from Face++ data using both front and profile views."""
    if not front_data or 'landmark' not in front_data:
        return {}

    front_landmarks = front_data['landmark']
    profile_landmarks = profile_data.get('landmark') if profile_data else None

    # --- Metrics from Frontal View ---
    canthal_tilt = compute_canthal_tilt(front_landmarks)
    interpupil = compute_interpupil_distance(front_landmarks)
    mid_face_ratio = compute_mid_face_ratio(front_landmarks)
    bizygomatic_width = compute_bizygomatic_width(front_landmarks)
    bigonial_width = compute_bigonial_width(front_landmarks)
    fwhr = compute_facial_width_height_ratio(front_landmarks)
    thirds = compute_facial_thirds(front_landmarks)
    symmetry = compute_symmetry_score(front_landmarks)
    eye_whr = compute_eye_whr(front_landmarks)
    lip_fullness = compute_lip_fullness(front_landmarks)
    jaw_prominence = compute_jaw_prominence(front_landmarks)

    # --- Metrics from Profile View ---
    gonial_angle = compute_gonial_angle(profile_landmarks) if profile_landmarks else 'N/A'

    # --- Soft tissue & Beauty metrics (from primary front photo) ---
    skin_score = compute_skin_score(front_data)
    overall_quality = compute_overall_quality(front_data)
    beauty = front_data.get('beauty', {})
    beauty_male = beauty.get('male_score', 50)
    beauty_female = beauty.get('female_score', 50)
    beauty_avg = (beauty_male + beauty_female) / 2

    return {
        'canthal_tilt': canthal_tilt,
        'interpupil_distance': interpupil,
        'mid_face_ratio': mid_face_ratio,
        'gonial_angle': gonial_angle,
        'bizygomatic_width': bizygomatic_width,
        'bigonial_width': bigonial_width,
        'facial_width_height_ratio': fwhr,
        'facial_thirds': {
            'upper': thirds[0],
            'middle': thirds[1],
            'lower': thirds[2]
        },
        'symmetry_score': symmetry,
        'eye_whr': eye_whr,
        'lip_fullness': lip_fullness,
        'jaw_prominence': jaw_prominence,
        'skin_score': skin_score,
        'overall_quality': overall_quality,
        'beauty_male': beauty_male,
        'beauty_female': beauty_female,
        'beauty_avg': beauty_avg
    }
