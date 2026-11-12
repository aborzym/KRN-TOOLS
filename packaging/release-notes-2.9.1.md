# BETA — wersja do testów

- Naprawa zagnieżdżonych rozdwojeń zachowuje układ i kolejność warstw, gdy scalenie i ponowne otwarcie są zbędne.
- Przenoszenie `*Xrep` przed scalenie tylko w warstwach, w których powtórzenie nadal trwa.
- Wykrywanie i przenoszenie rozdwojeń przed interpretacje na początku taktu, gdy pozwala na to struktura spine’ów.
