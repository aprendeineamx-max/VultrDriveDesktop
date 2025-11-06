# Optimized Splash Screen for VultrDriveDesktop
from PyQt6.QtWidgets import QSplashScreen, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont

class FastSplashScreen(QSplashScreen):
    """
    Splash screen minimalista y ultra-rápido
    Se muestra mientras cargan los módulos pesados
    """
    def __init__(self):
        # Crear imagen simple (sin archivos externos)
        pixmap = QPixmap(500, 250)
        pixmap.fill(QColor(30, 30, 30))
        
        super().__init__(pixmap, Qt.WindowType.WindowStaysOnTopHint)
        
        # Configurar texto
        self.setStyleSheet("""
            QSplashScreen {
                background-color: #1e1e1e;
                border: 2px solid #3498db;
                border-radius: 10px;
            }
        """)
        
        # Mostrar mensaje
        self.showMessage(
            "Iniciando...",
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom,
            QColor(200, 200, 200)
        )
        
    def drawContents(self, painter):
        """Dibujar contenido personalizado"""
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        
        # Título más grande y centrado
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            "Vultr Drive Desktop"
        )
        
        super().drawContents(painter)
