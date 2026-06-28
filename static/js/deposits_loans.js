// MODULE: LOKATY I KREDYTY

async function loadDepositsLoans() {
    try {
        const [depRes, loanRes] = await Promise.all([
            fetch(`${API_URL}/deposits/list`,  { headers: getAuthHeaders() }).then(r => r.json()),
            fetch(`${API_URL}/loans/list`,     { headers: getAuthHeaders() }).then(r => r.json())
        ]);
        const depBody  = document.getElementById('deposits-rows');
        const loanBody = document.getElementById('loans-rows');
        depBody.innerHTML = '';
        loanBody.innerHTML = '';

        if (depRes.deposits && depRes.deposits.length) {
            depRes.deposits.forEach(d => {
                const expiresAt = new Date(d.expires_at);
                const now = new Date();
                const diffMs = expiresAt - now;
                const diffMin = Math.max(0, Math.round(diffMs / 60000));
                const statusCls = d.status === 'ACTIVE' ? 'badge-info' : 'badge-success';
                depBody.innerHTML += `<tr>
                    <td><strong>${parseFloat(d.amount).toFixed(2)} PLN</strong></td>
                    <td>${parseFloat(d.interest_rate).toFixed(2)}%/h</td>
                    <td>${d.status === 'ACTIVE' ? `${diffMin} min` : 'Zakończona'}</td>
                    <td><span class="badge ${statusCls}">${d.status}</span></td>
                </tr>`;
            });
        } else { depBody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak aktywnych lokat</td></tr>'; }

        if (loanRes.loans && loanRes.loans.length) {
            loanRes.loans.forEach(l => {
                const statusCls = l.status === 'ACTIVE' ? 'badge-danger' : 'badge-success';
                loanBody.innerHTML += `<tr>
                    <td>${parseFloat(l.principal).toFixed(2)} PLN</td>
                    <td><strong style="color:var(--color-danger)">${parseFloat(l.remaining_balance).toFixed(2)} PLN</strong></td>
                    <td>${parseFloat(l.monthly_payment).toFixed(2)} PLN</td>
                    <td><span class="badge ${statusCls}">${l.status}</span></td>
                    <td>${l.status === 'ACTIVE' ? `<button class="btn-repay" onclick="repayLoan(${l.id})">Spłać ratę</button>` : '–'}</td>
                </tr>`;
            });
        } else { loanBody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak aktywnych kredytów</td></tr>'; }
    } catch(e) { console.error('Błąd lokat/kredytów:', e); }
}

document.getElementById('deposit-create-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const amount = parseFloat(document.getElementById('deposit-amount-input').value);
    try {
        const res = await fetch(`${API_URL}/deposits/create`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ amount })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); loadDepositsLoans(); loadDashboardData(); }
        else showToast(data.message || 'Błąd tworzenia lokaty.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

document.getElementById('loan-request-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const amount   = parseFloat(document.getElementById('loan-amount-input').value);
    const term_months = parseInt(document.getElementById('loan-term-input').value);
    try {
        const res = await fetch(`${API_URL}/loans/create`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ amount, term_months })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); loadDepositsLoans(); loadDashboardData(); }
        else showToast(data.message || 'Błąd wniosku o kredyt.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

async function repayLoan(loanId) {
    try {
        const res = await fetch(`${API_URL}/loans/repay`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ loan_id: loanId })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadDepositsLoans(); loadDashboardData(); }
        else showToast(data.message || 'Błąd spłaty raty.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
}

