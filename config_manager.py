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
    GLOBAL_SETTINGS_KEY = '_global_settings'
    SAVED_MOUNTS_KEY = '_saved_mounts'
    def __init__(self, config_file='config.json', enable_encryption=False):
        # ===== DESHABILITAR ENCRIPTACIÓN: Credenciales en texto plano para portabilidad =====
        # Detectar si estamos ejecutando desde PyInstaller
        if getattr(sys, 'frozen', False):
            # Ejecutando desde ejecutable empaquetado
            base_path = os.path.dirname(sys.executable)
        else:
            # Ejecutando desde script Python
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        self.base_path = base_path
        self.config_file = os.path.join(base_path, config_file)
        
        # ===== ENCRIPTACIÓN DESHABILITADA: Siempre usar texto plano =====
        self.encryption_enabled = False  # Forzar deshabilitado
        self.encryption_manager = None
        
        self.configs = self.load_configs()
        if not isinstance(self.configs, dict):
            self.configs = {}
        if self.GLOBAL_SETTINGS_KEY not in self.configs:
            self.configs[self.GLOBAL_SETTINGS_KEY] = {
                'auto_refresh_days': 7,
                'auto_mount_enabled': False
            }
            self.save_configs()
        else:
            settings = self.configs.get(self.GLOBAL_SETTINGS_KEY, {})
            changed = False
            if 'auto_refresh_days' not in settings:
                settings['auto_refresh_days'] = 7
                changed = True
            if 'auto_mount_enabled' not in settings:
                settings['auto_mount_enabled'] = False
                changed = True
            if changed:
                self.configs[self.GLOBAL_SETTINGS_KEY] = settings
                self.save_configs()

    def load_configs(self):
        """Cargar configuraciones y desencriptar credenciales"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    configs = json.load(f)
                
                # ===== SIN ENCRIPTACIÓN: Decodificar base64 y guardar en texto plano =====
                # Decodificar credenciales de base64 a texto plano para portabilidad
                if configs:
                    import base64
                    needs_save = False
                    
                    for profile_name, profile_data in configs.items():
                        if isinstance(profile_data, dict):
                            # Decodificar access_key si está en base64
                            if 'access_key' in profile_data and profile_data['access_key']:
                                access_key = profile_data['access_key']
                                # Si parece ser base64, decodificar
                                if len(access_key) > 50 and ('=' in access_key or access_key.replace('+', '').replace('/', '').replace('=', '').replace('-', '').replace('_', '').isalnum()):
                                    try:
                                        decoded_bytes = base64.b64decode(access_key)
                                        decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
                                        
                                        # Si es un token Fernet (gAAAAA), simplemente ignorarlo
                                        # No hacer nada, dejar que el usuario reingrese las credenciales manualmente
                                        if decoded_str.startswith('gAAAAA'):
                                            # Token Fernet - no se puede usar, dejar vacío
                                            profile_data['access_key'] = ''
                                            needs_save = True
                                        elif not (decoded_str.startswith('Z0FB') or decoded_str.startswith('gAAAAA')):
                                            # Es texto plano válido después de decodificar
                                            if access_key != decoded_str:
                                                profile_data['access_key'] = decoded_str
                                                needs_save = True
                                    except Exception as e:
                                        print(f"[ConfigManager] No se pudo decodificar access_key: {e}")
                            
                            # Decodificar secret_key si está en base64
                            if 'secret_key' in profile_data and profile_data['secret_key']:
                                secret_key = profile_data['secret_key']
                                if len(secret_key) > 50 and ('=' in secret_key or secret_key.replace('+', '').replace('/', '').replace('=', '').replace('-', '').replace('_', '').isalnum()):
                                    try:
                                        decoded_bytes = base64.b64decode(secret_key)
                                        decoded_str = decoded_bytes.decode('utf-8', errors='ignore')
                                        
                                        if decoded_str.startswith('gAAAAA'):
                                            # Token Fernet - no se puede usar, dejar vacío
                                            profile_data['secret_key'] = ''
                                            needs_save = True
                                        elif not (decoded_str.startswith('Z0FB') or decoded_str.startswith('gAAAAA')):
                                            # Es texto plano válido
                                            if secret_key != decoded_str:
                                                profile_data['secret_key'] = decoded_str
                                                needs_save = True
                                    except Exception as e:
                                        print(f"[ConfigManager] No se pudo decodificar secret_key: {e}")
                    
                    # Normalizar metadatos adicionales para cada perfil
                    for profile_name, profile_data in configs.items():
                        if not isinstance(profile_data, dict) or profile_name.startswith('_'):
                            continue
                        profile_type = profile_data.get('type', 's3')
                        normalized_type = profile_type.lower() if isinstance(profile_type, str) else 's3'
                        if profile_data.get('type') != normalized_type:
                            profile_data['type'] = normalized_type
                            needs_save = True
                        profile_type = normalized_type
                        if profile_type == 's3' and not profile_data.get('default_bucket'):
                            profile_data['default_bucket'] = profile_name
                            needs_save = True
                        if 'auto_mount' not in profile_data:
                            profile_data['auto_mount'] = True
                            needs_save = True
                        if 'auto_mount_letter' not in profile_data:
                            profile_data['auto_mount_letter'] = 'V'
                            needs_save = True
                        if 'refresh_interval_days' not in profile_data:
                            profile_data['refresh_interval_days'] = configs.get(self.GLOBAL_SETTINGS_KEY, {}).get('auto_refresh_days', 7)
                            needs_save = True
                        session_block = profile_data.get('session')
                        if not isinstance(session_block, dict):
                            session_block = {}
                            profile_data['session'] = session_block
                            needs_save = True
                        for key in ('last_login_ts', 'last_check_ts', 'last_status', 'last_error', 'last_mount_letter', 'last_mount_ts'):
                            if key not in session_block:
                                session_block[key] = None
                                needs_save = True
                    # Guardar configuraciones decodificadas si hubo cambios
                    if needs_save:
                        try:
                            self.configs = configs
                            self.save_configs()
                            print(f"[ConfigManager] Credenciales decodificadas y guardadas en texto plano")
                        except Exception as e:
                            print(f"[ConfigManager] Error al guardar credenciales decodificadas: {e}")
                
                return configs
            except json.JSONDecodeError as e:
                print(f"[ConfigManager] Error al leer archivo de configuración: {e}")
                return {}
            except Exception as e:
                print(f"[ConfigManager] Error inesperado al cargar configuraciones: {e}")
                return {}
        return {}

    def save_configs(self):
        """Guardar configuraciones en texto plano (sin encriptación)"""
        try:
            # ===== SIN ENCRIPTACIÓN: Guardar credenciales en texto plano =====
            # Limpiar campos internos antes de guardar
            configs_to_save = {}
            for profile_name, profile_data in self.configs.items():
                if isinstance(profile_data, dict):
                    clean_data = {k: v for k, v in profile_data.items() 
                                 if not k.startswith('_')}  # Excluir campos internos
                    configs_to_save[profile_name] = clean_data
                else:
                    configs_to_save[profile_name] = profile_data
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(configs_to_save, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Error al guardar configuraciones: {e}")
            raise

    def add_config(self, profile_name, access_key, secret_key, host_base):
        """
        Mantener compatibilidad con versiones anteriores que solo manejaban S3.
        """
        self.save_profile(
            profile_name,
            's3',
            access_key=access_key,
            secret_key=secret_key,
            host_base=host_base,
        )

    def save_profile(self, profile_name: str, profile_type: str, **fields):
        """
        Crear o actualizar un perfil (S3 o MEGA) en texto plano.
        """
        profile = self.configs.get(profile_name, {}).copy()
        profile_type = (profile_type or 's3').lower()
        profile['type'] = profile_type

        def _clean(value):
            if isinstance(value, str):
                return value.strip()
            return value

        if profile_type == 'mega':
            profile['email'] = _clean(fields.get('email', ''))
            profile['password'] = _clean(fields.get('password', ''))
            profile.pop('access_key', None)
            profile.pop('secret_key', None)
            profile.pop('host_base', None)
            profile.pop('default_bucket', None)
        else:
            profile['access_key'] = _clean(fields.get('access_key', ''))
            profile['secret_key'] = _clean(fields.get('secret_key', ''))
            profile['host_base'] = _clean(fields.get('host_base', ''))
            profile.pop('email', None)
            profile.pop('password', None)

        self.configs[profile_name] = profile
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
        return [
            name for name in self.configs.keys()
            if not name.startswith('_')
        ]

    def get_global_refresh_interval(self, default=7):
        settings = self.configs.get(self.GLOBAL_SETTINGS_KEY, {})
        return int(settings.get('auto_refresh_days', default))

    def set_global_refresh_interval(self, days: int):
        settings = self.configs.get(self.GLOBAL_SETTINGS_KEY, {})
        settings['auto_refresh_days'] = int(days)
        self.configs[self.GLOBAL_SETTINGS_KEY] = settings
        self.save_configs()

    def get_global_auto_mount(self) -> bool:
        settings = self.configs.get(self.GLOBAL_SETTINGS_KEY, {})
        return bool(settings.get('auto_mount_enabled', False))

    def set_global_auto_mount(self, enabled: bool):
        settings = self.configs.get(self.GLOBAL_SETTINGS_KEY, {})
        settings['auto_mount_enabled'] = bool(enabled)
        self.configs[self.GLOBAL_SETTINGS_KEY] = settings
        self.save_configs()

    def get_profile_refresh_interval(self, profile_name, default=None):
        profile = self.get_config(profile_name) or {}
        if default is None:
            default = self.get_global_refresh_interval()
        return int(profile.get('refresh_interval_days', default))

    def set_profile_refresh_interval(self, profile_name, days: int):
        profile = self.configs.get(profile_name, {})
        profile['refresh_interval_days'] = int(days)
        self.configs[profile_name] = profile
        self.save_configs()

    def set_profile_auto_mount(self, profile_name: str, enabled: bool):
        profile = self.configs.get(profile_name, {})
        profile['auto_mount'] = bool(enabled)
        self.configs[profile_name] = profile
        self.save_configs()

    def set_profile_auto_mount_letter(self, profile_name: str, letter: str):
        profile = self.configs.get(profile_name, {})
        profile['auto_mount_letter'] = (letter or '').upper()
        self.configs[profile_name] = profile
        self.save_configs()

    def set_profile_default_bucket(self, profile_name: str, bucket: str):
        profile = self.configs.get(profile_name, {})
        profile['default_bucket'] = bucket or ''
        self.configs[profile_name] = profile
        self.save_configs()

    def update_profile_field(self, profile_name, field, value):
        profile = self.configs.get(profile_name, {})
        profile[field] = value
        self.configs[profile_name] = profile
        self.save_configs()

    def get_profile_session(self, profile_name):
        profile = self.get_config(profile_name) or {}
        session = profile.get('session')
        if not isinstance(session, dict):
            session = {}
        return session

    def update_profile_session(self, profile_name, **fields):
        profile = self.configs.get(profile_name, {})
        session = profile.get('session')
        if not isinstance(session, dict):
            session = {}
        session.update(fields)
        profile['session'] = session
        self.configs[profile_name] = profile
        self.save_configs()

    def get_profile_session_field(self, profile_name, field, default=None):
        session = self.get_profile_session(profile_name)
        return session.get(field, default)

    # ===== Persistencia de montajes múltiples =====

    def save_mounts(self, mounts_data):
        """Guardar lista de montajes múltiples."""
        try:
            if not isinstance(self.configs, dict):
                self.configs = {}
            self.configs[self.SAVED_MOUNTS_KEY] = mounts_data
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.configs, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Error al guardar montajes: {e}")

    def get_saved_mounts(self):
        """Obtener montajes guardados de la configuración."""
        if not isinstance(self.configs, dict):
            return []
        return self.configs.get(self.SAVED_MOUNTS_KEY, [])


