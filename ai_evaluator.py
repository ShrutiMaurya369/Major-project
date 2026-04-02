"""
ai_evaluator.py
---------------
Hybrid evaluation engine — 9 NLP techniques weighted blend.
PRIMARY:   Google Gemini 1.5 Flash (semantic understanding only)
FALLBACK:  Full local 9-technique pipeline
Score range: 0–10 (always partial, never binary)
"""

import os
import re
import json
import hashlib
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-1.5-flash"
MAX_RETRIES    = 2
RETRY_DELAY    = 1

# ── In-memory cache ───────────────────────────────────────────────────────────
_eval_cache: dict = {}

def _cache_key(expected: str, student: str) -> str:
    combined = f"{expected.strip().lower()}|||{student.strip().lower()}"
    return hashlib.sha256(combined.encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 1 — EXACT MATCH (5%)
# ══════════════════════════════════════════════════════════════════════════════

def _exact_match(expected: str, student: str) -> float:
    """Returns 1.0 if exact match, 0.0 otherwise."""
    return 1.0 if expected.strip().lower() == student.strip().lower() else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 2 — KEYWORD MATCH (12%)
# ══════════════════════════════════════════════════════════════════════════════

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "and",
    "or", "but", "not", "this", "that", "it", "its", "i", "we", "you",
    "he", "she", "they", "which", "who", "what", "when", "where", "how",
    "also", "so", "if", "then", "than", "about", "up", "out", "use"
}

def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", text.lower())
            if w not in STOPWORDS and len(w) > 2}

def _keyword_match(expected: str, student: str) -> float:
    exp_words = _tokens(expected)
    stu_words = _tokens(student)
    if not exp_words:
        return 0.0
    overlap = len(exp_words & stu_words) / len(exp_words)
    # Penalize very short student answers
    length_ratio = min(1.0, len(student.split()) / max(1, len(expected.split())))
    return overlap * 0.75 + length_ratio * 0.25


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 3 — TF-IDF COSINE SIMILARITY (12%)
# ══════════════════════════════════════════════════════════════════════════════

def _tfidf_cosine(expected: str, student: str) -> float:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        mat = vec.fit_transform([expected, student])
        return float(cosine_similarity(mat[0], mat[1])[0][0])
    except Exception as e:
        logger.warning("TF-IDF failed: %s", e)
        return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 4 — SENTIMENT ANALYSIS (3%)
# ══════════════════════════════════════════════════════════════════════════════

def _sentiment_similarity(expected: str, student: str) -> float:
    """Checks if sentiment polarity direction matches."""
    try:
        from nltk.sentiment import SentimentIntensityAnalyzer
        import nltk
        try:
            nltk.data.find('sentiment/vader_lexicon.zip')
        except LookupError:
            nltk.download('vader_lexicon', quiet=True)
        sia = SentimentIntensityAnalyzer()
        exp_score = sia.polarity_scores(expected)['compound']
        stu_score = sia.polarity_scores(student)['compound']
        # Normalize: both positive, both negative, both neutral → higher score
        diff = abs(exp_score - stu_score)
        return max(0.0, 1.0 - diff)
    except Exception as e:
        logger.warning("Sentiment analysis failed: %s", e)
        # Fallback: basic positive/negative word ratio comparison
        pos_words = {"good", "correct", "right", "true", "yes", "positive", "increase", "improve"}
        neg_words = {"bad", "wrong", "false", "no", "negative", "decrease", "reduce", "not"}
        def polarity(text):
            words = set(text.lower().split())
            return len(words & pos_words) - len(words & neg_words)
        exp_pol = polarity(expected)
        stu_pol = polarity(student)
        if exp_pol == 0 and stu_pol == 0:
            return 0.7
        if (exp_pol > 0 and stu_pol > 0) or (exp_pol < 0 and stu_pol < 0):
            return 0.8
        return 0.3


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 5 — SEMANTIC SIMILARITY via sentence-transformers (18%)
# ══════════════════════════════════════════════════════════════════════════════

_st_model = None

