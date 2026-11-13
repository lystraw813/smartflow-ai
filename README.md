# SmartFlow AI — Invoice Automation

**Live demo:** https://smartflow-ai.enzonic.dev/  
**API documentation:** https://smartflow-api.enzonic.dev/docs

SmartFlow AI is a cloud-hosted **portfolio prototype** for AI-assisted invoice processing and workflow automation. It combines a React interface, a Python/FastAPI backend, a MySQL database, and the OpenAI API to reduce manual data entry and help users track invoice approval and payment status.

> **Demo only:** Use fictional or nonconfidential invoices. This is not a production accounting or payment-processing system. Review all AI-extracted values against the source invoice before saving.

## Features

- **AI-assisted PDF extraction:** Extracts a proposed vendor, invoice number, amount, and due date from uploaded invoices, including scanned/image-based PDFs. The user reviews and can correct the fields before registration.
- **Invoice registration:** Saves invoice details and optionally retains the original PDF for viewing.
- **Duplicate checks:** Rejects a repeated vendor and invoice-number combination within the same demo workspace.
- **Approval routing:** Invoices over $1,000 are marked **Pending Approval**; smaller invoices are marked **Ready for Review**. Users can approve or reject invoices.
- **Payment tracking:** Approved invoices can be marked paid, or corrected back to unpaid.
- **Dashboard:** Displays total invoices, approved/unpaid amount, overdue invoices, and invoices due in the next seven days.
- **Document retrieval and audit history:** Original PDFs remain available after approval or payment; workflow events are recorded.
- **Temporary demo workspaces:** Visitor-specific demo data is separated by browser session and expired after 24 hours.
- **API usage protection:** The AI extraction endpoint has application-level request quotas to reduce unexpected API usage. These are request limits, **not** a guaranteed dollar spending cap.

## Technology

| Layer | Technology |
| --- | --- |
| Frontend | React, Vite, JavaScript |
| Backend/API | Python, FastAPI |
| Database | MySQL in cloud deployments; SQLite for local development |
| AI extraction | OpenAI API |
| PDF processing | PyMuPDF, pypdf |
| Hosting | Enzonic |
| Version control | GitHub |

## Demonstrated workflow

1. Select a PDF invoice and click **Extract Details**.
2. Review the AI-populated vendor, invoice number, amount, and due date; correct any errors.
3. Click **Add invoice** to register the invoice and attach its original PDF.
4. Review the automatically assigned approval status; approve or reject the invoice.
5. Open **View PDF** to retrieve the attached document.
6. For an approved invoice, click **Mark as Paid** to update the payment status and dashboard.

## Validation performed

Four invoice PDFs were tested through the live extraction API, covering different document challenges:

| Test | Challenge | Observed result |
| --- | --- | --- |
| Vonvitti Visuals | Image-based scanned PDF | Vendor, invoice number, and amount extracted correctly |
| BriteBox Electrical | Seven-page PDF with additional material and payment/balance amounts | Correct invoice vendor, number, and total extracted |
| Corporate Filings LLC | Multiple company names and dates | Correct vendor, number, amount, and explicitly stated due date extracted |
| Value Focused Solutions | Fragmented selectable PDF text | Correct vendor, invoice number, and amount extracted |

**Result:** All four test invoices returned the expected vendor, invoice number, and total amount. Due-date accuracy should still be independently checked for documents that do not clearly state a due date; an invoice date must not be assumed to be a due date.

The frontend was also tested end-to-end with Value Focused Solutions: extraction, form population, invoice registration, **Pending Approval** routing for $4,427.50, approval, overdue calculation, original PDF viewing, and marking the invoice **Paid**. The approved/unpaid balance returned to $0.00 after payment was recorded.

## Run locally

### Backend

Requires Python 3.10+ and the dependencies in `backend/requirements.txt`.

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:

- **Windows PowerShell:** `.venv\Scripts\Activate.ps1`
- **macOS/Linux:** `source .venv/bin/activate`

Then install dependencies and start the API:

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

The local API documentation is at http://127.0.0.1:8000/docs.

For AI extraction, set an environment variable named `OPENAI_API_KEY` in your local shell or deployment provider's secret settings. **Never commit an API key or other credentials to GitHub.** If `DATABASE_URL` is configured, the backend uses MySQL; otherwise it uses local SQLite.

### Frontend

Requires Node.js 20+.

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Configure the frontend API URL for your development or hosted environment as required by the app's frontend setup.

## Current scope and limitations

- This is a portfolio demonstration, not a production-ready accounts-payable system.
- AI-extracted values require human review. Invoices without a clear due date may need manual correction.
- PDF uploads are limited to 10 MB and 10 pages; the extraction implementation visually examines up to the first three pages and may also use embedded text.
- Demo session identifiers are **not authenticated accounts**; do not upload confidential financial documents.
- Demo invoice data is intended to expire after 24 hours.
- Request quotas reduce the risk of runaway AI usage but do not ensure a fixed spending maximum.
- No live bank integrations, real payments, inbound email ingestion, or accounting-system synchronization are implemented.

## Potential next steps

- Improve due-date validation and explicit missing-field handling.
- Add automated integration/regression tests and clearer operational monitoring.
- Add production-grade authentication, authorization, and security controls.
- Add optional email ingestion or accounting-system integration.
- Add redacted screenshots and a short product walkthrough video.

---

**Project status:** Working, cloud-hosted prototype demonstrated in November 2026.
