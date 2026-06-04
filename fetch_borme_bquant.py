#!/usr/bin/env python3
"""
fetch_borme_bquant.py - Calaf Transparencia

Descarrega el paquet public BORME de BquantFinance/licitaciones-espana,
filtra nomes els adjudicataris de Calaf i genera json/borme_adjudicataris.json.

Esta pensat per executar-se a GitHub Actions, perque borme.zip pesa uns 750 MB.
Requereix duckdb:

  python -m pip install duckdb
  python fetch_borme_bquant.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from fetch_borme_adjudicataris import build_payload, load_adjudicataris


DEFAULT_RELEASE_URL = "https://github.com/BquantFinance/licitaciones-espana/releases/download/v2026.02/borme.zip"
CONTRACTES_CSV = Path("calaf_contractes.csv")
OUTPUT_JSON = Path("json") / "borme_adjudicataris.json"
CACHE_DIR = Path(".cache") / "borme_bquant"


def norm_name(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = text.replace("Ñ", "##ENIE##")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("##ENIE##", "Ñ")
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"\bS\s*\.\s*R\s*\.\s*L\s*\.?\b", "SRL", text)
    text = re.sub(r"\bS\s*\.\s*L\s*\.\s*U\s*\.?\b", "SLU", text)
    text = re.sub(r"\bS\s*\.\s*L\s*\.\s*P\s*\.?\b", "SLP", text)
    text = re.sub(r"\bS\s*\.\s*L\s*\.\s*L\s*\.?\b", "SLL", text)
    text = re.sub(r"\bS\s*\.\s*L\s*\.?\b", "SL", text)
    text = re.sub(r"\bS\s*\.\s*A\s*\.\s*U\s*\.?\b", "SAU", text)
    text = re.sub(r"\bS\s*\.\s*A\s*\.\s*E\s*\.?\b", "SAE", text)
    text = re.sub(r"\bS\s*\.\s*A\s*\.?\b", "SA", text)
    text = re.sub(r"\bS\s*\.\s*C\s*\.?\b", "SC", text)
    text = re.sub(r"\bA\s*\.\s*I\s*\.\s*E\s*\.?\b", "AIE", text)
    text = re.sub(r"\bS\s*\.\s*M\s*\.\s*E\s*\.?\b", "SME", text)
    text = re.sub(r"\bS\s+R\s+L\b", "SRL", text)
    text = re.sub(r"\bS\s+M\s+E\b", "SME", text)
    text = re.sub(r"\bS\s+L\s+U\b", "SLU", text)
    text = re.sub(r"\bS\s+L\s+P\b", "SLP", text)
    text = re.sub(r"\bS\s+L\s+L\b", "SLL", text)
    text = re.sub(r"\bS\s+L\b$", "SL", text)
    text = re.sub(r"\bS\s+A\s+U\b", "SAU", text)
    text = re.sub(r"\bS\s+A\s+E\b", "SAE", text)
    text = re.sub(r"\bS\s+A\b$", "SA", text)
    text = re.sub(r"[,.\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    suffixes = [
        " SOCIEDAD ANONIMA DEPORTIVA",
        " SOCIEDAD ANONIMA",
        " SOCIEDAD LIMITADA PROFESIONAL",
        " SOCIEDAD LIMITADA LABORAL",
        " SOCIEDAD LIMITADA NUEVA EMPRESA",
        " SOCIEDAD LIMITADA",
        " SOCIEDAD COOPERATIVA ANDALUZA",
        " SOCIEDAD COOPERATIVA",
        " SOCIEDAD CIVIL PROFESIONAL",
        " SOCIEDAD CIVIL",
        " SOCIEDAD UNIPERSONAL",
        " AGRUPACION DE INTERES ECONOMICO",
        " SAU",
        " SLU",
        " SAD",
        " SLL",
        " SLP",
        " SLNE",
        " SA SME",
        " SAE",
        " SME",
        " SA",
        " SL",
        " SC",
        " SCA",
        " SCCL",
        " SCOOP",
        " SE",
        " SRL",
        " AIE",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix):
                text = text[:-len(suffix)].strip()
                changed = True
                break
    return re.sub(r"[.,;]+$", "", text).strip()


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 100_000_000:
        print(f"Ja existeix: {path} ({path.stat().st_size / 1e6:.1f} MB)")
        return

    tmp = path.with_suffix(path.suffix + ".part")
    print(f"Descarregant {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "CalafTransparencia/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, tmp.open("wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 1024)
    tmp.replace(path)
    print(f"Descarregat: {path} ({path.stat().st_size / 1e6:.1f} MB)")


def extract_borme_parquets(zip_path: Path, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "borme_empresas_pub.parquet": out_dir / "borme_empresas_pub.parquet",
        "borme_cargos_pub.parquet": out_dir / "borme_cargos_pub.parquet",
    }

    if all(p.exists() for p in targets.values()):
        return targets["borme_empresas_pub.parquet"], targets["borme_cargos_pub.parquet"]

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for filename, target in targets.items():
            match = next((n for n in names if n.endswith(filename)), None)
            if not match:
                raise FileNotFoundError(f"No s'ha trobat {filename} dins {zip_path}")
            print(f"Extraient {match}")
            with zf.open(match) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

    return targets["borme_empresas_pub.parquet"], targets["borme_cargos_pub.parquet"]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def query_borme(empresas_path: Path, cargos_path: Path, names: list[str], out_dir: Path) -> tuple[Path, Path]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("Falta duckdb. Executa: python -m pip install duckdb") from exc

    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE targets(empresa_norm VARCHAR)")
    con.executemany("INSERT INTO targets VALUES (?)", [(n,) for n in names])

    empresas_sql = """
        SELECT e.*
        FROM read_parquet(?) e
        JOIN targets t ON e.empresa_norm = t.empresa_norm
    """
    cargos_sql = """
        SELECT c.*
        FROM read_parquet(?) c
        JOIN targets t ON c.empresa_norm = t.empresa_norm
    """
    cur = con.execute(empresas_sql, [str(empresas_path)])
    empresas_cols = [d[0] for d in cur.description]
    empresas = [dict(zip(empresas_cols, row)) for row in cur.fetchall()]

    cur = con.execute(cargos_sql, [str(cargos_path)])
    cargos_cols = [d[0] for d in cur.description]
    cargos = [dict(zip(cargos_cols, row)) for row in cur.fetchall()]

    empresas_csv = out_dir / "borme_empreses_calaf.csv"
    cargos_csv = out_dir / "borme_carrecs_calaf.csv"
    write_csv(empresas_csv, empresas)
    write_csv(cargos_csv, cargos)
    print(f"Empreses BORME filtrades: {len(empresas)}")
    print(f"Carrecs BORME filtrats: {len(cargos)}")
    return empresas_csv, cargos_csv


def read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description="Filtra BORME public de Bquant per adjudicataris de Calaf")
    parser.add_argument("--contractes", type=Path, default=CONTRACTES_CSV)
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--release-url", default=DEFAULT_RELEASE_URL)
    parser.add_argument("--zip", type=Path, help="ZIP BORME ja descarregat")
    parser.add_argument("--skip-download", action="store_true", help="No descarrega; usa --zip o cache existent")
    args = parser.parse_args()

    adjudicataris = load_adjudicataris(args.contractes)
    names = sorted({norm_name(a["nom"]) for a in adjudicataris.values() if norm_name(a["nom"])})
    if not names:
        raise RuntimeError("No hi ha adjudicataris amb nom per creuar")

    zip_path = args.zip or (args.cache_dir / "borme.zip")
    if not args.skip_download and not args.zip:
        download(args.release_url, zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)

    empresas_parquet, cargos_parquet = extract_borme_parquets(zip_path, args.cache_dir / "data")
    empresas_csv, cargos_csv = query_borme(empresas_parquet, cargos_parquet, names, args.cache_dir / "filtered")

    payload = build_payload(
        adjudicataris,
        read_csv_records(empresas_csv),
        read_csv_records(cargos_csv),
    )
    payload["font"] = "BORME public BquantFinance/licitaciones-espana v2026.02"
    payload["release_url"] = args.release_url

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Guardat: {args.output}")
    print(f"Adjudicataris amb dades BORME: {payload['amb_dades']}/{payload['total_adjudicataris']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
