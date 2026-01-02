from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QProgressBar, QGroupBox, 
                             QMessageBox, QTextEdit)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from backup_manager import BackupManager
import time

class BackupWorker(QThread):
    progress_update = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, backup_manager, target_drive):
        super().__init__()
        self.manager = backup_manager
        self.target_drive = target_drive
        self.is_running = True

    def run(self):
        success, msg, process = self.manager.start_bare_metal_backup(self.target_drive)
        if not success:
            self.finished.emit(False, msg)
            return

        # Monitor process
        self.progress_update.emit("Backup iniciado... Esperando datos...")
        
        while process.poll() is None and self.is_running:
            # En un caso real, leeríamos stdout/stderr para actualizar barra de progreso
            # wbadmin es verboso en stderr
            line = process.stdout.readline()
            if line:
                self.progress_update.emit(line.strip())
            
            # También sondear get status
            status = self.manager.get_backup_status()
            if status:
                self.progress_update.emit(f"Estado: {status}")
            
            time.sleep(2)
            
        if process.returncode == 0:
            self.finished.emit(True, "Backup completado exitosamente.")
        else:
            stderr = process.stderr.read()
            self.finished.emit(False, f"Error en backup: {stderr}")

class RecoveryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.backup_manager = BackupManager()
        self.setup_ui()
        self.refresh_drives()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("🛡️ Proyecto Phoenix: Bare Metal Recovery")
        header_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #007acc;")
        layout.addWidget(header_label)
        
        # Sección 1: Prerrequisitos
        prereq_group = QGroupBox("1. Estado del Sistema")
        prereq_layout = QVBoxLayout()
        self.lbl_status = QLabel("Verificando requisitos...")
        prereq_layout.addWidget(self.lbl_status)
        prereq_group.setLayout(prereq_layout)
        layout.addWidget(prereq_group)
        
        # Sección 2: Configuración de Backup
        backup_group = QGroupBox("2. Backup de Sistema Completo (Local Staging)")
        backup_layout = QVBoxLayout()
        
        # Selector de Disco
        backup_layout.addWidget(QLabel("Selecciona Disco de Staging (Destino Temporal):"))
        self.drive_selector = QComboBox()
        backup_layout.addWidget(self.drive_selector)
        
        btn_refresh = QPushButton("🔄 Actualizar Discos")
        btn_refresh.clicked.connect(self.refresh_drives)
        backup_layout.addWidget(btn_refresh)
        
        # Botón de Inicio
        self.btn_start_backup = QPushButton("🚀 Iniciar Bare Metal Backup")
        self.btn_start_backup.setStyleSheet("background-color: #28a745; color: white; padding: 10px; font-weight: bold;")
        self.btn_start_backup.clicked.connect(self.start_backup)
        backup_layout.addWidget(self.btn_start_backup)
        
        backup_group.setLayout(backup_layout)
        layout.addWidget(backup_group)
        
        # Sección 3: Progreso y Logs
        log_group = QGroupBox("3. Progreso")
        log_layout = QVBoxLayout()
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas;")
        log_layout.addWidget(self.txt_log)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

    def refresh_drives(self):
        # 1. Chequear wbadmin
        ok, msg = self.backup_manager.check_prerequisites()
        if ok:
            self.lbl_status.setText(f"✅ {msg}")
            self.lbl_status.setStyleSheet("color: green")
            self.btn_start_backup.setEnabled(True)
        else:
            self.lbl_status.setText(f"❌ {msg}")
            self.lbl_status.setStyleSheet("color: red")
            self.btn_start_backup.setEnabled(False)
            return

        # 2. Listar discos
        self.drive_selector.clear()
        drives = self.backup_manager.get_available_drives()
        if not drives:
            self.drive_selector.addItem("No se encontraron discos secundarios aptos")
            self.btn_start_backup.setEnabled(False)
        else:
            for d in drives:
                self.drive_selector.addItem(d['label'], d['letter'])
            self.btn_start_backup.setEnabled(True)

    def start_backup(self):
        target_drive = self.drive_selector.currentData()
        if not target_drive:
            QMessageBox.warning(self, "Error", "Selecciona un disco de destino válido.")
            return
            
        confirm = QMessageBox.question(
            self, 
            "Confirmar Backup Bare Metal",
            f"⚠️ Se iniciará un backup completo del sistema (C:) hacia {target_drive}.\n\n"
            "Esto puede tardar varias horas y consumirá mucho espacio.\n"
            "¿Estás seguro?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self.btn_start_backup.setEnabled(False)
        self.txt_log.clear()
        self.log("Iniciando proceso de backup...")
        
        self.worker = BackupWorker(self.backup_manager, target_drive)
        self.worker.progress_update.connect(self.log)
        self.worker.finished.connect(self.on_backup_finished)
        self.worker.start()

    def log(self, message):
        self.txt_log.append(f"[{time.strftime('%H:%M:%S')}] {message}")
        # Scroll al final
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_backup_finished(self, success, message):
        self.btn_start_backup.setEnabled(True)
        if success:
            QMessageBox.information(self, "Backup Completado", message)
            self.log("✅ PROCESO FINALIZADO CON ÉXITO")
        else:
            QMessageBox.critical(self, "Error de Backup", message)
            self.log("❌ PROCESO FALLIDO")
