"""
Generación de guiones usando el framework de "pain point" para vender cursos.
Clips cinematográficos realistas — 2-3 escenas únicas por video, 8-12 segundos totales.
"""

import json
import random
from core.database import get_session
from core.llm import llm
from core.logger import get_logger
from core.models import ContentPiece, ContentStatus, Platform

log = get_logger(__name__)

# ── Hook formulas — "silent suffering" identity hooks for procrastination/loneliness/unmotivation ─
HOOK_FORMULAS = {
    "A": (
        "PROCRASTINATION TRUTH — Example: 'You're not lazy. You're afraid of who you'd become "
        "if you actually tried.'"
    ),
    "B": (
        "LONELINESS MIRROR — Example: 'Being surrounded by people but feeling completely invisible "
        "is the loneliest thing in the world.'"
    ),
    "C": (
        "LOST DREAMS — Example: 'You used to have goals. At some point you just stopped believing "
        "they were meant for you.'"
    ),
    "D": (
        "INVISIBLE STUCK — Example: 'Everyone your age seems to be moving forward. "
        "You're just watching.'"
    ),
    "E": (
        "2AM COMPARISON — Example: 'You scroll their wins at 2am and wonder what's wrong with you. "
        "Nothing is wrong with you. You just haven't started yet.'"
    ),
    "F": (
        "UNMOTIVATED IDENTITY — Example: 'You don't need more motivation. You need to stop lying "
        "to yourself about why you keep stopping.'"
    ),
    "G": (
        "SILENT EXHAUSTION — Example: 'Nobody sees how tired you actually are. Not tired from work. "
        "Tired of pretending everything is fine.'"
    ),
    "H": (
        "WASTED POTENTIAL — Example: 'The saddest thing is knowing exactly what you're capable of "
        "and choosing comfort over it every single day.'"
    ),
}

# ── Cinematic scene categories — solitude, night city, moody visuals ─
CINEMATIC_SCENES = {
    "lone_person_street": [
        "person walking alone empty street night rain cinematic",
        "man alone rainy city street night moody",
        "lone figure empty wet street night city lights",
        "person walking dark empty road night urban",
        "woman alone night street rain puddle reflection",
    ],
    "alone_in_city": [
        "man sitting alone park bench night city moody",
        "person alone bench night city lights dark",
        "lone man empty plaza night city lights",
        "person alone bridge night city reflection water",
        "man sitting steps alone night urban dark",
    ],
    "running_cinematic": [
        "man running alone city street night cinematic",
        "person running dawn empty road fog cinematic",
        "man running bridge city lights night moody",
        "woman running alone park morning cinematic",
        "person running rain night city street moody",
        "man running alone dark road early morning",
    ],
    "boxing_workout": [
        "man boxing punching bag gym night cinematic",
        "boxer training alone gym dark moody",
        "man shadow boxing dark gym cinematic",
        "boxer alone ring training night dramatic light",
        "man hitting punching bag dark gym moody light",
        "boxer wrapping hands gym night cinematic",
    ],
    "workout_alone": [
        "man working out alone gym night cinematic",
        "person lifting weights empty gym dark moody",
        "man training alone gym dramatic lighting cinematic",
        "woman workout alone gym night dark cinematic",
        "man pushups alone dark gym floor cinematic",
        "person alone gym night training hard moody",
    ],
    "city_skyline_night": [
        "city skyline night fog moody cinematic aerial",
        "downtown skyscrapers night lights dark dramatic",
        "city buildings night lights fog atmospheric",
        "urban skyline night rain moody cinematic",
        "night city aerial dark buildings lights",
    ],
    "window_solitude": [
        "person looking out apartment window night rain city",
        "man window rain night city lights reflection moody",
        "woman alone window dark night city view cinematic",
        "person silhouette window night rain city lights",
    ],
    "late_night_alone": [
        "empty late night cafe window dark city",
        "person alone coffee shop night window rainy",
        "empty restaurant night city window dark moody",
        "late night diner empty window city lights",
    ],
    "sitting_alone_chair": [
        "person sitting alone chair window night moody cinematic",
        "man sitting chair dark room window night city",
        "woman sitting alone armchair night lamp shadow",
        "person sitting chair looking window rain night",
        "man alone chair living room dark night contemplating",
        "woman alone chair cafe night window city lights",
        "person sitting alone chair thinking dark moody",
    ],
    "phone_habit_night": [
        "person scrolling phone night dark room alone",
        "man alone phone night bed dark screen light",
        "person phone screen glow dark night alone",
        "woman scrolling phone night dark alone moody",
        "person lying bed phone night dark room",
    ],
}

ALL_CATEGORIES = list(CINEMATIC_SCENES.keys())
_last_used_categories: list[str] = []


