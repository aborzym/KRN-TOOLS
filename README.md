# SPINEWORKS

Graficzne narzędzie do kontrolowanej korekty i uzupełniania plików Humdrum.

Pierwszy etap obejmuje:

- otwieranie plików `.krn` przyciskiem lub metodą „przeciągnij i upuść”;
- kolumnowy podgląd bloku interpretacji nagłówka;
- uzupełnianie `*part…` i `*staff…` w spine'ach pomocniczych na podstawie
  poprzedzającego spine'u `**kern`;
- cofanie zmian w bieżącej sesji.

## Uruchomienie deweloperskie

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
spineworks
```

