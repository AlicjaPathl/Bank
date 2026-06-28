import os
import sys
import uuid
import logging
import threading
import smtplib
import random
import string
import base64
import io
import pyotp
import qrcode
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from dotenv import load_dotenv

# Wczytywanie konfiguracji z pliku .env
load_dotenv()

# Dodajemy katalog bieżący do ścieżki Pythona na wypadek importów
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server import Server, User, hash_password, verify_password, logger

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)  # Włączamy CORS na wypadek pracy z zewnętrznych domen

# Konfiguracja SMTP ze zmiennych środowiskowych
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")

import json

# Słownik sesji webowych: token -> user_id
WEB_SESSIONS = {}
web_session_lock = threading.Lock()

SESSIONS_FILE = "web_sessions.json"

def load_sessions():
    global WEB_SESSIONS
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r") as f:
                WEB_SESSIONS = json.load(f)
    except Exception as e:
        logger.error(f"Błąd ładowania sesji: {e}")

def save_sessions():
    try:
        with open(SESSIONS_FILE, "w") as f:
            json.dump(WEB_SESSIONS, f)
    except Exception as e:
        logger.error(f"Błąd zapisu sesji: {e}")

load_sessions()

# Słownik kodów resetu hasła: email -> {"code": "123456", "expires_at": datetime}
RESET_CODES = {}
reset_codes_lock = threading.Lock()

# Słownik dla tymczasowych rejestracji: temp_token -> {user_obj, secret, attempts}
TEMP_REGISTRATIONS = {}
temp_reg_lock = threading.Lock()

# Słownik dla tymczasowych sesji autoryzacyjnych logowania: temp_token -> {user_id, email, type, attempts}
TEMP_AUTH_SESSIONS = {}
temp_auth_lock = threading.Lock()


class WebBankServer(Server):
    def __init__(self, user_class):
        self.User = user_class
        # Używamy wątkowo-lokalnego połączenia bazy danych (odziedziczone z Server)
        self.thread_local = threading.local()
        self.running = True
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.znane = {}
        self.migrate_db()
        # Start background ticking services
        self.start_background_services()

    def start_background_services(self):
        # Stock simulation thread
        t1 = threading.Thread(target=self._stock_simulation_loop, daemon=True)
        t1.start()
        # Hourly deposit check thread
        t2 = threading.Thread(target=self._hourly_deposit_loop, daemon=True)
        t2.start()

    def _stock_simulation_loop(self):
        import time
        logger.info("Uruchamianie wątku symulacji giełdy...")
        while self.running:
            try:
                time.sleep(10)
                # Oblicz inflację
                inf_res = self.sql("SELECT value FROM global_settings WHERE key = 'inflation_rate'", fetch=True)
                inflation = float(inf_res[0]) if inf_res else 5.0
                bias = (inflation / 100.0) / 200.0 # Delikatny bias wzrostowy od inflacji
                
                stocks = self.sql("SELECT symbol, current_price FROM stocks", many=True)
                if stocks:
                    for sym, price in stocks:
                        price = float(price)
                        # Fluktuacja -1.5% do +1.5% + bias
                        change = random.uniform(-0.015, 0.015) + bias
                        new_price = max(1.0, round(price * (1 + change), 2))
                        self.sql("UPDATE stocks SET current_price = %s WHERE symbol = %s", (new_price, sym))
                        self.sql("INSERT INTO stock_history (symbol, price) VALUES (%s, %s)", (sym, new_price))
            except Exception as e:
                logger.error(f"Błąd w pętli symulacji giełdy: {e}")

    def _hourly_deposit_loop(self):
        import time
        logger.info("Uruchamianie wątku rozliczania lokat godzinowych...")
        while self.running:
            try:
                time.sleep(10)
                now = datetime.now()
                # Pobierz lokaty wygasłe i aktywne
                expired_deposits = self.sql(
                    "SELECT id, user_id, amount, interest_rate FROM hourly_deposits WHERE status = 'ACTIVE' AND expires_at <= %s",
                    (now,), many=True
                )
                if expired_deposits:
                    for dep_id, user_id, amount, rate in expired_deposits:
                        amount = float(amount)
                        rate = float(rate)
                        # Odsetki w skali godzinowej: rate% od zdeponowanej kwoty (gamified rate)
                        interest = round(amount * (rate / 100.0), 2)
                        total_payout = amount + interest
                        
                        # Zaktualizuj status lokaty
                        self.sql("UPDATE hourly_deposits SET status = 'COMPLETED' WHERE id = %s", (dep_id,))
                        # Dodaj środki użytkownikowi
                        self.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (total_payout, user_id))
                        # Dodaj transakcję
                        self.sql(
                            "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
                            (None, user_id, total_payout, 'DEPOSIT')
                        )
                        # Dodaj punkty nagród za ukończenie lokaty
                        self.sql("UPDATE users SET reward_points = COALESCE(reward_points, 0) + 15 WHERE id = %s", (user_id,))
                        logger.info(f"Lokata #{dep_id} zakończona. Wypłacono {total_payout} PLN dla użytkownika ID {user_id}")
            except Exception as e:
                logger.error(f"Błąd w pętli rozliczania lokat: {e}")

    def apply_inflation_to_user(self, user_id):
        try:
            inf_res = self.sql("SELECT value FROM global_settings WHERE key = 'inflation_rate'", fetch=True)
            inflation_rate = float(inf_res[0]) if inf_res else 5.0
            
            user_res = self.sql("SELECT saldo, last_inflation_applied FROM users WHERE id = %s", (user_id,), fetch=True)
            if user_res:
                saldo, last_applied = user_res
                saldo = float(saldo)
                now = datetime.now()
                
                # Różnica czasu w sekundach
                time_diff = (now - last_applied).total_seconds()
                
                # Naliczamy co najmniej po 10 sekundach
                if time_diff > 10 and saldo > 0:
                    seconds_in_year = 31536000.0
                    # Przyspieszenie 500x dla potrzeb demonstracji, żeby było widać wpływ inflacji
                    multiplier = 500.0
                    rate_per_second = (inflation_rate / 100.0) / seconds_in_year * multiplier
                    factor = (1 - rate_per_second) ** time_diff
                    new_saldo = round(saldo * factor, 2)
                    
                    if new_saldo != saldo:
                        self.sql("UPDATE users SET saldo = %s, last_inflation_applied = %s WHERE id = %s", (new_saldo, now, user_id))
                    else:
                        self.sql("UPDATE users SET last_inflation_applied = %s WHERE id = %s", (now, user_id))
        except Exception as e:
            logger.error(f"Błąd przy naliczaniu inflacji dla użytkownika {user_id}: {e}")

    def login_web(self, email, haslo):
        """Weryfikuje logowanie użytkownika na potrzeby aplikacji webowej"""
        logger.info(f"Web API: Próba logowania dla email: {email}")
        
        sql = """
            SELECT id, imie, nazwisko, saldo, nr_karty, haslo, two_factor_method, totp_secret, failed_login_attempts, locked 
            FROM users 
            WHERE email = %s
        """
        result = self.sql(sql, (email,), fetch=True)

        if result:
            user_id, imie, nazwisko, saldo, nr_karty, stored_haslo, two_factor_method, totp_secret, failed_attempts, locked = result
            
            if locked:
                return {"status": "FAIL", "message": "Konto zostało zablokowane z powodu zbyt wielu prób logowania."}
                
            if verify_password(stored_haslo, haslo):
                card_display = self.format_card_number(nr_karty)
                
                # Automatyczna migracja: jeśli hasło w bazie jest jawnym tekstem, zaktualizuj do bezpiecznego haszu
                if ":" not in stored_haslo:
                    try:
                        hashed_pwd = hash_password(haslo)
                        update_sql = "UPDATE users SET haslo = %s WHERE id = %s"
                        self.sql(update_sql, (hashed_pwd, user_id))
                        logger.info(f"Web API: Zmigrowano hasło użytkownika ID {user_id} do formatu zhaszowanego")
                    except Exception as me:
                        logger.error(f"Web API: Błąd automatycznej migracji hasła: {me}")

                if two_factor_method == "EMAIL":
                    success, details = self.generate_and_send_email_otp(email)
                    if not success:
                        return {"status": "FAIL", "message": f"Nie udało się wysłać kodu OTP ({details})"}
                    
                    temp_token = uuid.uuid4().hex
                    with temp_auth_lock:
                        TEMP_AUTH_SESSIONS[temp_token] = {
                            "user_id": user_id,
                            "email": email,
                            "type": "EMAIL",
                            "attempts": 0
                        }
                    return {
                        "status": "AWAITING_EMAIL_OTP",
                        "temp_token": temp_token,
                        "message": "Kod weryfikacyjny OTP został wysłany na Twój adres e-mail."
                    }
                elif two_factor_method == "TOTP":
                    temp_token = uuid.uuid4().hex
                    with temp_auth_lock:
                        TEMP_AUTH_SESSIONS[temp_token] = {
                            "user_id": user_id,
                            "email": email,
                            "type": "TOTP",
                            "attempts": 0
                        }
                    return {
                        "status": "AWAITING_TOTP",
                        "temp_token": temp_token,
                        "message": "Podaj kod z aplikacji Google Authenticator."
                    }
                else:
                    self.sql("UPDATE users SET failed_login_attempts = 0 WHERE id = %s", (user_id,))
                    return {
                        "status": "OK",
                        "id": user_id,
                        "imie": imie,
                        "nazwisko": nazwisko,
                        "saldo": float(saldo),
                        "nr_karty": nr_karty,
                        "nr_karty_format": card_display
                    }
            else:
                # Zwiększamy licznik błędnych prób
                new_attempts = failed_attempts + 1
                if new_attempts >= 3:
                    self.sql("UPDATE users SET failed_login_attempts = %s, locked = TRUE WHERE email = %s", (new_attempts, email))
                    logger.warning(f"Web API: Niepoprawne hasło. Konto {email} zostało zablokowane.")
                    return {"status": "FAIL", "message": "Niepoprawne hasło. Konto zostało zablokowane z powodu zbyt wielu prób logowania."}
                else:
                    self.sql("UPDATE users SET failed_login_attempts = %s WHERE email = %s", (new_attempts, email))
                    logger.warning(f"Web API: Niepoprawne hasło dla użytkownika: {email}")
                    return {"status": "FAIL", "message": f"Nieprawidłowy email lub hasło. Pozostało prób: {3 - new_attempts}"}
        else:
            logger.warning(f"Web API: Nie znaleziono użytkownika z email: {email}")

        return {"status": "FAIL", "message": "Nieprawidłowy email lub hasło"}

    def register_web(self, user_obj):
        """Rejestruje nowego użytkownika na potrzeby aplikacji webowej"""
        logger.info(f"Web API: Próba rejestracji nowego użytkownika: {user_obj.email}")
        
        # Generuj unikalny numer karty
        card_number = self.generate_card_number()
        user_obj.nr_karty = card_number

        # Haszuj hasło przed zapisem
        hashed_pwd = hash_password(user_obj.haslo)

        sql = """
            INSERT INTO users (imie, nazwisko, pesel, email, pin, haslo, saldo, nr_karty, two_factor_method, totp_secret)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """

        data = (
            user_obj.imie,
            user_obj.nazwisko,
            user_obj.pesel,
            user_obj.email,
            user_obj.pin,
            hashed_pwd,
            user_obj.saldo or 10000.00,
            card_number,
            getattr(user_obj, 'two_factor_method', 'NONE'),
            getattr(user_obj, 'totp_secret', None)
        )

        result = self.sql(sql, data, fetch=True)

        if result:
            user_obj.id = result[0]
            card_display = self.format_card_number(card_number)
            logger.info(f"Web API: Zarejestrowano pomyślnie nowego użytkownika o ID: {result[0]}")
            return {
                "status": "OK",
                "id": result[0],
                "imie": user_obj.imie,
                "nazwisko": user_obj.nazwisko,
                "nr_karty": card_number,
                "nr_karty_format": card_display,
                "saldo": float(user_obj.saldo or 0)
            }
        
        logger.error("Web API: Nie udało się zarejestrować użytkownika w bazie.")
        return {"status": "FAIL", "message": "Nie udało się zarejestrować"}

    def get_other_users(self, current_user_id):
        """Pobiera listę pozostałych użytkowników (do wyboru odbiorcy przelewu)"""
        sql = "SELECT id, imie, nazwisko, email, nr_karty FROM users WHERE id != %s ORDER BY id"
        results = self.sql(sql, (current_user_id,), many=True)
        users = []
        if results:
            for r in results:
                users.append({
                    "id": r[0],
                    "imie": r[1],
                    "nazwisko": r[2],
                    "email": r[3],
                    "nr_karty_format": self.format_card_number(r[4])
                })
        return users

    def resolve_recipient_id(self, recipient):
        """Rozwiązuje identyfikator odbiorcy (ID, e-mail lub numer karty) do ID użytkownika"""
        # 1. Sprawdź czy to jest ID (liczba całkowita)
        try:
            rid = int(recipient)
            user = self.get_user(rid)
            if user:
                return user["id"]
        except ValueError:
            pass

        # 2. Sprawdź czy to jest email
        sql = "SELECT id FROM users WHERE email = %s"
        res = self.sql(sql, (recipient.strip(),), fetch=True)
        if res:
            return res[0]

        # 3. Sprawdź czy to jest numer karty (usuwamy spacje)
        card_clean = recipient.replace(" ", "")
        sql = "SELECT id FROM users WHERE nr_karty = %s"
        res = self.sql(sql, (card_clean,), fetch=True)
        if res:
            return res[0]

        return None


# Inicjalizacja instancji serwera bankowego
bank_service = WebBankServer(User)


