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
            case 'view-users':
                viewTitle.textContent = 'Użytkownicy banku';
                loadUsersData();
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

// Wyszukiwanie użytkowników na żywo
document.getElementById('users-search-input')?.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    document.querySelectorAll('#users-cards-container .user-card').forEach(card => {
        const name = card.querySelector('.user-card-name')?.textContent.toLowerCase() || '';
        const email = card.querySelector('.user-card-email')?.textContent.toLowerCase() || '';
        if (name.includes(query) || email.includes(query)) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
});

