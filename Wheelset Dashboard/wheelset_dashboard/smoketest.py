"""Smoke-Test der Datenschicht (Phase P1).

Beispiel:
    python -m wheelset_dashboard.smoketest --profile vgf \
        --csv-raw "../Wheelset Analyzer_new_approach/bo_radsatzdaten_export.csv"
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .data.repository import Repository, RepositoryConfig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="Kundenprofil (vgf, abellio, mob)")
    ap.add_argument("--csv-raw", required=True, help="Pfad zu bo_radsatzdaten_export.csv")
    ap.add_argument("--csv-prognose", default=None, help="(optional) bo_radsatzdaten_prognose_export.csv")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    repo = Repository(RepositoryConfig(
        profile_name=args.profile,
        source="csv",
        csv_raw_path=Path(args.csv_raw),
        csv_prognose_path=Path(args.csv_prognose) if args.csv_prognose else None,
    ))

    flotte = repo.load()

    # Logik-Pass (P2): Status + Lager-Zustand
    from .logic.status import recompute_all as recompute_status
    from .logic.lager_state import recompute_all as recompute_lager
    recompute_status(flotte)
    lager_counts = recompute_lager(flotte)

    print()
    print(f"== Flotte ({repo.profile.name}) ==")
    print(f"Einheiten eingebaut: {len(flotte.einheiten)}")
    print(f"Lager-Komponenten:   {len(flotte.lager)}  "
          f"(ready={lager_counts['ready']}, to_overhaul={lager_counts['to_overhaul']})")
    print(f"Flotten-Status:      {flotte.status().value}")
    print()

    # Top 10 Einheiten mit Zusammenfassung + Status
    print("Einheiten (max. 10):")
    for i, (bez, einheit) in enumerate(sorted(flotte.einheiten.items())):
        if i >= 10:
            print(f"  ... und {len(flotte.einheiten) - 10} weitere")
            break
        n_dg = len(einheit.drehgestelle)
        n_achsen = sum(len(dg.achsen) for dg in einheit.drehgestelle.values())
        n_direkt = sum(len(dg.direkt_messreihen) for dg in einheit.drehgestelle.values())
        mgroessen = set()
        for dg in einheit.drehgestelle.values():
            for a in dg.achsen.values():
                for r in a.raeder.values():
                    mgroessen.update(r.messreihen.keys())
            mgroessen.update(dg.direkt_messreihen.keys())
        print(f"  [{einheit.status().value:6s}] {bez:28s}  DGs={n_dg:3d}  Achsen={n_achsen:3d}  "
              f"DG-direkt-Msg={n_direkt}  Messgroessen={sorted(mgroessen)}")

    # eine Beispiel-Achse mit Messreihen auflisten
    print()
    print("Beispiel-Achse:")
    for e, dg, a in flotte.alle_achsen():
        print(f"  {e.topeinheit_bez} > {dg.dg_einbaupos} > {a.rs_einbaupos}")
        for seite, rad in a.raeder.items():
            for mg, mr in rad.messreihen.items():
                letzt = mr.letzter_wert()
                print(f"    Seite {seite.value:12s} {mg:20s} n={len(mr.historie):4d}  "
                      f"letzte={letzt.datum.date() if letzt else '-'}  "
                      f"stand={letzt.stand if letzt else '-'}")
        break


if __name__ == "__main__":
    main()
