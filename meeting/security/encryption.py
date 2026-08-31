import os
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def get_cipher():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable is not set. Please configure it in your environment.")
    if isinstance(key, str):
        key = key.strip().encode()
    return Fernet(key)


def encrypt(text):
    cipher = get_cipher()
    encrypted = cipher.encrypt(text.encode())
    return encrypted.decode()


def decrypt(text):
    cipher = get_cipher()
    decrypted = cipher.decrypt(text.encode())
    return decrypted.decode()