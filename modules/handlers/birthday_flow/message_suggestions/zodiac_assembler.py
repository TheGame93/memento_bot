"""zodiac_assembler.py — Procedural Italian zodiac birthday message assembly.

Chunk-based assembler with trait phrases for all 12 Western signs and 12
Eastern animals.  Produces plain-text messages (no Markdown) suitable for
sending without a parse_mode.

Public API
----------
assemble_zodiac_message(western_info, eastern_info, *, turning_age, title,
                        use_western, use_eastern, rng) -> str | None
"""
from __future__ import annotations

import random as _random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Static trait data
# ---------------------------------------------------------------------------

# Each phrase is written as a predicate that completes the sentence:
#   "Da [Segno], {trait}."
# All phrases avoid gendered adjectives that would require agreement with the
# subject, using instead constructions with "hai ...", "la tua ...",
# "il tuo ...", "sai ...", "porti ..." which are invariant.

_WESTERN_TRAITS: dict[str, list[str]] = {
    "Ariete": [
        "hai un'energia contagiosa e una determinazione che non conosce ostacoli",
        "il tuo coraggio ti spinge sempre a fare il primo passo, anche quando gli altri esitano",
        "sai come trascinare gli altri con il tuo entusiasmo autentico e la tua vitalità",
    ],
    "Toro": [
        "la tua affidabilità è un dono raro: chi ti conosce sa di poter contare su di te",
        "hai la pazienza e la costanza di chi sa che le cose migliori richiedono tempo",
        "porti stabilità e calore in ogni relazione, un punto fermo per chi ti vuole bene",
    ],
    "Gemelli": [
        "la tua mente vivace sa trovare connessioni dove gli altri non vedono nulla",
        "hai un talento naturale per la comunicazione e sai come far sentire ascoltate le persone",
        "la tua curiosità insaziabile ti porta sempre a scoprire nuovi orizzonti e idee",
    ],
    "Cancro": [
        "il tuo cuore generoso sa prendersi cura degli altri con una sensibilità unica",
        "hai un'intuizione straordinaria e sai capire le persone a un livello profondo",
        "sei un punto di riferimento prezioso per chi ti vuole bene, una presenza sicura e affettuosa",
    ],
    "Leone": [
        "il tuo carisma e la tua generosità hanno il potere di illuminare ogni ambiente",
        "hai una presenza che ispira fiducia e porta calore ovunque tu vada",
        "la tua passione e la tua vitalità aprono porte e creano possibilità per chi ti sta vicino",
    ],
    "Vergine": [
        "la tua precisione e il tuo senso del dettaglio fanno sempre la differenza",
        "hai una mente analitica che sa trasformare anche le situazioni più complesse in opportunità",
        "la tua affidabilità e la tua dedizione sono qualità rare, sempre apprezzate da chi ti conosce",
    ],
    "Bilancia": [
        "hai un senso innato dell'armonia e sai come trovare l'equilibrio anche nelle situazioni più difficili",
        "la tua diplomazia e la tua eleganza creano ponti dove altri vedono solo muri",
        "sai ascoltare con il cuore e dare consigli che fanno davvero la differenza per chi ti chiede aiuto",
    ],
    "Scorpione": [
        "hai una profondità di carattere e una passione che lasciano un segno indelebile in chi ti incontra",
        "la tua determinazione è inarrestabile: quando ti poni un obiettivo, sai come raggiungerlo",
        "il tuo istinto acuto ti permette di vedere oltre le apparenze e capire ciò che gli altri non vedono",
    ],
    "Sagittario": [
        "la tua sete di avventura e il tuo ottimismo sono un dono contagioso per chi ti sta vicino",
        "hai una visione del mondo ampia e generosa che ispira chi ha la fortuna di conoscerti",
        "la tua energia e la tua libertà interiore aprono porte e fanno sembrare possibile l'impossibile",
    ],
    "Capricorno": [
        "la tua disciplina e la tua ambizione ti permettono di costruire qualcosa di duraturo nel tempo",
        "hai la capacità di trasformare la fatica in risultati concreti, passo dopo passo",
        "la tua responsabilità e la tua maturità sono un esempio ispirante per chi ha la fortuna di stare al tuo fianco",
    ],
    "Acquario": [
        "la tua originalità e il tuo pensiero indipendente aprono nuove strade dove gli altri non osano",
        "hai una visione del futuro unica e sai come portare idee fresche e innovative in ogni situazione",
        "il tuo spirito libero e la tua apertura mentale ispirano chi ti conosce a pensare in grande",
    ],
    "Pesci": [
        "la tua sensibilità e la tua creatività ti permettono di vedere il mondo con occhi speciali",
        "hai una capacità empatica straordinaria: sai sempre come far sentire gli altri compresi e valorizzati",
        "il tuo spirito sognatore porta poesia e profondità in tutto ciò che tocca",
    ],
}

