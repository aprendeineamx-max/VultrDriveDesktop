from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QComboBox, 
                             QLabel, QFileDialog, QStatusBar, QHBoxLayout, QGroupBox, 
                             QMessageBox, QLineEdit, QTabWidget, QTextEdit, QProgressBar,
                             QMenu, QScrollArea, QSizePolicy, QToolButton, QSystemTrayIcon,
                             QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
                             QCheckBox, QStyle)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction
from typing import Optional, Tuple
from config_manager import ConfigManager
from s3_handler import S3Handler
from ui.settings_window import SettingsWindow
from rclone_manager import RcloneManager
from file_watcher import RealTimeSync
from drive_detector import DriveDetector
from startup_manager import StartupManager
from notification_manager import NotificationManager, NotificationType
from core.task_runner import TaskRunner
from multiple_mount_manager import MultipleMountManager
from ui.multi_mounts_widget import MultiMountsWidget
from storage_session_manager import StorageSessionManager
from functools import partial
import time

# ===== MEJORA Task5: Auditoría y Monitor =====
try:
    from core.audit_logger import get_audit_logger, AuditEventType
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    AuditEventType = None

try:
    from core.state_monitor import get_state_monitor, ComponentStatus
    STATE_MONITOR_AVAILABLE = True
except ImportError:
    STATE_MONITOR_AVAILABLE = False
    ComponentStatus = None

try:
    from core.task_scheduler import TaskScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    TaskScheduler = None

# ===== MEJORA #48: Manejo de Errores Mejorado =====
try:
    from error_handler import handle_error, get_error_handler
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False

# ===== MEJORA #47: Sistema de Logging =====
try:
    from logger_manager import get_logger
    logger = get_logger(__name__)
    LOGGING_AVAILABLE = True
except ImportError:
    LOGGING_AVAILABLE = False
    logger = None

import os

class UploadThread(QThread):
    finished = pyqtSignal(bool, dict)

    def __init__(self, s3_handler, bucket_name, file_path):
        super().__init__()
        self.s3_handler = s3_handler
        self.bucket_name = bucket_name
        self.file_path = file_path

    def run(self):
        try:
            success = self.s3_handler.upload_file(self.bucket_name, self.file_path)
            file_name = os.path.basename(self.file_path)
            if success:
                self.finished.emit(True, {"file": file_name})
            else:
                error_message = getattr(self.s3_handler, "last_error", "") or ""
                self.finished.emit(False, {"file": file_name, "error": error_message})
        except Exception as e:
            self.finished.emit(False, {"file": os.path.basename(self.file_path), "error": str(e)})


class BackupThread(QThread):
    progress = pyqtSignal(int, dict)
    finished = pyqtSignal(bool, dict)

    def __init__(self, s3_handler, bucket_name, folder_path):
        super().__init__()
        self.s3_handler = s3_handler
        self.bucket_name = bucket_name
        self.folder_path = folder_path

    def run(self):
        try:
            files = []
            for root, dirs, filenames in os.walk(self.folder_path):
                for filename in filenames:
                    files.append(os.path.join(root, filename))
            
            total = len(files)
            if total == 0:
                self.finished.emit(False, {"reason": "no_files"})
                return

            for index, file_path in enumerate(files, start=1):
                relative_path = os.path.relpath(file_path, self.folder_path)
                self.progress.emit(
                    int(((index - 1) * 100) / total),
                    {
                        "current": index,
                        "total": total,
                        "file": relative_path,
                    },
                )
                self.s3_handler.upload_file(self.bucket_name, file_path, relative_path)
            
            self.finished.emit(True, {"total": total})
        except Exception as e:
            self.finished.emit(False, {"reason": "exception", "detail": str(e)})


