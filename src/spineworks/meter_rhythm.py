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
