SELECT id, imie, nazwisko, saldo, nr_karty
FROM users
WHERE email = %(email)s AND haslo = %(haslo)s;