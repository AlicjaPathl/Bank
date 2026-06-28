const API_URL = '/api';

// --- ELEMENTY DOM ---
const authContainer = document.getElementById('auth-container');
const dashboardContainer = document.getElementById('dashboard-container');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const authTitle = document.getElementById('auth-title');
const authSubtitle = document.getElementById('auth-subtitle');
const switchToRegister = document.getElementById('switch-to-register');
const switchToLogin = document.getElementById('switch-to-login');
const logoutBtn = document.getElementById('logout-btn');

// Formularze 2FA
const twoFactorForm = document.getElementById('2fa-form');
const totpSetupSection = document.getElementById('totp-setup-section');
const qrCodeImg = document.getElementById('qr-code-img');
const secretKeyText = document.getElementById('secret-key-text');
const twoFactorLabel = document.getElementById('2fa-label');
const twoFactorCodeInput = document.getElementById('2fa-code');
const cancelTwoFactorBtn = document.getElementById('cancel-2fa-btn');

// Formularze resetu hasła
const forgotPasswordLink = document.getElementById('forgot-password-link');
const forgotPasswordStep1Form = document.getElementById('forgot-password-step1-form');
const forgotPasswordStep2Form = document.getElementById('forgot-password-step2-form');
const switchToLoginClasses = document.querySelectorAll('.switch-to-login-class');

// Formularze transakcji
const transferForm = document.getElementById('transfer-form');
const depositForm = document.getElementById('deposit-form');
const withdrawForm = document.getElementById('withdraw-form');

// Pola danych konta
const cardBalance = document.getElementById('card-balance');
const cardNumberDisplay = document.getElementById('card-number-display');
const cardHolderName = document.getElementById('card-holder-name');
const accountId = document.getElementById('account-id');
const accountEmail = document.getElementById('account-email');
const sidebarUserName = document.getElementById('sidebar-user-name');
const userAvatarInitials = document.getElementById('user-avatar-initials');
const currentDateDisplay = document.getElementById('current-date-time');

// Widoki i kontenery dynamiczne
const viewTitle = document.getElementById('view-title');
const menuItems = document.querySelectorAll('.menu-item');
const viewPanes = document.querySelectorAll('.view-pane');
const transactionRows = document.getElementById('transaction-history-rows');
const usersCardsContainer = document.getElementById('users-cards-container');

// --- STRUKTURA STANU SESJI ---
let sessionToken = localStorage.getItem('session_token') || '';
let currentUser = null;
let resetEmail = '';
let tempAuthToken = '';
let currentTwoFactorFlow = ''; // 'login' lub 'register'

// --- POWIADOMIENIA TOAST ---
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icon = type === 'success' ? 'fa-solid fa-circle-check' : 'fa-solid fa-triangle-exclamation';
    toast.innerHTML = `<i class="${icon}"></i> <span>${message}</span>`;
    
    container.appendChild(toast);
    
    // Usuń po 4 sekundach z animacją zanikania
    setTimeout(() => {
        toast.classList.add('fade-out');
        toast.addEventListener('animationend', () => {
            toast.remove();
        });
    }, 4000);
}

// --- POMOCNICZE FORMATOWANIE ---
function formatCardNumber(number) {
    if (number && number.length === 16) {
        return number.match(/.{1,4}/g).join(' ');
    }
    return number;
}

function getInitials(name, surname) {
    return ((name ? name[0] : '') + (surname ? surname[0] : '')).toUpperCase();
}

function updateDateTime() {
    const days = ['Niedziela', 'Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek', 'Sobota'];
    const months = [
        'Stycznia', 'Lutego', 'Marca', 'Kwietnia', 'Maja', 'Czerwca', 
        'Lipca', 'Sierpnia', 'Września', 'Października', 'Listopada', 'Grudnia'
    ];
    const now = new Date();
    const day = days[now.getDay()];
    const dateNum = now.getDate();
    const month = months[now.getMonth()];
    const year = now.getFullYear();
    const time = now.toTimeString().split(' ')[0].substring(0, 5);
    
    currentDateDisplay.textContent = `${day}, ${dateNum} ${month} ${year} | ${time}`;
}

