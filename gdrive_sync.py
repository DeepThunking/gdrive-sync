import os
import pickle
import datetime
import hashlib
import json # For loading credentials from string
import getpass # For securely getting password
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_PATH = 'token.json'
CREDENTIALS_PATH = 'credentials.json'  # Unencrypted credentials file
CREDENTIALS_PATH_ENC = 'credentials.json.enc' # Encrypted credentials file
SALT_SIZE = 16  # Size of the salt for key derivation

# --- Main Settings ---
# Set to False to actually perform operations on Google Drive.
# Set to True to only print what would happen.
DRY_RUN = True
# The name of the folder in Google Drive where backups will be stored.
DRIVE_BACKUP_ROOT_FOLDER_NAME = "Documents Backup"
# Compare file content hashes for more robust change detection (slower).
# If False, relies on modification time and size.
COMPARE_HASHES = True

# --- Cryptography Helper Functions ---
def generate_key_from_password(password: str, salt: bytes) -> bytes:
    """Derives a Fernet key from a password and salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32, # Fernet key length
        salt=salt,
        iterations=100000, # Adjust iterations as needed for security/performance
        backend=default_backend()
    )
    # Fernet key must be 32 url-safe base64-encoded bytes.
    # kdf.derive directly gives 32 bytes. We then base64 encode it.
    derived_key = kdf.derive(password.encode())
    return base64.urlsafe_b64encode(derived_key)

def encrypt_content(content: str, password: str) -> bytes:
    """Encrypts string content, returns bytes (salt + encrypted_data)."""
    salt = os.urandom(SALT_SIZE)
    key = generate_key_from_password(password, salt)
    f = Fernet(key)
    encrypted_data = f.encrypt(content.encode())
    return salt + encrypted_data

def decrypt_content(encrypted_data_with_salt: bytes, password: str) -> str:
    """Decrypts bytes (salt + encrypted_data), returns string content."""
    salt = encrypted_data_with_salt[:SALT_SIZE]
    encrypted_data = encrypted_data_with_salt[SALT_SIZE:]
    key = generate_key_from_password(password, salt)
    f = Fernet(key)
    decrypted_data = f.decrypt(encrypted_data)
    return decrypted_data.decode()

def manage_credentials():
    """
    Manages loading and optional encryption of credentials.json.
    Returns the client_config dictionary or None.
    """
    client_config = None
    # 'password' variable was defined but not used in the broader scope of this function,
    # it's better to define it where it's actually used (e.g. current_password, new_password)
    # password = None # Commented out

    if os.path.exists(CREDENTIALS_PATH_ENC):
        print(f"Found encrypted credentials: {CREDENTIALS_PATH_ENC}")
        while True:
            current_password = getpass.getpass(f"Enter password to decrypt '{CREDENTIALS_PATH_ENC}': ")
            if not current_password:
                print("Password cannot be empty. Please try again.")
                continue
            try:
                with open(CREDENTIALS_PATH_ENC, 'rb') as f:
                    encrypted_content_with_salt = f.read()
                decrypted_json_str = decrypt_content(encrypted_content_with_salt, current_password)
                client_config = json.loads(decrypted_json_str)
                print("Credentials decrypted successfully.")
                break
            except Exception as e:
                print(f"Failed to decrypt: {e}. Incorrect password or corrupted file?")
                retry = input("Try again? (y/n): ").lower()
                if retry != 'y':
                    return None
    elif os.path.exists(CREDENTIALS_PATH):
        print(f"Found unencrypted credentials file: {CREDENTIALS_PATH}")
        try:
            with open(CREDENTIALS_PATH, 'r') as f:
                client_config = json.load(f)
            
            encrypt_choice = input(f"Do you want to encrypt '{CREDENTIALS_PATH}' now? (y/n): ").lower()
            if encrypt_choice == 'y':
                new_password = "" # Initialize to ensure it's defined
                while True:
                    new_password = getpass.getpass(f"Enter a new password to encrypt '{CREDENTIALS_PATH}': ")
                    if not new_password:
                         print("Password cannot be empty. Please try again.")
                         continue
                    password_confirm = getpass.getpass("Confirm password: ")
                    if new_password == password_confirm:
                        break
                    else:
                        print("Passwords do not match. Please try again.")
                try:
                    with open(CREDENTIALS_PATH, 'r') as f_plain:
                        plain_content = f_plain.read()
                    encrypted_data = encrypt_content(plain_content, new_password)
                    with open(CREDENTIALS_PATH_ENC, 'wb') as f_enc:
                        f_enc.write(encrypted_data)
                    print(f"Successfully encrypted credentials to '{CREDENTIALS_PATH_ENC}'.")
                    print(f"IMPORTANT: Please MANUALLY DELETE the original unencrypted file '{CREDENTIALS_PATH}' for security.")
                except Exception as e:
                    print(f"Error during encryption: {e}")
        except Exception as e:
            print(f"Error reading '{CREDENTIALS_PATH}': {e}")
            return None
    else:
        print(f"ERROR: Credentials file not found.")
        print(f"Please place '{CREDENTIALS_PATH}' (downloaded from Google Cloud Console)")
        print(f"or an existing '{CREDENTIALS_PATH_ENC}' in the script's directory.")
        return None
    
    return client_config


def authenticate_gdrive():
    """Authenticates with Google Drive, handling encrypted credentials."""
    creds = None
    client_config_dict = None

    # Manage credentials (load/decrypt/offer encryption)
    client_config_dict = manage_credentials()
    if not client_config_dict:
        return None # Failed to get credentials content

    # Load existing token if available
    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            print(f"Error loading token from {TOKEN_PATH}: {e}. Will try to re-authenticate.")
            creds = None # Force re-authentication

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Refreshing access token...")
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}")
                print("Attempting full re-authentication.")
                # Fall through to re-authentication using client_config_dict
                creds = None # Ensure we re-authenticate
        
        if not creds: # This will be true if initial load failed, token expired and couldn't refresh, or no token existed
            try:
                print("Attempting new authentication or re-authentication...")
                # Use client_config_dict instead of client_secrets_file
                flow = InstalledAppFlow.from_client_config(client_config_dict, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"Error during authentication flow: {e}")
                print(f"Ensure your '{CREDENTIALS_PATH}' or '{CREDENTIALS_PATH_ENC}' is valid.")
                return None
        
        # Save the credentials for the next run
        try:
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
            print(f"Token saved to {TOKEN_PATH}")
        except Exception as e:
            print(f"Error saving token to {TOKEN_PATH}: {e}")


    try:
        service = build('drive', 'v3', credentials=creds)
        print("Google Drive API service created successfully.")
        return service
    except HttpError as error:
        print(f'An API error occurred while building Drive service: {error}')
        return None
    except Exception as e:
        print(f"An unexpected error occurred during service build: {e}")
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
    # Escape single quotes in the item's name for the Drive API query
    # A single quote ' needs to become \' in the query.
    # In Python, to represent \', we write '\\''.
    escaped_name = name.replace("'", "\\'")
    query = f"name = '{escaped_name}' and '{parent_id}' in parents and trashed = false"
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
        # Sanitize name for placeholder ID to avoid issues if name contains problematic characters
        safe_name_part = "".join(c if c.isalnum() or c in (' ', '_', '-') else '_' for c in name)
        print(f"[DRY RUN] Would create folder: '{name}' in parent ID '{parent_id}'")
        return f"dry_run_folder_id_for_{safe_name_part.replace(' ', '_')}"

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
    # Ensure timezone-aware datetime for comparison
    local_mtime_dt_utc = datetime.datetime.fromtimestamp(local_mtime_ts, datetime.timezone.utc)
    local_size = local_file_path.stat().st_size

    if existing_drive_file:
        drive_file_id = existing_drive_file['id']
        drive_mtime_str = existing_drive_file.get('modifiedTime')
        drive_size_str = existing_drive_file.get('size') # Size in Drive is string
        drive_md5 = existing_drive_file.get('md5Checksum')

        needs_update = False
        if drive_mtime_str:
            try:
                # Google Drive API's modifiedTime is like '2023-10-27T10:30:00.000Z'
                # Python's fromisoformat handles 'Z' correctly in 3.11+
                # For broader compatibility, replace 'Z' with '+00:00'
                drive_mtime_dt_utc = datetime.datetime.fromisoformat(drive_mtime_str.replace('Z', '+00:00'))
            except ValueError: # Fallback for slightly different ISO formats if any
                 from dateutil import parser # Import here to avoid making it a hard dependency if not needed
                 drive_mtime_dt_utc = parser.isoparse(drive_mtime_str)


            # Compare modification times (local is newer by more than a small tolerance, e.g., 2 seconds)
            if local_mtime_dt_utc > drive_mtime_dt_utc + datetime.timedelta(seconds=2):
                print(f"  Local file '{file_name}' is newer based on timestamp.")
                needs_update = True
            else:
                # If timestamps are close, check size
                if drive_size_str and int(drive_size_str) != local_size:
                    print(f"  Local file '{file_name}' size mismatch (Local: {local_size}, Drive: {drive_size_str}).")
                    needs_update = True
                elif COMPARE_HASHES and drive_md5:
                    # If timestamps and sizes are same, optionally check MD5 hash
                    local_md5_val = get_file_md5(local_file_path) # Renamed to avoid conflict
                    if local_md5_val and local_md5_val != drive_md5:
                        print(f"  Local file '{file_name}' MD5 mismatch.")
                        needs_update = True
                    elif not local_md5_val:
                        print(f"  Could not calculate local MD5 for '{file_name}', assuming update needed if hashes compared.")
                        needs_update = True
                elif COMPARE_HASHES and not drive_md5:
                     print(f"  Drive file '{file_name}' has no MD5, cannot compare hashes. Assuming update needed if hashes compared.")
                     needs_update = True
        else: # No modifiedTime on Drive file, assume update
            print(f"  Drive file '{file_name}' has no modifiedTime, scheduling update.")
            needs_update = True

        if not needs_update:
            print(f"  File '{file_name}' is up-to-date. Skipping.")
            return drive_file_id

        # --- Update existing file ---
        if DRY_RUN:
            print(f"  [DRY RUN] Would update file: '{file_name}' (ID: {drive_file_id})")
            return drive_file_id

        print(f"  Updating file: '{file_name}' (ID: {drive_file_id}) in Drive...")
        media = MediaFileUpload(str(local_file_path), resumable=True) # Ensure path is string
        try:
            updated_file = service.files().update(fileId=drive_file_id,
                                                 media_body=media,
                                                 fields='id, name, modifiedTime').execute()
            print(f"  Updated: '{updated_file.get('name')}', New ModTime: {updated_file.get('modifiedTime')}")
            return updated_file.get('id')
        except HttpError as error:
            print(f'  An API error occurred while updating "{file_name}": {error}')
            return None
    else:
        # --- Upload new file ---
        if DRY_RUN:
            # Sanitize name for placeholder ID
            safe_file_name_part = "".join(c if c.isalnum() or c in (' ', '_', '-', '.') else '_' for c in file_name)
            print(f"  [DRY RUN] Would upload new file: '{file_name}' to folder ID '{drive_folder_id}'")
            return f"dry_run_file_id_for_{safe_file_name_part.replace(' ', '_')}"

        print(f"  Uploading new file: '{file_name}' to Drive folder ID '{drive_folder_id}'...")
        file_metadata = {
            'name': file_name,
            'parents': [drive_folder_id]
        }
        media = MediaFileUpload(str(local_file_path), resumable=True) # Ensure path is string
        try:
            file = service.files().create(body=file_metadata,
                                          media_body=media,
                                          fields='id, name, modifiedTime').execute()
            print(f"  Uploaded: '{file.get('name')}' (ID: {file.get('id')}), ModTime: {file.get('modifiedTime')}")
            return file.get('id')
        except HttpError as error:
            print(f'  An API error occurred while uploading "{file_name}": {error}')
            return None

def sync_directory_recursive(service, local_dir_path: Path, drive_parent_folder_id: str):
    """
    Recursively syncs a local directory to a Google Drive folder.
    """
    print(f"\nProcessing local directory: '{local_dir_path}' -> Drive Folder ID: '{drive_parent_folder_id}'")

    # 1. Get items from Google Drive in the current parent folder
    drive_items_map = {}
    # Avoid querying Drive if the parent_id is a dry_run placeholder and DRY_RUN is active
    if not (DRY_RUN and drive_parent_folder_id and drive_parent_folder_id.startswith("dry_run_")):
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
            return # Stop processing this directory if we can't list its contents
        except Exception as e: # Catch other potential errors like network issues during listing
            print(f"An unexpected error occurred listing Drive items in '{drive_parent_folder_id}': {e}")
            return


    # 2. Iterate over local items (files and directories)
    try:
        # Ensure local_dir_path still exists before iterating
        if not local_dir_path.exists():
            print(f"  Local directory '{local_dir_path}' no longer exists. Skipping.")
            return
        local_items_iterator = local_dir_path.iterdir()
    except PermissionError:
        print(f"  Permission denied reading local directory: {local_dir_path}. Skipping.")
        return
    except FileNotFoundError: # Should be caught by the .exists() check above, but good for safety
        print(f"  Local directory not found (possibly deleted during sync?): {local_dir_path}. Skipping.")
        return


    for local_item_path in local_items_iterator:
        local_item_name = local_item_path.name

        if local_item_name.startswith('.'): # Skip hidden files/folders
            print(f"  Skipping hidden item: {local_item_path}")
            continue
        
        # Skip specific problematic files if necessary (e.g., system files)
        if local_item_name.lower() in ['thumbs.db', '$recycle.bin', '.ds_store']:
            print(f"  Skipping system file: {local_item_path}")
            continue

        existing_drive_item = drive_items_map.get(local_item_name)

        try:
            if local_item_path.is_file():
                print(f"  Checking local file: '{local_item_name}'")
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
                        print(f"  CONFLICT: Local directory '{local_item_name}' but Drive has a FILE with the same name. Skipping sync for this directory.")
                        continue 
                else:
                    print(f"  Local directory '{local_item_name}' not found in Drive. Creating...")
                    drive_subdir_id = create_drive_folder(service, local_item_name, drive_parent_folder_id)

                if drive_subdir_id: 
                    sync_directory_recursive(service, local_item_path, drive_subdir_id)
                else:
                    print(f"  Could not obtain Drive folder ID for '{local_item_name}'. Skipping sync for this directory.")
        except FileNotFoundError: # If file/dir is deleted mid-process
            print(f"  Local item not found (possibly deleted during sync?): {local_item_path}. Skipping.")
            continue
        except PermissionError:
            print(f"  Permission denied accessing local item: {local_item_path}. Skipping.")
            continue
        except Exception as e: # Catch-all for other unexpected errors for this item
            print(f"  An unexpected error occurred processing local item {local_item_path}: {e}. Skipping.")
            continue


def main():
    """Main function to run the sync process."""
    print("Starting Google Drive Sync...")
    if DRY_RUN:
        print("!!!!!!!!!!!!!! DRY RUN MODE ENABLED !!!!!!!!!!!!!!")
        print("No actual changes will be made to your Google Drive.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")

    # --- Get local documents path ---
    default_docs_path_str = str(Path.home() / "Documents")
    local_documents_path_str = input(f"Enter path to local directory to sync (default: '{default_docs_path_str}'): ")
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

    sync_directory_recursive(service, local_documents_path, drive_root_backup_folder_id)

    print("\n------------------------------------")
    print("Synchronization process finished.")
    if DRY_RUN:
        print("DRY RUN was enabled. No actual changes were made.")
    print("------------------------------------")

if __name__ == '__main__':
    import base64 # Required for generate_key_from_password
    # Attempt to import dateutil.parser for robust ISO date parsing.
    # This is a common library, but if not present, the script might have issues with some date formats.
    try:
        from dateutil import parser
    except ImportError:
        print("Warning: 'python-dateutil' library not found. `pip install python-dateutil` for more robust date parsing.")
        print("The script will attempt to parse dates without it, but might be less flexible.")
    main()
