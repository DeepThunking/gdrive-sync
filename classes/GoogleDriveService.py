import os.path
import pickle
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

# If modifying these SCOPES, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/drive']

class GoogleDriveService:
    def __init__(self, credentials_file='credentials.json', token_file='token.pickle'):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = self._authenticate()

    def _authenticate(self):
        creds = None
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Error refreshing token: {e}")
                    print("Attempting re-authentication.")
                    creds = None # Force re-authentication
            
            if not creds: # If refresh failed or no token.pickle
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES)
                # Specify a fixed port or ensure the user knows how to handle the redirect.
                # For server-side or headless, you'd use a different flow.
                # For local scripts, this often opens a browser.
                # Consider adding a timeout or specific port if issues arise.
                creds = flow.run_local_server(port=0) 
            
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        try:
            service = build('drive', 'v3', credentials=creds)
            return service
        except HttpError as error:
            print(f'An error occurred building the service: {error}')
            return None
        except Exception as e:
            print(f"An unexpected error occurred during service build: {e}")
            return None

    def get_item_id(self, item_name, parent_folder_id='root', mime_type=None):
        """
        Gets the ID of a file or folder by its name and parent folder ID.
        If mime_type is specified, it will filter by that (e.g., 'application/vnd.google-apps.folder').
        Returns the ID if found, None otherwise.
        """
        if not self.service:
            print("Drive service not available.")
            return None
        
        query = f"name = '{item_name}' and '{parent_folder_id}' in parents and trashed = false"
        if mime_type:
            query += f" and mimeType = '{mime_type}'"
            
        try:
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)').execute()
            items = results.get('files', [])
            if items:
                return items[0].get('id')
            return None
        except HttpError as error:
            print(f'An error occurred: {error}')
            return None

    def get_folder_id(self, folder_name, parent_folder_id='root'):
        """Helper to specifically get a folder ID."""
        return self.get_item_id(folder_name, parent_folder_id, mime_type='application/vnd.google-apps.folder')

    def create_folder(self, folder_name, parent_folder_id='root'):
        """Creates a folder and returns its ID."""
        if not self.service:
            print("Drive service not available.")
            return None

        # Check if folder already exists to avoid duplicates by name in the same parent
        existing_folder_id = self.get_folder_id(folder_name, parent_folder_id)
        if existing_folder_id:
            print(f"Folder '{folder_name}' already exists with ID: {existing_folder_id}")
            return existing_folder_id

        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        try:
            folder = self.service.files().create(body=file_metadata, fields='id').execute()
            print(f"Folder '{folder_name}' created with ID: {folder.get('id')}")
            return folder.get('id')
        except HttpError as error:
            print(f'An error occurred creating folder: {error}')
            return None
            
    def upload_file(self, local_file_path, folder_id, drive_file_name=None, update_existing=False, existing_file_id=None):
        """
        Uploads a file to a specific folder in Google Drive.
        If update_existing is True and existing_file_id is provided, it updates the file.
        Otherwise, it creates a new file.
        """
        if not self.service:
            print("Drive service not available.")
            return None
        if not os.path.exists(local_file_path):
            print(f"Local file not found: {local_file_path}")
            return None

        if drive_file_name is None:
            drive_file_name = os.path.basename(local_file_path)

        file_metadata = {'name': drive_file_name}
        if not update_existing: # Create new file
             file_metadata['parents'] = [folder_id]

        media = MediaFileUpload(local_file_path, resumable=True)
        
        try:
            if update_existing and existing_file_id:
                print(f"Updating file '{drive_file_name}' (ID: {existing_file_id}) in Drive...")
                file = self.service.files().update(
                    fileId=existing_file_id,
                    body=file_metadata, # Only metadata that needs changing, e.g. new name
                    media_body=media,
                    fields='id, name, modifiedTime'
                ).execute()
                print(f"File '{file.get('name')}' updated successfully. New modifiedTime: {file.get('modifiedTime')}")
            else: # Create new file
                print(f"Uploading file '{drive_file_name}' to folder ID '{folder_id}'...")
                # Check if file with the same name already exists in the target folder to avoid duplicates
                # This check can be enhanced or made optional based on user preference
                existing_remote_file_id = self.get_item_id(drive_file_name, folder_id)
                if existing_remote_file_id:
                    # Here, you might decide to update, skip, or rename.
                    # For now, let's print a warning and proceed to upload as a new file (Drive allows duplicate names)
                    # or better, update it. Let's assume update for now if name matches.
                    print(f"File '{drive_file_name}' already exists with ID: {existing_remote_file_id}. Updating it.")
                    return self.upload_file(local_file_path, folder_id, drive_file_name, update_existing=True, existing_file_id=existing_remote_file_id)

                file_metadata['parents'] = [folder_id] # Set parent for new file
                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, name, modifiedTime'
                ).execute()
                print(f"File '{file.get('name')}' uploaded successfully with ID: {file.get('id')}, ModifiedTime: {file.get('modifiedTime')}")
            return file.get('id')
        except HttpError as error:
            print(f'An error occurred during upload: {error}')
            return None
        except Exception as e:
            print(f"An unexpected error during upload: {e}")
            return None

    def download_file(self, file_id, local_folder_path, local_file_name):
        """Downloads a file from Drive."""
        if not self.service:
            print("Drive service not available.")
            return False
        
        os.makedirs(local_folder_path, exist_ok=True)
        local_file_path = os.path.join(local_folder_path, local_file_name)

        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            print(f"Downloading '{local_file_name}' (ID: {file_id}) to '{local_file_path}'...")
            while done is False:
                status, done = downloader.next_chunk()
                print(f"Download {int(status.progress() * 100)}%.")
            
            with open(local_file_path, 'wb') as f:
                f.write(fh.getvalue())
            print(f"File '{local_file_name}' downloaded successfully to '{local_file_path}'.")
            return True
        except HttpError as error:
            print(f'An error occurred during download: {error}')
            return False
        except Exception as e:
            print(f"An unexpected error during download: {e}")
            return False

    def list_folder_contents(self, folder_id='root', fields="files(id, name, mimeType, modifiedTime, md5Checksum)"):
        """Lists files and folders in a given Drive folder."""
        if not self.service:
            print("Drive service not available.")
            return []
        try:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                pageSize=1000, # Adjust as needed, handle pagination for very large folders
                fields=fields
            ).execute()
            items = results.get('files', [])
            return items
        except HttpError as error:
            print(f'An error occurred listing folder contents: {error}')
            return []

    def get_file_metadata(self, file_id, fields="id, name, mimeType, modifiedTime, md5Checksum, size, parents"):
        """Gets metadata for a specific file or folder."""
        if not self.service:
            print("Drive service not available.")
            return None
        try:
            file_metadata = self.service.files().get(fileId=file_id, fields=fields).execute()
            return file_metadata
        except HttpError as error:
            print(f'An error occurred fetching metadata for {file_id}: {error}')
            return None