"""
fetch_wix.py — WIX Deutschland v2.0 (12 Indikatoren, monatlich)
================================================================
Neue Indikatoren: Auftragseingänge, Exporte, Handelsbilanz,
                  Insolvenzen, Bauproduktion
Neue Gewichtung:  Staatsschuldenquote auf 10%
"""

import requests, json, re
from datetime import datetime
from typing import Optional

EUROSTAT   = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
HTML_FILE  = "index.html"
DATA_FILE  = "wix-data.json"

# ── Eurostat API ──────────────────────────────────────────────────────────────

def eurostat_get(dataset: str, params: dict, n: int = 16) -> dict:
    p = {**params, "format": "JSON", "lang": "EN", "lastTimePeriods": n}
    try:
        r = requests.get(f"{EUROSTAT}/{dataset}", params=p, timeout=30)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f"  ⚠ {dataset}: {e}")
        return {}
    try:
        dims     = d["id"]
        t_idx    = dims.index("TIME_PERIOD")
        t_cats   = d["dimension"]["TIME_PERIOD"]["category"]
        periods  = [k for k, _ in sorted(t_cats["index"].items(), key=lambda x: x[1])]
        size     = d["size"]
        stride   = 1
        for s in size[t_idx + 1:]:
            stride *= s
        vals = d.get("value", {})
        return {p: round(float(vals[str(i * stride)]), 2)
                for i, p in enumerate(periods)
                if str(i * stride) in vals}
    except Exception as e:
        print(f"  ⚠ Parse {dataset}: {e}")
        return {}

def latest(s: dict) -> tuple[Optional[str], Optional[float]]:
    if not s: return None, None
    k = sorted(s.keys())[-1]
    return k, s[k]

def quarterly_avg(monthly: dict) -> dict:
    q = {}
    for m, v in monthly.items():
        try:
            yr, mo = m.split("-")
            key = f"{yr}-Q{(int(mo)-1)//3+1}"
            q.setdefault(key, []).append(v)
        except Exception:
            continue
    return {k: round(sum(v)/len(v), 2) for k, v in q.items()}

# ── Scoring (alle 0–100) ──────────────────────────────────────────────────────

def cl(v, lo=0, hi=100): return max(lo, min(hi, v))

SCORING = {
    "bip":       lambda v: cl(50 + v / 3   * 50),   # BIP YoY %
    "industrie": lambda v: cl(50 + v / 5   * 50),   # Industrie YoY %
    "auftraege": lambda v: cl(50 + v / 5   * 50),   # Aufträge YoY %
    "exporte":   lambda v: cl(50 + v / 4   * 50),   # Exporte YoY %
    "handelsb":  lambda v: cl(50 + v / 10  * 50),   # Handelsbilanz YoY %
    "alq":       lambda v: cl(100 - (v-3)  * 17),   # Arbeitslosenquote %
    "insolvenz": lambda v: cl(50 - v / 30  * 50),   # Insolvenzen YoY % (invertiert)
    "inflation": lambda v: cl(100 - abs(v-2) * 25), # Inflation YoY %
    "einzelhdl": lambda v: cl(50 + v / 4   * 50),   # Einzelhandel YoY %
    "bau":       lambda v: cl(50 + v / 5   * 50),   # Bauproduktion YoY %
    "produktiv": lambda v: cl(50 + v / 2   * 50),   # Produktivität YoY %
    "schulden":  lambda v: cl(100 - (v-60) * 5),    # Schuldenquote % BIP
}

WEIGHTS = {
    "bip":       0.09,  # 9%
    "industrie": 0.09,  # 9%
    "auftraege": 0.07,  # 7%
    "exporte":   0.08,  # 8%
    "handelsb":  0.05,  # 5%
    "alq":       0.14,  # 14%
    "insolvenz": 0.08,  # 8%
    "inflation": 0.11,  # 11%
    "einzelhdl": 0.09,  # 9%
    "bau":       0.05,  # 5%
    "produktiv": 0.05,  # 5%
    "schulden":  0.10,  # 10%  ← erhöht
}

