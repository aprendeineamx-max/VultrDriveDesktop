import sys
import json
import os

try:
    import ctypes
except ImportError:  # pragma: no cover
    ctypes = None

def get_base_path():
    """Get the base path for the application (works with PyInstaller)"""
    if getattr(sys, 'frozen', False):
        # Ejecutando desde ejecutable empaquetado
        return os.path.dirname(sys.executable)
    else:
        # Ejecutando desde script Python
        return os.path.dirname(os.path.abspath(__file__))

def load_user_preferences():
    """Load user preferences for language and theme"""
    base_path = get_base_path()
    preferences_file = os.path.join(base_path, "user_preferences.json")
    default_preferences = {
        "language": "es",
        "theme": "dark"
    }
    
    try:
        if os.path.exists(preferences_file):
            with open(preferences_file, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            return default_preferences
    except:
        return default_preferences

def save_user_preferences(preferences):
    """Save user preferences for language and theme"""
    base_path = get_base_path()
    preferences_file = os.path.join(base_path, "user_preferences.json")
    try:
        with open(preferences_file, "w", encoding="utf-8") as f:
            json.dump(preferences, f, indent=2)
    except:
        pass

def check_winfsp():
    """
    Verifica si WinFsp está instalado (ultra-rápido: <1ms)
    Retorna: bool - True si está instalado, False si no
    """
    winfsp_paths = [
        r"C:\Program Files (x86)\WinFsp\bin\winfsp-x64.dll",
        r"C:\Program Files\WinFsp\bin\winfsp-x64.dll"
    ]
    
    for path in winfsp_paths:
        if os.path.exists(path):
            return True
    
    return False

def install_winfsp_silent():
    import subprocess
    import os
    import time

    def run_msiexec_admin(path):
        ps_command = (
            "Start-Process msiexec -ArgumentList '/i `\"{0}`\" /quiet /norestart' -Verb runAs -Wait"
        ).format(path.replace("'", "''"))
        result = subprocess.run(
            ['powershell', '-NoLogo', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps_command],
            check=False,
            timeout=240
        )
        return result.returncode == 0

    def run_installer_admin(target):
        if target.endswith('.msi'):
            return run_msiexec_admin(target)
        ps_command = (
            "Start-Process -FilePath `\"{0}`\" -Verb runAs -Wait"
        ).format(target.replace("'", "''"))
        result = subprocess.run(
            ['powershell', '-NoLogo', '-NoProfile', '-WindowStyle', 'Hidden', '-Command', ps_command],
            check=False,
            timeout=240
        )
        return result.returncode == 0

    try:
        base_path = get_base_path()
        installer_bat = os.path.join(base_path, "INSTALAR_WINFSP.bat")
        msi_files = []
        search_paths = [base_path, os.path.join(base_path, "dependencies"), os.path.join(base_path, "winfsp")]
        for directory in search_paths:
            if os.path.isdir(directory):
                for file in os.listdir(directory):
                    if file.lower().startswith("winfsp") and file.lower().endswith(".msi"):
                        msi_files.append(os.path.join(directory, file))

        if msi_files:
            # Instalar MSI con privilegios de administrador
            msi_path = msi_files[0]
            ok = run_installer_admin(msi_path)
        elif os.path.exists(installer_bat):
            # Ejecutar BAT con privilegios de administrador
            ok = run_installer_admin(installer_bat)
        else:
            ok = False
        
        # Esperar un momento para que finalice la instalación
        time.sleep(5)
        
        # Verificar si se instaló correctamente
        return check_winfsp() and ok
    
    except Exception as e:
        return False

# Importaciones de PyQt6 para las clases siguientes
from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer, Qt
from PyQt6.QtWidgets import QApplication

class WinFspInstaller(QObject):
    """Worker en segundo plano para instalar WinFsp sin bloquear la UI"""

    finished = pyqtSignal(bool)

    def run(self):
        success = install_winfsp_silent()
        if success and not check_winfsp():
            success = False
        self.finished.emit(success)

def start_component_check(window, manual=False, force_install=False):
    """Verifica e instala componentes sin bloquear la UI"""

    if getattr(window, "_winfsp_thread", None) and window._winfsp_thread.isRunning():
        window.statusBar().showMessage(window.tr("status_installing_winfsp"), 5000)
        return

    if not manual and getattr(window, "_component_check_completed", False) and not force_install:
        return

    window.statusBar().showMessage(window.tr("status_checking_components"), 3000)

    if check_winfsp() and not force_install:
        window._component_check_completed = True
        window.statusBar().showMessage(window.tr("status_components_ready"), 5000)
        return

    window.statusBar().showMessage(window.tr("status_installing_winfsp"))

    installer = WinFspInstaller()
    thread = QThread()
    installer.moveToThread(thread)

    def finish(success):
        if success and check_winfsp():
            window._component_check_completed = True
            window.statusBar().showMessage(window.tr("status_install_finished"), 8000)
        elif success:
            window.statusBar().showMessage(window.tr("status_install_cancelled"), 8000)
        else:
            window.statusBar().showMessage(window.tr("status_install_failed"), 8000)

        if thread.isRunning():
            thread.quit()
            thread.wait()
        else:
            thread.wait(100)

        installer.deleteLater()
        thread.deleteLater()
        window._winfsp_installer = None
        window._winfsp_thread = None

    installer.finished.connect(finish)
    thread.started.connect(installer.run)

    window._winfsp_installer = installer
    window._winfsp_thread = thread
    thread.start()

def main():
    app = QApplication(sys.argv)
    
    # ===== OPTIMIZACIÓN 3: Mostrar splash mientras carga el resto =====
    splash = None
    try:
        from splash_screen import FastSplashScreen
        splash = FastSplashScreen()
        splash.show()
        app.processEvents()  # Forzar renderizado del splash
    except:
        pass  # Si falla el splash, continuar sin él
    if splash:
        splash.showMessage("Iniciando...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        app.processEvents()
    
    # ===== OPTIMIZACIÓN 4: Cargar módulos pesados con feedback =====
    if splash:
        splash.showMessage("Cargando interfaz...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        app.processEvents()
    
    from ui.main_window import MainWindow
    from theme_manager import ThemeManager
    from translations import Translations
    
    # Load user preferences
    preferences = load_user_preferences()
    
    # Initialize theme manager and translations
    if splash:
        splash.showMessage("Configurando tema...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        app.processEvents()
    
    theme_manager = ThemeManager()
    translations = Translations()
    
    # Set user preferences
    theme_manager.set_theme(preferences.get("theme", "dark"))
    translations.set_language(preferences.get("language", "es"))
    
    # Apply theme
    app.setStyleSheet(theme_manager.get_current_stylesheet())

    # Create main window with theme manager and translations
    if splash:
        splash.showMessage("Iniciando...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        app.processEvents()
    
    window = MainWindow(theme_manager, translations, save_user_preferences)
    if hasattr(window, "set_winfsp_installer"):
        window.set_winfsp_installer(lambda: start_component_check(window, manual=True, force_install=True))
    window.trigger_component_check = lambda: start_component_check(window)
    window.manual_install_winfsp = lambda: start_component_check(window, manual=True, force_install=True)
    
    # Cerrar splash y mostrar ventana principal
    if splash:
        splash.finish(window)
    
    window.show()
    
    # ===== OPTIMIZACIÓN 5: Ejecutar tareas en segundo plano DESPUÉS de mostrar ventana =====
    # Detectar y desmontar discos montados (sin bloquear la UI)
    def cleanup_mounted_drives():
        """Ejecutar en segundo plano después de mostrar ventana"""
        try:
            from rclone_manager import RcloneManager
            mounted = RcloneManager.detect_mounted_drives()
            if mounted:
                # Hay discos montados, desmontarlos silenciosamente
                RcloneManager.unmount_all_drives()
        except:
            pass  # Si falla, no importa, continuar normalmente
    
    # Ejecutar en 500ms (medio segundo después de mostrar ventana)
    QTimer.singleShot(500, cleanup_mounted_drives)

    # Verificar componentes sin bloquear la apertura
    QTimer.singleShot(800, lambda: start_component_check(window))
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
