import re
from dataclasses import dataclass
from fractions import Fraction

from spineworks.humdrum import HumdrumError


@dataclass(frozen=True)
class MeterSignature:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.numerator <= 0 or self.denominator <= 0:
            raise HumdrumError("Wartości metrum muszą być dodatnie.")

    @property
    def duration(self) -> Fraction:
        """Długość pełnego taktu w jednostkach całej nuty."""
        return Fraction(self.numerator, self.denominator)

    @property
    def requires_rest_choice(self) -> bool:
        """Czy uzgodniony sposób zapisu pauz wymaga wyboru użytkownika."""
        return (self.numerator, self.denominator) in {
            (6, 8),
            (9, 8),
            (12, 8),
            (6, 4),
        }


def parse_meter(token: str) -> MeterSignature:
    match = re.fullmatch(r"\*M([0-9]+)/([0-9]+)", token)
    if match is None:
        raise HumdrumError(f"Nieobsługiwany zapis metrum: {token!r}.")

    numerator, denominator = match.groups()
    return MeterSignature(
        numerator=int(numerator),
        denominator=int(denominator),
    )


@dataclass(frozen=True)
class MeterRestOption:
    meter: MeterSignature
    key: str
    label: str
    groups: tuple[int, ...]
    split_three_units: bool = False

    def __post_init__(self) -> None:
        if (
            not self.groups
            or any(group <= 0 for group in self.groups)
            or sum(self.groups) != self.meter.numerator
        ):
            raise HumdrumError("Grupowanie nie odpowiada metrum.")

        if self.split_three_units and (
            self.meter.denominator != 8 or any(group != 3 for group in self.groups)
        ):
            raise HumdrumError("Podział na ćwierćnutę i ósemkę wymaga grup trzech ósemek.")


def meter_rest_options(
    meter: MeterSignature,
) -> tuple[MeterRestOption, ...]:
    signature = (meter.numerator, meter.denominator)

    if signature in {(6, 8), (9, 8), (12, 8)}:
        groups = (3,) * (meter.numerator // 3)
        return (
            MeterRestOption(
                meter=meter,
                key="quarter_eighth",
                label="Grupy jako ćwierćnuta i ósemka",
                groups=groups,
                split_three_units=True,
            ),
            MeterRestOption(
                meter=meter,
                key="dotted",
                label="Grupy jako ćwierćnuta z kropką",
                groups=groups,
            ),
        )

    if signature == (6, 4):
        return (
            MeterRestOption(
                meter=meter,
                key="three_plus_three",
                label="3+3 — dwie półnuty z kropką",
                groups=(3, 3),
            ),
            MeterRestOption(
                meter=meter,
                key="two_plus_two_plus_two",
                label="2+2+2 — trzy półnuty",
                groups=(2, 2, 2),
            ),
        )

    standard_groups = {
        1: (1,),
        2: (1, 1),
        3: (2, 1),
        4: (2, 2),
    }
    groups = standard_groups.get(meter.numerator)
    if groups is None:
        raise HumdrumError("Dla tego metrum nie ustalono jeszcze sposobu grupowania pauz.")

    return (
        MeterRestOption(
            meter=meter,
            key="standard",
            label="Podział standardowy",
            groups=groups,
        ),
    )
