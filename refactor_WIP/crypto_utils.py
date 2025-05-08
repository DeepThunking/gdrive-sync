import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes

class CryptoUtils:
    def __init__(self, key_file='encryption.key'):
        self.key_file = key_file
        self.key = self.load_or_generate_key()

    def load_or_generate_key(self):
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                return f.read()
        else:
            key = get_random_bytes(32)
            with open(self.key_file, 'wb') as f:
                f.write(key)
            return key

    def encrypt_file(self, input_path, output_path):
        cipher = AES.new(self.key, AES.MODE_CBC)
        with open(input_path, 'rb') as f:
            data = pad(f.read(), AES.block_size)
        with open(output_path, 'wb') as f:
            f.write(cipher.iv)
            f.write(cipher.encrypt(data))

    def decrypt_file(self, input_path, output_path):
        with open(input_path, 'rb') as f:
            iv = f.read(16)
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            decrypted = unpad(cipher.decrypt(f.read()), AES.block_size)
        with open(output_path, 'wb') as f:
            f.write(decrypted)