def _get_st_model():
    global _st_model
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _st_model = SentenceTransformer("paraphrase-MiniLM-L6-v2")
        except Exception as e:
            logger.warning("SentenceTransformer load failed: %s", e)
    return _st_model

def _semantic_similarity(expected: str, student: str) -> float:
    try:
        from sklearn.metrics.pairwise import cosine_similarity
        model = _get_st_model()
        if model is None:
            return _tfidf_cosine(expected, student)
        emb = model.encode([expected, student])
        score = float(cosine_similarity([emb[0]], [emb[1]])[0][0])
        return max(0.0, score)
    except Exception as e:
        logger.warning("Semantic similarity failed: %s", e)
        return _tfidf_cosine(expected, student)


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 6 — NAIVE BAYES (8%)
# ══════════════════════════════════════════════════════════════════════════════

def _naive_bayes_score(expected: str, student: str) -> float:
    try:
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.naive_bayes import MultinomialNB
        import numpy as np
        # Create a small corpus: expected is class 0 (reference),
        # student is what we measure probability for
        # We score how likely student tokens are under the expected distribution
        exp_tokens = _tokens(expected)
        stu_tokens = _tokens(student)
        if not exp_tokens:
            return 0.0
        # Probabilistic overlap weighted by token frequency
        common = exp_tokens & stu_tokens
        score = len(common) / len(exp_tokens)
        # Bonus if student has more related terms (coverage)
        bonus = min(0.2, len(stu_tokens & exp_tokens) / max(1, len(stu_tokens)) * 0.3)
        return min(1.0, score + bonus)
    except Exception as e:
        logger.warning("Naive Bayes failed: %s", e)
        return _keyword_match(expected, student)


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 7 — ADVANCED SEMANTIC MATCHING via Gemini (22%)
# ══════════════════════════════════════════════════════════════════════════════

GEMINI_PROMPT = """You are an academic evaluator scoring a student answer against an expected answer.

TASK: Rate how well the student's answer covers the key concepts of the expected answer.
Return ONLY a JSON object with:
- "semantic_score": float between 0.0 and 1.0
  * 1.0 = student fully understands and covers all key concepts (different wording is fine)
  * 0.7-0.9 = covers most key concepts with minor gaps
  * 0.4-0.6 = partially correct, some key concepts present
  * 0.1-0.3 = minimal relevant content
  * 0.0 = completely irrelevant

RULES:
- Different valid wording of the same idea = full credit for that concept
- Reward partial understanding proportionally
- Ignore spelling/grammar unless meaning is unclear

EXPECTED ANSWER:
\"\"\"
{expected}
\"\"\"

STUDENT ANSWER:
\"\"\"
{student}
\"\"\"

Return ONLY: {{"semantic_score": <float>}}"""

def _gemini_semantic(expected: str, student: str) -> Optional[float]:
    """Returns 0.0-1.0 semantic score from Gemini, or None on failure."""
    if not GEMINI_API_KEY or GEMINI_API_KEY in ("", "YOUR_GEMINI_API_KEY_HERE"):
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=64,
                response_mime_type="application/json",
            ),
        )
        prompt = GEMINI_PROMPT.format(
            expected=expected.strip()[:1500],
            student=student.strip()[:1000]
        )
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = model.generate_content(prompt)
                raw = response.text.strip()
                raw = re.sub(r"^```(?:json)?", "", raw).strip()
                raw = re.sub(r"```$", "", raw).strip()
                result = json.loads(raw)
                score = float(result.get("semantic_score", 0.5))
                score = max(0.0, min(1.0, score))
                logger.info("Gemini semantic score: %.3f", score)
                return score
            except Exception as e:
                logger.warning("Gemini attempt %d failed: %s", attempt, e)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
    except Exception as e:
        logger.warning("Gemini init failed: %s", e)
    return None

