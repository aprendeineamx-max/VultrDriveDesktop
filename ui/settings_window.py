from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout, QHBoxLayout, QListWidget, QMessageBox
from PyQt6.QtCore import pyqtSignal

class SettingsWindow(QWidget):
    profiles_updated = pyqtSignal()

    def __init__(self, config_manager):
        super().__init__()
        self.config_manager = config_manager
        self.setWindowTitle("Manage Profiles")
        self.setGeometry(150, 150, 500, 400)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(20)

        # Left side: List of profiles
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Existing Profiles:"))
        self.profile_list = QListWidget()
        self.profile_list.itemClicked.connect(self.load_profile_details)
        left_layout.addWidget(self.profile_list)
        
        self.delete_button = QPushButton("Delete Selected Profile")
        self.delete_button.clicked.connect(self.delete_profile)
        left_layout.addWidget(self.delete_button)

        # Right side: Form to add/edit
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Add or Edit Profile:"))
        
        self.form_layout = QFormLayout()
        self.profile_name_input = QLineEdit()
        self.access_key_input = QLineEdit()
        self.secret_key_input = QLineEdit()
        self.host_base_input = QLineEdit()

        self.form_layout.addRow("Profile Name:", self.profile_name_input)
        self.form_layout.addRow("Access Key:", self.access_key_input)
        self.form_layout.addRow("Secret Key:", self.secret_key_input)
        self.form_layout.addRow("Hostname:", self.host_base_input)
        
        right_layout.addLayout(self.form_layout)

        self.save_button = QPushButton("Save Profile")
        self.save_button.clicked.connect(self.save_profile)
        right_layout.addWidget(self.save_button)
        right_layout.addStretch()

        self.layout.addLayout(left_layout, 1)
        self.layout.addLayout(right_layout, 2)

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
