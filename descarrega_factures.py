#!/usr/bin/env python3
"""
descarrega_factures.py
======================
Descarrega automàticament els Excels del Registre de Factures
del Portal de Transparència de l'Ajuntament de Calaf.

⚠️  IMPORTANT: Executa aquest script des del teu ordinador (Windows/Mac).
    Des de servidors externs (cloud, VPS) el portal retorna 403.

Ruta portal: Transparència → 5. Contractes → 5.1. Relació →
             5.1.2. Registre de Factures → {Any} → {Trimestre}.xlsx

Ús:
    python descarrega_factures.py                  # Descarrega tots els nous
    python descarrega_factures.py --any 2025       # Només un any
    python descarrega_factures.py --force          # Reescriu existents
    python descarrega_factures.py --consolidar     # Descarrega + consolida CSV
    python descarrega_factures.py --dry-run        # Mostra sense descarregar

Requisits:
    pip install requests beautifulsoup4 openpyxl pandas

Alternativa (si requests dóna 403):
    pip install playwright && playwright install chromium
    → canvia USE_PLAYWRIGHT = True a la secció CONFIG

Autor: Chester (Calaf Transparència)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ Falta requests o beautifulsoup4.")
    print("   Instal·la amb: pip install requests beautifulsoup4")
    sys.exit(1)

# ─── CONFIGURACIÓ ──────────────────────────────────────────────────────────────

BASE_URL   = "https://calaf.eadministracio.cat"
# UUID fix de la carpeta 5.1.2 Registre de Factures
FACTURES_UUID = "00fa51c7-54eb-49b4-8dde-31aa117d91a3"
FACTURES_URL  = f"{BASE_URL}/transparency/{FACTURES_UUID}/"

# ── Canvia a True si requests dóna 403 ──
USE_PLAYWRIGHT = False

# Carpeta de descàrrega (relativa a aquest script)
DOWNLOAD_DIR = Path(__file__).parent / "excels_factures"

# Fitxer de control per no repetir descàrregues
MANIFEST_FILE = DOWNLOAD_DIR / "manifest.json"

# Headers per semblar Chrome real
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ca-ES,ca;q=0.9,es;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}

# ─── HELPERS ───────────────────────────────────────────────────────────────────

def get_session():
    """Crea sessió amb cookies de la seu electrònica."""
    if USE_PLAYWRIGHT:
        print("ℹ️  Mode Playwright actiu (browser real headless)")
        return None  # Playwright gestiona la sessió per separat

    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        # Visita la pàgina principal per obtenir cookies
        r = s.get(BASE_URL, timeout=15)
        r.raise_for_status()
        # Visita el portal de transparència per establir context
        time.sleep(0.5)
        r2 = s.get(f"{BASE_URL}/transparency", timeout=15)
        print(f"✅ Sessió iniciada (status: {r2.status_code}, "
              f"cookies: {len(s.cookies)})")
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            print("⚠️  403 Forbidden — el portal et bloqueja.")
            print("   → Solució 1: Executa el script des del teu ordinador (no servidor)")
            print("   → Solució 2: Canvia USE_PLAYWRIGHT = True al script")
            sys.exit(1)
        print(f"⚠️  Error HTTP {e.response.status_code}: {e}")
    except Exception as e:
        print(f"⚠️  No s'ha pogut iniciar sessió: {e}")
    return s


# ─── MODE PLAYWRIGHT (backup si requests dóna 403) ─────────────────────────────

def playwright_descarregar_tot(dest_dir, any_filtre=None, force=False):
    """
    Alternativa amb Playwright quan requests dóna 403.
    Usa un browser real (Chromium headless).
    Instal·la amb: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright no instal·lat.")
        print("   Executa: pip install playwright && playwright install chromium")
        sys.exit(1)

    manifest = load_manifest()
    total_nous = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ca-ES",
        )
        page = context.new_page()

        print("\n🌐 Playwright: navegant al portal...")
        page.goto(FACTURES_URL, wait_until="networkidle")

        # Trobar carpetes d'any
        any_links = page.query_selector_all("a[href*='/transparency/']")
        anys = {}
        for link in any_links:
            text = link.inner_text().strip()
            match = re.search(r"(20\d{2})", text)
            if match:
                any_str = match.group(1)
                if any_filtre and any_str != str(any_filtre):
                    continue
                href = link.get_attribute("href")
                anys[any_str] = urljoin(BASE_URL, href)

        print(f"   Anys trobats: {list(anys.keys())}")

        for any_str in sorted(anys.keys(), reverse=True):
            print(f"\n📅 Any {any_str}:")
            page.goto(anys[any_str], wait_until="networkidle")

            doc_links = page.query_selector_all("a[href*='/preview-document/']")
            for link in doc_links:
                nom = link.inner_text().strip()
                href = link.get_attribute("href")
                uuid = href.split("/")[-1]
                key = f"{any_str}_{uuid}"

                if key in manifest and not force:
                    print(f"   ⏭️  {nom}: ja descarregat")
                    continue

                print(f"   ⬇️  {nom}...")
                page.goto(urljoin(BASE_URL, href), wait_until="networkidle")

                # Clicar "Descarregar una còpia"
                dest_dir.mkdir(parents=True, exist_ok=True)
                nom_fitxer = f"{any_str}_{nom}.xlsx"
                nom_fitxer = re.sub(r'[<>:"/\\|?*]', "_", nom_fitxer)
                dest_path = dest_dir / nom_fitxer

                with page.expect_download() as dl_info:
                    dl_button = page.query_selector("a:has-text('Descarregar')")
                    if dl_button:
                        dl_button.click()
                    else:
                        print(f"   ❌ Botó de descàrrega no trobat per {nom}")
                        continue

                download = dl_info.value
                download.save_as(dest_path)

                manifest[key] = {
                    "nom": nom, "any": any_str, "uuid": uuid,
                    "path": str(dest_path), "data": datetime.now().isoformat()
                }
                save_manifest(manifest)
                total_nous += 1
                print(f"   ✅ Desat: {nom_fitxer}")
                time.sleep(0.5)

        browser.close()

    return total_nous


