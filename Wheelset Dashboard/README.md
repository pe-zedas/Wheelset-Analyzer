# Wheelset Dashboard

Desktop-Dashboard zur Visualisierung der Radsatzdaten (parallel zum Prognose-Backend `Wheelset Analyzer_new_approach`).

- Framework: PySide6 (Qt 6)
- Datenquellen: Oracle (`BO_RADSATZDATEN`, `BO_RADSATZDATEN_PROGNOSE`) oder CSV-Export
- Kundenprofile unter `wheelset_dashboard/config/profiles/`

Vollständige Spezifikation in [doc/PRD_Wheelset_Dashboard.md](doc/PRD_Wheelset_Dashboard.md).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Phase P1 — Smoke-Test (Datenschicht)

```powershell
python -m wheelset_dashboard.smoketest --profile vgf --csv-raw "..\Wheelset Analyzer_new_approach\bo_radsatzdaten_export.csv"
```
