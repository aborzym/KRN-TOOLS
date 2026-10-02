from fractions import Fraction

from spineworks.humdrum import HumdrumError
from spineworks.spine_validation import SpineBranch


def remap_spine_remaining(
    before: tuple[SpineBranch, ...],
    remaining: tuple[Fraction, ...],
    after: tuple[SpineBranch, ...],
) -> tuple[Fraction, ...]:
    """Przenieś pozostałe długości przez rozdwojenia i scalenia."""
    if len(before) != len(remaining):
        raise HumdrumError("Liczba długości nie odpowiada liczbie spinów.")

    if any(value < 0 for value in remaining):
        raise HumdrumError("Pozostała długość nie może być ujemna.")

    def is_ancestor(
        ancestor: SpineBranch,
        descendant: SpineBranch,
    ) -> bool:
        depth = len(ancestor.path)
        return (
            ancestor.identity == descendant.identity
            and descendant.path[:depth] == ancestor.path
            and descendant.opening_lines[:depth] == ancestor.opening_lines
        )

    result: list[Fraction] = []

    for branch in after:
        if branch.identity.spine_type != "**kern":
            result.append(Fraction(0))
            continue

        ancestors = [
            (candidate, value)
            for candidate, value in zip(before, remaining, strict=True)
            if is_ancestor(candidate, branch)
        ]

        if ancestors:
            # Zachowany głos lub nowa gałąź po *^.
            _, value = max(
                ancestors,
                key=lambda item: len(item[0].path),
            )
            result.append(value)
            continue

        descendants = [
            value
            for candidate, value in zip(before, remaining, strict=True)
            if is_ancestor(branch, candidate)
        ]

        if not descendants:
            raise HumdrumError("Nie można ustalić poprzednika głosu **kern.")

        if len(set(descendants)) != 1:
            instrument = branch.identity.instrument or "**kern"
            raise HumdrumError(
                f"{instrument}: scalane głosy mają różne pozostałe długości rytmiczne."
            )

        result.append(descendants[0])

    return tuple(result)
