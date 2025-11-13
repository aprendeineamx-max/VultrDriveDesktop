from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, 
                             QHBoxLayout, QListWidget, QMessageBox, QCheckBox, QGroupBox, QTabWidget)
from PyQt6.QtCore import pyqtSignal, Qt

class SettingsWindow(QWidget):
    profiles_updated = pyqtSignal()

    def __init__(self, config_manager, main_window=None):
        super().__init__()
        self.config_manager = config_manager
        self.main_window = main_window
        self.translations = getattr(main_window, "translations", None)
        self.setWindowTitle(self.tr("settings_window_title"))
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
        left_layout.addWidget(QLabel(self.tr("settings_existing_profiles")))
        self.profile_list = QListWidget()
        self.profile_list.itemClicked.connect(self.load_profile_details)
        left_layout.addWidget(self.profile_list)
        
        self.delete_button = QPushButton(self.tr("settings_delete_profile_button"))
        self.delete_button.clicked.connect(self.delete_profile)
        left_layout.addWidget(self.delete_button)

        # Right side: Form to add/edit
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel(self.tr("settings_add_edit_profile")))
        
        self.form_layout = QFormLayout()
        self.profile_name_input = QLineEdit()
        self.profile_name_input.setPlaceholderText(self.tr("settings_profile_placeholder"))
        
        self.access_key_input = QLineEdit()
        self.access_key_input.setPlaceholderText(self.tr("settings_access_key_placeholder"))
        
        self.secret_key_input = QLineEdit()
        self.secret_key_input.setPlaceholderText(self.tr("settings_secret_key_placeholder"))
        self.secret_key_input.setEchoMode(QLineEdit.EchoMode.Password)  # Ocultar contraseña
        
        self.host_base_input = QLineEdit()
        self.host_base_input.setPlaceholderText(self.tr("settings_host_placeholder"))

        self.form_layout.addRow(self.tr("settings_profile_label"), self.profile_name_input)
        self.form_layout.addRow(self.tr("settings_access_key_label"), self.access_key_input)
        self.form_layout.addRow(self.tr("settings_secret_key_label"), self.secret_key_input)
        self.form_layout.addRow(self.tr("settings_host_label"), self.host_base_input)
        
        right_layout.addLayout(self.form_layout)

        self.save_button = QPushButton(self.tr("settings_save_button"))
        self.save_button.clicked.connect(self.save_profile)
        right_layout.addWidget(self.save_button)
        right_layout.addStretch()

        profiles_layout.addLayout(left_layout, 1)
        profiles_layout.addLayout(right_layout, 2)
        
        self.tabs.addTab(profiles_tab, self.tr("settings_profiles_tab"))
        
        # Pestaña 2: Configuración General
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setContentsMargins(20, 20, 20, 20)
        general_layout.setSpacing(15)
        
        # Grupo: Inicio Automático
        startup_group = QGroupBox(self.tr("settings_startup_group"))
        startup_layout = QVBoxLayout()
        
        self.chk_startup = QCheckBox(self.tr("settings_startup_checkbox"))
        if self.main_window and hasattr(self.main_window, 'startup_manager'):
            self.chk_startup.setChecked(self.main_window.startup_manager.is_enabled())
        self.chk_startup.stateChanged.connect(self.on_startup_changed)
        startup_layout.addWidget(self.chk_startup)
        
        self.chk_minimized = QCheckBox(self.tr("settings_startup_minimized"))
        if self.main_window and hasattr(self.main_window, 'startup_manager'):
            self.chk_minimized.setEnabled(self.chk_startup.isChecked())
        self.chk_minimized.stateChanged.connect(self.on_startup_minimized_changed)
        startup_layout.addWidget(self.chk_minimized)
        
        startup_info = QLabel(self.tr("settings_startup_info"))
        startup_info.setWordWrap(True)
        startup_info.setStyleSheet("color: #888; font-size: 9pt; margin-top: 10px;")
        startup_layout.addWidget(startup_info)
        
        startup_group.setLayout(startup_layout)
        general_layout.addWidget(startup_group)
        
        # Grupo: Notificaciones
        notifications_group = QGroupBox(self.tr("settings_notifications_group"))
        notifications_layout = QVBoxLayout()
        
        self.chk_notifications = QCheckBox(self.tr("settings_notifications_checkbox"))
        if self.main_window and hasattr(self.main_window, 'notification_manager'):
            self.chk_notifications.setChecked(self.main_window.notification_manager.enabled)
        else:
            self.chk_notifications.setChecked(True)
        self.chk_notifications.stateChanged.connect(self.on_notifications_changed)
        notifications_layout.addWidget(self.chk_notifications)
        
        notifications_info = QLabel(self.tr("settings_notifications_info"))
        notifications_info.setWordWrap(True)
        notifications_info.setStyleSheet("color: #888; font-size: 9pt; margin-top: 10px;")
        notifications_layout.addWidget(notifications_info)
        
        notifications_group.setLayout(notifications_layout)
        general_layout.addWidget(notifications_group)
        
        general_layout.addStretch()
        
        self.tabs.addTab(general_tab, self.tr("settings_general_tab"))

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
            QMessageBox.warning(self, self.tr("warning"), self.tr("settings_warning_all_fields"))

    def delete_profile(self):
        selected_items = self.profile_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, self.tr("warning"), self.tr("settings_warning_select_profile"))
            return

        profile_name = selected_items[0].text()
        reply = QMessageBox.question(self, self.tr("settings_confirm_delete_title"), 
                                     self.tr("settings_confirm_delete_text").format(profile_name),
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
                    self.tr("settings_notification_saved_title"),
                    message
                )
        else:
            if self.main_window.notification_manager:
                self.main_window.notification_manager.error(
                    self.tr("settings_notification_error_title"),
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
                self.tr("settings_notification_updated_title"),
                message
            )
    
    def on_notifications_changed(self, state):
        """Callback cuando cambia el checkbox de notificaciones"""
        if not self.main_window or not hasattr(self.main_window, 'notification_manager'):
            return
        
        enabled = state == Qt.CheckState.Checked
        self.main_window.notification_manager.set_enabled(enabled)

    def tr(self, key):
        if self.translations:
            return self.translations.get(key)
        return key