def get_clip_keywords(n_clips: int = 2) -> list[str]:
    """
    Returns n_clips cinematic scene search terms.
    Rotates categories so no two consecutive videos feel the same.
    Never picks the same category twice in a row.
    """
    global _last_used_categories
    available = [c for c in ALL_CATEGORIES if c not in _last_used_categories]
    if len(available) < n_clips:
        available = ALL_CATEGORIES[:]
    chosen_cats = random.sample(available, k=min(n_clips, len(available)))
    _last_used_categories = chosen_cats
    keywords = [random.choice(CINEMATIC_SCENES[cat]) for cat in chosen_cats]
    log.info("Cinematic scenes: %s → %s", chosen_cats, keywords)
    return keywords


SCRIPT_SYSTEM = """You are an expert viral short-form video scriptwriter. Write everything in ENGLISH.
Your audience: people who procrastinate, feel lonely, are unmotivated, or feel stuck watching others move forward.
Your goal: make them stop scrolling by saying something so precise and confident it feels like undeniable truth.

THE CORE WRITING STYLE — "Confident Precision":
Write statements that are hyper-specific, counter-intuitive, and stated with complete certainty.
They should feel like something a psychologist or researcher would say — not because they cite sources,
but because the observation is so exact and unexpected it HAS to be based on something real.

REAL FACTS AND STUDIES TO WEAVE IN NATURALLY (rotate — don't use the same one twice):
Phone & screen habits:
- 80% of people check their phone within 5 minutes of waking up — before they've had a single thought of their own
- The average person checks their phone 96 times per day — once every 10 minutes
- 71% of people sleep with their phone within arm's reach
- After a phone interruption, it takes an average of 23 minutes to fully regain focus
- The average person spends 37 days per year on social media
- 67% of people check their phone even when it hasn't buzzed or rung

Procrastination & habits:
- 88% of workers procrastinate at least one hour every single day
- Only 8% of people achieve their New Year's goals — not because they lack desire, but because they never changed the environment
- It takes an average of 66 days to build a real habit — not 21 like everyone says
- 92% of people who set goals in January abandon them by February 15th

Loneliness & motivation:
- 61% of adults report feeling lonely on a regular basis — even those surrounded by people
- 54% of people say no one in their life truly knows them well
- People who feel a sense of purpose wake up differently — studies show they have 15% lower cortisol levels in the morning

HOW TO USE THEM:
- Drop them mid-sentence like they're obvious: "80% of people check their phone before they've had a single thought of their own. You are probably one of them."
- Use the number to reframe: "92% fail their goals by February. Not because they're lazy. Because they never changed what happens at 7am."
- Contrast with the viewer: "61% of adults feel lonely regularly. Most of them are surrounded by people."
- Never cite a source awkwardly — state it as known fact, then pivot to the emotional truth it reveals

WRITING TECHNIQUES (mix freely):
- Percentage-based observation that reframes a common feeling
- Counter-intuitive truths: "The problem is never laziness. It's that your brain learned that trying leads to disappointment."
- Pattern observations: "People who feel stuck don't lack motivation. They lack proof that moving forward is safe."
- Micro-story with precise emotional detail: "You made a plan. You felt good about it. Three days later you were back to the same routine. Not because you're weak. Because nothing in your environment changed."

TARGET EMOTIONS:
- "How does this person know exactly what I'm going through"
- "I've never heard this described so accurately"
- "This is uncomfortable because it's true"

CAPTION STRUCTURE (all in English):
Line 1: A sharp, specific observation or stat that stops them cold
Lines 2-5: 3-4 precise behavioral/emotional patterns they recognize in themselves
Line 6: Reframe — they're not broken, this is a documented pattern
Line 7: Tease the shift with a specific counter-intuitive insight
Lines 8-9: Hint at the solution without revealing it
Line 10: Soft CTA ("Description has everything if you're ready.")
Line 11: 15 relevant hashtags

Write in English. Be precise, confident, and specific. Avoid generic phrases like "many people" — say exactly what happens, when, and how it feels."""


