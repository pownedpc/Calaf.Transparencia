#!/usr/bin/env python3
"""
fetch_contractes.py - Calaf Transparencia

Consulta l'API de dades obertes AOC/CKAN del Perfil de Contractant (PSCP),
filtra els contractes de l'Ajuntament de Calaf i genera:

  - calaf_contractes.csv
  - json/contractes.json

També creua adjudicataris amb els proveidors de data.csv per NIF i per nom
normalitzat. No requereix dependencies externes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AJUNTAMENT_NOM = "Ajuntament de Calaf"
AJUNTAMENT_NIF = "P0803100G"
AJUNTAMENT_DIR3 = "L01080313"

API_SQL_URL = "https://dadesobertes.seu-e.cat/api/3/action/datastore_search_sql"
PSCP_RESOURCE_ID = "7448c675-8880-464e-9980-1b92119e59c8"

DATA_CSV = Path("data.csv")
OUTPUT_CSV = Path("calaf_contractes.csv")
OUTPUT_JSON = Path("json") / "contractes.json"

CSV_FIELDS = [
    "data_adjudicacio",
    "any",
    "expedient",
    "fase",
    "procediment",
    "tipus_contracte",
    "objecte",
    "cpv",
    "nif_adjudicatari",
    "adjudicatari",
    "import_sense_iva",
    "import_amb_iva",
    "valor_estimat",
    "ofertes_rebudes",
    "durada",
    "enllac",
    "font",
    "factures_match",
    "factures_import",
    "factures_count",
]


def api_get(sql: str) -> dict[str, Any]:
    url = API_SQL_URL + "?" + urllib.parse.urlencode({"sql": sql})
    req = urllib.request.Request(url, headers={"User-Agent": "CalafTransparencia/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError(payload)
    return payload["result"]


def sql_quote(value: str) -> str:
    return value.replace("'", "''")


def fetch_contractes(limit: int = 5000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    where = (
        f'"NOM_ORGAN" = \'{sql_quote(AJUNTAMENT_NOM)}\' '
        f'OR "CODI_DIR3" = \'{sql_quote(AJUNTAMENT_DIR3)}\''
    )

    while True:
        sql = (
            f'SELECT * FROM "{PSCP_RESOURCE_ID}" '
            f"WHERE {where} "
            'ORDER BY "DATA_ADJUDICACIO_CONTRACTE" DESC, "_id" DESC '
            f"LIMIT {limit} OFFSET {offset}"
        )
        batch = api_get(sql).get("records", [])
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    return rows


def to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def clean_nif(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"\b(SL|S\.L\.|SLU|S\.L\.U\.|SA|S\.A\.|SAU|S\.A\.U\.|SCCL|SCP)\b", "", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def date10(value: Any) -> str:
    text = str(value or "")
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else ""


def clean_text(value: Any) -> str:
    text = re.sub(r"\\[rn]", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def load_factures_index(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_nif: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return by_nif, by_name

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            amount = to_float(row.get("import"))
            nif = clean_nif(row.get("nif_tercer"))
            name = norm_name(row.get("proveidor"))
            for key, index in ((nif, by_nif), (name, by_name)):
                if not key:
                    continue
                item = index.setdefault(key, {"count": 0, "import": 0.0})
                item["count"] += 1
                item["import"] += amount

    return by_nif, by_name


def normalize_contract(row: dict[str, Any], fact_by_nif: dict[str, dict[str, Any]], fact_by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    nif = clean_nif(row.get("IDENTIFICACIO_ADJUDICATARI"))
    adjudicatari = clean_text(row.get("DENOMINACIO_ADJUDICATARI"))
    name_key = norm_name(adjudicatari)
    factura_hit = fact_by_nif.get(nif) if nif else None
    match_type = "nif" if factura_hit else ""
    if not factura_hit and name_key:
        factura_hit = fact_by_name.get(name_key)
        match_type = "nom" if factura_hit else ""

    data_adj = date10(row.get("DATA_ADJUDICACIO_CONTRACTE")) or date10(row.get("DATA_PUBLICACIO_ADJUDICACIO")) or date10(row.get("DATA_PUBLICACIO_CONTRACTE_AGREGAT"))
    any_adj = data_adj[:4] if data_adj else ""
    import_sense = to_float(row.get("IMPORT_ADJUDICACIO_SENSE_IVA"))
    import_amb = to_float(row.get("IMPORT_ADJUDICACIO_AMB_IVA"))

    return {
        "data_adjudicacio": data_adj,
        "any": any_adj,
        "expedient": clean_text(row.get("CODI_EXPEDIENT")),
        "fase": clean_text(row.get("FASE_PUBLICACIO")),
        "procediment": clean_text(row.get("PROCEDIMENT")),
        "tipus_contracte": clean_text(row.get("TIPUS_CONTRACTE")),
        "objecte": clean_text(row.get("OBJECTE_CONTRACTE") or row.get("DENOMINACIO")),
        "cpv": clean_text(row.get("CODI_CPV")),
        "nif_adjudicatari": nif,
        "adjudicatari": adjudicatari,
        "import_sense_iva": round(import_sense, 2),
        "import_amb_iva": round(import_amb, 2),
        "valor_estimat": round(to_float(row.get("VALOR_ESTIMAT_CONTRACTE") or row.get("VALOR_ESTIMAT_EXPEDIENT")), 2),
        "ofertes_rebudes": clean_text(row.get("OFERTES_REBUDES")),
        "durada": clean_text(row.get("DURADA_CONTRACTE")),
        "enllac": clean_text(row.get("ENLLAC_PUBLICACIO")),
        "font": "AOC PSCP",
        "factures_match": match_type,
        "factures_import": round(float(factura_hit["import"]), 2) if factura_hit else 0,
        "factures_count": int(factura_hit["count"]) if factura_hit else 0,
    }


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, Any]], raw_count: int, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = sum(to_float(r["import_amb_iva"]) for r in rows)
    matches = [r for r in rows if r["factures_match"]]
    payload = {
        "municipi": "Calaf",
        "ajuntament_nif": AJUNTAMENT_NIF,
        "ajuntament_dir3": AJUNTAMENT_DIR3,
        "font": "AOC PSCP - API CKAN/DataStore",
        "resource_id": PSCP_RESOURCE_ID,
        "actualitzat": datetime.now(timezone.utc).isoformat(),
        "total_api": raw_count,
        "total": len(rows),
        "import_amb_iva": round(total, 2),
        "coincidencies_factures": len(matches),
        "contractes": rows,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarrega contractes PSCP de Calaf via API AOC")
    parser.add_argument("--limit", type=int, default=5000, help="Mida de pagina de l'API")
    args = parser.parse_args()

    print("=== Calaf Transparencia - Contractes AOC/PSCP ===")
    print(f"Filtre: {AJUNTAMENT_NOM} / {AJUNTAMENT_DIR3} / {AJUNTAMENT_NIF}")

    fact_by_nif, fact_by_name = load_factures_index(DATA_CSV)
    raw = fetch_contractes(limit=args.limit)
    rows = [normalize_contract(r, fact_by_nif, fact_by_name) for r in raw]
    rows.sort(key=lambda r: (r["data_adjudicacio"], r["expedient"]), reverse=True)

    write_csv(rows, OUTPUT_CSV)
    write_json(rows, len(raw), OUTPUT_JSON)

    total = sum(float(r["import_amb_iva"]) for r in rows)
    matches = sum(1 for r in rows if r["factures_match"])
    print(f"Contractes: {len(rows)}")
    print(f"Import adjudicat amb IVA: {total:,.2f} EUR")
    print(f"Coincidencies amb factures: {matches}")
    print(f"Guardat: {OUTPUT_CSV}")
    print(f"Guardat: {OUTPUT_JSON}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
