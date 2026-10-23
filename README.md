# Bull vs Bear AI

**Agentic RAG that debates every Indian IPO from its own offer document.**
A Bull agent and a Bear agent each retrieve their own evidence from the company's DRHP/RHP and
receive Python-computed financial metrics as facts. They debate over three rounds (opening,
rebuttal, closing). A Judge on a *different* LLM provider first re-checks every citation in code,
strikes unsupported claims, and only then weighs the survivors into a verdict with a confidence
level. A React dashboard lists all IPOs and shows the debate live, with clickable citations that
open the source page.

Built for IntelliCode 2026 (FinTech). Demo case: Jio Platforms (DRHP filed 19 June 2026, RHP
15 Oct 2026). The pipeline is IPO-agnostic. Moneyview (digital lending) and Orient Cables
(manufacturing) go through exactly the same code.

> ⚠ Not investment advice. Every verdict payload carries this disclaimer.

## The problem

Indian offer documents run 500–600 pages, and retail investors get 3 days to decide. LLM summaries
are fluent but unverifiable: they hallucinate figures and cite nothing. This project keeps the
fluency but makes every statement auditable:

- **Numbers never come from an LLM.** Ratios and scores are computed in Python from the extracted
  restated statements. Each one records its formula, inputs and source pages.
- **Every claim must cite** chunk ids or metric ids. Claims without a valid reference are struck.
- **Adversarial structure:** two agents with opposite incentives search for evidence the other
  side would rather ignore.
- **Independent judge:** a different model family, and only after deterministic verification.

## Architecture

```
Data Sources (SEBI filings, NSE issues, BSE*, data/raw drop folder)
        │
        ▼
IPO Watcher (APScheduler; dedupe on issuer + filing date + doc type)  ──► IPO registry (SQLite)
        │
        ▼
Parse & Chunk (PyMuPDF)              Table Extraction (pdfplumber)
 section-aware, recursive, overlap    restated P&L / balance sheet / cash flow per fiscal year
        │                                         │
        ▼                                         ▼
Vector DB (ChromaDB, bge-small, CPU)      Metrics Store (SQLite: value, formula, inputs, pages)
        │      + BM25 ──► RRF hybrid retriever    │
        └──────────────┬──────────────────────────┘
                       ▼
        Bull Agent ◄── 3 rounds ──► Bear Agent     (debater LLM: Gemini, fallbacks via .env)
                       │
                       ▼
        Judge: code verification (rapidfuzz figures + NLI entailment) → LLM verdict
               (judge LLM on a different provider, e.g. Groq)
                       │
                       ▼
        FastAPI (SSE stream, replay) ──► React dashboard (Vite + TS + Tailwind)
```
\* BSE's API sits behind bot protection and refuses scripted requests; the source fails soft.

### Code map

| Area | Module |
|---|---|
| Registry, dedup, status | `backend/ingestion/registry.py` |
| Sources | `backend/ingestion/sources/{sebi,nse,bse,local_drop}.py` |
| Watcher / scheduler | `backend/ingestion/watcher.py` |
| PDF parsing, section detection | `backend/processing/pdf_parser.py`, `sections.py` |
| Chunking | `backend/processing/chunker.py` |
| Financial tables | `backend/processing/tables.py`, `line_items.py` |
| Embeddings, vector store, cache | `backend/knowledge/{embeddings,vector_store,cache}.py` |
| Metrics | `backend/metrics/formulas.py` (pure), `engine.py` (traceability) |
| Hybrid retrieval | `backend/retrieval/hybrid.py` |
| LLM client | `backend/llm/client.py` |
| Agents, verifier, judge, orchestration | `backend/agents/` |
| Back-test | `backend/backtest.py` |
| API | `backend/api/main.py` |
| Dashboard | `frontend/src/` |

## Algorithms

- **Section detection.** SEBI ICDR fixes the titles of offer-document sections. Headings are
  detected from PDF bookmarks or, failing that, from lines that are bold or larger than body
  text, set in capitals, in the top third of the page, and fully matching a pattern table. Pages
  matching more than three headings are tables of contents and are skipped.