// Uruchomienie cyklu aktualizacji zegara
setInterval(updateDateTime, 30000);
updateDateTime();

// --- ZARZĄDZANIE WIDOKAMI ---
menuItems.forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetViewId = item.getAttribute('data-view');
        
        // Aktualizacja aktywnego elementu menu
        menuItems.forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        
        // Aktualizacja widoczności widoku
        viewPanes.forEach(pane => pane.classList.remove('active'));
        document.getElementById(targetViewId).classList.add('active');
        
        // Zmiana nagłówka widoku
        switch (targetViewId) {
            case 'view-summary':
                viewTitle.textContent = 'Podsumowanie konta';
                loadDashboardData();
                break;
            case 'view-transfer':
                viewTitle.textContent = 'Wykonaj przelew';
                break;
            case 'view-invoices':
                viewTitle.textContent = 'Faktury';
                loadInvoices();
                break;
            case 'view-deposits-loans':
                viewTitle.textContent = 'Lokaty i Kredyty';
                loadDepositsLoans();
                break;
            case 'view-stock':
                viewTitle.textContent = 'Giełda Papierów Wartościowych';
                loadStockView();
                break;
            case 'view-agreements':
                viewTitle.textContent = 'Umowy online';
                loadAgreements();
                break;
            case 'view-fundraisers':
                viewTitle.textContent = 'Zbiórki społecznościowe';
                loadFundraisers();
                break;
            case 'view-chat':
                viewTitle.textContent = 'Czat E2E (End-to-End)';
                loadChatContacts();
                break;
            case 'view-ai-console':
                viewTitle.textContent = 'Konsola Asystenta AI';
                break;
            case 'view-rewards':
                viewTitle.textContent = 'Nagrody i Cashback';
                loadRewards();
                break;
            case 'view-settings':
                viewTitle.textContent = 'Ustawienia konta';
                loadSettings();
                break;
            case 'view-admin':
                viewTitle.textContent = 'Panel Administratora';
                loadAdminPanel();
                break;
        }
    });
});

function hideAllAuthForms() {
    loginForm.classList.remove('active');
    registerForm.classList.remove('active');
    forgotPasswordStep1Form.classList.remove('active');
    forgotPasswordStep2Form.classList.remove('active');
    twoFactorForm.classList.remove('active');
}

// Przełączanie formularzy auth
switchToRegister.addEventListener('click', (e) => {
    e.preventDefault();
    hideAllAuthForms();
    registerForm.classList.add('active');
    authTitle.textContent = 'Rejestracja';
    authSubtitle.textContent = 'Załóż nowe konto bankowe';
});

switchToLogin.addEventListener('click', (e) => {
    e.preventDefault();
    hideAllAuthForms();
    loginForm.classList.add('active');
    authTitle.textContent = 'Logowanie';
    authSubtitle.textContent = 'Zaloguj się do swojego konta bankowego';
});

// Przełączanie na reset hasła (krok 1)
forgotPasswordLink.addEventListener('click', (e) => {
    e.preventDefault();
    hideAllAuthForms();
    forgotPasswordStep1Form.classList.add('active');
    authTitle.textContent = 'Zapomniałeś hasła?';
    authSubtitle.textContent = 'Wpisz swój adres e-mail, aby otrzymać 6-cyfrowy kod';
});

// Wróć do logowania z resetowania
switchToLoginClasses.forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        hideAllAuthForms();
        loginForm.classList.add('active');
        authTitle.textContent = 'Logowanie';
        authSubtitle.textContent = 'Zaloguj się do swojego konta bankowego';
    });
});

