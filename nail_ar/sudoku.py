import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

DIGITS = "123456789"
GIVENS = tuple(map(int, (
    "530070000"
    "600195000"
    "098000060"
    "800060003"
    "400803001"
    "700020006"
    "060000280"
    "000419005"
    "000080079"
)))


def box_for(index):
    row, col = divmod(index, 9)
    return row // 3 * 3 + col // 3


def box_cells(box):
    row, col = divmod(box, 3)
    start = row * 27 + col * 3
    return tuple(start + y * 9 + x for y in range(3) for x in range(3))


PEERS = tuple(frozenset(
    other for other in range(81) if other != index and (
        other // 9 == index // 9 or other % 9 == index % 9
        or box_for(other) == box_for(index)
    )
) for index in range(81))


def solve(board, limit=2):
    cells = list(board)
    answers = []

    def search():
        if len(answers) >= limit:
            return
        choices = [(set(range(1, 10)) - {cells[p] for p in PEERS[i]}, i)
                   for i, value in enumerate(cells) if value == 0]
        if not choices:
            answers.append(tuple(cells))
            return
        options, index = min(choices, key=lambda item: len(item[0]))
        for value in sorted(options):
            cells[index] = value
            search()
        cells[index] = 0

    if not any(v and any(board[p] == v for p in PEERS[i]) for i, v in enumerate(board)):
        search()
    return answers


SOLUTION, = solve(GIVENS)


def default_path():
    return Path(os.getenv("NAIL_AR_SAVE_PATH") or os.getenv("NAILPILOT_SAVE_PATH") or
                (Path.home() / ".local" / "share" / "nailpilot" / "sudoku-v1.json"))


class Sudoku:
    def __init__(self, clock, path=None):
        self.clock = clock
        self.path = Path(path) if path is not None else None
        self.givens = GIVENS
        self.cells = list(GIVENS)
        self.box = self.selected = None
        self.elapsed = 0.0
        self.joined = None
        self.save_error = False
        self.load()

    def load(self):
        if self.path is None:
            return
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or data.get("givens") != list(GIVENS):
                return
            cells = data["cells"]
            if (not isinstance(cells, list) or len(cells) != 81
                    or any(type(v) is not int or not 0 <= v <= 9 for v in cells)
                    or any(clue and clue != cells[i] for i, clue in enumerate(GIVENS))):
                return
            elapsed = data.get("elapsed")
            if type(elapsed) in (int, float) and 0 <= elapsed < float("inf"):
                self.elapsed = elapsed
            self.cells = cells
            box, selected = data.get("box"), data.get("selected")
            if type(box) is int and 0 <= box < 9:
                self.box = box
                if type(selected) is int and selected in box_cells(box) and not GIVENS[selected]:
                    self.selected = selected
        except (OSError, ValueError, KeyError):
            return

    @property
    def playtime(self):
        return self.elapsed + (self.clock() - self.joined if self.joined is not None else 0)

    def save(self):
        if self.path is None:
            return
        temp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as stream:
                temp = Path(stream.name)
                json.dump(dict(givens=self.givens, cells=self.cells, box=self.box,
                               selected=self.selected, elapsed=self.playtime), stream)
            temp.replace(self.path)
            self.save_error = False
        except OSError:
            self.save_error = True
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    def open(self):
        if self.joined is None and not self.solved:
            self.joined = self.clock()

    def leave(self):
        self.elapsed = self.playtime
        self.joined = None
        self.save()

    def choose_box(self, box):
        if box != self.box:
            self.box, self.selected = box, None
            self.save()

    def select(self, index):
        if self.box is not None and index in box_cells(self.box) and not self.givens[index]:
            self.selected = index
            self.save()

    def enter(self, number):
        if self.selected is None or not 0 <= number <= 9 or self.solved:
            return
        self.cells[self.selected] = number
        if self.solved:
            self.leave()
        else:
            self.save()

    @property
    def errors(self):
        return {i for i, value in enumerate(self.cells)
                if not self.givens[i] and value not in (0, SOLUTION[i])}

    @property
    def solved(self):
        return tuple(self.cells) == SOLUTION
