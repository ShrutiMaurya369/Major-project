"""
ai_evaluator.py
---------------
Drop-in AI evaluation module for Auto Checker.
Uses Google Gemini 1.5 Flash — free tier, fast, deterministic at temperature=0.

Place this file in the same directory as admin.py.
"""

import os
import json
import hashlib
import time
import logging
from functools import lru_cache
from typing import Optional
import google.generativeai as genai

# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
GEMINI_MODEL   = "gemini-1.5-flash"   # Fast + free tier
TEMPERATURE    = 0.0                  # Deterministic — same input → same score every time
MAX_RETRIES    = 3
RETRY_DELAY    = 2                    # seconds between retries


# ── System Prompt ─────────────────────────────────────────────────────────────
# Carefully engineered for consistency, rubric-clarity, and essay handling.
SYSTEM_PROMPT = """You are a strict, consistent academic evaluator. Your job is to grade student essay answers against an expected (model) answer.

SCORING RUBRIC (0–10):
  10 — Perfect or near-perfect: covers all key points, correct, well-explained.
   8–9 — Strong: covers most key points with minor gaps or phrasing issues.
   6–7 — Adequate: covers the main idea but missing important detail or depth.
   4–5 — Partial: some relevant content but significant gaps or misconceptions.
   2–3 — Weak: minimal relevant content, mostly incorrect or off-topic.
   0–1 — No meaningful attempt or completely incorrect.

EVALUATION CRITERIA:
1. Conceptual accuracy — are the facts and ideas correct?
2. Coverage — does it address all key points in the expected answer?
3. Depth — is the explanation sufficiently detailed for the topic?
4. Clarity — is the response coherent and logically structured?

STRICT RULES:
- Be CONSISTENT. The same answer must always receive the same score.
- Do NOT reward padding, repetition, or filler text.
- Do NOT penalise different but equally valid wording of the same idea.
- Do NOT factor in grammar or spelling unless it makes the meaning unclear.
- A student answer that is factually correct but uses different words than the expected answer should still score well.

OUTPUT FORMAT — respond ONLY with valid JSON, no markdown, no extra text:
{
  "score": <integer 0-10>,
  "feedback": "<2-3 concise sentences explaining the score>",
  "key_points_covered": ["point1", "point2"],
  "key_points_missing": ["point3"]
}"""


# ── In-memory cache (avoids re-evaluating identical answer pairs) ──────────────
_eval_cache: dict = {}

def _cache_key(expected: str, student: str) -> str:
    """Stable hash key for a (expected, student) answer pair."""
    combined = f"{expected.strip().lower()}|||{student.strip().lower()}"
    return hashlib.sha256(combined.encode()).hexdigest()


# ── Gemini Client ─────────────────────────────────────────────────────────────
def _get_client():
    """Initialise and return Gemini client. Called lazily."""
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        generation_config=genai.types.GenerationConfig(
            temperature=TEMPERATURE,
            max_output_tokens=512,
            response_mime_type="application/json",  # Forces JSON output
        ),
    )


# ── Core Evaluation Function ──────────────────────────────────────────────────
def ai_evaluate(expected_answer: str, student_answer: str) -> dict:
    """
    Evaluate a student's essay answer using Gemini AI.

    Args:
        expected_answer: The teacher's model/correct answer.
        student_answer:  The student's submitted answer.

    Returns:
        dict with keys: score (int), feedback (str),
                        key_points_covered (list), key_points_missing (list)

    Raises:
        ValueError: If inputs are empty.
        RuntimeError: If Gemini API fails after all retries.
    """
    # ── Input validation ──────────────────────────────────────────────────────
    if not expected_answer or not expected_answer.strip():
        raise ValueError("expected_answer cannot be empty.")
    if not student_answer or not student_answer.strip():
        return {
            "score": 0,
            "feedback": "No answer was provided by the student.",
            "key_points_covered": [],
            "key_points_missing": ["All key points are missing — no answer submitted."]
        }

    # ── Fast path: exact match ────────────────────────────────────────────────
    if expected_answer.strip().lower() == student_answer.strip().lower():
        return {
            "score": 10,
            "feedback": "The student's answer is an exact match to the expected answer.",
            "key_points_covered": ["All key points covered."],
            "key_points_missing": []
        }

    # ── Cache lookup ──────────────────────────────────────────────────────────
    key = _cache_key(expected_answer, student_answer)
    if key in _eval_cache:
        logger.debug("Cache hit for evaluation key %s", key[:8])
        return _eval_cache[key]

    # ── Build user prompt ─────────────────────────────────────────────────────
    user_prompt = f"""EXPECTED ANSWER (model answer by teacher):
\"\"\"
{expected_answer.strip()}
\"\"\"

STUDENT ANSWER:
\"\"\"
{student_answer.strip()}
\"\"\"

Evaluate the student answer against the expected answer using the rubric. Return JSON only."""

    # ── API call with retry logic ─────────────────────────────────────────────
    model = _get_client()
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = model.generate_content(user_prompt)
            raw_text = response.text.strip()

            # Strip accidental markdown fences if present
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            result = json.loads(raw_text)

            # Validate required fields
            score = int(result.get("score", 0))
            score = max(0, min(10, score))          # Clamp to [0, 10]
            result["score"] = score
            result.setdefault("feedback", "No feedback provided.")
            result.setdefault("key_points_covered", [])
            result.setdefault("key_points_missing", [])

            # Store in cache
            _eval_cache[key] = result
            logger.info("AI evaluation complete — score: %d", score)
            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON parse error on attempt {attempt}: {e}"
            logger.warning(last_error)
        except Exception as e:
            last_error = f"API error on attempt {attempt}: {e}"
            logger.warning(last_error)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    # ── All retries exhausted — fall back gracefully ──────────────────────────
    logger.error("Gemini evaluation failed after %d attempts: %s", MAX_RETRIES, last_error)
    raise RuntimeError(f"AI evaluation failed after {MAX_RETRIES} attempts. Last error: {last_error}")


def ai_evaluate_safe(expected_answer: str, student_answer: str,
                     fallback_score: Optional[int] = None) -> dict:
    """
    Safe wrapper around ai_evaluate().
    On any failure, returns a fallback result instead of raising.

    Use this in routes where you cannot afford to crash.
    """
    try:
        return ai_evaluate(expected_answer, student_answer)
    except Exception as e:
        logger.error("ai_evaluate_safe caught: %s", e)
        score = fallback_score if fallback_score is not None else 0
        return {
            "score": score,
            "feedback": "AI evaluation was unavailable. Score assigned automatically.",
            "key_points_covered": [],
            "key_points_missing": [],
            "error": str(e)
        }
