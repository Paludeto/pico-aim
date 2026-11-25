"""Deteccao do alvo: limiar de cor em HSV + maior contorno -> centroide."""
import numpy as np

try:
    import cv2
except ImportError:             # sem OpenCV: centroide da mascara inteira
    cv2 = None

# Magenta (255, 0, 255) em HSV do OpenCV: H = 150 (escala 0..179)
HSV_LO = (140, 120, 120)
HSV_HI = (165, 255, 255)
MIN_AREA = 80.0                 # px^2; descarta ruido


def detect_target(bgr: np.ndarray, lo=HSV_LO, hi=HSV_HI, min_area=MIN_AREA):
    """Retorna (cx, cy) em pixels da imagem, ou None se nao houver alvo."""
    if cv2 is None:
        b, g, r = (bgr[..., i].astype(np.int16) for i in range(3))
        mask = (r > 180) & (b > 180) & (g < 90)
        if mask.sum() < min_area:
            return None
        ys, xs = np.nonzero(mask)
        return float(xs.mean()), float(ys.mean())
    hsv = cv2.cvtColor(np.ascontiguousarray(bgr[..., :3]), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    m = cv2.moments(c)
    if m["m00"] < min_area:
        return None
    return m["m10"] / m["m00"], m["m01"] / m["m00"]
