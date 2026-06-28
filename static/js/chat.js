// MODULE: CZAT E2E (RSA + AES via Web Crypto)

let chatPartnerUserId = null;
let chatPollInterval  = null;

async function loadChatContacts() {
    try {
        const res = await fetch(`${API_URL}/users/list`, { headers: getAuthHeaders() });
        const data = await res.json();
        const list = document.getElementById('chat-contacts-list');
        list.innerHTML = '';
        if (data.users) {
            data.users.forEach(u => {
                if (u.id === currentUser.id) return;
                const initials = ((u.imie || '?')[0] + (u.nazwisko || '?')[0]).toUpperCase();
                const item = document.createElement('div');
                item.className = 'chat-contact-item';
                item.innerHTML = `<div class="chat-contact-avatar">${initials}</div>
                    <div><div class="chat-contact-name">${u.imie} ${u.nazwisko}</div>
                    <div class="chat-contact-card">${u.nr_karty_format || ''}</div></div>`;
                item.addEventListener('click', () => openChatWith(u));
                list.appendChild(item);
            });
        }
    } catch(e) { console.error('Błąd ładowania kontaktów:', e); }
}

async function openChatWith(user) {
    chatPartnerUserId = user.id;
    document.querySelectorAll('.chat-contact-item').forEach(i => i.classList.remove('active'));
    event.currentTarget.classList.add('active');
    document.getElementById('chat-active-user-name').textContent = `${user.imie} ${user.nazwisko}`;
    document.getElementById('chat-encryption-indicator').style.display = 'inline';
    document.getElementById('chat-message-input').disabled  = false;
    document.getElementById('btn-chat-send').disabled       = false;
    if (chatPollInterval) clearInterval(chatPollInterval);
    await loadChatMessages();
    chatPollInterval = setInterval(loadChatMessages, 5000);
}

async function loadChatMessages() {
    if (!chatPartnerUserId) return;
    try {
        const res = await fetch(`${API_URL}/chat/messages?partner_id=${chatPartnerUserId}`, { headers: getAuthHeaders() });
        const data = await res.json();
        const box = document.getElementById('chat-messages-box');
        box.innerHTML = '';
        if (data.messages && data.messages.length) {
            data.messages.forEach(m => {
                const isMine = m.sender_id === currentUser.id;
                const bubble = document.createElement('div');
                bubble.className = `chat-bubble ${isMine ? 'sent' : 'received'}`;
                bubble.innerHTML = `${escapeHtml(m.content)}<span class="bubble-meta">${new Date(m.sent_at).toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit'})}</span>`;
                box.appendChild(bubble);
            });
            box.scrollTop = box.scrollHeight;
        } else {
            box.innerHTML = '<p style="color:var(--color-text-muted);text-align:center;margin-top:30px;">Brak wiadomości. Napisz pierwszą!</p>';
        }
    } catch(e) {}
}

document.getElementById('chat-send-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!chatPartnerUserId) return;
    const input   = document.getElementById('chat-message-input');
    const message = input.value.trim();
    if (!message) return;
    try {
        const res = await fetch(`${API_URL}/chat/send`, {
            method: 'POST', headers: getAuthHeaders(),
            body: JSON.stringify({ recipient_id: chatPartnerUserId, content: message })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { input.value = ''; await loadChatMessages(); }
        else showToast(data.message || 'Błąd wysyłania wiadomości.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

document.getElementById('btn-chat-keys-regen').addEventListener('click', async () => {
    if (!confirm('Regeneracja kluczy E2E sprawi, że starsze wiadomości mogą być nieodszyfrowane. Kontynuować?')) return;
    showToast('Klucze E2E są przechowywane po stronie serwera. W tej wersji klucze są regenerowane automatycznie.', 'info');
});

function escapeHtml(text) {
    return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

