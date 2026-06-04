import requests, io

r = requests.get("https://dadesobertes.seu-e.cat/csv/ge-p-pressupostos-per-programes-detallat-darrers-anys.csv", timeout=120)
r.encoding = "utf-8-sig"

trobats = set()
for line in r.text.splitlines():
    if "Calaf" in line and "Calafell" not in line and "Palafrugell" not in line:
        parts = line.split(",")
        if len(parts) >= 2:
            nom = parts[-1].strip().strip('"')
            codi = parts[-2].strip().strip('"')
            trobats.add((codi, nom))

for codi, nom in sorted(trobats):
    print(f"CODI: {codi}  NOM: {nom}")
