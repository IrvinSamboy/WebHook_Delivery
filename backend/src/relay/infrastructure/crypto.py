from cryptography.fernet import Fernet


class SecretCipher:
    """Cifra los secretos antes de guardarlos y los descifra al leerlos."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()
