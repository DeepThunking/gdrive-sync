import os
from datetime import datetime, timezone

class DriveSyncManager:
    def __init__(self, drive_client, local_dir, crypto_utils=None):
        self.drive_client = drive_client
        self.local_dir = local_dir
        self.crypto_utils = crypto_utils

    def sync_folder(self, folder_id: str):
        os.makedirs(self.local_dir, exist_ok=True)
        files = self.drive_client.list_files(folder_id)

        for file in files:
            file_path = os.path.join(self.local_dir, file['name'])
            temp_path = file_path + '.tmp'
            remote_mtime = datetime.fromisoformat(file['modifiedTime'].replace('Z', '+00:00'))

            if os.path.exists(file_path):
                local_mtime = datetime.fromtimestamp(os.path.getmtime(file_path), timezone.utc)
                if local_mtime >= remote_mtime:
                    print(f"Skipping {file['name']} (up to date)")
                    continue

            print(f"Downloading {file['name']}...")
            self.drive_client.download_file(file['id'], temp_path)

            if self.crypto_utils:
                self.crypto_utils.encrypt_file(temp_path, file_path)
                os.remove(temp_path)
            else:
                os.rename(temp_path, file_path) 