def calc_wix(vals: dict) -> float:
    return round(sum(SCORING[k](v) * WEIGHTS[k]
                     for k, v in vals.items() if k in SCORING), 1)

# ── Fallback-Werte (Q1 2026) ──────────────────────────────────────────────────

FALLBACK = {
    "period":    "2026-Q1",
    "bip":        0.4,   # BIP YoY %
    "industrie": -0.5,   # Industrieproduktion YoY %
    "auftraege": -3.0,   # Auftragseingänge YoY %
    "exporte":   -1.5,   # Exporte YoY %
    "handelsb":  -5.0,   # Handelsbilanz YoY-Veränderung %
    "alq":        6.5,   # Arbeitslosenquote %
    "insolvenz": 30.0,   # Insolvenzen YoY % (positiv = mehr = schlecht)
    "inflation":  2.2,   # VPI YoY %
    "einzelhdl": -2.5,   # Einzelhandel YoY %
    "bau":       -8.0,   # Bauproduktion YoY %
    "produktiv":  0.83,  # Arbeitsproduktivität YoY %
    "schulden":  66.5,   # Schuldenquote % BIP
}

# ── Historische WIX-Zeitreihe (alte 7-Ind. Formel, für Verlaufschart) ─────────
HIST_Q = ["Q2'06","Q3'06","Q4'06","Q1'07","Q2'07","Q3'07","Q4'07","Q1'08","Q2'08","Q3'08","Q4'08","Q1'09","Q2'09","Q3'09","Q4'09","Q1'10","Q2'10","Q3'10","Q4'10","Q1'11","Q2'11","Q3'11","Q4'11","Q1'12","Q2'12","Q3'12","Q4'12","Q1'13","Q2'13","Q3'13","Q4'13","Q1'14","Q2'14","Q3'14","Q4'14","Q1'15","Q2'15","Q3'15","Q4'15","Q1'16","Q2'16","Q3'16","Q4'16","Q1'17","Q2'17","Q3'17","Q4'17","Q1'18","Q2'18","Q3'18","Q4'18","Q1'19","Q2'19","Q3'19","Q4'19","Q1'20","Q2'20","Q3'20","Q4'20","Q1'21","Q2'21","Q3'21","Q4'21","Q1'22","Q2'22","Q3'22","Q4'22","Q1'23","Q2'23","Q3'23","Q4'23","Q1'24","Q2'24","Q3'24","Q4'24","Q1'25","Q2'25","Q3'25","Q4'25"]
HIST_V = [73,72,72,73,72,72,63,67,56,42,32,18,18,17,22,65,73,75,74,77,76,73,66,53,55,54,51,40,56,56,62,69,62,59,59,55,63,62,63,62,65,64,64,68,72,74,74,70,69,60,52,55,48,45,51,28,21,30,35,32,62,57,48,45,35,32,31,32,42,41,45,46,49,50,52,53,55,57,58]

# ── Daten holen ───────────────────────────────────────────────────────────────

