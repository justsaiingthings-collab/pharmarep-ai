"""
PharmaRep AI Assistant — FastAPI backend
Run: python3 -m uvicorn main:app --reload --port 8000
Open: http://localhost:8000
"""

import os
import re
import json
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from database import init_db, run_query, get_stats

load_dotenv()

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the SQLite database from the Excel file on startup."""
    init_db()
    yield


app = FastAPI(title="PharmaRep AI Assistant", lifespan=lifespan)


# ── Prompts ───────────────────────────────────────────────────────────────────

SCHEMA = """
SQLite Database Schema (all tables linked by "Medical License Number"):

Table: personal_details
  "First Name"             TEXT
  "Last Name"              TEXT
  "Medical License Number" TEXT  ← Primary Key
  "Mobile Number"          TEXT
  "Office Number"          TEXT
  "Street Address"         TEXT
  "City"                   TEXT
  "State"                  TEXT  (2-letter code e.g. TX, CA)
  "Country"                TEXT
  "Zip Code"               TEXT
  "Remarks"                TEXT

Table: license_details
  "Medical License Number" TEXT  ← FK → personal_details
  "Tenure (Years)"         INTEGER
  "License Expiry Date"    TEXT  (YYYY-MM-DD)

Table: drug_purchase_details
  "Record ID"              INTEGER  ← Primary Key
  "Drug ID"                TEXT
  "Drug Name"              TEXT
  "Brand"                  TEXT
  "Purchase Date"          TEXT  (YYYY-MM-DD)
  "Quantity"               INTEGER
  "Amount ($)"             REAL
  "Medical License Number" TEXT  ← FK → personal_details

Today's date: 2026-03-09
"""

SQL_SYSTEM = f"""You are a SQLite expert for a pharmaceutical representative assistant.

{SCHEMA}

Given a natural language question, generate ONE valid SQLite SELECT query.

STRICT RULES:
- Return ONLY the raw SQL — no markdown fences, no backticks, no explanation
- Double-quote ALL column names (they contain spaces and special characters)
- Use JOINs when data spans multiple tables; join key is "Medical License Number"
- For "expiring soon / next 90 days": "License Expiry Date" BETWEEN '2026-03-09' AND '2026-06-07'
- For "expired": "License Expiry Date" < '2026-03-09'
- For "recent purchases": last 12 months from today
- Default LIMIT 20 rows unless the user specifies otherwise
- If the question is completely unrelated to the available data, return exactly: NOT_AVAILABLE
"""

COMBINED_SYSTEM = """You are a professional AI assistant for pharmaceutical sales representatives.

Given a user question and database results, respond with ONLY valid JSON — no markdown fences, no extra text:

{
  "response": "Full professional answer here",
  "voice": "1-2 sentence plain TTS summary, max 35 words, no formatting",
  "suggestions": ["Follow-up question 1", "Follow-up question 2", "Follow-up question 3"]
}

RESPONSE RULES:
- Open with a one-line summary (e.g. "Found 4 doctors in California.")
- Group data logically: Name, Contact, Location, License status, Drug Purchases
- Format dates as "Mon DD, YYYY" | amounts as "$X,XXX.XX"
- End with: Sources: personal_details · license_details · drug_purchase_details
- Empty results → set response to exactly: "The requested data is not available in the current data sources."
- Max 400 words — never invent or infer data

VOICE RULES:
- Plain conversational language, no lists, no markdown, max 35 words

SUGGESTIONS RULES:
- 3 short, specific follow-up questions relevant to the current result
- Examples: "Show license expiry for these doctors", "Who else purchased Humira?", "Any expired licenses in Texas?"
"""


# ── Anthropic API via SDK ─────────────────────────────────────────────────────

MODEL = "claude-haiku-4-5-20251001"

def call_claude(api_key: str, system: str, user_msg: str, max_tokens: int = 600) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return message.content[0].text.strip()


def parse_combined(raw: str) -> dict:
    """Extract JSON from Claude's combined response, with a plain-text fallback."""
    import json, re
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Fallback: treat the whole text as the response
    return {"response": raw, "voice": "", "suggestions": []}


def sanitise_sql(raw: str) -> str:
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    return raw


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(str(BASE_DIR / "index.html"))


@app.get("/health")
async def health():
    api_configured = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
    try:
        stats = get_stats()
        db_ready = True
    except Exception:
        stats = {}
        db_ready = False
    return JSONResponse({
        "status": "ok" if api_configured and db_ready else "degraded",
        "api_key_configured": api_configured,
        "db_ready": db_ready,
        "db_stats": stats,
    })


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not configured. Add it to your .env file.",
        )

    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # Step 1: Generate SQL
    raw_sql =  call_claude(api_key, SQL_SYSTEM, user_msg, 400)
    sql_query = sanitise_sql(raw_sql)

    if sql_query.upper() == "NOT_AVAILABLE":
        return {
            "response": "The requested data is not available in the current data sources.",
            "voice_response": "That information is not available in the current data sources.",
            "sql_query": None,
            "result_count": 0,
            "error": None,
        }

    # Step 2: Execute SQL (local — instant)
    try:
        rows = run_query(sql_query)
    except Exception as exc:
        return {
            "response": "I had trouble querying the database. Try rephrasing your question.",
            "voice_response": "I had trouble with that query. Please try rephrasing.",
            "suggestions": [],
            "sql_query": sql_query,
            "result_count": 0,
            "error": str(exc),
        }

    # Step 3: Format response + voice + suggestions in ONE call
    snippet = str(rows[:20]) if rows else "[]"
    raw = call_claude(
        api_key, COMBINED_SYSTEM,
        f"User question: {user_msg}\n\nDatabase results ({len(rows)} row(s)):\n{snippet}",
        900,
    )
    parsed = parse_combined(raw)

    return {
        "response":     parsed.get("response", raw),
        "voice_response": parsed.get("voice", ""),
        "suggestions":  parsed.get("suggestions", []),
        "sql_query":    sql_query,
        "result_count": len(rows),
        "error":        None,
    }
