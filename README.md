# Vultr Drive Desktop

Una aplicación de escritorio completa para gestionar tu almacenamiento en Vultr Object Storage.

## Características

### ✨ Funcionalidades Principales

1. **Gestión de Perfiles**
   - Añadir múltiples cuentas de Vultr Object Storage
   - Cambiar entre perfiles fácilmente
   - Editar y eliminar perfiles existentes

2. **Operaciones de Archivos**
   - Subir archivos individuales
   - Backup completo de carpetas
   - Barra de progreso para operaciones largas
   - Selección de bucket de destino

3. **Montaje de Disco** 🔥
   - Monta tu Object Storage como una unidad de disco en "Este equipo"
   - Elige la letra de unidad que prefieras (V-Z)
   - Accede a tus archivos como si estuvieran en tu PC
   - Desmonta la unidad de forma segura cuando termines

4. **Opciones Avanzadas**
   - Formatear buckets (con confirmación doble para seguridad)
   - Eliminar todos los archivos de un bucket

5. **Backup Rápido desde Escritorio**
   - Acceso directo en el escritorio para backups instantáneos
   - Sin necesidad de abrir la aplicación principal

## Instalación

### Requisitos Previos
- Windows 10/11 o Windows Server
- Python 3.9 o superior

### Dependencias ya instaladas
- PyQt6
- boto3
- watchdog
- pywin32
- rclone (incluido en el proyecto)
- WinFsp (instalador `.msi` incluido en la versión portable)

## Uso

### Iniciar la Aplicación

```powershell
cd c:\Users\lvarg\Desktop\VultrDriveDesktop
py app.py
```

### Crear Acceso Directo de Backup en el Escritorio

```powershell
py create_shortcut.py
```

Esto creará un acceso directo llamado "Vultr Backup Now" en tu escritorio que te permitirá hacer backups rápidos sin abrir la aplicación principal.

## Guía de Uso

### 1. Configurar un Perfil

1. Abre la aplicación
2. Haz clic en "⚙️ Manage Profiles"
3. Completa el formulario:
   - **Profile Name**: Nombre descriptivo (ej: "almacen-de-backups-cuenta-destino")
   - **Access Key**: Tu Access Key de Vultr
   - **Secret Key**: Tu Secret Key de Vultr
   - **Hostname**: El hostname de tu región (ej: lax1.vultrobjects.com)
4. Haz clic en "Save Profile"

**Nota**: Ya tienes un perfil preconfigurado con tus credenciales.

### 2. Subir Archivos

1. Selecciona tu perfil en la pestaña "Main"
2. Elige el bucket de destino
3. Haz clic en "📁 Upload File"
4. Selecciona el archivo
5. Espera a que se complete la subida

### 3. Hacer Backup de una Carpeta

1. Selecciona tu perfil y bucket
2. Haz clic en "💾 Backup Folder"
3. Selecciona la carpeta que deseas respaldar
4. La barra de progreso mostrará el avance
5. Recibirás una confirmación al finalizar

### 4. Montar como Disco (¡INCREÍBLE!)

1. Ve a la pestaña "Drive Mount"
2. Selecciona la letra de unidad que desees (V, W, X, Y, Z)
3. Asegúrate de tener un perfil y bucket seleccionados
4. Haz clic en "🔗 Mount Drive"
5. ¡Ahora puedes acceder a tu almacenamiento desde "Este equipo"!

**Para desmontar:**
- Haz clic en "🔌 Unmount Drive" cuando termines
- O cierra la aplicación (te preguntará si deseas desmontar)

### 5. Formatear un Bucket (⚠️ Usar con precaución)

1. Ve a la pestaña "Advanced"
2. Asegúrate de tener el bucket correcto seleccionado
3. Haz clic en "🗑️ Format Selected Bucket"
4. Lee las advertencias cuidadosamente
5. Confirma escribiendo el nombre del bucket
6. Todos los archivos serán eliminados permanentemente

## Estructura del Proyecto

```
VultrDriveDesktop/
├── app.py                  # Aplicación principal
├── s3_handler.py          # Gestión de operaciones S3/Vultr
├── config_manager.py      # Gestión de perfiles y configuración
├── rclone_manager.py      # Gestión de montaje de disco
├── file_watcher.py        # Monitoreo de archivos (tiempo real)
├── backup_now.py          # Script de backup rápido
├── create_shortcut.py     # Creador de acceso directo
├── config.json            # Almacenamiento de perfiles (generado)
├── rclone.exe            # Herramienta de montaje
├── ui/
│   ├── main_window.py    # Interfaz principal
│   ├── settings_window.py # Ventana de configuración
│   └── style.qss         # Hoja de estilos
└── README.md             # Este archivo
```

## Solución de Problemas

### La unidad no se monta
- Verifica que la letra de unidad no esté en uso
- Asegúrate de que las credenciales sean correctas
- Revisa que el bucket exista

### Error al subir archivos
- Verifica tu conexión a internet
- Confirma que las credenciales sean válidas
- Asegúrate de que el bucket exista y tengas permisos

### La aplicación no inicia
- Verifica que Python esté instalado correctamente
- Asegúrate de que todas las dependencias estén instaladas
- Ejecuta: `py -m pip install PyQt6 boto3 watchdog pywin32`

## Mejoras Futuras Sugeridas

1. **Sincronización en Tiempo Real**
   - Monitorear carpetas y subir cambios automáticamente
   - Similar a Google Drive o Dropbox

2. **Cifrado de Archivos**
   - Cifrar archivos antes de subirlos
   - Mayor seguridad para datos sensibles

3. **Bandeja del Sistema**
   - Icono en la bandeja del sistema
   - Menú contextual para acciones rápidas
   - Notificaciones de progreso

4. **Múltiples Selecciones**
   - Subir a múltiples buckets simultáneamente
   - Backup sincronizado entre varias cuentas

5. **Programador de Backups**
   - Backups automáticos programados
   - Backups incrementales

6. **Historial de Versiones**
   - Mantener versiones anteriores de archivos
   - Restaurar archivos a versiones previas

## Créditos

Desarrollado con:
- PyQt6 - Interfaz de usuario moderna
- boto3 - SDK de AWS (compatible con S3)
- rclone - Montaje de almacenamiento en la nube
- watchdog - Monitoreo de sistema de archivos

## Licencia

Uso personal y comercial permitido.

---

¿Preguntas o problemas? Revisa la documentación de Vultr Object Storage: https://www.vultr.com/docs/vultr-object-storage/
