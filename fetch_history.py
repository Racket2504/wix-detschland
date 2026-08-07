"""
fetch_history.py — Echte historische WIX-Zeitreihe (2006–2025) aus Eurostat
============================================================================
Holt für alle 11 live verfügbaren Indikatoren (Auftragseingänge bleibt
Fallback, siehe CLAUDE_HISTORIE.md) die KOMPLETTE Zeitreihe von Eurostat
(nicht nur die letzten Werte wie fetch_wix.py) und berechnet daraus den WIX
für jedes Quartal von 2006-Q1 bis 2025-Q4.

Nutzt exakt dieselben Dataset-IDs/Parameter wie fetch_wix.py (nur
lastTimePeriod -> sinceTimePeriod) und importiert SCORING/WEIGHTS/cl
unverändert von dort — die Methodik wird nicht angefasst.

AUSFÜHREN: python fetch_history.py
Schreibt: history.json (volle Kontrolle) — fetch_wix.py/index.html werden
NICHT von diesem Skript verändert (das passiert danach manuell/gezielt).
"""

import requests, json
from fetch_wix import SCORING, WEIGHTS, cl, FALLBACK, quarterly_avg, format_period, BA_ILO_OFFSET

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

START_Q = "2006-Q1"
END_Q   = "2026-Q1"   # letztes vollständiges Quartal; danach übernimmt der Live-Fetch


def eurostat_get_since(dataset: str, params: dict, since: str) -> dict:
    """Wie eurostat_get() in fetch_wix.py, aber mit sinceTimePeriod statt
    lastTimePeriod, um die volle verfügbare Historie zu holen."""
    p = {**params, "format": "JSON", "lang": "EN", "sinceTimePeriod": since}
    try:
        r = requests.get(f"{EUROSTAT}/{dataset}", params=p, timeout=60)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f"  ⚠ {dataset}: {e}")
        return {}
    try:
        dims    = d["id"]
        t_idx   = dims.index("time")
        t_cats  = d["dimension"]["time"]["category"]
        periods = [k for k, _ in sorted(t_cats["index"].items(), key=lambda x: x[1])]
        size    = d["size"]
        stride  = 1
        for s in size[t_idx + 1:]:
            stride *= s
        vals = d.get("value", {})
        return {p: round(float(vals[str(i * stride)]), 2)
                for i, p in enumerate(periods)
                if str(i * stride) in vals}
    except Exception as e:
        print(f"  ⚠ Parse {dataset}: {e}")
        return {}


def yoy_from_raw(monthly: dict) -> dict:
    """Berechnet M/M-12 YoY% aus einer rohen monatlichen Wertreihe
    (für Handelsbilanz, wo Eurostat keine fertige YoY-Rate liefert)."""
    months = sorted(monthly.keys())
    idx = {m: i for i, m in enumerate(months)}
    out = {}
    for m in months:
        yr, mo = m.split("-")
        prev = f"{int(yr)-1}-{mo}"
        if prev in monthly and monthly[prev] != 0:
            out[m] = round((monthly[m] / abs(monthly[prev]) - 1) * 100, 2)
    return out


def quarter_range(start: str, end: str) -> list[str]:
    sy, sq = start.split("-Q"); ey, eq = end.split("-Q")
    sy, sq, ey, eq = int(sy), int(sq), int(ey), int(eq)
    out = []
    y, q = sy, sq
    while (y, q) <= (ey, eq):
        out.append(f"{y}-Q{q}")
        q += 1
        if q == 5:
            q = 1; y += 1
    return out


def backfill(series: dict, quarters: list[str], label: str) -> dict:
    """Füllt fehlende frühe Quartale mit dem ältesten verfügbaren Wert auf
    und dokumentiert das auf der Konsole (z.B. sts_rb_m beginnt erst 2015)."""
    if not series:
        return {q: None for q in quarters}
    earliest_q = sorted(series.keys())[0]
    earliest_v = series[earliest_q]
    out = {}
    missing_before = [q for q in quarters if q < earliest_q]
    if missing_before:
        print(f"  ↳ {label}: keine Daten vor {earliest_q} — "
              f"{len(missing_before)} Quartale mit ältestem Wert ({earliest_v}) aufgefüllt")
    for q in quarters:
        out[q] = series.get(q, earliest_v if q < earliest_q else None)
    return out


