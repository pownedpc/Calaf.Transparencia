# Calaf Transparència — Context per Claude Code

## Què és aquest projecte
Portal web públic de transparència municipal per Calaf (~3.500 hab.), Catalunya Central.
Impulsat per Chester per a l'Aliança Catalana, candidatura 2027.
URL: https://pownedpc.github.io/Calaf.Transparencia

## Stack
- `index.html` — tot el portal en un sol fitxer (HTML + CSS + JS vanilla, sense dependències)
- `data.csv` — 14.853 factures, 1.128 proveïdors, ~30,57M€ (2016–2025)
- GitHub Pages — deploy automàtic en cada push a `main`
- GoatCounter — analytics (https://transparenciacalaf.goatcounter.com)

## Estructura del CSV
```
data, any, trimestre, num_document, import, situacio, codi_operacio,
nif_tercer, proveidor, descripcio, categoria, font,
menjo_score, menjo_total_cat, menjo_num_cont, menjo_slug,
calaf_score, calaf_pct_pressupost, calaf_anys
```

## Scripts Python disponibles
- `descarrega_factures.py` — descarrega Excels del portal de transparència de Calaf
- `consolidate.py` — processa Excels → data.csv
- `enrich_menjometre.py` — enriqueix data.csv amb dades del Menjòmetre
- `score_calaf.py` — calcula score de risc per proveïdor

## Flux d'actualització trimestral
```bash
python descarrega_factures.py --consolidar   # descarrega + consolida
python enrich_menjometre.py                  # enriqueix amb Menjòmetre
python score_calaf.py                        # actualitza scores
git add data.csv
git commit -m "data: actualització QX 20XX"
git push
```

## Pestanyes del portal (setView)
| ID | Nom | Funció |
|----|-----|--------|
| taula | Inici | Explorador complet amb cerca |
| proveidors | Proveïdors | Rànquing top 30 |
| anys | Per any | Evolució 2016-2025 |
| categories | Categories | Obra pública, serveis... |
| subvencions | Subvencions | Entitats i associacions |
| pressupost | Pressupost | Capítols 2023-2026 |
| campanyes | Campanyes | Cost publicitat institucional |
| convenis | Convenis | PDFs oficials |
| conceptes | Conceptes | Cards desplegables |
| alertes | Alertes | Fragmentació, recurrència |
| govern | Govern | Regidors, sous, plantilla, oposició |
| equipaments | Equipaments | 19 instal·lacions municipals |
| contractacio | Contractació 2026 | Pla anual de contractació |

## Govern municipal (JxC-AM 2023-2027)
- Montserrat Mases Sala — Alcaldessa, 29.736,96€, Leds-C4
- Jordi Biosca Pou — 1r Tinent (Urbanisme), 22.960€, Ernust Fincas SL, 3 vincles BORME
- Montserrat Isern Vivancos — 2a Tinent (Social/Educació), 15.050€, Dept. Educació
- Roger Rotés Biosca — Regidor (Medi Ambient/TIC), 13.160€, AUSA
- Laura Sòria Grau — Regidora (Esports/RRHH), 13.160€, TERSA
- Vicenç Sugrañes Creus — Regidor (Cultura/Festes), 13.160€, Tallers Ratera

## Proveïdors destacats (per Calaf Score)
- ROMA INFRAESTRUCTURES I SERVEIS SA (A25012386) — score 82, ~24% despesa total
- RESIDÈNCIA TERCERA EDAT L'ONADA SL (B43514504) — score 35
- ADTEL SISTEMAS DE COMUNICACION SL — serveis comunicació

## Portal de transparència de Calaf
- URL: https://calaf.eadministracio.cat/transparency
- Excels de factures: secció 5.1.2 REGISTRE DE FACTURES
- UUID carpeta factures: 00fa51c7-54eb-49b4-8dde-31aa117d91a3
- Format Excels: {trimestre}_FRES_PORTAL_{any}.xlsx (ex: 1T_FRES_PORTAL_2025)
- Plataforma: esPublico Gestiona (requereix sessió de navegador per descarregar)

## Convencions de codi
- Idioma portal: Català
- Idioma comentaris i commits: Català o castellà
- Cap dependència externa en index.html
- CSS inline o en <style> al mateix fitxer
- JS al final del <body>
- Funcions JS: camelCase, noms en català quan possible

## Commits recents rellevants
- feat: alertes, govern, badges Menjometre i score Calaf
- feat: pestanya Equipaments municipals amb 19 instal·lacions
- feat: plantilla 2026 a Govern + nova tab Pla Contractacio 2026
- refactor: nav net 5 tabs + drawer complet amb descripcions
- fix: claus equipaments afinades + nota SS patronal a Govern

## Notes importants
- El portal genera el contingut dinàmicament des de data.csv via fetch()
- setView() controla quina pestanya és visible
- VIEWS array ha d'estar sincronitzat amb els divs #view-{id}
- NAV_VIEWS = les 5 pestanyes del nav horitzontal (taula, proveidors, alertes, govern, equipaments)
- La resta de pestanyes s'accedeixen via el drawer lateral (botó ☰)
- GoatCounter events: /e/pestanya/{id}, /e/cerca/{mode}/{query}