# Funkcja pomocnicza do wysyłania maila weryfikacyjnego
def send_verification_email(to_email, code):
    """Wysyła kod potwierdzający na podany adres e-mail w formacie HTML."""
    subject = "Kod potwierdzający - PathlBank"
    html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    background-color: #090b10;
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: #f0f3f8;
    margin: 0;
    padding: 0;
  }}
  .container {{
    max-width: 550px;
    margin: 30px auto;
    background: #121620;
    border: 1px solid rgba(0, 242, 254, 0.2);
    border-radius: 16px;
    padding: 35px;
    box-shadow: 0 8px 32px 0 rgba(0, 242, 254, 0.08);
  }}
  .header {{
    text-align: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding-bottom: 20px;
    margin-bottom: 30px;
  }}
  .logo {{
    font-size: 28px;
    font-weight: bold;
    color: #00f2fe;
    text-decoration: none;
  }}
  .content {{
    line-height: 1.6;
    font-size: 15px;
    color: #e2e8f0;
  }}
  .otp-container {{
    text-align: center;
    margin: 30px 0;
  }}
  .otp-code {{
    display: inline-block;
    font-size: 34px;
    font-weight: bold;
    letter-spacing: 6px;
    color: #00f2fe;
    background: rgba(0, 242, 254, 0.1);
    border: 2px solid #00f2fe;
    border-radius: 12px;
    padding: 10px 25px;
    box-shadow: 0 0 15px rgba(0, 242, 254, 0.15);
  }}
  .footer {{
    text-align: center;
    font-size: 11px;
    color: #8a99ad;
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    padding-top: 20px;
    margin-top: 35px;
  }}
  .warning {{
    background: rgba(255, 23, 68, 0.1);
    border-left: 4px solid #ff1744;
    padding: 12px;
    border-radius: 4px;
    margin-top: 20px;
    font-size: 13px;
    color: #ff8a9a;
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <span class="logo">🏦 PathlBank</span>
    </div>
    <div class="content">
      <p style="font-size: 17px; font-weight: bold; color: #ffffff;">Witaj!</p>
      <p>Otrzymaliśmy prośbę o zresetowanie hasła lub weryfikację rejestracji do Twojego konta w PathlBank. Twój kod potwierdzający to:</p>
      <div class="otp-container">
        <span class="otp-code">{code}</span>
      </div>
      <p>Kod jest ważny przez <strong>10 minut</strong>. Jeśli to nie Ty wykonywałeś operację, po prostu zignoruj tę wiadomość.</p>
    </div>
    <div class="footer">
      Pozdrawiamy,<br>
      <strong>Zespół PathlBank</strong><br>
      <span style="font-size: 10px; color: #64748b;">Ta wiadomość została wygenerowana automatycznie, prosimy na nią nie odpowiadać.</span>
    </div>
  </div>
</body>
</html>"""

    # Wypisz kod w logach
    logger.info(f"==================================================")
    logger.info(f"   KOD WERYFIKACYJNY DLA {to_email}: {code}   ")
    logger.info(f"==================================================")

    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP nie zostało w pełni skonfigurowane w .env. Użyto logowania w konsoli.")
        return False, "SMTP_NOT_CONFIGURED"

    try:
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to_email

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        
        logger.info(f"E-mail z kodem weryfikacyjnym został pomyślnie wysłany do {to_email}")
        return True, "SENT"
    except Exception as e:
        logger.error(f"Błąd wysyłania e-maila przez SMTP do {to_email}: {e}")
        return False, str(e)


# Decorator do autoryzacji zapytań API
def requires_auth(f):
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if token and token.startswith("Bearer "):
            token = token.split(" ", 1)[1]
        else:
            token = request.headers.get("X-Session-Token")

        if not token:
            return jsonify({"status": "FAIL", "message": "Brak tokenu autoryzacji"}), 401

        with web_session_lock:
            user_id = WEB_SESSIONS.get(token)

        if not user_id:
            return jsonify({"status": "FAIL", "message": "Niepoprawny lub wygasły token sesji"}), 401

        return f(user_id, *args, **kwargs)
    # Zmiana nazwy funkcji, by Flask nie zgłaszał konfliktów
    decorated.__name__ = f.__name__
    return decorated


# --- STATYCZNE STRONY ---
@app.route("/")
def serve_index():
    return render_template("index.html")


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(app.static_folder, path)


# --- PUNKTY KOŃCOWE API REST ---

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json() or {}
    required = ["imie", "nazwisko", "pesel", "email", "pin", "haslo"]
    if not all(k in data for k in required):
        return jsonify({"status": "FAIL", "message": "Brak wymaganych danych do rejestracji"}), 400

    # Sprawdź czy użytkownik istnieje
    email = data["email"]
    check_sql = "SELECT id FROM users WHERE email = %s"
    if bank_service.sql(check_sql, (email,), fetch=True):
        return jsonify({"status": "FAIL", "message": "Użytkownik o podanym adresie e-mail już istnieje"}), 400

    two_factor_method = data.get("two_factor_method", "NONE")

    try:
        user_obj = User(
            imie=data["imie"],
            nazwisko=data["nazwisko"],
            pesel=data["pesel"],
            email=email,
            pin=data["pin"],
            haslo=data["haslo"],
            saldo=float(data.get("saldo", 0)),
            two_factor_method=two_factor_method
        )

        # --- ZAWSZE wymagana weryfikacja e-mail przed rejestracją ---
        import hashlib
        from datetime import datetime, timedelta

        otp_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        otp_hash = hashlib.sha256(otp_code.encode('utf-8')).hexdigest()
        otp_expires = datetime.now() + timedelta(minutes=10)

        # Wysyłamy OTP weryfikacyjny na e-mail
        send_verification_email(email, otp_code)

        temp_token = uuid.uuid4().hex
        with temp_reg_lock:
            TEMP_REGISTRATIONS[temp_token] = {
                "user_obj": user_obj,
                "two_factor_method": two_factor_method,
                "otp_hash": otp_hash,
                "otp_expires": otp_expires,
                "email_verified": False,
                "totp_secret": None,
                "attempts": 0,
                "stage": "AWAITING_EMAIL_VERIFY"
            }

        return jsonify({
            "status": "AWAITING_EMAIL_VERIFY",
            "temp_token": temp_token,
            "message": f"Wysłano 6-cyfrowy kod weryfikacyjny na adres {email}. Kod ważny 10 minut."
        })

    except Exception as e:
        logger.error(f"Web API: Błąd rejestracji: {e}")
        return jsonify({"status": "FAIL", "message": str(e)}), 400


@app.route("/api/register/verify-email", methods=["POST"])
def api_register_verify_email():
    """Krok 2a rejestracji: weryfikacja adresu e-mail (wymagane zawsze).
    Po sukcesie: jeśli TOTP → zwraca AWAITING_TOTP z QR, jeśli nie → tworzy konto."""
    data = request.get_json() or {}
    temp_token = data.get("temp_token")
    code = data.get("code")

    if not temp_token or not code:
        return jsonify({"status": "FAIL", "message": "Brak tokenu lub kodu"}), 400

    with temp_reg_lock:
        reg_info = TEMP_REGISTRATIONS.get(temp_token)

    if not reg_info or reg_info.get("stage") != "AWAITING_EMAIL_VERIFY":
        return jsonify({"status": "FAIL", "message": "Wygasła lub niepoprawna sesja rejestracji. Zacznij od nowa."}), 400

    import hashlib
    from datetime import datetime

    # Sprawdź wygaśnięcie kodu
    if datetime.now() > reg_info["otp_expires"]:
        with temp_reg_lock:
            TEMP_REGISTRATIONS.pop(temp_token, None)
        return jsonify({"status": "FAIL", "message": "Kod weryfikacyjny wygasł. Zacznij rejestrację od nowa."}), 400

    # Sprawdź liczbę prób
    attempts = reg_info.get("attempts", 0)
    if attempts >= 3:
        with temp_reg_lock:
            TEMP_REGISTRATIONS.pop(temp_token, None)
        return jsonify({"status": "FAIL", "message": "Zbyt wiele błędnych prób. Rejestracja anulowana."}), 400

    # Porównaj hash
    input_hash = hashlib.sha256(code.strip().encode('utf-8')).hexdigest()
    if input_hash != reg_info["otp_hash"]:
        reg_info["attempts"] = attempts + 1
        left = 3 - reg_info["attempts"]
        return jsonify({"status": "FAIL", "message": f"Niepoprawny kod weryfikacyjny. Pozostało prób: {left}"}), 400

    # === E-mail zweryfikowany ===
    reg_info["email_verified"] = True
    two_factor_method = reg_info["two_factor_method"]
    user_obj = reg_info["user_obj"]

    if two_factor_method == "TOTP":
        # Generuj secret + QR code i przejdź do kroku TOTP
        secret = pyotp.random_base32()
        uri = f"otpauth://totp/PathlBank:{user_obj.email}?secret={secret}&issuer=PathlBank"

        qr = qrcode.QRCode()
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        qr_code_base64 = f"data:image/png;base64,{img_str}"

        # Aktualizuj sesję tymczasową
        reg_info["totp_secret"] = secret
        reg_info["attempts"] = 0
        reg_info["stage"] = "AWAITING_TOTP"

        return jsonify({
            "status": "AWAITING_TOTP",
            "temp_token": temp_token,
            "secret": secret,
            "qr_code": qr_code_base64,
            "message": "E-mail zweryfikowany! Zeskanuj kod QR w aplikacji Google Authenticator."
        })

    # Brak TOTP — zarejestruj konto od razu
    res = bank_service.register_web(user_obj)
    with temp_reg_lock:
        TEMP_REGISTRATIONS.pop(temp_token, None)

    if res["status"] == "OK":
        token = uuid.uuid4().hex
        with web_session_lock:
            WEB_SESSIONS[token] = res["id"]
            save_sessions()
        res["token"] = token
        res["message"] = "Rejestracja zakończona sukcesem!"
        return jsonify(res)
    else:
        return jsonify(res), 400


@app.route("/api/register/verify-totp", methods=["POST"])
def api_register_verify_totp():
    """Krok 2b rejestracji (opcjonalny): weryfikacja Google Authenticator.
    Wywoływany tylko gdy two_factor_method=TOTP i e-mail już zweryfikowany."""
    data = request.get_json() or {}
    temp_token = data.get("temp_token")
    code = data.get("code")

    if not temp_token or not code:
        return jsonify({"status": "FAIL", "message": "Brak tokenu lub kodu"}), 400

    with temp_reg_lock:
        reg_info = TEMP_REGISTRATIONS.get(temp_token)

    if not reg_info or not reg_info.get("email_verified") or reg_info.get("stage") != "AWAITING_TOTP":
        return jsonify({"status": "FAIL", "message": "Niepoprawna lub wygasła sesja. Zacznij rejestrację od nowa."}), 400

    user_obj = reg_info["user_obj"]
    secret = reg_info["totp_secret"]

    totp = pyotp.TOTP(secret)
    if totp.verify(code.strip()):
        user_obj.two_factor_method = 'TOTP'
        user_obj.totp_secret = secret
        res = bank_service.register_web(user_obj)

        with temp_reg_lock:
            TEMP_REGISTRATIONS.pop(temp_token, None)

        if res["status"] == "OK":
            token = uuid.uuid4().hex
            with web_session_lock:
                WEB_SESSIONS[token] = res["id"]
                save_sessions()
            res["token"] = token
            res["message"] = "Rejestracja zakończona sukcesem! Google Authenticator skonfigurowany."
            return jsonify(res)
        else:
            return jsonify(res), 400
    else:
        reg_info["attempts"] = reg_info.get("attempts", 0) + 1
        if reg_info["attempts"] >= 3:
            with temp_reg_lock:
                TEMP_REGISTRATIONS.pop(temp_token, None)
            return jsonify({"status": "FAIL", "message": "Zbyt wiele nieudanych prób TOTP. Rejestracja anulowana."}), 400
        return jsonify({"status": "FAIL", "message": f"Niepoprawny kod TOTP. Pozostało prób: {3 - reg_info['attempts']}"}), 400


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    email = data.get("email")
    haslo = data.get("haslo")

    if not email or not haslo:
        return jsonify({"status": "FAIL", "message": "Brak emailu lub hasła"}), 400

    try:
        res = bank_service.login_web(email, haslo)
        if res["status"] == "OK":
            token = uuid.uuid4().hex
            with web_session_lock:
                WEB_SESSIONS[token] = res["id"]
                save_sessions()
            res["token"] = token
            return jsonify(res)
        elif res["status"] in ["AWAITING_EMAIL_OTP", "AWAITING_TOTP"]:
            return jsonify(res)
        else:
            return jsonify(res), 401
    except Exception as e:
        logger.error(f"Web API: Błąd logowania: {e}")
        return jsonify({"status": "FAIL", "message": str(e)}), 500


@app.route("/api/login/verify-2fa", methods=["POST"])
def api_login_verify_2fa():
    data = request.get_json() or {}
    temp_token = data.get("temp_token")
    code = data.get("code")

    if not temp_token or not code:
        return jsonify({"status": "FAIL", "message": "Brak tokenu lub kodu"}), 400

    with temp_auth_lock:
        auth_info = TEMP_AUTH_SESSIONS.get(temp_token)

    if not auth_info:
        return jsonify({"status": "FAIL", "message": "Niepoprawna lub wygasła sesja weryfikacji."}), 400

    user_id = auth_info["user_id"]
    email = auth_info["email"]
    auth_type = auth_info["type"]
    
    sql = "SELECT locked, failed_login_attempts FROM users WHERE id = %s"
    res = bank_service.sql(sql, (user_id,), fetch=True)
    if res and res[0]:
        return jsonify({"status": "FAIL", "message": "Konto jest zablokowane."}), 403

    verified = False
    if auth_type == "EMAIL":
        from server import verify_email_otp
        verified = verify_email_otp(email, code)
    elif auth_type == "TOTP":
        sql_totp = "SELECT totp_secret FROM users WHERE id = %s"
        res_totp = bank_service.sql(sql_totp, (user_id,), fetch=True)
        if res_totp and res_totp[0]:
            import pyotp
            totp = pyotp.TOTP(res_totp[0])
            verified = totp.verify(code.strip())
            
            if verified:
                bank_service.sql("UPDATE users SET failed_login_attempts = 0 WHERE id = %s", (user_id,))
            else:
                db_attempts = res[1] if res else 0
                new_db_attempts = db_attempts + 1
                if new_db_attempts >= 3:
                    bank_service.sql("UPDATE users SET failed_login_attempts = %s, locked = TRUE WHERE id = %s", (new_db_attempts, user_id))
                else:
                    bank_service.sql("UPDATE users SET failed_login_attempts = %s WHERE id = %s", (new_db_attempts, user_id))

    if verified:


        # Jeśli pomyślnie przeszliśmy wszystkie weryfikacje
        with temp_auth_lock:
            if temp_token in TEMP_AUTH_SESSIONS:
                del TEMP_AUTH_SESSIONS[temp_token]
        
        # Resetujemy błędne próby w bazie
        bank_service.sql("UPDATE users SET failed_login_attempts = 0 WHERE id = %s", (user_id,))
        
        sql_user = "SELECT id, imie, nazwisko, saldo, nr_karty FROM users WHERE id = %s"
        u_res = bank_service.sql(sql_user, (user_id,), fetch=True)
        
        token = uuid.uuid4().hex
        with web_session_lock:
            WEB_SESSIONS[token] = user_id
            save_sessions()
            
        return jsonify({
            "status": "OK",
            "token": token,
            "id": u_res[0],
            "imie": u_res[1],
            "nazwisko": u_res[2],
            "saldo": float(u_res[3]),
            "nr_karty": u_res[4],
            "nr_karty_format": bank_service.format_card_number(u_res[4])
        })
    else:
        sql_attempts = "SELECT locked, failed_login_attempts FROM users WHERE id = %s"
        res_att = bank_service.sql(sql_attempts, (user_id,), fetch=True)
        
        if res_att and res_att[0]:
            with temp_auth_lock:
                if temp_token in TEMP_AUTH_SESSIONS:
                    del TEMP_AUTH_SESSIONS[temp_token]
            return jsonify({"status": "FAIL", "message": "Konto zostało zablokowane z powodu zbyt wielu prób logowania."}), 403
        else:
            attempts = res_att[1] if res_att else 0
            return jsonify({"status": "FAIL", "message": f"Niepoprawny kod weryfikacyjny. Pozostało prób: {3 - attempts}"}), 400


@app.route("/api/logout", methods=["POST"])
def api_logout():
    token = request.headers.get("Authorization")
    if token and token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
    else:
        token = request.headers.get("X-Session-Token")

    if token:
        with web_session_lock:
            if token in WEB_SESSIONS:
                del WEB_SESSIONS[token]
                save_sessions()
        return jsonify({"status": "OK", "message": "Wylogowano pomyślnie"})
    return jsonify({"status": "FAIL", "message": "Brak tokenu"}), 400


@app.route("/api/info", methods=["GET"])
@requires_auth
def api_info(user_id):
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user:
        user["nr_karty_format"] = bank_service.format_card_number(user["nr_karty"])
        return jsonify({"status": "OK", "user": user})
    return jsonify({"status": "FAIL", "message": "Nie znaleziono użytkownika"}), 404


@app.route("/api/balance", methods=["GET"])
@requires_auth
def api_balance(user_id):
    bank_service.apply_inflation_to_user(user_id)
    res = bank_service.get_balance(user_id)
    return jsonify(res)


@app.route("/api/deposit", methods=["POST"])
@requires_auth
def api_deposit(user_id):
    return jsonify({"status": "FAIL", "message": "Wpłaty gotówkowe w tym banku są zablokowane. Bank działa w systemie rzeczywistym."}), 400


@app.route("/api/withdraw", methods=["POST"])
@requires_auth
def api_withdraw(user_id):
    return jsonify({"status": "FAIL", "message": "Wypłaty gotówkowe w tym banku są zablokowane. Bank działa w systemie rzeczywistym."}), 400


@app.route("/api/transfer", methods=["POST"])
@requires_auth
def api_transfer(user_id):
    data = request.get_json() or {}
    recipient = data.get("recipient")
    try:
        amount = float(data.get("amount", 0))
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400

    if not recipient:
        return jsonify({"status": "FAIL", "message": "Brak odbiorcy przelewu"}), 400

    # Rozwiąż identyfikator odbiorcy do ID użytkownika
    recipient_id = bank_service.resolve_recipient_id(str(recipient))
    if not recipient_id:
        return jsonify({"status": "FAIL", "message": f"Odbiorca '{recipient}' nie został odnaleziony w systemie"}), 404

    res = bank_service.transfer(user_id, recipient_id, amount)
    if res["status"] == "OK":
        return jsonify(res)
    return jsonify(res), 400


@app.route("/api/history", methods=["GET"])
@requires_auth
def api_history(user_id):
    try:
        limit = int(request.args.get("limit", 15))
    except ValueError:
        limit = 15
    res = bank_service.get_history(user_id, limit=limit)
    return jsonify(res)


@app.route("/api/users", methods=["GET"])
@requires_auth
def api_users(user_id):
    users = bank_service.get_other_users(user_id)
    return jsonify({"status": "OK", "users": users})


@app.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    data = request.get_json() or {}
    email = data.get("email")

    if not email:
        return jsonify({"status": "FAIL", "message": "Wpisz swój adres e-mail"}), 400

    # Sprawdź czy użytkownik istnieje w bazie
    sql = "SELECT id FROM users WHERE email = %s"
    res = bank_service.sql(sql, (email,), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Użytkownik o podanym e-mailu nie istnieje"}), 404

    # Generowanie losowego 6-cyfrowego kodu
    code = "".join(random.choices(string.digits, k=6))
    expiry = datetime.now() + timedelta(minutes=10)

    # Zapis w pamięci
    with reset_codes_lock:
        RESET_CODES[email] = {
            "code": code,
            "expires_at": expiry
        }

    # Wyślij e-mail
    success, details = send_verification_email(email, code)

    if success:
        return jsonify({
            "status": "OK",
            "message": "Kod weryfikacyjny został wysłany na Twój adres e-mail."
        })
    elif details == "SMTP_NOT_CONFIGURED":
        return jsonify({
            "status": "OK",
            "message": "Wygenerowano kod pomyślnie. Ze względu na brak konfiguracji SMTP w .env, kod znajdziesz w logach serwera (bank_server.log) i konsoli."
        })
    else:
        return jsonify({
            "status": "OK",
            "message": f"Wygenerowano kod. Wystąpił błąd wysyłki SMTP ({details}), dlatego kod znajdziesz w logach serwera (bank_server.log) i konsoli."
        })


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    data = request.get_json() or {}
    email = data.get("email")
    code = data.get("code")
    new_password = data.get("new_password")

    if not email or not code or not new_password:
        return jsonify({"status": "FAIL", "message": "Wszystkie pola są wymagane"}), 400

    if len(new_password) < 5:
        return jsonify({"status": "FAIL", "message": "Hasło musi mieć co najmniej 5 znaków"}), 400

    # Weryfikacja kodu
    with reset_codes_lock:
        reset_info = RESET_CODES.get(email)

    if not reset_info:
        return jsonify({"status": "FAIL", "message": "Brak wygenerowanego kodu dla tego e-maila. Spróbuj ponownie."}), 400

    if reset_info["expires_at"] < datetime.now():
        with reset_codes_lock:
            if email in RESET_CODES:
                del RESET_CODES[email]
        return jsonify({"status": "FAIL", "message": "Kod weryfikacyjny wygasł. Wygeneruj nowy."}), 400

    if reset_info["code"] != code.strip():
        return jsonify({"status": "FAIL", "message": "Niepoprawny kod weryfikacyjny."}), 400

    # Kod poprawny - zmiana hasła w bazie
    try:
        hashed_pwd = hash_password(new_password)
        sql = "UPDATE users SET haslo = %s WHERE email = %s"
        bank_service.sql(sql, (hashed_pwd, email))

        # Usuń kod z pamięci
        with reset_codes_lock:
            if email in RESET_CODES:
                del RESET_CODES[email]

        logger.info(f"Web API: Zresetowano hasło dla konta {email}")
        return jsonify({"status": "OK", "message": "Hasło zostało zmienione. Możesz się teraz zalogować."})
    except Exception as e:
        logger.error(f"Web API: Błąd bazy danych podczas resetu hasła: {e}")
        return jsonify({"status": "FAIL", "message": "Błąd bazy danych podczas resetu hasła"}), 500


# --- POMOCNICZA FUNKCJA NAGRÓD ---
def add_reward_points(user_id, points):
    try:
        sql = "UPDATE users SET reward_points = COALESCE(reward_points, 0) + %s WHERE id = %s"
        bank_service.sql(sql, (points, user_id))
    except Exception as e:
        logger.error(f"Error adding reward points: {e}")


# --- NOWE WIDOKI I PUNKTY KOŃCOWE API ---

# --- USTAWIENIA ---
@app.route("/api/settings/change-password", methods=["POST"])
@requires_auth
def api_settings_change_password(user_id):
    data = request.get_json() or {}
    old_pw = data.get("old_password")
    new_pw = data.get("new_password")
    if not old_pw or not new_pw:
        return jsonify({"status": "FAIL", "message": "Podaj stare i nowe hasło"}), 400
    if len(new_pw) < 5:
        return jsonify({"status": "FAIL", "message": "Nowe hasło musi mieć co najmniej 5 znaków"}), 400
    
    res = bank_service.sql("SELECT haslo FROM users WHERE id = %s", (user_id,), fetch=True)
    if not res or not verify_password(res[0], old_pw):
        return jsonify({"status": "FAIL", "message": "Stare hasło jest niepoprawne"}), 400
        
    hashed = hash_password(new_pw)
    bank_service.sql("UPDATE users SET haslo = %s WHERE id = %s", (hashed, user_id))
    add_reward_points(user_id, 10)
    return jsonify({"status": "OK", "message": "Hasło zostało zmienione pomyślnie!"})


@app.route("/api/settings/toggle-2fa", methods=["POST"])
@requires_auth
def api_settings_toggle_2fa(user_id):
    data = request.get_json() or {}
    method = data.get("method")
    if method not in ["NONE", "EMAIL", "TOTP"]:
        return jsonify({"status": "FAIL", "message": "Niepoprawna metoda 2FA"}), 400
    
    if method == "TOTP":
        secret = pyotp.random_base32()
        sql_email = "SELECT email FROM users WHERE id = %s"
        email_res = bank_service.sql(sql_email, (user_id,), fetch=True)
        email = email_res[0] if email_res else "user"
        uri = f"otpauth://totp/PathlBank:{email}?secret={secret}&issuer=PathlBank"
        
        qr = qrcode.QRCode()
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        bank_service.sql("UPDATE users SET totp_secret = %s, two_factor_method = 'TOTP' WHERE id = %s", (secret, user_id))
        add_reward_points(user_id, 20)
        return jsonify({
            "status": "OK",
            "method": "TOTP",
            "secret": secret,
            "qr_code": f"data:image/png;base64,{img_str}",
            "message": "Metoda 2FA zmieniona na Google Authenticator (TOTP). Zeskanuj kod QR."
        })
    else:
        bank_service.sql("UPDATE users SET two_factor_method = %s WHERE id = %s", (method, user_id))
        add_reward_points(user_id, 10)
        return jsonify({"status": "OK", "method": method, "message": f"Metoda 2FA została zmieniona na {method}."})


@app.route("/api/settings/register-company", methods=["POST"])
@requires_auth
def api_settings_register_company(user_id):
    data = request.get_json() or {}
    name = data.get("name")
    nip = data.get("nip")
    regon = data.get("regon")
    if not name or not nip or not regon:
        return jsonify({"status": "FAIL", "message": "Nazwa firmy, NIP oraz REGON są wymagane"}), 400
    
    if len(nip) != 10 or not nip.isdigit():
        return jsonify({"status": "FAIL", "message": "NIP musi składać się z 10 cyfr"}), 400
    if len(regon) not in [9, 14] or not regon.isdigit():
        return jsonify({"status": "FAIL", "message": "REGON musi mieć 9 lub 14 cyfr"}), 400
        
    sql = """
        UPDATE users 
        SET is_company = TRUE, company_name = %s, company_nip = %s, company_regon = %s 
        WHERE id = %s
    """
    bank_service.sql(sql, (name, nip, regon, user_id))
    add_reward_points(user_id, 50)
    return jsonify({"status": "OK", "message": "Firma została zarejestrowana i zweryfikowana pomyślnie!"})


# --- PANEL ADMINA ---
@app.route("/api/admin/settings", methods=["POST"])
@requires_auth
def api_admin_settings(admin_id):
    admin = bank_service.get_user(admin_id)
    if not admin or admin.get("is_admin") != 1:
        return jsonify({"status": "FAIL", "message": "Brak uprawnień administratora"}), 403
        
    data = request.get_json() or {}
    inflation = data.get("inflation_rate")
    interest = data.get("interest_rate")
    
    if inflation is not None:
        bank_service.sql("INSERT INTO global_settings (key, value) VALUES ('inflation_rate', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (str(inflation), str(inflation)))
    if interest is not None:
        bank_service.sql("INSERT INTO global_settings (key, value) VALUES ('interest_rate', %s) ON CONFLICT (key) DO UPDATE SET value = %s", (str(interest), str(interest)))
        
    return jsonify({"status": "OK", "message": "Ustawienia globalne zostały zaktualizowane!"})


@app.route("/api/admin/give-money", methods=["POST"])
@requires_auth
def api_admin_give_money(admin_id):
    admin = bank_service.get_user(admin_id)
    if not admin or admin.get("is_admin") != 1:
        return jsonify({"status": "FAIL", "message": "Brak uprawnień administratora"}), 403
        
    data = request.get_json() or {}
    recipient = data.get("recipient")
    try:
        amount = float(data.get("amount", 0))
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
        
    if amount <= 0:
        return jsonify({"status": "FAIL", "message": "Kwota musi być większa niż zero"}), 400
        
    recipient_id = bank_service.resolve_recipient_id(str(recipient))
    if not recipient_id:
        return jsonify({"status": "FAIL", "message": "Nie znaleziono odbiorcy"}), 404
        
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount, recipient_id))
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (admin_id, recipient_id, amount, 'TRANSFER')
    )
    return jsonify({"status": "OK", "message": f"Przelano pomyślnie {amount:.2f} PLN do użytkownika."})


@app.route("/api/admin/users", methods=["GET"])
@requires_auth
def api_admin_users(admin_id):
    admin = bank_service.get_user(admin_id)
    if not admin or admin.get("is_admin") != 1:
        return jsonify({"status": "FAIL", "message": "Brak uprawnień"}), 403
        
    search = request.args.get("search", "")
    if search:
        sql = """
            SELECT id, imie, nazwisko, email, saldo, nr_karty, is_admin, is_company, company_name 
            FROM users 
            WHERE (imie ILIKE %s OR nazwisko ILIKE %s OR email ILIKE %s OR nr_karty ILIKE %s)
            ORDER BY id ASC
        """
        like_search = f"%{search}%"
        res = bank_service.sql(sql, (like_search, like_search, like_search, like_search), many=True)
    else:
        sql = """
            SELECT id, imie, nazwisko, email, saldo, nr_karty, is_admin, is_company, company_name 
            FROM users 
            ORDER BY id ASC
        """
        res = bank_service.sql(sql, many=True)
        
    users = []
    for r in res:
        users.append({
            "id": r[0],
            "imie": r[1],
            "nazwisko": r[2],
            "email": r[3],
            "saldo": float(r[4]),
            "nr_karty": r[5],
            "nr_karty_format": bank_service.format_card_number(r[5]),
            "is_admin": r[6],
            "is_company": r[7],
            "company_name": r[8]
        })
    return jsonify({"status": "OK", "users": users})


@app.route("/api/admin/stats", methods=["GET"])
@requires_auth
def api_admin_stats(admin_id):
    admin = bank_service.get_user(admin_id)
    if not admin or admin.get("is_admin") != 1:
        return jsonify({"status": "FAIL", "message": "Brak uprawnień"}), 403
        
    total_users = bank_service.sql("SELECT COUNT(*) FROM users", fetch=True)[0]
    total_companies = bank_service.sql("SELECT COUNT(*) FROM users WHERE is_company = TRUE", fetch=True)[0]
    total_balance = float(bank_service.sql("SELECT SUM(saldo) FROM users", fetch=True)[0] or 0)
    total_loans = float(bank_service.sql("SELECT SUM(remaining_amount) FROM loans WHERE status = 'APPROVED'", fetch=True)[0] or 0)
    total_deposits = float(bank_service.sql("SELECT SUM(amount) FROM hourly_deposits WHERE status = 'ACTIVE'", fetch=True)[0] or 0)
    
    inf_res = bank_service.sql("SELECT value FROM global_settings WHERE key = 'inflation_rate'", fetch=True)
    interest_res = bank_service.sql("SELECT value FROM global_settings WHERE key = 'interest_rate'", fetch=True)
    inflation_rate = float(inf_res[0]) if inf_res else 5.0
    interest_rate = float(interest_res[0]) if interest_res else 4.5
    
    return jsonify({
        "status": "OK",
        "stats": {
            "total_users": total_users,
            "total_companies": total_companies,
            "total_balance": total_balance,
            "total_loans": total_loans,
            "total_deposits": total_deposits,
            "inflation_rate": inflation_rate,
            "interest_rate": interest_rate
        }
    })


# --- CZAT E2E ---
@app.route("/api/chat/register-key", methods=["POST"])
@requires_auth
def api_chat_register_key(user_id):
    data = request.get_json() or {}
    pub_key = data.get("public_key")
    if not pub_key:
        return jsonify({"status": "FAIL", "message": "Klucz publiczny jest wymagany"}), 400
    bank_service.sql("UPDATE users SET public_key = %s WHERE id = %s", (pub_key, user_id))
    return jsonify({"status": "OK", "message": "Klucz publiczny został zarejestrowany"})


@app.route("/api/chat/public-key/<int:target_user_id>", methods=["GET"])
@requires_auth
def api_chat_public_key(user_id, target_user_id):
    res = bank_service.sql("SELECT public_key FROM users WHERE id = %s", (target_user_id,), fetch=True)
    if res and res[0]:
        return jsonify({"status": "OK", "public_key": res[0]})
    return jsonify({"status": "FAIL", "message": "Brak klucza publicznego dla tego użytkownika"}), 404


@app.route("/api/chat/send_e2e_legacy", methods=["POST"])
@requires_auth
def api_chat_send(user_id):
    data = request.get_json() or {}
    recipient_id = data.get("recipient_id")
    encrypted_msg = data.get("encrypted_message")
    key_sender = data.get("encrypted_key_sender")
    key_recipient = data.get("encrypted_key_recipient")
    
    if not recipient_id or not encrypted_msg or not key_sender or not key_recipient:
        return jsonify({"status": "FAIL", "message": "Brak kompletnych danych wiadomości E2E"}), 400
        
    sql = """
        INSERT INTO e2e_messages (from_user, to_user, encrypted_message, encrypted_key_sender, encrypted_key_recipient)
        VALUES (%s, %s, %s, %s, %s)
    """
    bank_service.sql(sql, (user_id, recipient_id, encrypted_msg, key_sender, key_recipient))
    add_reward_points(user_id, 5)
    return jsonify({"status": "OK", "message": "Zaszyfrowana wiadomość została wysłana."})


@app.route("/api/chat/messages/<int:other_id>", methods=["GET"])
@requires_auth
def api_chat_messages(user_id, other_id):
    sql = """
        SELECT id, from_user, to_user, encrypted_message, encrypted_key_sender, encrypted_key_recipient, created_at 
        FROM e2e_messages 
        WHERE (from_user = %s AND to_user = %s) OR (from_user = %s AND to_user = %s)
        ORDER BY id ASC
    """
    res = bank_service.sql(sql, (user_id, other_id, other_id, user_id), many=True)
    messages = []
    for r in res:
        messages.append({
            "id": r[0],
            "from_user": r[1],
            "to_user": r[2],
            "encrypted_message": r[3],
            "encrypted_key_sender": r[4],
            "encrypted_key_recipient": r[5],
            "created_at": r[6].isoformat()
        })
    return jsonify({"status": "OK", "messages": messages})


# --- KONSOLA AI ---
@app.route("/api/ai/chat", methods=["POST"])
@requires_auth
def api_ai_chat(user_id):
    data = request.get_json() or {}
    message = data.get("message", "").strip().lower()
    if not message:
        return jsonify({"status": "FAIL", "message": "Brak wiadomości"}), 400
        
    user = bank_service.get_user(user_id)
    tx_sql = """
        SELECT t.id, t.amount, t.type, t.created_at,
               u1.imie as from_imie, u1.nazwisko as from_nazw, u1.email as from_mail,
               u2.imie as to_imie, u2.nazwisko as to_nazw, u2.email as to_mail
        FROM transactions t
        LEFT JOIN users u1 ON t.from_user = u1.id
        LEFT JOIN users u2 ON t.to_user = u2.id
        WHERE t.from_user = %s OR t.to_user = %s
        ORDER BY t.id DESC LIMIT 3
    """
    tx_res = bank_service.sql(tx_sql, (user_id, user_id), many=True)
    
    inf_res = bank_service.sql("SELECT value FROM global_settings WHERE key = 'inflation_rate'", fetch=True)
    int_res = bank_service.sql("SELECT value FROM global_settings WHERE key = 'interest_rate'", fetch=True)
    inflation = float(inf_res[0]) if inf_res else 5.0
    interest = float(int_res[0]) if int_res else 4.5
    
    response = ""
    action = None
    
    if "saldo" in message or "pieniądze" in message or "pieniadze" in message or "balans" in message:
        response = f"Witaj {user['imie']}! Twoje aktualne saldo na koncie wynosi **{user['saldo']:.2f} PLN**."
    elif "historia" in message or "transakcje" in message or "przelew" in message and "ostatni" in message:
        if not tx_res:
            response = "Nie masz jeszcze żadnych transakcji w historii."
        else:
            response = "Oto zestawienie Twoich ostatnich 3 transakcji:\n"
            for tx in tx_res:
                tx_id, amount, tx_type, date, f_imie, f_nazw, f_mail, t_imie, t_nazw, t_mail = tx
                date_str = date.strftime("%Y-%m-%d %H:%M")
                if tx_type == 'DEPOSIT':
                    response += f"- **+{amount:.2f} PLN** (Wpłata/Lokata) w dniu {date_str}\n"
                elif tx_type == 'WITHDRAW':
                    response += f"- **-{amount:.2f} PLN** (Wypłata) w dniu {date_str}\n"
                else:
                    if f_mail == user["email"]:
                        response += f"- **-{amount:.2f} PLN** do {t_imie} {t_nazw} ({t_mail}) w dniu {date_str}\n"
                    else:
                        response += f"- **+{amount:.2f} PLN** od {f_imie} {f_nazw} ({f_mail}) w dniu {date_str}\n"
    elif "inflacja" in message or "stopy" in message or "oprocentowanie" in message:
        response = f"Obecna inflacja w naszym systemie bankowym wynosi **{inflation:.1f}%** w skali rocznej. Nasza główna stopa procentowa (oprocentowanie lokat godzinowych) wynosi **{interest:.1f}%** na godzinę. Założenie lokaty to świetny sposób na walkę z inflacją!"
    elif "lokata" in message or "lokatę" in message or "zdeponuj" in message:
        words = message.split()
        amount_found = None
        for w in words:
            w_clean = w.replace(",", ".").replace("pln", "").replace("zł", "")
            try:
                val = float(w_clean)
                if val >= 100:
                    amount_found = val
                    break
            except ValueError:
                continue
        if amount_found:
            response = f"Zidentyfikowałem chęć założenia lokaty na kwotę **{amount_found:.2f} PLN**. Napisz 'potwierdzam lokatę {amount_found}' lub kliknij przycisk poniżej, aby natychmiast ją uruchomić!"
            action = {"type": "create_deposit", "amount": amount_found}
        else:
            response = f"Chcesz założyć lokatę godzinową? Oprocentowanie wynosi **{interest}%** na godzinę (min. kwota to 100 PLN). Podaj kwotę w pytaniu, np: 'AI załóż lokatę na 500 PLN'."
    elif "potwierdzam lokatę" in message:
        words = message.split()
        amount_found = None
        for w in words:
            w_clean = w.replace(",", ".").replace("pln", "").replace("zł", "")
            try:
                val = float(w_clean)
                if val >= 100:
                    amount_found = val
                    break
            except ValueError:
                continue
        if amount_found:
            if user["saldo"] >= amount_found:
                now = datetime.now()
                expires_at = now + timedelta(hours=1)
                bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount_found, user_id))
                bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)", (user_id, None, amount_found, 'WITHDRAW'))
                bank_service.sql("INSERT INTO hourly_deposits (user_id, amount, interest_rate, created_at, expires_at, status) VALUES (%s, %s, %s, %s, %s, 'ACTIVE')", (user_id, amount_found, interest, now, expires_at))
                add_reward_points(user_id, 15)
                response = f"Pomyślnie otworzyłem lokatę godzinową na kwotę **{amount_found:.2f} PLN** z oprocentowaniem **{interest}%/h**! Środki zostaną zwrócone po 1 godzinie."
            else:
                response = "Niestety, nie masz wystarczających środków na koncie, aby założyć tę lokatę."
        else:
            response = "Nie zrozumiałem kwoty lokaty."
    elif "kredyt" in message or "pożyczka" in message or "pozyczka" in message:
        response = f"W PathlBank oferujemy szybkie kredyty gotówkowe oparte na stopach procentowych ({interest:.1f}%). Możesz złożyć wniosek o kredyt w sekcji 'Lokaty i Kredyty' lub bezpośrednio przez formularz na panelu. Jaką kwotą jesteś zainteresowany?"
    elif "pomoc" in message or "potrafisz" in message or "komendy" in message:
        response = """Jestem Twoim osobistym asystentem bankowości PathlBank. Oto co potrafię:
1. Sprawdzić Twoje **saldo** ("podaj moje saldo").
2. Pokazać ostatnie **transakcje** ("jaka jest moja historia transakcji?").
3. Poinformować o **inflacji** i stopach procentowych.
4. Pomóc w **założeniu lokaty** ("załóż lokatę na 500 PLN").
5. Wyjaśnić działanie umów, faktur i E2E czatu.
Wpisz dowolne z powyższych haseł, aby uzyskać pomoc!"""
    else:
        response = f"Witaj {user['imie']}! Słyszę Twoje pytanie: '{data.get('message')}', ale nie jestem pewien, jak na nie odpowiedzieć. Możesz mnie zapytać o swoje saldo, historię transakcji, stopy procentowe albo o założenie lokaty. Wpisz 'pomoc', aby wyświetlić listę wspieranych tematów!"
        
    return jsonify({
        "status": "OK",
        "response": response,
        "action": action
    })


# --- FAKTURY ---
@app.route("/api/invoices/issue", methods=["POST"])
@requires_auth
def api_invoices_issue(user_id):
    data = request.get_json() or {}
    recipient = data.get("recipient")
    amount = data.get("amount")
    title = data.get("title")
    
    if not recipient or not amount or not title:
        return jsonify({"status": "FAIL", "message": "Odbiorca, kwota i tytuł są wymagane"}), 400
        
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            return jsonify({"status": "FAIL", "message": "Kwota musi być dodatnia"}), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
        
    recipient_id = bank_service.resolve_recipient_id(str(recipient))
    if not recipient_id:
        return jsonify({"status": "FAIL", "message": "Odbiorca nie został znaleziony"}), 404
    if recipient_id == user_id:
        return jsonify({"status": "FAIL", "message": "Nie możesz wystawić faktury samemu sobie"}), 400
        
    sql = "INSERT INTO invoices (sender_id, recipient_id, amount, title, status) VALUES (%s, %s, %s, %s, 'UNPAID')"
    bank_service.sql(sql, (user_id, recipient_id, amount_val, title))
    add_reward_points(user_id, 15)
    return jsonify({"status": "OK", "message": "Faktura została wystawiona pomyślnie."})


@app.route("/api/invoices/received", methods=["GET"])
@requires_auth
def api_invoices_received(user_id):
    sql = """
        SELECT i.id, i.amount, i.title, i.status, i.created_at, u.imie, u.nazwisko, u.email
        FROM invoices i
        JOIN users u ON i.sender_id = u.id
        WHERE i.recipient_id = %s
        ORDER BY i.id DESC
    """
    res = bank_service.sql(sql, (user_id,), many=True)
    invoices = []
    for r in res:
        invoices.append({
            "id": r[0],
            "amount": float(r[1]),
            "title": r[2],
            "status": r[3],
            "created_at": r[4].isoformat(),
            "sender_name": f"{r[5]} {r[6]}",
            "sender_email": r[7]
        })
    return jsonify({"status": "OK", "invoices": invoices})


@app.route("/api/invoices/sent", methods=["GET"])
@requires_auth
def api_invoices_sent(user_id):
    sql = """
        SELECT i.id, i.amount, i.title, i.status, i.created_at, u.imie, u.nazwisko, u.email
        FROM invoices i
        JOIN users u ON i.recipient_id = u.id
        WHERE i.sender_id = %s
        ORDER BY i.id DESC
    """
    res = bank_service.sql(sql, (user_id,), many=True)
    invoices = []
    for r in res:
        invoices.append({
            "id": r[0],
            "amount": float(r[1]),
            "title": r[2],
            "status": r[3],
            "created_at": r[4].isoformat(),
            "recipient_name": f"{r[5]} {r[6]}",
            "recipient_email": r[7]
        })
    return jsonify({"status": "OK", "invoices": invoices})


@app.route("/api/invoices/pay/<int:invoice_id>", methods=["POST"])
@requires_auth
def api_invoices_pay(user_id, invoice_id):
    sql = "SELECT sender_id, recipient_id, amount, title, status FROM invoices WHERE id = %s"
    res = bank_service.sql(sql, (invoice_id,), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Faktura nie istnieje"}), 404
        
    sender_id, recipient_id, amount, title, status = res
    amount = float(amount)
    
    if recipient_id != user_id:
        return jsonify({"status": "FAIL", "message": "Nie jesteś odbiorcą tej faktury"}), 403
    if status != 'UNPAID':
        return jsonify({"status": "FAIL", "message": "Ta faktura została już rozliczona lub odrzucona"}), 400
        
    # Nalicz inflację przed płatnością
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user["saldo"] < amount:
        return jsonify({"status": "FAIL", "message": "Brak wystarczających środków na koncie"}), 400
        
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount, user_id))
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount, sender_id))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (user_id, sender_id, amount, 'PAYMENT')
    )
    
    bank_service.sql("UPDATE invoices SET status = 'PAID' WHERE id = %s", (invoice_id,))
    
    add_reward_points(user_id, 10)
    add_reward_points(sender_id, 10)
    
    return jsonify({"status": "OK", "message": "Faktura została opłacona pomyślnie!"})


@app.route("/api/invoices/reject/<int:invoice_id>", methods=["POST"])
@requires_auth
def api_invoices_reject(user_id, invoice_id):
    sql = "SELECT recipient_id, status FROM invoices WHERE id = %s"
    res = bank_service.sql(sql, (invoice_id,), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Faktura nie istnieje"}), 404
    recipient_id, status = res
    if recipient_id != user_id:
        return jsonify({"status": "FAIL", "message": "Nie jesteś odbiorcą tej faktury"}), 403
    if status != 'UNPAID':
        return jsonify({"status": "FAIL", "message": "Tej faktury nie można już odrzucić"}), 400
        
    bank_service.sql("UPDATE invoices SET status = 'REJECTED' WHERE id = %s", (invoice_id,))
    return jsonify({"status": "OK", "message": "Faktura została odrzucona."})


# --- ZBIÓRKI ---
@app.route("/api/fundraisers/create", methods=["POST"])
@requires_auth
def api_fundraisers_create(user_id):
    user = bank_service.get_user(user_id)
    if not user or not user.get("is_company"):
        return jsonify({"status": "FAIL", "message": "Tylko zweryfikowane firmy mogą organizować zbiórki"}), 403
        
    data = request.get_json() or {}
    title = data.get("title")
    desc = data.get("description", "")
    target = data.get("target_amount")
    
    if not title or not target:
        return jsonify({"status": "FAIL", "message": "Tytuł i kwota docelowa są wymagane"}), 400
        
    try:
        target_val = float(target)
        if target_val <= 0:
            return jsonify({"status": "FAIL", "message": "Kwota musi być dodatnia"}), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
        
    sql = "INSERT INTO fundraisers (company_id, title, description, target_amount, raised_amount, status) VALUES (%s, %s, %s, %s, 0, 'ACTIVE')"
    bank_service.sql(sql, (user_id, title, desc, target_val))
    add_reward_points(user_id, 30)
    return jsonify({"status": "OK", "message": "Zbiórka została pomyślnie utworzona!"})


@app.route("/api/fundraisers/list", methods=["GET"])
@requires_auth
def api_fundraisers_list(user_id):
    sql = """
        SELECT f.id, f.title, f.description, f.target_amount, f.raised_amount, f.status, f.created_at, u.company_name
        FROM fundraisers f
        JOIN users u ON f.company_id = u.id
        ORDER BY f.id DESC
    """
    res = bank_service.sql(sql, many=True)
    fundraisers = []
    for r in res:
        fundraisers.append({
            "id": r[0],
            "title": r[1],
            "description": r[2],
            "target_amount": float(r[3]),
            "raised_amount": float(r[4]),
            "status": r[5],
            "created_at": r[6].isoformat(),
            "company_name": r[7]
        })
    return jsonify({"status": "OK", "fundraisers": fundraisers})


@app.route("/api/fundraisers/donate", methods=["POST"])
@requires_auth
def api_fundraisers_donate(user_id):
    data = request.get_json() or {}
    fund_id = data.get("fundraiser_id")
    amount = data.get("amount")
    
    if not fund_id or not amount:
        return jsonify({"status": "FAIL", "message": "Identyfikator zbiórki i kwota są wymagane"}), 400
        
    try:
        amount_val = float(amount)
        if amount_val <= 0:
            return jsonify({"status": "FAIL", "message": "Kwota musi być dodatnia"}), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
        
    sql = "SELECT company_id, title, status FROM fundraisers WHERE id = %s"
    res = bank_service.sql(sql, (fund_id,), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Zbiórka nie istnieje"}), 404
        
    company_id, title, status = res
    if status != 'ACTIVE':
        return jsonify({"status": "FAIL", "message": "Zbiórka została już zakończona"}), 400
        
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user["saldo"] < amount_val:
        return jsonify({"status": "FAIL", "message": "Brak wystarczających środków na koncie"}), 400
        
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount_val, user_id))
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount_val, company_id))
    bank_service.sql("UPDATE fundraisers SET raised_amount = raised_amount + %s WHERE id = %s", (amount_val, fund_id))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (user_id, company_id, amount_val, 'PAYMENT')
    )
    
    add_reward_points(user_id, 15)
    
    raised_res = bank_service.sql("SELECT raised_amount, target_amount FROM fundraisers WHERE id = %s", (fund_id,), fetch=True)
    if raised_res and raised_res[0] >= raised_res[1]:
        bank_service.sql("UPDATE fundraisers SET status = 'COMPLETED' WHERE id = %s", (fund_id,))
        
    return jsonify({"status": "OK", "message": "Darowizna została przekazana pomyślnie!"})


# --- KREDYTY I LOKATY ---
@app.route("/api/loans/request", methods=["POST"])
@requires_auth
def api_loans_request(user_id):
    data = request.get_json() or {}
    amount = data.get("amount")
    term = data.get("term_months")
    
    if not amount or not term:
        return jsonify({"status": "FAIL", "message": "Kwota i okres spłaty są wymagane"}), 400
        
    try:
        amount_val = float(amount)
        term_val = int(term)
        if amount_val <= 0 or term_val <= 0:
            return jsonify({"status": "FAIL", "message": "Kwota i okres muszą być dodatnie"}), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Niepoprawne dane kwoty lub okresu"}), 400
        
    int_res = bank_service.sql("SELECT value FROM global_settings WHERE key = 'interest_rate'", fetch=True)
    interest_rate = float(int_res[0]) if int_res else 4.5
    
    total_repayment = amount_val * (1 + (interest_rate / 100.0) * (term_val / 12.0))
    monthly_installment = round(total_repayment / term_val, 2)
    total_repayment = round(total_repayment, 2)
    
    sql = """
        INSERT INTO loans (user_id, amount, interest_rate, term_months, remaining_amount, monthly_installment, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'APPROVED')
    """
    bank_service.sql(sql, (user_id, amount_val, interest_rate, term_val, total_repayment, monthly_installment))
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount_val, user_id))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (None, user_id, amount_val, 'DEPOSIT')
    )
    
    add_reward_points(user_id, 30)
    
    return jsonify({
        "status": "OK",
        "message": f"Kredyt na kwotę {amount_val:.2f} PLN został przyznany automatycznie. Rata miesięczna: {monthly_installment:.2f} PLN."
    })


@app.route("/api/loans/list", methods=["GET"])
@requires_auth
def api_loans_list(user_id):
    sql = "SELECT id, amount, interest_rate, term_months, remaining_amount, monthly_installment, status, created_at FROM loans WHERE user_id = %s ORDER BY id DESC"
    res = bank_service.sql(sql, (user_id,), many=True)
    loans = []
    for r in res:
        loans.append({
            "id": r[0],
            "amount": float(r[1]),
            "interest_rate": float(r[2]),
            "term_months": r[3],
            "remaining_amount": float(r[4]),
            "monthly_installment": float(r[5]),
            "status": r[6],
            "created_at": r[7].isoformat()
        })
    return jsonify({"status": "OK", "loans": loans})


@app.route("/api/loans/pay-installment/<int:loan_id>", methods=["POST"])
@requires_auth
def api_loans_pay_installment(user_id, loan_id):
    sql = "SELECT remaining_amount, monthly_installment, status FROM loans WHERE id = %s AND user_id = %s"
    res = bank_service.sql(sql, (loan_id, user_id), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Kredyt nie istnieje"}), 404
        
    remaining_amount, installment, status = res
    remaining_amount = float(remaining_amount)
    installment = float(installment)
    
    if status == 'PAID':
        return jsonify({"status": "FAIL", "message": "Ten kredyt został już spłacony"}), 400
        
    pay_amount = min(installment, remaining_amount)
    
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user["saldo"] < pay_amount:
        return jsonify({"status": "FAIL", "message": "Brak wystarczających środków na koncie"}), 400
        
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (pay_amount, user_id))
    new_remaining = round(remaining_amount - pay_amount, 2)
    new_status = 'APPROVED' if new_remaining > 0 else 'PAID'
    
    bank_service.sql("UPDATE loans SET remaining_amount = %s, status = %s WHERE id = %s", (new_remaining, new_status, loan_id))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (user_id, None, pay_amount, 'WITHDRAW')
    )
    
    add_reward_points(user_id, 10)
    
    return jsonify({
        "status": "OK",
        "message": f"Spłacono ratę w kwocie {pay_amount:.2f} PLN. Pozostała kwota: {new_remaining:.2f} PLN."
    })


@app.route("/api/deposits/create", methods=["POST"])
@requires_auth
def api_deposits_create(user_id):
    data = request.get_json() or {}
    amount = data.get("amount")
    
    if not amount:
        return jsonify({"status": "FAIL", "message": "Kwota lokaty jest wymagana"}), 400
        
    try:
        amount_val = float(amount)
        if amount_val < 100:
            return jsonify({"status": "FAIL", "message": "Minimalna kwota lokaty to 100 PLN"}), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
        
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user["saldo"] < amount_val:
        return jsonify({"status": "FAIL", "message": "Brak wystarczających środków na koncie"}), 400
        
    int_res = bank_service.sql("SELECT value FROM global_settings WHERE key = 'interest_rate'", fetch=True)
    interest_rate = float(int_res[0]) if int_res else 4.5
    
    now = datetime.now()
    expires_at = now + timedelta(hours=1)
    
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount_val, user_id))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (user_id, None, amount_val, 'WITHDRAW')
    )
    
    sql = "INSERT INTO hourly_deposits (user_id, amount, interest_rate, created_at, expires_at, status) VALUES (%s, %s, %s, %s, %s, 'ACTIVE')"
    bank_service.sql(sql, (user_id, amount_val, interest_rate, now, expires_at))
    
    add_reward_points(user_id, 15)
    
    return jsonify({
        "status": "OK",
        "message": f"Lokata godzinowa na kwotę {amount_val:.2f} PLN została pomyślnie otwarta!"
    })


@app.route("/api/deposits/list", methods=["GET"])
@requires_auth
def api_deposits_list(user_id):
    sql = "SELECT id, amount, interest_rate, created_at, expires_at, status FROM hourly_deposits WHERE user_id = %s ORDER BY id DESC"
    res = bank_service.sql(sql, (user_id,), many=True)
    deposits = []
    for r in res:
        deposits.append({
            "id": r[0],
            "amount": float(r[1]),
            "interest_rate": float(r[2]),
            "created_at": r[3].isoformat(),
            "expires_at": r[4].isoformat(),
            "status": r[5]
        })
    return jsonify({"status": "OK", "deposits": deposits})


# --- UMOWY (KSIĘGOWOŚĆ I PODPISYWANIE UMÓW) ---
@app.route("/api/agreements/create", methods=["POST"])
@requires_auth
def api_agreements_create(user_id):
    data = request.get_json() or {}
    recipient = data.get("recipient")
    title = data.get("title")
    content = data.get("content")
    amount = data.get("amount", 0.0)
    pin = data.get("pin")
    
    if not recipient or not title or not content or not pin:
        return jsonify({"status": "FAIL", "message": "Odbiorca, tytuł, treść umowy oraz Twój PIN są wymagane"}), 400
        
    try:
        amount_val = float(amount)
        if amount_val < 0:
            return jsonify({"status": "FAIL", "message": "Kwota nie może być ujemna"}), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
        
    sql_pin = "SELECT pin FROM users WHERE id = %s"
    res_pin = bank_service.sql(sql_pin, (user_id,), fetch=True)
    if not res_pin or res_pin[0] != pin:
        return jsonify({"status": "FAIL", "message": "Podany PIN autoryzacyjny jest niepoprawny"}), 400
        
    recipient_id = bank_service.resolve_recipient_id(str(recipient))
    if not recipient_id:
        return jsonify({"status": "FAIL", "message": "Odbiorca umowy nie został znaleziony"}), 404
    if recipient_id == user_id:
        return jsonify({"status": "FAIL", "message": "Nie możesz zawrzeć umowy z samym sobą"}), 400
        
    sig_raw = f"{user_id}-{title}-{content}-{amount_val}-{pin}-{datetime.now().isoformat()}"
    creator_sig = hashlib.sha256(sig_raw.encode()).hexdigest()
    
    sql = """
        INSERT INTO agreements (creator_id, signer_id, title, content, amount, status, creator_signature)
        VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)
    """
    bank_service.sql(sql, (user_id, recipient_id, title, content, amount_val, creator_sig))
    add_reward_points(user_id, 15)
    
    return jsonify({"status": "OK", "message": "Umowa została utworzona i opatrzona Twoim cyfrowym podpisem zabezpieczającym."})


@app.route("/api/agreements/list", methods=["GET"])
@requires_auth
def api_agreements_list(user_id):
    sql = """
        SELECT a.id, a.title, a.content, a.amount, a.status, a.creator_signature, a.signer_signature, a.created_at, a.signed_at,
               u1.imie, u1.nazwisko, u1.email, u2.imie, u2.nazwisko, u2.email
        FROM agreements a
        JOIN users u1 ON a.creator_id = u1.id
        JOIN users u2 ON a.signer_id = u2.id
        WHERE a.creator_id = %s OR a.signer_id = %s
        ORDER BY a.id DESC
    """
    res = bank_service.sql(sql, (user_id, user_id), many=True)
    agreements = []
    for r in res:
        agreements.append({
            "id": r[0],
            "title": r[1],
            "content": r[2],
            "amount": float(r[3]),
            "status": r[4],
            "creator_signature": r[5],
            "signer_signature": r[6],
            "created_at": r[7].isoformat(),
            "signed_at": r[8].isoformat() if r[8] else None,
            "creator_name": f"{r[9]} {r[10]}",
            "creator_email": r[11],
            "signer_name": f"{r[12]} {r[13]}",
            "signer_email": r[14]
        })
    return jsonify({"status": "OK", "agreements": agreements})


@app.route("/api/agreements/sign/<int:agreement_id>", methods=["POST"])
@requires_auth
def api_agreements_sign(user_id, agreement_id):
    data = request.get_json() or {}
    pin = data.get("pin")
    
    if not pin:
        return jsonify({"status": "FAIL", "message": "Podaj PIN, aby autoryzować podpis"}), 400
        
    sql_pin = "SELECT pin FROM users WHERE id = %s"
    res_pin = bank_service.sql(sql_pin, (user_id,), fetch=True)
    if not res_pin or res_pin[0] != pin:
        return jsonify({"status": "FAIL", "message": "Podany PIN autoryzacyjny jest niepoprawny"}), 400
        
    sql = "SELECT creator_id, signer_id, title, content, amount, status FROM agreements WHERE id = %s"
    res = bank_service.sql(sql, (agreement_id,), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Umowa nie istnieje"}), 404
        
    creator_id, signer_id, title, content, amount, status = res
    amount = float(amount)
    
    if signer_id != user_id:
        return jsonify({"status": "FAIL", "message": "Nie jesteś adresatem tej umowy"}), 403
    if status != 'PENDING':
        return jsonify({"status": "FAIL", "message": "Umowa została już podpisana lub odrzucona"}), 400
        
    if amount > 0:
        bank_service.apply_inflation_to_user(user_id)
        signer_user = bank_service.get_user(user_id)
        if signer_user["saldo"] < amount:
            return jsonify({"status": "FAIL", "message": f"Brak środków do podpisania umowy opiewającej na kwotę {amount:.2f} PLN"}), 400
            
        bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount, user_id))
        bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount, creator_id))
        
        bank_service.sql(
            "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
            (user_id, creator_id, amount, 'PAYMENT')
        )
        
    sig_raw = f"{user_id}-{title}-{content}-{amount}-{pin}-{datetime.now().isoformat()}"
    signer_sig = hashlib.sha256(sig_raw.encode()).hexdigest()
    
    now = datetime.now()
    bank_service.sql(
        "UPDATE agreements SET status = 'SIGNED', signer_signature = %s, signed_at = %s WHERE id = %s",
        (signer_sig, now, agreement_id)
    )
    
    add_reward_points(user_id, 30)
    add_reward_points(creator_id, 30)
    
    return jsonify({"status": "OK", "message": "Umowa została prawnie podpisana cyfrowo przez obie strony, a transakcja rozliczona."})


@app.route("/api/agreements/reject/<int:agreement_id>", methods=["POST"])
@requires_auth
def api_agreements_reject(user_id, agreement_id):
    sql = "SELECT signer_id, status FROM agreements WHERE id = %s"
    res = bank_service.sql(sql, (agreement_id,), fetch=True)
    if not res:
        return jsonify({"status": "FAIL", "message": "Umowa nie istnieje"}), 404
    signer_id, status = res
    if signer_id != user_id:
        return jsonify({"status": "FAIL", "message": "Nie jesteś adresatem tej umowy"}), 403
    if status != 'PENDING':
        return jsonify({"status": "FAIL", "message": "Ta umowa nie jest już w statusie oczekiwania"}), 400
        
    bank_service.sql("UPDATE agreements SET status = 'REJECTED' WHERE id = %s", (agreement_id,))
    return jsonify({"status": "OK", "message": "Umowa została odrzucona."})


# --- PROGRAM NAGRÓD (LOYALTY) ---
# --- (Rewards exchange moved to alias routes section below) ---



# --- GIEŁDA PAPIERÓW WARTOŚCIOWYCH ---
@app.route("/api/stocks/list", methods=["GET"])
@requires_auth
def api_stocks_list(user_id):
    res = bank_service.sql("SELECT symbol, name, current_price FROM stocks ORDER BY symbol ASC", many=True)
    stocks = []
    for r in res:
        hist = bank_service.sql("SELECT price FROM stock_history WHERE symbol = %s ORDER BY id DESC LIMIT 10", (r[0],), many=True)
        prev_price = float(hist[-1][0]) if len(hist) > 1 else float(r[2])
        curr_price = float(r[2])
        change_pct = round(((curr_price - prev_price) / prev_price) * 100, 2) if prev_price > 0 else 0.0
        
        stocks.append({
            "symbol": r[0],
            "name": r[1],
            "current_price": curr_price,
            "change_pct": change_pct
        })
    return jsonify({"status": "OK", "stocks": stocks})


@app.route("/api/stocks/history/<symbol>", methods=["GET"])
@requires_auth
def api_stocks_history(user_id, symbol):
    res = bank_service.sql(
        "SELECT price, timestamp FROM stock_history WHERE symbol = %s ORDER BY id DESC LIMIT 50",
        (symbol,), many=True
    )
    history = []
    for r in reversed(res):
        history.append({
            "price": float(r[0]),
            "timestamp": r[1].isoformat()
        })
    return jsonify({"status": "OK", "history": history})


@app.route("/api/stocks/portfolio", methods=["GET"])
@requires_auth
def api_stocks_portfolio(user_id):
    sql = """
        SELECT us.symbol, us.shares, us.avg_buy_price, s.name, s.current_price
        FROM user_stocks us
        JOIN stocks s ON us.symbol = s.symbol
        WHERE us.user_id = %s AND us.shares > 0
        ORDER BY us.symbol ASC
    """
    res = bank_service.sql(sql, (user_id,), many=True)
    portfolio = []
    total_val = 0.0
    for r in res:
        symbol, shares, avg_buy, name, curr_price = r
        avg_buy = float(avg_buy)
        curr_price = float(curr_price)
        val = shares * curr_price
        total_val += val
        pnl = (curr_price - avg_buy) * shares
        pnl_pct = round((pnl / (avg_buy * shares)) * 100, 2) if avg_buy > 0 else 0.0
        
        portfolio.append({
            "symbol": symbol,
            "name": name,
            "shares": shares,
            "avg_buy_price": avg_buy,
            "current_price": curr_price,
            "value": val,
            "pnl": pnl,
            "pnl_pct": pnl_pct
        })
    return jsonify({"status": "OK", "portfolio": portfolio, "total_value": total_val})


@app.route("/api/stocks/buy", methods=["POST"])
@requires_auth
def api_stocks_buy(user_id):
    data = request.get_json() or {}
    symbol = data.get("symbol")
    try:
        shares = int(data.get("shares", 0))
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Liczba akcji musi być liczbą"}), 400
        
    if not symbol or shares <= 0:
        return jsonify({"status": "FAIL", "message": "Niepoprawne dane zakupu"}), 400
        
    stock_res = bank_service.sql("SELECT name, current_price FROM stocks WHERE symbol = %s", (symbol,), fetch=True)
    if not stock_res:
        return jsonify({"status": "FAIL", "message": "Spółka nie istnieje"}), 404
    name, current_price = stock_res
    current_price = float(current_price)
    
    total_cost = round(shares * current_price, 2)
    
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user["saldo"] < total_cost:
        return jsonify({"status": "FAIL", "message": f"Brak wystarczających środków. Koszt: {total_cost:.2f} PLN."}), 400
        
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (total_cost, user_id))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (user_id, None, total_cost, 'WITHDRAW')
    )
    
    port_res = bank_service.sql("SELECT shares, avg_buy_price FROM user_stocks WHERE user_id = %s AND symbol = %s", (user_id, symbol), fetch=True)
    if port_res:
        curr_shares, curr_avg = port_res
        new_shares = curr_shares + shares
        new_avg = round(((curr_shares * float(curr_avg)) + total_cost) / new_shares, 2)
        bank_service.sql("UPDATE user_stocks SET shares = %s, avg_buy_price = %s WHERE user_id = %s AND symbol = %s", (new_shares, new_avg, user_id, symbol))
    else:
        bank_service.sql("INSERT INTO user_stocks (user_id, symbol, shares, avg_buy_price) VALUES (%s, %s, %s, %s)", (user_id, symbol, shares, current_price))
        
    add_reward_points(user_id, 10)
    
    return jsonify({"status": "OK", "message": f"Zakupiono pomyślnie {shares} akcji {symbol} za {total_cost:.2f} PLN."})


@app.route("/api/stocks/sell", methods=["POST"])
@requires_auth
def api_stocks_sell(user_id):
    data = request.get_json() or {}
    symbol = data.get("symbol")
    try:
        shares = int(data.get("shares", 0))
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Liczba akcji musi być liczbą"}), 400
        
    if not symbol or shares <= 0:
        return jsonify({"status": "FAIL", "message": "Niepoprawne dane sprzedaży"}), 400
        
    port_res = bank_service.sql("SELECT shares FROM user_stocks WHERE user_id = %s AND symbol = %s", (user_id, symbol), fetch=True)
    if not port_res or port_res[0] < shares:
        return jsonify({"status": "FAIL", "message": "Brak wystarczającej liczby akcji w portfelu"}), 400
        
    curr_shares = port_res[0]
    
    stock_res = bank_service.sql("SELECT current_price FROM stocks WHERE symbol = %s", (symbol,), fetch=True)
    if not stock_res:
        return jsonify({"status": "FAIL", "message": "Spółka nie istnieje"}), 404
    current_price = float(stock_res[0])
    
    total_revenue = round(shares * current_price, 2)
    
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (total_revenue, user_id))
    
    new_shares = curr_shares - shares
    bank_service.sql("UPDATE user_stocks SET shares = %s WHERE user_id = %s AND symbol = %s", (new_shares, user_id, symbol))
    
    bank_service.sql(
        "INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, %s)",
        (None, user_id, total_revenue, 'DEPOSIT')
    )
    
    add_reward_points(user_id, 10)
    
    return jsonify({"status": "OK", "message": f"Sprzedano pomyślnie {shares} akcji {symbol} za {total_revenue:.2f} PLN."})





# ================================================================
#  ALIAS / BRIDGE ROUTES  (frontend URL → backend handler)
# ================================================================

@app.route("/api/profile", methods=["GET"])
@requires_auth
def api_profile_alias(user_id):
    """Alias for /api/info – used by frontend settings view."""
    bank_service.apply_inflation_to_user(user_id)
    user = bank_service.get_user(user_id)
    if user:
        user["nr_karty_format"] = bank_service.format_card_number(user["nr_karty"])
        return jsonify({"status": "OK", "user": user})
    return jsonify({"status": "FAIL", "message": "Nie znaleziono użytkownika"}), 404


@app.route("/api/users/list", methods=["GET"])
@requires_auth
def api_users_list_alias(user_id):
    """Alias for /api/users – used by chat contacts list."""
    users = bank_service.get_other_users(user_id)
    return jsonify({"status": "OK", "users": users})


@app.route("/api/invoices/create", methods=["POST"])
@requires_auth
def api_invoices_create_alias(user_id):
    """Create an invoice. Schema: invoices(sender_id, recipient_id, amount, title, status=UNPAID)."""
    data = request.get_json() or {}
    recipient = data.get("recipient")
    try:
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
    title = data.get("title", "Faktura")
    if not recipient or amount <= 0:
        return jsonify({"status": "FAIL", "message": "Brak danych faktury"}), 400
    recipient_id = bank_service.resolve_recipient_id(str(recipient))
    if not recipient_id:
        return jsonify({"status": "FAIL", "message": f"Odbiorca '{recipient}' nie odnaleziony"}), 404
    bank_service.sql(
        "INSERT INTO invoices (sender_id, recipient_id, amount, title, status) VALUES (%s, %s, %s, %s, 'UNPAID')",
        (user_id, recipient_id, amount, title)
    )
    add_reward_points(user_id, 5)
    return jsonify({"status": "OK", "message": f"Wystawiono fakturę na {amount:.2f} PLN dla odbiorcy."})


@app.route("/api/invoices/pay", methods=["POST"])
@requires_auth
def api_invoices_pay_alias(user_id):
    """POST body: {invoice_id}. Schema: invoices(sender_id, status=UNPAID/PAID)."""
    data = request.get_json() or {}
    try:
        invoice_id = int(data.get("invoice_id", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawny ID faktury"}), 400
    inv = bank_service.sql(
        "SELECT id, sender_id, recipient_id, amount, title, status FROM invoices WHERE id = %s AND recipient_id = %s AND status = 'UNPAID'",
        (invoice_id, user_id), many=True
    )
    if not inv:
        return jsonify({"status": "FAIL", "message": "Faktura nie istnieje lub już opłacona"}), 404
    inv = inv[0] if isinstance(inv, list) else inv
    if isinstance(inv, dict):
        amount = float(inv["amount"])
        sender_id = inv["sender_id"]
    else:
        amount = float(inv[3])
        sender_id = inv[1]
    bal = bank_service.get_balance(user_id)
    if float(bal.get("saldo", 0)) < amount:
        return jsonify({"status": "FAIL", "message": "Niewystarczające środki na saldzie"}), 400
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount, user_id))
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount, sender_id))
    bank_service.sql("UPDATE invoices SET status = 'PAID' WHERE id = %s", (invoice_id,))
    bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, 'TRANSFER')", (user_id, sender_id, amount))
    add_reward_points(user_id, 5)
    return jsonify({"status": "OK", "message": f"Faktura {invoice_id} opłacona pomyślnie ({amount:.2f} PLN)."})


@app.route("/api/loans/create", methods=["POST"])
@requires_auth
def api_loans_create_alias(user_id):
    """Create a loan. Schema: loans(user_id, amount, interest_rate, term_months, remaining_amount, monthly_installment, status=APPROVED)."""
    data = request.get_json() or {}
    try:
        amount = float(data.get("amount", 0))
        term_months = int(data.get("term_months", 12))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawne dane kredytu"}), 400
    if amount < 10:
        return jsonify({"status": "FAIL", "message": "Minimalna kwota kredytu to 10 PLN"}), 400
    settings = bank_service.get_bank_settings()
    annual_rate = float(settings.get("interest_rate", 5.0))
    monthly_rate = annual_rate / 100.0 / 12.0
    if monthly_rate > 0:
        monthly_installment = amount * (monthly_rate * (1 + monthly_rate) ** term_months) / ((1 + monthly_rate) ** term_months - 1)
    else:
        monthly_installment = amount / term_months
    monthly_installment = round(monthly_installment, 2)
    remaining_amount = round(monthly_installment * term_months, 2)
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount, user_id))
    bank_service.sql(
        "INSERT INTO loans (user_id, amount, interest_rate, term_months, remaining_amount, monthly_installment, status) VALUES (%s, %s, %s, %s, %s, %s, 'APPROVED')",
        (user_id, amount, annual_rate, term_months, remaining_amount, monthly_installment)
    )
    bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, 'DEPOSIT')", (None, user_id, amount))
    return jsonify({"status": "OK", "message": f"Kredyt {amount:.2f} PLN ({term_months} mies.) przyznany. Rata: {monthly_installment:.2f} PLN/mies."})


@app.route("/api/loans/repay", methods=["POST"])
@requires_auth
def api_loans_repay_alias(user_id):
    """POST body: {loan_id}. Schema: loans(monthly_installment, remaining_amount, status=APPROVED/PAID)."""
    data = request.get_json() or {}
    try:
        loan_id = int(data.get("loan_id", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawny ID kredytu"}), 400
    loan = bank_service.sql(
        "SELECT id, user_id, amount, remaining_amount, monthly_installment, status FROM loans WHERE id = %s AND user_id = %s AND status = 'APPROVED'",
        (loan_id, user_id), many=True
    )
    if not loan:
        return jsonify({"status": "FAIL", "message": "Kredyt nie istnieje lub już spłacony"}), 404
    loan = loan[0] if isinstance(loan, list) else loan
    if isinstance(loan, dict):
        monthly_installment = float(loan["monthly_installment"])
        remaining = float(loan["remaining_amount"])
    else:
        monthly_installment = float(loan[4])
        remaining = float(loan[3])
    bal = bank_service.get_balance(user_id)
    if float(bal.get("saldo", 0)) < monthly_installment:
        return jsonify({"status": "FAIL", "message": "Niewystarczające środki na saldzie"}), 400
    new_remaining = max(0.0, remaining - monthly_installment)
    new_status = "PAID" if new_remaining <= 0 else "APPROVED"
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (monthly_installment, user_id))
    bank_service.sql("UPDATE loans SET remaining_amount = %s, status = %s WHERE id = %s", (new_remaining, new_status, loan_id))
    bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, 'WITHDRAW')", (user_id, None, monthly_installment))
    msg = f"Rata {monthly_installment:.2f} PLN spłacona." + (" Kredyt w pełni spłacony!" if new_status == "PAID" else f" Pozostało: {new_remaining:.2f} PLN.")
    return jsonify({"status": "OK", "message": msg})


@app.route("/api/agreements/sign", methods=["POST"])
@requires_auth
def api_agreements_sign_alias(user_id):
    """POST body: {agreement_id, pin}. Schema: agreements(creator_id, signer_id, status=PENDING/SIGNED)."""
    data = request.get_json() or {}
    try:
        agreement_id = int(data.get("agreement_id", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawny ID umowy"}), 400
    pin = str(data.get("pin", ""))
    user = bank_service.get_user(user_id)
    if not user or str(user.get("pin", "")) != pin:
        return jsonify({"status": "FAIL", "message": "Niepoprawny PIN autoryzacyjny"}), 403
    agr = bank_service.sql(
        "SELECT id FROM agreements WHERE id = %s AND signer_id = %s AND status = 'PENDING'",
        (agreement_id, user_id), many=True
    )
    if not agr:
        return jsonify({"status": "FAIL", "message": "Umowa nie istnieje, nie jest do Ciebie skierowana, lub już podpisana"}), 404
    bank_service.sql(
        "UPDATE agreements SET status = 'SIGNED', signer_signature = %s, signed_at = CURRENT_TIMESTAMP WHERE id = %s",
        (f"PIN_AUTH_{user_id}", agreement_id)
    )
    return jsonify({"status": "OK", "message": "Umowa podpisana pomyślnie."})


@app.route("/api/agreements/<int:agreement_id>", methods=["GET"])
@requires_auth
def api_agreement_get(user_id, agreement_id):
    """Get a single agreement for preview. Schema: agreements(creator_id, signer_id)."""
    agr = bank_service.sql(
        """SELECT a.id, a.creator_id, a.signer_id, a.title, a.content, a.amount, a.status, a.created_at,
           CONCAT(ua.imie, ' ', ua.nazwisko) AS party_a_name,
           CONCAT(ub.imie, ' ', ub.nazwisko) AS party_b_name
           FROM agreements a
           LEFT JOIN users ua ON ua.id = a.creator_id
           LEFT JOIN users ub ON ub.id = a.signer_id
           WHERE a.id = %s AND (a.creator_id = %s OR a.signer_id = %s)""",
        (agreement_id, user_id, user_id), many=True
    )
    if not agr:
        return jsonify({"status": "FAIL", "message": "Umowa nie znaleziona"}), 404
    row = agr[0] if isinstance(agr, list) else agr
    if isinstance(row, dict):
        result = {
            "id": row.get("id"), "party_a_name": row.get("party_a_name"), "party_b_name": row.get("party_b_name"),
            "title": row.get("title"), "content": row.get("content"),
            "amount": str(row.get("amount", 0)), "status": row.get("status"),
            "created_at": str(row.get("created_at", ""))
        }
    else:
        result = {
            "id": row[0], "party_a_name": row[8], "party_b_name": row[9],
            "title": row[3], "content": row[4],
            "amount": str(row[5]), "status": row[6], "created_at": str(row[7])
        }
    return jsonify({"status": "OK", "agreement": result})


@app.route("/api/chat/messages", methods=["GET"])
@requires_auth
def api_chat_messages_alias(user_id):
    """GET ?partner_id=X. Uses e2e_messages(from_user, to_user, encrypted_message, created_at).
    Returns plain content for frontend display (encrypted_message as content)."""
    try:
        partner_id = int(request.args.get("partner_id", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawny partner_id"}), 400
    msgs = bank_service.sql(
        """SELECT id, from_user, to_user, encrypted_message, created_at
           FROM e2e_messages
           WHERE (from_user = %s AND to_user = %s)
              OR (from_user = %s AND to_user = %s)
           ORDER BY id ASC LIMIT 100""",
        (user_id, partner_id, partner_id, user_id), many=True
    )
    result = []
    if msgs:
        for m in msgs:
            if isinstance(m, dict):
                result.append({
                    "id": m.get("id"), "sender_id": m.get("from_user"),
                    "recipient_id": m.get("to_user"),
                    "content": m.get("encrypted_message", ""),
                    "sent_at": str(m.get("created_at", ""))
                })
            else:
                result.append({"id": m[0], "sender_id": m[1], "recipient_id": m[2], "content": m[3], "sent_at": str(m[4])})
    return jsonify({"status": "OK", "messages": result})


@app.route("/api/chat/send", methods=["POST"])
@requires_auth
def api_chat_send_alias(user_id):
    """Send a chat message. Accepts plain 'content' or full E2E encrypted payload."""
    data = request.get_json() or {}
    recipient_id = data.get("recipient_id")
    # Accept plain content (frontend simplified mode)
    content = data.get("content") or data.get("encrypted_message", "")
    if not recipient_id or not content:
        return jsonify({"status": "FAIL", "message": "Brak danych wiadomości"}), 400
    bank_service.sql(
        "INSERT INTO e2e_messages (from_user, to_user, encrypted_message, encrypted_key_sender, encrypted_key_recipient) VALUES (%s, %s, %s, '', '')",
        (user_id, recipient_id, content)
    )
    add_reward_points(user_id, 2)
    return jsonify({"status": "OK", "message": "Wiadomość wysłana."})


@app.route("/api/stocks/history", methods=["GET"])
@requires_auth
def api_stocks_history_alias(user_id):
    """GET ?symbol=X. Schema: stock_history(symbol, price, timestamp)."""
    symbol = request.args.get("symbol", "")
    if not symbol:
        return jsonify({"status": "FAIL", "message": "Brak symbolu"}), 400
    hist = bank_service.sql(
        "SELECT price, timestamp FROM stock_history WHERE symbol = %s ORDER BY timestamp ASC LIMIT 200",
        (symbol,), many=True
    )
    result = []
    if hist:
        for h in hist:
            if isinstance(h, dict):
                result.append({"price": str(h.get("price")), "recorded_at": str(h.get("timestamp", ""))})
            else:
                result.append({"price": str(h[0]), "recorded_at": str(h[1])})
    return jsonify({"status": "OK", "history": result})


@app.route("/api/settings/2fa", methods=["POST"])
@requires_auth
def api_settings_2fa_alias(user_id):
    """Set 2FA method directly. Alias for toggle-2fa."""
    data = request.get_json() or {}
    method = data.get("method", "NONE")
    code = data.get("code", "")
    
    if method not in ("NONE", "EMAIL", "TOTP"):
        return jsonify({"status": "FAIL", "message": "Niepoprawna metoda 2FA"}), 400

    user = bank_service.get_user(user_id)
    email = user.get("email")

    if method == "TOTP":
        if not code:
            import pyotp
            import qrcode
            import io
            import base64
            
            secret = pyotp.random_base32()
            bank_service.sql("UPDATE users SET totp_secret = %s WHERE id = %s", (secret, user_id))
            
            uri = f"otpauth://totp/PathlBank:{email}?secret={secret}&issuer=PathlBank"
            
            qr = qrcode.QRCode()
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            qr_code_base64 = f"data:image/png;base64,{img_str}"
            
            return jsonify({
                "status": "REQUIRE_VERIFICATION",
                "secret": secret,
                "qr_code": qr_code_base64,
                "message": "Zeskanuj kod w Google Authenticator"
            })
        else:
            import pyotp
            res_totp = bank_service.sql("SELECT totp_secret FROM users WHERE id = %s", (user_id,), fetch=True)
            totp_secret = res_totp[0] if res_totp else None
            if not totp_secret:
                return jsonify({"status": "FAIL", "message": "Brak konfiguracji TOTP"}), 400
            
            totp = pyotp.TOTP(totp_secret)
            if not totp.verify(code):
                return jsonify({"status": "FAIL", "message": "Nieprawidłowy kod TOTP"}), 400
            
            bank_service.sql("UPDATE users SET two_factor_method = 'TOTP' WHERE id = %s", (user_id,))
            return jsonify({"status": "OK", "message": "Weryfikacja 2FA ustawiona: Google Authenticator (TOTP)."})

    bank_service.sql("UPDATE users SET two_factor_method = %s WHERE id = %s", (method, user_id))
    labels = {"NONE": "wyłączone", "EMAIL": "OTP na e-mail", "TOTP": "Google Authenticator (TOTP)"}
    return jsonify({"status": "OK", "message": f"Weryfikacja 2FA ustawiona: {labels[method]}."})


@app.route("/api/rewards", methods=["GET"])
@requires_auth
def api_rewards_get(user_id):
    """Return user's current reward points."""
    user = bank_service.get_user(user_id)
    pts = int(user.get("reward_points", 0)) if user else 0
    return jsonify({"status": "OK", "points": pts})


@app.route("/api/rewards/exchange", methods=["POST"])
@requires_auth
def api_rewards_exchange_v2(user_id):
    """Accept either 'option' or 'points' key for exchange amount."""
    data = request.get_json() or {}
    option = data.get("points") or data.get("option")
    try:
        option = int(option)
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawna liczba punktów"}), 400
    if option not in [100, 500, 1000]:
        return jsonify({"status": "FAIL", "message": "Dostępne progi: 100, 500, 1000 punktów"}), 400
    user = bank_service.get_user(user_id)
    pts = int(user.get("reward_points", 0)) if user else 0
    if pts < option:
        return jsonify({"status": "FAIL", "message": f"Za mało punktów. Posiadasz: {pts} pkt."}), 400
    cashback_map = {100: 10.00, 500: 60.00, 1000: 150.00}
    cashback = cashback_map[option]
    bank_service.sql("UPDATE users SET reward_points = reward_points - %s, saldo = saldo + %s WHERE id = %s", (option, cashback, user_id))
    bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, 'DEPOSIT')", (None, user_id, cashback))
    return jsonify({"status": "OK", "message": f"Wymieniono {option} pkt na {cashback:.2f} PLN cashback!"})