def main():
    quarters = quarter_range(START_Q, END_Q)
    print(f"Hole echte Historie {START_Q} .. {END_Q} ({len(quarters)} Quartale) von Eurostat...\n")

    series = {}

    print("  1. BIP (quarterly YoY)...")
    series["bip"] = eurostat_get_since("namq_10_gdp",
        {"geo":"DE","unit":"CLV_PCH_SM","s_adj":"SCA","na_item":"B1GQ"}, START_Q)

    print("  2. Industrieproduktion (monthly YoY -> Quartalsdurchschnitt)...")
    s = eurostat_get_since("sts_inpr_m",
        {"geo":"DE","s_adj":"CA","nace_r2":"B-D","indic_bt":"PRD","unit":"PCH_SM"}, "2006-01")
    series["industrie"] = quarterly_avg(s)

    print("  3. Auftragseingänge — kein Eurostat-Dataset, Fallback für alle Quartale")
    series["auftraege"] = {q: FALLBACK["auftraege"] for q in quarters}

    print("  4. Exporte (monthly YoY -> Quartalsdurchschnitt)...")
    s = eurostat_get_since("ext_st_27_2020msbec",
        {"geo":"DE","stk_flow":"EXP","indic_et":"TRD_VAL_RT12","partner":"WORLD","bclas_bec":"TOTAL"}, "2006-01")
    series["exporte"] = quarterly_avg(s)

    print("  5. Handelsbilanz (roh -> manuelles YoY -> Quartalsdurchschnitt)...")
    s = eurostat_get_since("ext_st_27_2020msbec",
        {"geo":"DE","stk_flow":"BAL_RT","indic_et":"TRD_VAL","partner":"WORLD","bclas_bec":"TOTAL"}, "2005-01")
    series["handelsb"] = quarterly_avg(yoy_from_raw(s))

    print("  6. Arbeitslosenquote (monthly ILO-Niveau -> Quartalsdurchschnitt, BA-Näherung)...")
    s = eurostat_get_since("une_rt_m",
        {"geo":"DE","s_adj":"SA","age":"TOTAL","sex":"T","unit":"PC_ACT"}, "2006-01")
    s = {k: round(v + BA_ILO_OFFSET, 2) for k, v in s.items()}
    series["alq"] = quarterly_avg(s)

    print("  7. Insolvenzen (monthly YoY -> Quartalsdurchschnitt, ab 2015)...")
    s = eurostat_get_since("sts_rb_m",
        {"geo":"DE","indic_bt":"BKRT","nace_r2":"B-S_X_O_S94","s_adj":"NSA","unit":"PCH_SM"}, "2006-01")
    series["insolvenz"] = quarterly_avg(s)

    print("  8. Inflation (monthly YoY -> Quartalsdurchschnitt)...")
    s = eurostat_get_since("prc_hicp_manr",
        {"geo":"DE","unit":"RCH_A","coicop":"CP00"}, "2006-01")
    series["inflation"] = quarterly_avg(s)
    # prc_hicp_manr hinkt bei Eurostat z.T. mehrere Monate hinterher (Stand
    # dieses Laufs: letzter Datenpunkt Dez. 2025, Datensatz seit Feb. 2026
    # nicht aktualisiert) — für das dadurch fehlende aktuellste Quartal wird
    # der ohnehin für diese Periode gepflegte FALLBACK-Wert verwendet, statt
    # das ganze Quartal aus der Historie zu kippen.
    if END_Q not in series["inflation"]:
        print(f"  ↳ inflation: {END_Q} bei Eurostat noch nicht verfügbar (Publikations-Lag) "
              f"— Fallback-Wert {FALLBACK['inflation']} verwendet")
        series["inflation"][END_Q] = FALLBACK["inflation"]

    print("  9. Einzelhandel (monthly YoY -> Quartalsdurchschnitt)...")
    s = eurostat_get_since("sts_trtu_m",
        {"geo":"DE","s_adj":"CA","nace_r2":"G47","indic_bt":"VOL_SLS","unit":"PCH_SM"}, "2006-01")
    series["einzelhdl"] = quarterly_avg(s)

    print("  10. Bauproduktion (monthly YoY -> Quartalsdurchschnitt)...")
    s = eurostat_get_since("sts_copr_m",
        {"geo":"DE","s_adj":"CA","nace_r2":"F","indic_bt":"PRD","unit":"PCH_SM"}, "2006-01")
    series["bau"] = quarterly_avg(s)

    print("  11. Arbeitsproduktivität (quarterly YoY)...")
    series["produktiv"] = eurostat_get_since("namq_10_lp_ulc",
        {"geo":"DE","s_adj":"SCA","na_item":"RLPR_PER","unit":"PCH_SM"}, START_Q)

    print("  12. Staatsschuldenquote (quarterly Niveau)...")
    series["schulden"] = eurostat_get_since("gov_10q_ggdebt",
        {"geo":"DE","unit":"PC_GDP","sector":"S13","na_item":"GD"}, START_Q)

    print()

    # Auf gemeinsames Quartalsraster bringen + fehlende frühe Quartale auffüllen
    grid = {}
    for k in WEIGHTS:
        grid[k] = backfill(series[k], quarters, k)

    # WIX je Quartal berechnen — exakt dieselben SCORING/WEIGHTS wie fetch_wix.py
    history = []
    for q in quarters:
        vals = {k: grid[k][q] for k in WEIGHTS if grid[k][q] is not None}
        if len(vals) < len(WEIGHTS):
            missing = set(WEIGHTS) - set(vals)
            print(f"  ⚠ {q}: fehlende Indikatoren {missing} — Quartal übersprungen")
            continue
        scores = {k: round(SCORING[k](v), 1) for k, v in vals.items()}
        wix = round(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 1)
        history.append({"quarter": q, "label": format_period(q), "wix": wix,
                         "raw": vals, "scores": scores})

    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    print(f"\n✓ {len(history)}/{len(quarters)} Quartale berechnet -> history.json")
    print("\nStichproben:")
    for q in ["2006-Q2", "2009-Q1", "2009-Q2", "2017-Q3", "2020-Q2", "2022-Q4", "2025-Q4"]:
        hit = next((h for h in history if h["quarter"] == q), None)
        print(f"  {q}: {hit['wix'] if hit else '—'}")


if __name__ == "__main__":
    main()
