import socket
import psycopg
import random
import string
from datetime import datetime, timedelta
import logging
import sys
import threading
import hashlib
import os
import pyotp
import qrcode
import io

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        logging.FileHandler("bank_server.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("BankServer")

# Pomocnicze funkcje do haszowania haseł
def hash_password(password: str, salt: str = None) -> str:
    """Haszuje hasło za pomocą SHA256 z solą."""
    if not salt:
        salt = os.urandom(16).hex()
    hash_obj = hashlib.sha256((salt + password).encode('utf-8'))
    hashed = hash_obj.hexdigest()
    return f"{salt}:{hashed}"

def verify_password(stored_val: str, input_password: str) -> bool:
    """Weryfikuje hasło porównując z wartością zapisaną w bazie (obsługuje też plaintext dla wstecznej kompatybilności)."""
    if stored_val and ":" in stored_val:
        try:
            salt, hashed = stored_val.split(":", 1)
            hash_obj = hashlib.sha256((salt + input_password).encode('utf-8'))
            return hash_obj.hexdigest() == hashed
        except Exception:
            return False
    return stored_val == input_password


def verify_email_otp(email, code) -> bool:
    """Weryfikuje jednorazowy kod OTP wysłany na email.
    Zwraca True jeśli kod jest poprawny i ważny, False w przeciwnym razie."""
    try:
        with psycopg.connect(
            dbname="BankDb",
            user="postgres",
            password="770528",
            host="localhost"
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT otp_hash, otp_expires_at, failed_login_attempts, locked FROM users WHERE email = %s",
                    (email,)
                )
                res = cur.fetchone()
                if not res:
                    return False

                otp_hash, otp_expires_at, failed_attempts, locked = res
                if locked:
                    return False

                if not otp_hash or not otp_expires_at:
                    return False

                if datetime.now() > otp_expires_at:
                    cur.execute(
                        "UPDATE users SET otp_hash = NULL, otp_expires_at = NULL WHERE email = %s",
                        (email,)
                    )
                    conn.commit()
                    return False

                input_hash = hashlib.sha256(code.strip().encode('utf-8')).hexdigest()

                if input_hash == otp_hash:
                    cur.execute(
                        "UPDATE users SET otp_hash = NULL, otp_expires_at = NULL, failed_login_attempts = 0 WHERE email = %s",
                        (email,)
                    )
                    conn.commit()
                    return True
                else:
                    new_attempts = failed_attempts + 1
                    if new_attempts >= 3:
                        cur.execute(
                            "UPDATE users SET failed_login_attempts = %s, locked = TRUE WHERE email = %s",
                            (new_attempts, email)
                        )
                    else:
                        cur.execute(
                            "UPDATE users SET failed_login_attempts = %s WHERE email = %s",
                            (new_attempts, email)
                        )
                    conn.commit()
                    return False
    except Exception as e:
        logger.error(f"Błąd verify_email_otp dla {email}: {e}")
        return False


class Create:
    def __init__(self):
        self.source = "system"


class User:
    def __init__(
            self,
            *,
            id=None,
            imie,
            nazwisko,
            pesel,
            email,
            pin,
            haslo,
            saldo=0,
            nr_karty=None,
            creator=None,
            two_factor_method='NONE',
            totp_secret=None
    ):
        self.id = id
        self.imie = imie
        self.nazwisko = nazwisko
        self.pesel = pesel
        self.email = email
        self.pin = pin
        self.haslo = haslo
        self.saldo = saldo
        self.nr_karty = nr_karty
        self.creator = creator
        self.two_factor_method = two_factor_method
        self.totp_secret = totp_secret


class Server:
    def __init__(self, user_class):
        self.User = user_class
        # Używamy wątkowo-lokalnego połączenia bazy danych
        self.thread_local = threading.local()
        
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("localhost", 4300))
        self.znane = {
            "1234": "bankomat_warszawska"
        }
        self.running = True
        # Słownik do przechowywania sesji klientów i blokada wątkowa do jego synchronizacji
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.migrate_db()

    def migrate_db(self):
        """Uruchamia bezpieczną migrację bazy danych, aby dodać kolumny i tabele bankowości rzeczywistej."""
        logger.info("Rozpoczęcie migracji bazy danych...")
        try:
            sql_statements = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS two_factor_method VARCHAR(20) DEFAULT 'NONE';",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64);",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_hash VARCHAR(64);",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS otp_expires_at TIMESTAMP;",
                
                # Ustawienia i panel admina
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER DEFAULT 0;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_company BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS company_name TEXT;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS company_nip TEXT;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS company_regon TEXT;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS public_key TEXT;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS reward_points INTEGER DEFAULT 0;",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_inflation_applied TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
                "ALTER TABLE users ALTER COLUMN saldo SET DEFAULT 10000.00;",

                # Tabela czatu E2E
                """
                CREATE TABLE IF NOT EXISTS e2e_messages (
                    id SERIAL PRIMARY KEY,
                    from_user INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    to_user INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    encrypted_message TEXT NOT NULL,
                    encrypted_key_sender TEXT NOT NULL,
                    encrypted_key_recipient TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """,
                # Tabela faktur
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    id SERIAL PRIMARY KEY,
                    sender_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    recipient_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount NUMERIC(20,2) NOT NULL,
                    title TEXT NOT NULL,
                    status VARCHAR(20) DEFAULT 'UNPAID',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """,
                # Tabela zbiórek
                """
                CREATE TABLE IF NOT EXISTS fundraisers (
                    id SERIAL PRIMARY KEY,
                    company_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT,
                    target_amount NUMERIC(20,2) NOT NULL,
                    raised_amount NUMERIC(20,2) DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'ACTIVE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """,
                # Tabela kredytów
                """
                CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount NUMERIC(20,2) NOT NULL,
                    interest_rate NUMERIC(5,2) NOT NULL,
                    term_months INTEGER NOT NULL,
                    remaining_amount NUMERIC(20,2) NOT NULL,
                    monthly_installment NUMERIC(20,2) NOT NULL,
                    status VARCHAR(20) DEFAULT 'APPROVED',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """,
                # Tabela umów
                """
                CREATE TABLE IF NOT EXISTS agreements (
                    id SERIAL PRIMARY KEY,
                    creator_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    signer_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    amount NUMERIC(20,2) DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'PENDING',
                    creator_signature TEXT,
                    signer_signature TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    signed_at TIMESTAMP
                );
                """,
                # Tabela lokat godzinowych
                """
                CREATE TABLE IF NOT EXISTS hourly_deposits (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    amount NUMERIC(20,2) NOT NULL,
                    interest_rate NUMERIC(5,2) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    status VARCHAR(20) DEFAULT 'ACTIVE'
                );
                """,
                # Tabele giełdy
                """
                CREATE TABLE IF NOT EXISTS stocks (
                    symbol VARCHAR(10) PRIMARY KEY,
                    name TEXT NOT NULL,
                    current_price NUMERIC(20,2) NOT NULL
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS stock_history (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(10) REFERENCES stocks(symbol) ON DELETE CASCADE,
                    price NUMERIC(20,2) NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """,
                """
                CREATE TABLE IF NOT EXISTS user_stocks (
                    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    symbol VARCHAR(10) REFERENCES stocks(symbol) ON DELETE CASCADE,
                    shares INTEGER NOT NULL,
                    avg_buy_price NUMERIC(20,2) NOT NULL,
                    PRIMARY KEY(user_id, symbol)
                );
                """,
                # Tabela ustawień globalnych
                """
                CREATE TABLE IF NOT EXISTS global_settings (
                    key VARCHAR(50) PRIMARY KEY,
                    value VARCHAR(50) NOT NULL
                );
                """
            ]
            for statement in sql_statements:
                self.sql(statement)
                
            # Seeding giełdy
            stocks_count = self.sql("SELECT COUNT(*) FROM stocks", fetch=True)
            if stocks_count and stocks_count[0] == 0:
                logger.info("Zasilanie tabeli stocks początkowymi danymi...")
                initial_stocks = [
                    ('PHL', 'PathlBank Inc.', 120.00),
                    ('GGL', 'Gugle', 340.00),
                    ('TSL', 'Teslowo', 210.00),
                    ('MSF', 'Microsofcik', 420.00),
                    ('AMD', 'AMD', 160.00)
                ]
                for sym, name, prc in initial_stocks:
                    self.sql("INSERT INTO stocks (symbol, name, current_price) VALUES (%s, %s, %s)", (sym, name, prc))
                    self.sql("INSERT INTO stock_history (symbol, price) VALUES (%s, %s)", (sym, prc))

            # Seeding ustawień globalnych
            settings_count = self.sql("SELECT COUNT(*) FROM global_settings", fetch=True)
            if settings_count and settings_count[0] == 0:
                logger.info("Zasilanie tabeli global_settings...")
                self.sql("INSERT INTO global_settings (key, value) VALUES ('inflation_rate', '5.0')")
                self.sql("INSERT INTO global_settings (key, value) VALUES ('interest_rate', '4.5')")

            # Ustawienie wszystkich istniejących użytkowników jako administratorów na potrzeby testów i zaliczenia
            self.sql("UPDATE users SET is_admin = 1 WHERE is_admin IS NULL OR is_admin = 0")
            
            logger.info("Migracja bazy danych zakończona pomyślnie.")
        except Exception as e:
            logger.error(f"Błąd podczas migracji bazy danych: {e}")

    def send_otp_email(self, to_email, code):
        """Wysyła 6-cyfrowy kod OTP na podany adres e-mail przez Gmail SMTP w formacie HTML."""
        import smtplib
        from email.mime.text import MIMEText
        
        subject = "Kod weryfikacyjny 2FA - PathlBank"
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
      <p>Otrzymaliśmy próbę logowania do Twojego konta. Twój jednorazowy kod weryfikacyjny 2FA to:</p>
      <div class="otp-container">
        <span class="otp-code">{code}</span>
      </div>
      <p>Kod jest ważny przez <strong>5 minut</strong>. Kod może być użyty tylko raz.</p>
      <div class="warning">
        Jeśli to nie Ty próbowałeś się zalogować, natychmiast zaloguj się do systemu i zmień swoje hasło.
      </div>
    </div>
    <div class="footer">
      Pozdrawiamy,<br>
      <strong>Zespół PathlBank</strong><br>
      <span style="font-size: 10px; color: #64748b;">Ta wiadomość została wygenerowana automatycznie, prosimy na nią nie odpowiadać.</span>
    </div>
  </div>
