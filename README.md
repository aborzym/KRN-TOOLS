# SPINEWORKS

Graficzny edytor nagłówka i struktury spine'ów w plikach Humdrum (`.krn`).

SPINEWORKS pozwala wykonywać typowe korekty przygotowawcze bez ręcznego
przepisywania wielokolumnowych rekordów interpretacji. Zmiany powstają najpierw
w dokumencie roboczym, można je cofnąć, a plik na dysku jest modyfikowany dopiero
po wybraniu polecenia **Zapisz**.

## Funkcje

- otwieranie plików `.krn` z okna programu albo metodą „przeciągnij i upuść”;
- podgląd bloku interpretacji w układzie odpowiadającym spine'om dokumentu;
- edycja nazw pełnych, nazw skróconych, kodów instrumentów i grup instrumentów;
- edycja rekordu `!!!system-decoration:`;
- oznaczanie kursywy w spine’ach `**text` i `**mod-text` na podstawie
  znaczników `/…/`, z obsługą `*ij` i `*Xij`;
- przenoszenie oznaczeń custosów z komentarzy lokalnych spine’ów `**kern`
  do rekordów interpretacji `*custos:dźwięk`, umieszczanych przed komentarzami,
  kreską taktową albo następną nutą;
- ukrywanie nut, pauz, łuków, ligatur i powiązanej dynamiki w wybranych
  spine’ach `**kern` oraz w domkniętym zakresie taktów, z obsługą `*^`, `*v`
  i opcjonalnego rozszerzania istniejących oznaczeń `yy` do maksymalnie `yyyy`;
- dodawanie i poprawianie rekordu `!!!!SEGMENT:` z pełną nazwą pliku;
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

SPINEWORKS automatycznie przeszukuje typowe katalogi instalacji Humdrum.
Dodatkowe katalogi można wskazać w aplikacji przez „Narzędzia Humdrum…”.
Ustawienia są zapamiętywane między uruchomieniami.

Alternatywnie można użyć zmiennej środowiskowej
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

## Budowanie aplikacji

PyInstaller korzysta z dołączonego pliku `SPINEWORKS.spec`, który pakuje ikonę
okna razem z aplikacją.

Na macOS najpierw należy utworzyć plik ICNS, a następnie zbudować aplikację:

```bash
./packaging/build-macos-icon.sh
pyinstaller --noconfirm --clean SPINEWORKS.spec
```

Na Linuksie wystarczy:

```bash
pyinstaller --noconfirm --clean SPINEWORKS.spec
```

Następnie zbuduj pakiet DEB:

```bash
bash packaging/build-linux-deb.sh
```

Numer wersji jest definiowany w `src/spineworks/__init__.py`.
Konfiguracja pakietu Python, PyInstaller oraz skrypt budowania DEB
pobierają go z tego samego miejsca.

## Pakiety instalacyjne

Pakiety wydania 2.4.0:

- Linux `x86_64` — `SPINEWORKS-2.4.0-linux-x86_64.deb`;
- macOS Apple Silicon `arm64` — `SPINEWORKS-2.4.0-macos-arm64.dmg`

Wersja dla macOS Intel `x86_64` zostanie dodana oddzielnie.

Od wersji 2.3.0 aplikacja automatycznie sprawdza dostępność nowych wydań.
Przed instalacją wyświetla opis zmian, pobiera pakiet właściwy dla systemu,
sprawdza jego rozmiar i sumę SHA-256, a po potwierdzeniu instaluje aktualizację
i uruchamia program ponownie. Aktualizacje można też sprawdzić ręcznie z paska
narzędzi.
