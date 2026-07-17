"""
seed_demo
=========
Insert synthetic-but-realistic Italian menopause reels (with transcripts +
enrichments already filled) so the cluster stage and the FEC can be
demoed/verified without live scraping or an HF token.

    python manage.py seed_demo
    python manage.py seed_demo --clear

Marks rows enrich_status='done' so `run_pipeline --only cluster` will
embed + cluster them with the local model.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    DONE, Enrichment, Reel, ReelArgument, TrackedAccount, Transcript,
)

ACCOUNTS = ["medyca.it", "menopausa.serena", "ginecologa.online", "over50wellness"]

# (topic-group, summary, topics, transcript, arguments, format)
DEMO = [
    ("vampate", "Consigli pratici per gestire le vampate di calore in menopausa.",
     ["vampate", "menopausa", "rimedi naturali"],
     "Le vampate di calore sono uno dei sintomi più comuni della menopausa. "
     "Vestiti a strati, evita cibi piccanti e caffeina, e prova la respirazione "
     "profonda quando arriva l'ondata di calore.",
     ["Vestirsi a strati aiuta a gestire le vampate",
      "Caffeina e cibi piccanti peggiorano le vampate"], "talking_head"),
    ("vampate", "Perché arrivano le vampate e cosa succede al corpo.",
     ["vampate", "ormoni", "estrogeni"],
     "Quando gli estrogeni calano, l'ipotalamo si confonde e crede che tu abbia "
     "troppo caldo, così dilata i vasi e ti fa sudare. È fisiologia, non sei tu.",
     ["Il calo di estrogeni altera la termoregolazione dell'ipotalamo",
      "Le vampate sono un fenomeno fisiologico"], "voiceover"),
    ("vampate", "3 rimedi naturali contro le vampate che funzionano davvero.",
     ["rimedi naturali", "vampate", "salvia"],
     "Salvia, trifoglio rosso e una dieta ricca di fitoestrogeni possono ridurre "
     "la frequenza delle vampate. Non sono miracoli ma aiutano.",
     ["La salvia può ridurre la frequenza delle vampate",
      "I fitoestrogeni aiutano contro le vampate"], "tutorial"),
    ("terapia_ormonale", "La verità sulla terapia ormonale sostitutiva.",
     ["terapia ormonale", "TOS", "estrogeni"],
     "La terapia ormonale sostitutiva non causa il tumore al seno nella maggior "
     "parte delle donne, se iniziata al momento giusto e sotto controllo medico. "
     "Parlane con il tuo ginecologo.",
     ["La terapia ormonale non aumenta sempre il rischio di tumore al seno",
      "La TOS va iniziata al momento giusto"], "intervista"),
    ("terapia_ormonale", "Chi può fare la terapia ormonale e chi no.",
     ["terapia ormonale", "controindicazioni"],
     "Non tutte possono fare la TOS: chi ha avuto trombosi o certi tumori deve "
     "valutare alternative. Ma per molte donne i benefici superano i rischi.",
     ["Le donne con storia di trombosi devono valutare alternative alla TOS",
      "Per molte donne i benefici della TOS superano i rischi"], "talking_head"),
    ("terapia_ormonale", "Estrogeni in gel vs pastiglie: quale scegliere.",
     ["estrogeni", "terapia ormonale", "gel"],
     "Gli estrogeni transdermici in gel hanno un rischio trombotico più basso "
     "rispetto alle pastiglie perché saltano il passaggio epatico.",
     ["Gli estrogeni in gel hanno minor rischio trombotico delle pastiglie"],
     "voiceover"),
    ("ossa", "Menopausa e osteoporosi: proteggi le tue ossa.",
     ["osteoporosi", "ossa", "calcio"],
     "Dopo la menopausa la densità ossea cala rapidamente. Calcio, vitamina D e "
     "allenamento con i pesi sono i tuoi migliori alleati contro l'osteoporosi.",
     ["Il calo di estrogeni accelera la perdita di densità ossea",
      "L'allenamento coi pesi protegge dall'osteoporosi"], "tutorial"),
    ("ossa", "Perché dovresti sollevare pesi dopo i 50 anni.",
     ["allenamento", "ossa", "forza"],
     "Il sollevamento pesi non ti fa diventare grossa: stimola le ossa a "
     "rinforzarsi e mantiene il metabolismo attivo. Fondamentale in menopausa.",
     ["Il sollevamento pesi rinforza le ossa dopo i 50 anni",
      "L'allenamento di forza mantiene attivo il metabolismo"], "talking_head"),
    ("ossa", "Vitamina D: quanta ne serve davvero in menopausa.",
     ["vitamina D", "integratori", "ossa"],
     "In menopausa servono circa 800-1000 UI di vitamina D al giorno per "
     "assorbire il calcio e proteggere le ossa. Fatti controllare i valori.",
     ["Servono circa 800-1000 UI di vitamina D al giorno in menopausa"],
     "voiceover"),
    ("peso", "Perché in menopausa si ingrassa sulla pancia.",
     ["peso", "metabolismo", "pancia"],
     "Con il calo degli estrogeni il grasso si redistribuisce sull'addome e il "
     "metabolismo rallenta. Non è colpa tua, è ormonale, ma puoi contrastarlo.",
     ["In menopausa il grasso si redistribuisce sull'addome",
      "Il calo di estrogeni rallenta il metabolismo"], "talking_head"),
    ("peso", "Cosa mangiare per non ingrassare in menopausa.",
     ["alimentazione", "peso", "proteine"],
     "Aumenta le proteine, riduci gli zuccheri raffinati e non saltare i pasti. "
     "Le proteine mantengono la massa muscolare che brucia calorie.",
     ["Aumentare le proteine aiuta a mantenere la massa muscolare",
      "Ridurre gli zuccheri raffinati aiuta il controllo del peso"], "tutorial"),
    ("umore", "Menopausa e sbalzi d'umore: non stai impazzendo.",
     ["umore", "ansia", "ormoni"],
     "Gli sbalzi ormonali influenzano serotonina e dopamina, quindi ansia e "
     "irritabilità sono comuni. Non sei tu che esageri, è la chimica del cervello.",
     ["Gli sbalzi ormonali influenzano serotonina e dopamina",
      "Ansia e irritabilità in menopausa hanno una base ormonale"], "voiceover"),
    ("umore", "Come dormire meglio durante la menopausa.",
     ["sonno", "insonnia", "benessere"],
     "L'insonnia in menopausa è legata alle vampate notturne e al calo del "
     "progesterone. Camera fresca, niente schermi e una routine fissa aiutano.",
     ["Il calo del progesterone contribuisce all'insonnia in menopausa",
      "Una camera fresca riduce i risvegli notturni"], "talking_head"),
]


class Command(BaseCommand):
    help = "Seed synthetic enriched demo reels for verification/demo."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Delete demo reels first.")

    def handle(self, *args, **opts):
        if opts["clear"]:
            Reel.objects.filter(shortcode__startswith="DEMO").delete()
            self.stdout.write("Cleared demo reels.")

        accounts = {}
        for i, name in enumerate(ACCOUNTS):
            acc, _ = TrackedAccount.objects.get_or_create(
                username=name,
                defaults={"display_name": name.replace(".", " ").title(),
                          "followers_count": 5000 * (i + 3)},
            )
            accounts[name] = acc

        now = timezone.now()
        created = 0
        for idx, (grp, summary, topics, transcript, arguments, fmt) in enumerate(DEMO):
            acc = accounts[ACCOUNTS[idx % len(ACCOUNTS)]]
            shortcode = f"DEMO{idx:03d}"
            reel, _ = Reel.objects.update_or_create(
                shortcode=shortcode,
                defaults={
                    "account": acc,
                    "caption": summary,
                    "posted_at": now - timedelta(days=idx),
                    "duration_s": 45.0,
                    "view_count": 12000 + idx * 830,
                    "like_count": 640 + idx * 47,
                    "comment_count": 20 + idx * 3,
                    "media_status": DONE,
                    "transcribe_status": DONE,
                    "enrich_status": DONE,
                    "argument_status": DONE,
                    "is_active": True,
                },
            )
            Transcript.objects.update_or_create(
                reel=reel,
                defaults={"text": transcript, "language": "it",
                          "segments": [{"start": 0, "end": 45, "text": transcript}],
                          "model_name": "demo", "audio_duration_s": 45.0},
            )
            Enrichment.objects.update_or_create(
                reel=reel,
                defaults={"summary_it": summary, "topics": topics,
                          "hook_text": transcript.split(".")[0],
                          "hook_analysis_it": "Apre con un'affermazione empatica.",
                          "target_audience_it": "Donne 45-60 anni in menopausa.",
                          "content_format": fmt, "llm_model": "demo"},
            )
            reel.arguments.all().delete()
            for a in arguments:
                ReelArgument.objects.create(reel=reel, text_it=a)
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created} demo reels across {len(accounts)} accounts. "
            f"Run `run_pipeline --only cluster` to cluster them."
        ))
