INSERT INTO users (imie, nazwisko, pesel, email, pin, haslo, saldo)
VALUES (%(imie)s, %(nazwisko)s, %(pesel)s, %(email)s, %(pin)s, %(haslo)s, %(saldo)s)
RETURNING id, nr_karty;