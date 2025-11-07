"""
Drive Detector - Detecta unidades montadas por rclone
"""
import subprocess
import re
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
                            mounted_drives.append({
                                'letter': letter,
                                'path': f'{letter}:',
                                'label': label,
                                'process_ids': ','.join(rclone_processes) if rclone_processes else 'N/A',
                                'has_process': len(rclone_processes) > 0
                            })
                except Exception:
                    continue
        
        except Exception as e:
            print(f"Error detectando unidades: {e}")
        
        return mounted_drives
    
    @staticmethod
    def unmount_drive(drive_letter: str) -> Tuple[bool, str]:
        """
        Desmonta SOLO una unidad específica
        
        Args:
            drive_letter: Letra de la unidad (ej: 'V')
            
        Returns:
            Tuple (success: bool, message: str)
        """
        try:
            import time
            drive_path = f"{drive_letter}:"
            
            print(f"[DEBUG] Iniciando desmontaje de {drive_letter}:")
            
            # ESTRATEGIA SIMPLIFICADA: 
            # 1. Buscar PIDs de rclone que contengan esta letra en su comando
            # 2. Matar SOLO esos PIDs
            # 3. Verificar que se desmontó
            
            # PASO 1: Usar WMIC para encontrar procesos rclone con esta letra
            print(f"[DEBUG] Buscando PIDs de rclone para {drive_letter}:")
            
            # Comando WMIC simplificado
            wmic_cmd = f'wmic process where "name=\'rclone.exe\'" get ProcessId,CommandLine /format:list'
            
            result = subprocess.run(
                ['cmd', '/c', wmic_cmd],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15
            )
            
            print(f"[DEBUG] WMIC resultado exitoso")
            
            # Buscar PIDs que contengan la letra de unidad
            pids = []
            current_pid = None
            current_cmdline = None
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                
                if line.startswith('CommandLine='):
                    current_cmdline = line.split('=', 1)[1] if '=' in line else ''
                elif line.startswith('ProcessId='):
                    pid_str = line.split('=', 1)[1].strip() if '=' in line else ''
                    if pid_str and pid_str.isdigit():
                        current_pid = pid_str
                
                # Si tenemos ambos, verificar si contiene nuestra letra
                if current_pid and current_cmdline:
                    # Buscar "V:" o " V:" en la línea de comandos
                    if f" {drive_letter}:" in current_cmdline or f"={drive_letter}:" in current_cmdline:
                        print(f"[DEBUG] Encontrado PID {current_pid} para {drive_letter}:")
                        pids.append(current_pid)
                    current_pid = None
                    current_cmdline = None
            
            if not pids:
                print(f"[DEBUG] No se encontraron PIDs especificos para {drive_letter}:")
                print(f"[DEBUG] Intentando metodo alternativo...")
                
                # Método alternativo: usar tasklist y buscar
                tasklist_result = subprocess.run(
                    ['tasklist', '/FI', 'IMAGENAME eq rclone.exe', '/FO', 'CSV', '/NH'],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=10
                )
                
                # Si hay procesos rclone pero no encontramos el específico,
                # como último recurso intentamos net use
                if 'rclone.exe' in tasklist_result.stdout:
                    print(f"[DEBUG] Hay procesos rclone corriendo, intentando net use...")
                    
                    # Intentar forzar desmontaje con net use
                    result = subprocess.run(
                        ['net', 'use', drive_path, '/delete', '/yes'],
                        capture_output=True,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=10
                    )
                    time.sleep(1.5)
                    
                    # Verificar si se desmontó
                    vol_result = subprocess.run(
                        ['cmd', '/c', 'vol', drive_path],
                        capture_output=True,
                        text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=5
                    )
                    
                    if vol_result.returncode != 0:
                        print(f"[DEBUG] Desmontado con net use")
                        return True, f"Unidad {drive_letter}: desmontada exitosamente"
                
                # Si nada funcionó
                return False, f"No se pudo desmontar la unidad {drive_letter}.\nIntenta cerrar todos los archivos abiertos desde esta unidad."
            
            # PASO 2: Matar SOLO los PIDs específicos
            print(f"[DEBUG] Matando {len(pids)} proceso(s): {', '.join(pids)}")
            
            for pid in pids:
                print(f"[DEBUG] Ejecutando taskkill /F /PID {pid}")
                result = subprocess.run(
                    ['taskkill', '/F', '/PID', pid],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5
                )
                print(f"[DEBUG] Taskkill resultado: {result.returncode}")
            
            # Esperar a que se libere
            time.sleep(2.0)
            
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
                return True, f"Unidad {drive_letter}: desmontada exitosamente"
            else:
                print(f"[DEBUG] La unidad aun esta montada, intentando net use...")
                
                # Último intento con net use
                result = subprocess.run(
                    ['net', 'use', drive_path, '/delete', '/yes'],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=10
                )
                time.sleep(1.5)
                
                # Verificar de nuevo
                vol_result = subprocess.run(
                    ['cmd', '/c', 'vol', drive_path],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=5
                )
                
                if vol_result.returncode != 0:
                    return True, f"Unidad {drive_letter}: desmontada exitosamente"
                else:
                    return False, f"No se pudo desmontar la unidad {drive_letter}.\nIntenta cerrar todos los archivos abiertos desde esta unidad."
                
        except Exception as e:
            print(f"[DEBUG] Excepcion: {str(e)}")
            return False, f"Error al desmontar: {str(e)}"
    
    @staticmethod
    def unmount_all_drives() -> Tuple[bool, str]:
        """
        Desmonta todas las unidades montadas por rclone
        
        Returns:
            Tuple (success: bool, message: str)
        """
        try:
            result = subprocess.run(
                ['taskkill', '/F', '/IM', 'rclone.exe'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                return True, "Todas las unidades desmontadas exitosamente"
            else:
                # No hay procesos de rclone
                return True, "No hay unidades montadas"
                
        except Exception as e:
            return False, f"Error al desmontar unidades: {str(e)}"
    
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
