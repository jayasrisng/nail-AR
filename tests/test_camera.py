from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from nail_ar.designs import DESIGNS
from nail_ar.preview import CameraPreview, NailTracker, composite, nail_guide
from nail_ar.services import Services, demo_scan, parse_inventory
from nail_ar.session import Inventory


class CameraTests(TestCase):
    def fake_services(self, frame):
        services = Services(demo=True)
        services.key = "test-key"
        camera = Mock()
        camera.is_camera_open.return_value = True
        camera.capture_camera_image.return_value = frame
        services.camera = Mock(return_value=camera)
        return services, camera

    def test_live_scan_passes_exact_camera_frame_to_model(self):
        frame = np.zeros((90, 120, 3), dtype=np.uint8)
        frame[35:60, 30:100] = (20, 130, 200)
        services, camera = self.fake_services(frame)
        client = Mock()
        services.helper = Mock(return_value=client)
        client.process_multimodal_with_image.return_value = (
            '{"items":[{"id":2,"status":"not_visible"},{"id":0,"status":"found"},'
            '{"id":1,"status":"uncertain"}]}'
        )
        result = services.scan(("File", "Bowl", "Base coat"))
        self.assertEqual(result.statuses, (Inventory.FOUND, Inventory.UNCERTAIN, Inventory.NOT_VISIBLE))
        self.assertEqual(result.label, "LIVE CAMERA SCAN")
        self.assertIs(client.process_multimodal_with_image.call_args.kwargs["image"], frame)
        camera.open_camera.assert_called_once()
        camera.capture_camera_image.assert_called_once()
        camera.close_camera.assert_called_once()

    def test_invalid_provider_response_and_camera_failure_are_not_samples(self):
        services, _ = self.fake_services(None)
        services.helper = Mock()
        result = services.scan(("File",))
        self.assertTrue(result.error)
        self.assertFalse(result.statuses)
        services.helper.assert_not_called()
        self.assertIn("DEMO MODE", demo_scan(1).label)
        for response in ('{}', '{"items":[]}', '{"items":[{"id":0,"status":"missing"}]}'):
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_inventory(response, 1)

    def test_preview_handles_failure_and_releases_camera(self):
        services, camera = self.fake_services(None)
        camera.is_camera_open.return_value = False
        preview = CameraPreview(services, DESIGNS[0])
        preview.run()
        self.assertIn("Camera unavailable", preview.status)
        camera.close_camera.assert_called_once()

    def test_tracker_follows_synthetic_nail_and_clips_overlay(self):
        tracker = NailTracker()
        for dx, dy in ((0, 0), (14, -8), (28, -16)):
            gray = np.zeros((240, 320), np.uint8)
            cv2.ellipse(gray, (160 + dx, 120 + dy), (24, 36), 0, 0, 360, 180, -1)
            region = tracker.acquire(gray, nail_guide(gray.shape, .2)) if dx == dy == 0 else tracker.update(gray)
            self.assertIsNotNone(region)
            self.assertLess(abs(region[0][0] - 160 - dx), 3)
            frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            output = composite(frame, DESIGNS[0], region)
            self.assertFalse(np.array_equal(frame, output))
            self.assertTrue(np.array_equal(frame[0], output[0]))
        self.assertIsNone(tracker.update(np.zeros_like(gray)))
        self.assertIsNone(tracker.update(gray))
        self.assertIsNone(tracker.acquire(np.zeros_like(gray), nail_guide(gray.shape, .2)))

    def test_tracking_exception_keeps_camera_preview_available(self):
        frame = np.zeros((90, 120, 3), np.uint8)
        services, camera = self.fake_services(frame)
        preview = CameraPreview(services, DESIGNS[2])

        def get_frame():
            preview.stop.set()
            return frame
        camera.capture_camera_image.side_effect = get_frame
        preview.actions.put("lock")
        with patch.object(NailTracker, "acquire", side_effect=cv2.error("bad tracking")):
            preview.run()
        self.assertIn("Tracking lost", preview.latest[1])
        camera.close_camera.assert_called_once()
