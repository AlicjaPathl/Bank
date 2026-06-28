// MODULE: ZBIÓRKI

async function loadFundraisers() {
    try {
        const res = await fetch(`${API_URL}/fundraisers/list`, { headers: getAuthHeaders() });
        const data = await res.json();
        const grid = document.getElementById('fundraisers-list-grid');
        grid.innerHTML = '';
        if (data.fundraisers && data.fundraisers.length) {
            data.fundraisers.forEach(f => {
                const pct = Math.min(100, (parseFloat(f.collected) / parseFloat(f.goal_amount)) * 100).toFixed(1);
                grid.innerHTML += `<div class="fundraiser-card">
                    <div>
                        <span class="badge badge-info">${f.company_name}</span>
                        <h3 style="margin-top:8px;">${f.title}</h3>
                    </div>
                    <p style="font-size:13px;color:var(--color-text-muted);">${f.description}</p>
                    <div class="progress-bar-outer"><div class="progress-bar-inner" style="width:${pct}%"></div></div>
                    <div class="fund-amounts">
                        <span>Zebrano: <strong style="color:var(--color-success)">${parseFloat(f.collected).toFixed(2)} PLN</strong></span>
                        <span>Cel: <strong>${parseFloat(f.goal_amount).toFixed(2)} PLN</strong></span>
                    </div>
                    <button class="btn btn-primary" onclick="donateFundraiser(${f.id}, '${f.title}')">Wesprzyj zbiórkę</button>
                </div>`;
            });
        } else { grid.innerHTML = '<p style="color:var(--color-text-muted);text-align:center;padding:30px;">Brak aktywnych zbiórek.</p>'; }
        // Show create form only for companies
        if (currentUser && currentUser.is_company) {
            document.getElementById('company-fundraiser-card').style.display = 'block';
            const container = document.getElementById('fundraisers-container-card');
            container.style.gridColumn = 'span 1';
        }
    } catch(e) { console.error('Błąd zbiórek:', e); }
}

async function donateFundraiser(fundraiserId, title) {
    const amount = parseFloat(prompt(`Podaj kwotę wsparcia dla "${title}" (PLN):`));
    if (!amount || amount <= 0) return;
    try {
        const res = await fetch(`${API_URL}/fundraisers/donate`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ fundraiser_id: fundraiserId, amount })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadFundraisers(); loadDashboardData(); }
        else showToast(data.message || 'Błąd wpłaty na zbiórkę.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
}

document.getElementById('fundraiser-create-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const title       = document.getElementById('fund-title').value.trim();
    const description = document.getElementById('fund-description').value.trim();
    const goal_amount = parseFloat(document.getElementById('fund-target').value);
    try {
        const res = await fetch(`${API_URL}/fundraisers/create`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ title, description, goal_amount })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); loadFundraisers(); }
        else showToast(data.message || 'Błąd tworzenia zbiórki.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

