import socket
import sys


class BankClient:
    def __init__(self, host="localhost", port=4300):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect(self):
        self.sock.connect((self.host, self.port))

    def authenticate(self, ident="1234"):
        # Odbierz prośbę o identyfikację
        msg = self.sock.recv(1024).decode().strip()
        if msg == "ident":
            self.sock.sendall(ident.encode())

        # Odbierz potwierdzenie
        auth_msg = self.sock.recv(1024).decode().strip()
        if auth_msg == "AUTORIZE_GIT":
            self.sock.sendall("OK".encode())

        # Odbierz pierwszy prompt
        prompt = self.sock.recv(1024).decode()
        return prompt

    def run(self):
        try:
            self.connect()
            prompt = self.authenticate("1234")
            print(prompt, end="")

            while True:
                try:
                    command = input()

                    if command.lower() == "exit":
                        self.sock.sendall("exit".encode())
                        break

                    self.sock.sendall(command.encode())

                    # Odbieraj wszystko aż do nowego promptu
                    while True:
                        data = self.sock.recv(4096).decode()
                        print(data, end="")
                        if "> " in data:  # Koniec odpowiedzi (nowy prompt)
                            break

                except KeyboardInterrupt:
                    print("\nZamykanie...")
                    break
                except Exception as e:
                    print(f"\nBłąd: {e}")
                    break

        except ConnectionRefusedError:
            print("Błąd: Serwer nie jest dostępny")
        except Exception as e:
            print(f"Błąd: {e}")
        finally:
            self.sock.close()
            print("Koniec połączenia")


if __name__ == "__main__":
    client = BankClient()
    client.run()