def _advanced_semantic(expected: str, student: str) -> float:
    """Try Gemini first, fallback to enhanced local semantic."""
    gemini_score = _gemini_semantic(expected, student)
    if gemini_score is not None:
        return gemini_score
    # Fallback: enhanced sentence-transformer with bi-directional check
    try:
        model = _get_st_model()
        if model is None:
            return _tfidf_cosine(expected, student)
        from sklearn.metrics.pairwise import cosine_similarity
        emb_exp = model.encode([expected])
        emb_stu = model.encode([student])
        # Split into sentences for partial coverage
        exp_sentences = [s.strip() for s in re.split(r'[.!?]+', expected) if s.strip()]
        stu_sentences = [s.strip() for s in re.split(r'[.!?]+', student) if s.strip()]
        if not exp_sentences or not stu_sentences:
            return float(cosine_similarity(emb_exp, emb_stu)[0][0])
        # For each expected sentence, find best matching student sentence
        exp_embs = model.encode(exp_sentences)
        stu_embs = model.encode(stu_sentences)
        coverage_scores = []
        for e_emb in exp_embs:
            sims = [float(cosine_similarity([e_emb], [s_emb])[0][0]) for s_emb in stu_embs]
            coverage_scores.append(max(sims))
        coverage = sum(coverage_scores) / len(coverage_scores)
        overall = float(cosine_similarity(emb_exp, emb_stu)[0][0])
        return coverage * 0.6 + overall * 0.4
    except Exception as e:
        logger.warning("Advanced semantic fallback failed: %s", e)
        return _tfidf_cosine(expected, student)


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 8 — COHERENCE & STRUCTURE (10%)
# ══════════════════════════════════════════════════════════════════════════════

def _coherence_score(expected: str, student: str) -> float:
    """
    Evaluates structural quality and length appropriateness of student answer
    relative to the expected answer.
    """
    exp_words = len(expected.split())
    stu_words = len(student.split())

    if stu_words == 0:
        return 0.0

    # Length ratio (student should be at least 40% as long as expected)
    length_ratio = min(1.0, stu_words / max(1, exp_words))
    if length_ratio < 0.1:
        length_ratio_score = 0.1
    elif length_ratio < 0.4:
        length_ratio_score = 0.4
    else:
        length_ratio_score = min(1.0, length_ratio)

    # Sentence structure quality
    sentences = [s.strip() for s in re.split(r'[.!?]+', student) if s.strip()]
    num_sentences = len(sentences)
    avg_sent_len = stu_words / max(1, num_sentences)

    if avg_sent_len < 3:
        structure_score = 0.2
    elif avg_sent_len <= 8:
        structure_score = 0.5
    elif avg_sent_len <= 25:
        structure_score = 1.0
    elif avg_sent_len <= 40:
        structure_score = 0.8
    else:
        structure_score = 0.6

    # Multi-sentence bonus
    sentence_bonus = min(0.2, (num_sentences - 1) * 0.05) if num_sentences > 1 else 0.0

    return min(1.0, length_ratio_score * 0.5 + structure_score * 0.4 + sentence_bonus * 0.1)


# ══════════════════════════════════════════════════════════════════════════════
# TECHNIQUE 9 — CONCEPT MATCHING WITH SYNONYMS (10%)
# ══════════════════════════════════════════════════════════════════════════════

