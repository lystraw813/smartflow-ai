from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import io
import os
import ssl
import threading
from urllib.parse import urlparse, unquote
import pymysql
from decimal import Decimal, InvalidOperation
from pypdf import PdfReader

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DATABASE = BASE / 'smartflow.db'
STORAGE = BASE / 'storage' / 'invoices'
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
USE_MYSQL = bool(DATABASE_URL)
MAX_PDF_BYTES = 10 * 1024 * 1024

app = FastAPI(title='SmartFlow AI Invoice Automation', version='0.3.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173', 'http://127.0.0.1:5173',
        'https://smartflow-ai.enzonic.dev',
    ],
    allow_methods=['GET', 'POST'], allow_headers=['*'],
)

# Keep existing SQLite behavior locally; use Enzonic MySQL when DATABASE_URL is set.
# The lightweight wrapper lets existing SQL and API handlers remain unchanged.
class DatabaseConnection:
    def __init__(self, raw, mysql):
        self.raw, self.mysql = raw, mysql

    def execute(self, sql, params=()):
        if not self.mysql:
            return self.raw.execute(sql, params)
        cursor = self.raw.cursor()
        cursor.execute(sql.replace('?', '%s'), params)
        return cursor

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def open_connection():
    if not USE_MYSQL:
        conn = sqlite3.connect(DATABASE, timeout=20)
        conn.row_factory = sqlite3.Row
        return DatabaseConnection(conn, False)
    parsed = urlparse(DATABASE_URL)
    if parsed.scheme not in ('mysql', 'mysql+pymysql'):
        raise RuntimeError('DATABASE_URL must be a MySQL connection URL')
    if not parsed.hostname or not parsed.username:
        raise RuntimeError('DATABASE_URL is missing MySQL connection information')
    # Enzonic requires TLS. Verify the server certificate and hostname.
    raw = pymysql.connect(
        host=parsed.hostname, port=parsed.port or 3306,
        user=unquote(parsed.username), password=unquote(parsed.password or ''),
        database=unquote(parsed.path.lstrip('/')),
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
        ssl=ssl.create_default_context(), connect_timeout=15,
        read_timeout=30, write_timeout=30, autocommit=False,
    )
    return DatabaseConnection(raw, True)

_schema_lock = threading.Lock()
_schema_ready = False


