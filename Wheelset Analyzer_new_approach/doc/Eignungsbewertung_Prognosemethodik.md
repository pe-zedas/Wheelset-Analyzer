# Eignungsbewertung der Prognosemethodik

## Robustheit bei Datenluecken
**Staerken**
- Fit auf km-Achse toleriert unregelmaessige Messabstaende.
- Reprofilierungs-Spruenge werden explizit entfernt und spaeter wieder eingefuegt.

**Risiken**
- Wenige Messpunkte oder grosse Luecken koennen den Gauss-Newton-Fit instabil machen.
- Nicht monoton steigende Laufleistung fuehrt zum Abbruch (ContinuityError).
- Keine explizite Ausreisserbehandlung oder Glattung vorhanden.

## Sensitivitaet von `defParamExp`
- `defParamExp` formt die Default-Exponentialkurve, die in den Fit einfliesst.
- Bei kurzen Messreihen hat der Default-Anteil starkes Gewicht, Prognose ist empfindlich.
- Bei langen Messreihen sinkt der Einfluss, bleibt aber relevant, da Default-Werte als zusaetzliche Datenpunkte eingehen.

## Methodische Eignung (kurz)
- **Geeignet**, wenn der Verschleiss exponentiell verlaeuft und Reprofilierungen als Spruenge modelliert werden koennen.
- **Eingeschraenkt**, wenn Verschleiss linear, stueckweise oder stark betriebsabhaengig ist.
- **Keine Unsicherheitsabschaetzung** (keine Konfidenzintervalle oder Fehlerbaender).

## Empfehlung (kurz)
- Mindestanzahl Messpunkte pro Achse fuer Prognose definieren.
- Ausreisserfilter (z.B. IQR oder Medianfilter) vor dem Fit einsetzen.
- Sensitivitaet von `defParamExp` durch Kalibrierung oder fahrzeugtyp-spezifische Defaults reduzieren.
