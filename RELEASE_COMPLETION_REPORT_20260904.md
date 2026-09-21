# APEX Context Engine 1.0 — raport zakończenia naprawy

Data walidacji: 2026-09-04 (Europe/Warsaw)

## STATUS

FULLY_REPAIRED. Jedynym źródłem jest `D:\APEX_CONTEXT_ENGINE_V1_WORK\APEX_FINAL_FREEZE_CLONE`, a jedynym katalogiem wydania `D:\APEX_CONTEXT_ENGINE_V1_RELEASE`.

## ROOT CAUSES

1. Wiele starych klonów, freeze'ów, recovery i cache mieszało pochodzenie kodu oraz zajmowało 59 498 422 539 bajtów.
2. Ścieżki danych, profilu i Context Engine nie miały spójnego kontraktu frozen; build mógł zależeć od drzewa źródłowego lub zewnętrznego Pythona/przeglądarki.
3. Kontrakt CLI błędnie zwracał kod 2 dla pozytywnego `PASS_WITH_QUARANTINE`, mimo że GUI i adapter uznawały ten status za sukces.
4. Aktualny Betclic wyświetla modal onboardingowy „Xtra Wygrana” w Angular CDK overlay. Blokował on kliknięcie każdej zakładki przez 30 s i kończył poprawne zdarzenie jako `ZERO_ODDS`.
5. Historyczne fałszywe kwarantanny wynikały z niepełnej klasyfikacji udowodnionych rodzin/zakresów oraz utraty kontekstu nagłówków, okresu, właściciela lub uczestnika. Regresje utrwalają naprawione przypadki; nieudowodnione kształty nadal są fail-closed.

## ZMIENIONE PLIKI

- `diagnostics.py` — izolowany katalog danych frozen i profil Chromium.
- `gui.py` — jedna ścieżka Context Engine, katalog wyników i tryb `--release-e2e`.
- `core.py` — preferencja wbudowanego Chromium, metadane frozen i bezpieczne zamykanie rozpoznanego modalu Betclic.
- `context_engine_adapter.py` — Context Engine in-process w buildzie frozen.
- `apex_context_engine/cli.py` — exit 0 dla `PASS` i `PASS_WITH_QUARANTINE`.
- `release_self_test.py`, `test_release_contract.py` — kontrakt i E2E wydania.
- `tests_context/test_gui_integration_contract.py`, `tests_context/test_schema.py` — ścieżki skonsolidowanego drzewa.
- `BetclicFullOddsExtractor.spec`, `build_exe.py`, `installer.iss` — powtarzalny build portable/installer z Chromium.
- `README_START_PL.txt`, `pyproject.toml`, `AGENTS.md` — uruchamianie, zależności i zasady jednego źródła.

## TESTY

- `python -m unittest discover -v`: 381/381 OK po wszystkich poprawkach.
- `python -m pytest -q`: 116/116 OK po wszystkich poprawkach.
- `python -m compileall -q .`: OK.
- Testy kontraktu release: 5/5 OK, w tym modal i kod wyjścia CLI.
- Determinizm na świeżym pakiecie live, dwa przebiegi: JSON `44EBCC92AC99C5CACF7985005AFB7A1BC5D9EBF920E185F51611CCB7BD367A15`; TXT `7BEE2B5F6806E0A55D0B3B140580CAD8CB38217D3EBD5A81CDCA09F7731235AF`; oba identyczne, oba exit 0.

## E2E

Finalny ZIP rozpakowano poza źródłem i uruchomiono na rzeczywistym zdarzeniu Lincoln–Southampton. Wynik: frozen=true, exit 0, `GOTOWE`, 8/8 zakładek, 202 rynki, 802 kursy, 0 unresolved, parser truth PASS, `ANALYSIS_READY=YES`, `FULL_USABLE_READY=YES`, Context `PASS_WITH_QUARANTINE`. Runtime użył wyłącznie EXE i Chromium z rozpakowanego artefaktu. Modal „Xtra Wygrana” został rozpoznany i zamknięty.

Instalator 1.0 zakończył się komunikatem `Installation process succeeded`, nie wymagał restartu. Zainstalowany EXE uruchomił responsywne GUI dwa razy. Skrót pulpitu wskazuje dokładnie `%LOCALAPPDATA%\Programs\APEX Context Engine\APEX_Context_Engine.exe`. Python użytkownika nie jest wymagany przez wydanie.

## FALSE QUARANTINE

Na czystym poprawnym pakiecie: `PASS`, 9/9 zaakceptowanych, 0 kwarantanny, exit 0. Na live: 802 obserwacje zostały rozliczone; 766 przyjęto, 36 celowo odseparowano wyłącznie jako `UNSUPPORTED_PERIOD:OTHER` (rynki statystyczne 120 min / „z dogrywką”), 0 upstream excluded i 0 blocked reasons. To ochrona nieobsługiwanego zakresu rozliczenia, nie utrata obsługiwanych rekordów. Warstwa semantic-safety nie wylicza fair price dla nieobsługiwanych rodzin.

## PASS DLA POPRAWNYCH DANYCH

Minimalny kompletny pakiet: `PASS`, accepted=9, quarantined_source=0, exit 0. Pełny live E2E: pozytywny `PASS_WITH_QUARANTINE`, exit 0, analysis/full-usable YES, 0 unresolved.

## ZACHOWANIE OCHRONY DLA BŁĘDNYCH DANYCH

- URL strony głównej zamiast strony zdarzenia: frozen `BLOCKED`, `EVENT_NOT_PREMATCH`, exit 20, Context nie został uruchomiony.
- Pakiet z `ODDS="not-a-number"`: Context `BLOCKED`, accepted=0, quarantined_source=1, powód `INVALID_NUMBER:ODDS_NOT_NUMERIC:not-a-number`, exit 2.
- Niewspierane okresy/semantyka pozostają jawnie odseparowane; system nie dopowiada danych ani nie osłabia bramek bezpieczeństwa.

## CLEANUP I STORAGE

- Stan początkowy objęty audytem: 59 498 422 539 bajtów.
- Stan końcowy źródło + release: 000438911695 bajtów.
- Odzyskano: 059059510844 bajtów.
- Usunięto stare klony/freeze/recovery/archive, pozostałości buildów, cache, tymczasowe profile i katalogi izolowanych testów.
- Zachowano wyłącznie kanoniczne fixture'y regresyjne: 30 plików diagnostycznych, 74 snapshoty i 3 logi.

## POZOSTAŁE PROBLEMY

Brak znanych problemów blokujących wydanie. Naturalne ograniczenia operacyjne: zmiana DOM/WAF Betclic lub niedostępność sieci może bezpiecznie zablokować pobranie; rynki o nieobsługiwanym okresie/semantyce pozostają audytowalnie odseparowane zamiast być zgadywane.

## FINAL VERDICT

FULLY_REPAIRED — potwierdzone końcowym frozen E2E, pełną regresją, deterministycznym replayem, negatywnymi próbami fail-closed oraz rzeczywistą instalacją i dwukrotnym startem GUI.