def get_soup(session, url, retries=3):
    """Obté BeautifulSoup d'una URL amb reintents."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            if attempt < retries - 1:
                print(f"   ↻ Reintent {attempt+2}/{retries} per {url}")
                time.sleep(2 ** attempt)
            else:
                print(f"   ❌ Error en {url}: {e}")
                return None


def load_manifest():
    """Carrega el manifest de fitxers ja descarregats."""
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE) as f:
            return json.load(f)
    return {}


def save_manifest(manifest):
    """Desa el manifest."""
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def file_sha256(path):
    """SHA256 d'un fitxer per verificar integritat."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ─── DESCOBERTA ────────────────────────────────────────────────────────────────

def descobrir_anys(session, any_filtre=None):
    """
    Descobreix les carpetes d'any dins el Registre de Factures.
    Retorna: {any: uuid_url}
    """
    print(f"\n📂 Explorant Registre de Factures...")
    soup = get_soup(session, FACTURES_URL)
    if not soup:
        return {}

    anys = {}
    for link in soup.find_all("a", href=re.compile(r"/transparency/[0-9a-f-]{36}/")):
        text = link.get_text(strip=True)
        # Cerquem carpetes que comencin per any: "2025_Registre Factures", "2024", etc.
        match = re.search(r"(20\d{2})", text)
        if match:
            any_str = match.group(1)
            if any_filtre and any_str != str(any_filtre):
                continue
            url = urljoin(BASE_URL, link["href"])
            anys[any_str] = url
            print(f"   📅 Any {any_str}: {url}")

    if not anys:
        print("   ⚠️  No s'han trobat carpetes d'any.")
    return anys


