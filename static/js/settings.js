// MODULE: USTAWIENIA

async function loadSettings() {
    try {
        const res = await fetch(`${API_URL}/profile`, { headers: getAuthHeaders() });
        const data = await res.json();
        if (data.user) {
            const method = data.user.two_factor_method || 'NONE';
            document.querySelectorAll('input[name="settings-2fa-radio"]').forEach(r => {
                r.checked = (r.value === method);
            });
            if (data.user.is_company) {
                document.getElementById('settings-company-reg-card').innerHTML = `
                    <h2>Zarejestrowana firma</h2>
                    <p class="subtitle">Twoje konto ma zarejestrowaną firmę.</p>
                    <div style="display:flex;flex-direction:column;gap:10px;margin-top:15px;font-size:14px;">
                        <div><span style="color:var(--color-text-muted)">Nazwa:</span> <strong>${data.user.company_name || '–'}</strong></div>
                        <div><span style="color:var(--color-text-muted)">NIP:</span> <strong>${data.user.company_nip || '–'}</strong></div>
                        <div><span style="color:var(--color-text-muted)">REGON:</span> <strong>${data.user.company_regon || '–'}</strong></div>
                    </div>`;
            }
        }
    } catch(e) {}
}

document.getElementById('settings-password-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const old_password = document.getElementById('settings-old-password').value;
    const new_password = document.getElementById('settings-new-password').value;
    if (new_password.length < 5) { showToast('Nowe hasło musi mieć min. 5 znaków.', 'error'); return; }
    try {
        const res = await fetch(`${API_URL}/settings/change-password`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ old_password, new_password })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); e.target.reset(); }
        else showToast(data.message || 'Błąd zmiany hasła.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

document.querySelectorAll('input[name="settings-2fa-radio"]').forEach(r => {
    r.addEventListener('change', (e) => {
        const section = document.getElementById('settings-totp-setup-section');
        const codeInput = document.getElementById('settings-totp-code');
        if (section) section.style.display = 'none';
        if (codeInput) codeInput.value = '';
    });
});

document.getElementById('settings-2fa-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const method = document.querySelector('input[name="settings-2fa-radio"]:checked')?.value || 'NONE';
    const codeInput = document.getElementById('settings-totp-code');
    const code = codeInput ? codeInput.value : '';

    if (method === 'TOTP' && document.getElementById('settings-totp-setup-section').style.display === 'flex' && !code) {
        showToast('Wpisz kod z aplikacji TOTP, aby potwierdzić.', 'error');
        return;
    }

    try {
        const res = await fetch(`${API_URL}/settings/2fa`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ method, code })
        });
        const data = await res.json();
        if (res.ok) {
            if (data.status === 'REQUIRE_VERIFICATION') {
                const section = document.getElementById('settings-totp-setup-section');
                if (section) {
                    section.style.display = 'flex';
                    document.getElementById('settings-qr-code-img').src = data.qr_code;
                    document.getElementById('settings-secret-key-text').textContent = data.secret;
                }
                showToast(data.message || 'Zeskanuj kod QR i podaj kod TOTP.');
            } else if (data.status === 'OK') {
                const section = document.getElementById('settings-totp-setup-section');
                if (section) section.style.display = 'none';
                if (codeInput) codeInput.value = '';
                showToast(data.message || 'Ustawienia 2FA zapisane.');
            } else {
                showToast(data.message || 'Błąd zapisu 2FA.', 'error');
            }
        } else {
            showToast(data.message || 'Błąd zapisu 2FA.', 'error');
        }
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

document.getElementById('settings-company-form') && document.getElementById('settings-company-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name   = document.getElementById('company-name-input').value.trim();
    const nip    = document.getElementById('company-nip-input').value.trim();
    const regon  = document.getElementById('company-regon-input').value.trim();
    try {
        const res = await fetch(`${API_URL}/settings/register-company`, {
            method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ name, nip, regon })
        });
        const data = await res.json();
        if (res.ok && data.status === 'OK') { showToast(data.message); loadSettings(); }
        else showToast(data.message || 'Błąd rejestracji firmy.', 'error');
    } catch(e) { showToast('Błąd połączenia.', 'error'); }
});

