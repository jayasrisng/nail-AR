from concurrent.futures import ThreadPoolExecutor
from functools import partial
from os import getenv
import re
import subprocess
import sys
from time import monotonic

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QWidget
from raven_framework import Button, RavenApp
from raven_framework.helpers.font_utils import create_font

from .board import SudokuBoard
from .designs import DESIGNS
from .illustrations import NailArt, Sparkles
from .preview import CameraPreview
from .services import ScanResult, Services, demo_scan, normalize
from .session import Inventory, Screen, Session
from .sudoku import box_cells, box_for, default_path

CREAM = "#fff3ec"
PINK = "#ffc3dd"
LILAC = "#d9c9ff"
MUTED = "#c8b6cc"

WELCOME_LINE = "Let's do your nails! What are we creating today?"
CHOICE_LINE = "Beautiful choice! Let's make sure you have everything."
SCAN_LINE = "Before we start, let's check your nail station. Look at your supplies."
READY_LINE = "Perfect! Everything's ready. You won't need to get up halfway through!"
DONE_LINE = "Beautiful work! Your manicure is complete!"
COMPLETE_LINE = "Timer ended. Check your product directions."

# The composition grid is unitless and scales to the SDK application area.
GRID = 640


def time_text(seconds):
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class NailAR(RavenApp):
    def __init__(self, demo=False, seconds=900, narrate=False, save_path=None, clock=None):
        super().__init__()
        QApplication.setApplicationDisplayName("Nail AR")
        QTimer.singleShot(0, self.set_window_title)
        self.demo = demo
        self.narrate = narrate
        self.model = Session(seconds, clock=clock or monotonic, save_path=save_path or default_path())
        self.services = Services(demo)
        self.executor = ThreadPoolExecutor(max_workers=3)
        self.pending = []
        self.page = None
        self.countdown = self.sparkles = None
        self.scanning = self.recording = self.transcribing = False
        self.scan_error = ""
        self.inventory_page = 0
        self.preview = None
        self.preview_picture = self.preview_caption = None
        self.last_preview_frame = None
        self.timer_badge = None
        self.timer_finished = False
        self.last_save = self.model.clock()
        self.check_errors = False
        self.sudoku_overview = True
        self.notice = ""
        self.speech_version = 0
        self.local_speech = None
        self.set_app_background_color("#000000")

        self.command = QLineEdit(self.app)
        self.command.setGeometry(self.geometry_for(28, 536, 584, 54))
        self.command.setPlaceholderText("Type a voice command and press Enter")
        self.command.setStyleSheet(
            "QLineEdit {background:#2e2039;color:#fff3ec;border:2px solid #ffc3dd;"
            "border-radius:12px;padding:10px;font-size:21px;}"
        )
        self.command.hide()
        self.shortcuts = []
        for key, callback in (
            ("/", self.open_command), ("Esc", self.close_command),
            ("F2", partial(self.intent, "Next")),
            ("F3", partial(self.intent, "Go back")),
            ("F4", partial(self.intent, "Repeat")),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.pulse = QTimer(self)
        self.pulse.timeout.connect(self.refresh)
        self.pulse.start(100)
        self.destroyed.connect(partial(self.executor.shutdown, wait=False, cancel_futures=True))
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.draw()

    def set_window_title(self):
        self.window().setWindowTitle("Nail AR")

    def open_command(self):
        self.command.setGeometry(self.geometry_for(28, 536, 584, 54))
        # Install after Raven's global Enter filter so typing commands never toggles sleep.
        QApplication.instance().installEventFilter(self)
        self.command.show()
        self.command.raise_()
        self.command.setFocus()

    def eventFilter(self, obj, event):
        if (obj is self.command and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)):
            self.submit_command()
            return True
        return super().eventFilter(obj, event)

    def close_command(self):
        QApplication.instance().removeEventFilter(self)
        self.command.clear()
        self.command.hide()
        self.setFocus()

    def submit_command(self):
        phrase = self.command.text()
        self.close_command()
        self.intent(phrase)

    def geometry_for(self, x, y, w, h):
        sx, sy = self.app.width() / GRID, self.app.height() / GRID
        return QRect(round(x * sx), round(y * sy), round(w * sx), round(h * sy))

    def font_size(self, size):
        return round(size * min(self.app.width(), self.app.height()) / GRID)

    def place(self, widget, x, y, w, h):
        widget.setParent(self.page)
        widget.setGeometry(self.geometry_for(x, y, w, h))
        widget.show()
        return widget

    def label(self, content, x, y, w, h, size=22, color=CREAM, *, bold=False, center=False):
        label = QLabel(content)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        font = create_font("inter", size, "bold" if bold else "normal")
        font.setPixelSize(self.font_size(size))
        label.setFont(font)
        label.setStyleSheet(f"color:{color}; background:transparent;")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter |
                           (Qt.AlignmentFlag.AlignHCenter if center else Qt.AlignmentFlag.AlignLeft))
        return self.place(label, x, y, w, h)

    def button(self, title, callback, x, y, w, h=56, *, primary=False, active=False,
               enabled=True, size=20, content=None, transparent=False):
        size_px = self.geometry_for(0, 0, w, h).size()
        button = Button(
            center_text=title, width=size_px.width(), height=size_px.height(),
            text_size=self.font_size(size), content_widget=content,
            text_color=PINK if primary else CREAM, font_weight="bold", font="inter", corner_radius=16,
            background_color="transparent" if transparent else "#392238" if primary else "#221a2e",
            outline_color=PINK if primary or active else LILAC, outline_width=2,
            dwell_background_outline_color=("transparent" if transparent else
                                            "#e8acd1" if primary or active else "#685375"),
            scale_by=0, disabled=not enabled, use_gradient_border=False,
            enable_quad_dwell=True, use_fill_dwell=False,
        )
        button.setFixedSize(size_px)
        button.setAccessibleName(title or (content.accessibleName() if content else ""))
        button.on_clicked(callback)
        return self.place(button, x, y, w, h)

    def header(self, section, title, subtitle=None):
        self.label(section, 28, 15, 584, 28, 17, LILAC, bold=True)
        self.label(title, 28, 49, 584, 66, 42, bold=True)
        if subtitle:
            self.label(subtitle, 28, 115, 584, 50, 21, MUTED)

    def footer(self):
        if self.services.key:
            voice = "Stop listening" if self.recording else "Transcribing…" if self.transcribing else "Voice command"
            self.button(voice, self.toggle_voice, 416, 594, 196, 42, size=16,
                        enabled=not self.transcribing)
        status = self.notice or ("Demo Mode · sample inventory" if self.demo else "")
        if self.model.game.save_error and self.model.screen is Screen.SUDOKU:
            status = "Sudoku progress could not be saved."
        self.label(status, 28, 595, 376 if self.services.key else 584, 39, 18, MUTED)
        self.timer_badge = self.label("", 381, 12, 231, 29, 18, PINK)
        self.timer_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.update_timer_badge()

    def update_timer_badge(self):
        model = self.model
        if model.deadline is not None:
            status = time_text(model.remaining) + "  timer"
        elif model.paused_time is not None:
            status = time_text(model.remaining) + "  paused"
        elif self.timer_finished:
            status = "Timer ended"
        else:
            status = ""
        self.timer_badge.setText(status)

    def draw(self):
        if self.model.screen is not Screen.PREVIEW:
            self.stop_preview()
        if self.page:
            self.page.hide()
            self.page.deleteLater()
        self.countdown = self.sparkles = None
        self.page = QWidget()
        self.page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.page.setObjectName("nail-ar-page")
        self.page.setStyleSheet("QWidget#nail-ar-page {background-color:#000000;}")
        self.app.add(self.page, 0, 0)
        self.page.setFixedSize(self.app.size())
        render = {
            Screen.WELCOME: self.welcome, Screen.DESIGN_SELECTION: self.design_selection,
            Screen.DESIGN_CONFIRMATION: self.design_confirmation, Screen.SUPPLY_SCAN: self.supply_scan,
            Screen.SUPPLY_CONFIRMATION: self.supply_confirmation, Screen.TUTORIAL: self.tutorial,
            Screen.INVENTORY_OVERRIDE: self.inventory_override, Screen.PREVIEW: self.preview_screen,
            Screen.DRYING: self.drying, Screen.SUDOKU: self.sudoku,
            Screen.FINISH: self.finish,
        }[self.model.screen]
        render()
        self.footer()
        self.page.show()
        if self.command.isVisible():
            self.command.raise_()

    def act(self, action, message=None):
        self.notice = ""
        action()
        self.draw()
        if message:
            self.say(message)

    def say(self, message):
        self.speech_version += 1
        version = self.speech_version
        if not self.narrate or self.recording:
            return
        if self.services.key:
            self.background(self.services.synthesize, partial(self.play_narration, version, message), message)
        else:
            self.speak_locally(message)

    def play_narration(self, version, message, wav):
        if self.speech_version == version and not self.recording:
            if wav:
                self.services.play(wav)
            else:
                self.speak_locally(message)

    def speak_locally(self, message):
        if sys.platform == "darwin":
            if self.local_speech and self.local_speech.poll() is None:
                self.local_speech.terminate()
            try:
                self.local_speech = subprocess.Popen(
                    ["/usr/bin/say", "--", message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass

    def background(self, work, callback, *args):
        self.pending.append((self.executor.submit(work, *args), callback))

    def refresh(self):
        if self.model.tick():
            self.timer_finished = True
            if self.model.screen is Screen.DRYING:
                self.draw()
            self.say(COMPLETE_LINE)
        self.update_timer_badge()
        if self.countdown:
            self.refresh_countdown()
        if self.sparkles:
            self.sparkles.phase += .18
            self.sparkles.update()
        if self.model.screen is Screen.SUDOKU and self.model.clock() - self.last_save >= 2:
            self.model.game.save()
            self.last_save = self.model.clock()
        if self.model.screen is Screen.PREVIEW:
            self.refresh_preview()
        for future, callback in self.pending[:]:
            if future.done():
                self.pending.remove((future, callback))
                try:
                    result = future.result()
                except Exception:
                    result = None
                callback(result)

    def welcome(self):
        self.label("NAIL AR", 28, 35, 584, 74, 57, PINK, bold=True, center=True)
        self.label("Your personal nail studio.", 28, 116, 584, 38, 27, CREAM, center=True)
        self.place(NailArt(DESIGNS[0], trio=True), 132, 164, 376, 260)
        self.label("Nailed it. Built for Raven Prism.", 28, 430, 584, 52, 24, LILAC, center=True)
        self.button("Let’s do nails", partial(self.act, self.model.start, WELCOME_LINE),
                    140, 503, 360, 70, primary=True, size=26)

    def design_selection(self):
        self.header("NAIL AR / DESIGN", "What are we creating?")
        for i, design in enumerate(DESIGNS):
            y = 123 + i * 137
            card = QWidget()
            card.setAccessibleName(design.name)
            card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            art = NailArt(design, trio=True)
            art.setParent(card)
            art.setGeometry(self.geometry_for(9, 1, 163, 112))
            for content, y_offset, size, color in (
                (design.name, 23, 30, CREAM), (f"{design.difficulty}  ·  {design.duration}", 68, 20, LILAC),
            ):
                label = QLabel(content, card)
                label.setGeometry(self.geometry_for(182, y_offset, 362, 36))
                label.setStyleSheet(f"color:{color};font-size:{self.font_size(size)}px; background:transparent;")
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.button("", partial(self.act, partial(self.model.choose, i), CHOICE_LINE),
                        28, y, 584, 117, content=card)
        self.button("Back", partial(self.navigate, self.model.back), 28, 536, 155, 52)

    def design_confirmation(self):
        design = self.model.design
        self.header("NAIL AR / DESIGN", design.name, f"{design.difficulty}  ·  {design.duration}")
        self.place(NailArt(design, trio=True), 65, 168, 510, 322)
        self.button("Back", partial(self.act, self.model.change_design), 28, 516, 248)
        self.button("Continue", partial(self.act, self.model.prepare, SCAN_LINE), 292, 516, 320, primary=True)

    def supply_scan(self):
        self.header("NAIL AR / PREP", "Check your nail station",
                    "Look at your supplies, then choose a scan.")
        self.place(NailArt(self.model.design, "base", trio=True), 134, 159, 372, 207)
        if self.scan_error or not self.services.key:
            reason = self.scan_error or ("Sample inventory selected." if self.demo else "Live scan needs a configured vision model.")
            self.label("Demo Mode available · " + reason, 28, 359, 584, 55, 20, PINK)
        self.button(f"Optional soak: {'On' if self.model.soak else 'Off'}",
                    self.toggle_soak, 28, 426, 231, enabled=not self.scanning)
        title = "Scanning…" if self.scanning else "Scan Workspace"
        if self.services.key:
            self.button(title, self.scan, 282, 426, 330, primary=True, enabled=not self.scanning)
        self.button("Back", partial(self.navigate, self.model.back), 28, 506, 124)
        self.button("Skip Scan", self.request_override, 163, 506, 171)
        if self.demo or self.scan_error or not self.services.key:
            self.button("Demo Mode", self.run_demo_scan, 347, 506, 265, primary=True)

    def toggle_soak(self):
        self.model.soak = not self.model.soak
        self.model.inventory = []
        self.draw()

    def scan(self):
        if self.scanning or not self.services.key:
            return
        self.notice = self.scan_error = ""
        self.model.screen = Screen.SUPPLY_SCAN
        self.scanning = True
        self.draw()
        self.background(self.services.scan, partial(self.scan_finished, self.model.design, self.model.supplies),
                        self.model.supplies)

    def scan_finished(self, design, supplies, result):
        self.scanning = False
        if (self.model.screen is not Screen.SUPPLY_SCAN or self.model.design is not design
                or self.model.supplies != supplies):
            self.draw()
            return
        result = result or ScanResult(error="The live scan could not be completed.")
        if result.error:
            self.scan_error = result.error
            self.draw()
        else:
            self.apply_scan(result)

    def run_demo_scan(self):
        self.apply_scan(demo_scan(len(self.model.supplies)))

    def apply_scan(self, result):
        self.inventory_page = 0
        self.model.apply_scan(result.statuses, result.label)
        self.draw()
        if self.model.ready:
            self.say("Your supply checklist is ready.")
        else:
            self.say("Check each unverified supply, rescan, or continue with gaps.")

    def supply_confirmation(self):
        model = self.model
        self.header(model.scan_label, "Review your supplies",
                    "The scan reports what it can verify in this view.")
        offset = self.inventory_page * 3
        for i, status in enumerate(model.inventory[offset:offset + 3], offset):
            y = 166 + (i - offset) * 84
            self.label(model.supplies[i], 28, y, 356, 44, 23)
            caption = "Sample found" if status is Inventory.FOUND and model.scan_label.startswith("DEMO") else status.value
            self.label(caption, 28, y + 43, 356, 26, 19, LILAC)
            if status in (Inventory.UNCERTAIN, Inventory.NOT_VISIBLE):
                self.button("Confirm", partial(self.act, partial(model.confirm, i)), 417, y + 5, 195, 63)
        pages = (len(model.inventory) + 2) // 3
        self.button("Previous", partial(self.inventory_flip, -1), 28, 426, 149,
                    enabled=self.inventory_page > 0)
        self.label(f"{self.inventory_page + 1} / {pages}", 185, 426, 58, 56, 19, MUTED, center=True)
        self.button("More", partial(self.inventory_flip, 1), 250, 426, 100,
                    enabled=self.inventory_page + 1 < pages)
        self.button("Rescan" if self.services.key else "Back to Scan",
                    self.scan if self.services.key else partial(self.navigate, model.back), 365, 426, 247)
        self.button("Back", partial(self.navigate, model.back), 28, 516, 132)
        if model.ready:
            self.button("Continue", partial(self.act, model.begin, READY_LINE),
                        180, 516, 432, primary=True)
        else:
            self.button("Continue with Gaps", self.request_override, 180, 516, 432)

    def inventory_flip(self, direction):
        self.inventory_page += direction
        self.draw()

    def request_override(self):
        self.model.screen = Screen.INVENTORY_OVERRIDE
        self.draw()

    def inventory_override(self):
        self.header("NAIL AR / PREP", "Continue with gaps?")
        self.label("Some supplies are unverified. Skip any tutorial steps you can’t complete.",
                   28, 160, 584, 120, 28, MUTED)
        self.button("Back", partial(self.navigate, self.model.back), 28, 509, 150, 64)
        self.button("Begin Anyway", partial(self.navigate, partial(self.model.begin, True)),
                    205, 509, 407, 64, primary=True)

    def tutorial(self):
        model = self.model
        step = model.step
        self.header(f"{model.design.name.upper()} / STEP {model.step_index + 1} OF {len(model.steps)}",
                    "Tutorial paused" if model.paused else step.title)
        self.label(step.instruction, 28, 115, 584, 76, 26, MUTED)
        self.place(NailArt(model.design, step.art, step.stage), 40, 194, 387, 284)
        self.button("Camera Preview", self.open_preview, 420, 210, 192, 63, size=18)
        self.button("Drying Options" if step.drying else "Open Sudoku",
                    partial(self.navigate, model.drying_options) if step.drying else self.open_sudoku,
                    420, 288, 192, 63, size=18)
        if model.paused:
            self.button("Resume", partial(self.intent, "resume"), 420, 366, 192, 63)
        self.button("Back", partial(self.navigate, model.back), 28, 519, 134, 62)
        self.button("Repeat", partial(self.intent, "repeat"), 174, 519, 134, 62)
        self.button("Skip", partial(self.navigate, partial(model.next, True)), 320, 519, 134, 62)
        self.button("Next", partial(self.navigate, model.next), 466, 519, 146, 62, primary=True)

    def navigate(self, action):
        previous = self.model.screen, self.model.step_index
        self.act(action)
        if previous != (self.model.screen, self.model.step_index):
            self.announce_screen()

    def announce_screen(self):
        screen = self.model.screen
        if screen is Screen.TUTORIAL:
            self.say(self.model.step.instruction)
        elif screen is Screen.DRYING:
            self.say("Set an optional timer, play Sudoku, or continue.")
        elif screen is Screen.FINISH:
            self.say(DONE_LINE)

    def change_duration(self, seconds):
        self.model.duration = seconds
        self.draw()

    def drying(self):
        model = self.model
        self.header("NAIL AR / DRYING", "Optional drying timer")
        self.countdown = self.label("", 28, 119, 584, 72, 40, PINK, bold=True)
        self.label("Choose your product’s drying time. Gel requires the specified curing lamp.",
                   28, 196, 584, 70, 22, MUTED)
        presets = tuple(sorted({15, 60, 300, 900, model.duration}))
        for index, seconds in enumerate(presets):
            width = 584 // len(presets)
            self.button(time_text(seconds), partial(self.change_duration, seconds),
                        28 + index * width, 276, width - 8, 55,
                        primary=seconds == model.duration)
        self.button("− 30s", partial(self.change_duration, max(1, model.duration - 30)), 28, 340, 156, 55)
        self.button("+ 30s", partial(self.change_duration, model.duration + 30), 192, 340, 156, 55)
        active = model.deadline is not None or model.paused_time is not None
        timer_label = "Resume Timer" if model.paused_time is not None else "Pause Timer" if active else "Start Timer"
        action = model.resume_timer if model.paused_time is not None else model.pause_timer if active else model.start_timer
        self.button(timer_label, partial(self.timer_control, action), 363, 340, 249, primary=True)
        if active:
            self.button("Cancel Timer", partial(self.timer_control, model.cancel_timer), 28, 409, 252)
        self.button("Play Sudoku", self.open_sudoku, 365, 409, 247)
        self.button("Back", partial(self.navigate, model.back), 28, 512, 127, 65)
        self.button("Skip Wait", self.skip_wait, 169, 512, 192, 65)
        self.button("Continue", partial(self.navigate, model.next), 375, 512, 237, 65, primary=True)
        self.refresh_countdown()

    def refresh_countdown(self):
        model = self.model
        if model.deadline is not None or model.paused_time is not None:
            marker = " paused" if model.paused_time is not None else " remaining"
            self.countdown.setText(time_text(model.remaining) + marker)
        else:
            self.countdown.setText(time_text(model.duration) + " selected")

    def timer_control(self, action):
        action()
        self.timer_finished = False
        self.draw()

    def skip_wait(self):
        if self.model.screen in (Screen.TUTORIAL, Screen.DRYING) and self.model.step.drying:
            self.model.next(skip=True)
            self.notice = "Wait skipped. Check the product directions."
            self.draw()

    def open_sudoku(self):
        self.check_errors = False
        self.sudoku_overview = True
        self.navigate(self.model.play)

    def zoom_box(self, box):
        if not self.model.game.solved:
            self.model.game.choose_box(box)
            self.sudoku_overview = False
            self.draw()

    def show_board(self):
        self.sudoku_overview = True
        self.draw()

    def sudoku(self):
        game = self.model.game
        overview = self.sudoku_overview or game.box is None or game.solved
        title = "Sudoku complete" if game.solved else "9 × 9 Sudoku" if overview else f"Sudoku · Box {game.box + 1}"
        self.header("NAIL AR / SUDOKU", title)
        if game.solved:
            instruction = f"Solved in {time_text(int(game.playtime))}."
        elif overview:
            instruction = "Select a 3×3 box to zoom in."
        elif game.selected is None:
            instruction = "Choose an empty or editable cell."
        else:
            row, col = divmod(game.selected, 9)
            instruction = f"Row {row + 1}, column {col + 1} · choose a number."
        self.label(instruction, 28, 112, 584, 45, 23, MUTED)
        if overview:
            self.place(SudokuBoard(game, self.check_errors), 143, 158, 354, 354)
            if not game.solved:
                for box in range(9):
                    row, col = divmod(box, 3)
                    button = self.button("", partial(self.zoom_box, box), 143 + col * 118,
                                         158 + row * 118, 118, 118, transparent=True)
                    button.setAccessibleName(f"Box {box + 1}")
        else:
            for local, cell in enumerate(box_cells(game.box)):
                row, col = divmod(local, 3)
                value = game.cells[cell]
                text = ("!" if self.check_errors and cell in game.errors else "") + (str(value) if value else "·")
                button = self.button(text, partial(self.act, partial(game.select, cell)),
                                     28 + col * 95, 193 + row * 93, 85, 83,
                                     primary=game.selected == cell, enabled=not game.givens[cell] and not game.solved,
                                     size=29)
                r, c = divmod(cell, 9)
                button.setAccessibleName(f"Row {r + 1}, column {c + 1}")
            for digit in range(1, 10):
                row, col = divmod(digit - 1, 3)
                self.button(str(digit), partial(self.enter_number, digit), 330 + col * 95,
                            193 + row * 93, 85, 83, enabled=game.selected is not None and not game.solved, size=29)
            self.button("Erase", partial(self.enter_number, 0), 447, 474, 165, 55,
                        enabled=game.selected is not None and not game.solved)
            self.button("Full Board", self.show_board, 28, 474, 181, 55)
        self.button("Back", partial(self.navigate, self.model.back), 28, 536, 151, 52)
        self.button("Check Board", self.verify_puzzle, 386, 536, 226, 52)

    def verify_puzzle(self):
        self.check_errors = True
        errors = len(self.model.game.errors)
        self.notice = f"{errors} incorrect entries." if errors else "No incorrect entries so far."
        self.draw()

    def enter_number(self, number):
        game = self.model.game
        was_solved = game.solved
        game.enter(number)
        self.notice = ""
        self.draw()
        if not was_solved and game.solved:
            self.say("Nice work! You solved the Sudoku.")

    def open_preview(self):
        self.model.screen = Screen.PREVIEW
        self.preview = CameraPreview(self.services, self.model.design)
        self.last_preview_frame = None
        try:
            self.executor.submit(self.preview.run)
        except RuntimeError:
            self.preview.status = "Camera unavailable. Back returns to the nail guide."
        self.draw()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        QApplication.instance().removeEventFilter(self)
        self.stop_preview()
        self.model.game.leave()

    def stop_preview(self):
        if self.preview is not None:
            self.preview.stop.set()
            self.preview = None

    def preview_screen(self):
        self.header("NAIL AR / EXPERIMENT", "Camera preview",
                    "Hold one nail upright in bright, even light.")
        self.preview_picture = self.place(QLabel(), 28, 168, 584, 318)
        self.preview_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_caption = self.label("", 28, 490, 584, 42, 19, MUTED)
        self.last_preview_frame = None
        self.button("Back to Guide", partial(self.navigate, self.model.back), 28, 536, 190, 53)
        self.button("−", partial(self.preview_action, -.035), 232, 536, 66, 53, size=26).setAccessibleName("Smaller outline")
        self.button("+", partial(self.preview_action, .035), 312, 536, 66, 53, size=26).setAccessibleName("Larger outline")
        self.button("Lock Nail", partial(self.preview_action, "lock"), 393, 536, 219, 53, primary=True)

    def preview_action(self, action):
        if self.preview and self.preview.latest is not None:
            self.preview.actions.put(action)

    def refresh_preview(self):
        preview = self.preview
        if preview is None:
            return
        latest = preview.latest
        if preview.status != "Opening Raven camera…" or latest is None:
            self.preview_caption.setText(preview.status)
            self.preview_picture.clear()
        elif latest is not self.last_preview_frame:
            self.last_preview_frame = latest
            frame, caption = latest
            image = QImage(frame.data, frame.shape[1], frame.shape[0], frame.strides[0], QImage.Format.Format_BGR888)
            self.preview_picture.setPixmap(QPixmap.fromImage(image).scaled(
                self.preview_picture.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            self.preview_caption.setText(caption)

    def finish(self):
        self.header("NAIL AR / COMPLETE", "Beautiful work!", "Your manicure is complete.")
        self.place(NailArt(self.model.design, trio=True), 78, 165, 484, 294)
        self.sparkles = self.place(Sparkles(), 57, 167, 526, 272)
        self.label(f"{self.model.design.name}   ·   {len(self.model.steps)} steps   ·   {time_text(self.model.elapsed)} elapsed",
                   28, 453, 584, 41, 21, LILAC, center=True)
        self.button("Back", partial(self.navigate, self.model.back), 28, 514, 143, 66)
        self.button("Start Another Design", self.restart, 191, 514, 421, 66, primary=True)

    def restart(self):
        self.model.reset()
        self.act(self.model.start, WELCOME_LINE)

    def toggle_voice(self):
        if not self.services.key or self.transcribing:
            return
        self.speech_version += 1
        try:
            if not self.recording:
                if self.services.speaker:
                    self.services.speaker.stop_audio()
                if self.local_speech and self.local_speech.poll() is None:
                    self.local_speech.terminate()
                self.services.record()
                self.recording = True
                self.notice = "Listening… Select Stop listening when done."
            else:
                wav = self.services.stop_recording()
                self.recording = False
                self.transcribing = True
                self.notice = ""
                self.background(self.services.transcribe, self.voice_result, wav)
        except Exception:
            self.recording = self.transcribing = False
            self.notice = "Microphone unavailable. Use gaze or press /."
        self.draw()

    def voice_result(self, phrase):
        self.transcribing = False
        if phrase:
            self.intent(phrase)
        else:
            self.notice = "No command heard. Try again, use gaze, or press /."
            self.draw()

    def intent(self, phrase):
        command = normalize(phrase)
        model = self.model
        screen = model.screen
        if command == "lets do nails" and screen is Screen.WELCOME:
            self.act(model.start, WELCOME_LINE)
            return
        if command in ("back", "go back"):
            self.navigate(model.back)
            return
        if command.startswith("choose ") and screen in (Screen.DESIGN_SELECTION, Screen.DESIGN_CONFIRMATION):
            for index, design in enumerate(DESIGNS):
                if command == "choose " + normalize(design.name):
                    self.act(partial(model.choose, index), CHOICE_LINE)
                    return
        if command.startswith("confirm ") and screen is Screen.SUPPLY_CONFIRMATION:
            for index, name in enumerate(model.supplies):
                if command == "confirm " + normalize(name):
                    self.act(partial(model.confirm, index))
                    return
        if command in ("scan", "scan again", "scan supplies") and screen in (Screen.SUPPLY_SCAN, Screen.SUPPLY_CONFIRMATION):
            if self.services.key:
                self.scan()
            else:
                self.notice = "Live vision unavailable. Choose Demo Mode or Skip Scan."
                self.draw()
            return
        if command in ("demo mode", "demo scan") and screen in (Screen.SUPPLY_SCAN, Screen.SUPPLY_CONFIRMATION):
            self.run_demo_scan()
            return
        if command in ("skip scan", "skip") and screen in (Screen.SUPPLY_SCAN, Screen.SUPPLY_CONFIRMATION):
            self.request_override()
            return
        if command in ("skip wait", "skip") and screen in (Screen.TUTORIAL, Screen.DRYING) and model.step.drying:
            self.skip_wait()
            return
        if command in ("next", "continue", "skip") and screen in (Screen.TUTORIAL, Screen.DRYING):
            self.navigate(partial(model.next, command == "skip"))
            return
        if command in ("repeat", "what do i do now") and screen in (Screen.TUTORIAL, Screen.DRYING, Screen.PREVIEW):
            self.notice = model.step.instruction if screen is Screen.PREVIEW else "Instruction repeated"
            self.draw()
            self.say(model.step.instruction)
            return
        if command in ("pause", "resume") and screen is Screen.TUTORIAL:
            model.paused = command == "pause"
            self.act(lambda: None, None if model.paused else model.step.instruction)
            return
        if command in ("pause timer", "resume timer", "cancel timer") or (
                command in ("pause", "resume") and screen is Screen.DRYING):
            action = {"pause": model.pause_timer, "resume": model.resume_timer, "cancel": model.cancel_timer}
            self.timer_control(action[command.split()[0]])
            return
        if command == "start timer" and screen in (Screen.TUTORIAL, Screen.DRYING):
            model.drying_options()
            self.timer_control(model.start_timer)
            return
        if command in ("lets play sudoku", "play sudoku", "open sudoku") and screen in (Screen.DRYING, Screen.TUTORIAL, Screen.FINISH):
            self.open_sudoku()
            return
        if screen is Screen.SUDOKU:
            numbers = dict(zip("zero one two three four five six seven eight nine".split(), "0123456789"))
            digit = command.removeprefix("enter ").removeprefix("number ")
            digit = numbers.get(digit, digit)
            if digit in ("erase", "clear") or (len(digit) == 1 and digit in "0123456789"):
                self.enter_number(0 if digit in ("erase", "clear") else int(digit))
                return
            box = re.fullmatch(r"(?:box|choose box) (\w+)", command)
            cell = re.fullmatch(r"row (\w+) column (\w+)", command)
            if box and numbers.get(box[1], box[1]) in tuple("123456789"):
                self.zoom_box(int(numbers.get(box[1], box[1])) - 1)
                return
            if cell:
                row, col = (numbers.get(value, value) for value in cell.groups())
                if row in tuple("123456789") and col in tuple("123456789"):
                    index = (int(row) - 1) * 9 + int(col) - 1
                    self.zoom_box(box_for(index))
                    self.act(partial(model.game.select, index))
                    return
            if command in ("check", "check board"):
                self.verify_puzzle()
                return
        if command == "continue" and screen is Screen.DESIGN_CONFIRMATION:
            self.act(model.prepare, SCAN_LINE)
            return
        if command == "continue" and screen is Screen.SUPPLY_CONFIRMATION and model.ready:
            self.act(model.begin, READY_LINE)
            return
        if screen is Screen.PREVIEW and command in ("lock nail", "smaller outline", "larger outline"):
            self.preview_action({"lock nail": "lock", "smaller outline": -.035, "larger outline": .035}[command])
            return
        if command == "skip" and screen in (Screen.PREVIEW, Screen.SUDOKU):
            self.navigate(model.back)
            return
        self.notice = "Command unavailable here."
        self.draw()