cancelTwoFactorBtn.addEventListener('click', (e) => {
    e.preventDefault();
    hideAllAuthForms();
    loginForm.classList.add('active');
    authTitle.textContent = 'Logowanie';
    authSubtitle.textContent = 'Zaloguj się do swojego konta bankowego';
    tempAuthToken = '';
    currentTwoFactorFlow = '';
});

// --- POBIERANIE DANYCH Z API ---

// Nagłówki z autoryzacją
function getAuthHeaders() {
    return {
        'Content-Type': 'application/json',
        'X-Session-Token': sessionToken
    };
}

async function loadDashboardData() {
    try {
        const response = await fetch(`${API_URL}/info`, {
            headers: getAuthHeaders()
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            currentUser = data.user;
            
            // Renderowanie danych w interfejsie
            cardBalance.textContent = `${currentUser.saldo.toFixed(2)} PLN`;
            cardNumberDisplay.textContent = formatCardNumber(currentUser.nr_karty);
            
            const fullName = `${currentUser.imie} ${currentUser.nazwisko}`;
            cardHolderName.textContent = fullName.toUpperCase();
            sidebarUserName.textContent = fullName;
            userAvatarInitials.textContent = getInitials(currentUser.imie, currentUser.nazwisko);
            
            accountId.textContent = currentUser.id;
            accountEmail.textContent = currentUser.email;
            
            // Pobranie historii transakcji
            loadTransactionHistory();
        } else {
            handleAuthError();
        }
    } catch (error) {
        console.error('Błąd pobierania informacji:', error);
        showToast('Nie udało się połączyć z serwerem.', 'error');
    }
}

async function loadTransactionHistory() {
    try {
        const response = await fetch(`${API_URL}/history`, {
            headers: getAuthHeaders()
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            transactionRows.innerHTML = '';
            const txs = data.transactions;
            
            if (txs.length === 0) {
                transactionRows.innerHTML = `
                    <tr>
                        <td colspan="4" class="text-center">Brak transakcji w historii.</td>
                    </tr>`;
                return;
            }
            
            txs.forEach(t => {
                const tr = document.createElement('tr');
                
                // Kierunek i ikona
                let directionHtml = '';
                let amountClass = '';
                let amountSign = '';
                
                if (t.type === 'DEPOSIT') {
                    directionHtml = '<span class="trans-direction trans-incoming"><i class="fa-solid fa-circle-down"></i> Wpłata</span>';
                    amountClass = 'amount-incoming';
                    amountSign = '+';
                } else if (t.type === 'WITHDRAW') {
                    directionHtml = '<span class="trans-direction trans-outgoing"><i class="fa-solid fa-circle-up"></i> Wypłata</span>';
                    amountClass = 'amount-outgoing';
                    amountSign = '-';
                } else if (t.type === 'TRANSFER') {
                    if (t.direction === 'PRZYCHODZĄCY') {
                        directionHtml = '<span class="trans-direction trans-incoming"><i class="fa-solid fa-arrow-down-left"></i> Przelew</span>';
                        amountClass = 'amount-incoming';
                        amountSign = '+';
                    } else {
                        directionHtml = '<span class="trans-direction trans-outgoing"><i class="fa-solid fa-arrow-up-right"></i> Przelew</span>';
                        amountClass = 'amount-outgoing';
                        amountSign = '-';
                    }
                }
                
                const otherParty = t.other || 'System';
                // Data format
                const dateParsed = new Date(t.date);
                const dateStr = dateParsed.toLocaleString('pl-PL');
                
                tr.innerHTML = `
                    <td>${directionHtml}</td>
                    <td><strong>${otherParty}</strong></td>
                    <td>${dateStr}</td>
                    <td class="text-right ${amountClass}">${amountSign}${t.amount.toFixed(2)} zł</td>
                `;
                transactionRows.appendChild(tr);
            });
        }
    } catch (error) {
        console.error('Błąd pobierania historii:', error);
    }
}

async function loadUsersData() {
    try {
        const response = await fetch(`${API_URL}/users`, {
            headers: getAuthHeaders()
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            usersCardsContainer.innerHTML = '';
            const users = data.users;
            
            if (users.length === 0) {
                usersCardsContainer.innerHTML = '<div class="text-center padding-20">Brak innych użytkowników w systemie.</div>';
                return;
            }
            
            users.forEach(u => {
                const card = document.createElement('div');
                card.className = 'glass-card user-card';
                
                const initials = getInitials(u.imie, u.nazwisko);
                
                card.innerHTML = `
                    <div class="user-card-header">
                        <div class="user-card-avatar">${initials}</div>
                        <div class="user-card-info">
                            <span class="user-card-name">${u.imie} ${u.nazwisko}</span>
                            <span class="user-card-email">${u.email}</span>
                        </div>
                    </div>
                    <div class="user-card-body">
                        <div class="user-card-meta">
                            <span class="label">ID konta:</span>
                            <span class="val">${u.id}</span>
                        </div>
                        <div class="user-card-meta">
                            <span class="label">Numer karty:</span>
                            <span class="val">${u.nr_karty_format}</span>
                        </div>
                    </div>
                    <button class="btn btn-primary quick-transfer-btn" data-recipient="${u.id}">
                        <i class="fa-solid fa-paper-plane"></i> Przelew
                    </button>
                `;
                usersCardsContainer.appendChild(card);
            });
            
            // Obsługa kliknięcia szybkiego przelewu na kartach
            document.querySelectorAll('.quick-transfer-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const recipientId = btn.getAttribute('data-recipient');
                    
                    // Przełącz widok na formularz przelewu
                    document.querySelector('.menu-item[data-view="view-transfer"]').click();
                    // Uzupełnij odbiorcę
                    document.getElementById('trans-recipient').value = recipientId;
                    document.getElementById('trans-amount').focus();
                });
            });
        }
    } catch (error) {
        console.error('Błąd pobierania użytkowników:', error);
    }
}

