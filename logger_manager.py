"""
Sistema de Logging Robusto - VultrDrive Desktop
Mejora #47: Sistema completo de logging con niveles, rotación y persistencia
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from datetime import datetime
from enum import Enum

class LogLevel(Enum):
    """Niveles de logging"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LoggerManager:
    """
    Gestor centralizado de logging para VultrDrive Desktop
    
    Características:
    - Múltiples niveles de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - Rotación automática de logs
    - Logs en archivo y consola
    - Formato estructurado
    - Filtrado por nivel
    """
    
    def __init__(self, app_name="VultrDrive", log_dir=None, max_bytes=10*1024*1024, backup_count=5):
        """
        Inicializar el gestor de logging
        
        Args:
            app_name: Nombre de la aplicación
            log_dir: Directorio para logs (None = usar directorio por defecto)
            max_bytes: Tamaño máximo de archivo de log antes de rotar (10MB por defecto)
            backup_count: Número de archivos de backup a mantener (5 por defecto)
        """
        self.app_name = app_name
        self.log_dir = log_dir or self._get_default_log_dir()
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        
        # Crear directorio de logs si no existe
        os.makedirs(self.log_dir, exist_ok=True)
        
        # Configurar logger principal
        self.logger = logging.getLogger(app_name)
        self.logger.setLevel(logging.DEBUG)  # Capturar todos los niveles
        
        # Evitar duplicación de handlers
        if self.logger.handlers:
            return
        
        # Formato de logs
        self.file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        self.console_formatter = logging.Formatter(
            '%(levelname)-8s | %(message)s'
        )
        
        # Handler para archivo con rotación
        self._setup_file_handler()
        
        # Handler para consola
        self._setup_console_handler()
        
        # Logger inicializado
        self.logger.info(f"Logger inicializado. Logs en: {self.log_dir}")
    
    def _get_default_log_dir(self):
        """Obtener directorio por defecto para logs"""
        if getattr(sys, 'frozen', False):
            # Ejecutando desde ejecutable empaquetado
            base_path = os.path.dirname(sys.executable)
        else:
            # Ejecutando desde script Python
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        return os.path.join(base_path, "logs")
    
    def _setup_file_handler(self):
        """Configurar handler para archivo con rotación"""
        log_file = os.path.join(self.log_dir, f"{self.app_name}.log")
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # Todos los niveles en archivo
        file_handler.setFormatter(self.file_formatter)
        self.logger.addHandler(file_handler)
    
    def _setup_console_handler(self):
        """Configurar handler para consola"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)  # Solo INFO y superiores en consola
        console_handler.setFormatter(self.console_formatter)
        self.logger.addHandler(console_handler)
    
    def set_console_level(self, level: LogLevel):
        """Cambiar nivel de logging en consola"""
        for handler in self.logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.handlers.RotatingFileHandler):
                handler.setLevel(level.value)
    
    def set_file_level(self, level: LogLevel):
        """Cambiar nivel de logging en archivo"""
        for handler in self.logger.handlers:
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                handler.setLevel(level.value)
    
    def get_logger(self, name=None):
        """
        Obtener un logger específico
        
        Args:
            name: Nombre del logger (None = logger principal)
            
        Returns:
            Logger configurado
        """
        if name:
            return logging.getLogger(f"{self.app_name}.{name}")
        return self.logger
    
    def debug(self, message, *args, **kwargs):
        """Log nivel DEBUG"""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message, *args, **kwargs):
        """Log nivel INFO"""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message, *args, **kwargs):
        """Log nivel WARNING"""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message, *args, **kwargs):
        """Log nivel ERROR"""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message, *args, **kwargs):
        """Log nivel CRITICAL"""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message, *args, **kwargs):
        """Log excepción con traceback"""
        self.logger.exception(message, *args, **kwargs)
    
    def get_log_files(self):
        """Obtener lista de archivos de log"""
        log_files = []
        base_log = os.path.join(self.log_dir, f"{self.app_name}.log")
        
        if os.path.exists(base_log):
            log_files.append(base_log)
        
        # Agregar archivos rotados
        for i in range(1, self.backup_count + 1):
            rotated_log = f"{base_log}.{i}"
            if os.path.exists(rotated_log):
                log_files.append(rotated_log)
        
        return log_files
    
    def clear_old_logs(self, days=30):
        """
        Limpiar logs más antiguos que X días
        
        Args:
            days: Días de antigüedad para eliminar
        """
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        
        deleted_count = 0
        for log_file in self.get_log_files():
            try:
                file_time = datetime.fromtimestamp(os.path.getmtime(log_file))
                if file_time < cutoff_date:
                    os.remove(log_file)
                    deleted_count += 1
                    self.logger.info(f"Log antiguo eliminado: {log_file}")
            except Exception as e:
                self.logger.warning(f"No se pudo eliminar log {log_file}: {e}")
        
        if deleted_count > 0:
            self.logger.info(f"Se eliminaron {deleted_count} archivos de log antiguos")
        
        return deleted_count


# Singleton global
_logger_manager_instance = None

def get_logger_manager(app_name="VultrDrive", log_dir=None) -> LoggerManager:
    """
    Obtener instancia global del gestor de logging
    
    Args:
        app_name: Nombre de la aplicación
        log_dir: Directorio para logs
        
    Returns:
        LoggerManager instance
    """
    global _logger_manager_instance
    if _logger_manager_instance is None:
        _logger_manager_instance = LoggerManager(app_name, log_dir)
    return _logger_manager_instance

def get_logger(name=None):
    """
    Obtener logger específico (función de conveniencia)
    
    Args:
        name: Nombre del logger
        
    Returns:
        Logger instance
    """
    manager = get_logger_manager()
    return manager.get_logger(name)

