import json
import re
from dataclasses import dataclass
from os import getenv
from threading import Lock

from raven_framework.helpers.open_ai_helper import OpenAiHelper
from raven_framework.peripherals.camera import Camera
from raven_framework.peripherals.microphone import Microphone
from raven_framework.peripherals.speaker import Speaker

from .session import Inventory


@dataclass(frozen=True)
class ScanResult:
    statuses: tuple[Inventory, ...] = ()
    label: str = ""
    error: str = ""


def demo_scan(count):
    return ScanResult(tuple(
        Inventory.NOT_VISIBLE if i == 7 else
        Inventory.UNCERTAIN if i in (5, 8) else Inventory.FOUND
        for i in range(count)
    ), "DEMO MODE · Sample inventory")


def normalize(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower().replace("’", "").replace("'", "")))


def parse_inventory(response, count):
    response = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", response.strip())
    result = json.loads(response)
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        raise ValueError("Invalid inventory response")
    status_map = {
        "found": Inventory.FOUND, "not_visible": Inventory.NOT_VISIBLE,
        "uncertain": Inventory.UNCERTAIN,
    }
    statuses = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid inventory item")
        index, status = item.get("id"), item.get("status")
        if type(index) is not int or not 0 <= index < count or index in statuses:
            raise ValueError("Invalid or duplicate inventory ID")
        if not isinstance(status, str) or status not in status_map:
            raise ValueError("Unknown inventory status")
        statuses[index] = status_map[status]
    if len(statuses) != count:
        raise ValueError("Incomplete inventory response")
    return tuple(statuses[i] for i in range(count))


class Services:
    def __init__(self, demo):
        self.demo = demo
        self.key = None if demo else getenv("OPENAI_API_KEY")
        self.app_id = getenv("RAVEN_APP_ID", "")
        self.app_key = getenv("RAVEN_APP_KEY", "")
        self.mic = self.speaker = None
        self.camera_lock = Lock()

    def helper(self):
        return OpenAiHelper(self.key, timeout=10, max_retries=0)

    def camera(self):
        return Camera(self.app_id, self.app_key)

    def scan(self, supplies):
        if not self.key:
            return ScanResult(error="The live vision model needs an OpenAI API key.")
        try:
            with self.camera_lock:
                camera = self.camera()
                try:
                    camera.open_camera()
                    frame = camera.capture_camera_image() if camera.is_camera_open() else None
                finally:
                    camera.close_camera()
        except Exception:
            return ScanResult(error="Raven could not access the camera.")
        if frame is None or not frame.size:
            return ScanResult(error="Raven did not receive a camera frame.")
        try:
            response = self.helper().process_multimodal_with_image(
                'Inspect only the visible workspace in this image. Return JSON with key "items" '
                'containing one object {"id": integer, "status": string} per checklist item. '
                'Use "found" for clearly identified supplies, "not_visible" when no matching item '
                'is visible in the frame, and "uncertain" for partial, obscured, or ambiguous matches. '
                'For grouped items, both components must be visible to mark found. '
                'Checklist: ' + json.dumps(dict(enumerate(supplies))),
                image=frame,
                model=getenv("NAIL_AR_VISION_MODEL") or getenv("NAILPILOT_VISION_MODEL", "gpt-4o"),
            )
            return ScanResult(parse_inventory(response, len(supplies)), "LIVE CAMERA SCAN")
        except Exception:
            return ScanResult(error="The vision model did not return a complete checklist.")

    def record(self):
        if self.mic is None:
            self.mic = Microphone(self.app_id, self.app_key)
        self.mic.start_recording()

    def stop_recording(self):
        return self.mic.stop_recording()

    def transcribe(self, wav):
        return self.helper().transcribe_audio(wav) if wav else ""

    def synthesize(self, message):
        return self.helper().generate_tts(message)

    def play(self, wav):
        if wav:
            if self.speaker is None:
                self.speaker = Speaker(self.app_id, self.app_key)
            self.speaker.stop_audio()
            self.speaker.play_audio(wav)
