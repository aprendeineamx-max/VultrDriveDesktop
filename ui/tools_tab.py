from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QComboBox, QFileDialog, QProgressBar, QCheckBox, QGroupBox,
    QTextEdit, QMessageBox, QSpinBox, QSplitter, QFrame, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent
from ui.plan_editor import PlanEditorDialog
import os

class SmartUploadWorker(QThread):
    progress_update = pyqtSignal(str)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, rclone_manager, profile_name, source_folder, bucket_name, do_zip, do_sync, reuse_zip, **kwargs):
        super().__init__()
        self.rclone_manager = rclone_manager
        self.profile_name = profile_name
        self.source_folder = source_folder
        self.bucket_name = bucket_name
        self.do_zip = do_zip
        self.do_sync = do_sync
        self.reuse_zip = reuse_zip
        self.extra_params = kwargs  # transfers, checkers, tpslimit, burst ...
        self.is_running = True

    def run(self):
        try:
            # 1. Backup ZIP (Si está activado)
            if self.do_zip:
                zip_path = None
                
                # Check Reuso
                if self.reuse_zip:
                    self.status_update.emit("🔍 Buscando ZIP existente para reutilizar...")
                    try:
                        temp_dir = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), 'VultrDrive_Backups')
                        folder_name = os.path.basename(self.source_folder)
                        # Patrón: FolderName_YYYYMMDD_HHMMSS.zip
                        candidates = []
                        if os.path.exists(temp_dir):
                            for f in os.listdir(temp_dir):
                                if f.startswith(f"{folder_name}_") and f.endswith(".zip"):
                                    candidates.append(os.path.join(temp_dir, f))
                        
                        if candidates:
                            # Ordenar por fecha de modificación (el más reciente)
                            candidates.sort(key=os.path.getmtime, reverse=True)
                            zip_path = candidates[0]
                            self.status_update.emit(f"♻️ ZIP Existente encontrado: {os.path.basename(zip_path)}")
                        else:
                            self.status_update.emit("⚠️ No se encontró ZIP previo, se creará uno nuevo.")
                    except Exception as e:
                        self.status_update.emit(f"⚠️ Error buscando ZIP: {e}")

                if not zip_path:
                    self.status_update.emit("📦 Comprimiendo carpeta (Fase 1/2)...")
                    # Pasamos kwargs por si en el futuro compress_folder usa algo (hoy no)
                    success, zip_path = self.rclone_manager.compress_folder(self.source_folder)
                    
                    if not success:
                        self.finished.emit(False, f"Error al comprimir: {zip_path}")
                        return

                self.status_update.emit(f"🚀 Subiendo Backup ZIP: {os.path.basename(zip_path)}...")
                # FIXED: Pasar extra_params (transfers, etc) a upload_file para activar Ultra Mode
                success, msg = self.rclone_manager.upload_file(
                    self.profile_name, 
                    zip_path, 
                    self.bucket_name,
                    progress_callback=lambda p: self.progress_update.emit(f"[ZIP] {p}"),
                    **self.extra_params
                )
                
                # Eliminar temporal (Desactivado para preservar ZIP si falla o si usuario quiere conservarlo)
                # El usuario pidió "no pierdas el zip que ya está"
                # Podemos implementar una limpieza inteligente luego, por ahora lo dejamos.
                # try:
                #     os.remove(zip_path)
                # except:
                #     pass

                if not success:
                    self.finished.emit(False, f"Error al subir ZIP: {msg}")
                    return

            # 2. Sincronización Paralela (Si está activado)
            if self.do_sync:
                transfers = self.extra_params.get('transfers', '320')
                self.status_update.emit(f"⚡ Iniciando Sincronización Paralela ({transfers} hilos)...")
                success, msg = self.rclone_manager.sync_folder_parallel(
                    self.profile_name,
                    self.source_folder,
                    self.bucket_name,
                    progress_callback=lambda p: self.progress_update.emit(f"[SYNC] {p}"),
                    **self.extra_params
                )
                
                if not success:
                    self.finished.emit(False, f"Error en sincronización: {msg}")
                    return

            self.finished.emit(True, "✅ Operación completada exitosamente")

        except Exception as e:
            self.finished.emit(False, str(e))

    def stop(self):
        self.is_running = False

