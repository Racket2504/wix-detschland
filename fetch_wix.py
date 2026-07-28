"""
fetch_wix.py — WIX Deutschland Daten-Fetcher
=============================================
Holt aktuelle Wirtschaftsdaten von Eurostat und berechnet den WIX.
Aktualisiert index.html mit neuen Daten.

Datenquellen:
- Eurostat REST API (kostenlos, kein API-Key nötig)
- Fallback: letzte bekannte Werte falls API nicht verfügbar
"""

import requests
import json
import re
import sys
from datetime import datetime, date
from typing import Optional

# ── Konfiguration ─────────────────────────────────────────────────────────────

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
HTML_FILE = "index.html"
DATA_FILE = "wix-data.json"
N_PERIODS = 12  # Letzten 12 Quartale von API holen

# ── Eurostat API ──────────────────────────────────────────────────────────────

def eurostat_get(dataset: str, params: dict, n: int = N_PERIODS) -> dict:
    """Holt Zeitreihe von Eurostat. Gibt {period: value} zurück."""
    p = {**params, "format": "JSON", "lang": "EN", "lastTimePeriods": n}
    try:
        r = requests.get(f"{EUROSTAT}/{dataset}", params=p, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠ Eurostat {dataset} nicht verfügbar: {e}")
        return {}

    try:
        dims = data["id"]
        time_idx = dims.index("TIME_PERIOD")
        time_cats = data["dimension"]["TIME_PERIOD"]["category"]
        # Sortiere nach Index-Position
        times = sorted(time_cats["index"].items(), key=lambda x: x[1])
        periods = [t[0] for t in times]

        size = data["size"]
        stride = 1
        for s in size[time_idx + 1:]:
            stride *= s

        raw_values = data.get("value", {})
        result = {}
        for pos, period in enumerate(periods):
            flat = pos * stride
            v = raw_values.get(str(flat)) or raw_values.get(flat)
            if v is not None:
                result[period] = round(float(v), 2)
        return result
    except Exception as e:
        print(f"  ⚠ Fehler beim Parsen von {dataset}: {e}")
        return {}


def latest(series: dict) -> tuple[Optional[str], Optional[float]]:
    """Gibt (period, value) des neuesten Eintrags zurück."""
    if not series:
        return None, None
    period = sorted(series.keys())[-1]
    return period, series[period]


def quarterly_avg(monthly: dict, n_months: int = 3) -> dict:
    """Konvertiert Monatsdaten → Quartalsdurchschnitte."""
    quarters = {}
    months = sorted(monthly.keys())[-n_months * 4:]  # Letzte 4 Quartale
    for m in months:
        try:
            y, mo = m.split("-")
            q = (int(mo) - 1) // 3 + 1
            key = f"{y}-Q{q}"
            if key not in quarters:
                quarters[key] = []
            quarters[key].append(monthly[m])
        except Exception:
            continue
    return {k: round(sum(v) / len(v), 2) for k, v in quarters.items() if v}


# ── Scoring ───────────────────────────────────────────────────────────────────

def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))

def score_bip(v):    return clamp(50 + v / 3 * 50)
def score_alq(v):    return clamp(100 - (v - 3) * 17)
def score_infl(v):   return clamp(100 - abs(v - 2) * 25)
def score_ind(v):    return clamp(50 + v / 5 * 50)
def score_eh(v):     return clamp(50 + v / 4 * 50)
def score_prod(v):   return clamp(50 + v / 2 * 50)
def score_schuld(v): return clamp(100 - (v - 60) * 5)

def calc_wix(bip, alq, infl, ind, eh, prod, schuld):
    return round(
        score_bip(bip)    * 0.25 +
        score_alq(alq)    * 0.20 +
        score_infl(infl)  * 0.15 +
        score_ind(ind)    * 0.20 +
        score_eh(eh)      * 0.10 +
        score_prod(prod)  * 0.05 +
        score_schuld(schuld) * 0.05,
        1
    )


# ── Fallback-Daten (letzter bekannter Stand Q1 2026) ─────────────────────────

FALLBACK = {
    "period":  "2026-Q1",
    "bip":     0.4,
    "alq":     6.5,
    "infl":    2.2,
    "ind":    -0.5,
    "eh":     -2.5,
    "prod":    0.83,
    "schuld": 66.5,
}