# Each phrase completes: "Da [Animal] del calendario cinese, {trait}."
_EASTERN_TRAITS: dict[str, list[str]] = {
    "Ratto": [
        "hai una mente brillante e piena di risorse, sempre pronta a trovare soluzioni creative",
        "la tua curiosità e la tua adattabilità ti permettono di eccellere in ogni situazione",
        "il tuo intuito acuto sa cogliere le opportunità prima che si presentino agli altri",
    ],
    "Bue": [
        "la tua laboriosità e la tua determinazione trasformano ogni progetto in un risultato concreto",
        "hai una solidità e una perseveranza che sono la tua forza più grande e più rispettata",
        "la tua affidabilità e il tuo impegno costante conquistano la fiducia e il rispetto di tutti",
    ],
    "Tigre": [
        "hai un coraggio e un carisma che attirano naturalmente l'attenzione di chi ti sta intorno",
        "la tua energia vitale e la tua passione rendono ogni cosa che fai memorabile e speciale",
        "sai quando lanciarti con decisione e quando attendere il momento giusto: una dote strategica naturale",
    ],
    "Coniglio": [
        "la tua gentilezza e il tuo tatto creano armonia e serenità in ogni situazione",
        "hai una sensibilità raffinata e un gusto per le cose belle che ti rendono unico e speciale",
        "la tua diplomazia naturale ti permette di navigare anche le situazioni più delicate con grazia",
    ],
    "Drago": [
        "hai una forza interiore e un carisma rari che ti rendono un punto di riferimento naturale",
        "la tua ambizione e la tua energia inesauribile spostano i confini di ciò che è possibile",
        "il tuo spirito vivace e la tua generosità conquistano chi ha il privilegio di conoscerti davvero",
    ],
    "Serpente": [
        "la tua saggezza e la tua intuizione ti permettono di vedere oltre le apparenze",
        "hai una mente raffinata e un senso strategico che ti rende formidabile nei momenti che contano davvero",
        "il tuo charme discreto e la tua profondità di pensiero ti distinguono e ti rendono indimenticabile",
    ],
    "Cavallo": [
        "la tua energia e la tua sete di libertà ti portano sempre verso nuove avventure e scoperte",
        "hai un'esuberanza e un entusiasmo che rendono la vita più vivace e interessante per chi ti circonda",
        "la tua indipendenza e il tuo spirito avventuriero sono una fonte di ispirazione continua per chi ti conosce",
    ],
    "Capra": [
        "la tua creatività e la tua sensibilità artistica aggiungono bellezza al mondo intorno a te",
        "hai un cuore generoso e una dolcezza d'animo che creano legami autentici e duraturi",
        "la tua intuizione e il tuo spirito armonioso portano pace e serenità nelle relazioni",
    ],
    "Scimmia": [
        "la tua intelligenza vivace e la tua versatilità ti permettono di adattarti brillantemente a qualsiasi situazione",
        "hai un ingegno brillante e un senso dell'umorismo che rendono la vita più leggera per tutti",
        "la tua curiosità e la tua creatività aprono soluzioni innovative dove gli altri vedono solo problemi",
    ],
    "Gallo": [
        "la tua diligenza e la tua attenzione ai dettagli sono qualità che fanno davvero la differenza",
        "hai un senso del dovere e una precisione che ispirano fiducia e rispetto in chi ti circonda",
        "la tua determinazione e la tua ambizione ti permettono di raggiungere anche i traguardi più sfidanti",
    ],
    "Cane": [
        "la tua lealtà e la tua onestà sono le fondamenta solide di ogni rapporto che costruisci",
        "hai un senso innato della giustizia e sai sempre stare dalla parte di chi ha bisogno di supporto",
        "la tua fedeltà e il tuo calore umano rendono davvero fortunato chi ha il dono di conoscerti",
    ],
    "Maiale": [
        "la tua generosità e la tua sincerità creano un clima di fiducia e affetto autentico intorno a te",
        "hai un cuore aperto e una bontà d'animo che sono qualità rare e preziose in questo mondo",
        "la tua gioia di vivere e la tua spontaneità portano allegria e leggerezza in ogni ambiente",
    ],
}

