# SmartFlow AI — Invoice Automation (Milestone 1)

A portfolio prototype built with React, FastAPI and Python. It demonstrates invoice registration, duplicate detection, automatic approval routing and a dashboard. **This version does not yet process PDF files, receive email or call an AI model.** Data is in memory and resets when the backend restarts.

## Run locally

Backend (Python 3.10+):
```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Frontend (Node.js 20+):
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API documentation is at http://127.0.0.1:8000/docs.

## Demo cases
1. Add an invoice for $1,250: it routes to Pending Approval.
2. Add an invoice for $250: it routes to Ready for Review.
3. Enter the same vendor and invoice number again: the API rejects it as a duplicate (HTTP 409).
4. Approve an invoice: its status and dashboard counters update.

## Next milestones
SQLite persistence, PDF extraction, AI-assisted structured extraction, inbound email integration, audit logging, automated tests, and deployment.