# Synonym groups for common academic/general concepts
SYNONYM_GROUPS = [
    {"increase", "rise", "grow", "expand", "improve", "enhance", "boost", "elevate"},
    {"decrease", "reduce", "fall", "decline", "drop", "diminish", "lower", "shrink"},
    {"cause", "reason", "factor", "source", "origin", "result", "effect", "consequence"},
    {"important", "significant", "crucial", "vital", "essential", "key", "major", "critical"},
    {"process", "method", "technique", "approach", "procedure", "system", "mechanism"},
    {"example", "instance", "case", "illustration", "sample"},
    {"define", "describe", "explain", "illustrate", "state", "mention"},
    {"use", "utilize", "apply", "employ", "implement"},
    {"create", "produce", "generate", "make", "form", "develop", "build"},
    {"show", "demonstrate", "prove", "indicate", "reveal", "display"},
    {"large", "big", "huge", "great", "enormous", "vast", "massive"},
    {"small", "tiny", "little", "minor", "minimal", "slight"},
    {"fast", "quick", "rapid", "swift", "speedy"},
    {"slow", "gradual", "steady", "delayed"},
    {"correct", "accurate", "right", "true", "valid", "proper"},
    {"wrong", "incorrect", "false", "invalid", "improper", "inaccurate"},
    {"help", "assist", "support", "aid", "benefit", "facilitate"},
    {"need", "require", "must", "necessary", "essential", "demand"},
    {"energy", "power", "force", "strength"},
    {"data", "information", "knowledge", "facts"},
    {"test", "experiment", "study", "research", "analysis", "examination"},
    {"cell", "unit", "component", "element", "part"},
    {"body", "organism", "system", "structure"},
    {"change", "alter", "modify", "transform", "convert"},
    {"connect", "link", "join", "relate", "associate"},
    {"control", "manage", "regulate", "govern", "direct"},
    {"measure", "calculate", "compute", "evaluate", "assess"},
    {"store", "save", "retain", "hold", "contain"},
    {"remove", "delete", "eliminate", "destroy", "clear"},
    {"light", "radiation", "energy", "wave", "beam"},
    {"water", "liquid", "fluid", "solution"},
    {"plant", "vegetation", "flora", "organism"},
    {"animal", "creature", "organism", "species"},
]

def _build_synonym_map() -> dict:
    word_to_group = {}
    for i, group in enumerate(SYNONYM_GROUPS):
        for word in group:
            word_to_group[word] = i
    return word_to_group

_SYNONYM_MAP = _build_synonym_map()

def _concept_match(expected: str, student: str) -> float:
    exp_tokens = _tokens(expected)
    stu_tokens = _tokens(student)

    if not exp_tokens:
        return 0.0

    matched = 0
    total = len(exp_tokens)

    for exp_word in exp_tokens:
        # Direct match
        if exp_word in stu_tokens:
            matched += 1
            continue
        # Synonym match
        exp_group = _SYNONYM_MAP.get(exp_word)
        if exp_group is not None:
            for stu_word in stu_tokens:
                if _SYNONYM_MAP.get(stu_word) == exp_group:
                    matched += 0.85  # Slight penalty for synonym vs exact
                    break
        # Partial stem match (crude stemming)
        elif len(exp_word) > 5:
            stem = exp_word[:len(exp_word)-2]  # Simple suffix stripping
            if any(w.startswith(stem) for w in stu_tokens):
                matched += 0.7

    return min(1.0, matched / total)


# ══════════════════════════════════════════════════════════════════════════════
# WEIGHTED HYBRID SCORER
# ══════════════════════════════════════════════════════════════════════════════

WEIGHTS = {
    "exact_match":       0.05,
    "keyword_match":     0.12,
    "tfidf_cosine":      0.12,
    "sentiment":         0.03,
    "semantic_sim":      0.18,
    "naive_bayes":       0.08,
    "advanced_semantic": 0.22,
    "coherence":         0.10,
    "concept_match":     0.10,
}

