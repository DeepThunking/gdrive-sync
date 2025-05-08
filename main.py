from auth import GoogleDriveAuthenticator
from drive_client import DriveClient
from sync_manager import DriveSyncManager
from crypto_utils import CryptoUtils

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def main():
    creds = GoogleDriveAuthenticator('credentials.json', 'token.json', SCOPES).authenticate()
    drive_client = DriveClient(creds)
    crypto_utils = CryptoUtils()  # Comment this out if you don't want encryption
    sync_manager = DriveSyncManager(drive_client, './downloads', crypto_utils=crypto_utils)
    sync_manager.sync_folder('<YOUR_FOLDER_ID>')  # Replace with your folder ID

if __name__ == '__main__':
    main()