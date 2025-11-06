import boto3
from botocore.client import Config
import os

class S3Handler:
    def __init__(self, access_key, secret_key, host_base):
        self.session = boto3.session.Session()
        self.client = self.session.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=f'https://{host_base}',
            config=Config(s3={'addressing_style': 'virtual'})
        )

    def list_buckets(self):
        try:
            response = self.client.list_buckets()
            return [bucket['Name'] for bucket in response['Buckets']]
        except Exception as e:
            print(f"Error listing buckets: {e}")
            return []

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
