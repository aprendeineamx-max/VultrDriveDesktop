from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, 
                             QHBoxLayout, QListWidget, QMessageBox, QCheckBox, QGroupBox, QTabWidget)
from PyQt6.QtCore import pyqtSignal, Qt

class SettingsWindow(QWidget):
    profiles_updated = pyqtSignal()

    def __init__(self, config_manager, main_window=None):
        super().__init__()
        self.config_manager = config_manager
        self.main_window = main_window
        self.setWindowTitle("Configuración - VultrDrive Desktop")
        self.setGeometry(150, 150, 600, 500)

        # ===== PESTAÑAS =====
        self.tabs = QTabWidget()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.addWidget(self.tabs)
        
        # Pestaña 1: Perfiles
        profiles_tab = QWidget()
        profiles_layout = QHBoxLayout(profiles_tab)
        profiles_layout.setContentsMargins(10, 10, 10, 10)
        profiles_layout.setSpacing(20)

        # Left side: List of profiles
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Perfiles Existentes:"))
        self.profile_list = QListWidget()
        self.profile_list.itemClicked.connect(self.load_profile_details)
        left_layout.addWidget(self.profile_list)
        
        self.delete_button = QPushButton("Eliminar Perfil Seleccionado")
        self.delete_button.clicked.connect(self.delete_profile)
        left_layout.addWidget(self.delete_button)

        # Right side: Form to add/edit
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Agregar o Editar Perfil:"))
        
        self.form_layout = QFormLayout()
        self.profile_name_input = QLineEdit()
        self.profile_name_input.setPlaceholderText("Ej: mi-cuenta-vultr")
        
        self.access_key_input = QLineEdit()
        self.access_key_input.setPlaceholderText("Ej: VVQQYYLLLHH4OB6ZZAABBC")
        
        self.secret_key_input = QLineEdit()
        self.secret_key_input.setPlaceholderText("Ej: g9UUiHHvKKaabbcc12334455VVxxYYzzAABBCC")
        self.secret_key_input.setEchoMode(QLineEdit.EchoMode.Password)  # Ocultar contraseña
        
        self.host_base_input = QLineEdit()
        self.host_base_input.setPlaceholderText("Ej: ewr1.vultrobjects.com")

        self.form_layout.addRow("Nombre del Perfil:", self.profile_name_input)
        self.form_layout.addRow("Access Key:", self.access_key_input)
        self.form_layout.addRow("Secret Key:", self.secret_key_input)
        self.form_layout.addRow("Hostname:", self.host_base_input)
        
        right_layout.addLayout(self.form_layout)

        self.save_button = QPushButton("Guardar Perfil")
        self.save_button.clicked.connect(self.save_profile)
        right_layout.addWidget(self.save_button)
        right_layout.addStretch()

        profiles_layout.addLayout(left_layout, 1)
        profiles_layout.addLayout(right_layout, 2)
        
        self.tabs.addTab(profiles_tab, "📋 Perfiles")
        
        # Pestaña 2: Configuración General
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setContentsMargins(20, 20, 20, 20)
        general_layout.setSpacing(15)
        
        # Grupo: Inicio Automático
        startup_group = QGroupBox("🚀 Inicio Automático")
        startup_layout = QVBoxLayout()
        
        self.chk_startup = QCheckBox("Iniciar con Windows")
        if self.main_window and hasattr(self.main_window, 'startup_manager'):
            self.chk_startup.setChecked(self.main_window.startup_manager.is_enabled())
        self.chk_startup.stateChanged.connect(self.on_startup_changed)
        startup_layout.addWidget(self.chk_startup)
        
        self.chk_minimized = QCheckBox("Iniciar minimizado en bandeja")
        if self.main_window and hasattr(self.main_window, 'startup_manager'):
            self.chk_minimized.setEnabled(self.chk_startup.isChecked())
        self.chk_minimized.stateChanged.connect(self.on_startup_minimized_changed)
        startup_layout.addWidget(self.chk_minimized)
        
        startup_info = QLabel("Si está activado, VultrDrive Desktop se iniciará automáticamente cuando Windows arranque.")
        startup_info.setWordWrap(True)
        startup_info.setStyleSheet("color: #888; font-size: 9pt; margin-top: 10px;")
        startup_layout.addWidget(startup_info)
        
        startup_group.setLayout(startup_layout)
        general_layout.addWidget(startup_group)
        
        # Grupo: Notificaciones
        notifications_group = QGroupBox("🔔 Notificaciones")
        notifications_layout = QVBoxLayout()
        
        self.chk_notifications = QCheckBox("Mostrar notificaciones de escritorio")
        if self.main_window and hasattr(self.main_window, 'notification_manager'):
            self.chk_notifications.setChecked(self.main_window.notification_manager.enabled)
        else:
            self.chk_notifications.setChecked(True)
        self.chk_notifications.stateChanged.connect(self.on_notifications_changed)
        notifications_layout.addWidget(self.chk_notifications)
        
        notifications_info = QLabel("Recibirás notificaciones cuando se monten/desmonten unidades, se completen sincronizaciones, etc.")
        notifications_info.setWordWrap(True)
        notifications_info.setStyleSheet("color: #888; font-size: 9pt; margin-top: 10px;")
        notifications_layout.addWidget(notifications_info)
        
        notifications_group.setLayout(notifications_layout)
        general_layout.addWidget(notifications_group)
        
        general_layout.addStretch()
        
        self.tabs.addTab(general_tab, "⚙️ General")

        self.refresh_profile_list()

    def refresh_profile_list(self):
        self.profile_list.clear()
        self.profile_list.addItems(self.config_manager.list_profiles())

    def load_profile_details(self, item):
        profile_name = item.text()
        config = self.config_manager.get_config(profile_name)
        if config:
            self.profile_name_input.setText(profile_name)
            self.access_key_input.setText(config.get('access_key', ''))
            self.secret_key_input.setText(config.get('secret_key', ''))
            self.host_base_input.setText(config.get('host_base', ''))

    def save_profile(self):
        profile_name = self.profile_name_input.text()
        access_key = self.access_key_input.text()
        secret_key = self.secret_key_input.text()
        host_base = self.host_base_input.text()

        if profile_name and access_key and secret_key and host_base:
            self.config_manager.add_config(profile_name, access_key, secret_key, host_base)
            self.profiles_updated.emit()
            self.refresh_profile_list()
            self.clear_form()
        else:
            QMessageBox.warning(self, "Warning", "All fields are required to save a profile.")

    def delete_profile(self):
        selected_items = self.profile_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "Please select a profile to delete.")
            return

        profile_name = selected_items[0].text()
        reply = QMessageBox.question(self, 'Confirm Delete', 
                                     f"Are you sure you want to delete the profile '{profile_name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self.config_manager.delete_config(profile_name)
            self.profiles_updated.emit()
            self.refresh_profile_list()
            self.clear_form()

    def clear_form(self):
        self.profile_name_input.clear()
        self.access_key_input.clear()
        self.secret_key_input.clear()
        self.host_base_input.clear()
    
    def on_startup_changed(self, state):
        """Callback cuando cambia el checkbox de inicio automático"""
        if not self.main_window or not hasattr(self.main_window, 'startup_manager'):
            return
        
        enabled = state == Qt.CheckState.Checked
        minimized = self.chk_minimized.isChecked()
        
        success, message = self.main_window.startup_manager.toggle(enabled, minimized)
        
        if success:
            if self.main_window.notification_manager:
                self.main_window.notification_manager.success(
                    "Configuración Guardada",
                    message
                )
        else:
            if self.main_window.notification_manager:
                self.main_window.notification_manager.error(
                    "Error",
                    message
                )
        
        self.chk_minimized.setEnabled(enabled)
    
    def on_startup_minimized_changed(self, state):
        """Callback cuando cambia el checkbox de iniciar minimizado"""
        if not self.main_window or not hasattr(self.main_window, 'startup_manager'):
            return
        
        if not self.chk_startup.isChecked():
            return
        
        minimized = state == Qt.CheckState.Checked
        success, message = self.main_window.startup_manager.enable(minimized)
        
        if success and self.main_window.notification_manager:
            self.main_window.notification_manager.info(
                "Configuración Actualizada",
                message
            )
    
    def on_notifications_changed(self, state):
        """Callback cuando cambia el checkbox de notificaciones"""
        if not self.main_window or not hasattr(self.main_window, 'notification_manager'):
            return
        
        enabled = state == Qt.CheckState.Checked
        self.main_window.notification_manager.set_enabled(enabled)
