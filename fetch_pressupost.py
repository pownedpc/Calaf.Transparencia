"""
fetch_pressupost.py — Calaf Transparència
Versió 2 — mapatge categories reals data.csv vs programes pressupostaris
"""

import requests, csv, json, io, os
from datetime import datetime
from collections import defaultdict

CODI_ENS   = "803120002"
OUTPUT_DIR = "json"
DATA_CSV   = "data.csv"
CSV_URL    = "https://dadesobertes.seu-e.cat/csv/ge-p-pressupostos-per-programes-detallat-darrers-anys.csv"

# ── MAPATGE: codi programa (nivell 3) → categories factures ──────────────────
# Categories reals: Altres, Assessoria i estudis, Comunicació, Cultura i Festes,
# Lloguers, Manteniment, Material i subministres, Obra pública, Personal i contractació,
# Seguretat, Serveis, Serveis Socials, Subministraments, Subvencions i convenis,
# Subvenció, Vehicles i transport

MAPATGE = {
    # Serveis generals / administració
    "920": ["Serveis", "Assessoria i estudis", "Comunicació", "Lloguers", "Material i subministres", "Subministraments"],
    "912": ["Personal i contractació"],
    "924": ["Comunicació"],
    "491": ["Comunicació", "Assessoria i estudis"],

    # Serveis socials
    "231": ["Serveis Socials", "Serveis"],
    "232": ["Serveis Socials"],
    "233": ["Serveis Socials"],

    # Educació
    "320": ["Serveis", "Material i subministres", "Subministraments"],
    "323": ["Serveis", "Material i subministres"],
    "326": ["Serveis"],

    # Cultura i festes
    "332": ["Cultura i Festes", "Serveis"],
    "333": ["Cultura i Festes", "Manteniment"],
    "334": ["Cultura i Festes", "Serveis"],
    "337": ["Cultura i Festes"],
    "338": ["Cultura i Festes"],

    # Esports
    "341": ["Serveis", "Cultura i Festes"],
    "342": ["Manteniment", "Serveis", "Subministraments"],

    # Medi ambient / parcs
    "171": ["Manteniment", "Serveis"],
    "172": ["Serveis", "Assessoria i estudis"],
    "170": ["Serveis", "Assessoria i estudis"],

    # Benestar comunitari
    "160": ["Serveis", "Manteniment"],          # clavegueram
    "161": ["Subministraments", "Serveis"],      # aigua
    "162": ["Serveis"],                          # residus
    "163": ["Serveis"],                          # neteja viària
    "164": ["Manteniment", "Serveis"],           # cementiri
    "165": ["Subministraments", "Manteniment"],  # llum

    # Habitatge i urbanisme
    "150": ["Assessoria i estudis", "Serveis"],
    "151": ["Obra pública", "Assessoria i estudis"],
    "152": ["Manteniment", "Obra pública"],
    "153": ["Obra pública", "Manteniment"],

    # Seguretat
    "132": ["Seguretat", "Serveis"],
    "134": ["Vehicles i transport", "Serveis"],
    "135": ["Serveis"],

    # Foment ocupació
    "241": ["Serveis", "Subvencions i convenis"],

    # Promoció econòmica
    "430": ["Serveis", "Assessoria i estudis"],
    "432": ["Serveis", "Comunicació"],
    "433": ["Assessoria i estudis", "Serveis"],

    # Òrgans de govern
    "912": ["Personal i contractació"],

    # Subvencions / transferències
    "480": ["Subvencions i convenis", "Subvenció"],
    "489": ["Subvencions i convenis", "Subvenció"],
}

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"\n=== Fetch Pressupost Calaf v2 ===")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    print("→ Descarregant CSV AOC...")
    r = requests.get(CSV_URL, timeout=180)
    r.raise_for_status()
    r.encoding = "utf-8-sig"

    # Filtrar per Calaf
    partides = []
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        codi = str(row.get("CODI_ENS", row.get("codi_ens",""))).strip().lstrip("0")
        if codi == CODI_ENS.lstrip("0"):
            partides.append(row)

    print(f"✓ Partides Calaf: {len(partides)}")

    # Organitzar per any
    per_any = defaultdict(lambda: defaultdict(list))
    for p in partides:
        any_ex  = str(p.get("ANY_EXERCICI","")).strip()
        tipus   = str(p.get("TIPUS_PARTIDA","")).strip()
        classif = str(p.get("TIPUS_CLASSIF","")).strip()
        codi_p  = str(p.get("CODI_PANTALLA","")).strip()
        nivell  = str(p.get("NIVELL","")).strip()
        desc    = str(p.get("DESCRIPCIO","")).strip()
        try:
            import_val = float(str(p.get("IMPORT","0")).replace(",","."))
        except:
            import_val = 0.0

        if tipus == "D" and classif == "F" and import_val > 0:
            per_any[any_ex][codi_p].append({
                "codi": codi_p, "descripcio": desc,
                "import": import_val, "nivell": nivell,
            })

    anys = sorted(per_any.keys(), reverse=True)
    print(f"✓ Anys: {anys}")

    # Carregar factures per any i categoria
    factures_per_any_cat = defaultdict(lambda: defaultdict(float))
    if os.path.exists(DATA_CSV):
        with open(DATA_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    imp = float(row.get("import","0") or 0)
                except:
                    imp = 0.0
                cat   = row.get("categoria","Altres").strip()
                any_f = str(row.get("any","")).strip()
                factures_per_any_cat[any_f][cat] += imp
        print(f"✓ Factures carregades")

    # Calcular execució per any
    execucio = {}
    for any_ex in anys:
        cats_any = factures_per_any_cat.get(any_ex, {})
        resultat_n2 = []

        # Partides nivell 2 (blocs principals)
        for codi_p, llista in per_any[any_ex].items():
            top = [p for p in llista if p["nivell"] == "2"]
            if not top:
                continue
            p = top[0]

            # Sumar execució de totes les subpartides (nivell 3) d'aquest bloc
            import_executat = 0.0
            cats_coincidents = []
            prefix = codi_p  # e.g. "16", "32", "33"

            for codi3, llista3 in per_any[any_ex].items():
                if codi3.startswith(prefix) and len(codi3) == len(prefix) + 1:
                    if codi3 in MAPATGE:
                        for cat in MAPATGE[codi3]:
                            imp = cats_any.get(cat, 0)
                            if imp > 0:
                                import_executat += imp
                                if cat not in cats_coincidents:
                                    cats_coincidents.append(cat)

            pct = round(import_executat / p["import"] * 100, 1) if p["import"] > 0 else None

            resultat_n2.append({
                "codi":                p["codi"],
                "descripcio":          p["descripcio"],
                "import_pressupostat": round(p["import"], 2),
                "import_executat":     round(import_executat, 2),
                "pct_execucio":        pct,
                "categories":          cats_coincidents,
                "te_dades":            import_executat > 0,
            })

        execucio[any_ex] = sorted(resultat_n2, key=lambda x: x["import_pressupostat"], reverse=True)

    # Resum
    print(f"\n── Execució {anys[0]} ──")
    for e in execucio.get(anys[0], [])[:15]:
        pct = f"{e['pct_execucio']}%" if e["pct_execucio"] else "—"
        print(f"  {e['codi']:4}  {e['descripcio'][:42]:42}  {e['import_pressupostat']:>10,.0f}€  exec: {pct}")

    # Guardar
    output = {
        "municipi": "Calaf", "codi_ens": CODI_ENS,
        "actualitzat": datetime.now().isoformat(),
        "nota": "Pressupost inicial. Execució estimada via creuament categories factures vs programes funcionals.",
        "anys": anys,
        "execucio": execucio,
    }
    path = os.path.join(OUTPUT_DIR, "pressupost.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Guardat: {path}")
    print("=== Fi ===\n")

if __name__ == "__main__":
    main()