def descobrir_documents_any(session, any_str, url_any):
    """
    Descobreix els documents (Excels) dins una carpeta d'any.
    Retorna: [{nom, preview_url, uuid}]
    """
    soup = get_soup(session, url_any)
    if not soup:
        return []

    docs = []
    for link in soup.find_all("a", href=re.compile(r"/preview-document/[0-9a-f-]{36}")):
        nom = link.get_text(strip=True)
        preview_url = urljoin(BASE_URL, link["href"])
        uuid = link["href"].split("/")[-1]
        docs.append({"nom": nom, "preview_url": preview_url, "uuid": uuid, "any": any_str})
        print(f"      📄 {nom} → {uuid}")

    return docs


# ─── DESCÀRREGA ────────────────────────────────────────────────────────────────

def obtenir_url_descàrrega(session, preview_url):
    """
    Visita la pàgina de preview i obté l'URL de descàrrega
    que conté el token ?x=...
    """
    soup = get_soup(session, preview_url)
    if not soup:
        return None

    # Busca el botó "Descarregar una còpia"
    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True).lower()
        href = link["href"]
        if ("descarreg" in text or "download" in text or "còpia" in text) and "?x=" in href:
            return urljoin(preview_url, href)

    # Alternativa: qualsevol link amb ?x= que no sigui navegació
    for link in soup.find_all("a", href=re.compile(r"\?x=")):
        href = link["href"]
        # Excloem links de navegació (Inici, etc.)
        text = link.get_text(strip=True)
        if len(text) > 3 and text not in ("Inici", "Identificat", "Identifica't"):
            return urljoin(preview_url, href)

    return None


def descarregar_document(session, doc, dest_dir, force=False):
    """
    Descarrega un document Excel.
    Retorna: (path_fitxer, descarregat:bool) o (None, False) si error.
    """
    nom_fitxer = f"{doc['any']}_{doc['nom']}.xlsx"
    # Neteja nom (treu caràcters problemàtics)
    nom_fitxer = re.sub(r'[<>:"/\\|?*]', "_", nom_fitxer)
    dest_path = dest_dir / nom_fitxer

    if dest_path.exists() and not force:
        print(f"   ⏭️  Ja existeix: {nom_fitxer}")
        return dest_path, False

    print(f"   ⬇️  Descarregant: {nom_fitxer}...")

    # 1. Obtenir URL de descàrrega amb token de sessió
    dl_url = obtenir_url_descàrrega(session, doc["preview_url"])
    if not dl_url:
        print(f"   ❌ No s'ha trobat URL de descàrrega per {nom_fitxer}")
        return None, False

    # 2. Descarregar el fitxer
    try:
        r = session.get(dl_url, timeout=30, stream=True)
        r.raise_for_status()

        # Verificar que és un Excel
        content_type = r.headers.get("Content-Type", "")
        content_disp  = r.headers.get("Content-Disposition", "")

        # Acceptem xlsx, xls, octet-stream, o si el nom acaba en Excel
        is_excel = (
            "spreadsheet" in content_type or
            "excel" in content_type or
            "octet-stream" in content_type or
            ".xlsx" in content_disp or
            ".xls" in content_disp
        )

        if not is_excel and "html" in content_type:
            print(f"   ⚠️  La resposta és HTML, no Excel. Potser necessita autenticació.")
            # Intentem igualment desar i verificar més tard
            
        dest_dir.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

        size_kb = dest_path.stat().st_size / 1024
        print(f"   ✅ Desat: {nom_fitxer} ({size_kb:.0f} KB)")
        return dest_path, True

    except Exception as e:
        print(f"   ❌ Error descarregant {nom_fitxer}: {e}")
        return None, False


# ─── CONSOLIDACIÓ ──────────────────────────────────────────────────────────────

