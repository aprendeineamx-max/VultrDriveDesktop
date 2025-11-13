"""
Task Scheduler - Sistema de programación de tareas
Permite programar operaciones como sincronizaciones, backups, etc.
"""

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from datetime import datetime, time as dt_time, timedelta
from typing import Callable, Optional, Dict, List
from pathlib import Path
import json
import sys


class ScheduledTask:
    """Representa una tarea programada"""
    
    _WEEKDAY_MAP = {
        # English
        'mon': 0, 'monday': 0,
        'tue': 1, 'tuesday': 1,
        'wed': 2, 'wednesday': 2,
        'thu': 3, 'thursday': 3,
        'fri': 4, 'friday': 4,
        'sat': 5, 'saturday': 5,
        'sun': 6, 'sunday': 6,
        # Spanish
        'lunes': 0,
        'martes': 1,
        'miercoles': 2, 'miércoles': 2,
        'jueves': 3,
        'viernes': 4,
        'sabado': 5, 'sábado': 5,
        'domingo': 6,
        # Portuguese
        'segunda': 0,
        'terça': 1, 'terca': 1,
        'quarta': 2,
        'quinta': 3,
        'sexta': 4,
        'sábado': 5, 'sabado': 5,
        # French
        'lundi': 0,
        'mardi': 1,
        'mercredi': 2,
        'jeudi': 3,
        'vendredi': 4,
        'samedi': 5,
        'dimanche': 6,
        # German
        'montag': 0,
        'dienstag': 1,
        'mittwoch': 2,
        'donnerstag': 3,
        'freitag': 4,
        'samstag': 5,
        'sonntag': 6,
    }

    def __init__(
        self,
        task_id: str,
        callback: Callable,
        schedule_type: str,
        schedule_value: str,
        enabled: bool = True,
        last_run: Optional[datetime] = None,
        callback_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        self.task_id = task_id
        self.callback = callback
        self.schedule_type = schedule_type  # 'interval', 'daily', 'weekly', 'once'
        self.schedule_value = schedule_value  # '5m', '14:30', 'monday 09:00', '2024-12-25 10:00'
        self.enabled = enabled
        self.last_run = last_run
        self.next_run: Optional[datetime] = None
        self.run_count = 0
        self.error_count = 0
        self.callback_id = callback_id
        self.metadata = metadata or {}
        self._calculate_next_run()
    
    def _calculate_next_run(self):
        """Calcular cuándo debe ejecutarse la próxima vez"""
        now = datetime.now()
        
        if self.schedule_type == 'interval':
            # schedule_value es como "5m", "1h", "30s"
            import re
            match = re.match(r'(\d+)([smhd])', self.schedule_value.lower())
            if match:
                value, unit = int(match.group(1)), match.group(2)
                from datetime import timedelta
                if unit == 's':
                    delta = timedelta(seconds=value)
                elif unit == 'm':
                    delta = timedelta(minutes=value)
                elif unit == 'h':
                    delta = timedelta(hours=value)
                elif unit == 'd':
                    delta = timedelta(days=value)
                else:
                    delta = timedelta(minutes=5)  # Default
                self.next_run = now + delta
        
        elif self.schedule_type == 'daily':
            # schedule_value es como "14:30"
            try:
                hour, minute = map(int, self.schedule_value.split(':'))
                next_time = dt_time(hour, minute)
                today = datetime.combine(now.date(), next_time)
                if today <= now:
                    from datetime import timedelta
                    today += timedelta(days=1)
                self.next_run = today
            except:
                self.next_run = None
        
        elif self.schedule_type == 'weekly':
            self.next_run = self._calculate_next_weekly_run(now)
        
        elif self.schedule_type == 'once':
            # schedule_value es como "2024-12-25 10:00"
            try:
                self.next_run = datetime.strptime(self.schedule_value, "%Y-%m-%d %H:%M")
                if self.next_run <= now:
                    self.next_run = None  # Ya pasó
            except:
                self.next_run = None
    
    def should_run(self) -> bool:
        """Verificar si la tarea debe ejecutarse ahora"""
        if not self.enabled or not self.next_run:
            return False
        return datetime.now() >= self.next_run
    
    def execute(self):
        """Ejecutar la tarea"""
        try:
            self.callback()
            self.last_run = datetime.now()
            self.run_count += 1
            self._calculate_next_run()
            return True
        except Exception as e:
            self.error_count += 1
            raise e

    def _calculate_next_weekly_run(self, reference: datetime) -> Optional[datetime]:
        """Calcular próxima ejecución para tareas semanales."""
        if not self.schedule_value:
            return None
        parts = self.schedule_value.split()
        if not parts:
            return None
        day_part = parts[0]
        time_part = parts[1] if len(parts) > 1 else "00:00"
        try:
            hour, minute = map(int, time_part.split(':'))
        except ValueError:
            return None
        raw_days = [segment.strip().lower() for segment in day_part.split(',') if segment.strip()]
        weekdays = [self._WEEKDAY_MAP[day] for day in raw_days if day in self._WEEKDAY_MAP]
        if not weekdays:
            return None
        for offset in range(0, 7):
            candidate = reference + timedelta(days=offset)
            if candidate.weekday() in weekdays:
                candidate_dt = datetime.combine(candidate.date(), dt_time(hour, minute))
                if candidate_dt <= reference:
                    continue
                return candidate_dt
        return None


class TaskScheduler(QObject):
    """Scheduler de tareas con soporte para múltiples tipos de programación"""
    
    task_executed = pyqtSignal(str, bool, str)  # task_id, success, message
    task_error = pyqtSignal(str, str)  # task_id, error_message
    
    def __init__(self, check_interval_seconds: int = 60, storage_path: Optional[str] = None):
        super().__init__()
        self.tasks: Dict[str, ScheduledTask] = {}
        self.check_interval = check_interval_seconds * 1000  # Convertir a ms
        self.timer = QTimer()
        self.timer.timeout.connect(self._check_and_execute)
        self.running = False
        self._callback_registry: Dict[str, Callable] = {}
        self._storage_path = Path(storage_path) if storage_path else self._default_storage_path()
        self._definitions: Dict[str, Dict] = self._load_definitions()
    
    def start(self):
        """Iniciar el scheduler"""
        if not self.running:
            self.running = True
            self.timer.start(self.check_interval)
    
    def stop(self):
        """Detener el scheduler"""
        if self.running:
            self.running = False
            self.timer.stop()
    
    def add_task(self, task_id: str, callback: Callable, schedule_type: str, 
                 schedule_value: str, enabled: bool = True, *, persist: bool = False,
                 callback_id: Optional[str] = None, metadata: Optional[Dict] = None) -> bool:
        """
        Agregar una tarea programada
        
        Args:
            task_id: Identificador único de la tarea
            callback: Función a ejecutar
            schedule_type: Tipo de programación ('interval', 'daily', 'weekly', 'once')
            schedule_value: Valor de la programación
            enabled: Si está habilitada
        
        Returns:
            True si se agregó correctamente
        """
        if task_id in self.tasks:
            return False
        
        task = ScheduledTask(
            task_id,
            callback,
            schedule_type,
            schedule_value,
            enabled,
            callback_id=callback_id,
            metadata=metadata,
        )
        self.tasks[task_id] = task
        if persist:
            if not callback_id:
                raise ValueError("callback_id es requerido cuando persist=True")
            self._definitions[task_id] = {
                'task_id': task_id,
                'schedule_type': schedule_type,
                'schedule_value': schedule_value,
                'enabled': enabled,
                'callback_id': callback_id,
                'metadata': metadata or {},
            }
            self._save_definitions()
        return True
    
    def remove_task(self, task_id: str) -> bool:
        """Eliminar una tarea"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            if task_id in self._definitions:
                del self._definitions[task_id]
                self._save_definitions()
            return True
        return False
    
    def enable_task(self, task_id: str, enabled: bool = True) -> bool:
        """Habilitar o deshabilitar una tarea"""
        if task_id in self.tasks:
            self.tasks[task_id].enabled = enabled
            if enabled:
                self.tasks[task_id]._calculate_next_run()
            if task_id in self._definitions:
                self._definitions[task_id]['enabled'] = enabled
                self._save_definitions()
            return True
        return False
    
    def get_task_info(self, task_id: str) -> Optional[Dict]:
        """Obtener información de una tarea"""
        if task_id not in self.tasks:
            return None
        
        task = self.tasks[task_id]
        return {
            'task_id': task.task_id,
            'schedule_type': task.schedule_type,
            'schedule_value': task.schedule_value,
            'enabled': task.enabled,
            'last_run': task.last_run.isoformat() if task.last_run else None,
            'next_run': task.next_run.isoformat() if task.next_run else None,
            'run_count': task.run_count,
            'error_count': task.error_count,
            'metadata': task.metadata,
            'callback_id': task.callback_id,
        }
    
    def list_tasks(self) -> List[Dict]:
        """Listar todas las tareas"""
        return [self.get_task_info(task_id) for task_id in self.tasks.keys()]

    def register_callback(self, callback_id: str, callback: Callable):
        """Registrar operaciones disponibles para tareas persistentes."""
        self._callback_registry[callback_id] = callback
        self.restore_persisted_tasks()

    def restore_persisted_tasks(self):
        """Crear tareas basadas en el almacenamiento persistente."""
        restored = 0
        for task_id, definition in list(self._definitions.items()):
            if task_id in self.tasks:
                continue
            callback = self._callback_registry.get(definition.get('callback_id'))
            if not callback:
                continue
            task = ScheduledTask(
                task_id,
                callback,
                definition['schedule_type'],
                definition['schedule_value'],
                definition.get('enabled', True),
                callback_id=definition.get('callback_id'),
                metadata=definition.get('metadata', {}),
            )
            self.tasks[task_id] = task
            restored += 1
        return restored
    
    def _check_and_execute(self):
        """Verificar y ejecutar tareas pendientes"""
        now = datetime.now()
        for task_id, task in list(self.tasks.items()):
            if task.should_run():
                try:
                    success = task.execute()
                    self.task_executed.emit(task_id, success, "Tarea ejecutada correctamente")
                except Exception as e:
                    error_msg = str(e)
                    self.task_error.emit(task_id, error_msg)
                    # Recalcular próxima ejecución incluso si falló
                    task._calculate_next_run()

    def _default_storage_path(self) -> Path:
        """Ubicación por defecto del archivo de persistencia."""
        if getattr(sys, 'frozen', False):
            base = Path(sys.executable).parent
        else:
            base = Path(__file__).resolve().parents[1]
        data_dir = base / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "scheduler_tasks.json"

    def _load_definitions(self) -> Dict[str, Dict]:
        if not self._storage_path.exists():
            return {}
        try:
            with self._storage_path.open('r', encoding='utf-8') as handler:
                payload = json.load(handler)
                return {item['task_id']: item for item in payload.get('tasks', [])}
        except Exception:
            return {}

    def _save_definitions(self):
        data = {'tasks': list(self._definitions.values())}
        with self._storage_path.open('w', encoding='utf-8') as handler:
            json.dump(data, handler, ensure_ascii=False, indent=2)

