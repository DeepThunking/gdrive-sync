import os
import pickle
import datetime
import hashlib
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# --- Configuration ---
# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_PATH = 'token.json'  # Stores user's access and refresh tokens.
CREDENTIALS_PATH = 'credentials.json'  # Path to your OAuth 2.0 credentials file.

# --- Main Settings ---
# Set to False to actually perform operations on Google Drive.
# Set to True to only print what would happen.
DRY_RUN = False
# The name of the folder in Google Drive where backups will be stored.
DRIVE_BACKUP_ROOT_FOLDER_NAME = "My Documents Backup"
# Compare file content hashes for more robust change detection (slower).
# If False, relies on modification time and size.
COMPARE_HASHES = False


def authenticate_gdrive():
    """Shows basic usage of the Drive v3 API.
    Prints the names and ids of the first 10 files the user has access to.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                print("Attempting re-authentication.")
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                print(f"ERROR: Credentials file not found at '{CREDENTIALS_PATH}'")
                print("Please download it from Google Cloud Console and place it in the script's directory.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except HttpError as error:
        print(f'An API error occurred: {error}')
        return None
    except Exception as e:
        print(f"An unexpected error occurred during authentication: {e}")
        return None

def get_file_md5(file_path, block_size=8192):
    """Calculate MD5 hash of a file."""
    md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            while True:
                data = f.read(block_size)
                if not data:
                    break
                md5.update(data)
        return md5.hexdigest()
    except IOError:
        print(f"Could not read file for hashing: {file_path}")
        return None

def find_drive_item(service, name, parent_id, mime_type=None):
    """Finds a file or folder by name within a specific parent folder in Google Drive.

    Args:
        service: Authorized Google Drive API service instance.
        name (str): The name of the file or folder to find.
        parent_id (str): The ID of the parent folder.
        mime_type (str, optional): The MIME type to filter by (e.g., 'application/vnd.google-apps.folder').

    Returns:
        dict: The Drive item's metadata if found, else None.
    """
    query = f"name = '{name}' and '{parent_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"

    try:
        response = service.files().list(q=query,
                                        spaces='drive',
                                        fields='files(id, name, modifiedTime, md5Checksum, size, mimeType)').execute()
        items = response.get('files', [])
        if items:
            return items[0]  # Return the first match
        return None
    except HttpError as error:
        print(f'An API error occurred while searching for "{name}": {error}')
        return None

def create_drive_folder(service, name, parent_id):
    """Creates a folder in Google Drive.

    Args:
        service: Authorized Google Drive API service instance.
        name (str): The name of the folder to create.
        parent_id (str): The ID of the parent folder.

    Returns:
        str: The ID of the created folder, or None if an error occurs.
    """
    if DRY_RUN:
        print(f"[DRY RUN] Would create folder: '{name}' in parent ID '{parent_id}'")
        return f"dry_run_folder_id_for_{name.replace(' ', '_')}" # Placeholder for dry run

    file_metadata = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id]
    }
    try:
        folder = service.files().create(body=file_metadata, fields='id').execute()
        print(f"Created folder: '{name}' with ID: '{folder.get('id')}'")
        return folder.get('id')
    except HttpError as error:
        print(f'An API error occurred while creating folder "{name}": {error}')
        return None

def upload_or_update_file(service, local_file_path, drive_folder_id, existing_drive_file=None):
    """Uploads a new file or updates an existing one in Google Drive."""
    file_name = local_file_path.name
    local_mtime_ts = os.path.getmtime(local_file_path)
    local_mtime_dt_utc = datetime.datetime.fromtimestamp(local_mtime_ts, datetime.timezone.utc)
    local_size = local_file_path.stat().st_size

    if existing_drive_file:
        drive_file_id = existing_drive_file['id']
        drive_mtime_str = existing_drive_file.get('modifiedTime')
        drive_size_str = existing_drive_file.get('size') # Size in Drive is string
        drive_md5 = existing_drive_file.get('md5Checksum')

        needs_update = False
        if drive_mtime_str:
            # Google Drive API's modifiedTime is like '2023-10-27T10:30:00.000Z'
            # Need to parse it carefully. Python's fromisoformat handles 'Z' correctly in 3.11+
            # For broader compatibility, replace 'Z' with '+00:00' if needed or use dateutil.parser
            try:
                drive_mtime_dt_utc = datetime.datetime.fromisoformat(drive_mtime_str.replace('Z', '+00:00'))
            except ValueError: # Fallback for slightly different ISO formats if any
                 from dateutil import parser
                 drive_mtime_dt_utc = parser.isoparse(drive_mtime_str)


            # Compare modification times (local is newer by more than a small tolerance, e.g., 2 seconds)
            if local_mtime_dt_utc > drive_mtime_dt_utc + datetime.timedelta(seconds=2):
                print(f"Local file '{file_name}' is newer based on timestamp.")
                needs_update = True
            else:
                # If timestamps are close, check size
                if drive_size_str and int(drive_size_str) != local_size:
                    print(f"Local file '{file_name}' size mismatch (Local: {local_size}, Drive: {drive_size_str}).")
                    needs_update = True
                elif COMPARE_HASHES and drive_md5:
                    # If timestamps and sizes are same, optionally check MD5 hash
                    local_md5 = get_file_md5(local_file_path)
                    if local_md5 and local_md5 != drive_md5:
                        print(f"Local file '{file_name}' MD5 mismatch.")
                        needs_update = True
                    elif not local_md5:
                        print(f"Could not calculate local MD5 for '{file_name}', assuming update needed if hashes compared.")
                        needs_update = True # Or handle as error
                elif COMPARE_HASHES and not drive_md5:
                     print(f"Drive file '{file_name}' has no MD5, cannot compare hashes. Assuming update needed if hashes compared.")
                     needs_update = True


        else: # No modifiedTime on Drive file, assume update
            print(f"Drive file '{file_name}' has no modifiedTime, scheduling update.")
            needs_update = True

        if not needs_update:
            print(f"File '{file_name}' is up-to-date. Skipping.")
            return drive_file_id

        # --- Update existing file ---
        if DRY_RUN:
            print(f"[DRY RUN] Would update file: '{file_name}' (ID: {drive_file_id})")
            return drive_file_id

        print(f"Updating file: '{file_name}' (ID: {drive_file_id}) in Drive...")
        media = MediaFileUpload(local_file_path, resumable=True)
        try:
            updated_file = service.files().update(fileId=drive_file_id,
                                                 media_body=media,
                                                 fields='id, name, modifiedTime').execute()
            print(f"Updated: '{updated_file.get('name')}', New ModTime: {updated_file.get('modifiedTime')}")
            return updated_file.get('id')
        except HttpError as error:
            print(f'An API error occurred while updating "{file_name}": {error}')
            return None

    else:
        # --- Upload new file ---
        if DRY_RUN:
            print(f"[DRY RUN] Would upload new file: '{file_name}' to folder ID '{drive_folder_id}'")
            return f"dry_run_file_id_for_{file_name.replace(' ', '_')}"

        print(f"Uploading new file: '{file_name}' to Drive folder ID '{drive_folder_id}'...")
        file_metadata = {
            'name': file_name,
            'parents': [drive_folder_id]
        }
        media = MediaFileUpload(local_file_path, resumable=True)
        try:
            file = service.files().create(body=file_metadata,
                                          media_body=media,
                                          fields='id, name, modifiedTime').execute()
            print(f"Uploaded: '{file.get('name')}' (ID: {file.get('id')}), ModTime: {file.get('modifiedTime')}")
            return file.get('id')
        except HttpError as error:
            print(f'An API error occurred while uploading "{file_name}": {error}')
            return None

def sync_directory_recursive(service, local_dir_path, drive_parent_folder_id):
    """
    Recursively syncs a local directory to a Google Drive folder.
    """
    print(f"\nProcessing local directory: '{local_dir_path}' -> Drive Folder ID: '{drive_parent_folder_id}'")

    # 1. Get items from Google Drive in the current parent folder
    drive_items_map = {}
    if not DRY_RUN or drive_parent_folder_id and not drive_parent_folder_id.startswith("dry_run_"): # Don't query for dry_run IDs
        try:
            page_token = None
            while True:
                response = service.files().list(
                    q=f"'{drive_parent_folder_id}' in parents and trashed = false",
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum, size)',
                    pageToken=page_token
                ).execute()
                for item in response.get('files', []):
                    drive_items_map[item['name']] = item
                page_token = response.get('nextPageToken', None)
                if page_token is None:
                    break
        except HttpError as error:
            print(f"Could not list items in Drive folder ID '{drive_parent_folder_id}': {error}")
            # If we can't list the Drive folder, we can't reliably sync.
            # Depending on desired robustness, could retry or skip this directory.
            return


    # 2. Iterate over local items (files and directories)
    for local_item_path in local_dir_path.iterdir():
        local_item_name = local_item_path.name

        # Skip hidden files/folders like .DS_Store or Thumbs.db (customize as needed)
        if local_item_name.startswith('.'):
            print(f"Skipping hidden item: {local_item_path}")
            continue

        existing_drive_item = drive_items_map.get(local_item_name)

        if local_item_path.is_file():
            print(f"  Checking local file: '{local_item_name}'")
            # Ensure we are not trying to upload a file where a folder of the same name exists on Drive
            if existing_drive_item and existing_drive_item['mimeType'] == 'application/vnd.google-apps.folder':
                print(f"  CONFLICT: Local file '{local_item_name}' but Drive has a FOLDER with the same name. Skipping.")
                continue
            upload_or_update_file(service, local_item_path, drive_parent_folder_id, existing_drive_item)

        elif local_item_path.is_dir():
            print(f"  Checking local directory: '{local_item_name}'")
            drive_subdir_id = None
            if existing_drive_item:
                if existing_drive_item['mimeType'] == 'application/vnd.google-apps.folder':
                    drive_subdir_id = existing_drive_item['id']
                    print(f"  Local directory '{local_item_name}' found in Drive (ID: {drive_subdir_id}).")
                else:
                    # Name conflict: local is a directory, but Drive has a file with the same name
                    print(f"  CONFLICT: Local directory '{local_item_name}' but Drive has a FILE with the same name. Skipping sync for this directory.")
                    continue # Skip syncing this directory
            else:
                print(f"  Local directory '{local_item_name}' not found in Drive. Creating...")
                drive_subdir_id = create_drive_folder(service, local_item_name, drive_parent_folder_id)

            if drive_subdir_id: # If folder created successfully (or already existed)
                sync_directory_recursive(service, local_item_path, drive_subdir_id)
            else:
                print(f"  Could not obtain Drive folder ID for '{local_item_name}'. Skipping sync for this directory.")
    
    # 3. (Optional) Delete items from Drive that are not present locally
    # This makes it a true mirror. Be very careful with this feature.
    # For a backup, you might not want to delete from Drive if deleted locally.
    # Example (add a flag like DELETE_ORPHANED_DRIVE_FILES = False):
    # if DELETE_ORPHANED_DRIVE_FILES:
    #     local_item_names = {p.name for p in local_dir_path.iterdir() if not p.name.startswith('.')}
    #     for drive_item_name, drive_item_meta in drive_items_map.items():
    #         if drive_item_name not in local_item_names:
    #             if DRY_RUN:
    #                 print(f"[DRY RUN] Would delete orphaned Drive item: '{drive_item_name}' (ID: {drive_item_meta['id']})")
    #             else:
    #                 try:
    #                     print(f"Deleting orphaned Drive item: '{drive_item_name}' (ID: {drive_item_meta['id']})...")
    #                     service.files().delete(fileId=drive_item_meta['id']).execute()
    #                 except HttpError as error:
    #                     print(f"Failed to delete '{drive_item_name}': {error}")


def main():
    """Main function to run the sync process."""
    print("Starting Google Drive Sync...")
    if DRY_RUN:
        print("!!!!!!!!!!!!!! DRY RUN MODE ENABLED !!!!!!!!!!!!!!")
        print("No actual changes will be made to your Google Drive.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")

    local_documents_path_str = input(f"Enter the full path to your local 'Documents' directory (or leave blank to use default '{Path.home() / 'Documents'}'): ")
    if not local_documents_path_str:
        local_documents_path = Path.home() / "Documents"
    else:
        local_documents_path = Path(local_documents_path_str)

    if not local_documents_path.is_dir():
        print(f"Error: Local directory not found or is not a directory: {local_documents_path}")
        return

    print(f"Local source directory: {local_documents_path}")
    print(f"Target Google Drive root backup folder: '{DRIVE_BACKUP_ROOT_FOLDER_NAME}'\n")

    service = authenticate_gdrive()
    if not service:
        print("Failed to authenticate with Google Drive. Exiting.")
        return

    # Find or create the root backup folder in Google Drive
    drive_root_backup_folder = find_drive_item(service, DRIVE_BACKUP_ROOT_FOLDER_NAME, 'root', 'application/vnd.google-apps.folder')
    drive_root_backup_folder_id = None

    if drive_root_backup_folder:
        drive_root_backup_folder_id = drive_root_backup_folder['id']
        print(f"Found root backup folder in Drive: '{DRIVE_BACKUP_ROOT_FOLDER_NAME}' (ID: {drive_root_backup_folder_id})")
    else:
        print(f"Root backup folder '{DRIVE_BACKUP_ROOT_FOLDER_NAME}' not found in Drive. Creating it...")
        drive_root_backup_folder_id = create_drive_folder(service, DRIVE_BACKUP_ROOT_FOLDER_NAME, 'root')

    if not drive_root_backup_folder_id:
        print("Could not find or create the root backup folder in Google Drive. Exiting.")
        return

    # Start the recursive sync
    sync_directory_recursive(service, local_documents_path, drive_root_backup_folder_id)

    print("\n------------------------------------")
    print("Synchronization process finished.")
    if DRY_RUN:
        print("DRY RUN was enabled. No actual changes were made.")
    print("------------------------------------")

if __name__ == '__main__':
    # Attempt to import dateutil.parser for robust ISO date parsing.
    # This is a common library, but if not present, the script might have issues with some date formats.
    try:
        from dateutil import parser
    except ImportError:
        print("Warning: 'python-dateutil' library not found. `pip install python-dateutil` for more robust date parsing.")
        print("The script will attempt to parse dates without it, but might be less flexible.")

    main()

