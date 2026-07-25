"""
llm/prompts.py
==============
All Italian LLM prompts in one place. Domain context: contenuti Instagram
nella nicchia salute femminile / menopausa (ispirazione: medyca.it).
"""


# Recurring domain terms. Whisper conditions on this text, which is what stops
# "ormoni bioidentici" coming back as "umonibirentici" / "ormoni parentici".
MEDICAL_GLOSSARY = (
    "Terminologia medica ricorrente: ormoni bioidentici, terapia ormonale "
    "sostitutiva (TOS), estrogeni, progesterone, testosterone, DHEA, "
    "perimenopausa, menopausa, andropausa, osteoporosi, tiroide, Bijuva, "
    "vampate di calore, atrofia vulvovaginale, densitometria ossea, "
    "sindrome genito-urinaria della menopausa."
)

DOMAIN_CONTEXT = (
    "Il contesto è la creazione di contenuti Instagram in italiano nella nicchia "
    "della salute femminile, con particolare attenzione alla menopausa, "
    "perimenopausa, benessere ormonale, sessualità e invecchiamento in salute. "
    "L'obiettivo dell'analisi è aiutare un'attività a trarre ispirazione dai "
    "contenuti dei competitor."
)

# ── Enrichment: one call per reel ──────────────────────────────────────────────

ENRICH_SYSTEM = (
    "Sei un analista esperto di contenuti social in lingua italiana. "
    + DOMAIN_CONTEXT
    + " Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido, senza testo "
    "aggiuntivo e senza blocchi di codice."
)

ENRICH_USER_TEMPLATE = """Analizza questo reel di Instagram.

DIDASCALIA:
{caption}

TRASCRIZIONE AUDIO:
{transcript}

REGOLE FONDAMENTALI:
- Descrivi SOLO ciò che è realmente presente nella didascalia o nella
  trascrizione. Non dedurre, non completare, non immaginare.
- Se un campo non è determinabile dal materiale, restituisci stringa vuota
  (o lista vuota). Un campo vuoto è una risposta corretta.
- "hook_text" va compilato SOLO se c'è del parlato: copia le prime parole
  effettivamente pronunciate. Senza trascrizione lascialo vuoto.
- "topics" solo argomenti davvero trattati (da 0 a 6). Non aggiungere temi
  di menopausa o salute ormonale se il contenuto non ne parla.
- "is_on_topic": false se il reel non riguarda salute femminile, menopausa o
  benessere ormonale (es. auguri, eventi, sport, promozioni generiche).

Restituisci un JSON con questi campi:
{{
  "summary_it": "riassunto fedele in 1-2 frasi, in italiano ('' se non determinabile)",
  "topics": ["argomenti realmente trattati, minuscolo, 0-6 elementi"],
  "hook_text": "prime parole pronunciate ('' se non c'è parlato)",
  "hook_analysis_it": "perché il gancio funziona ('' se non c'è gancio)",
  "target_audience_it": "a chi si rivolge ('' se non determinabile)",
  "content_format": "uno tra: talking_head, voiceover, tutorial, testimonianza, text_overlay, intervista, altro",
  "is_on_topic": true,
  "off_topic_reason": "se is_on_topic è false, di cosa parla davvero ('' altrimenti)"
}}
"""


ENRICH_CAPTION_ONLY_NOTE = """
ATTENZIONE: questo reel NON ha parlato (nessuna trascrizione disponibile).
Basati esclusivamente sulla didascalia. Lascia "hook_text" e
"hook_analysis_it" vuoti. Non attribuire al video contenuti che non sono
scritti nella didascalia.
"""


ARGUMENTS_SYSTEM = (
    "Sei un analista che estrae affermazioni verificabili da un contenuto "
    "trascritto. Riporti solo ciò che è stato realmente detto, mai ciò che "
    "potrebbe essere stato detto. Rispondi SEMPRE ed esclusivamente con un "
    "oggetto JSON valido."
)

# Deliberately example-free: the previous version carried two sample claims,
# and the model returned them verbatim on reels that never mentioned them
# (25+ such rows in the database). Grounding is enforced in code instead:
# every "citazione" must appear in the transcript or the argument is dropped.
ARGUMENTS_USER_TEMPLATE = """Estrai le affermazioni principali effettivamente
espresse in questo contenuto.

TRASCRIZIONE:
{transcript}

DIDASCALIA:
{caption}

REGOLE:
- Ogni affermazione deve essere sostenuta da una CITAZIONE TESTUALE copiata
  parola per parola dalla trascrizione (o dalla didascalia se non c'è audio).
- Non parafrasare la citazione: deve essere una porzione esatta del testo.
- Se il contenuto non contiene affermazioni chiare, restituisci lista vuota.
  La lista vuota è una risposta corretta e preferibile a un'affermazione
  generica.
- Massimo 6 affermazioni. Nessun minimo.

Restituisci un JSON:
{{"argomenti": [{{"testo": "affermazione riformulata in modo autonomo",
                 "citazione": "porzione esatta del testo che la sostiene"}}]}}
"""


CLUSTER_NAME_SYSTEM = (
    "Sei un analista di contenuti Instagram. "
    + DOMAIN_CONTEXT
    + " Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido."
)

CLUSTER_NAME_USER_TEMPLATE = """\
Questi sono alcuni contenuti rappresentativi di uno stesso gruppo tematico:

{samples}

Assegna a questo gruppo:
- un nome breve (massimo 5 parole), in italiano
- una descrizione (massimo 2 frasi), in italiano
- 3-6 parole chiave in italiano

Restituisci un JSON:
{{ "label_it": "...", "description_it": "...", "keywords": ["...", "..."] }}
"""