def initialize_schema(conn):
    if USE_MYSQL:
        conn.execute('''CREATE TABLE IF NOT EXISTS invoices (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            vendor VARCHAR(255) NOT NULL,
            number VARCHAR(255) NOT NULL,
            amount DOUBLE NOT NULL,
            due_date VARCHAR(10) NOT NULL,
            status VARCHAR(50) NOT NULL,
            document_path VARCHAR(512) NULL,
            created_at VARCHAR(40) NOT NULL,
            updated_at VARCHAR(40) NOT NULL,
            payment_status VARCHAR(20) NOT NULL DEFAULT 'Unpaid',
            paid_at VARCHAR(40) NULL,
            UNIQUE KEY uq_invoice (vendor, number)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        conn.execute('''CREATE TABLE IF NOT EXISTS audit_events (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            invoice_id BIGINT NOT NULL,
            event VARCHAR(255) NOT NULL,
            created_at VARCHAR(40) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        conn.execute('''CREATE TABLE IF NOT EXISTS invoice_documents (
            invoice_id BIGINT PRIMARY KEY,
            content LONGBLOB NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
    else:
        STORAGE.mkdir(parents=True, exist_ok=True)
        conn.execute('''CREATE TABLE IF NOT EXISTS invoices (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          vendor TEXT NOT NULL,
          number TEXT NOT NULL,
          amount REAL NOT NULL,
          due_date TEXT NOT NULL,
          status TEXT NOT NULL,
          document_path TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(vendor, number)
        )''')
        existing_columns = {row['name'] for row in conn.execute('PRAGMA table_info(invoices)')}
        if 'payment_status' not in existing_columns:
            conn.execute("ALTER TABLE invoices ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'Unpaid'")
        if 'paid_at' not in existing_columns:
            conn.execute('ALTER TABLE invoices ADD COLUMN paid_at TEXT')
        conn.execute('''CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          invoice_id INTEGER NOT NULL,
          event TEXT NOT NULL,
          created_at TEXT NOT NULL
        )''')
    conn.commit()


@contextmanager
def db():
    global _schema_ready
    conn = open_connection()
    try:
        if not _schema_ready:
            with _schema_lock:
                if not _schema_ready:
                    initialize_schema(conn)
                    _schema_ready = True
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

class Invoice(BaseModel):
    vendor: str = Field(min_length=1)
    number: str = Field(min_length=1)
    amount: float = Field(gt=0)
    due_date: date

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def folder_name(value: str):
    value = re.sub(r'[^a-zA-Z0-9 _.-]', '_', value).strip(' .')
    return (value[:70] or 'Unidentified')

def row_dict(row):
    result = dict(row)
    result['has_document'] = bool(result['document_path'])
    result.pop('document_path', None)
    return result

def get_row(conn, invoice_id):
    row = conn.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Invoice not found')
    return row

def log(conn, invoice_id, event):
    conn.execute('INSERT INTO audit_events(invoice_id,event,created_at) VALUES(?,?,?)', (invoice_id, event, timestamp()))

def insert_invoice(conn, invoice: Invoice):
    vendor = invoice.vendor.strip()
    number = invoice.number.strip()
    if not vendor or not number:
        raise HTTPException(422, 'Vendor and invoice number are required')
    existing = conn.execute('SELECT id FROM invoices WHERE lower(vendor)=lower(?) AND lower(number)=lower(?)', (vendor, number)).fetchone()
    if existing:
        raise HTTPException(409, 'Duplicate vendor and invoice number')
    now = timestamp()
    status = 'Pending Approval' if invoice.amount > 1000 else 'Ready for Review'
    try:
        cur = conn.execute('INSERT INTO invoices(vendor,number,amount,due_date,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)', (vendor, number, invoice.amount, invoice.due_date.isoformat(), status, now, now))
    except pymysql.err.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062:
            raise HTTPException(409, 'Duplicate vendor and invoice number') from exc
        raise
    log(conn, cur.lastrowid, 'Registered invoice')
    return cur.lastrowid

def extract_invoice_text(content: bytes):
    try:
        reader = PdfReader(io.BytesIO(content))
        if len(reader.pages) > 10:
            raise HTTPException(400, 'Preview supports invoices of up to 10 pages')
        return '\n'.join(page.extract_text() or '' for page in reader.pages)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, 'Could not read the PDF')


def parse_invoice_fields(text: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = {'vendor': '', 'number': '', 'amount': '', 'due_date': ''}
    warnings = []
    if not lines:
        return result, ['No selectable text found. This may be a scanned PDF; enter details manually.']

    # The first meaningful line is often the vendor; this is a suggestion, not a guarantee.
    for line in lines[:5]:
        if line.upper() not in ('INVOICE', 'TAX INVOICE', 'RECEIPT') and not re.match(r'^(invoice|date|bill to)\b', line, re.I):
            result['vendor'] = line[:100]
            break
    if not result['vendor']:
        warnings.append('Vendor could not be identified.')

    for line in lines:
        match = re.search(r'\b(?:invoice\s*(?:number|no\.?|#)|inv\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/_-]*)', line, re.I)
        if match:
            result['number'] = match.group(1)
            break
    if not result['number']:
        warnings.append('Invoice number not found.')

    for idx, line in enumerate(lines):
        match = re.search(r'\bdue\s*date\s*[:\-]?\s*(.*)$', line, re.I)
        if match:
            raw = match.group(1).strip() or (lines[idx+1] if idx+1 < len(lines) else '')
            for fmt in ('%B %d, %Y', '%b %d, %Y', '%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y'):
                try:
                    result['due_date'] = datetime.strptime(raw, fmt).date().isoformat()
                    break
                except ValueError:
                    continue
            break
    if not result['due_date']:
        warnings.append('Due date not found or not recognized.')

    # Prefer labeled grand totals, never an arbitrary amount from a line item.
    for idx, line in enumerate(lines):
        match = re.search(r'\b(?:total\s+due|amount\s+due|balance\s+due|grand\s+total|total)\b\s*[:$ ]*([0-9,]+\.[0-9]{2})\b', line, re.I)
        raw = match.group(1) if match else None
        if not raw and re.fullmatch(r'(?:TOTAL DUE|AMOUNT DUE|BALANCE DUE|GRAND TOTAL|TOTAL)\s*:?$', line, re.I):
            if idx+1 < len(lines):
                next_match = re.fullmatch(r'\$?\s*([0-9,]+\.[0-9]{2})', lines[idx+1])
                raw = next_match.group(1) if next_match else None
        if raw:
            try:
                result['amount'] = str(Decimal(raw.replace(',', '')))
                break
            except InvalidOperation:
                pass
    if not result['amount']:
        warnings.append('Invoice total not found.')
    warnings.append('Review all extracted fields against the PDF before saving. Extraction uses text patterns, not AI.')
    return result, warnings


@app.post('/invoices/extract')
async def extract_invoice(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, 'Please select a PDF invoice')
    content = await file.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, 'PDF must be 10 MB or smaller')
    if not content.startswith(b'%PDF-'):
        raise HTTPException(400, 'File does not appear to be a PDF')
    fields, warnings = parse_invoice_fields(extract_invoice_text(content))
    return {'fields': fields, 'warnings': warnings}


@app.get('/payments/calendar')
def payment_calendar():
    # The calendar is based on due dates, not the approval timestamp.
    # Problem and pending invoices must never be treated as payment obligations.
    with db() as conn:
        rows = conn.execute("SELECT * FROM invoices WHERE status='Approved' ORDER BY due_date, id").fetchall()
        return [row_dict(row) for row in rows]

@app.get('/invoices')
def list_invoices():
    with db() as conn:
        return [row_dict(row) for row in conn.execute('SELECT * FROM invoices ORDER BY id DESC')]

@app.post('/invoices')
def add_invoice(invoice: Invoice):
    with db() as conn:
        invoice_id = insert_invoice(conn, invoice)
        return row_dict(get_row(conn, invoice_id))

@app.post('/invoices/upload')
async def upload_invoice(vendor: str = Form(...), number: str = Form(...), amount: float = Form(...), due_date: date = Form(...), file: UploadFile = File(...)):
    invoice = Invoice(vendor=vendor, number=number, amount=amount, due_date=due_date)
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, 'Please upload a PDF invoice')
    content = await file.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(413, 'PDF must be 10 MB or smaller')
    if not content.startswith(b'%PDF-'):
        raise HTTPException(400, 'File does not appear to be a PDF')
    with db() as conn:
        invoice_id = insert_invoice(conn, invoice)
        if USE_MYSQL:
            conn.execute('INSERT INTO invoice_documents(invoice_id, content) VALUES(?, ?)', (invoice_id, content))
            conn.execute('UPDATE invoices SET document_path=? WHERE id=?', ('mysql', invoice_id))
            log(conn, invoice_id, 'Original PDF saved in MySQL document storage')
        else:
            folder = STORAGE / folder_name(invoice.vendor) / 'Pending'
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / f'{invoice_id}_{uuid.uuid4().hex[:10]}.pdf'
            try:
                destination.write_bytes(content)
                conn.execute('UPDATE invoices SET document_path=? WHERE id=?', (str(destination), invoice_id))
                log(conn, invoice_id, 'Original PDF saved in vendor Pending folder')
            except Exception:
                destination.unlink(missing_ok=True)
                raise
        return row_dict(get_row(conn, invoice_id))

@app.get('/invoices/{invoice_id}/document')
def view_document(invoice_id: int):
    with db() as conn:
        row = get_row(conn, invoice_id)
        if not row['document_path']:
            raise HTTPException(404, 'No PDF attached to this invoice')
        if USE_MYSQL:
            document = conn.execute('SELECT content FROM invoice_documents WHERE invoice_id=?', (invoice_id,)).fetchone()
            if not document:
                raise HTTPException(404, 'Invoice PDF not found')
            return Response(content=document['content'], media_type='application/pdf', headers={
                'Content-Disposition': f'inline; filename="invoice-{invoice_id}.pdf"',
                'Cache-Control': 'no-store',
            })
        path = Path(row['document_path'])
        if not path.is_file() or not path.resolve().is_relative_to(STORAGE.resolve()):
            raise HTTPException(404, 'Invoice PDF not found')
        return FileResponse(path, media_type='application/pdf', content_disposition_type='inline')

def transition(invoice_id: int, target: str):
    with db() as conn:
        row = get_row(conn, invoice_id)
        if row['status'] in ('Approved', 'Problem'):
            raise HTTPException(409, 'Invoice has already been finalized')
        if USE_MYSQL:
            # MySQL keeps the PDF attached to the invoice; approval changes its status.
            conn.execute('UPDATE invoices SET status=?, updated_at=? WHERE id=?',
                         (target, timestamp(), invoice_id))
            log(conn, invoice_id, 'Status changed to ' + target)
        else:
            old = Path(row['document_path']) if row['document_path'] else None
            new_path = None
            if old:
                if not old.is_file() or not old.resolve().is_relative_to(STORAGE.resolve()):
                    raise HTTPException(404, 'Original invoice document is missing')
                folder = STORAGE / folder_name(row['vendor']) / target
                folder.mkdir(parents=True, exist_ok=True)
                new_path = folder / old.name
                shutil.move(str(old), str(new_path))
            try:
                conn.execute('UPDATE invoices SET status=?, document_path=?, updated_at=? WHERE id=?',
                             (target, str(new_path) if new_path else None, timestamp(), invoice_id))
                log(conn, invoice_id, 'Status changed to ' + target)
            except Exception:
                if old and new_path and new_path.exists():
                    shutil.move(str(new_path), str(old))
                raise
        return row_dict(get_row(conn, invoice_id))

@app.post('/invoices/{invoice_id}/approve')
def approve_invoice(invoice_id: int):
    return transition(invoice_id, 'Approved')

@app.post('/invoices/{invoice_id}/reject')
def reject_invoice(invoice_id: int):
    return transition(invoice_id, 'Problem')

@app.get('/invoices/{invoice_id}/history')
def invoice_history(invoice_id: int):
    with db() as conn:
        get_row(conn, invoice_id)
        return [dict(r) for r in conn.execute('SELECT event, created_at FROM audit_events WHERE invoice_id=? ORDER BY id', (invoice_id,))]


@app.post('/invoices/{invoice_id}/mark-paid')
def mark_paid(invoice_id: int):
    with db() as conn:
        row = get_row(conn, invoice_id)
        if row['status'] != 'Approved':
            raise HTTPException(409, 'Only approved invoices can be marked paid')
        if row['payment_status'] == 'Paid':
            raise HTTPException(409, 'Invoice is already marked paid')
        now = timestamp()
        conn.execute("UPDATE invoices SET payment_status='Paid', paid_at=?, updated_at=? WHERE id=?", (now, now, invoice_id))
        log(conn, invoice_id, 'Marked paid')
        return row_dict(get_row(conn, invoice_id))

@app.post('/invoices/{invoice_id}/mark-unpaid')
def mark_unpaid(invoice_id: int):
    with db() as conn:
        row = get_row(conn, invoice_id)
        if row['status'] != 'Approved':
            raise HTTPException(409, 'Only approved invoices can change payment status')
        if row['payment_status'] != 'Paid':
            raise HTTPException(409, 'Invoice is not marked paid')
        now = timestamp()
        conn.execute("UPDATE invoices SET payment_status='Unpaid', paid_at=NULL, updated_at=? WHERE id=?", (now, invoice_id))
        log(conn, invoice_id, 'Payment status corrected to unpaid')
        return row_dict(get_row(conn, invoice_id))
