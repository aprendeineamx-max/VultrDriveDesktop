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
    """Instala WinFsp de forma silenciosa con privilegios de administrador"""
    import subprocess
    import os
    import time

    def run_msiexec_admin(path):
        """Ejecuta el instalador MSI con privilegios de administrador"""
        try:
            # Comando PowerShell mejorado para instalación silenciosa
            ps_command = f"""
$process = Start-Process -FilePath 'msiexec.exe' -ArgumentList '/i', '"{path}"', '/quiet', '/norestart' -Verb RunAs -PassThru -Wait
exit $process.ExitCode
"""
            result = subprocess.run(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps_command],
                check=False,
                timeout=300,  # 5 minutos de timeout
                capture_output=True,
                text=True
            )
            print(f"[WinFsp Installer] MSI Exit Code: {result.returncode}")
            if result.stdout:
                print(f"[WinFsp Installer] Output: {result.stdout}")
            if result.stderr:
                print(f"[WinFsp Installer] Errors: {result.stderr}")
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            print("[WinFsp Installer] Timeout durante la instalación")
            return False
        except Exception as e:
            print(f"[WinFsp Installer] Error: {e}")
            return False

    try:
        base_path = get_base_path()
        
        # Buscar el instalador MSI en múltiples ubicaciones
        msi_files = []
        search_paths = [
            os.path.join(base_path, "dependencies"),
            os.path.join(base_path, "winfsp"),
            base_path
        ]
        
        print("[WinFsp Installer] Buscando instalador MSI...")
        for directory in search_paths:
            if os.path.isdir(directory):
                for file in os.listdir(directory):
                    if file.lower().startswith("winfsp") and file.lower().endswith(".msi"):
                        full_path = os.path.join(directory, file)
                        msi_files.append(full_path)
                        print(f"[WinFsp Installer] Encontrado: {full_path}")

        if not msi_files:
            print("[WinFsp Installer] No se encontró ningún instalador MSI")
            return False

        # Usar el primer instalador encontrado
        msi_path = msi_files[0]
        print(f"[WinFsp Installer] Instalando desde: {msi_path}")
        
        # Verificar que el archivo existe
        if not os.path.exists(msi_path):
            print(f"[WinFsp Installer] ERROR: El archivo no existe: {msi_path}")
            return False
        
        # Instalar MSI con privilegios de administrador
        print("[WinFsp Installer] Iniciando instalación...")
        ok = run_msiexec_admin(msi_path)
        
        if not ok:
            print("[WinFsp Installer] La instalación falló o fue cancelada")
            return False
        
        # Esperar a que la instalación finalice completamente
        print("[WinFsp Installer] Esperando a que finalice la instalación...")
        time.sleep(8)
        
        # Verificar si se instaló correctamente
        installed = check_winfsp()
        if installed:
            print("[WinFsp Installer] ¡WinFsp instalado exitosamente!")
        else:
            print("[WinFsp Installer] WinFsp no se detectó después de la instalación")
        
        return installed
    
    except Exception as e:
        print(f"[WinFsp Installer] Excepción: {e}")
        import traceback
        traceback.print_exc()
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
    
    # ===== VERIFICAR E INSTALAR WINFSP AUTOMÁTICAMENTE =====
    if not check_winfsp():
        print("[VultrDrive] WinFsp no está instalado. Intentando instalación automática...")
        if splash:
            splash.showMessage("Instalando componentes requeridos (WinFsp)...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
            app.processEvents()
        
        # Intentar instalar WinFsp automáticamente
        success = install_winfsp_silent()
        
        if success:
            print("[VultrDrive] WinFsp instalado exitosamente")
            if splash:
                splash.showMessage("WinFsp instalado correctamente", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                app.processEvents()
        else:
            print("[VultrDrive] No se pudo instalar WinFsp automáticamente")
            if splash:
                splash.showMessage("Continuando sin WinFsp (instalación pendiente)...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                app.processEvents()
    else:
        print("[VultrDrive] WinFsp ya está instalado")
    
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