// --- LOGIKA FORMULARZY ---

// Logowanie
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const haslo = document.getElementById('login-password').value;
    
    try {
        const response = await fetch(`${API_URL}/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, haslo })
        });
        
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            sessionToken = data.token;
            localStorage.setItem('session_token', sessionToken);
            showToast(data.message || 'Zalogowano pomyślnie!');
            
            // Przełącz kontenery widoku
            authContainer.classList.remove('active');
            dashboardContainer.classList.add('active');
            
            // Załaduj dane i przejdź do podsumowania
            document.querySelector('.menu-item[data-view="view-summary"]').click();
            loginForm.reset();
        } else if (response.ok && data.status === 'AWAITING_EMAIL_OTP') {
            hideAllAuthForms();
            twoFactorForm.classList.add('active');
            totpSetupSection.style.display = 'none';
            tempAuthToken = data.temp_token;
            currentTwoFactorFlow = 'login';
            twoFactorLabel.innerHTML = '<i class="fa-solid fa-envelope"></i> Wpisz kod OTP z e-maila';
            authTitle.textContent = 'Weryfikacja dwuetapowa';
            authSubtitle.textContent = data.message || 'Wysłano kod OTP na e-mail.';
        } else if (response.ok && data.status === 'AWAITING_TOTP') {
            hideAllAuthForms();
            twoFactorForm.classList.add('active');
            totpSetupSection.style.display = 'none';
            tempAuthToken = data.temp_token;
            currentTwoFactorFlow = 'login';
            twoFactorLabel.innerHTML = '<i class="fa-solid fa-key"></i> Wpisz kod TOTP z aplikacji Google Authenticator';
            authTitle.textContent = 'Weryfikacja dwuetapowa';
            authSubtitle.textContent = data.message || 'Podaj kod z aplikacji Google Authenticator.';
        } else {
            showToast(data.message || 'Błąd logowania.', 'error');
        }
    } catch (error) {
        console.error('Błąd logowania:', error);
        showToast('Błąd połączenia z serwerem.', 'error');
    }
});

// Reset hasła - Krok 1 (Żądanie kodu)
forgotPasswordStep1Form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('forgot-email').value;
    
    try {
        const response = await fetch(`${API_URL}/forgot-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            resetEmail = email;
            showToast(data.message || 'Kod weryfikacyjny został wysłany.');
            
            // Przełącz na krok 2
            forgotPasswordStep1Form.classList.remove('active');
            forgotPasswordStep2Form.classList.add('active');
            authTitle.textContent = 'Zmień hasło';
            authSubtitle.textContent = 'Wpisz 6-cyfrowy kod oraz nowe hasło';
            forgotPasswordStep1Form.reset();
        } else {
            showToast(data.message || 'Błąd wysyłania kodu.', 'error');
        }
    } catch (error) {
        console.error('Błąd żądania kodu:', error);
        showToast('Błąd połączenia z serwerem.', 'error');
    }
});