def consolidar_csv(excels_dir):
    """
    Processa tots els Excels descarregats i genera data.csv.
    Crida el script consolidate.py si existeix, o consolida inline.
    """
    try:
        import pandas as pd
    except ImportError:
        print("❌ Falta pandas. Instal·la amb: pip install pandas openpyxl")
        return

    consolidate_script = Path(__file__).parent / "consolidate.py"
    if consolidate_script.exists():
        print("\n🔄 Executant consolidate.py...")
        os.system(f'python "{consolidate_script}"')
        return

    # Consolidació inline si no hi ha script separat
    print("\n🔄 Consolidant Excels → data.csv...")
    dfs = []
    excels = list(Path(excels_dir).rglob("*.xlsx"))
    
    if not excels:
        print("   ⚠️  No s'han trobat fitxers .xlsx a processar")
        return

    for excel_path in sorted(excels):
        try:
            df = pd.read_excel(excel_path, header=0)
            df["_font"] = excel_path.name
            dfs.append(df)
            print(f"   ✓ {excel_path.name}: {len(df)} files")
        except Exception as e:
            print(f"   ⚠️  Error llegint {excel_path.name}: {e}")

    if dfs:
        combined = pd.concat(dfs, ignore_index=True)
        output_path = Path(__file__).parent / "data_nou.csv"
        combined.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n✅ CSV generat: {output_path} ({len(combined)} files de {len(excels)} Excels)")
    else:
        print("   ❌ Cap Excel s'ha pogut processar")


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Descarrega els Excels de factures del portal de Calaf"
    )
    parser.add_argument("--any",        help="Filtrar per any (ex: 2025)")
    parser.add_argument("--force",      action="store_true", help="Reescriu fitxers existents")
    parser.add_argument("--consolidar", action="store_true", help="Consolida CSV després")
    parser.add_argument("--dry-run",    action="store_true", help="Mostra sense descarregar")
    parser.add_argument("--playwright", action="store_true", help="Usa Playwright (browser real)")
    args = parser.parse_args()

    # Override global si --playwright
    global USE_PLAYWRIGHT
    if args.playwright:
        USE_PLAYWRIGHT = True

    print("=" * 60)
    print("  CALAF TRANSPARÈNCIA — Descàrrega de Factures")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"  Mode: {'Playwright' if USE_PLAYWRIGHT else 'requests'}")
    print("=" * 60)

    dest_dir = DOWNLOAD_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁 Carpeta destí: {dest_dir.resolve()}")

    manifest = load_manifest()
    print(f"📋 Fitxers al manifest: {len(manifest)}")

    # ── Mode Playwright ──
    if USE_PLAYWRIGHT:
        total_nous = playwright_descarregar_tot(
            dest_dir,
            any_filtre=args.any,
            force=args.force
        )
        if args.consolidar and total_nous > 0:
            consolidar_csv(dest_dir)
        print(f"\n✅ Fet! {total_nous} fitxers nous descarregats.")
        return

    # ── Mode requests ──
    session = get_session()
    time.sleep(1)

    anys = descobrir_anys(session, any_filtre=args.any)
    if not anys:
        print("\n❌ No s'han trobat anys. Comprova la connexió.")
        sys.exit(1)

    total_nous = 0
    total_errors = 0

    for any_str in sorted(anys.keys(), reverse=True):
        url_any = anys[any_str]
        print(f"\n📅 Any {any_str}:")

        docs = descobrir_documents_any(session, any_str, url_any)

        for doc in docs:
            key = f"{any_str}_{doc['uuid']}"

            if args.dry_run:
                print(f"   [DRY-RUN] → {doc['nom']} ({doc['uuid']})")
                continue

            if key in manifest and not args.force:
                print(f"   ⏭️  {doc['nom']}: ja al manifest")
                continue

            time.sleep(0.5)
            path, ok = descarregar_document(session, doc, dest_dir, force=args.force)

            if path and ok:
                manifest[key] = {
                    "nom": doc["nom"], "any": any_str, "uuid": doc["uuid"],
                    "path": str(path), "sha256": file_sha256(path),
                    "data": datetime.now().isoformat()
                }
                save_manifest(manifest)
                total_nous += 1
            elif path is None:
                total_errors += 1

    print("\n" + "=" * 60)
    print(f"  RESUM: {total_nous} nous, {total_errors} errors")
    if args.dry_run:
        print("  [DRY-RUN] Cap fitxer descarregat realment")

    if args.consolidar and total_nous > 0:
        consolidar_csv(dest_dir)

    print("\n✅ Fet!")


if __name__ == "__main__":
    main()
