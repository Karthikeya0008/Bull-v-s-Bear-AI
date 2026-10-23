# Bull vs Bear AI

Agentic RAG for Indian IPOs. Bull and Bear agents debate an IPO using evidence retrieved from
its DRHP/RHP, news and Python-computed financial metrics; a Judge on a different LLM verifies
every citation and gives a verdict. Built for IntelliCode 2026 (FinTech).

> Status: **Phase 1 (ingestion and knowledge layer)**. The full README (architecture,
> algorithms, demo) is written in Phase 4.

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
```
```powershell
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
```powershell
Copy-Item .env.example .env
```

## Phase 1 usage

Run the IPO watcher once (SEBI + NSE + BSE + the `data/raw` drop folder):

```powershell
.\.venv\Scripts\python.exe -m backend.ingest --watch
```

Download and ingest one IPO, or every curated IPO in `config/seed_ipos.yaml`:

```powershell
.\.venv\Scripts\python.exe -m backend.ingest --ipo jio-platforms
```
```powershell
.\.venv\Scripts\python.exe -m backend.ingest --all
```

Manual fallback: put any offer-document PDF in `data/raw/<ipo_id>/` (name it like
`RHP_2026-09-21.pdf` so the document type is detected) and run `--all`.

Inspect what was ingested:

```powershell
.\.venv\Scripts\python.exe -m backend.query ipos
```
```powershell
.\.venv\Scripts\python.exe -m backend.query sections --ipo jio-platforms
```
```powershell
.\.venv\Scripts\python.exe -m backend.query chunks --ipo jio-platforms --q "repayment of borrowings" -k 5
```
```powershell
.\.venv\Scripts\python.exe -m backend.query tables --ipo jio-platforms --statement pnl
```

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Data sources

- SEBI public issue filings (DRHP / RHP): https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=10
- NSE IPO listings: https://www.nseindia.com/market-data/all-upcoming-issues-ipo
- BSE public issues (best effort; currently blocks scripted access)

## Acknowledgements

Libraries: FastAPI, Uvicorn, Pydantic, pydantic-settings, SQLAlchemy, PyMuPDF (AGPL-3.0),
pdfplumber (and pdfminer.six), ChromaDB, sentence-transformers, PyTorch, httpx,
Beautiful Soup, lxml, APScheduler, PyYAML, tenacity, NumPy, pytest, Ruff.

Models: [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (MIT).
