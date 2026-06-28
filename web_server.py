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
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Wczytywanie konfiguracji z pliku .env
load_dotenv()

# Dodajemy katalog bieżący do ścieżki Pythona na wypadek importów
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server import Server, User, hash_password, verify_password, logger

app = Flask(__name__, static_folder="static")
CORS(app)  # Włączamy CORS na wypadek pracy z zewnętrznych domen

# Konfiguracja SMTP ze zmiennych środowiskowych
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")

# Słownik sesji webowych: token -> user_id
WEB_SESSIONS = {}
web_session_lock = threading.Lock()

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

                # ZAWSZE wysyłamy najpierw e-mail OTP jako pierwszy czynnik weryfikacji
                success, details = self.generate_and_send_email_otp(email)
                if not success:
                    return {"status": "FAIL", "message": f"Nie udało się wysłać kodu OTP ({details})"}
                
                # Generujemy tymczasowy token logowania
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
            user_obj.saldo or 0,
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
    """Wysyła kod potwierdzający na podany adres e-mail.
    W przypadku braku SMTP lub błędu, wypisuje kod w logach i konsoli."""
    subject = "Kod potwierdzajacy - Reset hasla"
    body = f"""Witaj!
 
Otrzymalismy prosbe o zresetowanie hasla do Twojego konta w PathlBank.
Twoj 6-cyfrowy kod potwierdzajacy to:
 
👉 {code} 👈
 
Kod jest wazny przez 10 minut. Jesli nie prosiles o zmiane hasla, zignoruj te wiadomosc.
 
Pozdrawiamy,
Zespol PathlBank"""

    # Wypisz kod w logach (zawsze jako mechanizm podglądu / fallbacku)
    logger.info(f"==================================================")
    logger.info(f"   KOD RESETU HASŁA DLA {to_email}: {code}   ")
    logger.info(f"==================================================")

    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP nie zostało w pełni skonfigurowane w .env. Użyto logowania w konsoli.")
        return False, "SMTP_NOT_CONFIGURED"

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to_email

        # Nawiązanie połączenia SMTP
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
    return send_from_directory(app.static_folder, "index.html")


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
        if auth_type == "EMAIL":
            # Sprawdź, czy użytkownik ma dodatkowo włączony TOTP (Google Authenticator)
            sql_totp = "SELECT two_factor_method FROM users WHERE id = %s"
            res_totp = bank_service.sql(sql_totp, (user_id,), fetch=True)
            if res_totp and res_totp[0] == 'TOTP':
                # Przejdź do weryfikacji drugiego czynnika (TOTP)
                with temp_auth_lock:
                    auth_info["type"] = "TOTP"
                    auth_info["attempts"] = 0
                return jsonify({
                    "status": "AWAITING_TOTP",
                    "temp_token": temp_token,
                    "message": "E-mail zweryfikowany! Podaj kod z aplikacji Google Authenticator."
                })

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
        return jsonify({"status": "OK", "message": "Wylogowano pomyślnie"})
    return jsonify({"status": "FAIL", "message": "Brak tokenu"}), 400


@app.route("/api/info", methods=["GET"])
@requires_auth
def api_info(user_id):
    user = bank_service.get_user(user_id)
    if user:
        user["nr_karty_format"] = bank_service.format_card_number(user["nr_karty"])
        return jsonify({"status": "OK", "user": user})
    return jsonify({"status": "FAIL", "message": "Nie znaleziono użytkownika"}), 404


@app.route("/api/balance", methods=["GET"])
@requires_auth
def api_balance(user_id):
    res = bank_service.get_balance(user_id)
    return jsonify(res)


@app.route("/api/deposit", methods=["POST"])
@requires_auth
def api_deposit(user_id):
    data = request.get_json() or {}
    try:
        amount = float(data.get("amount", 0))
        res = bank_service.deposit(user_id, amount)
        if res["status"] == "OK":
            return jsonify(res)
        return jsonify(res), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400


@app.route("/api/withdraw", methods=["POST"])
@requires_auth
def api_withdraw(user_id):
    data = request.get_json() or {}
    try:
        amount = float(data.get("amount", 0))
        res = bank_service.withdraw(user_id, amount)
        if res["status"] == "OK":
            return jsonify(res)
        return jsonify(res), 400
    except ValueError:
        return jsonify({"status": "FAIL", "message": "Kwota musi być liczbą"}), 400


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


if __name__ == "__main__":
    logger.info("Uruchamianie serwera webowego Flask na porcie 5000...")
    app.run(host="localhost", port=5000, debug=True)
