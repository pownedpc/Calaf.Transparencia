#!/usr/bin/env python3
"""
score_calaf.py
Calcula el Score Calaf per a cada proveïdor i afegeix la columna calaf_score al CSV.
Executa des de la carpeta del repositori: python score_calaf.py

Requisits: pip install pandas
"""

import pandas as pd
import os, sys, re

INPUT_CSV  = "data.csv"
OUTPUT_CSV = "data.csv"
LLINDAR_MENOR = 15000
MIN_FACTURES_FRAGMENTACIO = 20
MIN_IMPORT_MONOPOLI = 5000

# ─────────────────────────────────────────────────────────────────────────────
# NORMALITZACIÓ DE NOMS (duplicats coneguts)
# ─────────────────────────────────────────────────────────────────────────────
NORMALITZACIO = {
    # ROMA — variants amb accents erronis, comes, espais
    'ROMÀINFRAESTRUCTURES ISERVEIS, SAU':       'ROMA INFRAESTRUCTURES I SERVEIS SA',
    'ROMA INFRAESTRUCTURES I SERVEIS,S.A.U.':   'ROMA INFRAESTRUCTURES I SERVEIS SA',
    'ROMA INFRAESTRUCTURES I SERVEIS SAU':       'ROMA INFRAESTRUCTURES I SERVEIS SA',
    'ROMA INFRAESTRUCTURES I SERVEI, SAU':       'ROMA INFRAESTRUCTURES I SERVEIS SA',
    'ROMA INFRAESTRUCTURES I SERVEI':            'ROMA INFRAESTRUCTURES I SERVEIS SA',
    # Afegeix aquí altres duplicats que trobis
}

def normalitzar(df):
    n = df['proveidor'].map(lambda x: NORMALITZACIO.get(str(x).strip(), str(x).strip()))
    canvis = (n != df['proveidor']).sum()
    if canvis > 0:
        print(f"  Normalitzats {canvis} registres amb noms duplicats")
    df['proveidor'] = n
    return df

# ─────────────────────────────────────────────────────────────────────────────
# CÀLCUL DE SCORES
# ─────────────────────────────────────────────────────────────────────────────
def calcular_scores(df):
    total_despesa = df['import'].sum()
    resultats = {}

    for prov, grup in df.groupby('proveidor'):
        total_prov     = grup['import'].sum()
        pct_pressupost = (total_prov / total_despesa) * 100
        anys_unics     = grup['any'].nunique()
        num_factures   = len(grup)

        # ── Factor 1: Pes pressupostari (0-50) ──
        if pct_pressupost >= 10:   f1 = 50
        elif pct_pressupost >= 5:  f1 = 35
        elif pct_pressupost >= 2:  f1 = 20
        elif pct_pressupost >= 1:  f1 = 10
        else:                       f1 = 0

        # ── Bonus gran contracte (0-10) ──
        bonus = 10 if pct_pressupost >= 10 else 0

        # ── Factor 2: Recurrència temporal (0-20) ──
        if anys_unics >= 6:    f2 = 20
        elif anys_unics >= 4:  f2 = 12
        elif anys_unics >= 2:  f2 = 6
        else:                   f2 = 0

        # ── Factor 3: Fragmentació (0-15) — només si >20 factures ──
        if num_factures >= MIN_FACTURES_FRAGMENTACIO:
            factures_menors = (grup['import'] < LLINDAR_MENOR).sum()
            pct_menors = (factures_menors / num_factures) * 100
            if pct_menors >= 80:   f3 = 15
            elif pct_menors >= 60: f3 = 10
            elif pct_menors >= 40: f3 = 6
            elif pct_menors >= 20: f3 = 3
            else:                   f3 = 0
        else:
            f3 = 0

        # ── Factor 4: Monopoli de concepte (0-15) ──
        if 'descripcio' in df.columns:
            conceptes_prov = set(grup['descripcio'].dropna().str.upper().str.strip())
            conceptes_tots = set(df[df['proveidor'] != prov]['descripcio'].dropna().str.upper().str.strip())
            conceptes_exclusius = conceptes_prov - conceptes_tots
            import_exclusiu = grup[
                grup['descripcio'].str.upper().str.strip().isin(conceptes_exclusius)
            ]['import'].sum()
            if import_exclusiu >= MIN_IMPORT_MONOPOLI:
                pct_exclusiu = (import_exclusiu / total_prov * 100) if total_prov > 0 else 0
                if pct_exclusiu >= 80:   f4 = 15
                elif pct_exclusiu >= 50: f4 = 10
                elif pct_exclusiu >= 20: f4 = 5
                else:                     f4 = 0
            else:
                f4 = 0
        else:
            f4 = 0

        score = min(100, round(f1 + bonus + f2 + f3 + f4, 1))
        resultats[prov] = {
            'calaf_score':          score,
            'calaf_pct_pressupost': round(pct_pressupost, 2),
            'calaf_anys':           anys_unics,
        }

    return resultats

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if not os.path.exists(INPUT_CSV):
        print(f"ERROR: No trobo {INPUT_CSV}")
        sys.exit(1)

    print(f"Llegint {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV)
    print(f"  {len(df)} files, {df['proveidor'].nunique()} proveidors")

    print("Normalitzant noms duplicats...")
    df = normalitzar(df)
    print(f"  Despres de normalitzar: {df['proveidor'].nunique()} proveidors unics")

    for col in ['calaf_score','calaf_pct_pressupost','calaf_anys']:
        if col in df.columns: df.drop(columns=[col], inplace=True)

    print("Calculant scores...")
    scores = calcular_scores(df)

    df['calaf_score']          = df['proveidor'].map(lambda p: scores.get(p,{}).get('calaf_score', 0))
    df['calaf_pct_pressupost'] = df['proveidor'].map(lambda p: scores.get(p,{}).get('calaf_pct_pressupost', 0))
    df['calaf_anys']           = df['proveidor'].map(lambda p: scores.get(p,{}).get('calaf_anys', 0))

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Guardat: {OUTPUT_CSV}")

    top = (df.groupby('proveidor')
             .first()[['calaf_score','calaf_pct_pressupost','calaf_anys']]
             .sort_values('calaf_score', ascending=False)
             .head(15))

    print(f"\n=== TOP 15 SCORE CALAF ===")
    print(f"{'Proveidor':<50} {'Score':>6} {'%presup':>8} {'Anys':>5}")
    print("-"*72)
    for nom, row in top.iterrows():
        print(f"{nom[:50]:<50} {row['calaf_score']:>6.1f} {row['calaf_pct_pressupost']:>7.2f}% {int(row['calaf_anys']):>5}")

    print("\nFet! Ara executa:")
    print("  git add data.csv")
    print("  git commit -m 'data: score Calaf v3 + normalitzacio noms'")
    print("  git push")

if __name__ == "__main__":
    main()
