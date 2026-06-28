// MODULE: KONSOLA AI

const aiConsoleWindow = document.getElementById('ai-console-window');
const aiConsoleForm   = document.getElementById('ai-console-form');
const aiConsoleInput  = document.getElementById('ai-console-input');

function aiLog(text, cls = '') {
    const line = document.createElement('div');
    line.style.cssText = cls;
    line.textContent = text;
    aiConsoleWindow.appendChild(line);
    aiConsoleWindow.scrollTop = aiConsoleWindow.scrollHeight;
}

aiConsoleForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const cmd = aiConsoleInput.value.trim();
    if (!cmd) return;
    aiLog(`$ ${cmd}`, 'color: #aaffaa; font-weight: bold;');
    aiConsoleInput.value = '';
    try {
        const res = await fetch(`${API_URL}/ai/chat`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ message: cmd })
        });
        const data = await res.json();
        if (res.ok && data.reply) {
            aiLog(`[AI]: ${data.reply}`);
            if (data.action_result) aiLog(`[SYSTEM]: ${data.action_result}`, 'color: #ffff88;');
        } else aiLog(`[BŁĄD]: ${data.message || 'Brak odpowiedzi'}`, 'color: #ff6666;');
    } catch(err) { aiLog('[BŁĄD]: Brak połączenia z serwerem.', 'color: #ff6666;'); }
});

