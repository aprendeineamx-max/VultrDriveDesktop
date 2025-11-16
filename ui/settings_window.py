from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, 
                             QHBoxLayout, QListWidget, QMessageBox, QTabWidget, QComboBox)
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
        self.profile_list.itemSelectionChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list)
        
        self.new_profile_button = QPushButton(self.tr("settings_new_profile_button"))
        self.new_profile_button.clicked.connect(self.start_new_profile)
        left_layout.addWidget(self.new_profile_button)

        self.delete_button = QPushButton(self.tr("settings_delete_profile_button"))
        self.delete_button.clicked.connect(self.delete_profile)
        left_layout.addWidget(self.delete_button)

        # Right side: Form to add/edit
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel(self.tr("settings_add_edit_profile")))
        
        self.form_layout = QFormLayout()
        self.profile_name_input = QLineEdit()
        self.profile_name_input.setPlaceholderText(self.tr("settings_profile_placeholder"))

        self.profile_type_combo = QComboBox()
        self.profile_type_combo.addItem(self.tr("settings_profile_type_s3"), "s3")
        self.profile_type_combo.addItem(self.tr("settings_profile_type_mega"), "mega")
        self.profile_type_combo.currentIndexChanged.connect(self.update_profile_form_visibility)
        
        self.access_key_input = QLineEdit()
        self.access_key_input.setPlaceholderText(self.tr("settings_access_key_placeholder"))
        
        self.secret_key_input = QLineEdit()
        self.secret_key_input.setPlaceholderText(self.tr("settings_secret_key_placeholder"))
        self.secret_key_input.setEchoMode(QLineEdit.EchoMode.Password)  # Ocultar contraseña
        
        self.host_base_input = QLineEdit()
        self.host_base_input.setPlaceholderText(self.tr("settings_host_placeholder"))

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText(self.tr("settings_email_placeholder"))

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText(self.tr("settings_password_placeholder"))
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.form_layout.addRow(self.tr("settings_profile_label"), self.profile_name_input)
        self.form_layout.addRow(self.tr("settings_profile_type_label"), self.profile_type_combo)
        self.form_layout.addRow(self.tr("settings_access_key_label"), self.access_key_input)
        self.form_layout.addRow(self.tr("settings_secret_key_label"), self.secret_key_input)
        self.form_layout.addRow(self.tr("settings_host_label"), self.host_base_input)
        self.form_layout.addRow(self.tr("settings_email_label"), self.email_input)
        self.form_layout.addRow(self.tr("settings_password_label"), self.password_input)
        
        right_layout.addLayout(self.form_layout)

        self.save_button = QPushButton(self.tr("settings_save_button"))
        self.save_button.clicked.connect(self.save_profile)
        right_layout.addWidget(self.save_button)
        right_layout.addStretch()

        profiles_layout.addLayout(left_layout, 1)
        profiles_layout.addLayout(right_layout, 2)
        
        self.tabs.addTab(profiles_tab, self.tr("settings_profiles_tab"))
        self.update_profile_form_visibility()

        self.refresh_profile_list()

    def refresh_profile_list(self, select_profile=None):
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        profiles = self.config_manager.list_profiles()
        self.profile_list.addItems(profiles)
        self.profile_list.blockSignals(False)

        if select_profile:
            matches = self.profile_list.findItems(select_profile, Qt.MatchFlag.MatchExactly)
            if matches:
                self.profile_list.setCurrentItem(matches[0])
                self.load_profile_details(matches[0])
                return
        self.start_new_profile(clear_selection=False)

    def _on_profile_selected(self):
        items = self.profile_list.selectedItems()
        if not items:
            self.start_new_profile(clear_selection=False)
            return
        self.load_profile_details(items[0])

    def load_profile_details(self, item):
        profile_name = item if isinstance(item, str) else item.text()
        config = self.config_manager.get_config(profile_name) or {}
        profile_type = (config.get('type') or 's3').lower()
        index = self.profile_type_combo.findData(profile_type)
        if index >= 0:
            self.profile_type_combo.setCurrentIndex(index)
        else:
            self.profile_type_combo.setCurrentIndex(0)

        self.profile_name_input.setText(profile_name)

        if profile_type == 'mega':
            self.email_input.setText(config.get('email', ''))
            self.password_input.setText(config.get('password', ''))
            self.access_key_input.clear()
            self.secret_key_input.clear()
            self.host_base_input.clear()
        else:
            self.access_key_input.setText(config.get('access_key', ''))
            self.secret_key_input.setText(config.get('secret_key', ''))
            self.host_base_input.setText(config.get('host_base', ''))
            self.email_input.clear()
            self.password_input.clear()

        self.update_profile_form_visibility()

    def save_profile(self):
        profile_name = self.profile_name_input.text().strip()
        profile_type = self.profile_type_combo.currentData() or 's3'

        if profile_type == 'mega':
            email = self.email_input.text().strip()
            password = self.password_input.text().strip()
            if not (profile_name and email and password):
                QMessageBox.warning(self, self.tr("warning"), self.tr("settings_warning_mega_fields"))
                return
            self.config_manager.save_profile(profile_name, 'mega', email=email, password=password)
        else:
            access_key = self.access_key_input.text().strip()
            secret_key = self.secret_key_input.text().strip()
            host_base = self.host_base_input.text().strip()
            if not (profile_name and access_key and secret_key and host_base):
                QMessageBox.warning(self, self.tr("warning"), self.tr("settings_warning_s3_fields"))
                return
            self.config_manager.save_profile(
                profile_name,
                's3',
                access_key=access_key,
                secret_key=secret_key,
                host_base=host_base
            )

        self.profiles_updated.emit()
        self.refresh_profile_list(select_profile=profile_name)

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

    def start_new_profile(self, clear_selection=True):
        if clear_selection:
            self.profile_list.blockSignals(True)
            self.profile_list.clearSelection()
            self.profile_list.blockSignals(False)
        self.profile_name_input.clear()
        self.access_key_input.clear()
        self.secret_key_input.clear()
        self.host_base_input.clear()
        self.email_input.clear()
        self.password_input.clear()
        self.profile_type_combo.setCurrentIndex(0)
        self.update_profile_form_visibility()
        self.profile_name_input.setFocus()

    def clear_form(self):
        self.start_new_profile(clear_selection=False)

    def update_profile_form_visibility(self):
        profile_type = self.profile_type_combo.currentData() or 's3'
        is_mega = profile_type == 'mega'

        def toggle_field(widget, visible):
            label = self.form_layout.labelForField(widget)
            if label:
                label.setVisible(visible)
            widget.setVisible(visible)

        toggle_field(self.access_key_input, not is_mega)
        toggle_field(self.secret_key_input, not is_mega)
        toggle_field(self.host_base_input, not is_mega)
        toggle_field(self.email_input, is_mega)
        toggle_field(self.password_input, is_mega)

    def tr(self, key):
        if self.translations:
            return self.translations.get(key)
        return key
