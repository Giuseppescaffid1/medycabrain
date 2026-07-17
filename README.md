# medycabrain — Instagram Content Intelligence

POC per un'attività italiana nella nicchia salute femminile / menopausa
(ispirazione: [medyca.it](https://www.medyca.it/)).

Mima il comportamento dell'Apify Instagram Scraper per una lista di account
pubblici configurabili, estrae l'audio dai reel, li trascrive (italiano), li
arricchisce con un LLM e **clusterizza gli argomenti** in un DAG a due livelli.
Tutto è consultabile dal cliente in un "second brain" web: libreria
ricercabile, esplorazione dei cluster, workspace (preferiti / ispirazione /
note / etichette), gestione account.

```
BEC  Django 4.2 + DRF + PostgreSQL   — API + pipeline "sistema di agenti"
FEC  React 18 + TS + Vite + Tailwind — workspace cliente (italiano)
```

## Architettura della pipeline (BEC = sistema di agenti)

DAG leggero e idempotente (`pipeline/dag.py`). Ogni agente processa solo le
righe nel proprio stato `pending` → una fase che fallisce non blocca le altre.

```
ScraperAgent   → reel (metadati)      media_status=pending
DownloaderAgent→ ffmpeg mp3 + thumb   transcribe_status=pending   (video cancellato)
TranscriberAgent→ faster-whisper it   enrich_status=pending
EnrichAgent    → LLM (HF) riassunto+topic+hook+formato + argomenti
ClusterAgent   → embeddings locali → HDBSCAN/agglomerative → naming LLM (L1)
                 + argomenti assegnati ai cluster (L2)
```

### Comandi

```bash
cd BEC && source venv/bin/activate

python manage.py run_pipeline                 # tutta la pipeline
python manage.py run_pipeline --dry-run
python manage.py run_pipeline --only scrape --limit 5
python manage.py run_pipeline --skip-cluster  # top-up veloce
python manage.py seed_demo                    # dati demo (menopausa) senza scraping
python manage.py seed_demo && python manage.py run_pipeline --only cluster
```

## Setup locale

```bash
# BEC
cd BEC
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# torch CPU-only (evita i wheel CUDA da GB):
pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
cp .env.example .env      # imposta SECRET_KEY, DATABASE_URL, HF_API_TOKEN
python manage.py migrate
python manage.py seed_client_user --username cliente --password '...'
python manage.py runserver 127.0.0.1:8010

# FEC
cd ../FEC
npm install
npm run dev               # proxy /api → 127.0.0.1:8010
```

## Segreti da fornire

| Cosa | Dove | Come |
|------|------|------|
| **HF_API_TOKEN** | `BEC/.env` | token HuggingFace Pro (enrichment + naming cluster). Senza, la pipeline salta enrich/naming ma gira lo stesso. |
| **Sessione Instagram** | `BEC/data/ig_session.json` | cookie di un **account burner** (non quello del cliente). Vedi sotto. |

## Runbook: sessione Instagram (account burner)

I limiti anonimi di IG sono brutali (~1-2 richieste/30s). Serve una sessione
loggata di un account **usa e getta**.

1. Login su instagram.com con l'account burner in Chrome.
2. Estensione **Cookie-Editor** → Export → JSON (array di cookie).
3. Salva il file e importa:
   ```bash
   python manage.py ig_session import /percorso/cookie-export.json
   python manage.py ig_session test          # deve dire "Session OK"
   ```
Cookie critici: `sessionid`, `csrftoken`, `ds_user_id`. Il file viene messo in
`data/ig_session.json` (chmod 600, gitignored). Un vecchio file viene salvato
come backup automatico.

## Runbook: rotazione del doc_id GraphQL (ogni 2-4 settimane)

Instagram ruota il `doc_id` della query GraphQL dei reel: quando succede,
`ScraperAgent` logga `IGSchemaChanged` e passa al fallback instaloader.
Per rimettere a posto il percorso primario:

1. Apri `instagram.com/<account>/reels/` in Chrome, DevTools → Network.
2. Filtra `graphql/query`, apri la richiesta della tab reel, copia il `doc_id`.
3. Django admin → **Scraper configs** → `doc_id_reels_tab` → incolla il valore.

Nessun deploy: la config sta nel DB (`scraper_config`), editabile dall'admin.

## Deploy sul VPS (medycabrain.messtudent.com)

1. DNS: record A `medycabrain.messtudent.com → 81.17.96.27`.
2. DB già creato (`medycabrain` / `medycabrain_user`).
3. `.env` di produzione (`DJANGO_SETTINGS_MODULE=config.settings.production`).
4. `python manage.py collectstatic --noinput && python manage.py migrate`.
5. systemd: `deploy/medycabrain-backend.service` → porta **8010**.
6. `cd FEC && npm run build`.
7. nginx: `deploy/nginx-medycabrain.conf`, poi
   `sudo certbot --nginx -d medycabrain.messtudent.com`.
8. cron: `deploy/crontab.txt`.

## Note legali

Lo scraping di Instagram viola i ToS della piattaforma. Questo strumento
raccoglie **solo dati pubblici**, è privato e ad uso interno del cliente
("monitoraggio contenuti competitor"). Da comunicare al cliente per iscritto.