class MainWindow(QMainWindow):
    def __init__(self, theme_manager=None, translations=None, save_preferences_callback=None):
        super().__init__()

        # Store references to theme manager and translations
        self.theme_manager = theme_manager
        self.translations = translations
        self.save_preferences_callback = save_preferences_callback
        
        # Initialize UI
        self.setWindowTitle(self.tr("window_title"))
        self.setGeometry(100, 100, 900, 700)  # Ventana más grande y responsiva
        self.setMinimumSize(800, 600)  # Tamaño mínimo para evitar problemas de visualización

        self.config_manager = ConfigManager()
        self.s3_handler = None
        self.active_profile_type = 's3'
        self.rclone_manager = RcloneManager(self.config_manager)
        self.session_manager = StorageSessionManager(self.config_manager, self.rclone_manager, logger)
        self.profile_states = {}
        self.profile_refresh_spins = {}
        self.profile_auto_mount_checkboxes = {}
        self.profile_auto_mount_letters = {}
        self.profile_default_bucket_inputs = {}
        self.auto_mount_enabled = self.config_manager.get_global_auto_mount()
        self.multiple_mount_manager = None
        self.real_time_sync = None
        self.upload_thread = None
        self.backup_thread = None
        self.install_winfsp_callback = None
        self.tray_icon = None
        self._tray_menu = None
        self._tray_actions = {}
        self._is_in_tray = False
        self._force_quit = False
        self._tray_notified = False
        self._close_without_unmount = False  # Flag para cerrar sin desmontar
        self.task_runner = TaskRunner(self)
        self._refreshing_buckets = False
        self._current_bucket_handler = None
        self._manual_refresh_in_progress = False
        self._auto_refresh_in_progress = False
        self.mount_refresh_timer = QTimer(self)
        self.mount_refresh_timer.setInterval(60000)
        self.mount_refresh_timer.timeout.connect(self._auto_refresh_mount_if_needed)
        self.mount_refresh_timer.start()
        
        # ===== QUICK WINS: Inicializar gestores =====
        # Gestor de inicio automático
        self.startup_manager = StartupManager()
        
        # Gestor de notificaciones (se inicializará después del tray_icon)
        self.notification_manager = None
        
        # ===== Task5: Inicializar Auditoría, Monitor y Scheduler =====
        if AUDIT_AVAILABLE:
            self.audit_logger = get_audit_logger()
        else:
            self.audit_logger = None
        
        if STATE_MONITOR_AVAILABLE:
            self.state_monitor = get_state_monitor()
            # Registrar componentes principales
            self.state_monitor.register_component('main_window', ComponentStatus.INITIALIZING)
            self.state_monitor.register_component('s3_handler', ComponentStatus.UNKNOWN)
            self.state_monitor.register_component('rclone_manager', ComponentStatus.UNKNOWN)
            self.state_monitor.register_component('sync', ComponentStatus.STOPPED)
        else:
            self.state_monitor = None
        
        if SCHEDULER_AVAILABLE:
            self.task_scheduler = TaskScheduler(check_interval_seconds=60)
            self.task_scheduler.task_executed.connect(self._on_scheduled_task_executed)
            self.task_scheduler.task_error.connect(self._on_scheduled_task_error)
            self.task_scheduler.start()
        else:
            self.task_scheduler = None

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        # Add language and theme controls at the top
        self.setup_top_controls()

        # Create tabs
        self.tabs = QTabWidget()
        self.main_layout.addWidget(self.tabs)

        # Tab 0: Dashboard (NUEVO - Mejora #52)
        try:
            from dashboard_widget import DashboardWidget
            self.dashboard_tab = DashboardWidget(self)
            self.dashboard_tab.update_requested.connect(self.update_dashboard_stats)
            self.tabs.addTab(self.dashboard_tab, self.tr("dashboard_tab_title"))
        except ImportError:
            # Si no está disponible, continuar sin dashboard
            pass

        # Tab 1: Main Operations
        self.main_tab = QWidget()
        self.setup_main_tab()
        self.tabs.addTab(self.main_tab, self.tr("main_tab"))

        # Tab 2: Drive Mount
        self.mount_tab = QWidget()
        self.setup_mount_tab()
        self.tabs.addTab(self.mount_tab, self.tr("mount_tab"))

        # Tab 3: Real-Time Sync
        self.sync_tab = QWidget()
        self.setup_sync_tab()
        self.tabs.addTab(self.sync_tab, self.tr("sync_tab"))

        # Tab 4: Advanced
        self.advanced_tab = QWidget()
        self.setup_advanced_tab()
        self.tabs.addTab(self.advanced_tab, self.tr("advanced_tab"))

        # Status Bar
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage(self.tr("ready"))

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.main_layout.addWidget(self.progress_bar)

        # ===== MEJORA: Cargar perfil automáticamente al iniciar =====
        # Cargar el primer perfil disponible automáticamente
        if self.profile_selector.count() > 0:
            # Cargar perfil después de que la ventana se muestre (no bloquear inicio)
            QTimer.singleShot(500, lambda: self._auto_load_profile())
        else:
            self.statusBar().showMessage(self.tr("no_profiles_found"))

        self.refresh_profile_refresh_controls()
        QTimer.singleShot(1500, self._bootstrap_sessions)

        self.setup_tray_icon()
        self.update_background_button_text()
        
        # ===== MEJORA #52: Inicializar dashboard =====
        if hasattr(self, 'dashboard_tab'):
            QTimer.singleShot(1000, self.update_dashboard_stats)
        
        # ===== MEJORA #56: Atajos de Teclado =====
        try:
            from keyboard_shortcuts import KeyboardShortcuts
            self.keyboard_shortcuts = KeyboardShortcuts(self)
        except ImportError:
            pass

        self._bind_multiple_mount_manager()
        
        # ===== Task5: Marcar ventana principal como lista =====
        if self.state_monitor:
            QTimer.singleShot(1000, lambda: self.state_monitor.update_component_status(
                'main_window',
                ComponentStatus.READY
            ))

    def _bind_multiple_mount_manager(self):
        """Preparar conexiones con MultipleMountManager"""
        try:
            self.multiple_mount_manager = MultipleMountManager(self.rclone_manager)
            self.multi_mounts_widget = MultiMountsWidget(self.multiple_mount_manager, self.translations)
            self.multi_mounts_widget.request_new_mount.connect(self.show_mount_tab)
            if hasattr(self, "mounts_content_layout") and self.multi_mounts_widget.parent() is None:
                insert_index = max(0, self.mounts_content_layout.count() - 1)
                self.mounts_content_layout.insertWidget(insert_index, self.multi_mounts_widget)
        except Exception as exc:
            if LOGGING_AVAILABLE:
                logger.error("No se pudo inicializar MultipleMountManager: %s", exc, exc_info=True)
            self.multiple_mount_manager = None
            self.multi_mounts_widget = None
            return

        self.multiple_mount_manager.refresh_all_status()
        self._refresh_multi_mounts_widget(refresh_manager=False, defer=True)

    def _refresh_multi_mounts_widget(self, refresh_manager=True, defer=False):
        manager = getattr(self, "multiple_mount_manager", None)
        widget = getattr(self, "multi_mounts_widget", None)
        if refresh_manager and manager:
            manager.refresh_all_status()
        if widget:
            if defer:
                QTimer.singleShot(0, widget.refresh_table)
            else:
                widget.refresh_table()

    def _auto_load_profile(self):
        """Cargar perfil automáticamente al iniciar"""
        if self.profile_selector.count() > 0:
            profile_name = self.profile_selector.currentText()
            self.load_profile(profile_name)
            # Refrescar buckets automáticamente después de cargar perfil
            QTimer.singleShot(1000, self.refresh_buckets)
        
        # Verificar visibilidad del botón de cerrar sin desmontar al iniciar
        QTimer.singleShot(2000, self.update_close_without_unmount_button_visibility)

    def tr(self, key, *args):
        """Translate text using the translations system"""
        if self.translations:
            return self.translations.get(key, *args)
        return key

    def setup_top_controls(self):
        """Setup language and theme controls at the top"""
        top_layout = QHBoxLayout()
        
        # Language selector
        language_label = QLabel(self.tr("language"))
        self.language_button = QPushButton()
        self.language_button.setObjectName("languageButton")
        self.update_language_button_text()
        self.language_button.clicked.connect(self.show_language_menu)
        
        # Theme selector
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeButton")
        self.update_theme_button_text()
        self.theme_button.clicked.connect(self.toggle_theme)

        # Send to background button (system tray quick action)
        self.background_button = QToolButton()
        self.background_button.setObjectName("backgroundButton")
        self.background_button.setAutoRaise(True)
        self.background_button.clicked.connect(lambda: self.send_to_tray(show_message=True))
        self.background_button.setToolTip(self.tr("send_to_background_tooltip"))
        self.update_background_button_text()
        
        # ===== MEJORA: Botón para cerrar sin desmontar unidades =====
        self.close_without_unmount_button = QPushButton(self.tr("close_without_unmount"))
        self.close_without_unmount_button.setObjectName("closeWithoutUnmountButton")
        self.close_without_unmount_button.setToolTip(self.tr("close_without_unmount_tooltip"))
        self.close_without_unmount_button.clicked.connect(self.close_without_unmounting)
        self.close_without_unmount_button.hide()  # Ocultar inicialmente
        
        top_layout.addWidget(language_label)
        top_layout.addWidget(self.language_button)
        top_layout.addStretch()
        top_layout.addWidget(self.theme_button)
        top_layout.addWidget(self.background_button)
        top_layout.addWidget(self.close_without_unmount_button)
        
        self.main_layout.addLayout(top_layout)

    def setup_tray_icon(self):
        """Configura el icono en la bandeja del sistema con menú mejorado"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(icon, self)
        self._update_tray_tooltip()

        # ===== MENÚ CONTEXTUAL MEJORADO =====
        self._tray_menu = QMenu()
        self._tray_actions = {}

        # Acción: Mostrar ventana
        open_action = QAction(f"📂 {self.tr('tray_open')}", self)
        open_action.triggered.connect(self.restore_from_tray)
        self._tray_menu.addAction(open_action)
        self._tray_actions['open'] = open_action

        self._tray_menu.addSeparator()

        # Sección: Montar/Desmontar
        mount_action = QAction(f"➕ {self.tr('tray_mount_new_bucket')}", self)
        mount_action.triggered.connect(self.show_mount_tab)
        self._tray_menu.addAction(mount_action)
        self._tray_actions['mount'] = mount_action

        unmount_action = QAction(f"🗑 {self.tr('tray_unmount_all')}", self)
        unmount_action.triggered.connect(self.tray_unmount_all)
        self._tray_menu.addAction(unmount_action)
        self._tray_actions['unmount'] = unmount_action

        self._tray_menu.addSeparator()

        # Acción: Configuración
        settings_action = QAction(f"⚙️ {self.tr('tray_settings')}", self)
        settings_action.triggered.connect(self.open_settings)
        self._tray_menu.addAction(settings_action)
        self._tray_actions['settings'] = settings_action

        self._tray_menu.addSeparator()

        # Acción: Salir
        exit_action = QAction(f"❌ {self.tr('tray_exit')}", self)
        exit_action.triggered.connect(self.quit_application)
        self._tray_menu.addAction(exit_action)
        self._tray_actions['exit'] = exit_action

        self.tray_icon.setContextMenu(self._tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()
        
        # ===== INICIALIZAR GESTOR DE NOTIFICACIONES =====
        self.notification_manager = NotificationManager(self.tray_icon, self.translations)
        
        # Notificar inicio de aplicación
        QTimer.singleShot(1000, lambda: self.notification_manager.notify_app_started())
    
    def _update_tray_tooltip(self):
        """Actualizar tooltip del icono en bandeja"""
        try:
            from drive_detector import DriveDetector
            detected = DriveDetector.detect_mounted_drives()
            mounted_count = len(detected) if detected else 0
            tooltip = self.tr("tray_tooltip").format(mounted_count)
        except:
            tooltip = self.tr("app_name")
        
        if self.tray_icon:
            self.tray_icon.setToolTip(tooltip)
    
    def show_mount_tab(self):
        """Mostrar ventana y cambiar a pestaña de montaje"""
        self.restore_from_tray()
        if hasattr(self, 'tabs'):
            # Cambiar a pestaña "Montar Disco" (índice 1)
            self.tabs.setCurrentIndex(1)

    def update_language_button_text(self):
        """Update the language button text"""
        if self.translations:
            available_languages = self.translations.get_available_languages()
            current_lang = self.translations.current_language
            if current_lang in available_languages:
                self.language_button.setText(available_languages[current_lang])
            else:
                self.language_button.setText(self.tr("language"))

    def update_theme_button_text(self):
        """Update the theme button text"""
        if self.theme_manager:
            available_themes = self.theme_manager.get_available_themes()
            current_theme = self.theme_manager.current_theme
            if current_theme in available_themes:
                self.theme_button.setText(available_themes[current_theme])
            else:
                self.theme_button.setText(self.tr("theme"))

    def update_background_button_text(self):
        """Update the send-to-background button label"""
        if hasattr(self, 'background_button'):
            self.background_button.setText(self.tr("send_to_background"))
            self.background_button.setToolTip(self.tr("send_to_background_tooltip"))
        if hasattr(self, '_tray_actions') and self._tray_actions:
            if 'open' in self._tray_actions:
                self._tray_actions['open'].setText(f"📂 {self.tr('tray_open')}")
            if 'mount' in self._tray_actions:
                self._tray_actions['mount'].setText(f"➕ {self.tr('tray_mount_new_bucket')}")
            if 'unmount' in self._tray_actions:
                self._tray_actions['unmount'].setText(f"🗑 {self.tr('tray_unmount_all')}")
            if 'settings' in self._tray_actions:
                self._tray_actions['settings'].setText(f"⚙️ {self.tr('tray_settings')}")
            if 'exit' in self._tray_actions:
                self._tray_actions['exit'].setText(f"❌ {self.tr('tray_exit')}")
        if self.tray_icon:
            self.tray_icon.setToolTip(self.windowTitle())

    def send_to_tray(self, show_message=False):
        """Envía la aplicación a segundo plano"""
        if self.tray_icon:
            self.hide()
            self._is_in_tray = True
            if show_message:
                self.tray_icon.showMessage(
                    self.tr("background_running_title"),
                    self.tr("background_notification"),
                    QSystemTrayIcon.MessageIcon.Information,
                    4000
                )
        else:
            self.showMinimized()

    def restore_from_tray(self):
        """Restaurar la ventana principal desde la bandeja"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._is_in_tray = False

    def _on_tray_activated(self, reason):
        """Manejar la activación del icono en la bandeja"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Clic izquierdo: mostrar/ocultar ventana
            if self.isVisible():
                self.hide()
            else:
                self.restore_from_tray()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            # Doble clic: siempre mostrar
            self.restore_from_tray()

    def tray_unmount_all(self):
        """Permitir desmontar unidades desde la bandeja"""
        self.restore_from_tray()
        QTimer.singleShot(100, self.unmount_all_detected_drives)

    def quit_application(self):
        """Salir completamente de la aplicación"""
        reply = QMessageBox.question(
            self,
            self.tr("confirm_exit_title"),
            self.tr("confirm_exit_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Desmontar todas las unidades
            try:
                from drive_detector import DriveDetector
                DriveDetector.unmount_all_drives(self.translations)
            except:
                pass
            
            # Notificar
            if self.notification_manager:
                self.notification_manager.info(
                    self.tr("app_name"),
                    self.tr("closing_application")
                )
            
            # Marcar para salir realmente
            self._force_quit = True
            
            # Cerrar
            QApplication.quit()
    
    def close_without_unmounting(self):
        """Cerrar la aplicación sin desmontar las unidades montadas"""
        # Detener sincronización si está activa (pero no desmontar)
        if self.real_time_sync and self.real_time_sync.is_running():
            try:
                self.real_time_sync.stop()
                if LOGGING_AVAILABLE:
                    logger.info("Sincronización detenida antes de cerrar (sin desmontar)")
            except Exception as e:
                if LOGGING_AVAILABLE:
                    logger.warning(f"Error al detener sincronización: {e}")
        
        # Ocultar icono de bandeja si existe
        if self.tray_icon:
            try:
                self.tray_icon.hide()
            except:
                pass
        
        # Notificar
        if self.notification_manager:
            self.notification_manager.info(
                self.tr("app_name"),
                self.tr("close_without_unmount_message")
            )
        
        # Marcar para salir sin desmontar (evita el diálogo de "Drive Still Mounted")
        self._force_quit = True
        self._close_without_unmount = True  # Flag para evitar diálogo de desmontaje
        
        # Cerrar aplicación (las unidades permanecerán montadas)
        QApplication.quit()
    
    def exit_from_tray(self):
        """Cerrar la aplicación desde el menú de la bandeja (compatibilidad)"""
        self.quit_application()

    def _should_keep_in_background(self):
        """Determinar si la app debe quedarse en segundo plano"""
        sync_running = self.real_time_sync and self.real_time_sync.is_running()
        drive_mounted = False
        try:
            drive_mounted = self.rclone_manager.is_mounted()
        except Exception:
            drive_mounted = False
        return sync_running or drive_mounted

    def _execute_shutdown_tasks(self):
        """Realizar tareas de limpieza antes de salir"""
        # Si se cerró sin desmontar, no mostrar diálogos
        if self._close_without_unmount:
            # Solo detener sincronización silenciosamente
            if self.real_time_sync and self.real_time_sync.is_running():
                try:
                    self.real_time_sync.stop()
                except:
                    pass
            
            if self.tray_icon:
                self.tray_icon.hide()
            return
        
        # Comportamiento normal (con diálogos)
        if self.real_time_sync and self.real_time_sync.is_running():
            reply = QMessageBox.question(
                self,
                self.tr("sync_running_title"),
                self.tr("sync_running_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.real_time_sync.stop()

        if self.rclone_manager.is_mounted():
            reply = QMessageBox.question(
                self,
                self.tr("drive_still_mounted_title"),
                self.tr("drive_still_mounted_text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.rclone_manager.unmount_drive(self.drive_letter_input.currentText())

        if self.tray_icon:
            self.tray_icon.hide()

    def show_language_menu(self):
        """Show language selection menu"""
        if not self.translations:
            return
            
        menu = QMenu(self)
        available_languages = self.translations.get_available_languages()
        
        for lang_code, lang_name in available_languages.items():
            action = QAction(lang_name, self)
            action.setData(lang_code)
            action.triggered.connect(lambda checked, code=lang_code: self.change_language(code))
            
            # Mark current language
            if lang_code == self.translations.current_language:
                action.setCheckable(True)
                action.setChecked(True)
                
            menu.addAction(action)
        
        menu.exec(self.language_button.mapToGlobal(self.language_button.rect().bottomLeft()))

    def change_language(self, language_code):
        """Change the application language"""
        if self.translations and self.translations.set_language(language_code):
            # Save preference
            if self.save_preferences_callback:
                preferences = {
                    "language": language_code,
                    "theme": self.theme_manager.current_theme if self.theme_manager else "dark"
                }
                self.save_preferences_callback(preferences)
            
            # Show restart message
            QMessageBox.information(
                self, 
                self.tr("language_changed_title"), 
                self.tr("language_changed_message").format(
                    self.translations.get_available_languages()[language_code]
                )
            )
            
            # Update button text
            self.update_language_button_text()
            self.update_background_button_text()
            if getattr(self, "multi_mounts_widget", None):
                self.multi_mounts_widget.update_translations()

    def toggle_theme(self):
        """Toggle between dark and light theme"""
        if not self.theme_manager:
            return
            
        new_theme = "light" if self.theme_manager.current_theme == "dark" else "dark"
        
        if self.theme_manager.set_theme(new_theme):
            # Apply new theme
            if hasattr(self, 'parent') and hasattr(self.parent(), 'setStyleSheet'):
                self.parent().setStyleSheet(self.theme_manager.get_current_stylesheet())
            else:
                from PyQt6.QtWidgets import QApplication
                QApplication.instance().setStyleSheet(self.theme_manager.get_current_stylesheet())
            
            # Save preference
            if self.save_preferences_callback:
                preferences = {
                    "language": self.translations.current_language if self.translations else "en",
                    "theme": new_theme
                }
                self.save_preferences_callback(preferences)
            
            # Update button text
            self.update_theme_button_text()

    def setup_main_tab(self):
        # Crear un scroll area para toda la pestaña
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # Widget contenedor para el scroll
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        self.mounts_content_layout = layout

        # Profile selection group
        profile_group = QGroupBox(self.tr("profile_selection"))
        profile_layout = QHBoxLayout()
        self.profile_label = QLabel(self.tr("active_profile"))
        self.profile_selector = QComboBox()
        self.profile_selector.addItems(self.config_manager.list_profiles())
        self.profile_selector.currentTextChanged.connect(self.load_profile)
        profile_layout.addWidget(self.profile_label)
        profile_layout.addWidget(self.profile_selector, 1)
        profile_group.setLayout(profile_layout)
        layout.addWidget(profile_group)

        # Bucket selection group
        bucket_group = QGroupBox(self.tr("bucket_selection"))
        bucket_layout = QHBoxLayout()
        self.bucket_label = QLabel(self.tr("select_bucket"))
        self.bucket_selector = QComboBox()
        self.refresh_buckets_btn = QPushButton(self.tr("refresh"))
        self.refresh_buckets_btn.clicked.connect(lambda: self.refresh_buckets(force_remote=True))
        bucket_layout.addWidget(self.bucket_label)
        bucket_layout.addWidget(self.bucket_selector, 1)
        bucket_layout.addWidget(self.refresh_buckets_btn)
        bucket_group.setLayout(bucket_layout)
        layout.addWidget(bucket_group)

        # Main action buttons
        actions_group = QGroupBox(self.tr("actions"))
        actions_layout = QVBoxLayout()
        
        buttons_layout = QHBoxLayout()
        self.upload_button = QPushButton(self.tr("upload_file"))
        self.upload_button.clicked.connect(self.upload_file)
        self.backup_button = QPushButton(self.tr("backup_folder"))
        self.backup_button.clicked.connect(self.full_backup)
        buttons_layout.addWidget(self.upload_button)
        buttons_layout.addWidget(self.backup_button)
        
        actions_layout.addLayout(buttons_layout)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        # Auto refresh / session overview
        session_group = QGroupBox(self.tr("session_auto_refresh_group"))
        session_layout = QVBoxLayout()

        session_info = QLabel(self.tr("session_auto_refresh_help"))
        session_info.setWordWrap(True)
        session_info.setStyleSheet("color: #888; font-size: 10pt;")
        session_layout.addWidget(session_info)

        global_interval_layout = QHBoxLayout()
        global_interval_layout.addWidget(QLabel(self.tr("session_global_interval_label")))
        self.global_refresh_spin = QSpinBox()
        self.global_refresh_spin.setRange(1, 365)
        self.global_refresh_spin.setValue(self.config_manager.get_global_refresh_interval())
        self.global_refresh_spin.valueChanged.connect(self.on_global_refresh_changed)
        global_interval_layout.addWidget(self.global_refresh_spin)
        global_interval_layout.addStretch()
        session_layout.addLayout(global_interval_layout)

        self.global_auto_mount_checkbox = QCheckBox(self.tr("session_auto_mount_global"))
        self.global_auto_mount_checkbox.setChecked(self.config_manager.get_global_auto_mount())
        self.global_auto_mount_checkbox.stateChanged.connect(self.on_global_auto_mount_changed)
        session_layout.addWidget(self.global_auto_mount_checkbox)

        self.profile_refresh_container = QWidget()
        self.profile_refresh_layout = QVBoxLayout(self.profile_refresh_container)
        self.profile_refresh_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_refresh_layout.setSpacing(6)
        session_layout.addWidget(self.profile_refresh_container)

        self.profile_status_table = QTableWidget(0, 7)
        self.profile_status_table.setHorizontalHeaderLabels([
            self.tr("session_table_profile"),
            self.tr("session_table_type"),
            self.tr("session_table_status"),
            self.tr("session_table_days"),
            self.tr("session_table_next_refresh"),
            self.tr("session_table_mount"),
            self.tr("session_table_error"),
        ])
        self.profile_status_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.profile_status_table.verticalHeader().setVisible(False)
        self.profile_status_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.profile_status_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        session_layout.addWidget(self.profile_status_table)

        session_group.setLayout(session_layout)
        layout.addWidget(session_group)

        # Settings button
        settings_layout = QHBoxLayout()
        self.settings_button = QPushButton(self.tr("manage_profiles"))
        self.settings_button.clicked.connect(self.open_settings)
        settings_layout.addStretch()
        settings_layout.addWidget(self.settings_button)
        layout.addLayout(settings_layout)

        layout.addStretch()
        
        # Configurar el scroll area
        scroll.setWidget(container)
        
        # Agregar el scroll area al tab
        tab_layout = QVBoxLayout(self.main_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    def on_global_refresh_changed(self, value: int):
        self.config_manager.set_global_refresh_interval(value)
        self.refresh_profile_refresh_controls()
        self._bootstrap_sessions()

    def on_global_auto_mount_changed(self, state):
        enabled = state == Qt.CheckState.Checked
        self.config_manager.set_global_auto_mount(enabled)
        self.auto_mount_enabled = enabled
        self._bootstrap_sessions()

    def _on_profile_refresh_changed(self, profile_name: str, value: int):
        self.config_manager.set_profile_refresh_interval(profile_name, value)
        self._bootstrap_sessions()

    def on_profile_auto_mount_changed(self, profile_name: str, enabled: bool):
        self.config_manager.set_profile_auto_mount(profile_name, enabled)
        if self.config_manager.get_global_auto_mount():
            self._bootstrap_sessions()

    def on_profile_letter_changed(self, profile_name: str, letter: str):
        if not letter:
            return
        self.config_manager.set_profile_auto_mount_letter(profile_name, letter)
        if self.config_manager.get_global_auto_mount():
            self._bootstrap_sessions()

    def on_profile_bucket_changed(self, profile_name: str, bucket: str):
        self.config_manager.set_profile_default_bucket(profile_name, bucket.strip())
        if self.config_manager.get_global_auto_mount():
            self._bootstrap_sessions()

    def refresh_profile_refresh_controls(self):
        if not hasattr(self, 'profile_refresh_layout'):
            return

        while self.profile_refresh_layout.count():
            item = self.profile_refresh_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.profile_refresh_spins = {}
        self.profile_auto_mount_checkboxes = {}
        self.profile_auto_mount_letters = {}
        self.profile_default_bucket_inputs = {}

        for profile_name in self.config_manager.list_profiles():
            profile_data = self.config_manager.get_config(profile_name) or {}
            profile_type = profile_data.get('type', 's3').lower()

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(self.tr("session_profile_interval_label").format(profile_name))
            row_layout.addWidget(label)

            spin = QSpinBox()
            spin.setRange(1, 365)
            spin.setValue(self.config_manager.get_profile_refresh_interval(profile_name))
            spin.valueChanged.connect(lambda value, name=profile_name: self._on_profile_refresh_changed(name, value))
            row_layout.addWidget(spin)
            self.profile_refresh_spins[profile_name] = spin

            auto_checkbox = QCheckBox(self.tr("session_profile_auto_mount_label"))
            auto_checkbox.setChecked(profile_data.get('auto_mount', True))
            auto_checkbox.stateChanged.connect(
                lambda state, name=profile_name: self.on_profile_auto_mount_changed(
                    name, state == Qt.CheckState.Checked
                )
            )
            row_layout.addWidget(auto_checkbox)
            self.profile_auto_mount_checkboxes[profile_name] = auto_checkbox

            letter_label = QLabel(self.tr("session_profile_letter_label"))
            row_layout.addWidget(letter_label)

            letter_combo = QComboBox()
            letters = [chr(code) for code in range(ord('V'), ord('Z') + 1)]
            for letter in letters:
                letter_combo.addItem(letter)
            current_letter = (profile_data.get('auto_mount_letter') or letters[0]).upper()
            if current_letter not in letters:
                letter_combo.addItem(current_letter)
            letter_combo.setCurrentText(current_letter)
            letter_combo.currentTextChanged.connect(
                lambda value, name=profile_name: self.on_profile_letter_changed(name, value)
            )
            row_layout.addWidget(letter_combo)
            self.profile_auto_mount_letters[profile_name] = letter_combo

            if profile_type == 's3':
                bucket_label = QLabel(self.tr("session_profile_bucket_label"))
                row_layout.addWidget(bucket_label)
                bucket_input = QLineEdit(profile_data.get('default_bucket', ''))
                bucket_input.setPlaceholderText(self.tr("session_profile_bucket_placeholder"))
                bucket_input.editingFinished.connect(
                    lambda name=profile_name, widget=bucket_input: self.on_profile_bucket_changed(name, widget.text())
                )
                row_layout.addWidget(bucket_input, 1)
                self.profile_default_bucket_inputs[profile_name] = bucket_input
            else:
                bucket_label = QLabel(self.tr("session_profile_mega_root"))
                bucket_label.setStyleSheet("color: #888;")
                row_layout.addWidget(bucket_label, 1)
                self.profile_default_bucket_inputs[profile_name] = None

            row_layout.addStretch()
            self.profile_refresh_layout.addWidget(row_widget)

    def _bootstrap_sessions(self):
        if not hasattr(self, 'session_manager'):
            return

        auto_mount_enabled = self.config_manager.get_global_auto_mount()

        def execute():
            return self.session_manager.ensure_profiles_ready(auto_mount=auto_mount_enabled)

        def on_success(result):
            self.profile_states = result or {}
            self.update_profile_status_table()
            if hasattr(self, 'dashboard_tab'):
                QTimer.singleShot(10, self.update_dashboard_stats)

        self.statusBar().showMessage(self.tr("session_status_refreshing"))
        self.task_runner.run(
            execute,
            on_success=on_success,
            description="session_bootstrap",
        )

    def update_profile_status_table(self):
        if not hasattr(self, 'profile_status_table'):
            return

        states = self.session_manager.get_states()
        self.profile_status_table.setRowCount(len(states))
        for row_index, (profile, state) in enumerate(states.items()):
            self.profile_status_table.setItem(row_index, 0, QTableWidgetItem(profile))
            self.profile_status_table.setItem(row_index, 1, QTableWidgetItem(state.get('type', 'unknown').upper()))

            status_key = state.get('status', 'unknown')
            status_text = self.tr("session_status_ok") if status_key == 'ok' else self.tr("session_status_error")
            self.profile_status_table.setItem(row_index, 2, QTableWidgetItem(status_text))

            days_text = self._format_days_value(state.get('days_active'))
            self.profile_status_table.setItem(row_index, 3, QTableWidgetItem(days_text))

            next_refresh = self._format_datetime(state.get('next_refresh_ts'))
            self.profile_status_table.setItem(row_index, 4, QTableWidgetItem(next_refresh))

            mount_status = self._format_mount_status(state.get('mount_status'))
            self.profile_status_table.setItem(row_index, 5, QTableWidgetItem(mount_status))

            error_text = state.get('last_error') or self.tr("session_no_errors")
            self.profile_status_table.setItem(row_index, 6, QTableWidgetItem(error_text))

        self.profile_status_table.resizeRowsToContents()
        self.statusBar().showMessage(self.tr("session_status_ready"), 3000)

    def _format_days_value(self, value):
        if value is None:
            return self.tr("session_days_unknown")
        return self.tr("session_days_template").format(value)

    def _format_datetime(self, iso_value):
        if not iso_value:
            return self.tr("session_next_refresh_unknown")
        try:
            from datetime import datetime
            dt_value = datetime.fromisoformat(iso_value)
            return dt_value.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso_value

    def _format_mount_status(self, mount_state):
        if not mount_state:
            return self.tr("session_mount_unknown")
        status = mount_state.get('status')
        message = mount_state.get('message', '')
        if status == 'mounted':
            return self.tr("session_mount_ok").format(message)
        if status == 'error':
            return self.tr("session_mount_error").format(message)
        if status == 'skipped':
            return self.tr("session_mount_skipped").format(message)
        return message or self.tr("session_mount_unknown")

    def setup_mount_tab(self):
        # Crear un scroll area para toda la pestaña
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # Widget contenedor para el scroll
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)

        # Detector de discos montados (NUEVO)
        detector_group = QGroupBox("🔍 " + self.tr("mounted_drives_detector"))
        detector_group.setObjectName("detector_group")  # Nombre para encontrarlo después
        detector_group.setToolTip("ℹ️ " + self.tr("detector_tooltip"))  # Tooltip informativo
        detector_layout = QVBoxLayout()
        
        detector_info = QLabel(self.tr("detector_info"))
        detector_info.setWordWrap(True)
        detector_info.setStyleSheet("color: #888; font-size: 10pt; margin-bottom: 10px;")
        detector_layout.addWidget(detector_info)
        
        detector_buttons_layout = QHBoxLayout()
        self.detect_drives_btn = QPushButton("🔎 " + self.tr("detect_mounted_drives"))
        self.detect_drives_btn.clicked.connect(self.detect_mounted_drives)
        self.detect_drives_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 11pt;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        
        self.unmount_all_btn = QPushButton("🗑️ " + self.tr("unmount_all_drives"))
        self.unmount_all_btn.clicked.connect(self.unmount_all_detected_drives)
        self.unmount_all_btn.setEnabled(False)
        self.unmount_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 11pt;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        
        detector_buttons_layout.addWidget(self.detect_drives_btn)
        detector_buttons_layout.addWidget(self.unmount_all_btn)
        detector_layout.addLayout(detector_buttons_layout)
        
        # Lista de unidades detectadas
        self.drives_list = QTextEdit()
        self.drives_list.setReadOnly(True)
        self.drives_list.setMinimumHeight(70)  # Muy pequeño, solo para el texto
        self.drives_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)  # Solo crece verticalmente si hay contenido
        self.drives_list.setPlainText(self.tr("no_drives_detected"))
        self.drives_list.setStyleSheet("""
            QTextEdit {
                background-color: #2c3e50;
                color: #ecf0f1;
                border: 2px solid #34495e;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Consolas', monospace;
                font-size: 10pt;
            }
        """)
        detector_layout.addWidget(self.drives_list)
        
        # Contenedor para botones individuales de desmontaje (se llena dinámicamente)
        self.individual_buttons_container = QWidget()
        self.individual_buttons_container_layout = QVBoxLayout(self.individual_buttons_container)
        self.individual_buttons_container_layout.setContentsMargins(0, 10, 0, 0)
        self.individual_buttons_container.hide()  # Oculto hasta que se detecten unidades
        detector_layout.addWidget(self.individual_buttons_container)
        
        detector_group.setLayout(detector_layout)
        layout.addWidget(detector_group)

        # Mount configuration
        mount_group = QGroupBox(self.tr("mount_configuration"))
        mount_group.setToolTip("ℹ️ " + self.tr("mount_config_tooltip"))  # Tooltip informativo
        mount_layout = QVBoxLayout()

        drive_letter_layout = QHBoxLayout()
        drive_letter_layout.addWidget(QLabel(self.tr("drive_letter")))
        self.drive_letter_input = QComboBox()
        available_drives = [chr(i) for i in range(ord('V'), ord('Z')+1)]
        self.drive_letter_input.addItems(available_drives)
        # ✅ CONECTAR: Cuando cambia la letra, refrescar si está montada
        self.drive_letter_input.currentTextChanged.connect(self.update_unmount_button_state)
        drive_letter_layout.addWidget(self.drive_letter_input)
        drive_letter_layout.addStretch()
        mount_layout.addLayout(drive_letter_layout)

        mount_group.setLayout(mount_layout)
        layout.addWidget(mount_group)

        # Mount actions
        actions_group = QGroupBox(self.tr("drive_actions"))
        actions_group.setToolTip("ℹ️ " + self.tr("mount_actions_tooltip"))  # Tooltip informativo
        actions_layout = QVBoxLayout()

        self.mount_status_label = QLabel(self.tr("status_not_mounted"))
        actions_layout.addWidget(self.mount_status_label)

        buttons_layout = QHBoxLayout()
        self.mount_button = QPushButton(self.tr("mount_drive"))
        self.mount_button.clicked.connect(self.mount_drive)

        self.open_drive_button = QPushButton(self.tr("open_drive"))
        self.open_drive_button.setEnabled(False)
        self.open_drive_button.setToolTip(self.tr("open_drive_tooltip"))
        self.open_drive_button.clicked.connect(self.open_drive)
        self.open_drive_button.setStyleSheet("""
            QPushButton {
                background-color: #2980b9;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 11pt;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #1f6391;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)

        self.unmount_button = QPushButton(self.tr("unmount_drive"))
        self.unmount_button.clicked.connect(self.unmount_drive)
        self.unmount_button.setEnabled(False)

        self.refresh_drive_button = QPushButton(self.tr("refresh_drive"))
        self.refresh_drive_button.setEnabled(False)
        self.refresh_drive_button.clicked.connect(self.manual_refresh_mount)
        self.refresh_drive_button.setStyleSheet("""
            QPushButton {
                background-color: #ffc107;
                color: #222;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
            }
        """)

        buttons_layout.addWidget(self.mount_button)
        buttons_layout.addWidget(self.open_drive_button)
        buttons_layout.addWidget(self.unmount_button)
        buttons_layout.addWidget(self.refresh_drive_button)

        actions_layout.addLayout(buttons_layout)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        # Info text
        info_group = QGroupBox(self.tr("information"))
        info_layout = QVBoxLayout()
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMinimumHeight(80)
        info_text.setMaximumHeight(160)
        info_text.setPlainText(self.tr("mount_info").replace('\\n', '\n'))
        info_layout.addWidget(info_text)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()
        
        # Configurar el scroll area
        scroll.setWidget(container)
        
        # Agregar el scroll area al tab
        tab_layout = QVBoxLayout(self.mount_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

        mount_layout_container = QVBoxLayout(self.mount_tab)
        mount_layout_container.setContentsMargins(0, 0, 0, 0)
        mount_layout_container.addLayout(detector_layout)
        mount_layout_container.addWidget(mount_group)

        if hasattr(self, 'multi_mounts_widget') and self.multi_mounts_widget:
            mount_layout_container.addWidget(self.multi_mounts_widget)

    def setup_sync_tab(self):
        # Crear un scroll area para toda la pestaña
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # Widget contenedor para el scroll
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)

        # Folder selection
        folder_group = QGroupBox(self.tr("folder_to_monitor"))
        folder_group.setToolTip("ℹ️ " + self.tr("folder_monitor_tooltip"))  # Tooltip informativo
        folder_layout = QVBoxLayout()

        folder_select_layout = QHBoxLayout()
        self.sync_folder_label = QLabel(self.tr("no_folder_selected"))
        self.sync_folder_label.setWordWrap(True)
        self.sync_folder_btn = QPushButton(self.tr("select_folder"))
        self.sync_folder_btn.clicked.connect(self.select_sync_folder)
        folder_select_layout.addWidget(self.sync_folder_label, 1)
        folder_select_layout.addWidget(self.sync_folder_btn)
        folder_layout.addLayout(folder_select_layout)

        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)

        # Sync status and controls
        sync_group = QGroupBox(self.tr("sync_control"))
        sync_group.setToolTip("ℹ️ " + self.tr("sync_control_tooltip"))  # Tooltip informativo
        sync_layout = QVBoxLayout()

        self.sync_status_label = QLabel(self.tr("status_stopped"))
        sync_layout.addWidget(self.sync_status_label)

        buttons_layout = QHBoxLayout()
        self.start_sync_btn = QPushButton(self.tr("start_sync"))
        self.start_sync_btn.clicked.connect(self.start_real_time_sync)
        self.stop_sync_btn = QPushButton(self.tr("stop_sync"))
        self.stop_sync_btn.clicked.connect(self.stop_real_time_sync)
        self.stop_sync_btn.setEnabled(False)
        buttons_layout.addWidget(self.start_sync_btn)
        buttons_layout.addWidget(self.stop_sync_btn)

        sync_layout.addLayout(buttons_layout)
        sync_group.setLayout(sync_layout)
        layout.addWidget(sync_group)

        # Activity log
        log_group = QGroupBox(self.tr("activity_log"))
        log_group.setToolTip("ℹ️ " + self.tr("activity_log_tooltip"))  # Tooltip informativo
        log_layout = QVBoxLayout()

        self.sync_log = QTextEdit()
        self.sync_log.setReadOnly(True)
        self.sync_log.setMaximumHeight(200)
        self.sync_log.setPlainText(self.tr("sync_not_started"))
        log_layout.addWidget(self.sync_log)

        clear_log_btn = QPushButton(self.tr("clear_log"))
        clear_log_btn.clicked.connect(lambda: self.sync_log.clear())
        log_layout.addWidget(clear_log_btn)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Info text
        info_group = QGroupBox(self.tr("information"))
        info_layout = QVBoxLayout()
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMinimumHeight(80)
        info_text.setMaximumHeight(160)
        info_text.setPlainText(self.tr("sync_info"))
        info_layout.addWidget(info_text)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()
        
        # Configurar el scroll area
        scroll.setWidget(container)
        
        # Agregar el scroll area al tab
        tab_layout = QVBoxLayout(self.sync_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    def select_sync_folder(self):
        """Select folder for real-time synchronization"""
        folder = QFileDialog.getExistingDirectory(self, self.tr("dialog_select_monitor_folder"))
        if folder:
            self.sync_folder_label.setText(folder)
            self.sync_folder_label.setProperty('folder_path', folder)

    def start_real_time_sync(self):
        """Start real-time synchronization"""
        if not self._require_s3_features():
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_bucket_first"))
            return

        folder = self.sync_folder_label.property('folder_path')
        if not folder:
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_folder_to_monitor"))
            return

        bucket_name = self.bucket_selector.currentText()
        
        self.real_time_sync = RealTimeSync(
            self.s3_handler,
            bucket_name,
            folder,
            self.sync_log_message
        )

        success, message = self.real_time_sync.start()

        if success:
            self.sync_status_label.setText(self.tr("status_monitoring_folder").format(folder))
            self.start_sync_btn.setEnabled(False)
            self.stop_sync_btn.setEnabled(True)
            self.sync_log_message(f"✓ {message}")
            QMessageBox.information(self, self.tr("success"), message)
        else:
            QMessageBox.critical(self, self.tr("error"), message)
            self.sync_log_message(f"✗ {message}")

    def stop_real_time_sync(self):
        """Stop real-time synchronization"""
        if self.real_time_sync:
            success, message = self.real_time_sync.stop()
            
            if success:
                self.sync_status_label.setText(self.tr('status_stopped'))
                self.start_sync_btn.setEnabled(True)
                self.stop_sync_btn.setEnabled(False)
                self.sync_log_message(f"✓ {message}")
            else:
                QMessageBox.critical(self, self.tr("error"), message)
                self.sync_log_message(f"✗ {message}")

    def sync_log_message(self, message):
        """Add message to sync log"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.sync_log.append(f"[{timestamp}] {message}")

    def setup_advanced_tab(self):
        # Crear un scroll area para toda la pestaña
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        # Widget contenedor para el scroll
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)

        # Warning label
        warning_label = QLabel(f"[!]️ {self.tr('advanced_warning')}")
        warning_label.setStyleSheet("font-weight: bold; color: #ff6b6b; font-size: 12pt;")
        layout.addWidget(warning_label)

        # Format bucket group
        format_group = QGroupBox(self.tr('bucket_management'))
        format_layout = QVBoxLayout()

        format_info = QLabel(self.tr('format_warning'))
       
        format_info.setWordWrap(True)
        format_layout.addWidget(format_info)

        self.format_button = QPushButton(f"🗑️ {self.tr('format_bucket')}")
        self.format_button.clicked.connect(self.format_bucket)
        self.format_button.setStyleSheet(
            "QPushButton { background-color: #c92a2a; }"
            "QPushButton:hover { background-color: #a51e1e; }"
        )
        format_layout.addWidget(self.format_button)

        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        layout.addStretch()
        
        # Configurar el scroll area
        scroll.setWidget(container)
        
        # Agregar el scroll area al tab
        tab_layout = QVBoxLayout(self.advanced_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    def refresh_buckets(self, force_remote=False):
        if self.active_profile_type != 's3':
            self.bucket_selector.clear()
            self.bucket_selector.addItem(self.tr("mega_virtual_bucket"))
            self.bucket_selector.setCurrentIndex(0)
            self.statusBar().showMessage(self.tr("mega_bucket_placeholder_status"))
            return

        if not self.s3_handler:
            self.statusBar().showMessage(self.tr("select_profile_first"))
            return

        if force_remote and self.s3_handler:
            self.s3_handler.clear_cache('list_buckets')

        if self._refreshing_buckets and self._current_bucket_handler is self.s3_handler and not force_remote:
            if LOGGING_AVAILABLE:
                logger.debug("Se ignoró refresh_buckets porque ya hay una operación en curso.")
            return

        self._refreshing_buckets = True
        self._current_bucket_handler = self.s3_handler
        self.bucket_selector.clear()
        self.statusBar().showMessage(self.tr("loading_buckets"))

        current_handler = self.s3_handler
        description = f"list_buckets[{getattr(current_handler, 'host_base', 'unknown')}]"

        def fetch():
            return current_handler.list_buckets(use_cache=not force_remote)

        def on_success(result):
            if current_handler is not self.s3_handler:
                if LOGGING_AVAILABLE:
                    logger.debug("Resultado de buckets descartado: handler cambió durante la operación.")
                return
            buckets, error_message = result
            self._handle_bucket_response(buckets, error_message, force_remote=force_remote)

        def on_error(exc):
            if current_handler is not self.s3_handler:
                return
            error_msg = f"Error inesperado al listar buckets: {exc}"
            if LOGGING_AVAILABLE:
                logger.error("Error listando buckets (%s): %s", description, str(exc), exc_info=True)
            self._handle_bucket_response([], error_msg, force_remote=force_remote)

        def on_finished():
            self._refreshing_buckets = False
            self._current_bucket_handler = None

        self.task_runner.run(
            fetch,
            on_success=on_success,
            on_error=on_error,
            on_finished=on_finished,
            description=description,
        )

    def _handle_bucket_response(self, buckets, error_message, force_remote=False):
        self.bucket_selector.clear()

        if error_message:
            short_error = error_message if len(error_message) <= 120 else f"{error_message[:117]}..."
            self.statusBar().showMessage(f"❌ {short_error}")

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle(self.tr("error_list_buckets_title"))
            msg.setText(self.tr("error_list_buckets_text"))
            msg.setDetailedText(error_message)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()

            if LOGGING_AVAILABLE:
                logger.error(f"Error al refrescar buckets: {error_message}")
        elif buckets:
            self.bucket_selector.addItems(buckets)
            self.statusBar().showMessage(self.tr("buckets_found").format(len(buckets)))
            if LOGGING_AVAILABLE:
                logger.info(f"Buckets cargados exitosamente: {len(buckets)}")
        else:
            self.statusBar().showMessage(self.tr("no_buckets_found"))
            if LOGGING_AVAILABLE:
                logger.info("No se encontraron buckets (puede ser normal si no hay buckets creados)")

        if isinstance(force_remote, bool) and force_remote:
            # Invalidar caché de tamaños para obtener datos frescos del bucket activo
            if self.s3_handler:
                self.s3_handler.clear_cache('get_bucket_size')

        # Actualizar dashboard con métricas posiblemente nuevas
        self.update_dashboard_stats(force_remote=force_remote)

    def load_profile(self, profile_name):
        if not profile_name:
            self.s3_handler = None
            self.active_profile_type = 's3'
            self.statusBar().showMessage(self.tr("no_profile_selected"))
            return
            
        config = self.config_manager.get_config(profile_name)
        if not config:
            error_msg = self.tr("profile_not_found").format(profile_name)
            self.statusBar().showMessage(f"[!] {error_msg}")
            if LOGGING_AVAILABLE:
                logger.error(error_msg)
            self.s3_handler = None
            self.active_profile_type = 's3'
            return
        
        try:
            self.active_profile_type = config.get('type', 's3').lower()
            if self.active_profile_type != 's3':
                self.s3_handler = None
                self.bucket_selector.clear()
                self.bucket_selector.addItem(self.tr("mega_virtual_bucket"))
                self.bucket_selector.setCurrentIndex(0)
                self.statusBar().showMessage(self.tr("mega_profile_loaded").format(profile_name))
                if self.state_monitor:
                    self.state_monitor.update_component_status(
                        's3_handler',
                        ComponentStatus.READY,
                        {'profile_name': profile_name, 'type': 'mega'}
                    )
                return
            
            access_key = config.get('access_key', '').strip()
            secret_key = config.get('secret_key', '').strip()
            host_base = config.get('host_base', '').strip()
            
            if not access_key or not secret_key:
                error_msg = self.tr("profile_credentials_empty")
                self.statusBar().showMessage(f"[!] {error_msg}")
                if LOGGING_AVAILABLE:
                    logger.error(f"Perfil '{profile_name}' tiene credenciales vacías")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, self.tr("warning"), error_msg)
                return
            
            if not host_base:
                error_msg = self.tr("profile_host_empty")
                self.statusBar().showMessage(f"[!] {error_msg}")
                if LOGGING_AVAILABLE:
                    logger.error(f"Perfil '{profile_name}' tiene host_base vacío")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, self.tr("warning"), error_msg)
                return
            
            self.s3_handler = S3Handler(access_key, secret_key, host_base)
            self.statusBar().showMessage(self.tr("profile_loaded").format(profile_name))
            
            if self.state_monitor:
                self.state_monitor.update_component_status(
                    's3_handler',
                    ComponentStatus.READY,
                    {'profile_name': profile_name}
                )
            
            if LOGGING_AVAILABLE:
                logger.info(f"Perfil '{profile_name}' cargado exitosamente")
            
            self.refresh_buckets()
            
        except ValueError as exc:
            error_msg = str(exc)
            self.statusBar().showMessage(f"[!] {error_msg}")
            if LOGGING_AVAILABLE:
                logger.error(f"Error al cargar perfil '{profile_name}': {error_msg}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.tr("profile_load_error_title"), error_msg)
            self.s3_handler = None
            self.active_profile_type = 's3'
        except Exception as exc:
            error_msg = self.tr("profile_load_unexpected_error").format(str(exc))
            self.statusBar().showMessage(f"[!] {error_msg}")
            if LOGGING_AVAILABLE:
                logger.error(f"Error inesperado al cargar perfil '{profile_name}': {str(exc)}", exc_info=True)
            from PyQt6.QtWidgets import QMessageBox
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(exc, context="load_profile")
                QMessageBox.warning(self, self.tr("profile_load_error_title"), error.message)
            else:
                QMessageBox.warning(self, self.tr("profile_load_error_title"), error_msg)
            self.s3_handler = None
            self.active_profile_type = 's3'
    def upload_file(self):
        if not self._require_s3_features():
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, self.tr("warning"), self.tr("no_buckets_available"))
            return
        
        file_path, _ = QFileDialog.getOpenFileName(self, self.tr("dialog_select_upload_file"))
        if file_path:
            bucket_name = self.bucket_selector.currentText()
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.statusBar().showMessage(self.tr("status_uploading_file").format(os.path.basename(file_path)))
            
            self.upload_thread = UploadThread(self.s3_handler, bucket_name, file_path)
            self.upload_thread.finished.connect(self.upload_finished)
            self.upload_thread.start()

    def upload_finished(self, success, payload):
        self.progress_bar.setVisible(False)
        payload = payload or {}
        file_name = payload.get("file")
        error_detail = payload.get("error")

        if success:
            if file_name:
                QMessageBox.information(
                    self,
                    self.tr("success"),
                    self.tr("upload_success_dialog").format(file_name),
                )
            else:
                QMessageBox.information(self, self.tr("success"), self.tr("status_upload_completed"))
            self.statusBar().showMessage(self.tr("status_upload_completed"), 5000)
        else:
            if file_name:
                message = self.tr("upload_error_dialog").format(
                    file_name,
                    error_detail or "",
                )
            else:
                message = error_detail or self.tr("status_upload_failed")
            QMessageBox.critical(self, self.tr("error"), message)
            self.statusBar().showMessage(self.tr("status_upload_failed"), 5000)

    def full_backup(self):
        if not self._require_s3_features():
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, self.tr("warning"), self.tr("no_buckets_available"))
            return
        
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("dialog_select_backup_directory"))
        if dir_path:
            bucket_name = self.bucket_selector.currentText()
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.statusBar().showMessage(self.tr("status_backup_starting").format(dir_path))
            
            self.backup_thread = BackupThread(self.s3_handler, bucket_name, dir_path)
            self.backup_thread.progress.connect(self.backup_progress)
            self.backup_thread.finished.connect(self.backup_finished)
            self.backup_thread.start()

    def backup_progress(self, value, payload):
        self.progress_bar.setValue(value)
        payload = payload or {}
        current = payload.get("current")
        total = payload.get("total")
        file_path = payload.get("file")
        if current and total and file_path:
            self.statusBar().showMessage(
                self.tr("status_backup_progress").format(current, total, file_path)
            )
        elif file_path:
            self.statusBar().showMessage(self.tr("status_backup_progress_simple").format(file_path))

    def backup_finished(self, success, payload):
        self.progress_bar.setVisible(False)
        payload = payload or {}
        if success:
            total = payload.get("total", 0)
            QMessageBox.information(
                self,
                self.tr("success"),
                self.tr("backup_success_dialog").format(total),
            )
            self.statusBar().showMessage(self.tr("status_backup_completed"), 5000)
        else:
            reason = payload.get("reason")
            if reason == "no_files":
                message = self.tr("backup_no_files")
            elif reason == "exception":
                detail = payload.get("detail", "")
                message = self.tr("backup_error_dialog").format(detail)
            else:
                message = self.tr("status_backup_failed")
            QMessageBox.critical(self, self.tr("error"), message)
            self.statusBar().showMessage(self.tr("status_backup_failed"), 5000)

    def mount_drive(self):
        if not self.profile_selector.currentText():
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_profile_first"))
            return

        if self.active_profile_type == 's3' and self.bucket_selector.count() == 0:
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_bucket_to_mount"))
            return

        drive_letter = self.drive_letter_input.currentText()
        profile_name = self.profile_selector.currentText()
        bucket_name = self.bucket_selector.currentText() if self.active_profile_type == 's3' else ''

        # Mostrar mensaje inmediatamente en la barra de estado
        display_target = bucket_name or self.tr("mega_virtual_bucket")
        self.statusBar().showMessage(self.tr("status_mounting").format(display_target, drive_letter))
        description = f"mount_drive[{drive_letter}:{display_target}]"

        def execute_mount():
            success, message, process = self.rclone_manager.mount_drive(
                profile_name,
                drive_letter,
                bucket_name,
            )
            return success, message, drive_letter, bucket_name, process

        def on_success(result):
            success, message, _letter, _bucket, process = result
            if success and self.multiple_mount_manager:
                try:
                    self.multiple_mount_manager.record_mount_success(_letter, profile_name, _bucket, process)
                except Exception as exc:
                    if LOGGING_AVAILABLE:
                        logger.warning("No se pudo registrar montaje múltiple: %s", exc, exc_info=True)
            if LOGGING_AVAILABLE:
                logger.info("Montaje completado (%s): %s", description, message)
            self._handle_mount_result(success, message, _letter, _bucket, process)

        def on_error(exc):
            error_msg = f"Error inesperado: {exc}"
            if LOGGING_AVAILABLE:
                logger.error("Error en tarea de montaje (%s): %s", description, str(exc), exc_info=True)
            self._handle_mount_result(False, error_msg, drive_letter, bucket_name, None)

        self.task_runner.run(
            execute_mount,
            on_success=on_success,
            on_error=on_error,
            description=description,
        )
    
    def _handle_mount_result(self, success, message, drive_letter, bucket_name, process=None):
        """Manejar resultado del montaje desde señal (thread-safe)"""
        if success:
            self._on_mount_success(drive_letter, bucket_name, message, process)
        else:
            self._on_mount_error(message)
        self._refresh_multi_mounts_widget()
    
    def _on_mount_success(self, drive_letter, bucket_name, message, process=None):
        """Manejar éxito del montaje"""
        try:
            self.mount_status_label.setText(self.tr("status_mounted").format(drive_letter))
            self.mount_button.setEnabled(False)
            self.unmount_button.setEnabled(True)
            self.open_drive_button.setEnabled(True)
            self.statusBar().showMessage(self.tr("status_mount_success").format(drive_letter), 5000)
            
            # ===== AUDITORÍA =====
            if self.audit_logger:
                self.audit_logger.log(
                    AuditEventType.DRIVE_MOUNTED,
                    {'drive_letter': drive_letter, 'bucket_name': bucket_name},
                    success=True
                )
            
            # ===== ACTUALIZAR MONITOR =====
            if self.state_monitor:
                self.state_monitor.update_component_status(
                    'rclone_manager',
                    ComponentStatus.RUNNING,
                    {'mounted_drives': [drive_letter]}
                )
            
            # ===== NOTIFICACIÓN DE ÉXITO =====
            if self.notification_manager:
                self.notification_manager.notify_mount_success(drive_letter, bucket_name)
            
            # Actualizar tooltip de bandeja
            self._update_tray_tooltip()

            # ✅ Refrescar la detección después de 3 segundos para mostrar la nueva unidad
            QTimer.singleShot(3000, self.detect_mounted_drives)
            
            # Mostrar el botón de cerrar sin desmontar
            self.update_close_without_unmount_button_visibility()
        except Exception as e:
            if LOGGING_AVAILABLE:
                logger.error(f"Error al procesar éxito de montaje: {e}")
    
    def _on_mount_error(self, error_msg):
        """Manejar error del montaje"""
        try:
            needs_winfsp = "winfsp" in error_msg.lower()
            
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle(self.tr("mount_error_title"))
            msg_box.setText(self.tr("mount_error_text"))
            msg_box.setInformativeText(error_msg)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            
            install_button = None
            if needs_winfsp and self.install_winfsp_callback:
                install_button = msg_box.addButton(self.tr("install_winfsp_button"), QMessageBox.ButtonRole.ActionRole)

            msg_box.exec()

            self.statusBar().showMessage(self.tr("status_mount_error"), 5000)

            if install_button and msg_box.clickedButton() == install_button:
                self.statusBar().showMessage(self.tr("status_installing_winfsp"))
                self.install_winfsp_callback()
        except Exception as e:
            if LOGGING_AVAILABLE:
                logger.error(f"Error al procesar error de montaje: {e}")
            self.open_drive_button.setEnabled(False)

    def set_winfsp_installer(self, callback):
        """Registrar callback para instalar WinFsp desde la UI"""
        self.install_winfsp_callback = callback

    def open_drive(self):
        """Abrir la unidad montada en el Explorador de archivos"""
        drive_letter = self.drive_letter_input.currentText()
        if not drive_letter:
            return

        path = f"{drive_letter}:\\"
        if not os.path.exists(path):
            QMessageBox.warning(self, self.tr("warning"), self.tr("drive_not_ready").format(drive_letter))
            self.open_drive_button.setEnabled(False)
            return

        try:
            os.startfile(path)
        except Exception as ex:
            QMessageBox.critical(self, self.tr("error"), self.tr("drive_open_failed").format(drive_letter, str(ex)))

    def unmount_drive(self):
        """Desmonta la unidad seleccionada usando la misma lógica del botón naranja"""
        drive_letter = self.drive_letter_input.currentText()

        if not drive_letter:
            QMessageBox.warning(
                self,
                self.tr("select_drive_letter_title"),
                self.tr("select_drive_letter_text")
            )
            return

        self.unmount_specific_drive(drive_letter)

    def update_unmount_button_state(self, *args, detected_drives=None):
        """Actualizar el estado de los botones de acuerdo con la letra seleccionada"""
        selected_letter = self.drive_letter_input.currentText()

        if not selected_letter:
            self.unmount_button.setEnabled(False)
            self.open_drive_button.setEnabled(False)
            self.mount_button.setEnabled(False)
            self.refresh_drive_button.setEnabled(False)
            self.mount_status_label.setText("⭕ Selecciona una letra de unidad")
            return

        mounted_letters = []

        if detected_drives is not None:
            mounted_letters = [d['letter'] for d in detected_drives] if detected_drives else []
        else:
            try:
                detected = DriveDetector.detect_mounted_drives()
                mounted_letters = [d['letter'] for d in detected] if detected else []
            except Exception as e:
                print(f"Error detectando unidades: {e}")

        is_mounted = selected_letter in mounted_letters

        if is_mounted:
            self.unmount_button.setEnabled(True)
            self.unmount_button.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; border-radius: 5px; padding: 8px;")
            self.open_drive_button.setEnabled(True)
            self.mount_button.setEnabled(False)
            self.mount_button.setStyleSheet("background-color: #CCCCCC; color: gray; font-weight: bold; border-radius: 5px; padding: 8px;")
            self.refresh_drive_button.setEnabled(True)
            self.mount_status_label.setText(self.tr("drive_letter_mounted_status").format(selected_letter))
        else:
            self.unmount_button.setEnabled(False)
            self.unmount_button.setStyleSheet("background-color: #CCCCCC; color: gray; font-weight: bold; border-radius: 5px; padding: 8px;")
            self.open_drive_button.setEnabled(False)
            self.mount_button.setEnabled(True)
            self.mount_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px; padding: 8px;")
            self.refresh_drive_button.setEnabled(False)
            self.mount_status_label.setText(self.tr("drive_letter_not_mounted_status").format(selected_letter))

    def _remount_drive_backend(self, drive_letter: str, profile_name: str, bucket_name: Optional[str]):
        unmount_success, unmount_message = self.rclone_manager.unmount_drive(drive_letter)
        if not unmount_success:
            return False, unmount_message
        time.sleep(2)
        success, message, process = self.rclone_manager.mount_drive(
            profile_name,
            drive_letter,
            bucket_name
        )
        if success and self.multiple_mount_manager:
            try:
                self.multiple_mount_manager.record_mount_success(
                    drive_letter,
                    profile_name,
                    bucket_name or '',
                    process
                )
            except Exception:
                pass
        return success, message

    def manual_refresh_mount(self):
        if self._manual_refresh_in_progress:
            return

        drive_letter = self.drive_letter_input.currentText()
        if not drive_letter:
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_drive_letter_text"))
            return

        profile_name = self.profile_selector.currentText()
        if not profile_name:
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_profile_first"))
            return

        bucket_name = self.bucket_selector.currentText() if self.active_profile_type == 's3' else None
        self._manual_refresh_in_progress = True
        self.statusBar().showMessage(self.tr("status_refreshing_drive").format(drive_letter))

        description = f"refresh_mount[{drive_letter}]"
        self.task_runner.run(
            lambda: self._remount_drive_backend(drive_letter, profile_name, bucket_name),
            on_success=lambda result: self._on_manual_refresh_result(drive_letter, result),
            on_error=lambda exc: self._on_manual_refresh_error(drive_letter, exc),
            description=description,
        )

    def _on_manual_refresh_result(self, drive_letter: str, result: Tuple[bool, str]):
        self._manual_refresh_in_progress = False
        success, message = result
        if success:
            self.statusBar().showMessage(self.tr("status_refresh_drive_success").format(drive_letter), 4000)
            self.detect_mounted_drives()
        else:
            QMessageBox.warning(
                self,
                self.tr("warning"),
                self.tr("error_refresh_drive").format(drive_letter, message)
            )
            self.statusBar().showMessage(self.tr("error_refresh_drive").format(drive_letter, message), 5000)

    def _on_manual_refresh_error(self, drive_letter: str, exc: Exception):
        self._manual_refresh_in_progress = False
        error_msg = str(exc)
        QMessageBox.critical(
            self,
            self.tr("error"),
            self.tr("error_refresh_drive").format(drive_letter, error_msg)
        )
        self.statusBar().showMessage(self.tr("error_refresh_drive").format(drive_letter, error_msg), 5000)

    def _auto_refresh_mount_if_needed(self):
        if self.active_profile_type != 'mega':
            return

        drive_letter = self.drive_letter_input.currentText()
        if not drive_letter:
            return

        try:
            detected = DriveDetector.detect_mounted_drives()
            mounted_letters = [d['letter'] for d in detected] if detected else []
        except Exception:
            mounted_letters = []

        if drive_letter not in mounted_letters or self._auto_refresh_in_progress:
            return

        profile_name = self.profile_selector.currentText()
        if not profile_name:
            return

        self._auto_refresh_in_progress = True
        self.task_runner.run(
            lambda: self._remount_drive_backend(drive_letter, profile_name, None),
            on_success=lambda result: self._on_auto_refresh_result(result),
            on_error=self._on_auto_refresh_error,
            description=f"auto_refresh[{drive_letter}]",
        )

    def _on_auto_refresh_result(self, result: Tuple[bool, str]):
        self._auto_refresh_in_progress = False
        success, _ = result
        if success:
            self.detect_mounted_drives()

    def _on_auto_refresh_error(self, exc: Exception):
        self._auto_refresh_in_progress = False
        if LOGGING_AVAILABLE:
            logger.warning("Error en auto-refresh de MEGA: %s", exc)

    def format_bucket(self):
        if not self._require_s3_features():
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, self.tr("warning"), self.tr("no_buckets_available"))
            return

        bucket_name = self.bucket_selector.currentText()

        reply = QMessageBox.question(
            self, 
            self.tr("format_bucket_confirm_title"), 
            self.tr("format_bucket_confirm_text").format(bucket_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Double confirmation
            confirm_text, ok = QMessageBox.getText(
                self,
                self.tr("format_bucket_final_confirm_title"),
                self.tr("format_bucket_final_confirm_text").format(bucket_name)
            )

            if ok and confirm_text == bucket_name:
                self.statusBar().showMessage(self.tr("formatting_bucket_status").format(bucket_name))
                success = self.s3_handler.delete_all_objects(bucket_name)
                
                if success:
                    QMessageBox.information(self, self.tr("success"), self.tr("bucket_formatted_message").format(bucket_name))
                    self.statusBar().showMessage(self.tr("bucket_formatted"), 5000)
                else:
                    QMessageBox.critical(self, self.tr("error"), self.tr("format_failed"))
                    self.statusBar().showMessage(self.tr("format_failed"), 5000)
            else:
                self.statusBar().showMessage(self.tr("format_cancelled"), 3000)

    def open_settings(self):
        self.settings_window = SettingsWindow(self.config_manager, self)
        self.settings_window.profiles_updated.connect(self.update_profiles)
        self.settings_window.show()

    def update_profiles(self):
        current_profile = self.profile_selector.currentText()
        self.profile_selector.clear()
        profiles = self.config_manager.list_profiles()
        self.profile_selector.addItems(profiles)
        if current_profile in profiles:
            self.profile_selector.setCurrentText(current_profile)
        elif profiles:
            self.load_profile(profiles[0])
        else:
            self.load_profile(None)
        self.refresh_profile_refresh_controls()
        self._bootstrap_sessions()
    
    def update_close_without_unmount_button_visibility(self):
        """Actualiza la visibilidad del botón 'Cerrar sin Desmontar' basado en unidades montadas"""
        try:
            from drive_detector import DriveDetector
            detected_drives = DriveDetector.detect_mounted_drives()
            
            if detected_drives and len(detected_drives) > 0:
                # Hay unidades montadas, mostrar el botón
                self.close_without_unmount_button.show()
            else:
                # No hay unidades montadas, ocultar el botón
                self.close_without_unmount_button.hide()
        except Exception as e:
            # Si hay error, ocultar el botón por seguridad
            self.close_without_unmount_button.hide()
            if LOGGING_AVAILABLE:
                logger.warning(f"Error al actualizar visibilidad del botón: {e}")
    
    def detect_mounted_drives(self):
        """Detecta todas las unidades montadas por rclone"""
        self.drives_list.setPlainText("🔍 Detectando unidades montadas...\n")
        self.drives_list.repaint()
        
        detected_drives = []  # ✅ Inicializar FUERA del try para que esté disponible después
        
        try:
            detected_drives = DriveDetector.detect_mounted_drives()
            
            # Actualizar visibilidad del botón
            self.update_close_without_unmount_button_visibility()
            
            if not detected_drives:
                self.drives_list.setPlainText(
                    "ℹ️ No se detectaron unidades montadas\n\n"
                    "No hay unidades V:, W:, X:, Y:, Z: montadas actualmente.\n"
                    "Todas las letras están disponibles para montar."
                )
                self.unmount_all_btn.setEnabled(False)
                self.open_drive_button.setEnabled(False)
                
                # OCULTAR el contenedor de botones individuales
                if hasattr(self, 'individual_buttons_container'):
                    self.individual_buttons_container.hide()
                
                # Limpiar botones individuales si existen
                if hasattr(self, 'individual_unmount_buttons'):
                    for btn in self.individual_unmount_buttons:
                        btn.setParent(None)
                        btn.deleteLater()
                    self.individual_unmount_buttons = []
            else:
                result_text = f"✅ Se detectaron {len(detected_drives)} unidad(es) montada(s):\n\n"
                
                for drive in detected_drives:
                    result_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    result_text += f"💿 Unidad: {drive['letter']}:\n"
                    result_text += f"📁 Ruta: {drive['path']}\n"
                    result_text += f"🏷️  Etiqueta: {drive['label']}\n"
                    
                    if drive['has_process']:
                        result_text += f"🔧 Proceso(s): {drive['process_ids']}\n"
                        result_text += f"✅ Estado: Proceso activo\n\n"
                    else:
                        result_text += f"[!]️  Proceso: No detectado (sesión anterior)\n"
                        result_text += f"📌 Estado: Montada sin proceso activo\n\n"
                
                result_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                result_text += "\n💡 Usa los botones individuales o 'Desmontar Todas'."
                
                self.drives_list.setPlainText(result_text)
                self.unmount_all_btn.setEnabled(True)
                
                # MOSTRAR el contenedor de botones individuales
                if hasattr(self, 'individual_buttons_container'):
                    self.individual_buttons_container.show()
                
                # Crear botones individuales de desmontaje
                self.create_individual_unmount_buttons(detected_drives)
                
                # Actualizar status bar
                self.statusBar().showMessage(
                    f"✅ {len(detected_drives)} unidad(es) detectada(s): " + 
                    ", ".join([d['letter'] + ":" for d in detected_drives]),
                    5000
                )
        
        except Exception as e:
            error_msg = f"❌ Error al detectar unidades:\n\n{str(e)}\n\n"
            error_msg += "Asegúrate de que tienes los permisos necesarios."
            self.drives_list.setPlainText(error_msg)
            self.unmount_all_btn.setEnabled(False)
            detected_drives = []
            
            QMessageBox.critical(
                self,
                "Error de Detección",
                f"No se pudieron detectar las unidades montadas:\n\n{str(e)}"
            )
        finally:
            self.update_unmount_button_state(detected_drives=detected_drives)
            self._refresh_multi_mounts_widget()
    
    def create_individual_unmount_buttons(self, detected_drives):
        """Crea botones individuales para desmontar cada unidad"""
        # Limpiar layout existente
        while self.individual_buttons_container_layout.count():
            item = self.individual_buttons_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not detected_drives:
            # Si no hay unidades, ocultar el contenedor
            self.individual_buttons_container.hide()
            return
        
        # Etiqueta de sección
        label = QLabel("🎯 Desmontar Unidades Específicas:")
        label.setStyleSheet("font-weight: bold; color: #3498db; margin-top: 10px;")
        self.individual_buttons_container_layout.addWidget(label)
        
        # Crear un botón para cada unidad
        for drive in detected_drives:
            btn_layout = QHBoxLayout()
            
            # Botón de desmontaje
            unmount_btn = QPushButton(f"🗑️ Desmontar {drive['letter']}:")
            unmount_btn.clicked.connect(lambda checked, letter=drive['letter']: self.unmount_specific_drive(letter))
            unmount_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e67e22;
                    color: white;
                    border: none;
                    padding: 8px 15px;
                    font-size: 10pt;
                    font-weight: bold;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #d35400;
                }
            """)
            
            # Etiqueta con info
            info_label = QLabel(f"({drive['label'][:30]}{'...' if len(drive['label']) > 30 else ''})")
            info_label.setStyleSheet("color: #95a5a6; font-size: 9pt;")
            
            btn_layout.addWidget(unmount_btn)
            btn_layout.addWidget(info_label)
            btn_layout.addStretch()
            
            self.individual_buttons_container_layout.addLayout(btn_layout)
        
        # Mostrar el contenedor
        self.individual_buttons_container.show()
    
    def unmount_specific_drive(self, drive_letter: str):
        """Desmonta una unidad específica"""
        reply = QMessageBox.question(
            self,
            "[!]️ Confirmar Desmontaje",
            f"¿Estás seguro de que deseas desmontar la unidad {drive_letter}:?\n\n"
            f"Los archivos abiertos desde esta unidad se cerrarán.\n"
            f"Las demás unidades permanecerán montadas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.statusBar().showMessage(self.tr("status_unmounting_drive").format(drive_letter))
            
            try:
                if self.multiple_mount_manager:
                    success, message = self.multiple_mount_manager.unmount_drive(drive_letter)
                    if not success:
                        # Fallback a detección manual
                        success, message = DriveDetector.unmount_drive(drive_letter, self.translations)
                else:
                    success, message = DriveDetector.unmount_drive(drive_letter, self.translations)
                
                if success:
                    self.statusBar().showMessage(self.tr("status_unmount_drive_success").format(message), 3000)
                    
                    # Actualizar visibilidad del botón después de desmontar
                    QTimer.singleShot(1000, self.update_close_without_unmount_button_visibility)
                    
                    # ===== AUDITORÍA =====
                    if self.audit_logger:
                        self.audit_logger.log(
                            AuditEventType.DRIVE_UNMOUNTED,
                            {'drive_letter': drive_letter},
                            success=True
                        )
                    
                    # ===== ACTUALIZAR MONITOR =====
                    if self.state_monitor:
                        # Obtener lista actualizada de unidades montadas
                        from drive_detector import DriveDetector
                        mounted = DriveDetector.detect_mounted_drives()
                        mounted_letters = [d['letter'] for d in mounted] if mounted else []
                        if not mounted_letters:
                            self.state_monitor.update_component_status(
                                'rclone_manager',
                                ComponentStatus.READY,
                                {'mounted_drives': []}
                            )
                    
                    # ===== NOTIFICACIÓN DE DESMONTAJE =====
                    if self.notification_manager:
                        self.notification_manager.notify_unmount_success(drive_letter)
                    
                    # Actualizar tooltip de bandeja
                    self._update_tray_tooltip()
                    
                    # Función para actualizar la UI completamente
                    def refresh_ui_complete():
                        # 1. Refrescar la detección de unidades montadas
                        self.detect_mounted_drives()
                        
                        # 2. Rehabilitar el botón "Montar como Unidad"
                        self.mount_button.setEnabled(True)
                        
                        # 3. Deshabilitar el botón "Desmontar Unidad"
                        self.unmount_button.setEnabled(False)

                        # 3b. Deshabilitar botón de abrir hasta que vuelva a montarse
                        self.open_drive_button.setEnabled(False)
                        
                        # 4. Actualizar el estado del montaje
                        self.mount_status_label.setText(self.tr("status_not_mounted"))
                    
                    # Esperar 2 segundos para asegurar que la unidad se libere completamente
                    QTimer.singleShot(2000, refresh_ui_complete)
                    self._refresh_multi_mounts_widget()
                else:
                    QMessageBox.critical(
                        self,
                        self.tr("error"),
                        self.tr("error_unmount_drive").format(drive_letter, message)
                    )
                    self.statusBar().showMessage(self.tr("status_unmount_drive_error").format(drive_letter), 5000)
                    self._refresh_multi_mounts_widget()
                    
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("error"),
                    self.tr("error_unexpected_unmount_drive").format(drive_letter, str(e))
                )
                self._refresh_multi_mounts_widget()
    
    def unmount_all_detected_drives(self):
        """Desmonta todas las unidades detectadas"""
        reply = QMessageBox.question(
            self,
            self.tr("confirm_unmount_all_title"),
            self.tr("confirm_unmount_all_text"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.statusBar().showMessage(self.tr("status_unmounting_all"))
            
            try:
                success = False
                message = ""
                if self.multiple_mount_manager:
                    success, message = self.multiple_mount_manager.unmount_all()
                    if not success:
                        # Intentar fallback para cualquier unidad residual
                        success_fallback, message_fallback = DriveDetector.unmount_all_drives(self.translations)
                        if success_fallback:
                            success = True
                            message = message_fallback
                else:
                    success, message = DriveDetector.unmount_all_drives(self.translations)
                
                if success:
                    # Actualizar visibilidad del botón después de desmontar todas
                    QTimer.singleShot(1000, self.update_close_without_unmount_button_visibility)
                    
                    self.drives_list.setPlainText(self.tr("unmount_all_success_details").format(message))
                    self.unmount_all_btn.setEnabled(False)
                    
                    # También actualizar el estado del botón de unmount principal
                    self.unmount_button.setEnabled(False)
                    self.open_drive_button.setEnabled(False)
                    self.mount_button.setEnabled(True)
                    self.mount_status_label.setText(self.tr("status_not_mounted"))
                    
                    # Ocultar el contenedor de botones individuales
                    if hasattr(self, 'individual_buttons_container'):
                        self.individual_buttons_container.hide()
                    
                    QMessageBox.information(
                        self,
                        self.tr("success"),
                        message
                    )
                    
                    self.statusBar().showMessage(self.tr("status_unmount_all_success").format(message), 5000)
                    self._refresh_multi_mounts_widget()
                else:
                    self.drives_list.setPlainText(self.tr("unmount_all_error_details").format(message))
                    QMessageBox.critical(
                        self,
                        self.tr("error"),
                        self.tr("error_unmount_all").format(message)
                    )
                    self.statusBar().showMessage(self.tr("status_unmount_all_error"), 5000)
                    self._refresh_multi_mounts_widget()
                    
            except Exception as e:
                self.drives_list.setPlainText(self.tr("unmount_all_unexpected_error_details").format(str(e)))
                QMessageBox.critical(
                    self,
                    self.tr("error"),
                    self.tr("error_unexpected_unmount_all").format(str(e))
                )
                self._refresh_multi_mounts_widget()

    def closeEvent(self, event):
        """Gestionar el cierre de la aplicación con opción de segundo plano"""
        if self._force_quit or not self._should_keep_in_background():
            self._execute_shutdown_tasks()
            event.accept()
            return

        # Si hay icono en bandeja, minimizar a bandeja en lugar de cerrar
        if self.tray_icon and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            
            # Notificar la primera vez
            if not self._tray_notified and self.notification_manager:
                self.notification_manager.info(
                    self.tr("app_name"),
                    self.tr("tray_running_notification")
                )
                self._tray_notified = True
            return

        # Si no hay bandeja, mostrar diálogo
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setWindowTitle(self.tr("background_running_title"))
        dialog.setText(self.tr("background_running_message"))
        keep_btn = dialog.addButton(self.tr("background_keep_running"), QMessageBox.ButtonRole.AcceptRole)
        exit_btn = dialog.addButton(self.tr("background_exit"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = dialog.addButton(QMessageBox.StandardButton.Cancel)

        dialog.exec()

        clicked = dialog.clickedButton()
        if clicked == keep_btn:
            event.ignore()
            self.send_to_tray(show_message=True)
        elif clicked == exit_btn:
            self._force_quit = True
            self._execute_shutdown_tasks()
            event.accept()
        else:
            event.ignore()
    
    def _on_scheduled_task_executed(self, task_id: str, success: bool, message: str):
        """Manejar ejecución de tarea programada"""
        if LOGGING_AVAILABLE:
            logger.info(f"Tarea programada ejecutada: {task_id} - {message}")
        if self.audit_logger:
            self.audit_logger.log(
                AuditEventType.SYNC_STARTED if 'sync' in task_id.lower() else AuditEventType.BACKUP_STARTED,
                {'task_id': task_id, 'message': message},
                success=success
            )
    
    def _on_scheduled_task_error(self, task_id: str, error_message: str):
        """Manejar error en tarea programada"""
        if LOGGING_AVAILABLE:
            logger.error(f"Error en tarea programada {task_id}: {error_message}")
        if self.audit_logger:
            self.audit_logger.log(
                AuditEventType.ERROR_OCCURRED,
                {'task_id': task_id},
                success=False,
                error_message=error_message
            )
    
    def update_dashboard_stats(self, force_remote=False):
        """Actualizar estadísticas del dashboard (Mejora #52)"""
        if not hasattr(self, 'dashboard_tab'):
            return

        try:
            from datetime import datetime
            stats = {}
            stats['profile_type'] = getattr(self, 'active_profile_type', 's3')

            if self.active_profile_type != 's3' or not self.s3_handler:
                stats['space_used'] = 0
                stats['space_total'] = 0
                stats['files_synced_today'] = 0
                stats['transfer_speed'] = 0.0
                stats['last_sync'] = None
                try:
                    from drive_detector import DriveDetector
                    detected = DriveDetector.detect_mounted_drives()
                    stats['mounted_drives'] = [d['letter'] for d in detected] if detected else []
                except Exception:
                    stats['mounted_drives'] = []
                self.dashboard_tab.update_stats(stats)
                return

            # Obtener espacio usado del bucket
            if self.s3_handler and self.bucket_selector.count() > 0:
                try:
                    bucket_name = self.bucket_selector.currentText()
                    # Obtener tamaño real del bucket
                    space_used, error_msg = self.s3_handler.get_bucket_size(bucket_name, use_cache=not force_remote)

                    if error_msg:
                        if LOGGING_AVAILABLE:
                            logger.warning(f"Error al obtener tamaño del bucket: {error_msg}")
                        stats['space_used'] = 0
                        stats['space_total'] = 0
                    else:
                        stats['space_used'] = space_used if space_used else 0
                        # Vultr Object Storage: Los planes típicos son:
                        # - Starter: 250 GB
                        # - Performance: 1 TB (1024 GB)
                        # - Enterprise: Ilimitado
                        # Por defecto usamos 1 TB, pero el usuario puede tener más
                        # Si el espacio usado es mayor a 1 TB, ajustamos el total
                        if space_used > 1024 * 1024 * 1024 * 1024:  # Si usa más de 1 TB
                            # Estimar que tiene al menos 2x lo usado, o usar 10 TB como máximo razonable
                            estimated_total = max(space_used * 2, 10 * 1024 * 1024 * 1024 * 1024)
                            stats['space_total'] = estimated_total
                        else:
                            # Usar 1 TB como referencia estándar
                            stats['space_total'] = 1024 * 1024 * 1024 * 1024  # 1 TB en bytes
                except Exception as e:
                    if LOGGING_AVAILABLE:
                        logger.error(f"Error al obtener estadísticas del bucket: {e}")
                    stats['space_used'] = 0
                    stats['space_total'] = 0
            else:
                stats['space_used'] = 0
                stats['space_total'] = 0
            
            # Obtener archivos sincronizados hoy
            stats['files_synced_today'] = 0  # TODO: Implementar contador
            
            # Velocidad de transferencia
            stats['transfer_speed'] = 0.0  # TODO: Implementar
            
            # Última sincronización
            if self.real_time_sync and self.real_time_sync.is_running():
                stats['last_sync'] = datetime.now()
            else:
                stats['last_sync'] = None
            
            # Unidades montadas
            try:
                from drive_detector import DriveDetector
                detected = DriveDetector.detect_mounted_drives()
                stats['mounted_drives'] = [d['letter'] for d in detected] if detected else []
            except:
                stats['mounted_drives'] = []
            
            # Actualizar dashboard
            self.dashboard_tab.update_stats(stats)
        except Exception as e:
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(e, context="update_dashboard_stats")
                if self.notification_manager:
                    self.notification_manager.warning("Dashboard", f"Error al actualizar: {error.message}")
            if LOGGING_AVAILABLE:
                logger.error(f"Error al actualizar dashboard: {e}", exc_info=True)





