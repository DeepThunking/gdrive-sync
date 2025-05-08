from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import os

class DriveClient:
    def __init__(self, credentials):
        self.service = build('drive', 'v3', credentials=credentials)

    def list_files(self, folder_id: str):
        query = f"'{folder_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields="files(id, name, modifiedTime)").execute()
        return results.get('files', [])

    def download_file(self, file_id: str, file_path: str):
        request = self.service.files().get_media(fileId=file_id)
        with io.FileIO(file_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()