# --- API dla lokat frontend (hourly_deposits) ---
@app.route("/api/deposits/list", methods=["GET"])
@requires_auth
def api_deposits_list_alias(user_id):
    """List hourly_deposits for the current user. Schema: hourly_deposits(user_id, amount, interest_rate, expires_at, status)."""
    deps = bank_service.sql(
        "SELECT id, amount, interest_rate, expires_at, status FROM hourly_deposits WHERE user_id = %s ORDER BY id DESC",
        (user_id,), many=True
    )
    result = []
    if deps:
        for d in deps:
            if isinstance(d, dict):
                result.append({
                    "id": d["id"], "amount": str(d["amount"]),
                    "interest_rate": str(d["interest_rate"]),
                    "expires_at": str(d["expires_at"]), "status": d["status"]
                })
            else:
                result.append({"id": d[0], "amount": str(d[1]), "interest_rate": str(d[2]), "expires_at": str(d[3]), "status": d[4]})
    return jsonify({"status": "OK", "deposits": result})


@app.route("/api/deposits/create", methods=["POST"])
@requires_auth
def api_deposits_create_alias(user_id):
    """Create a 1-hour deposit. Schema: hourly_deposits."""
    data = request.get_json() or {}
    try:
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400
    if amount < 100:
        return jsonify({"status": "FAIL", "message": "Minimalna kwota lokaty to 100 PLN"}), 400
    bal = bank_service.get_balance(user_id)
    if float(bal.get("saldo", 0)) < amount:
        return jsonify({"status": "FAIL", "message": "Niewystarczające środki"}), 400
    settings = bank_service.get_bank_settings()
    interest_rate = float(settings.get("interest_rate", 4.5))
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount, user_id))
    bank_service.sql(
        "INSERT INTO hourly_deposits (user_id, amount, interest_rate, expires_at, status) VALUES (%s, %s, %s, NOW() + INTERVAL '1 hour', 'ACTIVE')",
        (user_id, amount, interest_rate)
    )
    bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, 'DEPOSIT')", (user_id, None, amount))
    add_reward_points(user_id, 10)
    return jsonify({"status": "OK", "message": f"Lokata {amount:.2f} PLN otwarta na 1 godzinę przy {interest_rate:.1f}%/h."})


