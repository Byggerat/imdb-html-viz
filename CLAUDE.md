# html-viz

A natural-language-to-visualization web app backed by IMDB data in PostgreSQL. Users type plain-English questions; an LLM generates SQL, the backend executes it, and D3.js renders the result as an interactive chart.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML + vanilla JS + D3.js (CDN) |
| Backend | Python 3.12+, FastAPI, uvicorn |
| Package manager | uv (astral-sh/uv) |
| Database | PostgreSQL (gold schema, read-only) |
| LLM | OpenRouter (model configurable via `.env`) |
| HTTP client | httpx (async) |
| DB driver | psycopg2-binary |

---

## File Map

```
html-viz/
├── CLAUDE.md           — this file
├── index.html          — single-page frontend
├── main.py             — FastAPI server (POST /query endpoint)
├── pyproject.toml      — Python dependencies (managed by uv)
├── uv.lock             — locked dependency versions
├── .env                — secrets (never commit)
└── .env.example        — template
```

---

## Running Locally

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
# then open index.html in a browser (or serve it statically)
```

The frontend fetches `http://localhost:8000/query`. For local dev, CORS is open to all origins.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST` | DB host |
| `POSTGRES_PORT` | DB port (default 5432) |
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | DB username |
| `POSTGRES_PASSWORD` | DB password |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_MODEL` | Model string, e.g. `anthropic/claude-sonnet-4-5` or `mistralai/mistral-7b-instruct` |

---

## API Contract

### `POST /query`

**Request**
```json
{ "question": "How many movies are there per year?" }
```

**Response (success)**
```json
{
  "data": [{"start_year": 1990, "count": 1234}, ...],
  "chart_type": "bar",
  "x_field": "start_year",
  "y_field": "count",
  "title": "Movies per Year"
}
```

**Response (error)**
```json
{ "error": "Could not generate a valid SQL query for that question." }
```

---

## LLM Prompt Design

The system prompt instructs the LLM to act as a SQL expert and return **only** a JSON object (no markdown, no prose). The schema context included in the system prompt is the full gold-layer schema (see below).

**Expected LLM output format:**
```json
{
  "sql": "SELECT start_year, COUNT(*) AS count FROM gold.dim_title WHERE start_year IS NOT NULL GROUP BY start_year ORDER BY start_year",
  "chart_type": "bar",
  "x_field": "start_year",
  "y_field": "count",
  "title": "Movies per Year"
}
```

**chart_type** must be one of: `bar`, `line`, `pie`, `scatter`, `table`.

Rules given to the LLM:
- Only query the `gold` schema; never bronze or silver.
- Use only `SELECT` statements; never INSERT/UPDATE/DELETE/DROP.
- Limit results to 500 rows maximum.
- Choose the chart type that best fits the data shape (time series → line, part-of-whole → pie, correlation → scatter, everything else → bar, raw rows → table).
- `x_field` and `y_field` must match column names returned by the SQL.

---

## Database Schema (gold layer)

### `gold.dim_title` — primary title dimension
| Column | Type | Notes |
|--------|------|-------|
| tconst | varchar(12) | IMDB title ID |
| title_type | varchar(32) | movie, short, tvSeries, tvEpisode, etc. |
| primary_title | text | English display title |
| original_title | text | Original language title |
| start_year | smallint | Release/start year |
| end_year | smallint | End year (TV series) |
| runtime_minutes | integer | |
| genres | varchar(128) | Comma-separated, e.g. "Action,Drama" |
| latest_snapshot_date | date | Date this row was last updated |
| parent_tconst | varchar(12) | For episodes: parent series ID |
| parent_primary_title | text | Display title of parent series |
| season_number | integer | |
| episode_number | integer | |

> **Note:** ratings are not on `dim_title`. JOIN with `fact_title_ratings` to get `average_rating` / `num_votes`. For current ratings filter on `snapshot_date = (SELECT MAX(snapshot_date) FROM gold.fact_title_ratings)`.

### `gold.bridge_title_genre` — normalised genre rows
| Column | Type | Notes |
|--------|------|-------|
| tconst | varchar(12) | IMDB title ID |
| genre | text | Single genre (one row per title/genre pair) |

> Prefer this over the denormalised `genres` column in `dim_title` for genre-based aggregations and filters.

### `gold.fact_title_ratings` — rating snapshots over time
| Column | Type |
|--------|------|
| tconst | varchar(12) |
| snapshot_date | date |
| average_rating | double precision |
| num_votes | integer |

### `gold.dim_date` — date dimension
| Column | Type |
|--------|------|
| date_day | date |
| year | integer |
| quarter | integer |
| month | integer |
| month_name | text |
| week_of_year | integer |
| day_of_month | integer |
| day_of_year | integer |
| day_of_week | integer |
| day_name | text |
| is_weekend | boolean |

---

## Chart Types & When to Use

| chart_type | Use case |
|-----------|----------|
| `bar` | Counts or aggregates by category (movies per year, top genres) |
| `line` | Trends over time (avg rating per year) |
| `pie` | Part-of-whole breakdown with few categories (genre share) |
| `scatter` | Correlation between two numeric fields (runtime vs rating) |
| `table` | Raw row results, rankings, or anything that doesn't fit a chart |

---

## Example Questions

- "How many movies are there per year?" → bar
- "What is the average rating per genre?" → bar
- "Show the trend of average rating over the years for movies" → line
- "What is the genre distribution of movies?" → pie
- "Show me the top 10 movies by number of votes" → table
- "Is there a correlation between runtime and rating?" → scatter
