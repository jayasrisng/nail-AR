from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    title: str
    instruction: str
    art: str = "bare"
    stage: int = 0
    drying: bool = False


@dataclass(frozen=True)
class Design:
    name: str
    difficulty: str
    duration: str
    color: str
    polish: str
    accents: str
    art: tuple[Step, ...]

    @property
    def supplies(self):
        return (
            "Nail cutter", "Nail file", "Cotton pads + remover", "Base coat",
            self.polish, "Detailing brush or dotting tool", self.accents, "Top coat",
        )

    @property
    def steps(self):
        return (
            Step("Clean your nails", "Remove old polish with a cotton pad and remover.", "clean"),
            Step("Trim if needed", "Use the nail cutter to even out the length.", "trim"),
            Step("File into shape", "Smooth the edges with a file. Choose round, oval, or square.", "file"),
            Step("Dry the nail surface", "Dry each nail completely before painting.", "dry"),
            Step("Apply a thin base coat", "Brush a thin layer over each clean nail.", "base"),
            Step("Let the base coat set", "Follow the drying directions on your base coat.", "base", drying=True),
            Step("Paint the first color coat", f"Apply a thin layer of {self.polish.lower()} to each nail.", "color"),
            Step("Let the first coat dry", "Follow the drying directions on your polish.", "color", drying=True),
            Step("Even out the color", "Add a second thin coat only where you need more coverage.", "color"),
            Step("Let the color settle", "Wait until the surface is ready for detail work.", "color", drying=True),
        ) + self.art + (
            Step("Repeat the design", "Repeat these details on your chosen nails.", "art", 99),
            Step("Let the artwork dry", "Use the drying directions for your accent polish.", "art", 99, True),
            Step("Seal with top coat", "Float a thin layer over your design and brush across the tip.", "art", 99),
            Step("Let the top coat dry", "Follow your top coat directions before using your hands.", "art", 99, True),
        )


PETALS = tuple(
    Step(f"Place petal {number} of 5", "Use white polish to place the highlighted dot.", "art", number)
    for number in range(1, 6)
)

DESIGNS = (
    Design("Daisy Dreams", "Easy", "30–50 min", "#cf819d", "Blush pink polish",
           "White + yellow accent polish", PETALS + (
               Step("Dot the yellow center", "Place one small yellow dot between the petals.", "art", 6),
           )),
    Design("Classic French", "Moderate", "30–50 min", "#ca9c94", "Nude pink polish",
           "White accent polish", (
               Step("Start the white tip", "Sweep white polish from the left edge toward the center.", "art", 1),
               Step("Close the smile line", "Mirror the curve from the right edge to meet the first stroke.", "art", 2),
               Step("Fill the free edge", "Fill the tip above the curve with a thin white coat.", "art", 3),
           )),
    Design("Starry Night", "Moderate", "35–55 min", "#323b83", "Dark blue polish",
           "Silver accent polish", (
               Step("Paint the first star", "With silver polish, cross a long vertical line with a short horizontal line.", "art", 1),
               Step("Add a smaller star", "Repeat the cross near the lower edge.", "art", 2),
               Step("Dot in the stardust", "Place tiny silver dots in the open space.", "art", 3),
           )),
)
