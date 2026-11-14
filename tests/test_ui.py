import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from raven_framework import Button

from nail_ar.app import NailAR
from nail_ar.session import Screen
from test_session import FakeClock


class SimulatorUITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.storage = TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        self.clock = FakeClock()
        self.app = NailAR(demo=True, seconds=15,
                             save_path=Path(self.storage.name) / "game.json", clock=self.clock)
        self.app.show()
        self.screens = set()

    def tearDown(self):
        self.app.pulse.stop()
        self.app.shutdown()
        self.app.executor.shutdown(wait=True)
        self.app.close()
        self.app.deleteLater()
        self.qt.processEvents()

    def check_viewport(self):
        page = self.app.page
        self.screens.add(self.app.model.screen)
        self.assertEqual(page.size(), self.app.app.size())
        for child in page.children():
            if isinstance(child, (Button, QLabel)) and child.isVisible():
                self.assertTrue(page.rect().contains(child.geometry()), child.accessibleName())
                if isinstance(child, QLabel) and child.text():
                    bounds = child.fontMetrics().boundingRect(
                        child.rect(), Qt.TextFlag.TextWordWrap, child.text()
                    )
                    self.assertLessEqual(bounds.height(), child.height(), child.text())

    def click(self, name):
        self.check_viewport()
        matches = [widget for widget in self.app.page.findChildren(Button)
                   if widget.accessibleName() == name and widget.isVisible()]
        self.assertTrue(matches, f"{name} on {self.app.model.screen}")
        QTest.mouseClick(matches[0], Qt.MouseButton.LeftButton)
        self.qt.processEvents()

    def voice(self, text):
        self.app.open_command()
        QTest.keyClicks(self.app.command, text)
        QTest.keyClick(self.app.command, Qt.Key.Key_Return)
        self.qt.processEvents()

    def test_complete_offline_demo(self):
        model = self.app.model
        self.click("Let’s do nails")
        self.click("Back")
        self.click("Let’s do nails")
        for name in ("Starry Night", "Classic French", "Daisy Dreams"):
            self.click(name)
            self.assertEqual(model.design.name, name)
            if name != "Daisy Dreams":
                self.click("Back")
        self.click("Continue")
        self.click("Back")
        self.click("Continue")
        self.click("Demo Mode")
        self.assertIn("DEMO MODE", model.scan_label)
        self.click("Continue with Gaps")
        self.click("Back")
        self.click("More")
        self.click("Confirm")
        self.voice("Confirm top coat")
        self.click("Continue")
        self.assertIs(model.screen, Screen.TUTORIAL)
        self.click("Repeat")
        self.assertEqual(self.app.notice, "Instruction repeated")
        self.voice("Pause")
        self.voice("Resume")
        self.click("Skip")
        self.click("Back")
        self.assertEqual(model.step_index, 0)
        camera = Mock()
        camera.is_camera_open.return_value = False
        self.app.services.camera = Mock(return_value=camera)
        self.click("Camera Preview")
        for _ in range(100):
            if "unavailable" in self.app.preview_caption.text():
                break
            QTest.qWait(20)
        self.assertIn("unavailable", self.app.preview_caption.text())
        self.click("Back to Guide")
        while not model.step.drying:
            self.click("Next")
        self.click("Drying Options")
        self.click("Back")
        self.click("Drying Options")
        self.click("01:00")
        self.assertEqual(model.duration, 60)
        self.click("00:15")
        self.click("Start Timer")
        deadline = model.deadline
        self.click("Play Sudoku")
        self.click("Box 1")
        self.click("Row 1, column 3")
        self.click("9")
        self.click("Check Board")
        self.assertEqual(model.game.errors, {2})
        self.click("Erase")
        self.voice("enter four")
        self.click("Back")
        self.click("Skip Wait")
        self.assertEqual(model.deadline, deadline)
        self.click("Next")
        self.click("Drying Options")
        self.click("Continue")
        self.voice("open Sudoku")
        self.assertEqual(model.game.cells[2], 4)
        self.assertEqual(model.game.selected, 2)
        self.clock.now += 16
        self.app.refresh()
        self.assertTrue(self.app.timer_finished)
        self.assertIs(model.screen, Screen.SUDOKU)
        self.click("Back")
        while model.screen is Screen.TUTORIAL:
            self.click("Next")
        self.assertIs(model.screen, Screen.FINISH)
        self.click("Start Another Design")
        self.assertIs(model.screen, Screen.DESIGN_SELECTION)
        self.assertEqual(self.screens, set(Screen))

    def test_layout_adapts_to_full_display(self):
        self.app.app.setFixedSize(720, 720)
        self.app.draw()
        self.test_complete_offline_demo()
        self.assertEqual(self.app.page.width(), 720)
