"""
Drive Detector - Detecta unidades montadas por rclone
"""
import subprocess
import re
import time
from typing import List, Dict, Tuple

class DriveDetector:
    """Detecta y gestiona unidades montadas por rclone"""
    
    @staticmethod
    def detect_mounted_drives() -> List[Dict[str, str]]:
        """
        Detecta todas las unidades montadas (incluyendo las montadas en sesiones anteriores)
        
        Returns:
            List de diccionarios con información de las unidades:
            [
                {
                    'letter': 'V',
                    'path': 'V:',
                    'label': 'Vultr Drive',
                    'process_id': '1234',
                    'has_process': True
                },
                ...
            ]
        """
        mounted_drives = []
        
        try:
            # Buscar procesos de rclone activos
            rclone_processes = []
            try:
                result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq rclone.exe', '/FO', 'CSV', '/NH'],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                if result.returncode == 0 and 'rclone.exe' in result.stdout:
                    for line in result.stdout.strip().split('\n'):
                        if 'rclone.exe' in line:
                            parts = line.split('","')
                            if len(parts) >= 2:
                                pid = parts[1].strip('"')
                                rclone_processes.append(pid)
            except Exception:
                pass
            
            # Verificar TODAS las letras V-Z independientemente de si hay procesos
            # Esto detectará unidades montadas en sesiones anteriores
            for letter in 'VWXYZ':
                try:
                    # Intentar acceder a la unidad usando cmd /c vol
                    vol_result = subprocess.run(
                        ['cmd', '/c', 'vol', f'{letter}:'],
                        capture_output=True,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    
                    if vol_result.returncode == 0:
                        # La unidad existe, obtener la etiqueta
                        label = "Unknown"
                        for line in vol_result.stdout.split('\n'):
                            if 'Volume in drive' in line:
                                match = re.search(r'is (.+)', line)
                                if match:
                                    label = match.group(1).strip()
                                    break
                        
                        # Verificar si es una unidad montada por rclone
                        # Las unidades rclone/WinFsp pueden aparecer como "Fixed Drive"
                        # Pero las identificamos por:
                        # 1. Están en letras V-Z (nuestro rango)
                        # 2. Tienen etiqueta que contiene patrones típicos (Vultr, bucket, etc)
                        # 3. O simplemente existen en V-Z (asumimos que son nuestras)
                        
                        is_likely_rclone = False
                        
                        # Si hay procesos de rclone activos, definitivamente es de rclone
                        if rclone_processes:
                            is_likely_rclone = True
                        # Si la etiqueta contiene palabras clave típicas de object storage
                        elif any(keyword in label.lower() for keyword in ['vultr', 'bucket', 'almacen', 'storage', 's3', 'backup']):
                            is_likely_rclone = True
                        # Si está en las letras V-Z y no es una unidad física común (CD/DVD)
                        elif letter in 'VWXYZ':
                            try:
                                # Verificar que no sea un CD/DVD
                                fsutil_result = subprocess.run(
                                    ['fsutil', 'fsinfo', 'drivetype', f'{letter}:'],
                                    capture_output=True,
                                    text=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW
                                )
                                # Si no es CD-ROM, probablemente es de rclone
                                if 'CD-ROM' not in fsutil_result.stdout:
                                    is_likely_rclone = True
                            except Exception:
                                # Si no podemos verificar, asumimos que es de rclone
                                is_likely_rclone = True
                        
                        # Si cumple los criterios, la agregamos
                        if is_likely_rclone:
                            letter_pids = DriveDetector.find_process_ids_for_letter(letter)
                            mounted_drives.append({
                                'letter': letter,
                                'path': f'{letter}:',
                                'label': label,
                                'process_ids': ','.join(str(pid) for pid in letter_pids) if letter_pids else 'N/A',
                                'has_process': len(letter_pids) > 0
                            })
                except Exception:
                    continue
        
        except Exception as e:
            print(f"Error detectando unidades: {e}")
        
        return mounted_drives
    
    @staticmethod
    def find_process_ids_for_letter(drive_letter: str) -> List[int]:
        """Obtener lista de PIDs de rclone asociados a una letra."""
        try:
            ps_command = f"""
            $letter = '{drive_letter.upper()}'
            $processes = Get-WmiObject Win32_Process -Filter "name='rclone.exe'"
            foreach ($p in $processes) {{
                if ($p.CommandLine -like "* $letter:*") {{
                    Write-Output $p.ProcessId
                }}
            }}
            """
            result = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_command],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15
            )
            pids = []
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
            return pids
        except Exception:
            return []

    @staticmethod
    def unmount_drive(drive_letter: str, translator=None) -> Tuple[bool, str]:
        """
        Desmonta SOLO una unidad específica
        
        Args:
            drive_letter: Letra de la unidad (ej: 'V')
            translator: Objeto de traducciones opcional (con método get())
            
        Returns:
            Tuple (success: bool, message: str)
        """
        def tr(key, fallback):
            if translator and hasattr(translator, 'get'):
                return translator.get(key, fallback)
            return fallback
        
        try:
            import time
            drive_path = f"{drive_letter}:"
            
            print(f"[DEBUG] Iniciando desmontaje de {drive_letter}:")
            
            # ESTRATEGIA CON POWERSHELL (más confiable que WMIC)
            # PowerShell puede filtrar directamente por CommandLine
            
            # PASO 1: Buscar el PID usando PowerShell
            print(f"[DEBUG] Buscando PID con PowerShell para {drive_letter}:")
            
            pids_to_kill = DriveDetector.find_process_ids_for_letter(drive_letter)
            
            if not pids_to_kill:
                print(f"[DEBUG] No se encontro PID especifico para {drive_letter}:")
                print(f"[DEBUG] Verificando si la unidad esta montada...")
                
                vol_result = subprocess.run(
                    ['cmd', '/c', 'vol', drive_path],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5
                )

                if vol_result.returncode != 0:
                    print(f"[DEBUG] La unidad {drive_letter}: no esta montada")
                    msg = tr('drive_unmount_not_mounted', f"La unidad {drive_letter}: no está montada o ya fue desmontada")
                    return True, msg.format(drive_letter) if '{}' in msg else msg

                print(f"[DEBUG] La unidad existe pero no hay proceso rclone asociado, aplicando desmontaje forzado")
                forced, forced_msg = DriveDetector._force_dismount_letter(drive_letter)
                if forced:
                    msg = tr('drive_unmount_success', f"Unidad {drive_letter}: desmontada exitosamente")
                    return True, msg.format(drive_letter) if '{}' in msg else msg

                msg = tr('drive_unmount_no_process', f"No se pudo desmontar la unidad {drive_letter}:\nNo se encontró el proceso rclone asociado.\nIntenta usar 'Desmontar Todas' o reiniciar la aplicación.")
                return False, msg.format(drive_letter) if '{}' in msg else msg
            
            # PASO 2: Matar los PIDs específicos
            print(f"[DEBUG] Matando {len(pids_to_kill)} proceso(s): {', '.join(pids_to_kill)}")
            
            for pid in pids_to_kill:
                print(f"[DEBUG] Ejecutando taskkill /F /PID {pid}")
                result = subprocess.run(
                    ['taskkill', '/F', '/PID', pid],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5
                )
                if result.returncode == 0:
                    print(f"[DEBUG] PID {pid} terminado exitosamente")
                else:
                    print(f"[DEBUG] Error al terminar PID {pid}: {result.stderr}")
            
            # Esperar a que se libere la unidad
            print(f"[DEBUG] Esperando a que se libere la unidad...")
            time.sleep(2.5)
            
            # PASO 3: Verificar que se desmontó
            vol_result = subprocess.run(
                ['cmd', '/c', 'vol', drive_path],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5
            )
            
            if vol_result.returncode != 0:
                print(f"[DEBUG] Unidad {drive_letter}: desmontada exitosamente")
                msg = tr('drive_unmount_success', f"Unidad {drive_letter}: desmontada exitosamente")
                return True, msg.format(drive_letter) if '{}' in msg else msg
            else:
                print(f"[DEBUG] La unidad todavia existe despues de matar el proceso, intentando desmontaje forzado")
                forced, forced_msg = DriveDetector._force_dismount_letter(drive_letter)
                if forced:
                    msg = tr('drive_unmount_success', f"Unidad {drive_letter}: desmontada exitosamente")
                    return True, msg.format(drive_letter) if '{}' in msg else msg
                msg = tr('drive_unmount_incomplete', f"No se pudo desmontar completamente la unidad {drive_letter}:\nEl proceso fue terminado pero la unidad aún responde.\nIntenta cerrar archivos abiertos y usa 'Desmontar Todas'.")
                return False, msg.format(drive_letter) if '{}' in msg else msg
                
        except Exception as e:
            print(f"[DEBUG] Excepcion: {str(e)}")
            import traceback
            traceback.print_exc()
            msg = tr('drive_unmount_error', f"Error al desmontar: {str(e)}")
            return False, msg.format(str(e)) if '{}' in msg else msg
    
    @staticmethod
    def unmount_all_drives(translator=None) -> Tuple[bool, str]:
        """
        Desmonta todas las unidades montadas por rclone
        
        Args:
            translator: Objeto de traducciones opcional (con método get())
        
        Returns:
            Tuple (success: bool, message: str)
        """
        def tr(key, fallback):
            if translator and hasattr(translator, 'get'):
                return translator.get(key, fallback)
            return fallback
        
        try:
            result = subprocess.run(
                ['taskkill', '/F', '/IM', 'rclone.exe'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            letters = []
            for letter in 'VWXYZ':
                vol_check = subprocess.run(
                    ['cmd', '/c', 'vol', f'{letter}:'],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                if vol_check.returncode == 0:
                    forced, _ = DriveDetector._force_dismount_letter(letter)
                    if forced:
                        letters.append(letter)

            if result.returncode == 0 or letters:
                msg = tr('drive_unmount_all_success', "Todas las unidades desmontadas exitosamente")
                if letters:
                    msg += f" (Forzado: {', '.join(letters)})"
                return True, msg
            else:
                return True, tr('drive_unmount_all_none', "No hay unidades montadas")
                
        except Exception as e:
            msg = tr('drive_unmount_all_error', f"Error al desmontar unidades: {str(e)}")
            return False, msg.format(str(e)) if '{}' in msg else msg
    
    @staticmethod
    def get_drive_info(drive_letter: str) -> Dict[str, str]:
        """
        Obtiene información detallada de una unidad
        
        Args:
            drive_letter: Letra de la unidad
            
        Returns:
            Dict con información de la unidad
        """
        try:
            result = subprocess.run(
                ['cmd', '/c', 'vol', f'{drive_letter}:'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                label = "Unknown"
                serial = "Unknown"
                
                for line in result.stdout.split('\n'):
                    if 'Volume in drive' in line:
                        match = re.search(r'is (.+)', line)
                        if match:
                            label = match.group(1).strip()
                    elif 'Volume Serial Number' in line:
                        match = re.search(r'is (.+)', line)
                        if match:
                            serial = match.group(1).strip()
                
                return {
                    'letter': drive_letter,
                    'label': label,
                    'serial': serial,
                    'mounted': True
                }
        except Exception:
            pass
        
        return {
            'letter': drive_letter,
            'label': 'Not Mounted',
            'serial': 'N/A',
            'mounted': False
        }

    @staticmethod
    def _force_dismount_letter(drive_letter: str) -> Tuple[bool, str]:
        """Intentar desmontar una unidad incluso sin proceso activo."""
        drive_path = f"{drive_letter}:"
        try:
            subprocess.run(
                ['mountvol', drive_path, '/D'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            time.sleep(1.0)
        except Exception as exc:
            print(f"[DEBUG] mountvol fallo para {drive_letter}: {exc}")

        vol_check = subprocess.run(
            ['cmd', '/c', 'vol', drive_path],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if vol_check.returncode != 0:
            print(f"[DEBUG] Desmontaje forzado exitoso para {drive_letter}")
            return True, f"Unidad {drive_letter}: desmontada forzadamente"

        # Intento adicional con PowerShell para liberar WinFsp si sigue montada
        try:
            ps_cmd = f"Try {{ $null = [System.IO.Directory]::Delete('{drive_path}\\\\') }} Catch {{}}"
            subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_cmd],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            time.sleep(0.5)
        except Exception:
            pass

        vol_check2 = subprocess.run(
            ['cmd', '/c', 'vol', drive_path],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if vol_check2.returncode != 0:
            print(f"[DEBUG] Desmontaje forzado con PowerShell exitoso para {drive_letter}")
            return True, f"Unidad {drive_letter}: desmontada forzadamente"

        return False, f"No fue posible desmontar {drive_letter} con desmontaje forzado"
