#!/usr/bin/env bash
# Stampa il messaggio pronto da inoltrare ad Alberto, con l'URL segreto
# inserito. L'URL è la credenziale: il messaggio va mandato in privato.
set -euo pipefail
cd "$(dirname "$0")/.."
# Il link INVITO, non l'URL col segreto: due inoltri consecutivi hanno
# mutilato l'URL lungo (uno spazio guadagnato, tre caratteri e /mcp persi).
# Il link corto sopravvive ai messenger; l'URL vero si copia dalla pagina
# col bottone, che non sbaglia.
INVITE=$(grep '^MCP_INVITE=' .env | cut -d= -f2)
URL="https://messtudent.com/medyca-mcp/invito/${INVITE}"

cat <<EOF
Ciao Alberto! Da oggi puoi interrogare la banca dati di Medyca direttamente
dal tuo Claude — reel nostri, reel dei competitor e articoli dei blog.

COME SI ATTIVA (2 minuti, serve un piano Claude a pagamento):

1. Apri questa pagina: ${URL}
2. Premi il bottone "Copia l'indirizzo"
3. Su claude.ai: Settings → Connectors → "Add custom connector"
   Nome:  Medyca Content Intelligence
   URL:   (incolla quello copiato al punto 2)
4. Clicca "Add". Non chiede login: l'indirizzo stesso è la chiave,
   quindi NON condividerlo con nessuno (è come una password).
5. Apri una nuova chat: nel menu degli strumenti (icona ⚙/🔌 sotto la
   casella di testo) vedrai "Medyca Content Intelligence" attivo.

Da lì chiedi quello che vuoi, in italiano. Esempi che funzionano bene:

• "Fai una panoramica di cosa c'è nella banca dati Medyca"
• "Che temi trattano i competitor che noi non tocchiamo?"
• "Cerca cosa abbiamo detto sul Bijuva e riassumi le affermazioni"
• "Confronta come noi e i competitor parliamo di perimenopausa"
• "Leggi l'ultimo articolo della Missori e dimmi se ci conviene
  rispondere con un reel"

Claude cita sempre da quale contenuto (e di chi) viene ogni affermazione,
e distingue ciò che diciamo noi da ciò che dicono i competitor.

Il connettore è in sola lettura: può consultare, non può modificare nulla.
Funziona anche dall'app Claude su telefono (stesso account).
EOF