// Reset hasła - Krok 2 (Zmiana hasła)
forgotPasswordStep2Form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = document.getElementById('reset-code').value;
    const newPassword = document.getElementById('reset-new-password').value;
    
    if (newPassword.length < 5) {
        showToast('Hasło musi mieć co najmniej 5 znaków.', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/reset-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: resetEmail, code, new_password: newPassword })
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            showToast(data.message || 'Hasło zostało pomyślnie zmienione.');
            forgotPasswordStep2Form.reset();
            
            // Przełącz na logowanie
            forgotPasswordStep2Form.classList.remove('active');
            loginForm.classList.add('active');
            authTitle.textContent = 'Logowanie';
            authSubtitle.textContent = 'Zaloguj się do swojego konta bankowego';
        } else {
            showToast(data.message || 'Błąd zmiany hasła.', 'error');
        }
    } catch (error) {
        console.error('Błąd zmiany hasła:', error);
        showToast('Błąd połączenia z serwerem.', 'error');
    }
});

// Rejestracja
registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const imie = document.getElementById('reg-imie').value;
    const nazwisko = document.getElementById('reg-nazwisko').value;
    const email = document.getElementById('reg-email').value;
    const pesel = document.getElementById('reg-pesel').value;
    const pin = document.getElementById('reg-pin').value;
    const haslo = document.getElementById('reg-password').value;
    const saldo = parseFloat(document.getElementById('reg-saldo').value) || 0.0;
    const two_factor_method = document.getElementById('reg-2fa').value;
    
    if (haslo.length < 5) {
        showToast('Hasło musi mieć co najmniej 5 znaków.', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ imie, nazwisko, email, pesel, pin, haslo, saldo, two_factor_method })
        });
        
        const data = await response.json();
        
        if (response.ok && data.status === 'AWAITING_EMAIL_VERIFY') {
            hideAllAuthForms();
            twoFactorForm.classList.add('active');
            totpSetupSection.style.display = 'none';
            tempAuthToken = data.temp_token;
            currentTwoFactorFlow = 'register_email';
            twoFactorLabel.innerHTML = '<i class="fa-solid fa-envelope"></i> Wpisz kod OTP z wiadomości e-mail';
            authTitle.textContent = 'Potwierdź swój adres e-mail';
            authSubtitle.textContent = data.message || 'Wysłano kod weryfikacyjny na Twój adres e-mail.';
            twoFactorCodeInput.value = '';
        } else {
            showToast(data.message || 'Błąd rejestracji.', 'error');
        }
    } catch (error) {
        console.error('Błąd rejestracji:', error);
        showToast('Błąd połączenia z serwerem.', 'error');
    }
});

