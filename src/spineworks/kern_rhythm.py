import re
from fractions import Fraction

from spineworks.humdrum import HumdrumError


def kern_duration(token: str) -> Fraction | None:
    """Odczytaj długość tokenu w jednostkach całej nuty."""
    if token == ".":
        return None

    if not token or any(character in token for character in ("\t", "\n", "\r")):
        raise HumdrumError("Nieprawidłowy token do odczytu rytmu.")

    if token.startswith(("*", "!", "=")):
        raise HumdrumError("Ten token nie jest tokenem danych **kern.")

    # Spacja rozdziela składniki akordu, a nie pola spinów.
    components = token.split()
    if not components:
        raise HumdrumError("Puste pole danych **kern.")

    durations: list[Fraction] = []

    for component in components:
        if "q" in component:
            durations.append(Fraction(0))
            continue

        match = re.search(r"([0-9]+)(\.*)", component)
        if match is None:
            raise HumdrumError(f"Nie można odczytać długości tokenu **kern: {component!r}.")

        if "%" in component:
            raise HumdrumError("Ułamkowy zapis rytmu z % nie jest jeszcze obsługiwany.")

        reciprocal, dots = match.groups()

        if set(reciprocal) == {"0"}:
            duration = Fraction(2 ** len(reciprocal))
        else:
            denominator = int(reciprocal)
            if denominator <= 0 or reciprocal.startswith("0"):
                raise HumdrumError(f"Nieprawidłowa wartość rytmiczna: {reciprocal!r}.")
            duration = Fraction(1, denominator)

        dot_count = len(dots)
        duration *= Fraction(
            2 ** (dot_count + 1) - 1,
            2**dot_count,
        )
        durations.append(duration)

    if len(set(durations)) != 1:
        raise HumdrumError("Składniki akordu mają różne długości rytmiczne.")

    return durations[0]
