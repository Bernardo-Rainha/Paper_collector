# Paper_collector

A simple Python script that pulls papers from five different sources via their respective APIs. How many you want (sometimes how many they can provide).

---

## What it does

The program searches for papers from different sources, downloads them, and creates a JSON file for each one, saving everything in a folder called `_BIBLIOTECA/YYYY-MM-DD/`.

The JSON serves as library control: it is used to check whether articles have already been downloaded, never repeating any, and if it runs more than once, it skips already-seen papers and continues with the next unseen ones (probably). It also stores metadata about each paper, giving you the freedom to build your own stuff on top of it later.

The sources have slightly different search modes, but nothing special. They all use the same system of keywords and/or categories.

The program was ENTIRELY designed as a daily application running on **Obsidian**, with its files edited in Markdown format with native YAML. Just put it in your vault and set it to repeat every day or every 7 days. It has a STRONG bias towards computing, engineering, mechanics and physics (you can change the keywords in the script).

---

## Requirements

- Python 3.9+ (standard library only — no `pip install` needed)
- Internet connection

## Setup

1. Drop `papers_collector.py` inside your Obsidian vault
2. Edit the `CONFIGURAÇÕES` block at the top:
   - `KEYWORDS` — your search terms
   - `S2_API_KEY` — your free Semantic Scholar key (see Sources)
   - `MAX_RESULTS`, `DAYS_BACK`, `DOWNLOAD_PDF`, etc.
3. Run it daily (cron, Task Scheduler, or a notebook cell)

## Usage

```bash
python papers_collector.py             # normal collection
python papers_collector.py --dry-run   # only lists what it found, saves nothing
python papers_collector.py --test-s2   # tests the Semantic Scholar key (1 request)
python papers_collector.py --busca "microservices"   # searches your local collection
```

## Output structure

```
_BIBLIOTECA/
├── vistos.json                  # dedup state (ids + normalized titles)
└── YYYY-MM-DD/
    ├── index.json               # all papers of the day
    ├── _RELATORIO_YYY-MM-DD.md  # daily report with auto-summaries
    ├── Paper_Title.pdf          # full text (when open access)
    ├── Paper_Title.json         # complete metadata
    └── Paper_Title.md           # Obsidian note with YAML frontmatter
```

Each `.md` note carries frontmatter (`titulo`, `autores`, `publicado`, `fonte`, `citacoes`, `tags`, `link`) so Obsidian search, Graph View and Dataview work natively. The auto-summary prefers the Semantic Scholar TL;DR (AI-generated); when unavailable, it falls back to an extractive summary of the abstract.

## Sources

### arXiv repository
The arXiv has a public API for pull requests and downloading papers: https://export.arxiv.org/api/query

### NASA NTRS
The NASA Technical Reports Server (NTRS) provides access to NASA metadata records, full-text online documents, images, and videos. The types of information included are conference papers, journal articles, meeting papers, patents, research reports, images, movies, and technical videos — scientific and technical information (STI) created or funded by NASA. Public API, **no key required**, rate limit 500 req/15 min. Docs: https://ntrs.nasa.gov/ · Swagger UI: https://ntrs.nasa.gov/api/openapi/

### Semantic Scholar
The Semantic Scholar API is given by the institution for simple requests; however, you need an academic (or business) email. After sending the request you'll receive the API key by email in a few hours. **Limit: 1 request/second (cumulative) — get the key, the anonymous pool rate-limits constantly.** Link: https://www.semanticscholar.org/product/api

### OpenAlex
Like the others, it has an open API with no key, but a limit of ~10 req/second. It covers more than just papers. Check it at https://api.openalex.org

### SciELO
Open access journals in português/español hosted on SciELO. It's not an API by its own: this source works through the OpenAlex index, with a **client-side filter that keeps only papers hosted at `scielo.*` URLs**. SciELO does not have a public search API of its own.

---

## Troubleshooting

**S2 keeps returning 429 (rate limit)** — run `python papers_collector.py --test-s2`. It shows whether the key is loaded, the remaining quota, and the raw server response. If `x-ratelimit-remaining: 0`, wait for the daily reset.

**Some PDFs fail to download** — usually paywalled or session-protected links; the script continues with the rest. For NASA links, remember they come as relative paths (`/api/citations/...`) and are resolved to absolute URLs internally.

**A source fails completely** — no problem: the script logs the failure and continues with the other four. Daily collection is never blocked by one source.

## Notes

- NASA asks for attribution: *"Data provided by NASA Scientific and Technical Information Program"*
- Some NTRS documents are export-controlled and have metadata but no public PDF — those are saved as notes only
- Built for personal/academic use
