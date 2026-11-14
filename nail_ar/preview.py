from math import hypot
from queue import Empty, SimpleQueue
from threading import Event

import cv2
import numpy as np


class NailTracker:
    """Track one centered nail inside camera image coordinates."""

    def __init__(self):
        self.anchor = None
        self.template = None
        self.box = None
        self.assisted = False

    def locate(self, gray, center):
        height, width = gray.shape
        cx, cy = center
        extent = min(width, height) // 4
        x, y = max(0, cx - extent), max(0, cy - extent)
        crop = gray[y:cy + extent, x:cx + extent]
        smoothed = cv2.GaussianBlur(crop, (5, 5), 0)
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(smoothed)
        edges = cv2.Canny(enhanced, 26, 78)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        matches = []
        for contour in contours:
            if len(contour) < 12 or cv2.contourArea(contour) < extent ** 2 * .055:
                continue
            (dx, dy), axes, angle = cv2.fitEllipse(contour)
            short, long = sorted(axes)
            distance = hypot(dx + x - cx, dy + y - cy)
            if not (extent * .28 < short <= long < extent * 1.8 and long / short <= 2.5):
                continue
            fill = cv2.contourArea(contour) / (np.pi * axes[0] * axes[1] / 4)
            if .65 < fill < 1.2 and distance < extent * .55:
                matches.append((distance, ((dx + x, dy + y), axes, angle)))
        return min(matches, key=lambda item: item[0])[1] if matches else None

    def acquire(self, gray, guide):
        center, axes, _ = guide
        self.assisted = True
        contour = self.locate(gray, center)
        if contour is not None:
            location, candidate_axes, _ = contour
            if (hypot(location[0] - center[0], location[1] - center[1]) < axes[0] * .22
                    and all(.65 < measured / expected < 1.35
                            for measured, expected in zip(sorted(candidate_axes), sorted(axes)))):
                guide = contour
        return self.store(gray, guide)

    def store(self, gray, region):
        (cx, cy), axes, _ = region
        radius = max(8, int(max(axes) * .70))
        x, y = max(0, int(cx) - radius), max(0, int(cy) - radius)
        sample = gray[y:int(cy) + radius, x:int(cx) + radius]
        if sample.size == 0 or sample.std() < 5:
            self.box = self.template = None
            return None
        self.template = sample.copy()
        self.anchor = (x, y)
        self.box = region
        return region

    def update(self, gray):
        if self.template is None:
            return None
        x, y = self.anchor
        h, w = self.template.shape
        pad = min(gray.shape) // 8
        left, top = max(0, x - pad), max(0, y - pad)
        search = gray[top:y + h + pad, left:x + w + pad]
        scores = cv2.matchTemplate(search, self.template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
        if score < .72:
            self.box = self.template = None
            return None
        new_x, new_y = left + dx, top + dy
        (cx, cy), axes, angle = self.box
        self.box = ((round(cx + new_x - x), round(cy + new_y - y)), axes, angle)
        self.anchor = (new_x, new_y)
        return self.box


def nail_guide(shape, size):
    height, width = shape[:2]
    breadth = max(16, round(min(width, height) * size))
    return (width // 2, height // 2), (breadth, round(breadth * 1.5)), 0


def draw_guide(frame, guide):
    output = frame.copy()
    center, axes, angle = guide
    cv2.ellipse(output, center, tuple(v // 2 for v in axes), angle,
                0, 360, (220, 205, 250), 2, cv2.LINE_AA)
    cv2.drawMarker(output, center, (220, 205, 250), cv2.MARKER_CROSS, 16, 1, cv2.LINE_AA)
    return output


def composite(frame, design, region):
    overlay = frame.copy()
    if region is None:
        h, w = overlay.shape[:2]
        cv2.drawMarker(overlay, (w // 2, h // 2), (220, 205, 250),
                       cv2.MARKER_CROSS, 34, 1, cv2.LINE_AA)
        return overlay

    (x, y), (width, height), angle = region
    center = (round(x), round(y))
    axes = (round(width / 2), round(height / 2))
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.ellipse(mask, center, axes, angle, 0, 360, 255, -1, cv2.LINE_AA)
    color = tuple(int(design.color[i:i + 2], 16) for i in (5, 3, 1))
    cv2.ellipse(overlay, center, axes, angle, 0, 360, color, -1, cv2.LINE_AA)
    radius = max(2, round(min(axes) * .15))
    white = (240, 245, 255)
    if design.name == "Daisy Dreams":
        for petal in range(5):
            phase = petal * 2 * np.pi / 5
            dot = (round(x + radius * 2 * np.cos(phase)), round(y + radius * 2 * np.sin(phase)))
            cv2.circle(overlay, dot, radius, white, -1, cv2.LINE_AA)
        cv2.circle(overlay, center, radius, (105, 218, 255), -1, cv2.LINE_AA)
    elif design.name == "Classic French":
        contour = cv2.ellipse2Poly(center, axes, round(angle), 210, 330, 3)
        cv2.polylines(overlay, [contour], False, white, radius * 2, cv2.LINE_AA)
    else:
        cv2.drawMarker(overlay, center, white, cv2.MARKER_STAR, radius * 5, 1, cv2.LINE_AA)
    blended = cv2.addWeighted(frame, .43, overlay, .57, 0)
    output = np.where(mask[..., None] > 0, blended, frame)
    cv2.ellipse(output, center, axes, angle, 0, 360, white, 1, cv2.LINE_AA)
    return output


class CameraPreview:
    def __init__(self, services, design):
        self.services, self.design = services, design
        self.stop = Event()
        self.actions = SimpleQueue()
        self.latest = None
        self.status = "Opening Raven camera…"

    def run(self):
        with self.services.camera_lock:
            if self.stop.is_set():
                return
            camera = None
            try:
                camera = self.services.camera()
                camera.open_camera()
                if not camera.is_camera_open():
                    self.status = "Camera unavailable. Back returns to the nail guide."
                    return
                tracker = NailTracker()
                misses = 0
                size = .19
                while not self.stop.is_set():
                    frame = camera.capture_camera_image()
                    if frame is None or not frame.size:
                        misses += 1
                        if misses >= 5:
                            self.status = "Camera frames unavailable. Use the nail guide."
                            return
                    else:
                        misses = 0
                        scale = min(1, 640 / max(frame.shape[:2]))
                        frame = cv2.resize(frame, None, fx=scale, fy=scale)
                        try:
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            lock = False
                            while True:
                                try:
                                    action = self.actions.get_nowait()
                                except Empty:
                                    break
                                if action == "lock":
                                    lock = True
                                else:
                                    size = min(.32, max(.10, size + action))
                                    tracker = NailTracker()
                                    lock = False
                            guide = nail_guide(frame.shape, size)
                            if lock:
                                region = tracker.acquire(gray, guide)
                            else:
                                region = tracker.update(gray) if tracker.assisted else None
                            if region:
                                rendered = composite(frame, self.design, region)
                                status = "Tracking the selected area · move slowly."
                            else:
                                rendered = draw_guide(frame, guide)
                                status = ("Tracking lost · align and Lock Nail again."
                                          if tracker.assisted else "Align your nail with the outline, then select Lock Nail.")
                        except (cv2.error, ValueError):
                            tracker = NailTracker()
                            rendered, status = frame, "Tracking lost · reposition your hand."
                        self.latest = (rendered, status)
                    self.stop.wait(.07)
            except Exception:
                self.status = "Camera unavailable. Back returns to the nail guide."
            finally:
                if camera is not None:
                    camera.close_camera()
