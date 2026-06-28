// MODULE: PANEL ADMINA

async function loadAdminPanel() {
    try {
        const res = await fetch(`${API_URL}/admin/stats`, { headers: getAuthHeaders() });
        const data = await res.json();
        if (res.status === 403) { showToast('Brak uprawnień administratora.', 'error'); return; }
        if (data.stats) {
            document.getElementById('admin-stat-total-balance').textContent  = `${parseFloat(data.stats.total_balance || 0).toFixed(2)} PLN`;
            document.getElementById('admin-stat-total-deposits').textContent = `${parseFloat(data.stats.total_deposits || 0).toFixed(2)} PLN`;
            document.getElementById('admin-stat-total-loans').textContent    = `${parseFloat(data.stats.total_loans || 0).toFixed(2)} PLN`;
            document.getElementById('admin-stat-users-count').textContent    = `${data.stats.total_users || 0} / ${data.stats.total_companies || 0}`;
        }
        if (data.settings) {
            document.getElementById('admin-inflation-input').value = data.settings.inflation_rate;
            document.getElementById('admin-interest-input').value  = data.settings.interest_rate;
        }
        loadAdminUsersTable(data.users || []);
    } catch(e) { console.error('Błąd panelu admina:', e); }
}

function loadAdminUsersTable(users) {
    const body = document.getElementById('admin-users-rows');
    body.innerHTML = '';
    users.forEach(u => {
        const roleCls = u.is_admin ? 'badge-danger' : (u.is_company ? 'badge-info' : 'badge-success');
        const roleLabel = u.is_admin ? 'Admin' : (u.is_company ? 'Firma' : 'Klient');
        body.innerHTML += `<tr>
            <td><strong>${u.name} ${u.surname}</strong><br><span style="font-size:11px;color:var(--color-text-muted)">${u.email}</span></td>
            <td>${parseFloat(u.saldo || 0).toFixed(2)} PLN</td>
            <td><span class="badge ${roleCls}">${roleLabel}</span></td>
        </tr>`;
    });
    if (!users.length) body.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak użytkowników</td></tr>';
}

// Filtr wyszukiwania admina
document.getElementById('admin-search-users').addEventListener('input', async (e) => {
    const q = e.target.value.toLowerCase().trim();
    if (!q) { loadAdminPanel(); return; }
    try {
        const res  = await fetch(`${API_URL}/admin/users`, { headers: getAuthHeaders() });
        const data = await res.json();
        const filtered = (data.users || []).filter(u =>
            `${u.name} ${u.surname} ${u.email}`.toLowerCase().includes(q)
        );
        loadAdminUsersTable(filtered);
    } catch(e) {}
});

document.getElementById('admin-settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inflation_rate = parseFloat(document.getElementById('admin-inflation-input').value);
    const interest_rate  = parseFloat(document.getElementById('admin-interest-input').value);
    try {
        const res = await fetch(`${API_URL}/admin/settings`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ inflation_rate, interest_rate })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') showToast(data.message || 'Parametry zaktualizowane.');
        else showToast(data.message || 'Błąd zapisu parametrów.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

document.getElementById('admin-give-money-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const recipient = document.getElementById('admin-recipient-input').value.trim();
    const amount    = parseFloat(document.getElementById('admin-amount-input').value);
    try {
        const res = await fetch(`${API_URL}/admin/give-money`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ recipient, amount })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); loadAdminPanel(); }
        else showToast(data.message || 'Błąd zasilenia konta.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});
