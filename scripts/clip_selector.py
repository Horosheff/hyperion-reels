"""
Advanced Clip Selection Algorithm
Based on research from Opus Clip, Vidyo.ai, and viral video science.

Key improvements:
1. Sentence Boundary Detection - clips start/end at natural breaks
2. Hook Quality Analysis - first 3 seconds scoring
3. Semantic Coherence - complete micro-stories
4. Virality Scoring - emotion, duration, hook strength
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

@dataclass
class ClipCandidate:
    """A potential clip with scoring metadata."""
    start: float
    end: float
    text: str = ""
    words: list[dict] = field(default_factory=list)
    
    # Scores (0-100)
    hook_score: float = 0
    coherence_score: float = 0
    emotion_score: float = 0
    duration_score: float = 0
    final_score: float = 0
    
    # Metadata
    hook_triggers: list[str] = field(default_factory=list)
    emotion: str = "neutral"
    sentence_count: int = 0
    
    @property
    def duration(self) -> float:
        return self.end - self.start


# === 2026 VIRAL HOOK PATTERNS ===
# Based on 2026 research: first 3 seconds determine 65-84% of retention
# Rewatches provide 84% greater algorithmic boost than comments
# Pattern interrupts, curiosity gaps, and value promises drive 80%+ retention
# Raw authenticity beats overproduction

HOOK_PATTERNS = {
    # CRITICAL: Pattern interrupts (weight: 3x) - Stop the scroll
    "pattern_interrupt": [
        r"^(stop|wait|hold on|don't scroll|не верьте|стоп|погодите|стойте)",
        r"^(nobody is talking about|все молчат|никто не говорит об этом|myth)",
        r"^(the truth about|правда про|реальность которую|what they don't tell)",
        r"^(what if|а что если|представьте|imagine|picture this|imagine you)",
        r"^(hot take|unpopular opinion|controversial but|буду честен|откровенно)",
    ],
    
    # Curiosity gap drivers (weight: 2.5x) - Must open to resolve
    "curiosity_gap": [
        r"(the reason why|причина почему|вот почему|here's why)",
        r"(here's what|вот что|вот в чем|the real reason|real reason)",
        r"(most people don't know|мало кто знает|не многие знают|secret)",
        r"(i finally found|я наконец нашел|нашел способ|it took me years)",
        r"(the secret to|секрет|ключ к|формула|key to|secret formula)",
        r"(unlock|раскрываю|открываю|вскрываю|reveal|exposing|uncovering)",
        r"(what happens when|что будет если|что произойдет|this happens when)",
    ],
    
    # Value promise (weight: 2x) - Edutainment dominates 2026
    "value_promise": [
        r"(learn how|learn to|научишься|научитесь|будешь знать|by the end)",
        r"(i'm going to show you|покажу как|объясню как|смотри как|let me show)",
        r"(by the end of this|к концу|к окончанию|за \d+ минут|in \d+ minutes)",
        r"(step[- ]by[- ]step|по шагам|пошагово|план действий|roadmap|blueprint)",
        r"(save you|экономит|сэкономит|избавит|решит проблему|solves|fixes|saving)",
        r"(will change|изменит|трансформирует|перевернет|change your|change how)",
        r"(how to|как сделать|как стать|how i|how we|как я|tutorial|guide)",
    ],
    
    # Direct questions (weight: 1.5x) - Engagement drivers
    "question": [
        r"\?",
        r"^(what|why|how|when|where|who|did you|have you|can you|would you)",
        r"^(что|почему|как|когда|где|кто|знаете ли|а вы|зачем|откуда)",
        r"^(правда ли|неужели|разве|может ли|как думаете|you ever wondered)",
        r"^(do you|are you|would you|ты|вы|вам|как вы|как ты|are you struggling)",
        r"^(have you ever|did you know|когда-нибудь|знали ли вы)",
    ],
    
    # Urgency/FOMO (weight: 1.5x) - Time-sensitive action
    "urgency": [
        r"(right now|immediately|today|urgent|breaking|must see|before you)",
        r"(сейчас|немедленно|сегодня|срочно|важно|обязательно|need to know)",
        r"(don't miss|only today|last chance|before it's gone|пока не)",
        r"(running out|заканчивается|успей|пока есть|последний шанс|limited time)",
        r"(trending|тренд|вирусно|взрывает|набирает|going viral|blowing up|trending now)",
        r"(before it's too late|пока не поздно|before they|before the|next 24 hours)",
    ],
    
    # Numbers/lists (weight: 1.2x) - Structured value
    "number": [
        r"\b\d+\s*(ways|tips|secrets|reasons|things|steps|mistakes|rules|hacks|ideas)",
        r"\b\d+\s*(способов|советов|причин|вещей|шагов|ошибок|правил|лайфхаков)",
        r"^(#\d+|number \d+|номер \d+|пункт \d+|вот \d+|top \d+|best \d+)\b",
        r"\b(первый|второй|третий|главный|основной|ключевой|number one|first thing)\b",
    ],
    
    # Emotional triggers (weight: 1.8x) - High shareability
    "emotion_peak": [
        r"(amazing|incredible|insane|mind-blowing|unbelievable|shocking|crazy)",
        r"(офигенно|невероятно|безумно|потрясающе|шокирует|взрыв мозга|blow your mind)",
        r"(this is crazy|это безумие|это невозможно|не может быть|can't believe)",
        r"(i can't believe|не могу поверить|в шоке|в восторге|mind blown|literally)",
        r"(you won't believe|не поверишь|не представляешь|не догадаешься|can't make this)",
        r"(insane results|crazy results|wow|omg|oh my|нахрен|охуеть|ахуеть|пиздец)",
    ],
    
    # Authenticity markers (weight: 1.3x) - 2026: raw beats polished
    "authenticity": [
        r"(honestly|to be honest|if i'm being honest|честно|если честно|по правде)",
        r"(real talk|let's be real|давай по-честному|откровенно|по существу|no cap)",
        r"(i made a mistake|я ошибся|провал|не сработало|не получилось|my failure|i failed)",
        r"(behind the scenes|изнутри|из-за кулис|не рассказывают|what i learned|lesson learned)",
        r"(i'm not supposed to share|not sharing this anywhere else|they don't want)",
    ],
    
    # Story/controversy (weight: 1.5x) - Narrative tension
    "story_conflict": [
        r"(what happened next|что было дальше|итог|результат|что из этого вышло|plot twist)",
        r"(i was wrong|я был не прав|ошибался|как я ошибся|unpopular opinion)",
        r"(here's the problem|вот проблема|вот в чем дело|the catch is|here's the issue)",
        r"(plot twist|twist|поворот|неожиданность|внезапно|suddenly|and then|then suddenly)",
        r"(story time|story about|true story|история о|real story|happened to me)",
    ],
    
    # Completion drivers (weight: 1.0x) - Keep watching signals
    "completion_driver": [
        r"(but first|но сначала|before that|перед этим|смотри сюрприз|but before)",
        r"(wait until|дождитесь|не переключайтесь|you won't believe what happens|wait for it)",
        r"(the best part|лучшее сейчас|сейчас будет|here comes the|coming up|next is)",
        r"(here's the kicker|вот загвоздка|фишка в том|the thing is|kicker is|the real kicker)",
        r"(and that's not even|и это еще не все|that's just the beginning|just the start)",
    ],
    
    # Direct address (weight: 1.3x) - Personal connection
    "direct_address": [
        r"\b(you|your|you're|you've|i'm telling you|you need|you want|you can)\b",
        r"\b(ты|вы|твой|ваш|тебе|вам|смотри|послушай|смотрите|слушайте)\b",
        r"(друзья|ребята|народ|братья|guys|everyone|folks|let me tell you something)",
        r"(if you're|если ты|если вы|who wants|кто хочет|are you tired of)",
    ],
}

# Per-category weights (opening ~3s); body matches use half base in analyze_hook_quality
HOOK_PATTERN_WEIGHTS: dict[str, float] = {
    "pattern_interrupt": 3.0,
    "curiosity_gap": 2.5,
    "value_promise": 2.0,
    "emotion_peak": 1.8,
    "question": 1.5,
    "urgency": 1.5,
    "story_conflict": 1.5,
    "authenticity": 1.3,
    "direct_address": 1.3,
    "number": 1.2,
    "completion_driver": 1.0,
}

# Emotion keywords for detection
EMOTION_KEYWORDS = {
    "joy": [
        "happy", "excited", "love", "amazing", "awesome", "great", "fantastic",
        "счастлив", "рад", "люблю", "круто", "супер", "отлично", "класс",
        "haha", "lol", "😂", "🤣", "❤️", "🔥",
    ],
    "surprise": [
        "wow", "omg", "unbelievable", "shocking", "crazy", "insane", "what",
        "вау", "офигеть", "невероятно", "шок", "безумие", "что",
        "😱", "🤯", "😮",
    ],
    "anger": [
        "angry", "hate", "stupid", "terrible", "worst", "annoying", "frustrated",
        "злой", "ненавижу", "тупой", "ужасно", "бесит", "достало",
        "😡", "🤬",
    ],
    "fear": [
        "scared", "afraid", "terrifying", "horror", "creepy", "dangerous",
        "страшно", "боюсь", "ужас", "жуть", "опасно",
        "😨", "😰",
    ],
    "awe": [
        "beautiful", "stunning", "breathtaking", "magnificent", "epic",
        "красиво", "потрясающе", "величественно", "эпично",
        "🤩", "✨",
    ],
    "humor": [
        "funny", "hilarious", "joke", "comedy", "laugh", "lmao",
        "смешно", "ржака", "шутка", "прикол", "ахах",
        "😂", "🤣", "😆",
    ],
}


WEBINAR_VALUE_PATTERNS: dict[str, list[str]] = {
    "explanation": [
        r"(вот почему|причина|суть в том|дело в том|here is why|here's why|the reason)",
        r"(объясню|разберем|давайте разберем|let me explain|break this down)",
    ],
    "demo": [
        r"(смотри|смотрите|посмотрите|watch this|look at this|let me show)",
        r"(пример|например|example|case study|кейс|демо|демонстрац)",
    ],
    "result": [
        r"(результат|итог|вывод|получается|result|outcome|conclusion)",
        r"(до и после|before and after|before/after|что изменилось)",
    ],
    "mistake": [
        r"(ошибка|ошибся|не делайте|mistake|wrong|failed|failure|what not to do)",
        r"(проблема|ловушка|подводный камень|problem|catch|trap)",
    ],
    "contrast": [
        r"(но на самом деле|а теперь|вместо этого|but actually|instead|however)",
        r"(раньше.*теперь|было.*стало|used to.*now)",
    ],
}


def analyze_hook_quality(text: str, first_3_sec_text: str = None) -> dict:
    """
    Analyze hook quality of clip's first ~3 seconds (2026-weighted patterns).

    Opening text gets full weight; same category in full clip body adds half
    (only if not already matched in the opening).
    """
    analysis_text = (first_3_sec_text or text[:150]).lower()
    full_text_lower = (text or "").lower()
    base_points = 12.0

    score = 0.0
    triggers: list[str] = []

    for pattern_name, patterns in HOOK_PATTERNS.items():
        weight = HOOK_PATTERN_WEIGHTS.get(pattern_name, 1.0)
        found_opening = False
        for pattern in patterns:
            if re.search(pattern, analysis_text, re.I):
                score += base_points * weight
                triggers.append(pattern_name)
                found_opening = True
                break
        if not found_opening:
            for pattern in patterns:
                if re.search(pattern, full_text_lower, re.I):
                    score += (base_points * 0.5) * weight
                    triggers.append(pattern_name)
                    break

    # Bonus for short, punchy first sentence
    first_sentence = analysis_text.split(".")[0] if "." in analysis_text else analysis_text
    word_count = len(first_sentence.split())
    if 3 <= word_count <= 10:
        score += 10
        triggers.append("punchy_opening")
    elif word_count < 3:
        score -= 5
    elif word_count > 20:
        score -= 8

    weak_starts = [
        "um", "uh", "so basically", "actually", "well", "okay",
        "ну", "эм", "типа", "короче", "ну типа", "итак", "значит так",
    ]
    if any(analysis_text.startswith(w) for w in weak_starts):
        score -= 18
        triggers.append("weak_start_penalty")

    if first_sentence and first_sentence[0] in ("!", "¿", "¡"):
        score += 8
        triggers.append("attention_punctuation")

    payoff_tail = full_text_lower[-120:] if full_text_lower else ""
    for indicator in (
        "результат", "итог", "вывод", "финал",
        "result", "outcome", "conclusion", "here's what happened",
    ):
        if indicator in payoff_tail:
            score += 10
            triggers.append("promises_payoff")
            break

    final = max(0, min(100, int(round(score))))
    return {
        "score": final,
        "triggers": list(set(triggers)),
        "passes_threshold": final >= 40,
    }


def analyze_webinar_value(text: str) -> dict:
    """Score webinar-specific standalone value: explanation, demo, mistake, result."""
    text_lower = (text or "").lower()
    score = 0
    triggers: list[str] = []
    for name, patterns in WEBINAR_VALUE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.I):
                score += 14
                triggers.append(f"webinar_{name}")
                break
    if len(text_lower.split()) >= 60:
        score += 8
        triggers.append("webinar_context")
    return {"score": min(100, score), "triggers": triggers}


def detect_emotion(text: str) -> tuple[str, float]:
    """
    Detect primary emotion in text.
    
    Returns:
        (emotion_name, confidence_score)
    """
    text_lower = text.lower()
    
    emotion_scores = {}
    for emotion, keywords in EMOTION_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        emotion_scores[emotion] = count
    
    if not any(emotion_scores.values()):
        return "neutral", 0.3
    
    best_emotion = max(emotion_scores, key=emotion_scores.get)
    confidence = min(1.0, emotion_scores[best_emotion] / 5)
    
    return best_emotion, confidence


def get_emotion_virality_score(emotion: str) -> float:
    """Get virality score based on emotion type."""
    scores = {
        "awe": 100,
        "joy": 90,
        "surprise": 85,
        "humor": 80,
        "anger": 60,
        "fear": 50,
        "neutral": 30,
        "sadness": 20,
    }
    return scores.get(emotion, 30)


def get_duration_score(duration: float, min_sec: float = 30, max_sec: float = 60) -> float:
    """
    Score clip duration based on target range.
    Any duration inside the requested range is valid. Do not lock selection to
    the midpoint: semantic completion should decide whether a clip is 30, 45,
    or 60 seconds.
    
    IMPORTANT: Clips BELOW min_sec get ZERO score to filter them out.
    """
    # Clips shorter than minimum get ZERO score - hard filter
    if duration < min_sec:
        return 0  # REJECT - too short
    
    # Clips longer than maximum are penalized
    if duration > max_sec:
        return 20  # Too long
    
    # Within range: only a small edge penalty. The old midpoint-heavy score
    # caused 30-60s clips to collapse into near-45s windows.
    target = (min_sec + max_sec) / 2
    distance_from_target = abs(duration - target)
    range_half = (max_sec - min_sec) / 2

    score = 96 - (distance_from_target / range_half) * 10
    return max(84, score)  # Minimum 84 for valid in-range clips


def _duration_candidates(min_duration: float, max_duration: float) -> list[float]:
    """Representative durations across the whole requested range."""
    if max_duration <= min_duration:
        return [float(min_duration)]
    span = max_duration - min_duration
    values = [
        min_duration,
        min_duration + span * 0.25,
        min_duration + span * 0.5,
        min_duration + span * 0.75,
        max_duration,
    ]
    return sorted({round(float(v), 2) for v in values})


def _looks_incomplete_ending(text: str) -> bool:
    """Detect tails that open the next thought instead of closing this one."""
    clean = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not clean:
        return True
    tail_sentences = [s.strip(" \t\r\n.,!?…:;—-") for s in re.split(r"(?<=[.!?…])\s+", clean) if s.strip()]
    tail = tail_sentences[-1] if tail_sentences else clean[-120:]
    dangling_exact = {
        "первое",
        "второе",
        "третье",
        "следующее",
        "дальше",
        "итак",
        "так",
        "сейчас",
        "сейчас объясню",
        "сейчас покажу",
        "я объясню",
        "объясню",
        "начнем",
        "продолжим",
        "one",
        "two",
        "next",
        "first",
        "second",
        "let me explain",
    }
    if tail in dangling_exact:
        return True
    dangling_prefixes = (
        "первое ",
        "второе ",
        "третье ",
        "следующий пункт",
        "следующая ",
        "сейчас объясню",
        "сейчас покажу",
        "давайте посмотрим",
        "я объясню",
        "let me explain",
        "here is why",
        "next ",
    )
    return tail.startswith(dangling_prefixes)


def find_sentence_boundaries(words: list[dict], text: str = None) -> list[dict]:
    """
    Find sentence boundaries in transcript.
    Uses punctuation and pause detection.
    
    Returns list of boundaries with word_idx and time.
    """
    if not words:
        return []
    
    boundaries = []
    sentence_end_chars = {'.', '!', '?', '。', '！', '？'}
    
    for i, word in enumerate(words):
        word_text = word.get("word", "").strip()
        if not word_text:
            continue
        
        # Check for sentence-ending punctuation
        if word_text[-1] in sentence_end_chars:
            boundaries.append({
                "word_idx": i,
                "time": word.get("end", 0),
                "type": "sentence_end",
            })
        
        # Check for long pause (gap > 0.8s to next word)
        if i < len(words) - 1:
            gap = words[i + 1].get("start", 0) - word.get("end", 0)
            if gap > 0.8:
                boundaries.append({
                    "word_idx": i,
                    "time": word.get("end", 0),
                    "type": "pause",
                })
    
    return boundaries


def calculate_coherence_simple(text: str) -> float:
    """
    Simple coherence check without external models.
    Checks if clip has intro-body-conclusion structure.
    """
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if len(sentences) < 2:
        return 0.5  # Single sentence - uncertain
    
    # Check for incomplete ending (ends with conjunction, list opener, etc.)
    last_sentence = sentences[-1].lower()
    incomplete_endings = ["and", "but", "so", "because", "или", "и", "но", "потому что"]
    if any(last_sentence.endswith(w) for w in incomplete_endings):
        return 0.3  # Incomplete thought
    if _looks_incomplete_ending(text):
        return 0.25  # Starts the next thought/list item instead of closing
    
    # Check for proper structure
    first_sentence = sentences[0].lower()
    
    # Story arc indicators
    has_intro = any(p in first_sentence for p in ["so", "today", "let me", "i'm going", "сегодня", "давай", "расскажу"])
    has_conclusion = any(p in last_sentence for p in ["that's", "so yeah", "remember", "так что", "вот так", "помни"])
    
    if has_intro and has_conclusion:
        return 1.0  # Complete story arc
    elif has_intro or has_conclusion:
        return 0.7  # Partial structure
    
    # Check for topic consistency (simple word overlap)
    first_words = set(sentences[0].lower().split())
    last_words = set(sentences[-1].lower().split())
    overlap = len(first_words & last_words) / max(len(first_words), 1)
    
    return 0.5 + overlap * 0.3


def select_best_clips(
    segments: list[dict],
    scenes: list[tuple[float, float]],
    clip_count: int = 3,
    min_duration: float = 15,
    max_duration: float = 60,
    logger: callable = None,
) -> list[ClipCandidate]:
    """
    Advanced clip selection using hook analysis and semantic coherence.
    
    Args:
        segments: List of transcript segments with 'start', 'end', 'text', '_words'
        scenes: List of (start, end) tuples from scene detection
        clip_count: Number of clips to select
        min_duration: Minimum clip duration in seconds
        max_duration: Maximum clip duration in seconds
        logger: Optional logging function
    
    Returns:
        List of ClipCandidate objects sorted by score
    """
    def log(msg):
        if logger:
            logger(msg)
    
    if not segments:
        log("No segments provided")
        return []
    
    # Extract all words if available
    all_words = []
    for seg in segments:
        if "_words" in seg:
            all_words = seg["_words"]
            break
    
    # Build full text with timing
    full_text = " ".join(seg.get("text", "") for seg in segments)
    video_duration = segments[-1].get("end", 0)
    
    log(f"Analyzing {len(segments)} segments, {len(all_words)} words, {video_duration:.0f}s video")
    
    # Find sentence boundaries
    boundaries = find_sentence_boundaries(all_words, full_text)
    log(f"Found {len(boundaries)} sentence boundaries")
    
    # Generate candidate clips
    candidates: list[ClipCandidate] = []
    
    # Strategy 1: Scene-based candidates
    if scenes:
        for start, end in scenes:
            # Skip very short or very long scenes
            duration = end - start
            if duration < min_duration:  # STRICT minimum - no 0.8 multiplier!
                continue
            if duration > max_duration:
                end = start + max_duration
            
            # Snap to sentence boundaries if possible
            start = _snap_to_boundary(start, boundaries, direction="after")
            end = _snap_to_boundary(end, boundaries, direction="before")
            
            # STRICT: must be at least min_duration after snapping
            if end - start >= min_duration:
                clip_text = _extract_text_for_range(segments, start, end)
                clip_words = _extract_words_for_range(all_words, start, end)
                
                candidate = ClipCandidate(
                    start=start,
                    end=end,
                    text=clip_text,
                    words=clip_words,
                )
                _score_candidate(candidate, min_duration, max_duration)
                candidates.append(candidate)
    
    # Strategy 2: Sliding window through ENTIRE video (better coverage)
    # This ensures we find high-hook moments even without scene detection
    log(f"Scanning video with sliding window for high-hook moments...")
    
    # Calculate step size: scan every 10 seconds for long videos, 5 for short
    step_size = 10 if video_duration > 600 else 5
    duration_candidates = _duration_candidates(min_duration, max_duration)
    
    window_candidates = 0
    for start in range(0, int(video_duration - min_duration), step_size):
        for target_duration in duration_candidates:
            end = start + target_duration
            if end > video_duration:
                end = video_duration

            if end - start < min_duration:
                continue

            # Snap to boundaries
            start_snapped = _snap_to_boundary(float(start), boundaries, direction="after")
            end_snapped = _snap_to_boundary(float(end), boundaries, direction="before")

            if end_snapped - start_snapped >= min_duration:
                clip_text = _extract_text_for_range(segments, start_snapped, end_snapped)

                # Quick pre-filter: only add if text has potential hooks
                hook_preview = analyze_hook_quality(clip_text[:200], clip_text[:100])
                if hook_preview["score"] >= 20:  # Only consider clips with some hook potential
                    clip_words = _extract_words_for_range(all_words, start_snapped, end_snapped)

                    candidate = ClipCandidate(
                        start=start_snapped,
                        end=end_snapped,
                        text=clip_text,
                        words=clip_words,
                    )
                    _score_candidate(candidate, min_duration, max_duration)
                    candidates.append(candidate)
                    window_candidates += 1
    
    log(f"Sliding window added {window_candidates} candidates")

    if len(candidates) < clip_count:
        backfill_candidates = 0
        log("Backfilling with transcript-density windows")
        for start in range(0, int(video_duration - min_duration), max(5, step_size)):
            for target_duration in duration_candidates:
                end = min(float(start) + target_duration, video_duration)
                if end - start < min_duration:
                    continue
                clip_text = _extract_text_for_range(segments, float(start), end)
                if len(clip_text.split()) < 20:
                    continue
                clip_words = _extract_words_for_range(all_words, float(start), end)
                candidate = ClipCandidate(
                    start=float(start),
                    end=end,
                    text=clip_text,
                    words=clip_words,
                )
                _score_candidate(candidate, min_duration, max_duration)
                candidates.append(candidate)
                backfill_candidates += 1
        log(f"Density backfill added {backfill_candidates} candidates")
    
    log(f"Generated {len(candidates)} candidate clips")
    
    # Remove duplicates (similar start times)
    candidates = _remove_duplicates(candidates)
    log(f"After dedup: {len(candidates)} candidates")
    
    # CRITICAL: Filter out clips shorter than min_duration
    before_filter = len(candidates)
    candidates = [c for c in candidates if c.duration >= min_duration]
    log(f"After duration filter (>={min_duration}s): {len(candidates)} candidates (removed {before_filter - len(candidates)})")
    
    # Sort by final score
    candidates.sort(key=lambda c: c.final_score, reverse=True)
    
    # Select top N non-overlapping clips
    selected: list[ClipCandidate] = []
    for candidate in candidates:
        # Double-check duration (should already be filtered)
        if candidate.duration < min_duration:
            log(f"Skipping short clip {candidate.start:.1f}-{candidate.end:.1f}s ({candidate.duration:.1f}s < {min_duration}s)")
            continue
        
        # Check overlap with already selected
        overlaps = False
        for sel in selected:
            if candidate.start < sel.end and candidate.end > sel.start:
                overlaps = True
                break
        
        if not overlaps:
            selected.append(candidate)
            log(f"Selected clip {candidate.start:.1f}-{candidate.end:.1f}s ({candidate.duration:.1f}s) "
                f"(score={candidate.final_score:.0f}, hook={candidate.hook_score:.0f}, "
                f"emotion={candidate.emotion}, triggers={candidate.hook_triggers})")
            
            if len(selected) >= clip_count:
                break
    
    return selected


def _score_candidate(candidate: ClipCandidate, min_duration: float = 30, max_duration: float = 60) -> None:
    """Calculate all scores for a clip candidate."""
    # Hook analysis: use real first ~3 seconds when word timestamps are available.
    first_3_sec_text = _extract_opening_text(candidate)
    hook_result = analyze_hook_quality(candidate.text, first_3_sec_text)
    candidate.hook_score = hook_result["score"]
    candidate.hook_triggers = hook_result["triggers"]

    webinar_result = analyze_webinar_value(candidate.text)
    candidate.hook_score = min(100, candidate.hook_score + webinar_result["score"] * 0.35)
    candidate.hook_triggers.extend(webinar_result["triggers"])
    
    # Emotion detection
    emotion, confidence = detect_emotion(candidate.text)
    candidate.emotion = emotion
    candidate.emotion_score = get_emotion_virality_score(emotion) * confidence
    
    # Duration score - pass min/max for proper scoring
    candidate.duration_score = get_duration_score(candidate.duration, min_duration, max_duration)
    
    # Coherence score
    candidate.coherence_score = calculate_coherence_simple(candidate.text) * 100
    
    # Final weighted score
    # If duration is invalid (score=0), the clip gets heavily penalized
    candidate.final_score = (
        candidate.hook_score * 0.42 +        # Hook + webinar value are most important
        candidate.emotion_score * 0.18 +     # Emotion drives shares
        candidate.duration_score * 0.20 +    # Duration affects completion
        candidate.coherence_score * 0.20     # Story completeness
    )


def _extract_opening_text(candidate: ClipCandidate, seconds: float = 3.0) -> str:
    if candidate.words:
        cutoff = candidate.start + seconds
        opening_words = [
            str(w.get("word", "")).strip()
            for w in candidate.words
            if candidate.start <= float(w.get("start", 0)) < cutoff
        ]
        opening = " ".join(w for w in opening_words if w)
        if opening:
            return opening
    return candidate.text[:100] if candidate.text else ""


def _snap_to_boundary(
    time: float,
    boundaries: list[dict],
    direction: str = "after",
    max_shift: float = 3.0,
) -> float:
    """
    Snap time to nearest sentence boundary.
    
    Args:
        time: Original time
        direction: "after" (find boundary after time) or "before" (find boundary before time)
        max_shift: Maximum seconds to shift
    """
    if not boundaries:
        return time
    
    if direction == "after":
        # Find first boundary after time
        for b in boundaries:
            if b["time"] >= time and b["time"] - time <= max_shift:
                return b["time"]
    else:
        # Find last boundary before time
        for b in reversed(boundaries):
            if b["time"] <= time and time - b["time"] <= max_shift:
                return b["time"]
    
    return time


def _extract_text_for_range(segments: list[dict], start: float, end: float) -> str:
    """Extract text from segments within time range."""
    texts = []
    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        if seg_start >= start and seg_end <= end:
            texts.append(seg.get("text", ""))
        elif seg_start < end and seg_end > start:
            # Partial overlap
            texts.append(seg.get("text", ""))
    return " ".join(texts)


def _extract_words_for_range(words: list[dict], start: float, end: float) -> list[dict]:
    """Extract words within time range."""
    return [w for w in words if start <= w.get("start", 0) < end]


def _remove_duplicates(candidates: list[ClipCandidate], threshold: float = 5.0) -> list[ClipCandidate]:
    """Remove candidates with similar start times, keeping highest scoring."""
    if not candidates:
        return []
    
    # Sort by start time
    sorted_candidates = sorted(candidates, key=lambda c: c.start)
    
    unique = [sorted_candidates[0]]
    for c in sorted_candidates[1:]:
        # If start is too close to last unique, compare scores
        if c.start - unique[-1].start < threshold:
            if c.final_score > unique[-1].final_score:
                unique[-1] = c
        else:
            unique.append(c)
    
    return unique
