// MODULE: GIEŁDA

let stockChartInstance = null;
let stockHistoryData = {};
let currentStockSymbol = null;

async function loadStockView() {
    try {
        const res = await fetch(`${API_URL}/stocks/list`, { headers: getAuthHeaders() });
        const data = await res.json();
        const sel = document.getElementById('stock-select');
        sel.innerHTML = '';
        if (data.stocks) {
            data.stocks.forEach(s => {
                sel.innerHTML += `<option value="${s.symbol}">${s.symbol} – ${s.name} (${parseFloat(s.current_price).toFixed(2)} PLN)</option>`;
            });
        }
        sel.addEventListener('change', () => selectStock(sel.value, data.stocks));
        if (data.stocks && data.stocks.length) selectStock(data.stocks[0].symbol, data.stocks);
        loadPortfolio();
    } catch(e) { console.error('Błąd giełdy:', e); }
}

async function selectStock(symbol, stocks) {
    currentStockSymbol = symbol;
    const stock = stocks ? stocks.find(s => s.symbol === symbol) : null;
    if (stock) {
        document.getElementById('stock-current-price-display').textContent = `${parseFloat(stock.current_price).toFixed(2)} PLN`;
        document.getElementById('stock-trade-title').textContent = `Inwestuj w ${stock.name} (${symbol})`;
    }
    try {
        const res = await fetch(`${API_URL}/stocks/history?symbol=${symbol}`, { headers: getAuthHeaders() });
        const hData = await res.json();
        drawStockChart(symbol, hData.history || []);
    } catch(e) {}
    // Recalculate cost display
    document.getElementById('stock-shares-count').dispatchEvent(new Event('input'));
}

document.getElementById('stock-shares-count').addEventListener('input', () => {
    const shares = parseInt(document.getElementById('stock-shares-count').value) || 0;
    const priceText = document.getElementById('stock-current-price-display').textContent;
    const price = parseFloat(priceText) || 0;
    document.getElementById('stock-total-cost-display').textContent = `${(shares * price).toFixed(2)} PLN`;
});

function drawStockChart(symbol, history) {
    const canvas = document.getElementById('stock-chart');
    const ctx = canvas.getContext('2d');
    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    canvas.width = w;
    canvas.height = h;
    ctx.clearRect(0, 0, w, h);
    if (!history.length) {
        ctx.fillStyle = 'rgba(255,255,255,0.2)';
        ctx.font = '16px Outfit';
        ctx.textAlign = 'center';
        ctx.fillText('Brak danych historycznych', w/2, h/2);
        return;
    }
    const prices = history.map(p => parseFloat(p.price));
    const times  = history.map(p => p.recorded_at);
    const minP = Math.min(...prices) * 0.995;
    const maxP = Math.max(...prices) * 1.005;
    const padL = 60, padR = 20, padT = 20, padB = 40;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;
    const toX = (i) => padL + (i / (prices.length - 1 || 1)) * chartW;
    const toY = (p) => padT + chartH - ((p - minP) / (maxP - minP || 1)) * chartH;

    // Grid lines
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
        const y = padT + (i / 5) * chartH;
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + chartW, y); ctx.stroke();
        const val = maxP - (i / 5) * (maxP - minP);
        ctx.fillStyle = 'rgba(255,255,255,0.3)';
        ctx.font = '10px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(val.toFixed(2), padL - 5, y + 4);
    }

    // Gradient fill
    const grad = ctx.createLinearGradient(0, padT, 0, padT + chartH);
    grad.addColorStop(0, 'rgba(0, 242, 254, 0.25)');
    grad.addColorStop(1, 'rgba(0, 242, 254, 0)');
    ctx.beginPath();
    ctx.moveTo(toX(0), padT + chartH);
    prices.forEach((p, i) => ctx.lineTo(toX(i), toY(p)));
    ctx.lineTo(toX(prices.length - 1), padT + chartH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Price line
    ctx.strokeStyle = '#00f2fe';
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    prices.forEach((p, i) => i === 0 ? ctx.moveTo(toX(i), toY(p)) : ctx.lineTo(toX(i), toY(p)));
    ctx.stroke();
}

document.getElementById('btn-stock-buy').addEventListener('click', async () => {
    const shares = parseInt(document.getElementById('stock-shares-count').value);
    if (!currentStockSymbol || !shares || shares < 1) { showToast('Wybierz akcje i podaj liczbę', 'error'); return; }
    try {
        const res = await fetch(`${API_URL}/stocks/buy`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ symbol: currentStockSymbol, shares })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadPortfolio(); loadDashboardData(); }
        else showToast(data.message || 'Błąd kupna akcji.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

document.getElementById('btn-stock-sell').addEventListener('click', async () => {
    const shares = parseInt(document.getElementById('stock-shares-count').value);
    if (!currentStockSymbol || !shares || shares < 1) { showToast('Wybierz akcje i podaj liczbę', 'error'); return; }
    try {
        const res = await fetch(`${API_URL}/stocks/sell`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ symbol: currentStockSymbol, shares })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadPortfolio(); loadDashboardData(); }
        else showToast(data.message || 'Błąd sprzedaży akcji.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

async function loadPortfolio() {
    try {
        const res = await fetch(`${API_URL}/stocks/portfolio`, { headers: getAuthHeaders() });
        const data = await res.json();
        const body = document.getElementById('stock-portfolio-rows');
        body.innerHTML = '';
        let total = 0;
        if (data.portfolio && data.portfolio.length) {
            data.portfolio.forEach(p => {
                const val = p.shares * parseFloat(p.current_price);
                const profit = val - p.shares * parseFloat(p.avg_buy_price);
                const profitCls = profit >= 0 ? 'color:var(--color-success)' : 'color:var(--color-danger)';
                total += val;
                body.innerHTML += `<tr>
                    <td><strong>${p.symbol}</strong><br><span style="font-size:11px;color:var(--color-text-muted)">${p.name}</span></td>
                    <td>${p.shares}</td>
                    <td>${parseFloat(p.avg_buy_price).toFixed(2)} PLN</td>
                    <td>${val.toFixed(2)} PLN</td>
                    <td style="${profitCls}">${profit >= 0 ? '+' : ''}${profit.toFixed(2)} PLN</td>
                </tr>`;
            });
        } else { body.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--color-text-muted);padding:20px;">Brak akcji w portfelu</td></tr>'; }
        document.getElementById('stock-portfolio-total').textContent = `${total.toFixed(2)} PLN`;
    } catch(e) {}
}

