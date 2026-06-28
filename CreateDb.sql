-- Tabela użytkowników - numer karty generowany w Python
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE IF NOT EXISTS users(
    id SERIAL PRIMARY KEY,
    imie TEXT NOT NULL,
    nazwisko TEXT NOT NULL,
    pesel CHAR(11) NOT NULL CHECK (pesel ~ '^[0-9]{11}$'),
    email TEXT NOT NULL UNIQUE,
    pin TEXT NOT NULL CHECK (char_length(pin) = 4),
    haslo TEXT NOT NULL,
    saldo NUMERIC(20,2) DEFAULT 0,
    nr_karty TEXT UNIQUE NOT NULL, -- Python generuje i wstawia
    two_factor_method VARCHAR(20) DEFAULT 'NONE',
    totp_secret VARCHAR(64),
    failed_login_attempts INTEGER DEFAULT 0,
    locked BOOLEAN DEFAULT FALSE,
    otp_hash VARCHAR(64),
    otp_expires_at TIMESTAMP
);

-- Indeks dla szybszego wyszukiwania
CREATE INDEX idx_users_nr_karty ON users(nr_karty);
CREATE INDEX idx_users_email ON users(email);

-- Tabela transakcji
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    from_user INTEGER REFERENCES users(id) ON DELETE CASCADE,
    to_user INTEGER REFERENCES users(id) ON DELETE CASCADE,
    amount NUMERIC(20,2) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('DEPOSIT', 'WITHDRAW', 'TRANSFER', 'PAYMENT')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_transactions_from_user ON transactions(from_user);
CREATE INDEX idx_transactions_to_user ON transactions(to_user);
CREATE INDEX idx_transactions_created_at ON transactions(created_at DESC);