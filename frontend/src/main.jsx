import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const API = 'http://127.0.0.1:8000';
const blank = { vendor: '', number: '', amount: '', due_date: '' };
const money = value => Number(value).toLocaleString('en-US', {style:'currency', currency:'USD'});
const todayString = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
};
const isOverdue = invoice => invoice.status === 'Approved' && invoice.payment_status !== 'Paid' && invoice.due_date < todayString();
const isDueSoon = invoice => {
  if (invoice.status !== 'Approved' || invoice.payment_status === 'Paid') return false;
  const today = new Date(`${todayString()}T12:00:00`);
  const due = new Date(`${invoice.due_date}T12:00:00`);
  const days = Math.round((due - today) / 86400000);
  return days >= 0 && days <= 7;
};
const dateLabel = iso => new Date(`${iso}T12:00:00`).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});

function App() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState(blank);
  const [pdf, setPdf] = useState(null);
  const [busy, setBusy] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractionWarnings, setExtractionWarnings] = useState([]);
  const [view, setView] = useState('Dashboard');
  const [calendarMonth, setCalendarMonth] = useState(() => new Date().getMonth());
  const [calendarYear, setCalendarYear] = useState(() => new Date().getFullYear());
  const [selectedDay, setSelectedDay] = useState(null);

  function clearForm() {
    setForm({...blank}); setPdf(null); setError(''); setNotice(''); setExtractionWarnings([]);
    const fileInput = document.getElementById('invoice-pdf');
    if (fileInput) fileInput.value = '';
  }
  const existingDuplicate = error.toLowerCase().includes('duplicate')
    ? items.find(item => item.vendor.trim().toLowerCase() === form.vendor.trim().toLowerCase()
      && item.number.trim().toLowerCase() === form.number.trim().toLowerCase())
    : null;

  async function refresh() {
    try {
      const response = await fetch(`${API}/invoices`);
      if (!response.ok) throw new Error('Unable to load invoices');
      setItems(await response.json());
    } catch (err) { setError(`Cannot connect to Python API: ${err.message}`); }
  }
  useEffect(() => { refresh(); }, []);

  async function extractDetails() {
    if (!pdf) { setError('Choose a PDF first.'); return; }
    setError(''); setNotice(''); setExtractionWarnings([]); setExtracting(true);
    try {
      const data = new FormData(); data.append('file', pdf);
      const response = await fetch(`${API}/invoices/extract`, {method:'POST', body:data});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Extraction failed');
      setForm(previous => ({...previous, ...Object.fromEntries(Object.entries(result.fields).filter(([,value]) => value !== ''))}));
      setExtractionWarnings(result.warnings || []);
      setNotice('Extraction finished. Verify the fields against the original invoice before adding it.');
    } catch (err) { setError(err.message); }
    finally { setExtracting(false); }
  }

  async function submit(e) {
    e.preventDefault(); setError(''); setNotice(''); setBusy(true);
    try {
      let response;
      if (pdf) {
        const data = new FormData();
        Object.entries(form).forEach(([key,value]) => data.append(key,value));
        data.append('file',pdf);
        response = await fetch(`${API}/invoices/upload`, {method:'POST',body:data});
      } else {
        response = await fetch(`${API}/invoices`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...form,amount:Number(form.amount)})});
      }
      if (!response.ok) {
        const details = await response.json();
        throw new Error(typeof details.detail === 'string' ? details.detail : 'Unable to register invoice');
      }
      const hadPdf = Boolean(pdf);
      clearForm(); await refresh();
      setNotice(hadPdf ? 'Invoice PDF saved in the vendor Pending folder.' : 'Invoice registered without a PDF.');
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function invoiceAction(id, action) {
    setError(''); setNotice('');
    try {
      const response = await fetch(`${API}/invoices/${id}/${action}`, {method:'POST'});
      if (!response.ok) {
        const details = await response.json();
        throw new Error(details.detail || 'Action failed');
      }
      await refresh();
      const messages = {
        approve:'Invoice approved. Its PDF has been moved to the vendor Approved folder.',
        reject:'Invoice moved to the Problem folder.',
        'mark-paid':'Payment recorded. The original PDF remains in its Approved folder.',
        'mark-unpaid':'Payment status changed back to Unpaid.'
      };
      setNotice(messages[action]);
    } catch (err) { setError(err.message); }
  }

  const approved = items.filter(i => i.status === 'Approved');
  const unpaid = approved.filter(i => i.payment_status !== 'Paid');
  const overdue = unpaid.filter(isOverdue);
  const soon = unpaid.filter(isDueSoon);
  const monthName = new Date(calendarYear,calendarMonth,1).toLocaleDateString('en-US',{month:'long',year:'numeric'});
  const daysInMonth = new Date(calendarYear,calendarMonth+1,0).getDate();
  const startWeekday = new Date(calendarYear,calendarMonth,1).getDay();
  const dayInvoices = day => approved.filter(i => i.due_date === `${calendarYear}-${String(calendarMonth+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`);
  const shownInvoices = selectedDay ? dayInvoices(selectedDay) : approved.filter(i => i.due_date.startsWith(`${calendarYear}-${String(calendarMonth+1).padStart(2,'0')}`));

  function shiftMonth(direction) {
    const d = new Date(calendarYear,calendarMonth+direction,1);
    setCalendarYear(d.getFullYear()); setCalendarMonth(d.getMonth()); setSelectedDay(null);
  }
  function documentLink(invoice) {
    return invoice.has_document ? <a href={`${API}/invoices/${invoice.id}/document`} target="_blank" rel="noopener noreferrer">View PDF</a> : <span className="muted">No PDF</span>;
  }
  function paymentBadge(invoice) {
    if (invoice.payment_status === 'Paid') return <span className="payment-tag paid">Paid</span>;
    if (isOverdue(invoice)) return <span className="payment-tag overdue">Overdue</span>;
    return <span className="payment-tag unpaid">Unpaid</span>;
  }
  function paymentAction(invoice) {
    if (invoice.payment_status === 'Paid') return <button className="secondary small-button" onClick={() => invoiceAction(invoice.id,'mark-unpaid')}>Correct to Unpaid</button>;
    return <button className="small-button" onClick={() => invoiceAction(invoice.id,'mark-paid')}>Mark as Paid</button>;
  }

  return <div className="layout">
    <aside><h2>SmartFlow AI</h2><p>Invoice Automation</p><nav aria-label="Main navigation">
      {['Dashboard','Invoices','Approvals','Payment Calendar'].map(name => <button key={name} className={`nav-item ${view === name ? 'active' : ''}`} onClick={() => {setView(name);setError('');setNotice('');}}>{name}</button>)}
    </nav><small>Automate • Validate • Approve</small></aside>
    <main>
      <header><h1>{view === 'Payment Calendar' ? 'Payment Calendar' : view === 'Dashboard' ? 'Invoice Command Center' : view}</h1><span>SmartFlow AI · Local Demo</span></header>
      <section className="stats">
        <article><label>Total invoices</label><strong>{items.length}</strong></article>
        <article><label>Approved, unpaid</label><strong>{money(unpaid.reduce((sum,i)=>sum+Number(i.amount),0))}</strong></article>
        <article><label>Overdue invoices</label><strong>{overdue.length}</strong></article>
        <article><label>Due in next 7 days</label><strong>{soon.length}</strong></article>
      </section>
      {error && <p className="error banner" role="alert">{existingDuplicate ? `Duplicate invoice: ${existingDuplicate.number} from ${existingDuplicate.vendor} already exists (${existingDuplicate.status}).` : error}{existingDuplicate?.has_document && <> <a href={`${API}/invoices/${existingDuplicate.id}/document`} target="_blank" rel="noopener noreferrer">View existing PDF</a></>}</p>}
      {notice && <p className="notice banner" role="status">{notice}</p>}

      {view === 'Dashboard' && <section className="panel">
        <h2>Register an invoice</h2>
        <p>Attach an original PDF to file it immediately under the vendor's Pending folder. Click Extract Details to prefill the form, then review all values before saving.</p>
        <form onSubmit={submit}>
          {[["vendor","Vendor"],["number","Invoice #"],["amount","Amount"],["due_date","Due date"]].map(([key,label]) => <label key={key}>{label}<input required type={key === 'amount' ? 'number' : key === 'due_date' ? 'date' : 'text'} step={key === 'amount' ? '0.01' : undefined} min={key === 'amount' ? '0.01' : undefined} value={form[key]} onChange={e => setForm({...form,[key]:e.target.value})}/></label>)}
          <label>Original invoice PDF (optional)<input id="invoice-pdf" type="file" accept="application/pdf,.pdf" onChange={e => {setPdf(e.target.files?.[0] || null);setExtractionWarnings([]);}}/></label>
          <button type="button" disabled={!pdf || extracting || busy} onClick={extractDetails}>{extracting ? 'Reading PDF...' : 'Extract Details'}</button>
          <button disabled={busy || extracting}>{busy ? 'Saving...' : 'Add invoice'}</button>
          <button className="secondary" type="button" disabled={busy || extracting} onClick={clearForm}>Clear Form</button>
        </form>
        {extractionWarnings.length > 0 && <div role="status"><strong>Extraction notes:</strong><ul>{extractionWarnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></div>}
      </section>}

      {view === 'Payment Calendar' && <section className="panel">
        <p>Approved invoices appear on their due dates. Payment tracking does not move or delete the original PDF.</p>
        <div className="calendar-toolbar"><button className="secondary" onClick={()=>shiftMonth(-1)}>Previous</button><h2>{monthName}</h2><button className="secondary" onClick={()=>shiftMonth(1)}>Next</button></div>
        <div className="calendar-grid">
          {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=><div className="calendar-weekday" key={d}>{d}</div>)}
          {Array.from({length:startWeekday},(_,i)=><div className="calendar-empty" key={`empty-${i}`}/>)}
          {Array.from({length:daysInMonth},(_,i)=>i+1).map(day=>{
            const due = dayInvoices(day);
            return <button key={day} className={`calendar-day ${selectedDay === day ? 'selected' : ''} ${due.length ? 'has-invoices' : ''}`} onClick={()=>setSelectedDay(selectedDay === day ? null : day)} aria-label={`${monthName} ${day}: ${due.length} approved invoices`}><span>{day}</span>{due.length>0 && <small>{due.length} invoice{due.length!==1?'s':''}<br/>{money(due.reduce((sum,i)=>sum+Number(i.amount),0))}</small>}</button>;
          })}
        </div>
        <h3>{selectedDay ? `Due ${monthName.split(' ')[0]} ${selectedDay}` : `All approved invoices due in ${monthName}`}</h3>
        <div className="tablewrap"><table><thead><tr><th>Invoice</th><th>Vendor</th><th>Due date</th><th>Amount</th><th>Payment</th><th>PDF</th><th>Action</th></tr></thead><tbody>
          {shownInvoices.map(i=><tr key={i.id}><td>{i.number}</td><td>{i.vendor}</td><td>{dateLabel(i.due_date)}</td><td>{money(i.amount)}</td><td>{paymentBadge(i)}</td><td>{documentLink(i)}</td><td>{paymentAction(i)}</td></tr>)}
        </tbody></table>{!shownInvoices.length && <p>No approved invoices due in this {selectedDay ? 'day' : 'month'}.</p>}</div>
      </section>}

      {view !== 'Payment Calendar' && <section className="panel"><h2>Invoice queue</h2><div className="tablewrap"><table>
        <thead><tr><th>Invoice</th><th>Vendor</th><th>Amount</th><th>Due</th><th>Approval</th><th>Payment</th><th>Document</th><th>Action</th></tr></thead>
        <tbody>{items.filter(i=>view !== 'Approvals' || !['Approved','Problem'].includes(i.status)).map(i=><tr key={i.id}>
          <td>{i.number}</td><td>{i.vendor}</td><td>{money(i.amount)}</td><td>{dateLabel(i.due_date)}</td><td><span className="status">{i.status}</span></td>
          <td>{i.status === 'Approved' ? paymentBadge(i) : <span className="muted">—</span>}</td><td>{documentLink(i)}</td>
          <td><div className="actions">{!['Approved','Problem'].includes(i.status) ? <><button onClick={()=>invoiceAction(i.id,'approve')}>Approve</button><button className="secondary" onClick={()=>invoiceAction(i.id,'reject')}>Reject</button></> : i.status === 'Approved' ? paymentAction(i) : <span className="muted">Needs review</span>}</div></td>
        </tr>)}</tbody>
      </table>{!items.length && <p>No invoices yet. Add one above.</p>}</div></section>}
    </main>
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
