# Python Google Drive Sync (Rsync-like)

## Description

This Python script provides a way to synchronize a local directory (e.g., your "Documents" folder) with a specified folder in Google Drive. It aims to emulate some functionalities of `rsync`, such as recursive directory syncing, updating modified files, and creating new files/folders in the destination.

The script uses the Google Drive API v3 for interactions with Google Drive and includes a feature to encrypt your `credentials.json` file for enhanced security, allowing the encrypted version to be (more) safely committed to source control.

## Features

* **Recursive Sync:** Synchronizes entire directory trees.
* **File & Folder Creation:** Creates new files and folders in Google Drive that exist locally.
* **File Updates:** Updates files in Google Drive if the local version is newer or different.
    * Compares modification timestamps and file sizes.
    * Optional MD5 hash comparison (`COMPARE_HASHES = True`) for more robust change detection.
* **Google Drive API:** Uses the official Google Drive API.
* **OAuth 2.0 Authentication:** Securely authenticates with your Google Account.
* **Credentials Encryption:**
    * Prompts to encrypt the `credentials.json` file using a user-provided password.
    * Stores encrypted credentials in `credentials.json.enc`.
    * Decrypts credentials in memory on-the-fly during script execution.
* **Dry Run Mode:** Allows you to see what changes would be made without actually modifying your Google Drive (`DRY_RUN = True`).
* **Token Storage:** Saves OAuth 2.0 tokens in `token.json` for subsequent runs, avoiding repeated browser authentication (unless the token expires or scopes change).

## Prerequisites

1.  **Python:** Python 3.7+ is recommended.
2.  **pip:** Python package installer.
3.  **Google Cloud Project:**
    * A Google Cloud Platform project with the **Google Drive API enabled**.
    * OAuth 2.0 credentials (client ID and client secret) downloaded as a `credentials.json` file.

## Installation

1.  **Clone the repository or download the script.**

2.  **Install required Python libraries:**
    ```bash
    pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib cryptography python-dateutil
    ```

## Configuration

1.  **`credentials.json` (Google Drive API Setup):**
    * Go to the [Google Cloud Console](https://console.cloud.google.com/).
    * Create a new project or select an existing one.
    * Enable the "Google Drive API" for your project.
    * Create OAuth 2.0 credentials for a "Desktop app".
    * Download the credentials JSON file and save it as `credentials.json` in the same directory as the script.

2.  **Script Settings (at the top of the Python script):**
    * `DRY_RUN = True` or `False`:
        * `True`: (Default) Prints actions that would be taken without making changes. Highly recommended for initial runs.
        * `False`: Performs actual uploads, updates, and folder creations on Google Drive.
    * `DRIVE_BACKUP_ROOT_FOLDER_NAME = "My Documents Backup (Python)"`: The name of the main folder to be created/used in your Google Drive root for this backup. You can change this to your preference.
    * `COMPARE_HASHES = False` or `True`:
        * `False`: (Default) Relies on modification time and size for detecting changes. Faster.
        * `True`: Additionally compares MD5 hashes of local files with Google Drive's `md5Checksum` if timestamps and sizes are inconclusive. More robust but slower, especially for many/large files.

## Usage

1.  **Place `credentials.json`:** Ensure the `credentials.json` file (downloaded from Google Cloud Console) is in the same directory as the Python script.

2.  **Run the script from your terminal:**
    ```bash
    python your_script_name.py
    ```
    (Replace `your_script_name.py` with the actual name of the script file).

3.  **First Run & Credentials Encryption:**
    * The script will detect the unencrypted `credentials.json`.
    * It will ask if you want to encrypt it. If you choose `y` (yes):
        * You will be prompted to enter and confirm a strong password. This password will be used to encrypt `credentials.json` and create `credentials.json.enc`.
        * **IMPORTANT:** After successful encryption, the script will remind you to **MANUALLY DELETE** the original unencrypted `credentials.json` file for security.
    * **Google Authentication:** A web browser window will open, asking you to log in to your Google account and authorize the script to access your Google Drive. Grant permission.
    * Upon successful authorization, a `token.json` file will be created. This stores your access/refresh tokens so you don't need to re-authorize through the browser every time.

4.  **Subsequent Runs:**
    * If `credentials.json.enc` exists, the script will prompt you for the password you set during the encryption step.
    * It will then use the stored `token.json` (if valid) or the decrypted credentials to authenticate and proceed with the sync.

5.  **Local Directory Path:**
    * The script will ask for the full path to your local directory that you want to sync (e.g., your "Documents" folder).
    * You can press Enter to use the default path (usually `~/Documents` on Linux/macOS or `C:\Users\YourUser\Documents` on Windows).

## Security Notes

* **`credentials.json` (Unencrypted):** This file contains sensitive API client secrets. **DO NOT** commit the unencrypted `credentials.json` to source control. Delete it after `credentials.json.enc` has been created.
* **`credentials.json.enc` (Encrypted):** This file can be committed to source control *if you are comfortable with the security of the encryption password you chose*. The security of this file relies on the strength of your password and the Fernet encryption algorithm.
* **`token.json`:** This file contains your OAuth 2.0 access and refresh tokens. It allows the script to access your Google Drive without re-prompting for your Google password. **DO NOT** commit `token.json` to source control. Add it to your `.gitignore` file.
* **Encryption Password:** Choose a strong, unique password for encrypting `credentials.json`. If you forget this password, you will not be able to decrypt `credentials.json.enc` and will need to re-create it from a fresh `credentials.json`.

## `.gitignore` Recommendations

Create a `.gitignore` file in your project directory with the following content to prevent committing sensitive files and cache:



Google OAuth credentials and tokens
credentials.json
token.json
Python cache
pycache/
*.pyc
*.pyo



## Potential Future Enhancements

* Implement deletion of orphaned files/folders in Google Drive (i.e., items that exist in Drive but not locally). This would require a new flag and careful implementation to prevent accidental data loss.
* Add more sophisticated logging (e.g., to a file).
* Allow configuration via a separate config file instead of hardcoding settings.
* Support for multiple backup profiles/configurations.

## License