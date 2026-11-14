from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nail_ar.designs import DESIGNS
from nail_ar.session import Inventory, Screen, Session
from nail_ar.sudoku import GIVENS, SOLUTION, Sudoku, box_for, solve


class FakeClock:
    def __init__(self):
        self.now = 100

    def __call__(self):
        return self.now


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.model = Session(15, self.clock)

    def start_design(self, index=0):
        model = self.model
        model.start()
        model.choose(index)
        model.prepare()
        model.apply_scan([Inventory.FOUND] * len(model.supplies), "LIVE CAMERA SCAN")
        model.begin()
        return model

    def test_back_and_skip_through_every_design_and_step(self):
        for index, design in enumerate(DESIGNS):
            with self.subTest(design=design.name):
                model = self.start_design(index)
                self.assertEqual(model.steps, design.steps)
                for i, step in enumerate(model.steps):
                    if i:
                        model.back()
                        self.assertEqual(model.step_index, i - 1)
                        model.next()
                    if step.drying:
                        model.drying_options()
                        model.back()
                    self.assertEqual(model.step, step)
                    model.next(skip=True)
                    self.assertIn(i, model.skipped)
                self.assertIs(model.screen, Screen.FINISH)
                model.back()
                self.assertIs(model.screen, Screen.TUTORIAL)
                model.reset()

    def test_inventory_status_rescan_and_intentional_override(self):
        model = self.model
        model.start()
        model.choose(0)
        model.prepare()
        model.soak = True
        statuses = [Inventory.FOUND] * 7 + [Inventory.NOT_VISIBLE, Inventory.UNCERTAIN]
        model.apply_scan(statuses, "LIVE CAMERA SCAN")
        self.assertEqual(model.inventory[-2:], statuses[-2:])
        model.begin()
        self.assertIs(model.screen, Screen.SUPPLY_CONFIRMATION)
        model.confirm(7)
        model.apply_scan(statuses, "LIVE CAMERA SCAN")
        self.assertIs(model.inventory[7], Inventory.MANUAL)
        model.screen = Screen.INVENTORY_OVERRIDE
        model.back()
        self.assertIs(model.screen, Screen.SUPPLY_CONFIRMATION)
        model.screen = Screen.INVENTORY_OVERRIDE
        model.begin(override=True)
        self.assertTrue(model.inventory_bypassed)
        self.assertEqual(model.steps[3].title, "Soak briefly")
        self.assertIs(model.inventory[8], Inventory.UNCERTAIN)

    def test_timer_and_puzzle_across_repeated_breaks(self):
        model = self.start_design()
        while not model.step.drying:
            model.next()
        first = model.step_index
        model.drying_options()
        model.start_timer()
        deadline = model.deadline
        model.play()
        game = model.game
        game.choose_box(0)
        game.select(2)
        game.enter(4)
        self.clock.now += 3
        model.back()
        self.assertEqual(game.playtime, 3)
        model.next(skip=True)
        self.assertEqual(model.deadline, deadline)
        self.assertEqual(model.step_index, first + 1)
        model.next()
        model.drying_options()
        model.start_timer()
        self.assertEqual(model.deadline, deadline)
        model.play()
        self.assertIs(model.game, game)
        self.assertEqual((game.box, game.selected, game.cells[2]), (0, 2, 4))
        self.clock.now += 12
        self.assertTrue(model.tick())
        self.assertIs(model.screen, Screen.SUDOKU)
        self.assertEqual(game.playtime, 15)
        model.back()
        model.next()
        self.assertIs(model.screen, Screen.TUTORIAL)

    def test_timer_pause_resume_and_cancel(self):
        model = self.start_design()
        while not model.step.drying:
            model.next()
        model.drying_options()
        model.start_timer()
        self.clock.now += 4
        model.pause_timer()
        model.back()
        self.clock.now += 30
        self.assertFalse(model.tick())
        self.assertEqual(model.remaining, 11)
        model.resume_timer()
        self.assertEqual(model.deadline, self.clock.now + 11)
        model.cancel_timer()
        self.assertEqual(model.remaining, 0)


class SudokuTests(unittest.TestCase):
    def test_unique_solution_and_completion(self):
        self.assertEqual(len(GIVENS), 81)
        self.assertEqual(solve(GIVENS), [SOLUTION])
        game = Sudoku(FakeClock())
        for index, digit in enumerate(SOLUTION):
            if not GIVENS[index]:
                game.choose_box(box_for(index))
                game.select(index)
                game.enter(digit)
        self.assertTrue(game.solved)
        self.assertFalse(game.errors)

    def test_errors_erase_givens_and_restart_persistence(self):
        clock = FakeClock()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "game.json"
            game = Sudoku(clock, path)
            game.open()
            game.choose_box(0)
            game.select(0)
            self.assertIsNone(game.selected)
            game.select(2)
            game.enter(9)
            self.assertEqual(game.errors, {2})
            clock.now += 6
            game.save()
            restored = Sudoku(clock, path)
            self.assertEqual(restored.givens, GIVENS)
            self.assertEqual(restored.cells, game.cells)
            self.assertEqual(restored.selected, 2)
            self.assertEqual(restored.box, 0)
            self.assertEqual(restored.playtime, 6)
            restored.enter(0)
            self.assertFalse(Sudoku(clock, path).errors)
