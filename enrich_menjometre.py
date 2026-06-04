#!/usr/bin/env python3
"""
enrich_menjometre.py
Enriqueix data.csv amb dades del Menjometre (score, total Catalunya, num contractes).
Executa des de la carpeta del repositori: python enrich_menjometre.py

Requisits: pip install pandas requests
"""

import json, subprocess, threading, time, queue, os, sys
import pandas as pd

INPUT_CSV  = "data.csv"
OUTPUT_CSV = "data.csv"
CACHE_FILE = "menjometre_cache.json"
DELAY_SECS = 0.5

class MenjometreClient:
    def __init__(self):
        self.proc = None
        self.q = queue.Queue()
        self._req_id = 0

    def start(self):
        print("Iniciant servidor Menjometre (npx)...")
        npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
        self.proc = subprocess.Popen(
            [npx_cmd, "-y", "menjometre-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        self._req_id += 1
        self._send({"jsonrpc":"2.0","id":self._req_id,"method":"initialize",
            "params":{"protocolVersion":"2024-11-05","capabilities":{},
                      "clientInfo":{"name":"calaf-enricher","version":"1.0"}}})
        resp = self._wait(self._req_id, timeout=20)
        if resp:
            info = resp.get("result",{}).get("serverInfo",{})
            print(f"  Connectat: {info.get('name','?')} v{info.get('version','?')}")
            return True
        print("  ERROR: no s'ha pogut connectar al servidor Menjometre")
        sys.exit(1)

    def _reader(self):
        for line in self.proc.stdout:
            line = line.decode().strip()
            if not line: continue
            try: self.q.put(json.loads(line))
            except: pass

    def _send(self, msg):
        self.proc.stdin.write((json.dumps(msg)+"\n").encode())
        self.proc.stdin.flush()

    def _wait(self, req_id, timeout=10):
        deadline = time.time() + timeout
        buf = []
        while time.time() < deadline:
            try:
                item = self.q.get(timeout=0.3)
                if item.get("id") == req_id:
                    for b in buf: self.q.put(b)
                    return item
                buf.append(item)
            except queue.Empty: pass
        for b in buf: self.q.put(b)
        return None

    def call(self, tool, args, timeout=10):
        self._req_id += 1
        self._send({"jsonrpc":"2.0","id":self._req_id,"method":"tools/call",
                    "params":{"name":tool,"arguments":args}})
        resp = self._wait(self._req_id, timeout=timeout)
        if not resp: return None
        content = resp.get("result",{}).get("content",[{}])
        text = content[0].get("text","{}") if content else "{}"
        try: return json.loads(text)
        except: return None

    def stop(self):
        if self.proc: self.proc.terminate()


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f: return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE,"w") as f: json.dump(cache, f, ensure_ascii=False, indent=2)

BUIT = {"menjo_score":None,"menjo_total_cat":None,"menjo_num_cont":None,"menjo_slug":None}

def best_match(results, nom_cerca):
    """
    Tria el millor resultat de la cerca:
    - Descarta UTEs (slug conté '-UTE' o '-UTE-')
    - Prefereix el resultat amb més total_public_funds
    - Si hi ha empat, el que té el nom més similar
    """
    nom_up = nom_cerca.upper()
    # Filtrar UTEs
    no_ute = [r for r in results if 'UTE' not in r.get('slug','').upper().split('-')]
    candidates = no_ute if no_ute else results
    # Si només n'hi ha un, agafar-lo
    if len(candidates) == 1:
        return candidates[0].get('slug')
    # Prioritzar el que té el nom més curt (menys probable que sigui UTE o consorci)
    candidates.sort(key=lambda r: len(r.get('slug','')))
    return candidates[0].get('slug')

def query_provider(client, nom, cache):
    if nom in cache: return cache[nom]

    res = client.call("search", {"query": nom, "type": "entity", "limit": 5})
    if not res or not res.get("data",{}).get("results"):
        cache[nom] = BUIT; save_cache(cache); return BUIT

    results = res["data"]["results"]
    slug = best_match(results, nom)
    if not slug:
        cache[nom] = BUIT; save_cache(cache); return BUIT

    time.sleep(DELAY_SECS)
    profile_res = client.call("get_entity", {"entity_id": slug})
    if not profile_res:
        cache[nom] = BUIT; save_cache(cache); return BUIT

    p = profile_res.get("data",{}).get("profile",{})
    result = {
        "menjo_score":     round(p.get("menjometre_score") or 0, 1),
        "menjo_total_cat": round(p.get("total_public_funds") or 0, 2),
        "menjo_num_cont":  int(p.get("total_contracts") or 0),
        "menjo_slug":      slug,
    }
    cache[nom] = result; save_cache(cache)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--reset', nargs='*', metavar='NOM',
        help='Re-consulta proveïdors específics (o tots si no en poses cap)')
    args = parser.parse_args()

    if not os.path.exists(INPUT_CSV):
        print(f"ERROR: No trobo {INPUT_CSV}. Executa des de la carpeta del repo.")
        sys.exit(1)

    print(f"Llegint {INPUT_CSV}...")
    df = pd.read_csv(INPUT_CSV)
    print(f"  {len(df)} files, {df['proveidor'].nunique()} proveidors unics")

    backup = INPUT_CSV.replace(".csv","_backup.csv")
    df.to_csv(backup, index=False)
    print(f"  Backup guardat: {backup}")

    cache = load_cache()
    print(f"  Cache: {len(cache)} proveidors ja consultats")

    # Reset entrades específiques o tot el cache
    if args.reset is not None:
        if args.reset:
            for nom in args.reset:
                if nom in cache:
                    del cache[nom]
                    print(f"  Reset: {nom}")
        else:
            cache = {}
            print("  Reset: cache complet esborrat")
        save_cache(cache)

    proveidors = [p for p in df["proveidor"].unique() if pd.notna(p) and str(p).strip()]
    noves = [p for p in proveidors if p not in cache]
    print(f"  A consultar: {len(noves)} nous ({len(proveidors)-len(noves)} en cache)\n")

    client = MenjometreClient()
    client.start()

    for i, nom in enumerate(noves, 1):
        print(f"  [{i:3}/{len(noves)}] {nom[:55]}")
        query_provider(client, nom, cache)
        time.sleep(DELAY_SECS)

    client.stop()

    print("\nEnriquint CSV...")
    df["menjo_score"]     = df["proveidor"].map(lambda n: cache.get(n,{}).get("menjo_score"))
    df["menjo_total_cat"] = df["proveidor"].map(lambda n: cache.get(n,{}).get("menjo_total_cat"))
    df["menjo_num_cont"]  = df["proveidor"].map(lambda n: cache.get(n,{}).get("menjo_num_cont"))
    df["menjo_slug"]      = df["proveidor"].map(lambda n: cache.get(n,{}).get("menjo_slug"))

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Guardat: {OUTPUT_CSV}")

    amb_dades = df[df["menjo_score"].notna()]["proveidor"].nunique()
    print(f"\n=== RESUM ===")
    print(f"Proveidors amb score: {amb_dades} / {df['proveidor'].nunique()}")
    print(f"\nTop 10 per score Menjometre:")
    top = (df.groupby("proveidor")
             .first()[["menjo_score","menjo_total_cat","menjo_num_cont"]]
             .dropna()
             .sort_values("menjo_score", ascending=False)
             .head(10))
    for nom, row in top.iterrows():
        total_m = (row['menjo_total_cat'] or 0) / 1e6
        print(f"  {nom[:50]:50} score:{row['menjo_score']:5.1f}  {total_m:.1f}M EUR  {int(row['menjo_num_cont'])} contractes")

    print("\nFet! Ara executa:")
    print("  git add data.csv menjometre_cache.json")
    print("  git commit -m 'data: enriquiment Menjometre'")
    print("  git push")

if __name__ == "__main__":
    main()