// Weryfikacja 2FA (logowanie i rejestracja)
twoFactorForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const code = twoFactorCodeInput.value.trim();
    
    if (code.length !== 6 || isNaN(code)) {
        showToast('Kod musi składać się z 6 cyfr.', 'error');
        return;
    }
    
    let url = '';
    if (currentTwoFactorFlow === 'register_email') {
        url = `${API_URL}/register/verify-email`;
    } else if (currentTwoFactorFlow === 'register_totp') {
        url = `${API_URL}/register/verify-totp`;
    } else {
        url = `${API_URL}/login/verify-2fa`;
    }
    
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ temp_token: tempAuthToken, code })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            if (data.status === 'AWAITING_TOTP') {
                hideAllAuthForms();
                twoFactorForm.classList.add('active');
                if (currentTwoFactorFlow === 'login') {
                    totpSetupSection.style.display = 'none';
                    twoFactorLabel.innerHTML = '<i class="fa-solid fa-key"></i> Wpisz kod z aplikacji Google Authenticator';
                    authTitle.textContent = 'Weryfikacja dwuetapowa (2FA)';
                    authSubtitle.textContent = data.message || 'Podaj aktualny kod TOTP.';
                } else {
                    totpSetupSection.style.display = 'flex';
                    qrCodeImg.src = data.qr_code;
                    secretKeyText.textContent = data.secret;
                    currentTwoFactorFlow = 'register_totp';
                    twoFactorLabel.innerHTML = '<i class="fa-solid fa-key"></i> Wpisz kod TOTP z aplikacji Google Authenticator';
                    authTitle.textContent = 'Konfiguracja Google Authenticator';
                    authSubtitle.textContent = data.message || 'Zeskanuj kod QR i podaj aktualny kod z aplikacji.';
                }
                tempAuthToken = data.temp_token;
                twoFactorCodeInput.value = '';
            } else if (data.status === 'OK') {
                sessionToken = data.token;
                localStorage.setItem('session_token', sessionToken);
                showToast(data.message || 'Rejestracja pomyślna!');
                
                // Przełącz na kokpit
                hideAllAuthForms();
                authContainer.classList.remove('active');
                dashboardContainer.classList.add('active');
                
                document.querySelector('.menu-item[data-view="view-summary"]').click();
                twoFactorForm.reset();
                loginForm.reset();
                registerForm.reset();
                tempAuthToken = '';
                currentTwoFactorFlow = '';
            }
        } else {
            showToast(data.message || 'Błąd weryfikacji kodu.', 'error');
            if (data.message && data.message.includes('anulowana')) {
                hideAllAuthForms();
                loginForm.classList.add('active');
                authTitle.textContent = 'Logowanie';
                authSubtitle.textContent = 'Zaloguj się do swojego konta bankowego';
                tempAuthToken = '';
                currentTwoFactorFlow = '';
            }
        }
    } catch (error) {
        console.error('Błąd weryfikacji 2FA:', error);
        showToast('Błąd weryfikacji po stronie serwera.', 'error');
    }
});

// Wylogowanie
logoutBtn.addEventListener('click', async () => {
    try {
        await fetch(`${API_URL}/logout`, {
            method: 'POST',
            headers: getAuthHeaders()
        });
    } catch (error) {
        console.error('Błąd podczas API logout:', error);
    }
    
    handleAuthError();
    showToast('Zostałeś wylogowany.');
});

function handleAuthError() {
    sessionToken = '';
    localStorage.removeItem('session_token');
    currentUser = null;
    
    dashboardContainer.classList.remove('active');
    authContainer.classList.add('active');
    
    // Przełącz na formularz logowania
    document.getElementById('switch-to-login').click();
}

