## Obsługa plików

- „Odśwież” ponownie wczytuje plik z dysku, z potwierdzeniem odrzucenia niezapisanych zmian.
- Obok nazwy pliku wyświetlana jest data i godzina ostatniej modyfikacji.
- „Zamknij plik” zamyka dokument bez zamykania aplikacji; na macOS działa skrót ⌘W.

## Dynamika i zakresy

- Nowy przycisk „LO:DY → LO:HP” poprawia komentarze przy widełkach bez oznaczeń p/f/s.
- Przy istniejącym LO:HP usuwa błędne LO:DY.
- Wyrównywanie dynamiki do prawej rozpoznaje p/f/s w dowolnym miejscu tokenu.
- Parametr rj jest dopisywany do istniejącego LO:DY bez tworzenia duplikatów.
- W dialogu dynamiki opcje wszystkich taktów i spine’ów są domyślnie odznaczone.
- Zakresy kolorowania i dynamiki automatycznie korygują koniec, gdy początek go przekroczy.
- Taką samą kontrolę taktów dodano w „Ukryj zakres”.

## Edytor i ukryte nuty

- Edytor rozdwojeń pokazuje metrum w nieedytowalnych, wyróżnionych komórkach.
- Dodano przycisk „Wyjdź” i uporządkowano zamykanie po udanym zapisie.
- Naprawa błędnych ligatur ukrywa wszystkie dźwięki obu naprawianych tokenów akordowych.

## Sprawdzenie

429 testów zakończonych powodzeniem.
Interfejs sprawdzono na macOS i Linuksie.
Potwierdzono brak duplikatów przy ponownym kolorowaniu, dopisywaniu rj i naprawie LO:DY.
