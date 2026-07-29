# Instagram Graph API — i passi manuali per attivarla

Il codice è pronto: appena `IG_GRAPH_TOKEN` compare in `.env`, lo stage
`scrape` della pipeline passa da solo al provider ufficiale (`graph`),
senza cookie e senza account personali. Questa guida copre i passi che
**solo un umano può fare** nelle interfacce di Meta.

Tempo stimato: 30-45 minuti la prima volta.

## Cosa serve, concettualmente

`business_discovery` — l'endpoint ufficiale per leggere account altrui —
va chiamato **da** un account Instagram Business. Non serve che sia
l'account del cliente: serve UN account IG Business che controlli tu,
collegato a una pagina Facebook, dentro un'app Meta. I 14 account tracciati
sono i **bersagli**, non i chiamanti.

## Passi

### 1. Account Instagram Business chiamante (5 min)
Se non ne hai già uno: crea (o riusa) un account Instagram qualsiasi →
Impostazioni → Account → **Passa a un account professionale** → Business.
Va bene un account nuovo e vuoto: fa solo da chiamante.

### 2. Pagina Facebook collegata (5 min)
L'account Business DEVE essere collegato a una pagina Facebook.
Da Instagram: Impostazioni → Account → Condivisione su altre app → Facebook
→ collega (o crea) una pagina. Anche qui: una pagina vuota va benissimo.

### 3. App Meta (10 min)
1. https://developers.facebook.com → **My Apps** → **Create App**
2. Tipo: **Business** (se chiede il caso d'uso: "Other" → Business)
3. Nome: es. `medycabrain` — non è pubblico, non serve approvazione
4. Nella dashboard dell'app: **Add product** → **Instagram Graph API** → Set up
   (serve anche **Facebook Login for Business**, di solito già incluso)

L'app può restare in **Development Mode**: per un uso interno come questo
non serve l'App Review. In Development Mode funziona per gli utenti che
hanno un ruolo sull'app — cioè tu (admin).

### 4. Il token (10 min)
1. https://developers.facebook.com/tools/explorer/ (Graph API Explorer)
2. In alto a destra: seleziona la TUA app
3. "User or Page" → **Get User Access Token**
4. Permessi da spuntare: `instagram_basic`, `pages_show_list`,
   `pages_read_engagement`, `business_management`
5. **Generate Access Token** → autorizza col tuo profilo Facebook,
   selezionando la pagina del passo 2
6. Copia il token (breve durata, ~1 ora) e **scambialo con uno lungo**
   (60 giorni):

```
curl -s "https://graph.facebook.com/v21.0/oauth/access_token\
?grant_type=fb_exchange_token\
&client_id=APP_ID\
&client_secret=APP_SECRET\
&fb_exchange_token=TOKEN_BREVE"
```

`APP_ID` e `APP_SECRET` sono in App Dashboard → Settings → Basic.
La risposta contiene `access_token`: quello è il token lungo.

### 5. Configura e verifica (5 min)

```
! echo 'IG_GRAPH_TOKEN=EAAG...' >> /home/giuseppe/projects/medycabrain/BEC/.env
cd /home/giuseppe/projects/medycabrain/BEC
venv/bin/python manage.py graph_check
```

`graph_check` valida il token, risolve l'id del chiamante (stampalo in
`.env` come `IG_GRAPH_USER_ID=...` come suggerisce), e **interroga uno per
uno i 14 account tracciati**, dicendo per ciascuno:
- se è interrogabile (deve essere Business/Creator — i profili personali
  non lo sono, e per quelli l'API ufficiale semplicemente non esiste);
- se i suoi video arrivano con `media_url` (= scaricabili e trascrivibili)
  o solo con i metadati (didascalie e conteggi, niente audio).

Rilancia con `--save` per registrare i verdetti: gli account non
interrogabili vengono saltati dalle raccolte future invece di fallire ogni
notte.

### 6. Fine
Nessun altro passo: la pipeline notturna riparte da sola col provider
`graph`. Riavvia il backend se vuoi vederlo subito
(`sudo systemctl restart medycabrain-backend` non serve: lo scraper gira
da cron/CLI e legge `.env` a ogni avvio).

## Cose da sapere

- **Il token lungo scade dopo 60 giorni.** Rinnovo: ripeti il passo 4.6 col
  token corrente (finché è valido, lo scambio lo rinnova). Un promemoria in
  calendario a ~50 giorni evita la sorpresa.
- **view/plays non ci sono** via business_discovery: per i competitor
  l'engagement si baserà su like e commenti. È un limite di Meta, non nostro.
- **`media_url` per i video altrui può mancare** (Meta lo omette a sua
  discrezione). Dove manca, l'API dà metadati e didascalie; il video per la
  trascrizione richiede Apify (a consumo) o resta fuori. `graph_check` lo
  misura account per account: decidere dopo aver visto i numeri.
- I profili **personali** (non Business/Creator) sono invisibili all'API
  ufficiale, per scelta di Meta. Se un competitor importante risulta ✗,
  le opzioni sono: accettare di non seguirlo, o seguirlo via Apify.
