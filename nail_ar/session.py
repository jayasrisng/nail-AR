from enum import Enum, auto
from math import ceil
from time import monotonic

from .designs import DESIGNS, Step
from .sudoku import Sudoku


class Screen(Enum):
    WELCOME = auto()
    DESIGN_SELECTION = auto()
    DESIGN_CONFIRMATION = auto()
    SUPPLY_SCAN = auto()
    SUPPLY_CONFIRMATION = auto()
    INVENTORY_OVERRIDE = auto()
    TUTORIAL = auto()
    DRYING = auto()
    SUDOKU = auto()
    PREVIEW = auto()
    FINISH = auto()


class Inventory(Enum):
    FOUND = "Found"
    NOT_VISIBLE = "Not visible"
    UNCERTAIN = "Uncertain"
    MANUAL = "Confirmed manually"


class Session:
    def __init__(self, duration=900, clock=monotonic, save_path=None):
        if duration <= 0:
            raise ValueError("Drying duration must be positive.")
        self.duration, self.clock = duration, clock
        self.game = Sudoku(clock, save_path)
        self.deadline = self.paused_time = None
        self.reset()

    def reset(self):
        self.screen = Screen.WELCOME
        self.started = self.finished = None
        self.design = None
        self.steps = ()
        self.inventory = []
        self.scan_label = ""
        self.soak = False
        self.step_index = 0
        self.skipped = set()
        self.paused = False
        self.inventory_bypassed = False
        self.sudoku_return = Screen.TUTORIAL

    def start(self):
        if self.screen is Screen.WELCOME:
            self.started = self.clock()
            self.screen = Screen.DESIGN_SELECTION

    def choose(self, index):
        if self.screen in (Screen.DESIGN_SELECTION, Screen.DESIGN_CONFIRMATION) and 0 <= index < len(DESIGNS):
            self.design = DESIGNS[index]
            self.steps = self.design.steps
            self.inventory = []
            self.scan_label = ""
            self.screen = Screen.DESIGN_CONFIRMATION

    def change_design(self):
        if self.screen is Screen.DESIGN_CONFIRMATION:
            self.screen = Screen.DESIGN_SELECTION

    def prepare(self):
        if self.screen is Screen.DESIGN_CONFIRMATION:
            self.screen = Screen.SUPPLY_SCAN

    @property
    def supplies(self):
        return self.design.supplies + (("Water bowl",) if self.soak else ())

    def apply_scan(self, statuses, label):
        if self.screen not in (Screen.SUPPLY_SCAN, Screen.SUPPLY_CONFIRMATION):
            return
        self.inventory = [
            Inventory.MANUAL if i < len(self.inventory) and self.inventory[i] is Inventory.MANUAL
            else statuses[i]
            for i in range(len(self.supplies))
        ]
        self.scan_label = label
        self.screen = Screen.SUPPLY_CONFIRMATION

    def confirm(self, index):
        if self.screen is Screen.SUPPLY_CONFIRMATION and 0 <= index < len(self.inventory):
            if self.inventory[index] in (Inventory.UNCERTAIN, Inventory.NOT_VISIBLE):
                self.inventory[index] = Inventory.MANUAL

    @property
    def ready(self):
        return bool(self.inventory) and all(
            status in (Inventory.FOUND, Inventory.MANUAL) for status in self.inventory
        )

    def begin(self, override=False):
        if not ((self.screen is Screen.SUPPLY_CONFIRMATION and self.ready)
                or (override and self.screen is Screen.INVENTORY_OVERRIDE)):
            return
        self.inventory_bypassed = override
        if self.soak:
            soak = Step("Soak briefly", "Dip your fingertips in the water bowl, then pat them dry.", "soak")
            self.steps = self.steps[:3] + (soak,) + self.steps[3:]
        self.screen = Screen.TUTORIAL

    @property
    def step(self):
        return self.steps[self.step_index]

    def next(self, skip=False):
        if self.screen not in (Screen.TUTORIAL, Screen.DRYING):
            return
        if skip:
            self.skipped.add(self.step_index)
        self.paused = False
        if self.step_index + 1 < len(self.steps):
            self.step_index += 1
            self.screen = Screen.TUTORIAL
        else:
            self.finished = self.clock()
            self.screen = Screen.FINISH

    def back(self):
        if self.screen is Screen.SUDOKU:
            self.game.leave()
            self.screen = self.sudoku_return
        elif self.screen is Screen.TUTORIAL:
            if self.step_index:
                self.step_index -= 1
            self.paused = False
        elif self.screen is Screen.FINISH:
            self.finished = None
            self.screen = Screen.TUTORIAL
        else:
            self.screen = {
                Screen.DESIGN_SELECTION: Screen.WELCOME,
                Screen.DESIGN_CONFIRMATION: Screen.DESIGN_SELECTION,
                Screen.SUPPLY_SCAN: Screen.DESIGN_CONFIRMATION,
                Screen.SUPPLY_CONFIRMATION: Screen.SUPPLY_SCAN,
                Screen.INVENTORY_OVERRIDE: Screen.SUPPLY_CONFIRMATION if self.inventory else Screen.SUPPLY_SCAN,
                Screen.DRYING: Screen.TUTORIAL,
                Screen.PREVIEW: Screen.TUTORIAL,
            }.get(self.screen, self.screen)

    def drying_options(self):
        if self.screen is Screen.TUTORIAL and self.step.drying:
            self.screen = Screen.DRYING

    def start_timer(self):
        if self.screen is Screen.DRYING and self.deadline is None and self.paused_time is None:
            self.deadline = self.clock() + self.duration

    @property
    def remaining(self):
        if self.deadline is not None:
            return max(0, ceil(self.deadline - self.clock()))
        return ceil(self.paused_time or 0)

    def pause_timer(self):
        if self.deadline is not None:
            self.paused_time = max(0, self.deadline - self.clock())
            self.deadline = None

    def resume_timer(self):
        if self.paused_time is not None:
            self.deadline = self.clock() + self.paused_time
            self.paused_time = None

    def cancel_timer(self):
        self.deadline = self.paused_time = None

    def tick(self):
        if self.deadline is not None and self.clock() >= self.deadline:
            self.deadline = None
            return True
        return False

    def play(self):
        if self.screen in (Screen.TUTORIAL, Screen.DRYING, Screen.FINISH):
            self.sudoku_return = self.screen
            self.game.open()
            self.screen = Screen.SUDOKU

    @property
    def elapsed(self):
        return int(self.finished - self.started) if self.finished is not None else 0
