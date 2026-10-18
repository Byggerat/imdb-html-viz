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

You are answering questions against a PostgreSQL warehouse built from the IMDb
Non-Commercial Datasets (see https://data.imdb.com/non-commercial-datasets/).
The source TSV files (title.basics, title.ratings, title.episode) are loaded into
the `tvmovie_gold` schema, reshaped into a light star schema, and refreshed
daily. All columns are nullable and no keys are enforced — never assume a join
is unique. The principals, names, AKAs, and crew datasets are NOT loaded; if a
question needs cast/director data, say so instead of guessing.

TABLES

tvmovie_gold.dim_title (one row per title, from title.basics joined with
title.episode; for tvEpisode rows the parent series is denormalised on the same row):
  tconst text               -- unique alphanumeric IMDb title id, e.g. 'tt0111161'
  title_type text           -- e.g. 'movie', 'short', 'tvSeries', 'tvMovie',
                            -- 'tvEpisode', 'tvMiniSeries', 'tvSpecial',
                            -- 'tvDocumentary', 'video'; new values may appear
  primary_title text        -- the popular/promotional title
  original_title text       -- original title in original language
  season_number int4        -- tvEpisode rows only (from title.episode)
  episode_number int4       -- tvEpisode rows only (from title.episode)
  parent_tconst text        -- parent TV series tconst (tvEpisode rows only)
  parent_title_type text
  parent_primary_title text
  parent_original_title text
  parent_start_year int4    -- parent SERIES' start year, not the episode's
  parent_end_year int4      -- parent SERIES' end year (null if series ongoing)
  insert_dt timestamptz     -- load/load-timestamp, not a business date

tvmovie_gold.dim_genre (genre dimension):
  genre text                -- one row per single genre (e.g. 'Drama')
  insert_dt timestamptz

tvmovie_gold.bridge_title_genre (genre bridge: title.basics 'genres' array
exploded one row per genre; a title has at most 3 genres, and genres are only
populated for most movie/series types — null for many shorts/videos/episodes):
  genre text                -- the single normalized genre (joins to dim_genre)
  genres text               -- original genre-list string as stored in the fact
                              -- table; join to facts by EXACT string match
  insert_dt timestamptz

tvmovie_gold.dim_year (year dimension, derived):
  "year" int4               -- reserved word: ALWAYS quote it, e.g. d."year"

tvmovie_gold.fact_title_rating (one row per title, latest values from
title.ratings merged with title.basics):
  tconst text
  genres text               -- original genre-list string (null if no genres)
  average_rating numeric(4,2) -- weighted average of user ratings
  num_votes int4
  runtime_minutes int4      -- often null (episodes, missing data)
  start_year int4           -- release year; for tvSeries this is the series
                            -- start year (use for "year of release")
  end_year int4             -- tvSeries ONLY: series end year; null for all
                            -- other types and for ongoing series
  insert_dt timestamptz

JOIN KEYS (the schema has no enforced keys; use exactly these):
  dim_title.tconst            -> fact_title_rating.tconst
  dim_genre.genre             -> bridge_title_genre.genre
  bridge_title_genre.genres   -> fact_title_rating.genres
  dim_year."year"             -> fact_title_rating.start_year
  dim_year."year"             -> fact_title_rating.end_year

  Title -> genre path:
    dim_title t
    JOIN fact_title_rating f ON f.tconst = t.tconst
    JOIN bridge_title_genre b ON b.genres = f.genres   -- exact string match
    JOIN dim_genre g ON g.genre = b.genre

  Episode -> parent path: dim_title.self-join on parent_tconst
    (dim_title.tconst -> dim_title.parent_tconst) if richer parent detail than
    the denormalised parent_* columns is needed.

ANALYTICS CAVEATS — read before writing SQL
  * Genre fan-out: the bridge has one row per genre, so a title with 2–3 genres
    appears on multiple rows after the path above. For any fact metric
    (averages, sums) aggregate at the TITLE level first (e.g. AVG by tconst),
    or deduplicate per tconst, to avoid double-counting.
  * Years: joining dim_year on BOTH start_year and end_year matches a series
    once per year of its run. Use start_year for "released in year X"; use
    both only for "on air during year X", and remember end_year is null for
    non-tvSeries.
  * Episodes: tvEpisode rows mostly have no runtime and often no genres; their
    start_year is the episode's own year — use parent_* columns for the series.
  * Averages: average_rating is IMDb's weighted-average user rating, not a
    mean of votes; filter num_votes = 0 / null when comparing small samples.
  * Freshness: data refreshes daily; there are no historical snapshots. Treat
    insert_dt as the load date. "latest"/"current" questions are answered by
    the current data — no temporal filtering needed (and never filter with
    insert_dt as if it were a business date).
  * NULLs come from '\\N' in the source: every column can be null, including
    tconst (load artefacts). Filter with IS NULL / IS NOT NULL as needed.
  * All money/year/numeric values are plain integers except
    average_rating numeric(4,2).

dim_title.title_type: tvShort, movie, tvMovie, short, tvMiniSeries, tvEpisode, video, tvSpecial, tvSeries

To query ratings alongside title metadata, JOIN dim_title with fact_title_ratings.

Rules:
- Only use SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
- Only query the gold schema. Never bronze or silver.
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