# --- API dla zbiórek frontend ---
@app.route("/api/fundraisers/list", methods=["GET"])
@requires_auth
def api_fundraisers_list_alias(user_id):
    """List active fundraisers. Schema: fundraisers(company_id, title, description, target_amount, raised_amount)."""
    rows = bank_service.sql(
        """SELECT f.id, f.title, f.description, f.target_amount, f.raised_amount, f.status,
           u.company_name
           FROM fundraisers f
           JOIN users u ON u.id = f.company_id
           WHERE f.status = 'ACTIVE'
           ORDER BY f.id DESC""",
        many=True
    )
    result = []
    if rows:
        for r in rows:
            if isinstance(r, dict):
                result.append({
                    "id": r["id"], "title": r["title"], "description": r.get("description",""),
                    "goal_amount": str(r["target_amount"]), "collected": str(r["raised_amount"]),
                    "company_name": r.get("company_name", "Firma")
                })
            else:
                result.append({
                    "id": r[0], "title": r[1], "description": r[2] or "",
                    "goal_amount": str(r[3]), "collected": str(r[4]),
                    "company_name": r[6] or "Firma"
                })
    return jsonify({"status": "OK", "fundraisers": result})


@app.route("/api/fundraisers/create", methods=["POST"])
@requires_auth
def api_fundraisers_create_alias(user_id):
    """Create a fundraiser (companies only). Schema: fundraisers(company_id, title, description, target_amount)."""
    user = bank_service.get_user(user_id)
    if not user or not user.get("is_company"):
        return jsonify({"status": "FAIL", "message": "Tylko zarejestrowane firmy mogą tworzyć zbiórki"}), 403
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    try:
        goal_amount = float(data.get("goal_amount", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Kwota docelowa musi być liczbą"}), 400
    if not title or goal_amount < 10:
        return jsonify({"status": "FAIL", "message": "Brak tytułu lub zbyt mała kwota docelowa"}), 400
    bank_service.sql(
        "INSERT INTO fundraisers (company_id, title, description, target_amount, raised_amount, status) VALUES (%s, %s, %s, %s, 0, 'ACTIVE')",
        (user_id, title, description, goal_amount)
    )
    return jsonify({"status": "OK", "message": f"Zbiórka '{title}' uruchomiona."})


@app.route("/api/fundraisers/donate", methods=["POST"])
@requires_auth
def api_fundraisers_donate_alias(user_id):
    """Donate to a fundraiser. Schema: fundraisers(raised_amount)."""
    data = request.get_json() or {}
    try:
        fundraiser_id = int(data.get("fundraiser_id", 0))
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        return jsonify({"status": "FAIL", "message": "Niepoprawne dane wpłaty"}), 400
    if amount <= 0:
        return jsonify({"status": "FAIL", "message": "Kwota musi być dodatnia"}), 400
    fund = bank_service.sql(
        "SELECT id, company_id, raised_amount, target_amount FROM fundraisers WHERE id = %s AND status = 'ACTIVE'",
        (fundraiser_id,), many=True
    )
    if not fund:
        return jsonify({"status": "FAIL", "message": "Zbiórka nie istnieje lub zakończona"}), 404
    fund = fund[0] if isinstance(fund, list) else fund
    company_id = fund["company_id"] if isinstance(fund, dict) else fund[1]
    bal = bank_service.get_balance(user_id)
    if float(bal.get("saldo", 0)) < amount:
        return jsonify({"status": "FAIL", "message": "Niewystarczające środki"}), 400
    bank_service.sql("UPDATE users SET saldo = saldo - %s WHERE id = %s", (amount, user_id))
    bank_service.sql("UPDATE users SET saldo = saldo + %s WHERE id = %s", (amount, company_id))
    bank_service.sql("UPDATE fundraisers SET raised_amount = raised_amount + %s WHERE id = %s", (amount, fundraiser_id))
    bank_service.sql("INSERT INTO transactions (from_user, to_user, amount, type) VALUES (%s, %s, %s, 'TRANSFER')", (user_id, company_id, amount))
    add_reward_points(user_id, 5)
    return jsonify({"status": "OK", "message": f"Dziękujemy za wsparcie {amount:.2f} PLN!"})


# --- API dla umów frontend ---
@app.route("/api/agreements/list", methods=["GET"])
@requires_auth
def api_agreements_list_alias(user_id):
    """List agreements for the current user. Schema: agreements(creator_id, signer_id)."""
    pending = bank_service.sql(
        """SELECT a.id, a.title, a.amount, a.status,
           CONCAT(uc.imie, ' ', uc.nazwisko) AS party_a_name
           FROM agreements a
           JOIN users uc ON uc.id = a.creator_id
           WHERE a.signer_id = %s AND a.status = 'PENDING'
           ORDER BY a.id DESC""",
        (user_id,), many=True
    )
    signed = bank_service.sql(
        """SELECT a.id, a.title, a.amount, a.status,
           CONCAT(uc.imie, ' ', uc.nazwisko) AS party_a_name,
           CONCAT(us.imie, ' ', us.nazwisko) AS party_b_name
           FROM agreements a
           JOIN users uc ON uc.id = a.creator_id
           LEFT JOIN users us ON us.id = a.signer_id
           WHERE (a.creator_id = %s OR a.signer_id = %s) AND a.status != 'PENDING'
           ORDER BY a.id DESC LIMIT 50""",
        (user_id, user_id), many=True
    )

    def fmt_pending(r):
        if isinstance(r, dict):
            return {"id": r["id"], "title": r["title"], "amount": str(r["amount"]), "party_a_name": r["party_a_name"]}
        return {"id": r[0], "title": r[1], "amount": str(r[2]), "party_a_name": r[4]}

    def fmt_signed(r):
        if isinstance(r, dict):
            return {"id": r["id"], "title": r["title"], "amount": str(r["amount"]),
                    "status": r["status"], "party_a_name": r["party_a_name"], "party_b_name": r.get("party_b_name", "")}
        return {"id": r[0], "title": r[1], "amount": str(r[2]), "status": r[3], "party_a_name": r[4], "party_b_name": r[5] or ""}

    return jsonify({
        "status": "OK",
        "pending": [fmt_pending(r) for r in (pending or [])],
        "signed":  [fmt_signed(r)  for r in (signed  or [])]
    })


@app.route("/api/agreements/create", methods=["POST"])
@requires_auth
def api_agreements_create_alias(user_id):
    """Create an agreement. Schema: agreements(creator_id, signer_id, title, content, amount, status=PENDING)."""
    data = request.get_json() or {}
    recipient = data.get("recipient", "").strip()
    title   = data.get("title", "").strip()
    content = data.get("content", "").strip()
    pin     = str(data.get("pin", ""))
    try:
        amount = float(data.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0.0
    if not recipient or not title or not content:
        return jsonify({"status": "FAIL", "message": "Wypełnij wszystkie wymagane pola"}), 400
    user = bank_service.get_user(user_id)
    if not user or str(user.get("pin", "")) != pin:
        return jsonify({"status": "FAIL", "message": "Niepoprawny PIN autoryzacyjny"}), 403
    signer_id = bank_service.resolve_recipient_id(recipient)
    if not signer_id:
        return jsonify({"status": "FAIL", "message": f"Użytkownik '{recipient}' nie odnaleziony"}), 404
    bank_service.sql(
        "INSERT INTO agreements (creator_id, signer_id, title, content, amount, status, creator_signature) VALUES (%s, %s, %s, %s, %s, 'PENDING', %s)",
        (user_id, signer_id, title, content, amount, f"PIN_AUTH_{user_id}")
    )
    add_reward_points(user_id, 10)
    return jsonify({"status": "OK", "message": f"Umowa '{title}' utworzona i wysłana do podpisu."})


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", 5000))
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    logger.info(f"Uruchamianie serwera webowego Flask na {host}:{port}...")
    app.run(host=host, port=port, debug=True)
