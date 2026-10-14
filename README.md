# imdb-html-viz

A natural-language-to-visualization web app backed by IMDB data in PostgreSQL. Type a plain-English question, and the app generates SQL via an LLM, runs it against the database, and renders the result as an interactive D3.js chart.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | HTML + vanilla JS + D3.js (CDN) |
| Backend | Python 3.12+, FastAPI, uvicorn |
| Package manager | uv |
| Database | PostgreSQL (gold schema, read-only) |
| LLM | OpenRouter (model configurable via `.env`) |

## Getting Started

**1. Clone and install dependencies**
```bash
git clone hhttps://github.com/Byggerat/imdb-html-viz.git
cd imdb-html-viz
uv sync
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env and fill in your credentials
```

**3. Run the server**
```bash
uv run uvicorn main:app --reload --port 8000
```

**4. Open `index.html` in your browser** (or serve it statically).

## Environment Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST` | DB host |
| `POSTGRES_PORT` | DB port (default `5432`) |
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | DB username |
| `POSTGRES_PASSWORD` | DB password |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_MODEL` | Model string, e.g. `anthropic/claude-sonnet-4-5` |

## Example Questions

- "How many movies are there per year?"
- "What is the average rating per genre?"
- "Show the trend of average rating over the years for movies"
- "What is the genre distribution of movies?"
- "Show me the top 10 movies by number of votes"
- "Is there a correlation between runtime and rating?"

## API

`POST /query`

```json
// Request
{ "question": "How many movies are there per year?" }

// Response
{
  "data": [{"start_year": 1990, "count": 1234}, ...],
  "chart_type": "bar",
  "x_field": "start_year",
  "y_field": "count",
  "title": "Movies per Year"
}
```
