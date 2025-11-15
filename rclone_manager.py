import os
import sys
import subprocess
import configparser
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from error_handler import handle_error, MountError, ConnectionError, PermissionError
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False
    MountError = ConnectionError = PermissionError = Exception


class RcloneManager:
    """
    AbstracciA3n de rclone para esta aplicaciA3n.
    - Mantiene un archivo rclone.conf local al proyecto (portabilidad total).
    - Soporta perfiles S3 y MEGA (backend oficial de rclone).
    - Gestiona procesos de montaje por letra para permitir mA?ltiples unidades simultA?neas.
    """

    def __init__(self, config_manager):
        self.config_manager = config_manager

        if getattr(sys, 'frozen', False):
            self.base_path = os.path.dirname(sys.executable)
        else:
            self.base_path = os.path.dirname(os.path.abspath(__file__))

        self.rclone_exe = self._resolve_rclone_executable()
        self.rclone_config_dir = os.path.join(self.base_path, 'data', 'rclone')
        os.makedirs(self.rclone_config_dir, exist_ok=True)
        self.rclone_config_file = os.path.join(self.rclone_config_dir, 'rclone.conf')

        self.mount_processes: Dict[str, subprocess.Popen] = {}

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------

    def _resolve_rclone_executable(self) -> str:
        candidates = [
            os.path.join(self.base_path, 'rclone.exe'),
            os.path.join(self.base_path, 'rclone', 'rclone.exe'),
            os.path.join(self.base_path, 'rclone-v1.71.2-windows-amd64', 'rclone.exe'),
            os.path.join(self.base_path, 'dependencies', 'rclone.exe'),
            os.path.join(os.path.dirname(self.base_path), 'rclone.exe'),
            'rclone.exe',
            'rclone',
        ]

        checked_paths = []

        for candidate in candidates:
            normalized = candidate
            checked_paths.append(normalized)
            try:
                if candidate in ('rclone', 'rclone.exe'):
                    result = subprocess.run([candidate, 'version'], capture_output=True, text=True, timeout=2)
                    if result.returncode == 0:
                        return candidate
                else:
                    if os.path.exists(candidate):
                        return candidate
            except Exception:
                continue

        # Búsqueda profunda dentro del repositorio para mantener portabilidad
        search_roots = [
            self.base_path,
            os.path.join(self.base_path, 'dependencies'),
            os.path.join(self.base_path, 'rclone-v1.71.2-windows-amd64'),
        ]

        for root in search_roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    if filename.lower() == 'rclone.exe':
                        discovered = os.path.join(dirpath, filename)
                        return discovered

        checked_text = '\n- '.join(checked_paths)
        raise FileNotFoundError(
            "No se encontró rclone.exe dentro del repositorio.\n"
            "Copia rclone.exe a la carpeta del proyecto (por ejemplo dentro de "
            "'rclone-v1.71.2-windows-amd64') o deja el binario en cualquiera de las rutas buscadas:\n"
            f"- {checked_text}"
        )

    def _build_base_cmd(self, *args) -> List[str]:
        return [
            self.rclone_exe,
            '--config',
            self.rclone_config_file,
            *args,
        ]

    def _obscure_password(self, password: str) -> str:
        """
        Usa `rclone obscure` para convertir la contraseA3a en formato aceptado por rclone.conf.
        """
        cmd = [self.rclone_exe, 'obscure', password]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"No se pudo oscurecer contraseA3a MEGA: {result.stderr.strip() or result.stdout.strip()}")
        return result.stdout.strip()

    def _write_config(self, parser: configparser.ConfigParser):
        with open(self.rclone_config_file, 'w', encoding='utf-8') as cfg:
            parser.write(cfg)

    def _load_config_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        if os.path.exists(self.rclone_config_file):
            with open(self.rclone_config_file, 'r', encoding='utf-8-sig') as cfg:
                parser.read_file(cfg)
        return parser

    def _get_section_name(self, profile_name: str) -> str:
        return f"profile_{profile_name}"

    # ------------------------------------------------------------------
    # ConfiguraciA3n
    # ------------------------------------------------------------------

    def create_rclone_config(self, profile_name: str) -> Optional[str]:
        """
        Crea o actualiza la secciA3n de rclone para un perfil.
        Soporta perfiles tipo `s3` y `mega`.
        """
        profile = self.config_manager.get_config(profile_name)
        if not profile:
            return None

        profile_type = profile.get('type', 's3').lower()
        parser = self._load_config_parser()
        section_name = self._get_section_name(profile_name)

        if not parser.has_section(section_name):
            parser.add_section(section_name)

        if profile_type == 'mega':
            email = profile.get('email')
            password = profile.get('password')
            if not email or not password:
                raise ValueError(f"Perfil '{profile_name}' de tipo MEGA requiere email y password.")

            obscured = profile.get('rclone_obscured_pass')
            if not obscured:
                obscured = self._obscure_password(password)
                self.config_manager.update_profile_field(profile_name, 'rclone_obscured_pass', obscured)

            parser.set(section_name, 'type', 'mega')
            parser.set(section_name, 'user', email)
            parser.set(section_name, 'pass', obscured)
        else:
            access_key = profile.get('access_key')
            secret_key = profile.get('secret_key')
            host_base = profile.get('host_base')
            if not access_key or not secret_key or not host_base:
                raise ValueError(f"Perfil '{profile_name}' requiere Access Key, Secret Key y host_base.")

            parser.set(section_name, 'type', 's3')
            parser.set(section_name, 'provider', 'Other')
            parser.set(section_name, 'access_key_id', access_key)
            parser.set(section_name, 'secret_access_key', secret_key)
            parser.set(section_name, 'endpoint', f"https://{host_base}")
            parser.set(section_name, 'acl', 'private')

        self._write_config(parser)
        return section_name

    # ------------------------------------------------------------------
    # Operaciones de montaje
    # ------------------------------------------------------------------

    def mount_drive(self, profile_name: str, drive_letter: str, bucket_name: Optional[str] = None) -> Tuple[bool, str, Optional[subprocess.Popen]]:
        """
        Monta un perfil en una letra de unidad. Retorna (success, message, process).
        Para S3 requiere bucket; para MEGA ignora bucket y monta la raA-z (o subcarpeta si se proporciona).
        """
        drive_letter = (drive_letter or '').upper()
        if not drive_letter:
            return False, "Letra de unidad no vA?lida.", None

        section_name = self.create_rclone_config(profile_name)
        if not section_name:
            return False, f"No existe configuraciA3n para el perfil '{profile_name}'.", None

        profile = self.config_manager.get_config(profile_name) or {}
        profile_type = profile.get('type', 's3').lower()

        target = ''
        if profile_type == 's3':
            bucket = bucket_name or profile.get('default_bucket')
            if not bucket:
                return False, f"El perfil '{profile_name}' no tiene bucket por defecto configurado.", None
            target = f"{section_name}:{bucket}"
        else:  # mega
            subpath = bucket_name or ''
            target = f"{section_name}:{subpath}" if subpath else f"{section_name}:"

        mount_point = f"{drive_letter}:"
        drive_path = f"{drive_letter}:\\"

        if os.path.exists(drive_path):
            # Si ya existe, intentar desmontar antes
            self.unmount_drive_by_letter(drive_letter)

        cmd = self._build_base_cmd(
            'mount',
            target,
            mount_point,
            '--vfs-cache-mode', 'writes',
            '--vfs-cache-max-age', '1h',
            '--vfs-cache-poll-interval', '15s',
            '--vfs-read-chunk-size', '128M',
            '--vfs-read-chunk-size-limit', '2G',
            '--buffer-size', '32M',
            '--timeout', '1h',
            '--retries', '3',
            '--low-level-retries', '10',
            '--stats', '1m',
            '--no-modtime',
            '--no-checksum',
            '--dir-cache-time', '5m',
            '--volname', f"{profile_name}-{profile_type}".replace(' ', '_')
        )
        cmd.extend(['--links'])

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                cwd=os.path.dirname(self.rclone_exe) if os.path.isfile(self.rclone_exe) else None
            )
        except FileNotFoundError as exc:
            if ERROR_HANDLING_AVAILABLE:
                error = MountError(f"No se pudo ejecutar rclone: {exc}", suggestion="Verifica que rclone.exe estA? en la carpeta del proyecto.")
                return False, error.get_user_message(), None
            return False, f"No se pudo ejecutar rclone: {exc}", None
        except Exception as exc:
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(exc, context="mount_drive")
                return False, error.get_user_message(), None
            return False, f"Error al iniciar rclone: {exc}", None

        time.sleep(5)
        if process.poll() is None:
            if os.path.exists(drive_path):
                self.mount_processes[drive_letter] = process
                return True, f"Montado exitosamente en {drive_letter}:", process
            # Dar tiempo adicional
            time.sleep(5)
            if os.path.exists(drive_path):
                self.mount_processes[drive_letter] = process
                return True, f"Montado exitosamente en {drive_letter}:", process

        stdout, stderr = process.communicate(timeout=5)
        error_msg = stderr.decode('utf-8', errors='ignore') if stderr else stdout.decode('utf-8', errors='ignore')
        return False, error_msg or "Error desconocido al montar con rclone.", None

    def mount_profile(self, profile_name: str, drive_letter: str, bucket_name: Optional[str] = None):
        """
        Atajo para montar usando configuraciA3n por defecto del perfil (auto_mount).
        """
        profile = self.config_manager.get_config(profile_name) or {}
        bucket = bucket_name or profile.get('default_bucket')
        return self.mount_drive(profile_name, drive_letter, bucket)

    def unmount_drive(self, drive_letter: str) -> Tuple[bool, str]:
        return self.unmount_drive_by_letter(drive_letter)

    def unmount_drive_by_process(self, process: subprocess.Popen, drive_letter: Optional[str] = None) -> Tuple[bool, str]:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        if drive_letter:
            self.mount_processes.pop(drive_letter.upper(), None)
        return True, f"Proceso rclone terminado para {drive_letter or 'unidad desconocida'}"

    def _find_process_ids_for_letter(self, drive_letter: str) -> List[int]:
        try:
            from drive_detector import DriveDetector
            return DriveDetector.find_process_ids_for_letter(drive_letter)
        except Exception:
            return []

    def unmount_drive_by_letter(self, drive_letter: str) -> Tuple[bool, str]:
        drive_letter = (drive_letter or '').upper()
        if not drive_letter:
            return False, "Letra de unidad no vA?lida."

        drive_path = f"{drive_letter}:"
        subprocess.run(['net', 'use', drive_path, '/delete', '/yes'], capture_output=True, text=True)
        time.sleep(1)

        stored_process = self.mount_processes.pop(drive_letter, None)
        if stored_process:
            success, message = self.unmount_drive_by_process(stored_process, drive_letter)
            if success:
                return True, message

        vol_check = subprocess.run(['cmd', '/c', 'vol', drive_path], capture_output=True, text=True)
        if vol_check.returncode != 0:
            return True, f"Unidad {drive_letter}: desmontada exitosamente"

        for pid in self._find_process_ids_for_letter(drive_letter):
            subprocess.run(['taskkill', '/PID', str(pid), '/F', '/T'], capture_output=True, text=True)
            time.sleep(0.5)

        vol_check = subprocess.run(['cmd', '/c', 'vol', drive_path], capture_output=True, text=True)
        if vol_check.returncode != 0:
            return True, f"Unidad {drive_letter}: desmontada exitosamente"

        return False, f"No se pudo desmontar la unidad {drive_letter}. Cierra archivos abiertos y vuelve a intentar."

    @staticmethod
    def detect_mounted_drives() -> List[str]:
        mounted = []
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq rclone.exe', '/FO', 'CSV', '/NH'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if 'rclone.exe' in result.stdout.lower():
                for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    path = f"{letter}:\\"
                    if os.path.exists(path):
                        mounted.append(letter)
        except Exception:
            pass
        return mounted

    @staticmethod
    def unmount_all_drives() -> Tuple[bool, str]:
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'rclone.exe'], capture_output=True, timeout=5)
            time.sleep(1)
            return True, "Todas las unidades desmontadas correctamente"
        except Exception as exc:
            return False, f"Error al desmontar: {exc}"

    def is_mounted(self) -> bool:
        for process in self.mount_processes.values():
            if process and process.poll() is None:
                return True
        return False

    # ------------------------------------------------------------------
    # Utilidades y verificaciones
    # ------------------------------------------------------------------

    def run_rclone_command(self, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
        cmd = self._build_base_cmd(*args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def list_buckets_rclone(self, profile_name: str) -> List[str]:
        section = self.create_rclone_config(profile_name)
        if not section:
            return []

        try:
            result = self.run_rclone_command(['lsd', f'{section}:'], timeout=20)
            if result.returncode != 0:
                return []
            buckets = []
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    buckets.append(parts[-1])
            return buckets
        except Exception:
            return []
