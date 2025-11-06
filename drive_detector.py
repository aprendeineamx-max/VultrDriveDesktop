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
        Desmonta una unidad específica
        
        Args:
            drive_letter: Letra de la unidad (ej: 'V')
            
        Returns:
            Tuple (success: bool, message: str)
        """
        try:
            # Primero intentar desmontar específicamente esta unidad usando net use
            drive_path = f"{drive_letter}:"
            
            # Intentar con net use delete
            result = subprocess.run(
                ['net', 'use', drive_path, '/delete', '/yes'],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode == 0:
                return True, f"Unidad {drive_letter}: desmontada exitosamente"
            
            # Si net use no funcionó, intentar matar el proceso específico de esa unidad
            # Buscar el comando de rclone que contiene esta letra de unidad
            try:
                wmic_result = subprocess.run(
                    ['wmic', 'process', 'where', 'name="rclone.exe"', 'get', 'processid,commandline', '/format:csv'],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                if wmic_result.returncode == 0:
                    for line in wmic_result.stdout.split('\n'):
                        if f'{drive_letter}:' in line or f'--drive-letter={drive_letter}' in line:
                            # Extraer el PID
                            parts = line.split(',')
                            if len(parts) >= 3:
                                pid = parts[2].strip()
                                if pid.isdigit():
                                    # Matar este proceso específico
                                    kill_result = subprocess.run(
                                        ['taskkill', '/F', '/PID', pid],
                                        capture_output=True,
                                        text=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW
                                    )
                                    
                                    if kill_result.returncode == 0:
                                        return True, f"Unidad {drive_letter}: desmontada exitosamente (proceso {pid} terminado)"
            except Exception:
                pass
            
            # Si nada funcionó, dar mensaje de que no se pudo desmontar
            return False, f"No se pudo desmontar la unidad {drive_letter}:\nIntenta cerrar todos los archivos abiertos desde esta unidad."
                
        except Exception as e:
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
