# La banca dati Medyca dentro Claude — connettore MCP

Il cliente può aggiungere la knowledge bank al **suo** Claude (claude.ai o
Claude Desktop) e fargli domande fondate sui suoi dati: i reel di
@medyca.menopausa, i reel dei competitor, gli articoli del blog medyca.it e
dei blog dei competitor.

## L'indirizzo da dare al cliente

L'URL È la credenziale (contiene un segreto): trattarlo come una password.
Per stamparlo:

```
cd /home/giuseppe/projects/medycabrain/BEC
echo "https://messtudent.com/medyca-mcp/$(grep '^MCP_SECRET=' .env | cut -d= -f2)/mcp"
```

Per ruotarlo (es. se l'URL è finito nelle mani sbagliate): cambiare
`MCP_SECRET` in `.env` con un valore nuovo
(`python3 -c "import secrets; print(secrets.token_urlsafe(24))"`),
poi `sudo systemctl restart medycabrain-mcp` e dare al cliente il nuovo URL.
Il vecchio smette di funzionare all'istante.

## Istruzioni per il cliente (da girare così come sono)

1. Su **claude.ai**: icona del profilo → **Settings** → **Connectors**
   → **Add custom connector**
2. Nome: `Medyca Content Intelligence`
3. URL: *(l'indirizzo qui sopra)*
4. **Add** — nessun login richiesto: l'indirizzo stesso è la chiave
5. In una nuova chat, il connettore compare tra gli strumenti (icona 🔌).
   Da lì Claude può consultare la banca dati da solo.

Domande che funzionano bene:
- *"Che temi trattano i competitor che noi non tocchiamo?"*
- *"Cerca cosa abbiamo detto sul Bijuva e riassumi le affermazioni"*
- *"Confronta come noi e i competitor parliamo di perimenopausa"*
- *"Leggi l'articolo più recente della Missori e dimmi se ci conviene
  rispondere con un reel"*

## Cosa espone (sola lettura)

| Tool | Cosa fa |
|---|---|
| `panoramica` | i numeri della banca: reel/articoli per proprietario, fonti, temi |
| `cerca` | ricerca semantica+lessicale su trascrizioni, articoli e analisi |
| `leggi` | testo completo di un contenuto: trascrizione o articolo, analisi, affermazioni con citazione |
| `temi` | la mappa dei temi correnti (cluster) con esempi di affermazioni |

Nessun tool scrive: il connettore non può modificare, cancellare o avviare
nulla.

## Come è fatto (per chi manutiene)

- `mcp_bridge/server.py` — SDK MCP ufficiale (streamable HTTP, risposte
  JSON, stateless), Django ORM in-process. Riusa `core.knowledge`
  (stesso recupero della chat interna: ranking ibrido, quote per lato),
  quindi le due superfici rispondono dagli stessi dati con la stessa logica.
- Servizio dedicato: systemd `medycabrain-mcp`, uvicorn su `127.0.0.1:8025`
  (l'8020 era occupata da ig-reels-publisher). Processo separato dal
  backend: una chiamata MCP lenta non occupa i worker dell'app.
- HTTPS: i connettori claude.ai lo esigono; si appoggia al certificato di
  messtudent.com (`location /medyca-mcp/` nel server 443 di
  `sites-enabled/spi`). Il dominio medycabrain non ha ancora DNS/SSL propri.
- Autenticazione: segreto nel percorso, verificato dall'app (non da nginx,
  così ruota da `.env` senza sudo). OAuth completo (authorization server +
  dynamic client registration) sarebbe sproporzionato per un solo cliente —
  scelta consapevole, non dimenticanza. Chi ha l'URL legge tutto:
  è il compromesso, ed è scritto qui.
- All'avvio il servizio precarica embedder e indice (a freddo la prima
  ricerca costava 14s; a caldo ~0,5s).
