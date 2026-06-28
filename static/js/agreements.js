// MODULE: UMOWY

async function loadAgreements() {
    try {
        const res = await fetch(`${API_URL}/agreements/list`, { headers: getAuthHeaders() });
        const data = await res.json();
        const pending = document.getElementById('agreements-pending-list');
        const signed  = document.getElementById('agreements-signed-rows');
        pending.innerHTML = '';
        signed.innerHTML  = '';
        if (data.pending && data.pending.length) {
            data.pending.forEach(a => {
                pending.innerHTML += `<div class="pending-agreement-item">
                    <h4><i class="fa-solid fa-file-contract"></i> ${a.title}</h4>
                    <p style="font-size:13px;color:var(--color-text-muted);">Wystawca: <strong>${a.party_a_name}</strong> | Kwota: <strong>${parseFloat(a.amount).toFixed(2)} PLN</strong></p>
                    <div style="display:flex;gap:10px;flex-wrap:wrap;">
                        <button class="btn btn-primary" style="font-size:12px;padding:6px 14px;" onclick="showAgreementPreview(${a.id})">Podgląd</button>
                        <button class="btn btn-success" style="font-size:12px;padding:6px 14px;" onclick="signAgreement(${a.id})">Podpisz (PIN)</button>
                    </div>
                </div>`;
            });
        } else { pending.innerHTML = '<p style="color:var(--color-text-muted)">Brak oczekujących umów.</p>'; }
        if (data.signed && data.signed.length) {
            data.signed.forEach(a => {
                const statusCls = a.status === 'SIGNED' ? 'badge-success' : 'badge-pending';
                signed.innerHTML += `<tr>
                    <td>${a.title}</td>
                    <td>${parseFloat(a.amount).toFixed(2)} PLN</td>
                    <td style="font-size:11px;">${a.party_a_name} ↔ ${a.party_b_name}</td>
                    <td><span class="badge ${statusCls}">${a.status}</span></td>
                    <td><button class="btn btn-logout" style="font-size:12px;padding:5px 10px;" onclick="showAgreementPreview(${a.id})">Podgląd</button></td>
                </tr>`;
            });
        } else { signed.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak podpisanych umów</td></tr>'; }
    } catch(e) { console.error('Błąd umów:', e); }
}

async function showAgreementPreview(agreementId) {
    try {
        const res = await fetch(`${API_URL}/agreements/${agreementId}`, { headers: getAuthHeaders() });
        const data = await res.json();
        if (!res.ok) { showToast('Nie można załadować umowy.', 'error'); return; }
        const a = data.agreement;
        const modal = document.createElement('div');
        modal.className = 'agreement-preview-modal';
        modal.innerHTML = `<div class="agreement-preview-box">
            <h2><i class="fa-solid fa-file-contract"></i> ${a.title}</h2>
            <div style="display:flex;gap:20px;flex-wrap:wrap;font-size:13px;">
                <span>Strona A: <strong>${a.party_a_name}</strong></span>
                <span>Strona B: <strong>${a.party_b_name || 'Oczekuje na podpis'}</strong></span>
                <span>Kwota: <strong>${parseFloat(a.amount).toFixed(2)} PLN</strong></span>
                <span>Status: <span class="badge ${a.status === 'SIGNED' ? 'badge-success' : 'badge-pending'}">${a.status}</span></span>
            </div>
            <pre>${a.content}</pre>
            <button class="btn btn-logout" onclick="this.closest('.agreement-preview-modal').remove()">Zamknij</button>
        </div>`;
        document.body.appendChild(modal);
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
}

async function signAgreement(agreementId) {
    const pin = prompt('Wpisz swój PIN autoryzacyjny (4 cyfry):');
    if (!pin) return;
    try {
        const res = await fetch(`${API_URL}/agreements/sign`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ agreement_id: agreementId, pin })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadAgreements(); }
        else showToast(data.message || 'Błąd podpisywania umowy.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
}

document.getElementById('agreement-create-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const recipient = document.getElementById('agreement-recipient').value.trim();
    const title     = document.getElementById('agreement-title').value.trim();
    const content   = document.getElementById('agreement-content').value.trim();
    const amount    = parseFloat(document.getElementById('agreement-amount').value) || 0;
    const pin       = document.getElementById('agreement-pin').value;
    try {
        const res = await fetch(`${API_URL}/agreements/create`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ recipient, title, content, amount, pin })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); loadAgreements(); }
        else showToast(data.message || 'Błąd tworzenia umowy.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

