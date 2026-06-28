// MODULE: NAGRODY

async function loadRewards() {
    try {
        const res = await fetch(`${API_URL}/rewards`, { headers: getAuthHeaders() });
        const data = await res.json();
        if (data.points !== undefined) {
            document.getElementById('rewards-points-balance').textContent = `${data.points} pkt`;
        }
    } catch(e) {}
}

document.querySelectorAll('.btn-exchange').forEach(btn => {
    btn.addEventListener('click', async () => {
        const points = parseInt(btn.dataset.option);
        if (!confirm(`Wymienić ${points} pkt na cashback PLN?`)) return;
        try {
            const res = await fetch(`${API_URL}/rewards/exchange`, {
                method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ points })
            });
            const data = await res.json();
            if (res.ok && data.status === 'OK') { showToast(data.message); loadRewards(); loadDashboardData(); }
            else showToast(data.message || 'Błąd wymiany punktów.', 'error');
        } catch(e) { showToast('Błąd połączenia.', 'error'); }
    });
});