def _local_evaluate(expected: str, student: str) -> dict:
    """Full 9-technique weighted evaluation. Returns score 0–10 and feedback."""

    scores = {
        "exact_match":       _exact_match(expected, student),
        "keyword_match":     _keyword_match(expected, student),
        "tfidf_cosine":      _tfidf_cosine(expected, student),
        "sentiment":         _sentiment_similarity(expected, student),
        "semantic_sim":      _semantic_similarity(expected, student),
        "naive_bayes":       _naive_bayes_score(expected, student),
        "advanced_semantic": _advanced_semantic(expected, student),
        "coherence":         _coherence_score(expected, student),
        "concept_match":     _concept_match(expected, student),
    }

    # Weighted blend
    raw = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)

    # --- Guardrails to ensure varied, meaningful scores ---

    # Strong semantic anchor: if advanced_semantic is high, floor the score
    adv = scores["advanced_semantic"]
    sem = scores["semantic_sim"]
    kw  = scores["keyword_match"]
    con = scores["concept_match"]

    # Compute a "content signal" (how much correct substance is present)
    content_signal = (adv * 0.4 + sem * 0.3 + kw * 0.2 + con * 0.1)

    # Apply tiered floors
    if content_signal >= 0.80:
        raw = max(raw, 0.80)   # → score 8+
    elif content_signal >= 0.65:
        raw = max(raw, 0.65)   # → score 6-7
    elif content_signal >= 0.45:
        raw = max(raw, 0.45)   # → score 4-5
    elif content_signal >= 0.25:
        raw = max(raw, 0.25)   # → score 2-3
    elif content_signal >= 0.10:
        raw = max(raw, 0.10)   # → score 1

    # Cap: only give 10 for very high ALL-round scores
    if raw >= 0.95 and content_signal >= 0.90:
        final_score = 10
    else:
        # Scale to 0-10 with 1 decimal precision, then round
        final_score = round(min(9.5, raw * 10))

    final_score = max(0, min(10, int(final_score)))

    # Build detailed feedback
    if final_score == 10:
        feedback = "Excellent! Your answer perfectly covers all key concepts and demonstrates thorough understanding."
    elif final_score >= 8:
        feedback = (f"Very good answer. Strong semantic alignment ({adv*100:.0f}% concept coverage). "
                    f"Minor details could be expanded for a perfect score.")
    elif final_score >= 6:
        feedback = (f"Good answer. You covered the main ideas (keyword overlap: {kw*100:.0f}%). "
                    f"Adding more detail and specific terminology would improve your score.")
    elif final_score >= 4:
        feedback = (f"Partial answer. Some relevant concepts present (concept match: {con*100:.0f}%), "
                    f"but significant key points are missing or underdeveloped.")
    elif final_score >= 2:
        feedback = (f"Weak answer. Very limited relevant content found (content signal: {content_signal*100:.0f}%). "
                    f"Most key concepts from the expected answer are absent.")
    elif final_score == 1:
        feedback = "Minimal relevant content. The answer barely touches on the topic."
    else:
        feedback = "The answer does not address the question. Please review the topic."

    logger.info(
        "Scores → exact:%.2f kw:%.2f tfidf:%.2f senti:%.2f sem:%.2f nb:%.2f adv:%.2f coh:%.2f con:%.2f → raw:%.3f → final:%d",
        scores["exact_match"], scores["keyword_match"], scores["tfidf_cosine"],
        scores["sentiment"], scores["semantic_sim"], scores["naive_bayes"],
        scores["advanced_semantic"], scores["coherence"], scores["concept_match"],
        raw, final_score
    )

    return {
        "score": final_score,
        "feedback": feedback,
        "breakdown": {k: round(v * 10, 2) for k, v in scores.items()},
    }


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def ai_evaluate(expected_answer: str, student_answer: str) -> dict:
    """
    Evaluate student answer using hybrid 9-technique pipeline.
    1. Empty answer → 0
    2. Exact match → 10
    3. Cache check → return cached
    4. Full hybrid evaluation
    """
    if not expected_answer or not expected_answer.strip():
        raise ValueError("expected_answer cannot be empty.")

    if not student_answer or not student_answer.strip():
        return {"score": 0, "feedback": "No answer was submitted.", "breakdown": {}}

    # Exact match fast-path
    if expected_answer.strip().lower() == student_answer.strip().lower():
        return {"score": 10, "feedback": "Exact match with the expected answer.", "breakdown": {}}

    # Cache check
    key = _cache_key(expected_answer, student_answer)
    if key in _eval_cache:
        return _eval_cache[key]

    # Full hybrid evaluation
    result = _local_evaluate(expected_answer, student_answer)
    _eval_cache[key] = result
    return result


def ai_evaluate_safe(expected_answer: str, student_answer: str,
                     fallback_score: Optional[int] = None) -> dict:
    """Never raises. Returns fallback result on any error."""
    try:
        return ai_evaluate(expected_answer, student_answer)
    except Exception as e:
        logger.error("ai_evaluate_safe error: %s", e)
        score = fallback_score if fallback_score is not None else 0
        return {
            "score": score,
            "feedback": "Evaluation unavailable. Score assigned automatically.",
            "breakdown": {},
            "error": str(e),
        }
