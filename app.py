import sys
import json
import os

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
    """
    Instala WinFsp automáticamente en segundo plano
    Retorna: bool - True si se instaló correctamente, False si falló
    """
    import subprocess
    import time
    
    base_path = get_base_path()
    installer_bat = os.path.join(base_path, "INSTALAR_WINFSP.bat")
    
    # Buscar el instalador MSI
    msi_files = []
    for file in os.listdir(base_path):
        if file.startswith("winfsp") and file.endswith(".msi"):
            msi_files.append(os.path.join(base_path, file))
    
    if not msi_files and not os.path.exists(installer_bat):
        return False
    
    try:
        if msi_files:
            # Instalar directamente el MSI en modo silencioso
            msi_path = msi_files[0]
            # /i = install, /quiet = sin UI, /norestart = no reiniciar
            subprocess.run(
                ['msiexec', '/i', msi_path, '/quiet', '/norestart'],
                check=False,
                timeout=120  # Timeout de 2 minutos
            )
        elif os.path.exists(installer_bat):
            # Ejecutar el BAT (que descargará e instalará)
            subprocess.run(
                [installer_bat],
                check=False,
                timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW  # Sin ventana
            )
        
        # Esperar un momento para que finalice la instalación
        time.sleep(3)
        
        # Verificar si se instaló correctamente
        return check_winfsp()
    
    except Exception as e:
        return False

def main():
    # ===== OPTIMIZACIÓN 1: Verificar WinFsp primero (0.06ms) =====
    winfsp_installed = check_winfsp()
    
    # ===== OPTIMIZACIÓN 2: Crear QApplication lo más rápido posible =====
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import Qt, QTimer
    
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
    
    # Si WinFsp no está instalado, instalarlo automáticamente (SOLO SI NO ESTÁ)
    if not winfsp_installed:
        if splash:
            splash.showMessage("Instalando WinFsp automáticamente...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
            app.processEvents()
        
        # Intentar instalar WinFsp en segundo plano
        success = install_winfsp_silent()
        
        if success:
            if splash:
                splash.showMessage("✅ WinFsp instalado correctamente", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                app.processEvents()
        else:
            # Si falla la instalación automática, continuar sin WinFsp
            if splash:
                splash.showMessage("⚠️ Continuando sin WinFsp...", Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
                app.processEvents()
    else:
        # WinFsp ya está instalado, no hacer nada
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
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
