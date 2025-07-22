import math
import numpy as np
from typing import Dict, Any, Optional

def calculate_distance(p1, p2): 
    return math.sqrt((p1['x'] - p2['x'])**2 + (p1['y'] - p2['y'])**2)

def calculate_angle(p1, p2, p3):
    v1 = (p1['x'] - p2['x'], p1['y'] - p2['y'])
    v2 = (p3['x'] - p2['x'], p3['y'] - p2['y'])
    dot_product = v1[0] * v2[0] + v1[1] * v2[1]
    mag_v1 = math.sqrt(v1[0]**2 + v1[1]**2)
    mag_v2 = math.sqrt(v2[0]**2 + v2[1]**2)
    if mag_v1 == 0 or mag_v2 == 0:
        return 0
    cosine_angle = dot_product / (mag_v1 * mag_v2)
    angle = math.degrees(math.acos(np.clip(cosine_angle, -1.0, 1.0)))
    return angle

def get_looksmax_metrics(face_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Вычисляет луксмакс-метрики на основе 83 точек лица от Face++.
    """
    if not face_data or 'landmark' not in face_data:
        return None

    lm = face_data['landmark']
    metrics = {}

    try:
        # Canthal Tilt
        left_medial_canthus = lm['left_eye_inner_corner']
        left_lateral_canthus = lm['left_eye_outer_corner']
        dx = left_lateral_canthus['x'] - left_medial_canthus['x']
        dy = left_medial_canthus['y'] - left_lateral_canthus['y'] # y is inverted
        metrics['canthal_tilt'] = round(math.degrees(math.atan2(dy, dx)), 2)

        # Gonial Angle
        # Points: left_jaw_lower, left_jaw_middle, left_ear_lower
        # Using contour points for a more robust calculation
        metrics['gonial_angle'] = round(calculate_angle(lm['contour_left9'], lm['contour_left7'], lm['contour_left5']), 2)

        # Bizygomatic Width
        metrics['bizygomatic_width'] = round(calculate_distance(lm['contour_left1'], lm['contour_right1']), 2)

        # Bigonial Width
        metrics['bigonial_width'] = round(calculate_distance(lm['contour_left7'], lm['contour_right7']), 2)

        # Facial Width-to-Height Ratio (FWHR)
        face_height = calculate_distance(lm['upper_lip_top'], lm['contour_chin'])
        if face_height > 0:
            metrics['fwhr'] = round(metrics['bizygomatic_width'] / face_height, 2)
        else:
            metrics['fwhr'] = 0

        # Mid-face Ratio
        total_face_height = calculate_distance(lm['hairline_left'], lm['contour_chin'])
        mid_face_height = calculate_distance(lm['left_eyebrow_upper_middle'], lm['nose_tip'])
        if total_face_height > 0:
            metrics['mid_face_ratio'] = round(mid_face_height / total_face_height, 2)
        else:
            metrics['mid_face_ratio'] = 0

        # Eye Separation Ratio (Interpupillary Distance)
        pupil_dist = calculate_distance(lm['left_eye_pupil'], lm['right_eye_pupil'])
        eye_width = calculate_distance(lm['left_eye_outer_corner'], lm['left_eye_inner_corner'])
        if eye_width > 0:
            metrics['eye_separation_ratio'] = round(pupil_dist / eye_width, 2)
        else:
            metrics['eye_separation_ratio'] = 0

        # Eye Aspect Ratio (Hunter vs Prey eyes)
        eye_height = calculate_distance(lm['left_eye_top'], lm['left_eye_bottom'])
        if eye_height > 0:
            metrics['eye_aspect_ratio'] = round(eye_width / eye_height, 2)
        else:
            metrics['eye_aspect_ratio'] = 0

        # Lip Fullness
        metrics['lip_fullness'] = round(calculate_distance(lm['upper_lip_bottom'], lm['lower_lip_top']), 2)

        # Add raw Face++ attributes
        attributes = face_data.get('attributes', {})
        metrics['skin_quality'] = attributes.get('skinstatus', {}).get('health', 0)
        metrics['headpose'] = attributes.get('headpose', {})

    except (KeyError, TypeError) as e:
        print(f"Ошибка при расчете метрик: {e}")
        return None

    return metrics