def generate_script(
    topic: str,
    format: str = "tutorial",
    platform: Platform = Platform.INSTAGRAM,
    target_duration: int = 45,
    content_gaps: list[str] | None = None,
) -> ContentPiece:
    """Genera un guión completo y lo guarda en la DB."""

    hook_letter = random.choice(list(HOOK_FORMULAS.keys()))
    hook_formula = HOOK_FORMULAS[hook_letter]

    gaps_context = ""
    if content_gaps:
        gaps_context = "\nCompetitor content gaps to exploit:\n" + "\n".join(
            f"- {g}" for g in content_gaps
        )

    prompt = f"""Write a viral pain-point video script about: "{topic}"
Hook type: {hook_letter} — {hook_formula}
{gaps_context}

Rules: English only. Short punchy sentences. Confident and specific like a researcher stating facts. No fluff.

Respond ONLY with this JSON (no extra text):
{{"title":"5-word punchy title in CAPS","hook":"ONE sentence max 12 words — confident, specific, stops them cold","overlay":"3-4 short sentences. Mix one real statistic with an emotional micro-story. State everything like an undeniable truth. Each sentence max 12 words. Example: '80% of people check their phone before a single thought of their own. Then wonder why the day feels gone. You are not lazy. You are just starting the day already behind.'","body":[{{"text":"ultra-specific scenario they recognize","duration_hint":10}},{{"text":"precise pattern observation stated with confidence","duration_hint":10}},{{"text":"counter-intuitive reframe that opens a door","duration_hint":8}}],"cta":"short soft CTA","hashtags":["#motivation","#mindset","#success"]}}"""

    log.info("Generando guión para: '%s' (hook %s)", topic, hook_letter)
    data = None
    for attempt in range(3):
        try:
            data = llm.json_generate(prompt, system=SCRIPT_SYSTEM)
            if data.get("title") and data.get("hook"):
                break
        except Exception as e:
            log.warning("Intento %d fallido al generar guión: %s", attempt + 1, e)
            data = None
    if not data:
        raise RuntimeError("El LLM no pudo generar un guión válido después de 3 intentos")

    body_segments = data.get("body", [])
    if isinstance(body_segments, list):
        body_text = "\n\n".join(
            seg["text"] if isinstance(seg, dict) else str(seg)
            for seg in body_segments
        )
    else:
        body_text = ""

    def _str(val, fallback=""):
        if isinstance(val, list):
            return " ".join(item.get("text", str(item)) if isinstance(item, dict) else str(item) for item in val)
        return str(val) if val else fallback

    cta = _str(data.get("cta") or data.get("CTA"), "Check the description if you're ready.")
    hook = _str(data.get("hook") or data.get("title"), "")
    title = _str(data.get("title"), hook[:50])
    full_script = f"{hook}\n\n{body_text}\n\n{cta}"

    raw_tags = data.get("hashtags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []
    # Serialize manually — Python 3.14 sqlite3 doesn't accept raw lists via JSON column
    hashtags_json = json.dumps(raw_tags)

    # Use the short overlay sentence for the video text; fall back to hook
    # Guard: LLM sometimes returns a list of dicts in overlay instead of a string
    overlay_raw = data.get("overlay") or hook
    if isinstance(overlay_raw, list):
        overlay_text = " ".join(
            item.get("text", str(item)) if isinstance(item, dict) else str(item)
            for item in overlay_raw
        )
    else:
        overlay_text = str(overlay_raw)

    with get_session() as db:
        piece = ContentPiece(
            title=title,
            script=full_script,
            hook=overlay_text,
            cta=cta,
            niche="pain-point / course selling",
            format=format,
            target_platform=platform,
            status=ContentStatus.DRAFT,
            hashtags=hashtags_json,
        )
        db.add(piece)
        db.commit()
        db.refresh(piece)
        db.expunge(piece)
        log.info("Guión creado: ID=%d '%s'", piece.id, piece.title)
        return piece


def generate_batch(topics: list[str], platform: Platform = Platform.INSTAGRAM) -> list[ContentPiece]:
    pieces = []
    for topic in topics:
        try:
            p = generate_script(topic, platform=platform)
            pieces.append(p)
        except Exception as e:
            log.error("Error generando guión para '%s': %s", topic, e)
    return pieces


def suggest_topics(niche: str, count: int = 10) -> list[str]:
    """Sugiere temas de pain-point para vender cursos de transformación."""
    prompt = (
        f'Suggest exactly {count} pain-point video topics for selling a transformation/online course. '
        f'Each topic should trigger emotions like "I am stuck", "I am wasting my life", or "I need to change". '
        f'Niche context: "{niche}". '
        f'Respond ONLY with valid JSON: {{"topics": ["topic 1", "topic 2", ..., "topic {count}"]}}'
    )
    for attempt in range(3):
        try:
            result = llm.json_generate(
                prompt,
                system="You are a viral content strategist. Respond ONLY with valid JSON, no extra text.",
            )
            topics = result.get("topics", [])
            if topics:
                log.info("Temas sugeridos: %d (intento %d)", len(topics), attempt + 1)
                return topics
        except Exception as e:
            log.warning("Intento %d fallido en suggest_topics: %s", attempt + 1, e)
    log.error("suggest_topics falló después de 3 intentos")
    return []