</body>
</html>"""

        logger.info(f"==================================================")
        logger.info(f"   KOD 2FA DLA {to_email}: {code}   ")
        logger.info(f"==================================================")

        smtp_user = os.getenv("SMTP_USER") or os.getenv("GMAIL_USER", "")
        smtp_password = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))

        if not smtp_user or not smtp_password:
            logger.warning("SMTP nie zostało w pełni skonfigurowane w .env (brak SMTP_USER lub GMAIL_APP_PASSWORD). Użyto logowania w konsoli.")
            return False, "SMTP_NOT_CONFIGURED"

        try:
            msg = MIMEText(html_body, "html", "utf-8")
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = to_email

            with smtplib.SMTP(smtp_host, smtp_port, timeout=5) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, to_email, msg.as_string())
            
            logger.info(f"E-mail 2FA został pomyślnie wysłany do {to_email}")
            return True, "SENT"
        except Exception as e:
            logger.error(f"Błąd wysyłania e-maila przez SMTP do {to_email}: {e}")
            return False, str(e)

    def generate_and_send_email_otp(self, email):
        """Generuje, haszuje i wysyła 6-cyfrowy kod OTP na adres e-mail."""
        code = "".join(random.choices(string.digits, k=6))
        otp_hash = hashlib.sha256(code.encode('utf-8')).hexdigest()
        expires_at = datetime.now() + timedelta(minutes=5)
        
        sql = "UPDATE users SET otp_hash = %s, otp_expires_at = %s WHERE email = %s"
        self.sql(sql, (otp_hash, expires_at, email))
        
        success, details = self.send_otp_email(email, code)
        return success, details

    def register_in_db(self, user_obj):
        """Rejestracja nowego użytkownika w bazie z opcjonalnymi polami 2FA"""
        logger.info(f"Rejestracja nowego użytkownika w DB: {user_obj.email}")
        
        card_number = self.generate_card_number()
        user_obj.nr_karty = card_number

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
            logger.info(f"Zarejestrowano pomyślnie w DB nowego użytkownika o ID: {result[0]}")
            return {
                "status": "OK",
                "message": f"Rejestracja pomyślna dla {user_obj.imie} {user_obj.nazwisko}",
                "id": result[0],
                "imie": user_obj.imie,
                "nazwisko": user_obj.nazwisko,
                "nr_karty": card_number,
                "nr_karty_format": card_display
            }
        
        logger.error("Nie udało się zarejestrować użytkownika w bazie.")
        return {"status": "FAIL", "message": "Nie udało się zarejestrować"}

    def handle_state_input(self, command, conn):
        with self.session_lock:
            session = self.sessions.get(conn)
            if not session:
                return False
            state = session.get('state', 'NORMAL')
            temp_user = session.get('temp_user')
            temp_totp_secret = session.get('temp_totp_secret')
            temp_email = session.get('temp_email')
            temp_login_attempts = session.get('temp_login_attempts', 0)

        cmd = command.strip().lower()

        if state == 'REG_AWAIT_2FA_CHOICE':
            if cmd in ['tak', 't', 'yes', 'y']:
                email = temp_user.email
                secret = pyotp.random_base32()
                uri = f"otpauth://totp/PathlBank:{email}?secret={secret}&issuer=PathlBank"
                
                qr = qrcode.QRCode()
                qr.add_data(uri)
                qr.make(fit=True)
                f = io.StringIO()
                qr.print_ascii(out=f)
                qr_ascii = f.getvalue()
                
                msg = f"\n=== GOOGLE AUTHENTICATOR SETUP ===\n"
                msg += qr_ascii
                msg += f"\nURI: {uri}\nSecret: {secret}\n"
                msg += "Zeskanuj kod QR powyżej za pomocą Google Authenticator.\n"
                msg += "Wprowadź aktualny 6-cyfrowy kod TOTP, aby zakończyć rejestrację: "
                conn.sendall(msg.encode())
                
                with self.session_lock:
                    session['state'] = 'REG_AWAIT_TOTP_VERIFICATION'
                    session['temp_totp_secret'] = secret
                    session['temp_login_attempts'] = 0
            elif cmd in ['nie', 'n', 'no']:
                temp_user.two_factor_method = 'NONE'
                res = self.register_in_db(temp_user)
                conn.sendall(f"{res['message']}\nZarejestrowano pomyślnie. Weryfikacja e-mail OTP będzie wymagana podczas logowania. Zaloguj się za pomocą komendy login.\n".encode())
                with self.session_lock:
                    session['state'] = 'NORMAL'
                    session['temp_user'] = None
            else:
                conn.sendall("Niepoprawna odpowiedź. Wpisz 'tak' lub 'nie': ".encode())
            return True

        elif state == 'REG_AWAIT_TOTP_VERIFICATION':
            secret = temp_totp_secret
            totp = pyotp.TOTP(secret)
            if totp.verify(command.strip()):
                temp_user.two_factor_method = 'TOTP'
                temp_user.totp_secret = secret
                res = self.register_in_db(temp_user)
                conn.sendall(f"{res['message']}\nGoogle Authenticator 2FA został aktywowany pomyślnie. Zaloguj się za pomocą komendy login.\n".encode())
                with self.session_lock:
                    session['state'] = 'NORMAL'
                    session['temp_user'] = None
                    session['temp_totp_secret'] = None
            else:
                temp_login_attempts += 1
                if temp_login_attempts >= 3:
                    conn.sendall("Błąd weryfikacji TOTP 3 razy. Rejestracja anulowana.\n".encode())
                    with self.session_lock:
                        session['state'] = 'NORMAL'
                        session['temp_user'] = None
                        session['temp_totp_secret'] = None
                else:
                    conn.sendall(f"Niepoprawny kod TOTP. Spróbuj ponownie (Pozostało prób: {3 - temp_login_attempts}): ".encode())
                    with self.session_lock:
                        session['temp_login_attempts'] = temp_login_attempts
            return True

        elif state == 'LOGIN_AWAIT_2FA_OTP':
            success = verify_email_otp(temp_email, command.strip())
            if success:
                sql = "SELECT id, imie, nazwisko, two_factor_method FROM users WHERE email = %s"
                res = self.sql(sql, (temp_email,), fetch=True)
                if res and res[3] == 'TOTP':
                    with self.session_lock:
                        session['state'] = 'LOGIN_AWAIT_2FA_TOTP'
                        session['temp_login_attempts'] = 0
                    conn.sendall("INFO: E-mail zweryfikowany! Wpisz aktualny kod z aplikacji Google Authenticator: ".encode())
                else:
                    with self.session_lock:
                        session['user_id'] = res[0]
                        session['state'] = 'NORMAL'
                        session['temp_email'] = None
                    conn.sendall(f"OK: Zalogowano jako {res[1]} {res[2]}\n".encode())
            else:
                sql = "SELECT locked, failed_login_attempts FROM users WHERE email = %s"
                res = self.sql(sql, (temp_email,), fetch=True)
                if res and res[0]:
                    conn.sendall("ERROR: Konto zostało zablokowane z powodu zbyt wielu prób logowania.\n".encode())
                    with self.session_lock:
                        session['state'] = 'NORMAL'
                        session['temp_email'] = None
                else:
                    attempts = res[1] if res else 0
                    conn.sendall(f"ERROR: Niepoprawny kod OTP. Spróbuj ponownie (Pozostało prób: {3 - attempts}): ".encode())
            return True

        elif state == 'LOGIN_AWAIT_2FA_TOTP':
            sql = "SELECT id, imie, nazwisko, totp_secret, failed_login_attempts FROM users WHERE email = %s"
            res = self.sql(sql, (temp_email,), fetch=True)
            if not res:
                conn.sendall("ERROR: Błąd wewnętrzny serwera.\n".encode())
                with self.session_lock:
                    session['state'] = 'NORMAL'
                    session['temp_email'] = None
                return True
                
            user_id, imie, nazwisko, secret, failed_attempts = res
            totp = pyotp.TOTP(secret)
            if totp.verify(command.strip()):
                self.sql("UPDATE users SET failed_login_attempts = 0 WHERE id = %s", (user_id,))
                with self.session_lock:
                    session['user_id'] = user_id
                    session['state'] = 'NORMAL'
                    session['temp_email'] = None
                conn.sendall(f"OK: Zalogowano jako {imie} {nazwisko}\n".encode())
            else:
                new_attempts = failed_attempts + 1
                if new_attempts >= 3:
                    self.sql("UPDATE users SET failed_login_attempts = %s, locked = TRUE WHERE id = %s", (new_attempts, user_id))
                    conn.sendall("ERROR: Konto zostało zablokowane z powodu zbyt wielu prób logowania.\n".encode())
                    with self.session_lock:
                        session['state'] = 'NORMAL'
                        session['temp_email'] = None
                else:
                    self.sql("UPDATE users SET failed_login_attempts = %s WHERE id = %s", (new_attempts, user_id))
                    conn.sendall(f"ERROR: Niepoprawny kod TOTP. Spróbuj ponownie (Pozostało prób: {3 - new_attempts}): ".encode())
            return True

        return True

    @property
    def conn(self):
        """Dynamicznie zwraca lub tworzy połączenie z bazą danych dla bieżącego wątku."""
        if not hasattr(self.thread_local, "conn") or self.thread_local.conn.closed:
            logger.debug("Tworzenie nowego połączenia z bazą danych dla wątku")
            self.thread_local.conn = psycopg.connect(
                dbname="BankDb",
                user="postgres",
                password="770528",
                host="localhost"
            )
        return self.thread_local.conn

    def generate_card_number(self):
        """Generuje unikalny 16-cyfrowy numer karty zaczynający się od 2137"""
        while True:
            # Generuj numer zaczynający się od 2137 i 12 losowych cyfr
            card_number = '2137' + ''.join([str(random.randint(0, 9)) for _ in range(12)])

            # Sprawdź czy numer już istnieje w bazie
            sql = "SELECT id FROM users WHERE nr_karty = %s"
            result = self.sql(sql, (card_number,), fetch=True)

            if not result:
                return card_number

    def format_card_number(self, card_number):
        """Formatuje numer karty do czytelnej postaci XXXX XXXX XXXX XXXX"""
        if card_number and len(card_number) == 16:
            return ' '.join([card_number[i:i + 4] for i in range(0, 16, 4)])
        return card_number

    def conn_close(self, conn):
        try:
            # Usuń sesję
            with self.session_lock:
                if conn in self.sessions:
                    del self.sessions[conn]
            conn.sendall("exit".encode())
            conn.close()
        except Exception as e:
            logger.debug(f"Błąd podczas zamykania gniazda: {e}")

    def get_prompt(self, conn):
        """Zwraca odpowiedni prompt dla sesji"""
        with self.session_lock:
            session = self.sessions.get(conn)
            if not session:
                return "Bank@system root/> "
            user_id = session.get('user_id')
            state = session.get('state', 'NORMAL')

        if state == 'REG_AWAIT_2FA_CHOICE':
            return "Wybierz Google Authenticator 2FA (tak/nie)> "
        elif state == 'REG_AWAIT_EMAIL_2FA_CHOICE':
            return "Wybierz Email 2FA (tak/nie)> "
        elif state == 'REG_AWAIT_TOTP_VERIFICATION':
            return "Kod TOTP weryfikacji> "
        elif state == 'LOGIN_AWAIT_2FA_OTP':
            return "Kod OTP weryfikacji> "
        elif state == 'LOGIN_AWAIT_2FA_TOTP':
            return "Kod TOTP weryfikacji> "

        if user_id:
            user = self.get_user(user_id)
            if user:
                return f"Bank@{user['imie']} {user['nazwisko']}> "

        return "Bank@system root/> "

    def get_user(self, user_id):
        """Pobierz dane użytkownika po ID"""
        sql = """
            SELECT id, imie, nazwisko, email, saldo, nr_karty,
                   is_admin, is_company, company_name, company_nip, company_regon, public_key, reward_points
            FROM users WHERE id = %s
        """
        result = self.sql(sql, (user_id,), fetch=True)
        if result:
            return {
                "id": result[0],
                "imie": result[1],
                "nazwisko": result[2],
                "email": result[3],
                "saldo": float(result[4]),
                "nr_karty": result[5],
                "is_admin": int(result[6] or 0),
                "is_company": bool(result[7]),
                "company_name": result[8],
                "company_nip": result[9],
                "company_regon": result[10],
                "public_key": result[11],
                "reward_points": int(result[12] or 0)
            }
        return None

    def run_command(self, command, conn):
        if command == "exit":
            logger.info("Klient zażądał zakończenia połączenia (exit)")
            self.conn_close(conn)
            return False

        with self.session_lock:
            session = self.sessions.get(conn)
            state = session.get('state', 'NORMAL') if session else 'NORMAL'

        if state != 'NORMAL':
            return self.handle_state_input(command, conn)

        parts = command.strip().split(" ")
        if not parts or parts[0] == "":
            conn.sendall(self.get_prompt(conn).encode())
            return True

        cmd = parts[0]
        logger.info(f"Otrzymano komendę '{cmd}'")

        if cmd == "login":
            if len(parts) < 3:
                conn.sendall("ERROR: Użycie: login <email> <haslo>".encode())
                return True
            email = parts[1]
            haslo = parts[2]
            
            sql = """
                SELECT id, imie, nazwisko, saldo, nr_karty, haslo, two_factor_method, totp_secret, failed_login_attempts, locked
                FROM users 
                WHERE email = %s
            """
            result = self.sql(sql, (email,), fetch=True)
            
            if not result:
                conn.sendall("ERROR: Nieprawidłowy email lub hasło".encode())
                return True
                
            user_id, imie, nazwisko, saldo, nr_karty, stored_haslo, two_factor_method, totp_secret, failed_attempts, locked = result
            
            if locked:
                conn.sendall("ERROR: Konto zablokowane z powodu zbyt wielu prób logowania".encode())
                return True
                
            if not verify_password(stored_haslo, haslo):
                new_attempts = failed_attempts + 1
                if new_attempts >= 3:
                    self.sql("UPDATE users SET failed_login_attempts = %s, locked = TRUE WHERE email = %s", (new_attempts, email))
                    conn.sendall("ERROR: Nieprawidłowy email lub hasło. Konto zostało zablokowane.".encode())
                else:
                    self.sql("UPDATE users SET failed_login_attempts = %s WHERE email = %s", (new_attempts, email))
                    conn.sendall(f"ERROR: Nieprawidłowy email lub hasło. Pozostało prób: {3 - new_attempts}".encode())
                return True
            
            # Automatyczna migracja: jeśli hasło w bazie jest jawnym tekstem, zaktualizuj do bezpiecznego haszu
            if ":" not in stored_haslo:
                try:
                    hashed_pwd = hash_password(haslo)
                    update_sql = "UPDATE users SET haslo = %s WHERE id = %s"
                    self.sql(update_sql, (hashed_pwd, user_id))
                    logger.info(f"Zmigrowano hasło użytkownika ID {user_id} do formatu zhaszowanego")
                except Exception as me:
                    logger.error(f"Błąd automatycznej migracji hasła: {me}")

            # Hasło poprawne
            if two_factor_method == 'TOTP':
                with self.session_lock:
                    self.sessions[conn]['state'] = 'LOGIN_AWAIT_2FA_TOTP'
                    self.sessions[conn]['temp_email'] = email
                    self.sessions[conn]['temp_login_attempts'] = 0
                conn.sendall("INFO: Wpisz aktualny kod z aplikacji Google Authenticator: ".encode())
            else:
                # Domyślnie zawsze wysyłamy e-mail OTP
                success, details = self.generate_and_send_email_otp(email)
                if success:
                    with self.session_lock:
                        self.sessions[conn]['state'] = 'LOGIN_AWAIT_2FA_OTP'
                        self.sessions[conn]['temp_email'] = email
                        self.sessions[conn]['temp_login_attempts'] = 0
                    conn.sendall("INFO: Wysłano kod OTP na Twój e-mail. Wpisz kod OTP: ".encode())
                else:
                    conn.sendall(f"ERROR: Błąd wysyłania e-maila 2FA ({details})".encode())

        elif cmd == "register":
            if len(parts) < 7:
                conn.sendall("ERROR: Użycie: register <imie> <nazwisko> <pesel> <email> <pin> <haslo>".encode())
                return True
            email = parts[4]
            check_sql = "SELECT id FROM users WHERE email = %s"
            if self.sql(check_sql, (email,), fetch=True):
                conn.sendall("ERROR: Użytkownik o podanym adresie e-mail już istnieje".encode())
                return True
            try:
                user = self.User(
                    imie=parts[1],
                    nazwisko=parts[2],
                    pesel=parts[3],
                    email=email,
                    pin=parts[5],
                    haslo=parts[6]
                )
                with self.session_lock:
                    self.sessions[conn]['state'] = 'REG_AWAIT_2FA_CHOICE'
                    self.sessions[conn]['temp_user'] = user
                conn.sendall("Czy chcesz włączyć Google Authenticator 2FA? (tak/nie): ".encode())
            except Exception as e:
                logger.error(f"Błąd rejestracji: {e}")
                conn.sendall(f"ERROR: {str(e)}".encode())

        elif cmd == "balance":
            with self.session_lock:
                session = self.sessions.get(conn)
                user_id = session.get('user_id') if session else None
            if not user_id:
                conn.sendall("ERROR: Musisz być zalogowany".encode())
                return True
            result = self.get_balance(user_id)
            conn.sendall(str(result).encode())

        elif cmd == "transfer":
            with self.session_lock:
                session = self.sessions.get(conn)
                user_id = session.get('user_id') if session else None
            if not user_id:
                conn.sendall("ERROR: Musisz być zalogowany".encode())
                return True
            if len(parts) < 3:
                conn.sendall("ERROR: Użycie: transfer <id_odbiorcy> <kwota>".encode())
                return True
            try:
                to_id = int(parts[1])
                amount = float(parts[2])
                result = self.transfer(user_id, to_id, amount)
                conn.sendall(str(result).encode())
            except ValueError:
                conn.sendall("ERROR: ID odbiorcy musi być liczbą całkowitą, a kwota liczbą zmiennoprzecinkową".encode())

        elif cmd == "deposit":
            with self.session_lock:
                session = self.sessions.get(conn)
                user_id = session.get('user_id') if session else None
            if not user_id:
                conn.sendall("ERROR: Musisz być zalogowany".encode())
                return True
            if len(parts) < 2:
                conn.sendall("ERROR: Użycie: deposit <kwota>".encode())
                return True
            try:
                amount = float(parts[1])
                result = self.deposit(user_id, amount)
                conn.sendall(str(result).encode())
            except ValueError:
                conn.sendall("ERROR: Kwota musi być liczbą".encode())

        elif cmd == "withdraw":
            with self.session_lock:
                session = self.sessions.get(conn)
                user_id = session.get('user_id') if session else None
            if not user_id:
                conn.sendall("ERROR: Musisz być zalogowany".encode())
                return True
            if len(parts) < 2:
                conn.sendall("ERROR: Użycie: withdraw <kwota>".encode())
                return True
            try:
                amount = float(parts[1])
                result = self.withdraw(user_id, amount)
                conn.sendall(str(result).encode())
            except ValueError:
                conn.sendall("ERROR: Kwota musi być liczbą".encode())

        elif cmd == "history":
            with self.session_lock:
                session = self.sessions.get(conn)
                user_id = session.get('user_id') if session else None
            if not user_id:
                conn.sendall("ERROR: Musisz być zalogowany".encode())
                return True
            result = self.get_history(user_id)
            conn.sendall(str(result).encode())

        elif cmd == "show":
            if len(parts) < 2:
                conn.sendall("ERROR: Użycie: show <users|user <id>>".encode())
                return True

            if parts[1] == "users":
                # Wyświetl wszystkich użytkowników
                result = self.show_all_users()
                conn.sendall(str(result).encode())

            elif parts[1] == "user":
                if len(parts) < 3:
                    conn.sendall("ERROR: Użycie: show user <id>".encode())
                    return True
                try:
                    user_id = int(parts[2])
                    result = self.show_user(user_id)
                    conn.sendall(str(result).encode())
                except ValueError:
                    conn.sendall("ERROR: ID musi być liczbą".encode())
            else:
                conn.sendall(
                    f"ERROR: Nieznane polecenie 'show {parts[1]}'. Użyj: show users lub show user <id>".encode())

        elif cmd == "logout":
            with self.session_lock:
                session = self.sessions.get(conn)
                logged_in = session and session.get('user_id') is not None
                if logged_in:
                    session['user_id'] = None
            if logged_in:
                logger.info("Wylogowano użytkownika pomyślnie")
                conn.sendall("OK: Wylogowano".encode())
            else:
                conn.sendall("INFO: Nie jesteś zalogowany".encode())

        elif cmd == "info":
            with self.session_lock:
                session = self.sessions.get(conn)
                user_id = session.get('user_id') if session else None
            if user_id:
                user = self.get_user(user_id)
                if user:
                    card_display = self.format_card_number(user['nr_karty'])
                    info = f"""
