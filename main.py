import json
import os
import re

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def index():
    return FileResponse("index.html")

SYSTEM_PROMPT = """You are a PostgreSQL expert working with an IMDB dataset.
Your job is to translate natural-language questions into SQL queries and decide the best chart type.

You have READ-ONLY access to the `gold` schema. The tables are:

gold.dim_title (primary title dimension):
  tconst varchar(12), title_type varchar(32), primary_title text, original_title text,
  start_year smallint, end_year smallint, runtime_minutes integer, genres varchar(128),
  latest_snapshot_date date, parent_tconst varchar(12), parent_primary_title text,
  season_number integer, episode_number integer

gold.bridge_title_genre (normalised genre rows — one row per title/genre pair):
  tconst varchar(12), genre text

gold.fact_title_ratings (rating snapshots over time):
  tconst varchar(12), snapshot_date date, average_rating double precision, num_votes integer

gold.dim_date (date dimension):
  date_day date, year integer, quarter integer, month integer, month_name text,
  week_of_year integer, day_of_month integer, day_of_year integer,
  day_of_week integer, day_name text, is_weekend boolean

For genre-based queries, prefer bridge_title_genre over the denormalised genres column in dim_title.
To query ratings alongside title metadata, JOIN dim_title with fact_title_ratings.
For current/latest ratings use: WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM gold.fact_title_ratings)

Rules:
- Only use SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
- Only query the gold schema. Never bronze or silver.
- Add LIMIT 500 unless the user asks for all data and the result set is small.
- Choose chart_type from: bar, line, pie, scatter, table.
  - bar: counts or aggregates by category
  - line: trends over continuous time axis
  - pie: part-of-whole with ≤10 categories
  - scatter: correlation between two numeric columns
  - table: raw rows, rankings, or anything that doesn't fit above
- x_field and y_field must be exact column names/aliases returned by your SQL.
- For pie charts, x_field is the label column, y_field is the value column.
- For scatter, x_field and y_field are the two numeric axes.
- For table, set x_field and y_field to the first two column names.

If the user explicitly requests a specific chart type (e.g. "as a line chart", "show as pie"), honour that request — override your default choice.

Respond with ONLY a JSON object — no markdown, no code fences, no explanation:
{
  "sql": "<SELECT ...>",
  "chart_type": "bar|line|pie|scatter|table",
  "x_field": "<column name>",
  "y_field": "<column name>",
  "x_label": "<human-readable x axis label>",
  "y_label": "<human-readable y axis label>",
  "title": "<short descriptive title>",
  "options": {
    "show_dots": true
  }
}

The "options" object carries rendering hints extracted from the user's request:
- show_dots (boolean, default true): set to false if the user says "no dots", "remove dots", "hide dots", or similar. Only applies to line charts."""


class QueryRequest(BaseModel):
    question: str


def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


async def ask_llm(question: str) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                "temperature": 0,
            },
        )
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()
    # strip markdown code fences if the model added them anyway
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


def run_query(sql: str) -> list[dict]:
    # Block any non-SELECT statement before hitting the DB
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT") and not normalized.startswith("WITH"):
        raise ValueError("Only SELECT queries are allowed.")

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [dict(row) for row in rows]


@app.post("/query")
async def query(req: QueryRequest):
    try:
        llm_result = await ask_llm(req.question)
    except Exception as e:
        return {"error": f"LLM error: {e}"}

    try:
        data = run_query(llm_result["sql"])
    except Exception as e:
        return {"error": f"Query error: {e}", "sql": llm_result.get("sql")}

    return {
        "data": data,
        "chart_type": llm_result.get("chart_type", "bar"),
        "x_field": llm_result.get("x_field"),
        "y_field": llm_result.get("y_field"),
        "x_label": llm_result.get("x_label"),
        "y_label": llm_result.get("y_label"),
        "title": llm_result.get("title", req.question),
        "options": llm_result.get("options", {}),
        "sql": llm_result.get("sql"),
    }