class HelpEventFilter(QObject):
    def __init__(self, help_callback, help_text):
        super().__init__()
        self.help_callback = help_callback
        self.help_text = help_text

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn or event.type() == QEvent.Type.Enter:
            self.help_callback(self.help_text)
        return False

class ToolsTab(QWidget):
    def __init__(self, rclone_manager, config_manager, parent=None):
        super().__init__(parent)
        self.rclone_manager = rclone_manager
        self.config_manager = config_manager
        self.worker = None
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter principal
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # === PANEL IZQUIERDO: CONTROLES ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(10, 10, 10, 10)

        # Header
        header_layout = QHBoxLayout()
        header_label = QLabel("🚀 Herramientas Avanzadas v2")
        header_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #3498db;")
        header_layout.addWidget(header_label)
        
        # Botón para abrir backups (NUEVO)
        btn_open_backups = QPushButton("📂 Abrir Backups")
        btn_open_backups.setToolTip("Abrir carpeta donde se guardan los ZIP temporales")
        btn_open_backups.clicked.connect(self.open_backups_folder)
        btn_open_backups.setStyleSheet("""
            QPushButton { background-color: #f39c12; color: white; border-radius: 4px; padding: 5px; }
            QPushButton:hover { background-color: #d35400; }
        """)
        header_layout.addStretch()
        header_layout.addWidget(btn_open_backups)
        
        left_layout.addLayout(header_layout)

        # 1. Selección de Origen y Destino
        config_group = QGroupBox("1. Origen y Destino")
        config_layout = QVBoxLayout()
        
        # Carpeta
        folder_layout = QHBoxLayout()
        self.folder_path = QTextEdit()
        self.folder_path.setPlaceholderText("Selecciona una carpeta...")
        self.folder_path.setMaximumHeight(35)
        self.folder_path.setReadOnly(True)
        browse_btn = QPushButton("📂 Examinar")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(self.folder_path)
        folder_layout.addWidget(browse_btn)
        config_layout.addLayout(folder_layout)

        # Bucket
        self.bucket_selector = QComboBox()
        config_layout.addWidget(QLabel("Bucket Destino:"))
        config_layout.addWidget(self.bucket_selector)
        config_group.setLayout(config_layout)
        left_layout.addWidget(config_group)

        # 2. Modos Opcionales
        modes_group = QGroupBox("2. Estrategia de Subida")
        modes_layout = QVBoxLayout()
        self.chk_zip = QCheckBox("📦 Backup Comprimido (.zip)")
        self.chk_zip.setChecked(True)
        
        self.chk_reuse_zip = QCheckBox("♻️ Usar ZIP existente si se encuentra")
        self.chk_reuse_zip.setToolTip("Si existe un archivo FolderName_*.zip reciente en la carpeta de backups, se usará en lugar de recomprimir.")
        self.chk_reuse_zip.setChecked(True)
        self.chk_reuse_zip.setStyleSheet("margin-left: 20px; color: #f39c12;")
        # Deshabilitar si chk_zip no está marcado
        self.chk_zip.toggled.connect(self.chk_reuse_zip.setEnabled)
        
        self.chk_sync = QCheckBox("⚡ Video Sincronización (Carpetas)")
        self.chk_sync.setChecked(True)
        
        modes_layout.addWidget(self.chk_zip)
        modes_layout.addWidget(self.chk_reuse_zip)
        modes_layout.addWidget(self.chk_sync)
        modes_group.setLayout(modes_layout)
        left_layout.addWidget(modes_group)

        # 3. Configuración de Planes (SISTEMA NUEVO)
        adv_group = QGroupBox("3. Plan de Rendimiento")
        adv_layout = QVBoxLayout()
        
        # Selector y Botón Editar
        plan_control_layout = QHBoxLayout()
        self.plan_selector = QComboBox()
        self.plan_selector.currentIndexChanged.connect(self.on_plan_changed)
        
        btn_edit_plans = QPushButton("⚙️ Editar Planes")
        btn_edit_plans.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit_plans.clicked.connect(self.open_plan_editor)
        
        plan_control_layout.addWidget(QLabel("Perfil Activo:"))
        plan_control_layout.addWidget(self.plan_selector, 1)
        plan_control_layout.addWidget(btn_edit_plans)
        adv_layout.addLayout(plan_control_layout)
        
        # Info del Plan
        self.plan_info_label = QLabel("Cargando detalles...")
        self.plan_info_label.setStyleSheet("color: #7f8c8d; font-style: italic; margin-top: 5px;")
        self.plan_info_label.setWordWrap(True)
        adv_layout.addWidget(self.plan_info_label)

        adv_group.setLayout(adv_layout)
        left_layout.addWidget(adv_group)

        # Progreso y Acción
        self.status_label = QLabel("Listo.")
        left_layout.addWidget(self.status_label)
        
        self.progress_log = QTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas; font-size: 9pt;")
        left_layout.addWidget(self.progress_log)

        self.start_btn = QPushButton("🚀 INICIAR OPERACIÓN")
        self.start_btn.setMinimumHeight(45)
        self.start_btn.setStyleSheet("""
            QPushButton { background-color: #27ae60; color: white; font-weight: bold; font-size: 11pt; border-radius: 4px; }
            QPushButton:hover { background-color: #2ecc71; }
            QPushButton:disabled { background-color: #555; }
        """)
        self.start_btn.clicked.connect(self.start_upload)
        left_layout.addWidget(self.start_btn)

        self.splitter.addWidget(left_widget)

        # === PANEL DERECHO: DOCUMENTACIÓN ===
        self.right_widget = QWidget()
        right_layout = QVBoxLayout(self.right_widget)
        right_layout.setContentsMargins(10, 10, 10, 10)

        # Toggle Button Header
        docs_header_layout = QHBoxLayout()
        docs_label = QLabel("📖 Documentación")
        docs_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        
        self.hide_docs_btn = QPushButton("Ocultar ➡")
        self.hide_docs_btn.setFlat(True)
        self.hide_docs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide_docs_btn.clicked.connect(self.toggle_docs)

        docs_header_layout.addWidget(docs_label)
        docs_header_layout.addStretch()
        docs_header_layout.addWidget(self.hide_docs_btn)
        right_layout.addLayout(docs_header_layout)

        self.help_text_view = QTextEdit()
        self.help_text_view.setReadOnly(True)
        self.help_text_view.setStyleSheet("background-color: #f0f0f0; color: #333; padding: 10px; border: none;")
        self.help_text_view.setHtml(self.get_intro_help())
        right_layout.addWidget(self.help_text_view)

        self.splitter.addWidget(self.right_widget)
        
        # Ajustar tamaños iniciales (70% - 30%)
        self.splitter.setSizes([700, 300])

        # === INICIALIZACIÓN ===
        self.install_help_filters()
        self.load_plans_to_combo()

        # Botón flotante para mostrar ayuda
        self.show_docs_btn = QPushButton("⬅ Mostrar Ayuda")
        self.show_docs_btn.setFlat(True)
        self.show_docs_btn.clicked.connect(self.toggle_docs)
        self.show_docs_btn.setVisible(False)
        left_layout.insertWidget(0, self.show_docs_btn)

    def load_plans_to_combo(self):
        self.plan_selector.blockSignals(True)
        self.plan_selector.clear()
        
        # Obtener planes (esto creará defaults si no existen)
        plans = self.config_manager.get_plans()
        plan_names = list(plans.keys())
        self.plan_selector.addItems(plan_names)
        
        # Seleccionar activo
        active = self.config_manager.get_active_plan()
        idx = self.plan_selector.findText(active)
        if idx >= 0:
            self.plan_selector.setCurrentIndex(idx)
        
        self.plan_selector.blockSignals(False)
        self.on_plan_changed()

    def on_plan_changed(self):
        plan_name = self.plan_selector.currentText()
        if not plan_name:
            return
            
        # Guardar como activo en config
        self.config_manager.set_active_plan(plan_name)
        
        # Mostrar resumen
        plan = self.config_manager.get_plan(plan_name)
        if plan:
            t = plan.get('transfers', 'N/A')
            c = plan.get('checkers', 'N/A')
            fps = plan.get('tpslimit', '0')
            self.plan_info_label.setText(
                f"Configuración: {t} Transfers | {c} Checkers | {fps} TPS Limit\n"
                f"Saturará tu red para máxima velocidad." if int(t) > 100 else 
                f"Modo equilibrado/seguro."
            )
        else:
            self.plan_info_label.setText("Error al cargar plan.")

    def open_plan_editor(self):
        dialog = PlanEditorDialog(self.config_manager, self)
        dialog.exec()
        # Recargar planes al cerrar
        self.load_plans_to_combo()

    def install_help_filters(self):
        helps = {
            self.chk_zip: "<h3>📦 Backup Comprimido (.zip)</h3><p>Crea un archivo ZIP de toda la carpeta antes de subirlo. Útil para históricos.</p>",
            self.chk_sync: "<h3>⚡ Video Sincronización</h3><p>Sube archivo a archivo con alto paralelismo.</p>",
            self.plan_selector: "<h3>⚙️ Perfil de Rendimiento</h3><p>Selecciona la agresividad de la subida.</p><ul><li><b>Ultra</b>: 320 hilos. Máxima velocidad.</li><li><b>Balanced</b>: 32 hilos. Uso normal.</li><li><b>Stability</b>: 4 hilos. Redes lentas.</li></ul>",
            self.bucket_selector: "<h3>🪣 Bucket Destino</h3><p>Dónde se guardarán los archivos en Vultr.</p>",
            self.folder_path: "<h3>📂 Carpeta Local</h3><p>Archivos a subir.</p>"
        }

        for widget, text in helps.items():
            filter_obj = HelpEventFilter(self.set_help_text, text)
            widget.installEventFilter(filter_obj)

    def open_backups_folder(self):
        """Abre la carpeta de backups temporales en el explorador"""
        temp_dir = os.path.join(os.environ.get('TEMP', os.path.expanduser('~')), 'VultrDrive_Backups')
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)
            
        try:
            os.startfile(temp_dir)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir la carpeta: {e}")
            setattr(widget, "_help_filter", filter_obj)

    def set_help_text(self, text):
        if self.right_widget.isVisible():
            self.help_text_view.setHtml(text)

    def get_intro_help(self):
        return """
        <h3>👋 Sistema de Planes</h3>
        <p>Configura el rendimiento exacto que necesitas.</p>
        <p>Usa el botón <b>⚙️ Editar Planes</b> para personalizar Transfers, Tps y más.</p>
        """

    def toggle_docs(self):
        visible = self.right_widget.isVisible()
        self.right_widget.setVisible(not visible)
        self.show_docs_btn.setVisible(visible)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta a Subir")
        if folder:
            self.folder_path.setText(folder)

    def set_buckets(self, buckets):
        current = self.bucket_selector.currentText()
        self.bucket_selector.clear()
        self.bucket_selector.addItems(buckets)
        if current in buckets:
            self.bucket_selector.setCurrentText(current)

    def start_upload(self):
        folder = self.folder_path.toPlainText()
        bucket = self.bucket_selector.currentText()
        profile = self.config_manager.get_active_profile()

        if not folder or not bucket or not profile:
            QMessageBox.warning(self, "Error", "Faltan datos (Carpeta, Bucket o Perfil).")
            return
        
        do_zip = self.chk_zip.isChecked()
        do_sync = self.chk_sync.isChecked()
        reuse_zip = self.chk_reuse_zip.isChecked()

        if not do_zip and not do_sync:
            QMessageBox.warning(self, "Error", "Elige ZIP, Sync o ambos.")
            return

        self.start_btn.setEnabled(False)
        self.progress_log.clear()
        
        # Obtener params del plan activo
        plan_name = self.plan_selector.currentText()
        plan_config = self.config_manager.get_plan(plan_name)
        
        if not plan_config:
            # Fallback seguro
            plan_config = {'transfers': '32', 'checkers': '32'}

        self.worker = SmartUploadWorker(
            self.rclone_manager, profile, folder, bucket, do_zip, do_sync, reuse_zip, **plan_config
        )
        self.worker.progress_update.connect(self.append_log)
        self.worker.status_update.connect(self.update_status)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def append_log(self, text):
        self.progress_log.append(text)
        sb = self.progress_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_status(self, text):
        self.status_label.setText(text)
        self.progress_log.append(f">>> {text}")

    def on_finished(self, success, message):
        self.start_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Éxito", message)
            self.status_label.setText("Completado.")
        else:
            QMessageBox.critical(self, "Error", message)
            self.status_label.setText("Error.")
