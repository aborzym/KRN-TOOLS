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


def hidden_rest_token(duration: Fraction) -> str:
    """Zapisz długość jako jedną ukrytą pauzę **kern."""
    if duration <= 0:
        raise HumdrumError("Ukryta pauza musi mieć dodatnią długość.")

    for dot_count in range(duration.numerator.bit_length() + 1):
        dot_factor = Fraction(
            2 ** (dot_count + 1) - 1,
            2**dot_count,
        )
        base = duration / dot_factor

        if base.numerator == 1:
            denominator = base.denominator
            is_binary = denominator & (denominator - 1) == 0
            if dot_count > 0 and not is_binary:
                continue
            reciprocal = str(denominator)
        elif (
            base.denominator == 1
            and base.numerator >= 2
            and base.numerator & (base.numerator - 1) == 0
        ):
            reciprocal = "0" * (base.numerator.bit_length() - 1)
        else:
            continue

        return f"{reciprocal}{'.' * dot_count}ryy"
    raise HumdrumError("Ta długość wymaga kilku ukrytych pauz lub nieobsługiwanego zapisu rytmu.")
