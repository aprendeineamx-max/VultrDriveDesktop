import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
import os

# ===== MEJORA #48: Manejo de Errores Mejorado =====
try:
    from error_handler import handle_error, AuthenticationError, ConnectionError as CustomConnectionError
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False

# ===== MEJORA #47: Sistema de Logging =====
try:
    from logger_manager import get_logger
    logger = get_logger(__name__)
    LOGGING_AVAILABLE = True
except ImportError:
    LOGGING_AVAILABLE = False
    logger = None

class S3Handler:
    def __init__(self, access_key, secret_key, host_base):
        self.access_key = access_key
        self.secret_key = secret_key
        self.host_base = host_base
        self.last_error = None
        
        # Validar credenciales antes de crear el cliente
        if not access_key or not secret_key:
            error_msg = "Credenciales vacías. Verifica tu perfil."
            self.last_error = error_msg
            if LOGGING_AVAILABLE:
                logger.error(error_msg)
            raise ValueError(error_msg)
        
        if not host_base:
            error_msg = "Host base no especificado. Verifica tu perfil."
            self.last_error = error_msg
            if LOGGING_AVAILABLE:
                logger.error(error_msg)
            raise ValueError(error_msg)
        
        try:
            self.session = boto3.session.Session()
            self.client = self.session.client(
                's3',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                endpoint_url=f'https://{host_base}',
                config=Config(s3={'addressing_style': 'virtual'})
            )
            if LOGGING_AVAILABLE:
                logger.debug(f"S3Handler inicializado para {host_base}")
        except Exception as e:
            error_msg = f"Error al inicializar cliente S3: {str(e)}"
            self.last_error = error_msg
            if LOGGING_AVAILABLE:
                logger.error(error_msg)
            raise

    def list_buckets(self):
        """
        Listar buckets disponibles
        
        Returns:
            tuple: (buckets_list, error_message)
                   buckets_list: Lista de nombres de buckets
                   error_message: Mensaje de error si hubo problema, None si fue exitoso
        """
        self.last_error = None
        
        try:
            if LOGGING_AVAILABLE:
                logger.debug(f"Intentando listar buckets desde {self.host_base}")
            
            response = self.client.list_buckets()
            buckets = [bucket['Name'] for bucket in response['Buckets']]
            
            if LOGGING_AVAILABLE:
                logger.info(f"Encontrados {len(buckets)} buckets: {buckets}")
            
            return buckets, None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            # Errores comunes de autenticación
            if error_code in ['InvalidAccessKeyId', 'SignatureDoesNotMatch']:
                message = f"Credenciales inválidas. Verifica tu Access Key y Secret Key.\n\nError: {error_msg}"
                self.last_error = message
                if LOGGING_AVAILABLE:
                    logger.error(f"Error de autenticación: {error_code} - {error_msg}")
                if ERROR_HANDLING_AVAILABLE:
                    error = handle_error(AuthenticationError(message), context="list_buckets")
                    return [], error.message
                return [], message
            
            # Error de conexión
            elif error_code in ['EndpointConnectionError', 'ConnectionError']:
                message = f"No se pudo conectar al servidor {self.host_base}.\n\nVerifica:\n- Tu conexión a Internet\n- Que el host base sea correcto\n\nError: {error_msg}"
                self.last_error = message
                if LOGGING_AVAILABLE:
                    logger.error(f"Error de conexión: {error_code} - {error_msg}")
                if ERROR_HANDLING_AVAILABLE:
                    error = handle_error(CustomConnectionError(message), context="list_buckets")
                    return [], error.message
                return [], message
            
            # Otros errores
            else:
                message = f"Error al listar buckets: {error_msg}\n\nCódigo de error: {error_code}"
                self.last_error = message
                if LOGGING_AVAILABLE:
                    logger.error(f"Error al listar buckets: {error_code} - {error_msg}")
                return [], message
                
        except NoCredentialsError as e:
            message = "No se encontraron credenciales. Verifica tu perfil."
            self.last_error = message
            if LOGGING_AVAILABLE:
                logger.error(f"Error de credenciales: {str(e)}")
            return [], message
            
        except EndpointConnectionError as e:
            message = f"No se pudo conectar al endpoint {self.host_base}.\n\nVerifica:\n- Tu conexión a Internet\n- Que el host base sea correcto (ej: ewr1.vultrobjects.com)"
            self.last_error = message
            if LOGGING_AVAILABLE:
                logger.error(f"Error de conexión al endpoint: {str(e)}")
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(CustomConnectionError(message), context="list_buckets")
                return [], error.message
            return [], message
            
        except Exception as e:
            message = f"Error inesperado al listar buckets: {str(e)}"
            self.last_error = message
            if LOGGING_AVAILABLE:
                logger.error(f"Error inesperado: {str(e)}", exc_info=True)
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(e, context="list_buckets")
                return [], error.message
            return [], message

    def upload_file(self, bucket_name, file_path, object_name=None):
        if object_name is None:
            object_name = os.path.basename(file_path)

        try:
            self.client.upload_file(file_path, bucket_name, object_name)
            print(f"File {file_path} uploaded to {bucket_name}/{object_name}")
            return True
        except Exception as e:
            print(f"Error uploading file: {e}")
            return False

    def list_objects(self, bucket_name, prefix=''):
        try:
            response = self.client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
            if 'Contents' in response:
                return [obj['Key'] for obj in response['Contents']]
            return []
        except Exception as e:
            print(f"Error listing objects: {e}")
            return []
    
    def get_bucket_size(self, bucket_name):
        """
        Obtener el tamaño total usado en un bucket
        
        Args:
            bucket_name: Nombre del bucket
            
        Returns:
            tuple: (size_bytes, error_message)
                   size_bytes: Tamaño total en bytes, None si hay error
                   error_message: Mensaje de error si hubo problema, None si fue exitoso
        """
        try:
            if LOGGING_AVAILABLE:
                logger.debug(f"Calculando tamaño del bucket '{bucket_name}'")
            
            total_size = 0
            paginator = self.client.get_paginator('list_objects_v2')
            
            for page in paginator.paginate(Bucket=bucket_name):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        total_size += obj.get('Size', 0)
            
            if LOGGING_AVAILABLE:
                logger.info(f"Tamaño del bucket '{bucket_name}': {total_size} bytes ({total_size / (1024*1024):.2f} MB)")
            
            return total_size, None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            message = f"Error al obtener tamaño del bucket: {error_msg}"
            
            if LOGGING_AVAILABLE:
                logger.error(f"Error al obtener tamaño del bucket: {error_code} - {error_msg}")
            
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(e, context="get_bucket_size")
                return None, error.message
            return None, message
            
        except Exception as e:
            message = f"Error inesperado al obtener tamaño del bucket: {str(e)}"
            if LOGGING_AVAILABLE:
                logger.error(f"Error inesperado: {str(e)}", exc_info=True)
            if ERROR_HANDLING_AVAILABLE:
                error = handle_error(e, context="get_bucket_size")
                return None, error.message
            return None, message

    def delete_object(self, bucket_name, object_name):
        try:
            self.client.delete_object(Bucket=bucket_name, Key=object_name)
            print(f"Deleted {object_name} from {bucket_name}")
            return True
        except Exception as e:
            print(f"Error deleting object: {e}")
            return False

    def delete_all_objects(self, bucket_name):
        try:
            # List all objects
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name)

            delete_us = []
            for page in pages:
                if 'Contents' in page:
                    delete_us.extend([{'Key': obj['Key']} for obj in page['Contents']])

            # Delete in batches of 1000 (S3 limit)
            if delete_us:
                for i in range(0, len(delete_us), 1000):
                    batch = delete_us[i:i+1000]
                    self.client.delete_objects(
                        Bucket=bucket_name,
                        Delete={'Objects': batch}
                    )
                print(f"Deleted {len(delete_us)} objects from {bucket_name}")
            
            return True
        except Exception as e:
            print(f"Error deleting all objects: {e}")
            return False

    def download_file(self, bucket_name, object_name, file_path):
        try:
            self.client.download_file(bucket_name, object_name, file_path)
            print(f"Downloaded {object_name} to {file_path}")
            return True
        except Exception as e:
            print(f"Error downloading file: {e}")
            return False
