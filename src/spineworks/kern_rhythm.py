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


def advance_kern_row(
    tokens: tuple[str, ...],
    remaining: tuple[Fraction, ...],
) -> tuple[Fraction, tuple[Fraction, ...]]:
    """Oblicz czas wiersza i pozostałe długości aktywnych głosów."""
    if not tokens or len(tokens) != len(remaining):
        raise HumdrumError("Liczba tokenów **kern nie odpowiada liczbie aktywnych głosów.")

    if any(value < 0 for value in remaining):
        raise HumdrumError("Pozostała długość głosu nie może być ujemna.")

    durations = tuple(kern_duration(token) for token in tokens)
    has_grace = any(duration == 0 for duration in durations)
    active = list(remaining)

    for column, duration in enumerate(durations):
        if duration is None:
            if active[column] == 0 and not has_grace:
                raise HumdrumError(
                    f"Głos {column + 1}: kropka nie kontynuuje żadnej aktywnej wartości rytmicznej."
                )
            continue

        if duration == 0:
            # Przednutka nie kasuje trwającej wartości tego głosu.
            continue

        if active[column] > 0:
            raise HumdrumError(
                f"Głos {column + 1}: nowy token zaczyna się "
                "przed zakończeniem poprzedniej wartości."
            )

        active[column] = duration

    if has_grace:
        return Fraction(0), tuple(active)

    positive = [value for value in active if value > 0]
    if not positive:
        raise HumdrumError("Nie można ustalić czasu wiersza danych **kern.")

    elapsed = min(positive)
    following = tuple(max(Fraction(0), value - elapsed) for value in active)
    return elapsed, following