def fetch_all() -> dict:
    print("Hole Daten von Eurostat (v2 — 12 Indikatoren)...\n")
    r = {}

    # 1. BIP YoY (quarterly)
    print("  1. BIP-Wachstum...")
    s = eurostat_get("namq_10_gdp", {"geo":"DE","unit":"CLV_PCH_SM","s_adj":"SCA","na_item":"B1GQ"})
    period, r["bip"] = latest(s)
    r["period"] = period
    print(f"     {period}: {r['bip']}%")

    # 2. Industrieproduktion YoY (monthly)
    print("  2. Industrieproduktion...")
    s = eurostat_get("sts_inpr_m", {"geo":"DE","s_adj":"SCA","nace_r2":"B-D","indic":"PROD","unit":"PCH_SM"})
    _, r["industrie"] = latest(s)
    print(f"     {r['industrie']}%")

    # 3. Auftragseingänge Industrie YoY (monthly)
    print("  3. Auftragseingänge Industrie...")
    s = eurostat_get("sts_inot_m", {"geo":"DE","s_adj":"SCA","nace_r2":"B-E36","indic":"NEW","unit":"PCH_SM"})
    _, r["auftraege"] = latest(s)
    print(f"     {r['auftraege']}%")

    # 4+5. Exporte und Handelsbilanz (monthly, Mio EUR)
    print("  4+5. Exporte & Handelsbilanz...")
    exp = eurostat_get("ext_st_27msbec", {"geo":"DE","tra_flow":"EXP","sitc06":"TOTAL","unit":"MIO_EUR"})
    imp = eurostat_get("ext_st_27msbec", {"geo":"DE","tra_flow":"IMP","sitc06":"TOTAL","unit":"MIO_EUR"})
    if exp and imp:
        shared = sorted(set(exp) & set(imp))
        if len(shared) >= 13:
            cur  = shared[-1]
            prev = shared[-13]  # Vorjahr
            r["exporte"]  = round((exp[cur] / exp[prev] - 1) * 100, 2) if exp.get(prev) else None
            bal_cur  = exp[cur]  - imp[cur]
            bal_prev = exp[prev] - imp[prev]
            r["handelsb"] = round((bal_cur / abs(bal_prev) - 1) * 100, 2) if bal_prev != 0 else None
            print(f"     Exporte YoY: {r['exporte']}%  |  Handelsbilanz YoY: {r['handelsb']}%")
    
    # 6. Arbeitslosenquote (monthly, ILO)
    print("  6. Arbeitslosenquote...")
    s = eurostat_get("une_rt_m", {"geo":"DE","s_adj":"SA","age":"TOTAL","sex":"T","unit":"PC_ACT"})
    _, r["alq"] = latest(s)
    print(f"     {r['alq']}%")

    # 7. Unternehmensinsolvenzen YoY (quarterly)
    print("  7. Unternehmensinsolvenzen...")
    s = eurostat_get("bsbs_ins_q", {"geo":"DE","indic":"INS_OPEN","unit":"NR"})
    if s and len(s) >= 5:
        qs = sorted(s.keys())
        cur_q, prev_q = qs[-1], qs[-5]  # Vorjahr
        r["insolvenz"] = round((s[cur_q] / s[prev_q] - 1) * 100, 2) if s.get(prev_q) else None
        print(f"     YoY: {r['insolvenz']}%")

    # 8. Inflationsrate VPI (monthly → Quartalsdurchschnitt)
    print("  8. Inflationsrate...")
    s = eurostat_get("prc_hicp_manr", {"geo":"DE","unit":"RCH_A","coicop":"CP00"}, n=6)
    _, r["inflation"] = latest(quarterly_avg(s)) if s else (None, None)
    print(f"     {r['inflation']}%")

    # 9. Einzelhandelsumsätze YoY (monthly)
    print("  9. Einzelhandelsumsätze...")
    s = eurostat_get("sts_trtu_m", {"geo":"DE","s_adj":"SCA","nace_r2":"G47","indic":"TOVT","unit":"PCH_SM"})
    _, r["einzelhdl"] = latest(s)
    print(f"     {r['einzelhdl']}%")

    # 10. Bauproduktion YoY (monthly)
    print("  10. Bauproduktion...")
    s = eurostat_get("sts_copr_m", {"geo":"DE","s_adj":"SCA","indic":"PROD","nace_r2":"F","unit":"PCH_SM"})
    _, r["bau"] = latest(s)
    print(f"     {r['bau']}%")

    # 11. Arbeitsproduktivität YoY (quarterly)
    print("  11. Arbeitsproduktivität...")
    s = eurostat_get("namq_10_lp_ulc", {"geo":"DE","s_adj":"SCA","na_item":"LP_I_NACE2","unit":"PCH_SM"})
    _, r["produktiv"] = latest(s)
    print(f"     {r['produktiv']}%")

    # 12. Staatsschuldenquote (quarterly)
    print("  12. Staatsschuldenquote...")
    s = eurostat_get("gov_10q_ggdebt", {"geo":"DE","unit":"PC_GDP","sector":"S13"})
    _, r["schulden"] = latest(s)
    print(f"     {r['schulden']}% BIP")

    return r

