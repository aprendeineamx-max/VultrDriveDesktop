import json
import os
import sys

# ===== MEJORA #36: Encriptación de Credenciales =====
try:
    from encryption_manager import get_encryption_manager, EncryptionError
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print("[ConfigManager] Advertencia: encryption_manager no disponible. Credenciales se guardarán en texto plano.")

class ConfigManager:
    def __init__(self, config_file='config.json', enable_encryption=True):
        # Detectar si estamos ejecutando desde PyInstaller
        if getattr(sys, 'frozen', False):
            # Ejecutando desde ejecutable empaquetado
            base_path = os.path.dirname(sys.executable)
        else:
            # Ejecutando desde script Python
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        self.config_file = os.path.join(base_path, config_file)
        
        # ===== MEJORA #36: Inicializar encriptación =====
        self.encryption_enabled = enable_encryption and ENCRYPTION_AVAILABLE
        if self.encryption_enabled:
            try:
                self.encryption_manager = get_encryption_manager()
            except Exception as e:
                print(f"[ConfigManager] Error al inicializar encriptación: {e}")
                self.encryption_enabled = False
        else:
            self.encryption_manager = None
        
        self.configs = self.load_configs()

    def load_configs(self):
        """Cargar configuraciones y desencriptar credenciales"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                
                # ===== MEJORA #36: Desencriptar credenciales =====
                if self.encryption_enabled and configs:
                    for profile_name, profile_data in configs.items():
                        if isinstance(profile_data, dict):
                            try:
                                decrypted = self.encryption_manager.decrypt_dict(
                                    profile_data,
                                    ['access_key', 'secret_key']
                                )
                                configs[profile_name] = decrypted
                            except EncryptionError as e:
                                print(f"[ConfigManager] Error al desencriptar perfil '{profile_name}': {e}")
                                # Continuar con datos sin desencriptar (puede ser texto plano antiguo)
                
                return configs
            except json.JSONDecodeError as e:
                print(f"[ConfigManager] Error al leer archivo de configuración: {e}")
                return {}
            except Exception as e:
                print(f"[ConfigManager] Error inesperado al cargar configuraciones: {e}")
                return {}
        return {}

    def save_configs(self):
        """Guardar configuraciones y encriptar credenciales"""
        try:
            # ===== MEJORA #36: Encriptar credenciales antes de guardar =====
            configs_to_save = self.configs.copy()
            
            if self.encryption_enabled:
                for profile_name, profile_data in configs_to_save.items():
                    if isinstance(profile_data, dict):
                        try:
                            encrypted = self.encryption_manager.encrypt_dict(
                                profile_data,
                                ['access_key', 'secret_key']
                            )
                            configs_to_save[profile_name] = encrypted
                        except EncryptionError as e:
                            print(f"[ConfigManager] Error al encriptar perfil '{profile_name}': {e}")
                            # Guardar sin encriptar si falla (fallback)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(configs_to_save, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Error al guardar configuraciones: {e}")
            raise

    def add_config(self, profile_name, access_key, secret_key, host_base):
        """
        Agregar o actualizar configuración de perfil
        
        Las credenciales se encriptarán automáticamente al guardar
        """
        self.configs[profile_name] = {
            'access_key': access_key,
            'secret_key': secret_key,
            'host_base': host_base
        }
        self.save_configs()
    
    def is_encryption_enabled(self):
        """Verificar si la encriptación está habilitada"""
        return self.encryption_enabled
    
    def migrate_to_encryption(self, force=False):
        """
        Migrar configuraciones existentes (texto plano) a encriptadas
        
        Args:
            force: Si True, forzar migración incluso si parece estar encriptado
        
        Returns:
            Número de perfiles migrados
        """
        if not self.encryption_enabled:
            return 0
        
        migrated = 0
        for profile_name, profile_data in self.configs.items():
            if isinstance(profile_data, dict):
                access_key = profile_data.get('access_key', '')
                secret_key = profile_data.get('secret_key', '')
                
                # Verificar si ya está encriptado con nuestro sistema
                is_encrypted = False
                if access_key:
                    is_encrypted = self.encryption_manager._is_encrypted(access_key)
                
                # Si no está encriptado (o forzamos), encriptar
                if force or not is_encrypted:
                    try:
                        # Verificar si realmente está encriptado intentando desencriptar
                        needs_encryption = True
                        if access_key and len(access_key) > 100:
                            try:
                                # Intentar desencriptar para verificar
                                test_decrypted = self.encryption_manager.decrypt(access_key)
                                # Si el resultado es diferente al original, ya está encriptado
                                if test_decrypted != access_key and len(test_decrypted) < len(access_key):
                                    needs_encryption = False  # Ya está encriptado correctamente
                            except Exception:
                                # No se pudo desencriptar, necesita encriptación
                                needs_encryption = True
                        
                        if needs_encryption:
                            # Si el access_key parece ser base64 pero no Fernet, 
                            # intentar decodificar primero
                            try:
                                import base64
                                # Intentar decodificar base64 para obtener el texto original
                                if access_key and '=' in access_key:
                                    try:
                                        decoded = base64.b64decode(access_key)
                                        # Si se decodifica, es base64 pero no Fernet
                                        # Usar el texto decodificado para encriptar
                                        profile_data['access_key'] = decoded.decode('utf-8', errors='ignore')
                                    except:
                                        pass  # No es base64 válido, usar tal cual
                                
                                if secret_key and '=' in secret_key:
                                    try:
                                        decoded = base64.b64decode(secret_key)
                                        profile_data['secret_key'] = decoded.decode('utf-8', errors='ignore')
                                    except:
                                        pass
                            except:
                                pass
                            
                            # Encriptar las credenciales
                            encrypted = self.encryption_manager.encrypt_dict(
                                profile_data,
                                ['access_key', 'secret_key']
                            )
                            self.configs[profile_name] = encrypted
                            migrated += 1
                    except Exception as e:
                        print(f"[ConfigManager] Error al migrar perfil '{profile_name}': {e}")
                        import traceback
                        traceback.print_exc()
        
        if migrated > 0:
            self.save_configs()
        
        return migrated

    def delete_config(self, profile_name):
        if profile_name in self.configs:
            del self.configs[profile_name]
            self.save_configs()

    def get_config(self, profile_name):
        return self.configs.get(profile_name)

    def list_profiles(self):
        return list(self.configs.keys())
