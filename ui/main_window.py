from PyQt6.QtWidgets import (QMainWindow, QVBoxLayout, QWidget, QPushButton, QComboBox, 
                             QLabel, QFileDialog, QStatusBar, QHBoxLayout, QGroupBox, 
                             QMessageBox, QLineEdit, QTabWidget, QTextEdit, QProgressBar,
                             QMenu)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction
from config_manager import ConfigManager
from s3_handler import S3Handler
from ui.settings_window import SettingsWindow
from rclone_manager import RcloneManager
from file_watcher import RealTimeSync
import os

class UploadThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, s3_handler, bucket_name, file_path):
        super().__init__()
        self.s3_handler = s3_handler
        self.bucket_name = bucket_name
        self.file_path = file_path

    def run(self):
        try:
            success = self.s3_handler.upload_file(self.bucket_name, self.file_path)
            if success:
                self.finished.emit(True, "Upload completed successfully")
            else:
                self.finished.emit(False, "Upload failed")
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")


class BackupThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

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
                self.finished.emit(False, "No files found in folder")
                return

            for i, file_path in enumerate(files):
                relative_path = os.path.relpath(file_path, self.folder_path)
                self.progress.emit(int((i / total) * 100), f"Uploading {relative_path}")
                self.s3_handler.upload_file(self.bucket_name, file_path, relative_path)
            
            self.finished.emit(True, f"Successfully backed up {total} files")
        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")


