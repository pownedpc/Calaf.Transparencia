#!/usr/bin/env python3
"""
fetch_borme_adjudicataris.py - Calaf Transparencia

Prepara una capa mercantil per als adjudicataris dels contractes de Calaf.

Entrada principal:
  - calaf_contractes.csv

Entrades opcionals:
  - --empreses empreses.csv|json|jsonl
  - --carrecs carrecs.csv|json|jsonl

Sortida:
  - json/borme_adjudicataris.json

El script funciona sense dependencies externes. Si encara no hi ha extracte BORME
local, genera igualment un fitxer amb els adjudicataris marcats com a pendents,
per deixar la interfície preparada sense inventar dades mercantils.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACTES_CSV = Path("calaf_contractes.csv")
OUTPUT_JSON = Path("json") / "borme_adjudicataris.json"


def clean_nif(value: Any) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"\b(SL|S\.L\.|SLU|S\.L\.U\.|SA|S\.A\.|SAU|S\.A\.U\.|SCCL|SCP|CB)\b", "", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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


def pick(row: dict[str, Any], *names: str) -> Any:
    lower = {str(k).lower(): v for k, v in row.items()}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        value = lower.get(name.lower())
        if value not in (None, ""):
            return value
    return ""


def read_records(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    if not path.exists():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("records", "data", "empreses", "carrecs"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        raise ValueError(f"No s'ha trobat cap llista de registres a {path}")
    raise ValueError(f"Format no suportat: {path.suffix}")


def load_adjudicataris(path: Path) -> dict[str, dict[str, Any]]:
    adjudicataris: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nif = clean_nif(row.get("nif_adjudicatari"))
            nom = str(row.get("adjudicatari") or "").strip()
            nom_key = norm_name(nom)
            key = nif or nom_key
            if not key:
                continue
            item = adjudicataris.setdefault(key, {
                "nif": nif,
                "nom": nom,
                "nom_normalitzat": nom_key,
                "contractes_count": 0,
                "contractes_import": 0.0,
            })
            item["contractes_count"] += 1
            item["contractes_import"] += to_float(row.get("import_amb_iva") or row.get("import_sense_iva") or row.get("valor_estimat"))
            if len(nom) > len(item["nom"]):
                item["nom"] = nom
                item["nom_normalitzat"] = nom_key
    return adjudicataris


def index_empreses(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_nif: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        nif = clean_nif(pick(row, "nif", "cif", "nif_empresa", "identificador"))
        nom = str(pick(row, "nom", "empresa", "denominacion", "denominacio", "razon_social", "razao_social")).strip()
        name_key = norm_name(nom)
        if nif:
            by_nif[nif] = row
        if name_key:
            by_name[name_key] = row
    return by_nif, by_name


def index_carrecs(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    by_nif: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        nif = clean_nif(pick(row, "nif", "cif", "nif_empresa", "identificador_empresa"))
        nom = str(pick(row, "empresa", "nom_empresa", "denominacion", "denominacio", "razon_social")).strip()
        name_key = norm_name(nom)
        if nif:
            by_nif[nif].append(row)
        if name_key:
            by_name[name_key].append(row)
    return by_nif, by_name


def is_active_charge(row: dict[str, Any]) -> bool:
    text = " ".join(str(v).lower() for v in row.values())
    return not any(word in text for word in ("cessament", "cese", "revocacion", "revocacio", "dimision", "dimissio"))


def summarize_charge(row: dict[str, Any]) -> dict[str, str]:
    return {
        "nom": str(pick(row, "persona", "nom_persona", "administrador", "apoderado", "carrec_persona")).strip(),
        "carrec": str(pick(row, "carrec", "cargo", "tipus_carrec", "acto")).strip(),
        "data": str(pick(row, "data", "fecha", "data_publicacio", "fecha_publicacion")).strip(),
    }


def build_flags(empresa: dict[str, Any], carrecs: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    estat = " ".join(str(pick(empresa, "estat", "estado", "situacio", "situacion", "acte", "acto", "actos")).lower().split())
    if any(word in estat for word in ("dissolta", "disuelta", "extingida", "extincio", "extincion")):
        flags.append("empresa_dissolta")
    if any(word in estat for word in ("concurs", "insolvencia")):
        flags.append("concurs")
    capital = to_float(pick(empresa, "capital", "capital_social", "capital_euros"))
    if capital and capital < 3000:
        flags.append("capital_social_baix")
    if not carrecs:
        flags.append("sense_carrecs_actius")
    return flags


def build_payload(adjudicataris: dict[str, dict[str, Any]], empreses_rows: list[dict[str, Any]], carrecs_rows: list[dict[str, Any]]) -> dict[str, Any]:
    empreses_by_nif, empreses_by_name = index_empreses(empreses_rows)
    carrecs_by_nif, carrecs_by_name = index_carrecs(carrecs_rows)

    records: list[dict[str, Any]] = []
    for item in adjudicataris.values():
        nif = item["nif"]
        name_key = item["nom_normalitzat"]
        empresa = (empreses_by_nif.get(nif) if nif else None) or empreses_by_name.get(name_key)
        carrecs_raw = (carrecs_by_nif.get(nif) if nif else None) or carrecs_by_name.get(name_key) or []
        carrecs = [summarize_charge(c) for c in carrecs_raw if is_active_charge(c)]

        if empresa or carrecs:
            estat = "amb_dades"
            flags = build_flags(empresa or {}, carrecs)
            font = "BORME local"
        else:
            estat = "pendent_borme"
            flags = []
            font = "pendent"

        records.append({
            **item,
            "contractes_import": round(float(item["contractes_import"]), 2),
            "estat": estat,
            "flags": flags,
            "carrecs": carrecs[:20],
            "capital_social": pick(empresa or {}, "capital", "capital_social", "capital_euros") or None,
            "data_constitucio": pick(empresa or {}, "data_constitucio", "fecha_constitucion") or None,
            "font": font,
        })

    records.sort(key=lambda r: (r["estat"] != "amb_dades", -float(r["contractes_import"]), r["nom"]))
    return {
        "font": "BORME local via extracte public",
        "actualitzat": datetime.now(timezone.utc).isoformat(),
        "total_adjudicataris": len(records),
        "amb_dades": sum(1 for r in records if r["estat"] == "amb_dades"),
        "pendents": sum(1 for r in records if r["estat"] != "amb_dades"),
        "adjudicataris": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera json/borme_adjudicataris.json per als adjudicataris de Calaf")
    parser.add_argument("--contractes", type=Path, default=CONTRACTES_CSV)
    parser.add_argument("--empreses", type=Path, help="Extracte BORME d'empreses en CSV, JSON o JSONL")
    parser.add_argument("--carrecs", type=Path, help="Extracte BORME de carrecs en CSV, JSON o JSONL")
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--keep-existing", action="store_true", help="No sobreescriu un JSON existent amb dades reals si no es passen fonts BORME")
    args = parser.parse_args()

    if not args.contractes.exists():
        raise FileNotFoundError(args.contractes)

    if args.keep_existing and not args.empreses and not args.carrecs and args.output.exists():
        try:
            with args.output.open("r", encoding="utf-8-sig") as f:
                existing = json.load(f)
            if int(existing.get("amb_dades") or 0) > 0:
                print(f"Es conserva {args.output}: ja conte dades BORME reals")
                return
        except Exception:
            pass

    adjudicataris = load_adjudicataris(args.contractes)
    empreses = read_records(args.empreses)
    carrecs = read_records(args.carrecs)
    payload = build_payload(adjudicataris, empreses, carrecs)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Adjudicataris: {payload['total_adjudicataris']}")
    print(f"Amb dades BORME: {payload['amb_dades']}")
    print(f"Pendents: {payload['pendents']}")
    print(f"Guardat: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
