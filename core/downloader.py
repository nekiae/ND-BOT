import cv2
import numpy as np

async def download_photo(photo_bytes: bytes, local_path: str):
    """Saves photo with quality enhancement."""
    nparr = np.frombuffer(photo_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("Could not decode image from bytes.")

    h, w = img.shape[:2]
    if min(h, w) < 400:
        scale = 400 / min(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    cv2.imwrite(local_path, img, [cv2.IMWRITE_JPEG_QUALITY, 90])
