# AI Evaluation Integration Guide
## Auto Checker — Gemini 1.5 Flash

---

## 1. Install the new dependency

```bash
pip install google-generativeai
```

Your existing packages (Flask, flask_mysqldb, sentence-transformers, sklearn, nltk) are
no longer needed for evaluation — but keep them if other parts of your project use them.

---

## 2. Get your free Gemini API key

1. Go to → https://aistudio.google.com/app/apikey
2. Sign in with a Google account
3. Click **"Create API key"** → copy it

Free tier limits (more than enough for local dev):
- 15 requests / minute
- 1,500 requests / day
- 1 million tokens / month

---

## 3. Set your API key (choose one method)

### Option A — Environment variable (recommended)
```bash
# Linux / macOS
export GEMINI_API_KEY="your-key-here"

# Windows CMD
set GEMINI_API_KEY=your-key-here

# Windows PowerShell
$env:GEMINI_API_KEY="your-key-here"
```

### Option B — Edit ai_evaluator.py directly (quick local dev)
```python
# Line 20 in ai_evaluator.py
GEMINI_API_KEY = "your-key-here"   # replace the placeholder
```

---

## 4. Add the two new files to your project

```
your_project/
├── admin.py             ← replace with the new version
├── ai_evaluator.py      ← add this new file
├── templates/
│   └── ...
└── ...
```

---

## 5. Optional — store AI feedback in the database

Add a `feedback` column to your `studentanswers` table so AI feedback persists:

```sql
ALTER TABLE studentanswers
ADD COLUMN ai_feedback TEXT DEFAULT NULL;
```

Then in `student_view_score` in `admin.py`, update the DB write to include feedback:

```python
cur.execute(
    "UPDATE studentanswers SET score = %s, ai_feedback = %s "
    "WHERE student_id = %s AND test_id = %s "
    "AND question_id IN (SELECT question_id FROM questions WHERE question_text = %s)",
    (score, feedback, student_id, test_id, question_text)
)
```

---

## 6. Show feedback in the student score template

In `student_view_score.html`, inside the scores loop, add:

```html
{% if score_item.feedback %}
  <div class="ai-feedback">
    <strong>AI Feedback:</strong> {{ score_item.feedback }}
  </div>
{% endif %}
```

---

## 7. Use the new JSON API (optional, for AJAX)

You can call evaluation on-demand from JavaScript:

```javascript
// POST /api/evaluate
const response = await fetch('/api/evaluate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    expected_answer: "Photosynthesis converts light energy into chemical energy...",
    student_answer:  "Plants use sunlight to make food from CO2 and water..."
  })
});

const result = await response.json();
console.log(result);
// {
//   "score": 8,
//   "feedback": "Good coverage of the core concept. Missing mention of chlorophyll.",
//   "key_points_covered": ["light energy", "CO2", "water"],
//   "key_points_missing": ["chlorophyll", "glucose output"]
// }
```

---

## 8. Architecture summary

```
Student submits answer
        │
        ▼
student_view_score  (admin.py)
        │
        ▼
evaluate_full(expected, student_answer)
        │
        ├── exact match? → score 10 immediately (no API call)
        ├── empty answer? → score 0 immediately (no API call)
        └── else → ai_evaluate_safe()
                        │
                        ├── cache hit? → return cached result (no API call)
                        └── else → Gemini 1.5 Flash API
                                        temperature=0  ← deterministic
                                        JSON mode      ← structured output
                                        retry x3       ← resilient
```

---

## 9. Key design decisions

| Decision | Reason |
|---|---|
| `temperature=0` | Same answer pair always gets the same score |
| `response_mime_type="application/json"` | Forces structured output, no parsing guesswork |
| In-memory cache (`_eval_cache`) | Identical answers skip the API entirely |
| `ai_evaluate_safe()` wrapper | App never crashes on API failure |
| Exact-match fast path | No API cost for perfect answers |
| Retry logic (3×, 2s delay) | Handles transient API timeouts gracefully |

---

## 10. Testing the evaluator in isolation

```python
# test_eval.py  — run with: python test_eval.py
import os
os.environ["GEMINI_API_KEY"] = "your-key-here"

from ai_evaluator import ai_evaluate

result = ai_evaluate(
    expected_answer="Photosynthesis is the process by which plants use sunlight, "
                    "water and carbon dioxide to produce oxygen and energy in the form of sugar.",
    student_answer="Plants make their own food using sunlight and CO2."
)

print(f"Score:    {result['score']}/10")
print(f"Feedback: {result['feedback']}")
print(f"Covered:  {result['key_points_covered']}")
print(f"Missing:  {result['key_points_missing']}")
```
