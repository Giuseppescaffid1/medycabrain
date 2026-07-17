"""
llm/prompts.py
==============
All Italian LLM prompts in one place. Domain context: contenuti Instagram
nella nicchia salute femminile / menopausa (ispirazione: medyca.it).
"""

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

ENRICH_USER_TEMPLATE = """\
Analizza questo reel di Instagram.

DIDASCALIA:
{caption}

TRASCRIZIONE AUDIO:
{transcript}

Restituisci un JSON con esattamente questi campi:
{{
  "summary_it": "riassunto del contenuto in 1-2 frasi, in italiano",
  "topics": ["3-6 argomenti/parole chiave in italiano, minuscolo"],
  "hook_text": "la frase/gancio iniziale che cattura l'attenzione (dalle prime battute)",
  "hook_analysis_it": "perché il gancio funziona o no, 1 frase in italiano",
  "target_audience_it": "a chi si rivolge il contenuto, 1 frase in italiano",
  "content_format": "uno tra: talking_head, voiceover, tutorial, testimonianza, text_overlay, intervista, altro"
}}
"""

# ── Argument extraction: one call per reel (layer 2) ────────────────────────────

ARGUMENTS_SYSTEM = (
    "Sei un analista che estrae le affermazioni/argomenti principali dai contenuti. "
    + DOMAIN_CONTEXT
    + " Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido."
)

ARGUMENTS_USER_TEMPLATE = """\
Estrai gli argomenti o affermazioni principali espressi in questo reel.
Ogni argomento deve essere una frase autonoma e comprensibile da sola, in italiano
(es. "La soia può ridurre le vampate di calore", "La terapia ormonale non aumenta
sempre il rischio di tumore al seno").

DIDASCALIA:
{caption}

TRASCRIZIONE:
{transcript}

Restituisci un JSON:
{{ "argomenti": ["affermazione 1", "affermazione 2", "..."] }}
Da 2 a 6 argomenti. Se il contenuto non contiene affermazioni chiare, restituisci
una lista vuota.
"""

# ── Cluster naming (layer 1) ────────────────────────────────────────────────────

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