# Historische Zeitreihe (Q2 2006 - Q4 2025, für Charts)
HISTORICAL = {
    "quarters": ["Q2'06","Q3'06","Q4'06","Q1'07","Q2'07","Q3'07","Q4'07","Q1'08","Q2'08","Q3'08","Q4'08","Q1'09","Q2'09","Q3'09","Q4'09","Q1'10","Q2'10","Q3'10","Q4'10","Q1'11","Q2'11","Q3'11","Q4'11","Q1'12","Q2'12","Q3'12","Q4'12","Q1'13","Q2'13","Q3'13","Q4'13","Q1'14","Q2'14","Q3'14","Q4'14","Q1'15","Q2'15","Q3'15","Q4'15","Q1'16","Q2'16","Q3'16","Q4'16","Q1'17","Q2'17","Q3'17","Q4'17","Q1'18","Q2'18","Q3'18","Q4'18","Q1'19","Q2'19","Q3'19","Q4'19","Q1'20","Q2'20","Q3'20","Q4'20","Q1'21","Q2'21","Q3'21","Q4'21","Q1'22","Q2'22","Q3'22","Q4'22","Q1'23","Q2'23","Q3'23","Q4'23","Q1'24","Q2'24","Q3'24","Q4'24","Q1'25","Q2'25","Q3'25","Q4'25"],
    "values":   [73,72,72,73,72,72,63,67,56,42,32,18,18,17,22,65,73,75,74,77,76,73,66,53,55,54,51,40,56,56,62,69,62,59,59,55,63,62,63,62,65,64,64,68,72,74,74,70,69,60,52,55,48,45,51,28,21,30,35,32,62,57,48,45,35,32,31,32,42,41,45,46,49,50,52,53,55,57,58],
}


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def fetch_current_data() -> dict:
    """Holt aktuelle Quartalsdaten von Eurostat."""
    print("Hole Daten von Eurostat...")
    result = {}

    # 1. BIP YoY (GDP at market prices, % change vs prev year)
    print("  → BIP-Wachstum (namq_10_gdp)...")
    bip_s = eurostat_get("namq_10_gdp", {
        "geo": "DE", "unit": "CLV_PCH_SM", "s_adj": "SCA", "na_item": "B1GQ"
    })
    period, result["bip"] = latest(bip_s)
    result["period"] = period
    print(f"     {period}: {result['bip']}%")

    # 2. Arbeitslosenquote (ILO harmonized, quarterly)
    print("  → Arbeitslosenquote (une_rt_q)...")
    alq_s = eurostat_get("une_rt_q", {
        "geo": "DE", "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"
    })
    _, result["alq"] = latest(alq_s)
    print(f"     {result['alq']}%")

    # 3. Inflation HICP (monatlich → Quartalsdurchschnitt)
    print("  → Inflationsrate (prc_hicp_manr)...")
    infl_m = eurostat_get("prc_hicp_manr", {
        "geo": "DE", "unit": "RCH_A", "coicop": "CP00"
    }, n=12)
    infl_q = quarterly_avg(infl_m)
    _, result["infl"] = latest(infl_q)
    print(f"     {result['infl']}%")

    # 4. Industrieproduktion YoY (quarterly)
    print("  → Industrieproduktion (sts_inpr_q)...")
    ind_s = eurostat_get("sts_inpr_q", {
        "geo": "DE", "s_adj": "SCA", "nace_r2": "B-D",
        "indic": "PROD", "unit": "PCH_SM"
    })
    _, result["ind"] = latest(ind_s)
    print(f"     {result['ind']}%")

    # 5. Einzelhandel YoY (quarterly)
    print("  → Einzelhandelsumsätze (sts_trtu_q)...")
    eh_s = eurostat_get("sts_trtu_q", {
        "geo": "DE", "s_adj": "SCA", "nace_r2": "G47",
        "indic": "TOVT", "unit": "PCH_SM"
    })
    _, result["eh"] = latest(eh_s)
    print(f"     {result['eh']}%")

    # 6. Arbeitsproduktivität (BIP je Erwerbstätigen, YoY)
    print("  → Arbeitsproduktivität (namq_10_lp_ulc)...")
    prod_s = eurostat_get("namq_10_lp_ulc", {
        "geo": "DE", "s_adj": "SCA",
        "na_item": "LP_I_NACE2", "unit": "PCH_SM"
    })
    _, result["prod"] = latest(prod_s)
    print(f"     {result['prod']}%")

    # 7. Staatsschuldenquote (% BIP, quarterly)
    print("  → Staatsschuldenquote (gov_10q_ggdebt)...")
    schuld_s = eurostat_get("gov_10q_ggdebt", {
        "geo": "DE", "unit": "PC_GDP", "sector": "S13"
    })
    _, result["schuld"] = latest(schuld_s)
    print(f"     {result['schuld']}% BIP")

    return result


