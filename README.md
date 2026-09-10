# SPINEWORKS

Graficzny edytor nagłówka i struktury spine'ów w plikach Humdrum (`.krn`).

SPINEWORKS pozwala wykonywać typowe korekty przygotowawcze bez ręcznego
przepisywania wielokolumnowych rekordów interpretacji. Zmiany powstają najpierw
w dokumencie roboczym, można je cofnąć, a plik na dysku jest modyfikowany dopiero
po wybraniu polecenia **Zapisz**.

## Funkcje wersji 1.0.1

- otwieranie plików `.krn` z okna programu albo metodą „przeciągnij i upuść”;
- podgląd bloku interpretacji w układzie odpowiadającym spine'om dokumentu;
- edycja nazw pełnych, nazw skróconych, kodów instrumentów i grup instrumentów;
- edycja rekordu `!!!system-decoration:`;
- generowanie kodów `*IC` za pomocą `addic`;
- dodawanie i usuwanie linii `*IG`;
- numerowanie taktów za pomocą `barnum`;
- dodawanie pustego spine'u dowolnego typu;
- dodawanie spine'u `**kern` z widocznymi albo ukrytymi pauzami;
- usuwanie wybranego spine'u;
- usuwanie oryginalnych łamań stron i systemów oraz pustych rekordów;
- uzupełnianie i poprawianie przypisań `*part` i `*staff` zgodnie ze strukturą
  instrumentów;
- cofanie zmian w bieżącej sesji.

## Wymagania

Program wymaga zainstalowanych narzędzi Humdrum używanych przez poszczególne
operacje:

- `addic`;
- `barnum`;
- `extractx`;
- `restfill`;
- `rid`.

SPINEWORKS szuka ich najpierw w zmiennej `PATH`, a następnie w typowych
lokalizacjach, między innymi:

```text
~/humdrum-tools/humlib/bin
~/humdrum-tools/humextra/bin
~/humdrum-tools/humdrum/bin
~/humlib/bin
~/humextra/bin
~/.local/bin
/opt/homebrew/bin
/opt/local/bin
/usr/local/bin
```

Niestandardowy katalog można wskazać w zmiennej środowiskowej
`SPINEWORKS_HUMDRUM_PATH`. Można w niej podać kilka katalogów rozdzielonych
dwukropkiem na Linuksie i macOS.

## Uruchomienie deweloperskie

Wymagany jest Python 3.11 lub nowszy.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
spineworks
```

Testy:

```bash
pytest
```

## Pakiety instalacyjne

Wydanie 1.0.1 jest przygotowywane dla następujących platform:

- Linux `x86_64` — `SPINEWORKS-1.0.1-linux-x86_64.deb`;
- macOS Apple Silicon `arm64` — `SPINEWORKS-1.0.1-macos-arm64.dmg`.

Wersja dla macOS Intel `x86_64` zostanie dodana oddzielnie.
