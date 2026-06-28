// MODULE: FAKTURY

async function loadInvoices() {
    try {
        const [recv, sent] = await Promise.all([
            fetch(`${API_URL}/invoices/received`, { headers: getAuthHeaders() }).then(r => r.json()),
            fetch(`${API_URL}/invoices/sent`,     { headers: getAuthHeaders() }).then(r => r.json())
        ]);
        const recvBody = document.getElementById('invoices-received-rows');
        const sentBody = document.getElementById('invoices-sent-rows');
        recvBody.innerHTML = '';
        sentBody.innerHTML = '';
        if (recv.invoices && recv.invoices.length) {
            recv.invoices.forEach(inv => {
                const statusCls = inv.status === 'PAID' ? 'badge-success' : 'badge-pending';
                recvBody.innerHTML += `<tr>
                    <td>${inv.issuer_name}</td>
                    <td>${inv.title}</td>
                    <td><strong>${parseFloat(inv.amount).toFixed(2)} PLN</strong></td>
                    <td><span class="badge ${statusCls}">${inv.status}</span></td>
                    <td>${inv.status === 'PENDING' ? `<button class="btn btn-primary" style="font-size:12px;padding:5px 10px;" onclick="payInvoice(${inv.id})">Opłać</button>` : '–'}</td>
                </tr>`;
            });
        } else { recvBody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak faktur przychodzących</td></tr>'; }
        if (sent.invoices && sent.invoices.length) {
            sent.invoices.forEach(inv => {
                const statusCls = inv.status === 'PAID' ? 'badge-success' : 'badge-pending';
                sentBody.innerHTML += `<tr>
                    <td>${inv.recipient_name}</td>
                    <td>${inv.title}</td>
                    <td><strong>${parseFloat(inv.amount).toFixed(2)} PLN</strong></td>
                    <td><span class="badge ${statusCls}">${inv.status}</span></td>
                </tr>`;
            });
        } else { sentBody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak wystawionych faktur</td></tr>'; }
    } catch(e) { console.error('Błąd faktur:', e); }
}

async function payInvoice(invoiceId) {
    if (!confirm('Czy na pewno chcesz opłacić tę fakturę?')) return;
    try {
        const res = await fetch(`${API_URL}/invoices/pay`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ invoice_id: invoiceId })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadInvoices(); loadDashboardData(); }
        else showToast(data.message || 'Błąd płatności faktury.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
}

document.getElementById('invoice-issue-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const recipient = document.getElementById('invoice-recipient').value.trim();
    const amount = parseFloat(document.getElementById('invoice-amount').value);
    const title = document.getElementById('invoice-title').value.trim();
    try {
        const res = await fetch(`${API_URL}/invoices/create`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ recipient, amount, title })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); loadInvoices(); }
        else showToast(data.message || 'Błąd wystawiania faktury.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