def apply_fallbacks(d: dict) -> dict:
    for k, v in FALLBACK.items():
        if d.get(k) is None:
            print(f"  ↳ Fallback '{k}': {v}")
            d[k] = v
    return d

def format_period(p: str) -> str:
    try:
        if "-Q" in p:
            y, q = p.split("-Q")
            return f"Q{q}'{y[2:]}"
        y, m = p.split("-")
        return f"{m}/{y[2:]}"
    except Exception:
        return p

# ── WIX JSON bauen ────────────────────────────────────────────────────────────

def build_json(raw: dict) -> dict:
    vals = {k: raw[k] for k in WEIGHTS if k in raw}
    wix  = calc_wix(vals)
    scores = {k: round(SCORING[k](v), 1) for k, v in vals.items()}
    period_label = format_period(raw.get("period", "?"))
    zone = ("Gesund" if wix>=70 else "Stabil" if wix>=55 else
            "Warnung" if wix>=42 else "Kritisch" if wix>=30 else "Systemkrise")
    all_q = HIST_Q + [period_label]
    all_v = HIST_V + [wix]
    return {
        "version":        "2.0",
        "generated":      datetime.utcnow().isoformat() + "Z",
        "current_period": period_label,
        "current_wix":    wix,
        "zone":           zone,
        "weights":        WEIGHTS,
        "raw":            {k: raw[k] for k in WEIGHTS},
        "scores":         scores,
        "history":        {"quarters": all_q, "values": all_v},
    }

# ── HTML updaten ──────────────────────────────────────────────────────────────

def update_html(wix: dict):
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print(f"  ⚠ {HTML_FILE} nicht gefunden.")
        return

    r   = wix["raw"]
    sc  = wix["scores"]
    h   = wix["history"]

    block = f"""// === WIX DATA v2 — AUTO-AKTUALISIERT VON fetch_wix.py ===
// Stand: {wix['generated']} UTC
const WIX_CURRENT = {wix['current_wix']};
const WIX_PERIOD  = "{wix['current_period']}";
const WIX_ZONE    = "{wix['zone']}";
const WIX_Q = {json.dumps(h['quarters'])};
const WIX_V = {json.dumps(h['values'])};
const WIX_RAW = {json.dumps(r, indent=2)};
const WIX_SCORES = {json.dumps(sc, indent=2)};
// === END WIX DATA ==="""

    new_html, n = re.subn(
        r"// === WIX DATA.*?// === END WIX DATA ===",
        block, html, flags=re.DOTALL)

    if n == 0:
        print("  ⚠ Daten-Marker nicht gefunden!")
    else:
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(new_html)
        print(f"  ✓ {HTML_FILE} aktualisiert")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"WIX Deutschland v2.0 — {datetime.utcnow():%Y-%m-%d %H:%M UTC}")
    print(f"{'='*60}\n")

    raw = fetch_all()
    raw = apply_fallbacks(raw)
    wix = build_json(raw)

    print(f"\n{'='*60}")
    print(f"WIX {wix['current_period']}: {wix['current_wix']}  →  {wix['zone']}")
    print(f"{'='*60}")
    for k, s in wix['scores'].items():
        bar = '█' * int(s/10) + '░' * (10 - int(s/10))
        print(f"  {k:12s} {bar}  {s:.0f}/100  (Roh: {wix['raw'][k]})")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(wix, f, indent=2, ensure_ascii=False)
    print(f"\n✓ {DATA_FILE} gespeichert")

    update_html(wix)
    print("\nFertig.\n")

if __name__ == "__main__":
    main()
