import os
import sys
import subprocess
import configparser
import time
from pathlib import Path

# ===== MEJORA #48: Manejo de Errores Mejorado =====
try:
    from error_handler import handle_error, MountError, ConnectionError, PermissionError
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False
    MountError = Exception
    ConnectionError = Exception
    PermissionError = Exception

class RcloneManager:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        
        # Detectar si estamos ejecutando desde PyInstaller
        if getattr(sys, 'frozen', False):
            # Ejecutando desde ejecutable empaquetado
            base_path = os.path.dirname(sys.executable)
        else:
            # Ejecutando desde script Python
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        self.rclone_exe = os.path.join(base_path, "rclone.exe")
        self.rclone_config_dir = os.path.join(os.path.expanduser("~"), ".config", "rclone")
        self.rclone_config_file = os.path.join(self.rclone_config_dir, "rclone.conf")
        os.makedirs(self.rclone_config_dir, exist_ok=True)
        self.mount_process = None
    
    @staticmethod
    def detect_mounted_drives():
        """
        Detecta todas las unidades montadas por rclone en el sistema
        Retorna: lista de letras de unidad (ej: ['V', 'W'])
        """
        mounted_drives = []
        try:
            # Ejecutar comando tasklist para buscar procesos rclone
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq rclone.exe', '/FO', 'CSV', '/NH'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if 'rclone.exe' in result.stdout:
                # Hay procesos rclone activos, verificar qué unidades están montadas
                for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    drive_path = f"{letter}:\\"
                    if os.path.exists(drive_path):
                        # Verificar si es un montaje de rclone
                        try:
                            # Intentar leer el volumen
                            result = subprocess.run(
                                ['cmd', '/c', 'vol', f'{letter}:'],
                                capture_output=True,
                                text=True,
                                timeout=1
                            )
                            # Si tiene "rclone" en el output, es un montaje de rclone
                            if 'rclone' in result.stdout.lower() or result.returncode != 0:
                                mounted_drives.append(letter)
                        except:
                            pass
        except Exception as e:
            pass
        
        return mounted_drives
    
    @staticmethod
    def unmount_all_drives():
        """
        Desmonta todas las unidades montadas por rclone
        Retorna: (success, message)
        """
        try:
            # Terminar todos los procesos rclone
            subprocess.run(
                ['taskkill', '/F', '/IM', 'rclone.exe'],
                capture_output=True,
                timeout=5
            )
            time.sleep(1)
            return True, "Todas las unidades desmontadas correctamente"
        except Exception as e:
            return False, f"Error al desmontar: {str(e)}"

    def create_rclone_config(self, profile_name):
        """Create or update rclone configuration for a profile"""
        config = self.config_manager.get_config(profile_name)
        if not config:
            return False

        rclone_config = configparser.ConfigParser()
        
        # Load existing config if it exists
        if os.path.exists(self.rclone_config_file):
            rclone_config.read(self.rclone_config_file)

        # Add or update the profile
        section_name = f"vultr_{profile_name}"
        if not rclone_config.has_section(section_name):
            rclone_config.add_section(section_name)

        rclone_config.set(section_name, 'type', 's3')
        rclone_config.set(section_name, 'provider', 'Other')
        rclone_config.set(section_name, 'access_key_id', config['access_key'])
        rclone_config.set(section_name, 'secret_access_key', config['secret_key'])
        rclone_config.set(section_name, 'endpoint', f"https://{config['host_base']}")
        rclone_config.set(section_name, 'acl', 'private')

        # Save configuration
        with open(self.rclone_config_file, 'w') as f:
            rclone_config.write(f)

        return section_name

    def mount_drive(self, profile_name, drive_letter, bucket_name=None):
        """Mount the storage as a network drive"""
        section_name = self.create_rclone_config(profile_name)
        if not section_name:
            return False, "Profile not found", None

        # Check if drive letter is available
        drive_path = f"{drive_letter}:\\"
        if os.path.exists(drive_path):
            return False, f"Drive letter {drive_letter}: is already in use", None

        # Build mount path
        if bucket_name:
            remote_path = f"{section_name}:{bucket_name}"
        else:
            remote_path = f"{section_name}:"

        mount_point = f"{drive_letter}:"

        # Find rclone executable - Mejorado para versión portable
        if getattr(sys, 'frozen', False):
            # Ejecutando desde ejecutable empaquetado
            base_path = os.path.dirname(sys.executable)
        else:
            # Ejecutando desde script Python
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        rclone_exe_paths = [
            os.path.join(base_path, "rclone.exe"),  # Mismo directorio que el ejecutable
            self.rclone_exe,  # Local rclone.exe
            os.path.join(base_path, "rclone-v1.71.2-windows-amd64", "rclone.exe"),
            os.path.join(os.path.dirname(base_path), "rclone.exe"),  # Directorio padre
            "rclone"  # System PATH
        ]
        
        rclone_path = None
        for path in rclone_exe_paths:
            if path != "rclone" and os.path.exists(path):
                rclone_path = path
                break
            elif path == "rclone":
                # Intentar ejecutar rclone del PATH
                try:
                    subprocess.run([path, "version"], capture_output=True, timeout=2)
                    rclone_path = path
                    break
                except:
                    pass
        
        if not rclone_path:
            return False, (
                "Rclone executable not found. Please ensure rclone.exe is in the same folder as the application. "
                f"Searched paths: {base_path}"
            ), None

        # Mount command optimized for Windows and multi-machine support
        cmd = [
            rclone_path,
            "mount",
            remote_path,
            mount_point,
            "--vfs-cache-mode", "writes",
            "--vfs-cache-max-age", "1h",
            "--vfs-cache-poll-interval", "15s",  # Actualizar más frecuentemente
            "--vfs-read-chunk-size", "128M",
            "--vfs-read-chunk-size-limit", "2G",
            "--buffer-size", "32M",
            "--timeout", "1h",
            "--retries", "3",
            "--low-level-retries", "10",
            "--stats", "1m",
            "--no-modtime",  # No sincronizar tiempos de modificación (evita conflictos)
            "--no-checksum",  # No verificar checksums (más rápido)
            "--dir-cache-time", "5m",  # Cache de directorio más corto
            "--volname", f"Vultr-{profile_name}"
        ]

        try:
            # Start the mount process in background for Windows
            # Use CREATE_NEW_PROCESS_GROUP to allow it to run independently
            self.mount_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                cwd=os.path.dirname(rclone_path)
            )
            
            # Wait for the mount to initialize
            import time
            time.sleep(5)
            
            # Check if the process is still running
            if self.mount_process.poll() is None:
                # Check if the drive actually appeared
                if os.path.exists(drive_path):
                    return True, f"Montado exitosamente en {drive_letter}:", self.mount_process
                else:
                    # Give it more time for slow connections
                    time.sleep(5)
                    if os.path.exists(drive_path):
                        return True, f"Montado exitosamente en {drive_letter}:", self.mount_process
                    else:
                        self.mount_process.terminate()
                        return False, (
                            f"No se pudo montar la unidad {drive_letter}:\n\n"
                            f"El proceso de montaje inició pero la unidad no apareció.\n\n"
                            f"Posibles causas:\n"
                            f"1. El bucket está vacío (crea una carpeta de prueba primero)\n"
                            f"2. Problemas de conexión con Vultr\n"
                            f"3. Credenciales incorrectas\n"
                            f"4. WinFsp necesita reinicio del sistema\n\n"
                            f"SOLUCIÓN:\n"
                            f"- Sube al menos 1 archivo al bucket desde la pestaña Principal\n"
                            f"- Verifica tu conexión a internet\n"
                            f"- Reinicia Windows y vuelve a intentar"
                        ), None
            else:
                # Process exited, check the error
                stdout, stderr = self.mount_process.communicate()
                error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "Error desconocido"
                
                # Detectar si es error de WinFsp
                if "winfsp" in error_msg.lower() or "cannot find winfsp" in error_msg.lower() or "cgofuse" in error_msg.lower():
                    return False, (
                        "⚠️ WinFsp no está instalado correctamente en este sistema.\n\n"
                        "SOLUCIÓN RÁPIDA:\n"
                        "1. Cierra esta aplicación\n"
                        "2. Ejecuta: INSTALAR_WINFSP.bat (en la carpeta del programa)\n"
                        "3. Reinicia Windows (importante)\n"
                        "4. Vuelve a abrir VultrDriveDesktop\n\n"
                        "O descarga manualmente:\n"
                        "https://winfsp.dev/rel/\n"
                        "Archivo: winfsp-2.0.23075.msi\n\n"
                        "WinFsp es REQUERIDO para montar unidades en Windows.\n"
                        "Es gratuito y de código abierto."
                    ), None
                
                return False, f"Error al montar: {error_msg}", None
                
        except FileNotFoundError as e:
            if ERROR_HANDLING_AVAILABLE:
                error = MountError(
                    f"Ejecutable de Rclone no encontrado en: {rclone_path}",
                    suggestion="Verifica que rclone.exe esté en la carpeta del programa",
                    original_error=e
                )
                return False, error.get_user_message(), None
            return False, f"Ejecutable de Rclone no encontrado en: {rclone_path}", None
        except Exception as e:
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(e, context=f"mount_drive({profile_name}, {drive_letter}, {bucket_name})")
                return False, error.get_user_message(), None
            return False, f"Error al montar: {str(e)}", None

    def unmount_drive(self, drive_letter):
        """Unmount the drive usando net use (específico para esa letra)"""
        try:
            import time
            drive_path = f"{drive_letter}:"
            
            # Primero intentar con net use para desmontar SOLO esa letra
            result = subprocess.run(
                ['net', 'use', drive_path, '/delete', '/yes'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            time.sleep(1.0)
            
            # Verificar si se desmontó
            vol_result = subprocess.run(
                ['cmd', '/c', 'vol', drive_path],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if vol_result.returncode != 0:
                # Se desmontó exitosamente
                if self.mount_process:
                    self.mount_process = None
                return True, f"Unidad {drive_letter}: desmontada exitosamente"
            
            # Si net use no funcionó, terminar el proceso rclone
            if self.mount_process:
                try:
                    self.mount_process.terminate()
                    self.mount_process.wait(timeout=2)
                    self.mount_process = None
                    time.sleep(0.5)
                except:
                    pass
            
            # Verificar nuevamente
            vol_result2 = subprocess.run(
                ['cmd', '/c', 'vol', drive_path],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if vol_result2.returncode != 0:
                return True, f"Unidad {drive_letter}: desmontada exitosamente"
            else:
                return False, f"No se pudo desmontar la unidad {drive_letter}.\nIntenta cerrar todos los archivos abiertos desde esta unidad."
                
        except Exception as e:
            return False, f"Error al desmontar: {str(e)}"

    def is_mounted(self):
        """Check if a drive is currently mounted"""
        return self.mount_process is not None and self.mount_process.poll() is None

    def list_buckets_rclone(self, profile_name):
        """List all buckets using rclone"""
        section_name = self.create_rclone_config(profile_name)
        if not section_name:
            return []

        cmd = [self.rclone_exe, "lsd", f"{section_name}:"]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                buckets = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split()
                        if len(parts) >= 5:
                            bucket_name = parts[-1]
                            buckets.append(bucket_name)
                return buckets
            return []
        except Exception as e:
            print(f"Error listing buckets: {e}")
            return []