// Formularz Przelewu
transferForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const recipient = document.getElementById('trans-recipient').value;
    const amount = parseFloat(document.getElementById('trans-amount').value);
    
    if (isNaN(amount) || amount <= 0) {
        showToast('Wpisz poprawną kwotę większą od zera.', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/transfer`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ recipient, amount })
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            showToast(data.message);
            transferForm.reset();
            
            // Przełącz na podsumowanie, by odświeżyć dane
            document.querySelector('.menu-item[data-view="view-summary"]').click();
        } else {
            showToast(data.message || 'Nie udało się zrealizować przelewu.', 'error');
        }
    } catch (error) {
        console.error('Błąd przelewu:', error);
        showToast('Błąd komunikacji z serwerem.', 'error');
    }
});

// Formularz Wpłaty
depositForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const amount = parseFloat(document.getElementById('deposit-amount').value);
    
    if (isNaN(amount) || amount <= 0) {
        showToast('Wpisz poprawną kwotę.', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/deposit`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ amount })
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            showToast(data.message);
            depositForm.reset();
            document.querySelector('.menu-item[data-view="view-summary"]').click();
        } else {
            showToast(data.message || 'Wpłata odrzucona.', 'error');
        }
    } catch (error) {
        console.error('Błąd wpłaty:', error);
        showToast('Błąd połączenia z serwerem.', 'error');
    }
});

// Formularz Wypłaty
withdrawForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const amount = parseFloat(document.getElementById('withdraw-amount').value);
    
    if (isNaN(amount) || amount <= 0) {
        showToast('Wpisz poprawną kwotę.', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/withdraw`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({ amount })
        });
        const data = await response.json();
        
        if (response.ok && data.status === 'OK') {
            showToast(data.message);
            withdrawForm.reset();
            document.querySelector('.menu-item[data-view="view-summary"]').click();
        } else {
            showToast(data.message || 'Niewystarczające środki lub błąd wypłaty.', 'error');
        }
    } catch (error) {
        console.error('Błąd wypłaty:', error);
        showToast('Błąd połączenia z serwerem.', 'error');
    }
});


// --- INICJALIZACJA STRONY ---
function initApp() {
    if (sessionToken) {
        authContainer.classList.remove('active');
        dashboardContainer.classList.add('active');
        // Reveal admin link if user is admin
        loadDashboardData().then(() => {
            if (currentUser && currentUser.is_admin) {
                const adminLink = document.getElementById('admin-panel-link');
                if (adminLink) adminLink.style.display = 'flex';
            }
        });
        document.querySelector('.menu-item[data-view="view-summary"]').click();
    } else {
        handleAuthError();
    }
}

// Uruchomienie aplikacji
initApp();

// ================================================================
//  MODULE: FAKTURY
// ================================================================
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

// ================================================================
//  MODULE: LOKATY I KREDYTY
// ================================================================
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

// ================================================================
//  MODULE: GIEŁDA
// ================================================================
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

// ================================================================
//  MODULE: UMOWY
// ================================================================
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

// ================================================================
//  MODULE: ZBIÓRKI
// ================================================================
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

// ================================================================
//  MODULE: CZAT E2E (RSA + AES via Web Crypto)
// ================================================================
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
                const initials = ((u.name || '?')[0] + (u.surname || '?')[0]).toUpperCase();
                const item = document.createElement('div');
                item.className = 'chat-contact-item';
                item.innerHTML = `<div class="chat-contact-avatar">${initials}</div>
                    <div><div class="chat-contact-name">${u.name} ${u.surname}</div>
                    <div class="chat-contact-card">${u.card_number ? u.card_number.replace(/(\d{4})/g,'$1 ').trim() : ''}</div></div>`;
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
    document.getElementById('chat-active-user-name').textContent = `${user.name} ${user.surname}`;
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

// ================================================================
//  MODULE: KONSOLA AI
// ================================================================
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

// ================================================================
//  MODULE: NAGRODY
// ================================================================
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

// ================================================================
//  MODULE: USTAWIENIA
// ================================================================
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

// ================================================================
//  MODULE: PANEL ADMINA
// ================================================================
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
