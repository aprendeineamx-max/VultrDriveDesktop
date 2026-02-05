import os
import glob
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QTextEdit, QGroupBox, QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from file_watcher import RealTimeSync
from config_manager import ConfigManager
from rclone_manager import RcloneManager
import string

class GCPAdapter:
    """Adaptador para que RealTimeSync pueda usar el cliente GCP Storage"""
    def __init__(self, client):
        self.client = client
        self.last_error = None

    def upload_file(self, bucket_name, file_path, object_name=None):
        try:
            bucket = self.client.bucket(bucket_name)
            if object_name is None:
                object_name = os.path.basename(file_path)
            
            # Normalizar path para GCP (forward slashes)
            object_name = object_name.replace("\\", "/")
            
            blob = bucket.blob(object_name)
            blob.upload_from_filename(file_path)
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

class GCPSyncTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.client = None
        self.sync_engine = None
        self.is_running = False
        
        # Managers
        self.config_manager = ConfigManager()
        self.rclone_manager = RcloneManager(self.config_manager)
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 1. Configuración de Origen (Local)
        source_group = QGroupBox("1. Origen (Local)")
        source_layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        self.path_input = QLabel("No se ha seleccionado carpeta")
        self.path_input.setStyleSheet("background-color: #2c3e50; padding: 5px; border-radius: 4px; color: #ecf0f1;")
        self.browse_btn = QPushButton("📂 Seleccionar Carpeta")
        self.browse_btn.clicked.connect(self.browse_folder)
        
        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(self.browse_btn)
        source_layout.addLayout(path_layout)
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)

        # 2. Configuración de Destino (Remoto)
        dest_group = QGroupBox("2. Destino (GCP Bucket)")
        dest_layout = QVBoxLayout()
        
        self.bucket_combo = QComboBox()
        dest_layout.addWidget(self.bucket_combo)
        dest_group.setLayout(dest_layout)
        layout.addWidget(dest_group)

        # 3. Montaje de Unidad (Nueva Sección)
        mount_group = QGroupBox("3. Montar como Unidad Local (Opcional)")
        mount_layout = QHBoxLayout()
        
        mount_layout.addWidget(QLabel("Letra:"))
        self.drive_letter_combo = QComboBox()
        self.available_drives = [f"{d}" for d in string.ascii_uppercase if d not in ['C', 'D']] # Simple exclusion
        self.drive_letter_combo.addItems(self.available_drives)
        # Select Z by default if available
        if 'Z' in self.available_drives:
            self.drive_letter_combo.setCurrentText('Z')
            
        mount_layout.addWidget(self.drive_letter_combo)
        
        self.mount_btn = QPushButton("🔌 Montar Unidad")
        self.mount_btn.clicked.connect(self.mount_bucket)
        self.mount_btn.setStyleSheet("background-color: #8e44ad; color: white;")
        
        self.unmount_btn = QPushButton("⏏️ Desmontar")
        self.unmount_btn.clicked.connect(self.unmount_bucket)
        self.unmount_btn.setStyleSheet("background-color: #c0392b; color: white;")
        self.unmount_btn.setEnabled(False)
        
        self.explore_drive_btn = QPushButton("📂 Abrir")
        self.explore_drive_btn.clicked.connect(self.open_mounted_drive)
        self.explore_drive_btn.setEnabled(False)
        
        mount_layout.addWidget(self.mount_btn)
        mount_layout.addWidget(self.unmount_btn)
        mount_layout.addWidget(self.explore_drive_btn)
        
        mount_group.setLayout(mount_layout)
        layout.addWidget(mount_group)

        # 4. Control
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ Iniciar Sincronización Automática")
        self.start_btn.clicked.connect(self.toggle_sync)
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60; 
                color: white; 
                font-weight: bold; 
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
            }
        """)
        self.start_btn.setEnabled(False)
        control_layout.addWidget(self.start_btn)
        layout.addLayout(control_layout)

        # 4. Log de actividad
        log_group = QGroupBox("Actividad en Tiempo Real")
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas, monospace;")
        log_layout.addWidget(self.log_area)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)

    def set_client(self, client):
        """Recibe el cliente autenticado desde GCPTab"""
        self.client = client
        self.refresh_buckets()

    def refresh_buckets(self):
        if not self.client: return
        
        # Si ya estamos recibiendo actualizaciones desde el Tab principal, 
        # quizás no necesitemos llamar a list_buckets aquí, pero lo mantenemos por si acaso
        # se llama manualmente.
        try:
            buckets = list(self.client.list_buckets())
            self.update_buckets_from_list(buckets)
        except Exception as e:
            self.log(f"Error listando buckets: {e}")

    def update_buckets_from_list(self, buckets):
        """Actualiza el combobox con una lista de buckets ya obtenida"""
        current_selection = self.bucket_combo.currentData()
        self.bucket_combo.clear()
        
        for bucket in buckets:
            self.bucket_combo.addItem(f"📦 {bucket.name}", bucket.name)
            
        # Restaurar selección si es posible
        if current_selection:
            index = self.bucket_combo.findData(current_selection)
            if index >= 0:
                self.bucket_combo.setCurrentIndex(index)
        
        if self.bucket_combo.count() > 0:
            self.check_ready_state()

    def browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta para Sincronizar")
        if path:
            self.path_input.setText(path)
            self.check_ready_state()

    def check_ready_state(self):
        has_path = os.path.isdir(self.path_input.text())
        has_bucket = self.bucket_combo.count() > 0
        self.start_btn.setEnabled(has_path and has_bucket)

    def mount_bucket(self):
        bucket_name = self.bucket_combo.currentData()
        drive_letter = self.drive_letter_combo.currentText()
        
        if not bucket_name:
            QMessageBox.warning(self, "Error", "Selecciona un bucket primero")
            return

        # Nombre del perfil en rclone
        rclone_remote_name = "gcp_current"
        
        # 1. Asegurar credenciales
        keys_dir = os.path.join(os.getcwd(), "Claves GCP")
        json_files = glob.glob(os.path.join(keys_dir, "*.json"))
        
        if not json_files:
             # Intentar buscarlas si no están en la ruta estándar (aunque GCP tab ya lo hace)
             QMessageBox.critical(self, "Error", "No se encontró ningún archivo JSON en 'Claves GCP'.")
             return
        
        creds_path = json_files[0]

        # 2. Configurar Rclone
        self.log(f"Configurando perfil Rclone '{rclone_remote_name}'...")
        self.rclone_manager.create_gcp_config(rclone_remote_name, creds_path)
        
        # 3. Montar
        self.log(f"Intentando montar bucket '{bucket_name}' en {drive_letter}: ...")
        self.mount_btn.setEnabled(False)
        self.mount_btn.setText("Montando...")
        
        # Ejecutar montaje (puede tardar un poco)
        QTimer.singleShot(100, lambda: self._perform_mount(rclone_remote_name, bucket_name, drive_letter))

    def _perform_mount(self, remote_name, bucket_name, drive_letter):
        # NOTA: mount_drive espera profile_name (section config), drive_letter sin ':', bucket_name opcional
        success, msg, process = self.rclone_manager.mount_drive(
            remote_name, 
            drive_letter, 
            bucket_name=bucket_name
        )
        
        if success:
            self.log(f"✅ Éxito: {msg}")
            self.mount_btn.setText("Montado")
            self.mount_btn.setEnabled(False)
            self.unmount_btn.setEnabled(True)
            self.explore_drive_btn.setEnabled(True)
            self.drive_letter_combo.setEnabled(False)
            self.bucket_combo.setEnabled(False)
        else:
            self.log(f"❌ Error al montar: {msg}")
            self.mount_btn.setText("🔌 Montar Unidad")
            self.mount_btn.setEnabled(True)
            QMessageBox.critical(self, "Error de Montaje", msg)

    def unmount_bucket(self):
        drive_letter = self.drive_letter_combo.currentText()
        self.log(f"Desmontando unidad {drive_letter}: ...")
        
        success, msg = self.rclone_manager.unmount_drive(drive_letter)
        
        if success:
            self.log(f"Unidad desmontada.")
            self.mount_btn.setText("🔌 Montar Unidad")
            self.mount_btn.setEnabled(True)
            self.unmount_btn.setEnabled(False)
            self.explore_drive_btn.setEnabled(False)
            self.drive_letter_combo.setEnabled(True)
            self.bucket_combo.setEnabled(True)
        else:
            self.log(f"Error al desmontar: {msg}")
            QMessageBox.warning(self, "Error", msg)

    def open_mounted_drive(self):
        drive_letter = self.drive_letter_combo.currentText()
        drive_path = f"{drive_letter}:\\"
        if os.path.exists(drive_path):
            os.startfile(drive_path)
        else:
             QMessageBox.warning(self, "Error", "La unidad no parece estar disponible")

    def toggle_sync(self):
        if not self.is_running:
            self.start_sync()
        else:
            self.stop_sync()

    def start_sync(self):
        folder = self.path_input.text()
        bucket_name = self.bucket_combo.currentData()
        
        if not folder or not os.path.isdir(folder):
            self.log("Error: Carpeta inválida")
            return

        if not self.client:
            self.log("Error: No hay conexión con GCP")
            return

        self.log(f"Iniciando monitorización en: {folder}")
        self.log(f"Destino: Bucket '{bucket_name}'")

        adapter = GCPAdapter(self.client)
        self.sync_engine = RealTimeSync(
            s3_handler=adapter, 
            bucket_name=bucket_name, 
            watch_directory=folder,
            callback=self.log
        )

        success, msg = self.sync_engine.start()
        if success:
            self.is_running = True
            self.start_btn.setText("⏹ Detener Sincronización")
            self.start_btn.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
            self.browse_btn.setEnabled(False)
            self.bucket_combo.setEnabled(False)
            self.log("✅ Sistema de sincronización activo. Esperando cambios...")
        else:
            self.log(f"❌ Error al iniciar: {msg}")

    def stop_sync(self):
        if self.sync_engine:
            self.sync_engine.stop()
            self.is_running = False
            self.start_btn.setText("▶ Iniciar Sincronización")
            self.start_btn.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
            self.browse_btn.setEnabled(True)
            self.bucket_combo.setEnabled(True)
            self.log("⏹ Sincronización detenida.")

    def log(self, message):
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_area.append(f"[{timestamp}] {message}")
        # Auto-scroll
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