_OPENINGS: list[str] = [
    "Tanti auguri di cuore!",
    "Buon compleanno!",
    "Tanti auguri per questo giorno speciale!",
    "Che giornata speciale!",
    "Un giorno come questo merita un pensiero davvero speciale!",
]

_CLOSINGS: list[str] = [
    "Che questo anno sia ricco di gioia, sorprese meravigliose e momenti indimenticabili!",
    "Auguri per un compleanno stupendo e per un anno tutto da vivere!",
    "Che il prossimo anno ti porti tutto ciò che meriti e anche di più!",
    "Con tanti auguri affettuosi per questo tuo giorno così speciale!",
    "Che la vita continui a offrirti il meglio — te lo meriti davvero!",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_zodiac_message(
    western_info: dict | None,
    eastern_info: dict | None,
    *,
    turning_age: int | None = None,
    title: str | None = None,
    use_western: bool = True,
    use_eastern: bool = False,
    rng: _random.Random | None = None,
) -> str | None:
    """Procedurally assemble an Italian birthday message incorporating zodiac traits.

    Parameters
    ----------
    western_info : dict | None
        Output of ``zodiac.get_western_zodiac()``.  Expected keys: ``sign``,
        ``element``, ``date_range``.
    eastern_info : dict | None
        Output of ``zodiac.get_eastern_zodiac()``.  Expected keys: ``animal``,
        ``yin_yang``, ``element``, ``chinese_year``.
    turning_age : int | None
        If provided, a line mentioning the milestone age is appended.
    title : str | None
        Person's name; if provided, a personalised salutation line is added.
    use_western : bool
        Whether to include Western zodiac content.
    use_eastern : bool
        Whether to include Eastern zodiac content.
    rng : random.Random | None
        RNG instance for deterministic generation.  A fresh one is created when
        *None*.  Callers may seed with the alert_id for stable per-birthday
        output.

    Returns
    -------
    str | None
        The assembled plain-text message, or *None* if no usable zodiac info
        is available for the requested combination.
    """
    if rng is None:
        rng = _random.Random()

    can_use_western = (
        use_western
        and isinstance(western_info, dict)
        and western_info.get("sign") in _WESTERN_TRAITS
    )
    can_use_eastern = (
        use_eastern
        and isinstance(eastern_info, dict)
        and eastern_info.get("animal") in _EASTERN_TRAITS
    )

    if not can_use_western and not can_use_eastern:
        return None

    parts: list[str] = []

    # Opening
    parts.append(rng.choice(_OPENINGS))

    # Optional personalised salutation
    if title:
        parts.append(f"Un pensiero speciale per {title}.")

    # Western zodiac trait block
    if can_use_western:
        sign = western_info["sign"]  # type: ignore[index]
        traits = _WESTERN_TRAITS[sign]
        if not traits:
            return None  # defensive: static data should never be empty
        trait = rng.choice(traits)
        parts.append(f"Da {sign}, {trait}.")

    # Eastern zodiac trait block
    if can_use_eastern:
        animal = eastern_info["animal"]  # type: ignore[index]
        traits = _EASTERN_TRAITS[animal]
        if not traits:
            return None  # defensive: static data should never be empty
        trait = rng.choice(traits)
        parts.append(f"Da {animal} del calendario cinese, {trait}.")

    # Optional turning-age milestone line
    if turning_age is not None:
        try:
            age = int(turning_age)
            if age > 0:
                parts.append(f"In questo anno speciale compi {age} anni!")
        except (TypeError, ValueError):
            pass

    # Closing
    parts.append(rng.choice(_CLOSINGS))

    return "\n\n".join(parts)
