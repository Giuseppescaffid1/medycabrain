---
id: 2026-11-13-ollama-sei-thread
titolo: Ollama usa 6 thread invece di 18 (5 volte più veloce su questo VDS)
stato: revisione
ramo: feat/ollama-sei-thread
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Giuseppe, 13/11/2026: «Non è possibile, bisogna ottimizzare questo aspetto
prima di procedere [...] Non può andare così lento». Dopo le misure, alla
domanda "6 thread dentro Processi locali o PR separata prima?" ha risposto
«come vuoi tu». Il capo sceglie: PR separata e piccola, prima.

Lavoro piccolo: niente giro completo della squadra. Scrive lo sviluppatore,
il capo verifica con una chiamata vera e apre la PR.

## 2. Disegno            (capo, al posto dell'architetto)

**Causa misurata** (dettaglio nel registro di
`.claude/tasks/2026-11-13-processi-locali.md`): Ollama di default usa tutti i
18 core. Su questo VDS (EPYC Zen 1, KVM) il tetto è la memoria, non i core, e
sopra i 6 thread la generazione crolla: qwen2.5 7b Q4_K_M fa 0,2-0,8 tok/s a
18 thread, 1,4-1,9 a 12, **3,8-4,0 a 6**, 2,9-3,2 a 4.

**Modifica** (3 file di codice/config, più documentazione):

1. `BEC/config/settings/base.py`, vicino a `OLLAMA_MODEL`: nuova impostazione
   `OLLAMA_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", "6"))`, con un
   commento che dice il vincolo e i numeri qui sopra (non che ripete il
   codice). Valore `0` = non mandare l'opzione (lascia decidere Ollama).
2. `BEC/llm/client.py`, `_ollama_chat`: se `settings.OLLAMA_NUM_THREAD > 0`,
   aggiungere `"num_thread": settings.OLLAMA_NUM_THREAD` a `payload["options"]`.
   Cercare con grep se esistono altri punti che chiamano Ollama direttamente
   (`/api/chat`, `/api/generate`, `/api/embed`) e applicare la stessa opzione
   solo dove si genera testo. Aggiornare il commento in cima al modulo.
3. `BEC/.env.example`: aggiungere `OLLAMA_NUM_THREAD=6` con mezza riga di
   spiegazione. **Non toccare `BEC/.env`** (non è nel repo; il default 6 basta).
4. `documentation/low-level/03-llm-and-embeddings.md`: nella parte su Ollama
   scrivere il vincolo con i numeri misurati e la nuova impostazione;
   correggere la riga 73 ("~1-3 tok/s on this CPU") con i numeri veri del 7b a
   6 thread e dire che il 3b va rimisurato. Scrivere anche i limiti noti:
   tetto della macchina ~5,6-7 tok/s in totale per il 7b, lettura del prompt
   9-13 tok/s, pagine grandi e attesa passiva provate senza guadagno.
5. Se esiste un test dei parametri di `_ollama_chat`, aggiornarlo; altrimenti
   aggiungerne uno piccolo che controlla che `num_thread` finisca nel payload
   (e che con `0` non ci finisca), senza chiamare Ollama davvero.

**Fuori da questo lavoro**: risposte in parallelo (`OLLAMA_NUM_PARALLEL`,
serve sudo e togliere il lucchetto), scelta 3b/7b, finestra di 4096 token,
pagina "Processi locali".

**Non committare** `.claude/tasks/2026-11-13-processi-locali.md`: appartiene
all'altro lavoro e resta fuori da questo ramo. Questo file invece sì.

## 3. Sviluppo           (sviluppatore)

File toccati:
- `BEC/config/settings/base.py`: `OLLAMA_NUM_THREAD` (default 6) con i numeri misurati nel commento.
- `BEC/llm/client.py`: `_ollama_chat` aggiunge `options.num_thread` se > 0; nota in cima al modulo.
- `BEC/.env.example`: `OLLAMA_NUM_THREAD=6`. `BEC/.env` non toccato.
- `documentation/low-level/03-llm-and-embeddings.md`: vincolo e numeri, riga della tabella corretta (7b ~3,8-4,0 tok/s a 6 thread, 3b da rimisurare), limiti noti (tetto ~5,6-7 tok/s, prompt 9-13 tok/s, pagine grandi e attesa passiva senza guadagno).
- `BEC/core/tests/test_ollama_options.py` (nuovo): con 6 `num_thread` finisce nel payload, con 0 no; `requests.post` finto.

Test: `manage.py test core.tests.test_ollama_options` -> 2 test, OK.

Scelte: nessun test esistente per `_ollama_chat`, quindi ne ho aggiunto uno nuovo. Il grep
non trova altre chiamate a Ollama per generare testo (solo `/api/chat` in `client.py`; `/api/tags`
e' solo un controllo di disponibilita').

Rimasto fuori (come da disegno): `OLLAMA_NUM_PARALLEL`, scelta 3b/7b, finestra 4096, pagina
"Processi locali". Il 3b non e' stato rimisurato. Non ho eseguito una chiamata vera a Ollama.
## 4. Revisione          (revisore)
## 5. Collaudo           (collaudatore)
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-13 - 6 e non 4 o 8: è il massimo misurato (3,8-4,0 tok/s); a 4 si
  scende a ~3,0, a 9 a 2,4. Resta configurabile da env perché su un'altra
  macchina il numero giusto sarà diverso.