- **Chunking.** Chunks never cross a section boundary. Inside a section, a span-based recursive
  splitter breaks on paragraph, then line, sentence, clause and word boundaries, up to 1,200
  characters (about 300 tokens, under bge-small's 512) with 200 characters of overlap. Every
  chunk keeps its exact page range.
- **Table extraction.** Statement pages are found by title. pdfplumber words are grouped into
  lines, and numbers broken by stray spaces ("1 26.52") are rejoined. Period columns
  (`FY2026`, `STUB-2026-06`) are read from the header and ordered by x position. Values map to
  columns by count, with leading note numbers ignored, or by nearest x. Labels map to canonical
  line items using sub-heading context (current vs non-current borrowings). Units are
  normalised to INR million.
- **Metrics.** Debt-to-equity, interest coverage (EBIT / finance costs), revenue and PAT growth,
  revenue CAGR, EBITDA margin (PBT + finance costs + D&A − other income), PAT margin, ROE,
  P/E at the upper price band, P/E vs the listed-peer median (from `config/peers.yaml`, copied
  from each RHP's peer table) and the OFS share of the issue.
  - **Altman Z''-Score, emerging-markets variant** (Altman 2005):
    `3.25 + 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BookEquity/TL`. It drops the
    sales/assets term, which is very industry-dependent (telecom vs fintech vs cables). It uses
    *book* equity, because a pre-IPO company has no market value. And it was calibrated for
    emerging-market issuers. Zones: safe > 5.85, grey 4.35–5.85, distress < 4.35. Ind AS has no
    separate retained-earnings line, so *other equity* is used as the proxy and the metric says so.
  - **Beneish M-Score** (8-variable, threshold −1.78) needs two consecutive years and the cash
    flow from operations. If an input is missing it is **skipped with a reason**, never guessed.
    Documented neutral assumptions apply: GMI = 1 for service companies without a cost-of-goods
    line, and SG&A is proxied by other expenses.
- **Hybrid retrieval.** BM25 (rank_bm25) over section + chunk text, with a small DRHP
  query-expansion table ("debt" → "borrowings"), plus dense cosine search (bge-small). The two
  are fused with **Reciprocal Rank Fusion**, `Σ 1/(60 + rank)`. RRF uses ranks only, so the two
  scores never need calibration. Results are filtered by `ipo_id` and the latest offer document.
- **Verification (judge, in code).** (1) Every evidence id must resolve. (2) Every figure in the
  claim must appear in a cited chunk or equal a cited metric value, allowing for rounding and
  crore/million/percent scale changes. (3) An optional verbatim quote is fuzzy-matched with
  rapidfuzz `partial_ratio ≥ 85`. (4) Entailment comes from `cross-encoder/nli-deberta-v3-small`,
  with a lexical-overlap fallback if the model is unavailable. Each claim ends up *supported*,
  *partially supported* or *struck*, with a reason.
- **Verdict.** The LLM judge sees only surviving claims and their status, and returns Strong Bull
  … Strong Bear, a confidence level and the top 3 decisive claims per side. A transparent
  baseline (strength × verification weight per side) is always computed. It becomes the verdict
  if no judge provider is available.
- **Caching.** SHA-256 content hashes in SQLite for embeddings, LLM responses and price data.
  Re-runs are free and survive rate limits. Every LLM call is logged (`llm_calls`) with tokens
  and latency.

## How to run

All commands are for **Windows PowerShell**, run from the project folder (`E:\BdebateEngine`),
one command at a time.

### A. Run it (when already set up)

Open **two PowerShell terminals** in the project folder.

**Terminal 1: start the backend API**
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --port 8000
```
Wait until it prints `Application startup complete`, and leave it running.

**Terminal 2: start the dashboard**
```powershell
npm --prefix frontend run dev
```
Wait for `Local: http://localhost:5173/`, and leave it running.

**Open the app** in your browser at **http://localhost:5173**

**Using it:**
1. On the IPO list, click **Jio Platforms Limited** (or Moneyview / Orient Cables).
2. Click **⚖ Start Debate** to run a live debate. It needs internet and your API keys, and takes
   about 2–4 minutes.
3. Or click a saved debate under **Saved debates** to replay it instantly, with no internet or
   API calls. This is the safest option for a live demo.
4. Click any citation chip (📄 or ƒx) to see the source page or the formula.
5. Open the **Back-test** tab to see verdicts against actual listing returns.

**To stop:** press `Ctrl + C` in both terminals.

### B. First-time setup (new machine)

You need **Python 3.11** and **Node 18+**. Run these one at a time:

1. Create the virtual environment:
   ```powershell
   python -m venv .venv
   ```
2. Install PyTorch (CPU build):
   ```powershell
   .\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```
3. Install the Python packages:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
4. Install the dashboard packages:
   ```powershell
   npm --prefix frontend install
   ```
5. Create your settings file:
   ```powershell
   Copy-Item .env.example .env
   ```
6. Open `.env` in an editor and fill in `GEMINI_API_KEY` (debaters) and `GROQ_API_KEY` (judge).
   `OPENROUTER_API_KEY` or `CEREBRAS_API_KEY` is optional but recommended: the judge must use a
   different provider from the debaters, so a third key keeps verdicts LLM-based when one free
   tier runs out. Without any keys the system still runs, using clearly labelled rule-based agents.
7. Download and process the IPO documents. This takes about 15 minutes the first time, mostly
   for embeddings:
   ```powershell
   .\.venv\Scripts\python.exe -m backend.ingest --all
   ```
8. Then follow **Section A**.

### Useful extras

Check for new IPO filings on SEBI and NSE:
```powershell
.\.venv\Scripts\python.exe -m backend.ingest --watch
```

Analyse a different IPO: drop its PDF into `data\raw\<ipo-id>\`, named like
`RHP_2026-09-21.pdf`, then run:
```powershell
.\.venv\Scripts\python.exe -m backend.ingest --all
```

Re-process one IPO from scratch (embeddings come from the cache, so it is quick):
```powershell
.\.venv\Scripts\python.exe -m backend.ingest --ipo jio-platforms --force
```

Inspect what was ingested from the command line:
```powershell
.\.venv\Scripts\python.exe -m backend.query chunks --ipo jio-platforms --q "repayment of borrowings" -k 5
```
```powershell
.\.venv\Scripts\python.exe -m backend.query tables --ipo jio-platforms --statement pnl
```

Run the tests:
```powershell
.\.venv\Scripts\python.exe -m pytest
```

### If something goes wrong

- **Dashboard says "Could not reach the API":** Terminal 1 isn't running. Start it again.
- **A debate shows "rule-based" instead of Gemini/Groq:** your free-tier quota is used up, or
  Gemini is busy. Wait a while, or add an OpenRouter key. Replaying saved debates always works.
- **A model error such as "no longer available":** free-tier models change. Set `GEMINI_MODEL`
  or `GROQ_MODEL` in `.env` to a model your key lists.
- **Port already in use:** a previous run is still open. Close the old terminals, or restart your PC.

**Offline demo.** Each finished debate stores every streamed event, so replay needs no internet
and no LLM. Back-test prices are cached in `data/backtest_prices.csv`.

## API

| Method | Path | |
|---|---|---|
| GET | `/api/ipos?status=upcoming\|open\|listed` | registry |
| GET | `/api/ipos/{id}` | IPO and its documents |
| GET | `/api/ipos/{id}/metrics` | metrics with formula, inputs, pages |
| GET | `/api/ipos/{id}/financials` | extracted statement rows |
| POST | `/api/ipos/{id}/search` | hybrid search `{"query": "...", "k": 8}` |
| POST | `/api/ipos/{id}/debate` | run a debate, Server-Sent Events stream |
| GET | `/api/debates/{id}` | stored claims, verification, verdict, models |
| GET | `/api/debates/{id}/replay` | re-stream a saved debate |
| GET | `/api/chunks/{chunk_id}` | citation text and page |
| GET | `/api/documents/{doc_id}/pdf#page=N` | source PDF |
| GET | `/api/backtest` | verdict vs listing-day and current return |

## Limitations (honest list)

- Table extraction is heuristic. Unusual layouts can miss rows. `data/processed/<ipo>/financials_override.csv`
  corrects any value, and overridden rows are flagged.
- The back-test sample is tiny (only recently listed IPOs). It illustrates the idea; it is not
  evidence of predictive skill.
- News is not ingested yet. Evidence comes from offer documents and computed metrics.
- Search quality check: for Jio, "debt repayment" ranks the Objects of the Issue passage (p.107)
  2nd, behind an MD&A paragraph on debt-financing cash flows; "litigation" queries land in
  Outstanding Litigation first.
- Without LLM API keys the debaters and judge fall back to a deterministic rule-based mode
  (labelled `rule-based` everywhere). It is useful offline, but much less nuanced than the LLM run.

## Data sources

- SEBI public issue filings (DRHP / RHP): https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10
- NSE IPO listings: https://www.nseindia.com/market-data/all-upcoming-issues-ipo
- BSE public issues (attempted; blocked for scripts)
- Yahoo Finance daily prices via yfinance (back-test)
- Offer documents used in the demo: Jio Platforms DRHP and RHP, Moneyview RHP and Orient Cables
  (India) RHP, all public on sebi.gov.in

## Acknowledgements

**Libraries:** FastAPI, Uvicorn, Pydantic, pydantic-settings, SQLAlchemy, PyMuPDF (AGPL-3.0),
pdfplumber / pdfminer.six, ChromaDB, sentence-transformers, PyTorch, NumPy, rank_bm25,
RapidFuzz, httpx, Beautiful Soup, lxml, APScheduler, PyYAML, tenacity, yfinance, pandas, pytest,
Ruff; React, React Router, Vite, TypeScript, Tailwind CSS.

**Models:** [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (MIT),
[cross-encoder/nli-deberta-v3-small](https://huggingface.co/cross-encoder/nli-deberta-v3-small)
(Apache-2.0), Google Gemini 3.5 Flash (debaters), OpenAI gpt-oss-120b served by Groq (judge),
and optional OpenRouter / Cerebras models as fallbacks (all free tiers).

**Methods:** Altman (2005) *An emerging market credit scoring system for corporate bonds*;
Beneish (1999) *The Detection of Earnings Manipulation*; Cormack, Clarke & Büttcher (2009)
*Reciprocal Rank Fusion*; Robertson & Zaragoza (2009) *BM25 and beyond*.