class MainWindow(QMainWindow):
    def __init__(self, theme_manager=None, translations=None, save_preferences_callback=None):
        super().__init__()
        
        # Store references to theme manager and translations
        self.theme_manager = theme_manager
        self.translations = translations
        self.save_preferences_callback = save_preferences_callback
        
        # Initialize UI
        self.setWindowTitle(self.tr("window_title"))
        self.setGeometry(100, 100, 700, 550)

        self.config_manager = ConfigManager()
        self.s3_handler = None
        self.rclone_manager = RcloneManager(self.config_manager)
        self.real_time_sync = None
        self.upload_thread = None
        self.backup_thread = None

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

        if self.profile_selector.count() > 0:
            self.load_profile(self.profile_selector.currentText())
        else:
            self.statusBar().showMessage(self.tr("no_profiles_found"))

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
        
        top_layout.addWidget(language_label)
        top_layout.addWidget(self.language_button)
        top_layout.addStretch()
        top_layout.addWidget(self.theme_button)
        
        self.main_layout.addLayout(top_layout)

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
                "Language Changed", 
                f"Language changed to {self.translations.get_available_languages()[language_code]}.\n\nPlease restart the application to see all changes."
            )
            
            # Update button text
            self.update_language_button_text()

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
        layout = QVBoxLayout(self.main_tab)
        layout.setSpacing(15)

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
        self.refresh_buckets_btn.clicked.connect(self.refresh_buckets)
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

        # Settings button
        settings_layout = QHBoxLayout()
        self.settings_button = QPushButton(self.tr("manage_profiles"))
        self.settings_button.clicked.connect(self.open_settings)
        settings_layout.addStretch()
        settings_layout.addWidget(self.settings_button)
        layout.addLayout(settings_layout)

        layout.addStretch()

    def setup_mount_tab(self):
        layout = QVBoxLayout(self.mount_tab)
        layout.setSpacing(15)

        # Mount configuration
        mount_group = QGroupBox(self.tr("mount_configuration"))
        mount_layout = QVBoxLayout()

        drive_letter_layout = QHBoxLayout()
        drive_letter_layout.addWidget(QLabel(self.tr("drive_letter")))
        self.drive_letter_input = QComboBox()
        available_drives = [chr(i) for i in range(ord('V'), ord('Z')+1)]
        self.drive_letter_input.addItems(available_drives)
        drive_letter_layout.addWidget(self.drive_letter_input)
        drive_letter_layout.addStretch()
        mount_layout.addLayout(drive_letter_layout)

        mount_group.setLayout(mount_layout)
        layout.addWidget(mount_group)

        # Mount actions
        actions_group = QGroupBox(self.tr("drive_actions"))
        actions_layout = QVBoxLayout()

        self.mount_status_label = QLabel(self.tr("status_not_mounted"))
        actions_layout.addWidget(self.mount_status_label)

        buttons_layout = QHBoxLayout()
        self.mount_button = QPushButton(self.tr("mount_drive"))
        self.mount_button.clicked.connect(self.mount_drive)
        self.unmount_button = QPushButton(self.tr("unmount_drive"))
        self.unmount_button.clicked.connect(self.unmount_drive)
        self.unmount_button.setEnabled(False)
        buttons_layout.addWidget(self.mount_button)
        buttons_layout.addWidget(self.unmount_button)

        actions_layout.addLayout(buttons_layout)
        actions_group.setLayout(actions_layout)
        layout.addWidget(actions_group)

        # Info text
        info_group = QGroupBox(self.tr("information"))
        info_layout = QVBoxLayout()
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(150)
        info_text.setPlainText(self.tr("mount_info").replace('\\n', '\n'))
        info_layout.addWidget(info_text)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()

    def setup_sync_tab(self):
        layout = QVBoxLayout(self.sync_tab)
        layout.setSpacing(15)

        # Folder selection
        folder_group = QGroupBox("Folder to Monitor")
        folder_layout = QVBoxLayout()

        folder_select_layout = QHBoxLayout()
        self.sync_folder_label = QLabel("No folder selected")
        self.sync_folder_label.setWordWrap(True)
        self.sync_folder_btn = QPushButton("📁 Select Folder")
        self.sync_folder_btn.clicked.connect(self.select_sync_folder)
        folder_select_layout.addWidget(self.sync_folder_label, 1)
        folder_select_layout.addWidget(self.sync_folder_btn)
        folder_layout.addLayout(folder_select_layout)

        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)

        # Sync status and controls
        sync_group = QGroupBox("Synchronization Control")
        sync_layout = QVBoxLayout()

        self.sync_status_label = QLabel("Status: Stopped")
        sync_layout.addWidget(self.sync_status_label)

        buttons_layout = QHBoxLayout()
        self.start_sync_btn = QPushButton("▶️ Start Real-Time Sync")
        self.start_sync_btn.clicked.connect(self.start_real_time_sync)
        self.stop_sync_btn = QPushButton("⏹️ Stop Sync")
        self.stop_sync_btn.clicked.connect(self.stop_real_time_sync)
        self.stop_sync_btn.setEnabled(False)
        buttons_layout.addWidget(self.start_sync_btn)
        buttons_layout.addWidget(self.stop_sync_btn)

        sync_layout.addLayout(buttons_layout)
        sync_group.setLayout(sync_layout)
        layout.addWidget(sync_group)

        # Activity log
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout()

        self.sync_log = QTextEdit()
        self.sync_log.setReadOnly(True)
        self.sync_log.setMaximumHeight(200)
        self.sync_log.setPlainText("Real-time sync not started yet.\n")
        log_layout.addWidget(self.sync_log)

        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(lambda: self.sync_log.clear())
        log_layout.addWidget(clear_log_btn)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Info text
        info_group = QGroupBox(self.tr("information"))
        info_layout = QVBoxLayout()
        info_text = QTextEdit()
        info_text.setReadOnly(True)
        info_text.setMaximumHeight(100)
        info_text.setPlainText(self.tr("sync_info"))
        info_layout.addWidget(info_text)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        layout.addStretch()

    def select_sync_folder(self):
        """Select folder for real-time synchronization"""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Monitor")
        if folder:
            self.sync_folder_label.setText(folder)
            self.sync_folder_label.setProperty('folder_path', folder)

    def start_real_time_sync(self):
        """Start real-time synchronization"""
        if not self.s3_handler:
            QMessageBox.warning(self, self.tr("warning"), self.tr("select_profile_first"))
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, self.tr("warning"), "Por favor selecciona un bucket primero.")
            return

        folder = self.sync_folder_label.property('folder_path')
        if not folder:
            QMessageBox.warning(self, self.tr("warning"), "Por favor selecciona una carpeta para monitorear.")
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
            self.sync_status_label.setText(f"{self.tr('status')}: Monitoreando {folder}")
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
                self.sync_status_label.setText(f"{self.tr('status')}: {self.tr('status_stopped')}")
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
        layout = QVBoxLayout(self.advanced_tab)
        layout.setSpacing(15)

        # Warning label
        warning_label = QLabel(f"⚠️ {self.tr('advanced_warning')}")
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

    def refresh_buckets(self):
        if not self.s3_handler:
            self.statusBar().showMessage(self.tr("select_profile_first"))
            return

        self.bucket_selector.clear()
        buckets = self.s3_handler.list_buckets()
        if buckets:
            self.bucket_selector.addItems(buckets)
            self.statusBar().showMessage(self.tr("buckets_found").format(len(buckets)))
        else:
            self.statusBar().showMessage(self.tr("no_buckets_found"))

    def load_profile(self, profile_name):
        if not profile_name:
            self.s3_handler = None
            self.statusBar().showMessage(self.tr("no_profile_selected"))
            return
            
        config = self.config_manager.get_config(profile_name)
        if config:
            self.s3_handler = S3Handler(config['access_key'], config['secret_key'], config['host_base'])
            self.statusBar().showMessage(self.tr("profile_loaded").format(profile_name))
            self.refresh_buckets()

    def upload_file(self):
        if not self.s3_handler:
            QMessageBox.warning(self, "Warning", "Please select a profile first.")
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, "Warning", "No buckets available. Please create a bucket first.")
            return
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File to Upload")
        if file_path:
            bucket_name = self.bucket_selector.currentText()
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.statusBar().showMessage(f"Uploading {os.path.basename(file_path)}...")
            
            self.upload_thread = UploadThread(self.s3_handler, bucket_name, file_path)
            self.upload_thread.finished.connect(self.upload_finished)
            self.upload_thread.start()

    def upload_finished(self, success, message):
        self.progress_bar.setVisible(False)
        if success:
            QMessageBox.information(self, "Success", message)
            self.statusBar().showMessage("Upload completed.", 5000)
        else:
            QMessageBox.critical(self, "Error", message)
            self.statusBar().showMessage("Upload failed.", 5000)

    def full_backup(self):
        if not self.s3_handler:
            QMessageBox.warning(self, "Warning", "Please select a profile first.")
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, "Warning", "No buckets available. Please create a bucket first.")
            return
        
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory to Backup")
        if dir_path:
            bucket_name = self.bucket_selector.currentText()
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.statusBar().showMessage(f"Starting backup of {dir_path}...")
            
            self.backup_thread = BackupThread(self.s3_handler, bucket_name, dir_path)
            self.backup_thread.progress.connect(self.backup_progress)
            self.backup_thread.finished.connect(self.backup_finished)
            self.backup_thread.start()

    def backup_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.statusBar().showMessage(message)

    def backup_finished(self, success, message):
        self.progress_bar.setVisible(False)
        if success:
            QMessageBox.information(self, "Success", message)
            self.statusBar().showMessage("Backup completed.", 5000)
        else:
            QMessageBox.critical(self, "Error", message)
            self.statusBar().showMessage("Backup failed.", 5000)

    def mount_drive(self):
        if not self.profile_selector.currentText():
            QMessageBox.warning(self, "Warning", "Please select a profile first.")
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, "Warning", "Please select a bucket to mount.")
            return

        drive_letter = self.drive_letter_input.currentText()
        profile_name = self.profile_selector.currentText()
        bucket_name = self.bucket_selector.currentText()

        self.statusBar().showMessage(f"Mounting {bucket_name} on {drive_letter}:...")
        success, message = self.rclone_manager.mount_drive(profile_name, drive_letter, bucket_name)

        if success:
            QMessageBox.information(self, "Success", message)
            self.mount_status_label.setText(f"Status: Mounted on {drive_letter}:")
            self.mount_button.setEnabled(False)
            self.unmount_button.setEnabled(True)
            self.statusBar().showMessage(f"Drive mounted on {drive_letter}:", 5000)
        else:
            # Mensaje de error mejorado con instrucciones
            error_msg = message
            if "WinFsp" in message or "not supported" in message:
                error_msg += "\n\n💡 Solución:\n"
                error_msg += "1. WinFsp es requerido para montar unidades\n"
                error_msg += "2. Ejecuta: .\\instalar_winfsp.ps1\n"
                error_msg += "3. O descarga desde: https://winfsp.dev/rel/"
            
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error de Montaje")
            msg_box.setText("No se pudo montar la unidad")
            msg_box.setInformativeText(error_msg)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
            self.statusBar().showMessage("Mount failed.", 5000)

    def unmount_drive(self):
        drive_letter = self.drive_letter_input.currentText()
        self.statusBar().showMessage(f"Unmounting drive {drive_letter}:...")
        
        success, message = self.rclone_manager.unmount_drive(drive_letter)

        if success:
            QMessageBox.information(self, "Success", message)
            self.mount_status_label.setText("Status: Not mounted")
            self.mount_button.setEnabled(True)
            self.unmount_button.setEnabled(False)
            self.statusBar().showMessage("Drive unmounted.", 5000)
        else:
            QMessageBox.critical(self, "Error", message)
            self.statusBar().showMessage("Unmount failed.", 5000)

    def format_bucket(self):
        if not self.s3_handler:
            QMessageBox.warning(self, "Warning", "Please select a profile first.")
            return

        if self.bucket_selector.count() == 0:
            QMessageBox.warning(self, "Warning", "No buckets available.")
            return

        bucket_name = self.bucket_selector.currentText()

        reply = QMessageBox.question(
            self, 
            'CONFIRM BUCKET FORMAT', 
            f"⚠️ WARNING ⚠️\n\n"
            f"You are about to DELETE ALL FILES in the bucket:\n'{bucket_name}'\n\n"
            f"This action is PERMANENT and CANNOT be undone!\n\n"
            f"Are you absolutely sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Double confirmation
            confirm_text, ok = QMessageBox.getText(
                self,
                "Final Confirmation",
                f"Type the bucket name '{bucket_name}' to confirm deletion:"
            )

            if ok and confirm_text == bucket_name:
                self.statusBar().showMessage(f"Formatting bucket {bucket_name}...")
                success = self.s3_handler.delete_all_objects(bucket_name)
                
                if success:
                    QMessageBox.information(self, "Success", f"Bucket '{bucket_name}' has been formatted.")
                    self.statusBar().showMessage("Bucket formatted.", 5000)
                else:
                    QMessageBox.critical(self, "Error", "Failed to format bucket.")
                    self.statusBar().showMessage("Format failed.", 5000)
            else:
                self.statusBar().showMessage("Format cancelled.", 3000)

    def open_settings(self):
        self.settings_window = SettingsWindow(self.config_manager)
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

    def closeEvent(self, event):
        """Handle application close event"""
        # Stop real-time sync if running
        if self.real_time_sync and self.real_time_sync.is_running():
            reply = QMessageBox.question(
                self,
                'Sync Still Running',
                'Real-time sync is still active. Do you want to stop it before closing?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.real_time_sync.stop()

        # Unmount drive if mounted
        if self.rclone_manager.is_mounted():
            reply = QMessageBox.question(
                self,
                'Drive Still Mounted',
                'A drive is still mounted. Do you want to unmount it before closing?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.rclone_manager.unmount_drive(self.drive_letter_input.currentText())

        event.accept()


