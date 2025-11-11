"""
Gestor de Encriptación - VultrDrive Desktop
Mejora #36: Encriptación de credenciales antes de guardar
"""

import os
import base64
import hashlib
import getpass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

class EncryptionManager:
    """
    Gestor de encriptación para credenciales
    
    Usa Fernet (AES-128 en modo CBC) para encriptación simétrica
    La clave se deriva de información del sistema del usuario
    """
    
    def __init__(self, salt=None):
        """
        Inicializar gestor de encriptación
        
        Args:
            salt: Salt personalizado (None = usar salt basado en usuario)
        """
        self.salt = salt or self._generate_salt()
        self._key = None
    
    def _generate_salt(self):
        """Generar salt único basado en usuario del sistema"""
        username = getpass.getuser()
        machine_name = os.environ.get('COMPUTERNAME', 'unknown')
        combined = f"{username}:{machine_name}:VultrDrive"
        return hashlib.sha256(combined.encode()).digest()[:16]
    
    def _get_key(self):
        """Obtener o generar clave de encriptación"""
        if self._key is None:
            # Derivar clave de información del sistema
            username = getpass.getuser()
            machine_id = os.environ.get('COMPUTERNAME', 'unknown')
            
            # Material para derivar clave
            password = f"{username}:{machine_id}:VultrDrive:2025"
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self.salt,
                iterations=100000,
                backend=default_backend()
            )
            
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self._key = Fernet(key)
        
        return self._key
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encriptar texto plano
        
        Args:
            plaintext: Texto a encriptar
            
        Returns:
            Texto encriptado (base64)
        """
        if not plaintext:
            return ""
        
        try:
            key = self._get_key()
            encrypted = key.encrypt(plaintext.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            raise EncryptionError(f"Error al encriptar: {str(e)}")
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Desencriptar texto
        
        Args:
            ciphertext: Texto encriptado (base64)
            
        Returns:
            Texto desencriptado
        """
        if not ciphertext:
            return ""
        
        # Detectar si el texto ya está encriptado
        if not self._is_encrypted(ciphertext):
            # Texto plano (compatibilidad con configuraciones antiguas)
            return ciphertext
        
        try:
            key = self._get_key()
            decoded = base64.urlsafe_b64decode(ciphertext.encode())
            decrypted = key.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            raise EncryptionError(f"Error al desencriptar: {str(e)}")
    
    def _is_encrypted(self, text: str) -> bool:
        """
        Detectar si un texto está encriptado con nuestro sistema Fernet
        
        Args:
            text: Texto a verificar
            
        Returns:
            True si está encriptado con Fernet
        """
        if not text:
            return False
        
        # Los textos encriptados con Fernet tienen características específicas:
        # 1. Son base64 URL-safe
        # 2. Tienen una longitud mínima (Fernet tokens son ~150+ caracteres)
        # 3. Pueden ser desencriptados con nuestra clave
        
        # Verificar longitud mínima (Fernet tokens son largos)
        if len(text) < 100:
            return False
        
        # Intentar desencriptar para verificar
        try:
            key = self._get_key()
            decoded = base64.urlsafe_b64decode(text.encode())
            # Si puede decodificar base64 y tiene longitud razonable, intentar desencriptar
            if len(decoded) > 0:
                # Intentar desencriptar (si falla, no está encriptado con nuestra clave)
                try:
                    key.decrypt(decoded)
                    return True
                except:
                    # No está encriptado con nuestra clave, o es texto plano en base64
                    return False
        except:
            return False
        
        return False
    
    def encrypt_dict(self, data: dict, fields: list) -> dict:
        """
        Encriptar campos específicos de un diccionario
        
        Args:
            data: Diccionario con datos
            fields: Lista de campos a encriptar
            
        Returns:
            Diccionario con campos encriptados
        """
        encrypted_data = data.copy()
        
        for field in fields:
            if field in encrypted_data and encrypted_data[field]:
                encrypted_data[field] = self.encrypt(encrypted_data[field])
        
        return encrypted_data
    
    def decrypt_dict(self, data: dict, fields: list) -> dict:
        """
        Desencriptar campos específicos de un diccionario
        
        Args:
            data: Diccionario con datos encriptados
            fields: Lista de campos a desencriptar
            
        Returns:
            Diccionario con campos desencriptados
        """
        decrypted_data = data.copy()
        
        for field in fields:
            if field in decrypted_data and decrypted_data[field]:
                try:
                    decrypted_data[field] = self.decrypt(decrypted_data[field])
                except EncryptionError:
                    # Si falla, mantener el valor original (puede ser texto plano antiguo)
                    pass
        
        return decrypted_data


class EncryptionError(Exception):
    """Excepción personalizada para errores de encriptación"""
    pass


# Singleton global
_encryption_manager_instance = None

def get_encryption_manager() -> EncryptionManager:
    """Obtener instancia global del gestor de encriptación"""
    global _encryption_manager_instance
    if _encryption_manager_instance is None:
        _encryption_manager_instance = EncryptionManager()
    return _encryption_manager_instance