=== INFORMACJE O KONCIE ===
ID: {user['id']}
Imię: {user['imie']}
Nazwisko: {user['nazwisko']}
Email: {user['email']}
Saldo: {user['saldo']:.2f} zł
Numer karty: {card_display}
==========================="""
                    conn.sendall(info.encode())
                else:
                    conn.sendall("ERROR: Nie znaleziono użytkownika".encode())
            else:
                conn.sendall("INFO: Nie jesteś zalogowany".encode())

        elif cmd == "help":
            help_text = """
=== DOSTĘPNE KOMENDY ===
  login <email> <haslo>     - Logowanie
  register <imie> <nazwisko> <pesel> <email> <pin> <haslo> - Rejestracja
  logout                    - Wylogowanie
  balance                   - Sprawdzenie salda
  deposit <kwota>          - Wpłata na konto
  withdraw <kwota>         - Wypłata z konta
  transfer <id_odbiorcy> <kwota> - Przelew
  history                   - Historia transakcji
  info                      - Informacje o koncie
  show users                - Wyświetl wszystkich użytkowników (admin)
  show user <id>            - Wyświetl szczegóły użytkownika (admin)
  help                      - Ta pomoc
  exit                      - Zakończenie połączenia
========================"""
            conn.sendall(help_text.encode())

        else:
            conn.sendall(f"ERROR: Nieznane polecenie '{cmd}'. Wpisz 'help' dla listy komend.".encode())

        return True

    def handle_client(self, conn, addr):
        logger.info(f"Obsługa nowego klienta z adresu {addr}")
        with self.session_lock:
            self.sessions[conn] = {'user_id': None}

        try:
            # Autoryzacja
            conn.sendall("ident".encode())
            ident = conn.recv(1024).decode().strip()

            if ident not in self.znane:
                logger.warning(f"Odrzucono połączenie od {addr} - nieznany identyfikator: {ident}")
                self.conn_close(conn)
                return

            device_name = self.znane[ident]
            logger.info(f"Klient {addr} autoryzowany pomyślnie jako: {device_name}")
            conn.sendall("AUTORIZE_GIT".encode())

            if conn.recv(1024).decode().strip() != "OK":
                logger.warning(f"Klient {addr} ({device_name}) nie przysłał potwierdzenia OK")
                self.conn_close(conn)
                return

            # Wyślij początkowy prompt
            conn.sendall(self.get_prompt(conn).encode())

            # Główna pętla obsługi komend klienta
            while self.running:
                try:
                    command = conn.recv(1024).decode().strip()
                    if not command:
                        break
                    if not self.run_command(command, conn):
                        break
                    # Po każdej komendzie wyślij nowy prompt
                    conn.sendall(self.get_prompt(conn).encode())
                except socket.error as se:
                    logger.debug(f"Błąd gniazda dla {addr}: {se}")
                    break

        except Exception as e:
            logger.error(f"Nieoczekiwany błąd podczas obsługi klienta {addr}: {e}", exc_info=True)
        finally:
            self.conn_close(conn)
            logger.info(f"Połączenie z {addr} zostało zamknięte")

    def start(self):
        logger.info("Serwer startuje na porcie 4300...")
        self.server.listen()
        self.server.settimeout(1.0)  # Pozwala pętli reagować na flagę self.running

        while self.running:
            try:
                conn, addr = self.server.accept()
                logger.info(f"Nawiązano połączenie z {addr}")
                # Uruchom obsługę klienta w osobnym wątku
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(conn, addr),
                    name=f"Client-{addr[0]}:{addr[1]}",
                    daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                logger.info("Przechwycono sygnał zamknięcia (KeyboardInterrupt)")
                self.stop()
                break
            except Exception as e:
                if self.running:
                    logger.error(f"Błąd przy akceptowaniu połączenia: {e}")
                continue

        logger.info("Czyszczenie zasobów serwera...")
        self.server.close()
        # Zamknij połączenie z bazą danych dla wątku głównego (jeśli istnieje)
        if hasattr(self.thread_local, "conn") and not self.thread_local.conn.closed:
            self.thread_local.conn.close()

    def sql(self, sql, data=None, fetch=False, many=False, commit=True):
        """Wykonuje zapytanie SQL z pliku lub bezpośrednio z obsługą transakcji i rollbacków"""
        try:
            with self.conn.cursor() as cur:
                if isinstance(sql, str) and sql.endswith('.sql'):
                    sql_path = sql
                    if not os.path.isabs(sql_path):
                        sql_path = os.path.join("/home/neon/PythonProject/Bank", sql)
                    with open(sql_path, "r", encoding="utf-8") as f:
                        sql_query = f.read()
                else:
                    sql_query = sql

                cur.execute(sql_query, data)

                if fetch:
                    result = cur.fetchone()
                elif many:
                    result = cur.fetchall()
                else:
                    result = None

            if commit:
                self.conn.commit()
            return result
        except Exception as e:
            logger.error(f"Błąd zapytania SQL: {sql} | Wyjątek: {e}")
            try:
                self.conn.rollback()
                logger.info("Pomyślnie wykonano rollback po błędzie SQL.")
            except Exception as re:
                logger.error(f"Nie udało się wykonać rollback: {re}")
            raise e

    def login(self, email, haslo, conn):
        """Logowanie użytkownika z weryfikacją hasła i automatyczną migracją z tekstu jawnego"""
        logger.info(f"Próba logowania dla email: {email}")
        sql = """
            SELECT id, imie, nazwisko, saldo, nr_karty, haslo 
            FROM users 
            WHERE email = %s
        """
        result = self.sql(sql, (email,), fetch=True)

        if result:
            stored_haslo = result[5]
            if verify_password(stored_haslo, haslo):
                with self.session_lock:
                    self.sessions[conn]['user_id'] = result[0]
                card_display = self.format_card_number(result[4])
                
                # Automatyczna migracja: jeśli hasło w bazie jest jawnym tekstem, zaktualizuj do bezpiecznego haszu
                ifStoredPlain = ":" not in stored_haslo
                if ifStoredPlain:
                    try:
                        hashed_pwd = hash_password(haslo)
                        update_sql = "UPDATE users SET haslo = %s WHERE id = %s"
                        self.sql(update_sql, (hashed_pwd, result[0]))
                        logger.info(f"Automatycznie zmigrowano hasło użytkownika ID {result[0]} do formatu zhaszowanego")
                    except Exception as me:
                        logger.error(f"Nie udało się automatycznie zmigrować hasła: {me}")

                logger.info(f"Zalogowano pomyślnie użytkownika ID {result[0]} ({result[1]} {result[2]})")
                return {
                    "status": "OK",
                    "message": f"Zalogowano jako {result[1]} {result[2]}",
                    "id": result[0],
                    "imie": result[1],
                    "nazwisko": result[2],
                    "saldo": float(result[3]),
                    "nr_karty": result[4],
                    "nr_karty_format": card_display
                }
            else:
                logger.warning(f"Niepoprawne hasło dla użytkownika: {email}")
        else:
            logger.warning(f"Nie znaleziono użytkownika z email: {email}")

        return {"status": "FAIL", "message": "Nieprawidłowy email lub hasło"}

    def register(self, user_obj, conn):
        """Rejestracja nowego użytkownika z bezpiecznym haszowaniem hasła"""
        logger.info(f"Próba rejestracji nowego użytkownika: {user_obj.email}")
        
        # Generuj unikalny numer karty
        card_number = self.generate_card_number()
        user_obj.nr_karty = card_number

        # Haszuj hasło przed zapisem
        hashed_pwd = hash_password(user_obj.haslo)

        sql = """
            INSERT INTO users (imie, nazwisko, pesel, email, pin, haslo, saldo, nr_karty)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
            card_number
        )

        result = self.sql(sql, data, fetch=True)

        if result:
            user_obj.id = result[0]
            with self.session_lock:
                self.sessions[conn]['user_id'] = result[0]
            card_display = self.format_card_number(card_number)
            logger.info(f"Zarejestrowano pomyślnie nowego użytkownika o ID: {result[0]}")
            return {
                "status": "OK",
                "message": f"Zarejestrowano i zalogowano jako {user_obj.imie} {user_obj.nazwisko}",
                "id": result[0],
                "imie": user_obj.imie,
                "nazwisko": user_obj.nazwisko,
                "nr_karty": card_number,
                "nr_karty_format": card_display
            }
        
        logger.error("Nie udało się zarejestrować użytkownika w bazie.")
        return {"status": "FAIL", "message": "Nie udało się zarejestrować"}

    def get_balance(self, user_id):
        """Sprawdzenie salda"""
        logger.info(f"Sprawdzanie salda dla użytkownika ID {user_id}")
        sql = "SELECT saldo FROM users WHERE id = %s"
        result = self.sql(sql, (user_id,), fetch=True)

        if result:
            return {"status": "OK", "saldo": float(result[0])}
        return {"status": "FAIL", "message": "Użytkownik nie znaleziony"}

    def transfer(self, from_id, to_id, amount):
        """Przelew między użytkownikami"""
        logger.info(f"Przelew od ID {from_id} do ID {to_id}, kwota: {amount}")
        try:
            if from_id == to_id:
                return {"status": "FAIL", "message": "Nie możesz przelać do siebie"}

            if amount <= 0:
                return {"status": "FAIL", "message": "Kwota musi być większa od 0"}

            # Sprawdź saldo
            balance = self.get_balance(from_id)
            if balance["status"] != "OK" or balance["saldo"] < amount:
                logger.warning(f"Przelew odrzucony: niewystarczające środki dla ID {from_id}")
                return {"status": "FAIL", "message": "Niewystarczające środki"}

            # Sprawdź czy odbiorca istnieje
            target = self.get_user(to_id)
            if not target:
                logger.warning(f"Przelew odrzucony: odbiorca ID {to_id} nie istnieje")
                return {"status": "FAIL", "message": "Odbiorca nie istnieje"}

            # Wykonaj przelew
            sql1 = "UPDATE users SET saldo = saldo - %s WHERE id = %s"
            sql2 = "UPDATE users SET saldo = saldo + %s WHERE id = %s"
            try:
                self.sql(sql1, (amount, from_id), commit=False)
                self.sql(sql2, (amount, to_id), commit=False)
                self.conn.commit()
            except Exception as te:
                try:
                    self.conn.rollback()
                except:
                    pass
                raise te

            # Loguj transakcję
            self.log_transaction(from_id, to_id, amount, "TRANSFER")
            logger.info(f"Przelew {amount} zł od ID {from_id} do ID {to_id} wykonany pomyślnie")

            return {
                "status": "OK",
                "message": f"Przelew {amount} zł do {target['imie']} {target['nazwisko']} wykonany"
            }

        except Exception as e:
            logger.error(f"Błąd przelewu: {e}")
            return {"status": "FAIL", "message": str(e)}

    def deposit(self, user_id, amount):
        """Wpłata na konto"""
        logger.info(f"Wpłata na konto użytkownika ID {user_id}, kwota: {amount}")
        if amount <= 0:
            return {"status": "FAIL", "message": "Kwota musi być większa od 0"}

        sql = "UPDATE users SET saldo = saldo + %s WHERE id = %s RETURNING saldo"
        result = self.sql(sql, (amount, user_id), fetch=True)

        if result:
            self.log_transaction(user_id, None, amount, "DEPOSIT")
            logger.info(f"Wpłacono pomyślnie. Nowe saldo dla ID {user_id}: {result[0]}")
            return {"status": "OK", "message": f"Wpłacono {amount} zł", "new_balance": float(result[0])}
        
        logger.warning(f"Wpłata nieudana: nie znaleziono użytkownika ID {user_id}")
        return {"status": "FAIL", "message": "Użytkownik nie znaleziony"}

    def withdraw(self, user_id, amount):
        """Wypłata z konta"""
        logger.info(f"Wypłata z konta użytkownika ID {user_id}, kwota: {amount}")
        if amount <= 0:
            return {"status": "FAIL", "message": "Kwota musi być większa od 0"}

        # Sprawdź saldo
        balance = self.get_balance(user_id)
        if balance["status"] != "OK" or balance["saldo"] < amount:
            logger.warning(f"Wypłata odrzucona: niewystarczające środki dla ID {user_id}")
            return {"status": "FAIL", "message": "Niewystarczające środki"}

        sql = "UPDATE users SET saldo = saldo - %s WHERE id = %s RETURNING saldo"
        result = self.sql(sql, (amount, user_id), fetch=True)

        if result:
            self.log_transaction(user_id, None, -amount, "WITHDRAW")
            logger.info(f"Wypłacono pomyślnie. Nowe saldo dla ID {user_id}: {result[0]}")
            return {"status": "OK", "message": f"Wypłacono {amount} zł", "new_balance": float(result[0])}
        
        logger.error(f"Błąd krytyczny podczas wypłaty dla ID {user_id}")
        return {"status": "FAIL", "message": "Błąd wypłaty"}

    def get_history(self, user_id, limit=10):
        """Pobierz historię transakcji"""
        logger.info(f"Pobieranie historii transakcji dla użytkownika ID {user_id}")
        sql = """
            SELECT t.id, t.from_user, t.to_user, t.amount, t.type, t.created_at,
                   u1.imie as from_imie, u1.nazwisko as from_nazwisko,
                   u2.imie as to_imie, u2.nazwisko as to_nazwisko
            FROM transactions t
            LEFT JOIN users u1 ON t.from_user = u1.id
            LEFT JOIN users u2 ON t.to_user = u2.id
            WHERE t.from_user = %s OR t.to_user = %s 
            ORDER BY t.created_at DESC 
            LIMIT %s
        """
        results = self.sql(sql, (user_id, user_id, limit), many=True)

        if results:
            transactions = []
            for r in results:
                trans = {
                    "id": r[0],
                    "amount": float(r[3]),
                    "type": r[4],
                    "date": str(r[5])
                }

                # Określ kierunek transakcji
                if r[1] == user_id:  # wysłane
                    trans["direction"] = "WYCHODZĄCY"
                    trans["other"] = f"{r[6] or '?'} {r[7] or '?'}" if r[6] else "System"
                elif r[2] == user_id:  # otrzymane
                    trans["direction"] = "PRZYCHODZĄCY"
                    trans["other"] = f"{r[8] or '?'} {r[9] or '?'}" if r[8] else "System"
                else:
                    trans["direction"] = "NIEZNANY"
                    trans["other"] = "???"

                transactions.append(trans)

            return {"status": "OK", "transactions": transactions}
        return {"status": "OK", "transactions": []}

    def log_transaction(self, from_user, to_user, amount, trans_type):
        """Loguj transakcję"""
        sql = """
            INSERT INTO transactions (from_user, to_user, amount, type)
            VALUES (%s, %s, %s, %s)
        """
        self.sql(sql, (from_user, to_user, amount, trans_type))

    def show_all_users(self):
        """Pobiera i formatuje listę wszystkich użytkowników (metoda admina)"""
        logger.info("Żądanie wyświetlenia wszystkich użytkowników (show users)")
        sql = "SELECT id, imie, nazwisko, email, saldo, nr_karty FROM users ORDER BY id"
        results = self.sql(sql, many=True)
        if not results:
            return "Brak użytkowników w systemie."
        
        output = []
        output.append("\n=== LISTA UŻYTKOWNIKÓW ===")
        output.append(f"{'ID':<5} | {'Imię i Nazwisko':<25} | {'Email':<25} | {'Saldo':<12} | {'Numer Karty':<20}")
        output.append("-" * 95)
        for r in results:
            card_display = self.format_card_number(r[5])
            full_name = f"{r[1]} {r[2]}"
            output.append(f"{r[0]:<5} | {full_name:<25} | {r[3]:<25} | {float(r[4]):<12.2f} | {card_display:<20}")
        output.append("=" * 95)
        return "\n".join(output)

    def show_user(self, user_id):
        """Pobiera i formatuje szczegółowe dane konkretnego użytkownika (metoda admina)"""
        logger.info(f"Żądanie wyświetlenia szczegółów użytkownika ID {user_id}")
        user = self.get_user(user_id)
        if not user:
            logger.warning(f"Żądanie show user: Użytkownik ID {user_id} nie istnieje")
            return f"ERROR: Użytkownik o ID {user_id} nie istnieje."
        
        card_display = self.format_card_number(user['nr_karty'])
        output = f"""
=== SZCZEGÓŁY UŻYTKOWNIKA ===
ID: {user['id']}
Imię: {user['imie']}
Nazwisko: {user['nazwisko']}
Email: {user['email']}
Saldo: {user['saldo']:.2f} zł
Numer karty: {card_display}
==========================="""
        return output

    def stop(self):
        """Zatrzymanie serwera"""
        logger.info("Zatrzymywanie serwera...")
        self.running = False


if __name__ == "__main__":
    try:
        server = Server(User)
        server.start()
    except KeyboardInterrupt:
        logger.info("Serwer zatrzymany przez użytkownika (KeyboardInterrupt w main)")
    except Exception as e:
        logger.error(f"Błąd krytyczny serwera: {e}", exc_info=True)
    finally:
        logger.info("Koniec programu")