def apply_fallbacks(data: dict) -> dict:
    """Ersetzt fehlende Werte durch Fallback-Daten."""
    for key, val in FALLBACK.items():
        if data.get(key) is None:
            print(f"  ⚠ Fallback für '{key}': {val}")
            data[key] = val
    return data


def build_wix_json(current: dict) -> dict:
    """Erstellt vollständiges WIX-Datenobjekt."""
    wix_current = calc_wix(
        current["bip"], current["alq"], current["infl"],
        current["ind"], current["eh"], current["prod"], current["schuld"]
    )

    # Quartal formatieren (z.B. "2026-Q1" → "Q1'26")
    period = current.get("period", "?")
    try:
        y, q = period.split("-Q")
        period_label = f"Q{q}'{y[2:]}"
    except Exception:
        period_label = period

    # Histor. Zeitreihe + aktueller Wert zusammenführen
    all_quarters = HISTORICAL["quarters"] + [period_label]
    all_values   = HISTORICAL["values"]   + [wix_current]

    return {
        "generated":     datetime.utcnow().isoformat() + "Z",
        "current_period": period_label,
        "current_wix":   wix_current,
        "current_raw": {
            "bip":    current["bip"],
            "alq":    current["alq"],
            "infl":   current["infl"],
            "ind":    current["ind"],
            "eh":     current["eh"],
            "prod":   current["prod"],
            "schuld": current["schuld"],
        },
        "scores": {
            "bip":    round(score_bip(current["bip"]),    1),
            "alq":    round(score_alq(current["alq"]),    1),
            "infl":   round(score_infl(current["infl"]),  1),
            "ind":    round(score_ind(current["ind"]),     1),
            "eh":     round(score_eh(current["eh"]),       1),
            "prod":   round(score_prod(current["prod"]),   1),
            "schuld": round(score_schuld(current["schuld"]), 1),
        },
        "history": {
            "quarters": all_quarters,
            "values":   all_values,
        }
    }


def update_html(wix: dict):
    """Injiziert aktuelle WIX-Daten in index.html."""
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print(f"  ⚠ {HTML_FILE} nicht gefunden. Nur JSON wird gespeichert.")
        return

    # Generiertes JS-Daten-Block
    raw = wix["current_raw"]
    hist = wix["history"]
    scores = wix["scores"]

    data_block = f"""// === WIX DATA — AUTO-AKTUALISIERT VON fetch_wix.py ===
// Stand: {wix['generated']} UTC
const WIX_CURRENT = {wix['current_wix']};
const WIX_PERIOD  = "{wix['current_period']}";
const WIX_Q = {json.dumps(hist['quarters'])};
const WIX_V = {json.dumps(hist['values'])};
const WIX_RAW = {json.dumps(raw, indent=2)};
const WIX_SCORES = {json.dumps(scores, indent=2)};
// === END WIX DATA ==="""

    # Ersetze Block zwischen Markern
    pattern = r"// === WIX DATA.*?// === END WIX DATA ==="
    new_html, n = re.subn(pattern, data_block, html, flags=re.DOTALL)

    if n == 0:
        print(f"  ⚠ Daten-Marker in {HTML_FILE} nicht gefunden! Füge oben im <script> Bereich hinzu:")
        print("  // === WIX DATA — AUTO-AKTUALISIERT VON fetch_wix.py ===")
        print("  // === END WIX DATA ===")
    else:
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"  ✓ {HTML_FILE} aktualisiert.")


def main():
    print(f"\n{'='*60}")
    print(f"WIX Deutschland — Daten-Fetcher")
    print(f"Gestartet: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    # Daten holen
    current = fetch_current_data()
    current = apply_fallbacks(current)

    # WIX berechnen
    wix = build_wix_json(current)
    print(f"\n{'='*60}")
    print(f"WIX {wix['current_period']}: {wix['current_wix']}")
    zone = ("Gesund" if wix['current_wix']>=70 else
            "Stabil" if wix['current_wix']>=55 else
            "Warnung" if wix['current_wix']>=42 else
            "Kritisch" if wix['current_wix']>=30 else "Systemkrise")
    print(f"Zone: {zone}")
    print(f"{'='*60}\n")

    # JSON speichern
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(wix, f, indent=2, ensure_ascii=False)
    print(f"✓ {DATA_FILE} gespeichert.")

    # HTML aktualisieren
    update_html(wix)
    print("\nFertig.")


if __name__ == "__main__":
    main()
