import os
import datetime
from dateutil import parser as dateutil_parser # For parsing Drive's RFC 3339 datetime strings
from ConfigLoader import ConfigLoader
from GoogleDriveService import GoogleDriveService
# Helper function (could be a static method in SyncManager or a utility function)
def get_local_file_mtime(local_path):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(local_path), tz=datetime.timezone.utc)
    except FileNotFoundError:
        return None

class SyncManager:
    def __init__(self, config_loader: ConfigLoader, drive_service: GoogleDriveService):
        self.config = config_loader
        self.drive_service = drive_service
        
        if not self.config.settings:
            raise ValueError("Configuration not loaded properly.")
        if not self.drive_service or not self.drive_service.service:
            raise ValueError("Google Drive service not initialized properly.")

        self.local_base_path = os.path.expanduser(self.config.local_sync_directory)
        self.drive_base_folder_name = self.config.drive_sync_folder_name
        self.drive_base_folder_id = None # To be fetched or created

        self.sync_direction = self.config.sync_direction
        self.conflict_resolution = self.config.conflict_resolution # e.g., 'local_wins', 'remote_wins', 'newer_wins', 'skip'
        self.dry_run = self.config.dry_run

        print(f"Sync Manager initialized: Dry Run mode is {'ON' if self.dry_run else 'OFF'}")


    def _ensure_drive_base_folder_exists(self):
        """Ensures the base sync folder exists on Drive and sets self.drive_base_folder_id."""
        if self.drive_base_folder_id:
            return self.drive_base_folder_id

        folder_id = self.drive_service.get_folder_id(self.drive_base_folder_name, 'root')
        if not folder_id:
            print(f"Base Drive folder '{self.drive_base_folder_name}' not found. Attempting to create it.")
            if not self.dry_run:
                folder_id = self.drive_service.create_folder(self.drive_base_folder_name, 'root')
                if not folder_id:
                    raise Exception(f"Failed to create base Drive folder '{self.drive_base_folder_name}'.")
            else:
                print(f"[DRY RUN] Would create base Drive folder '{self.drive_base_folder_name}'.")
                # In dry run, we can't proceed without a folder ID if it doesn't exist.
                # For a more robust dry run, you might need to simulate ID creation or skip operations dependent on it.
                # Or, assume it exists for the purpose of listing what *would* happen.
                # For now, let's raise an error or return a special value if it's critical.
                print("Cannot proceed with sync without base Drive folder in dry run if it doesn't exist.")
                return None 
        
        self.drive_base_folder_id = folder_id
        print(f"Using Drive folder: '{self.drive_base_folder_name}' (ID: {self.drive_base_folder_id})")
        return folder_id

    def _get_drive_path_id(self, relative_drive_path):
        """
        Given a relative path (e.g., "subdir1/file.txt" or "subdir1/subdir2"),
        finds or creates the necessary folders and returns the ID of the final component.
        If the path points to a file, it returns the parent folder's ID and the file name.
        If it points to a folder, it returns that folder's ID.
        This is a complex part, as it mirrors ensure_dir_exists and get_folder_id.
        """
        if not self._ensure_drive_base_folder_exists(): # Ensure base folder ID is set
             return None, None # Or handle error more gracefully

        parts = [p for p in relative_drive_path.split(os.path.sep) if p]
        current_parent_id = self.drive_base_folder_id
        
        # Traverse or create folders
        for i, part_name in enumerate(parts[:-1]): # All parts except the last one are folders
            folder_id = self.drive_service.get_folder_id(part_name, current_parent_id)
            if not folder_id:
                if not self.dry_run:
                    print(f"Creating Drive folder '{part_name}' under parent ID {current_parent_id}...")
                    folder_id = self.drive_service.create_folder(part_name, current_parent_id)
                    if not folder_id:
                        print(f"Failed to create Drive folder '{part_name}'.")
                        return None, None # Indicate failure
                else:
                    print(f"[DRY RUN] Would create Drive folder '{part_name}' under parent ID {current_parent_id}.")
                    # For dry run, we can't get a real ID. This makes further steps difficult.
                    # We might need to simulate this path. For now, let's assume it can't find/create.
                    return "simulated_parent_id_for_dry_run_folder_" + part_name, parts[-1] if len(parts) > 0 else None


            current_parent_id = folder_id
        
        # The last part could be a file or a folder
        final_component_name = parts[-1] if parts else None
        return current_parent_id, final_component_name


    def sync_to_drive(self, local_start_path=None, drive_target_folder_id=None):
        """
        Synchronizes a local directory (or subdirectory) to a Google Drive folder.
        Mirrors the logic of the original `sync_directory_to_drive`.
        """
        if local_start_path is None:
            local_start_path = self.local_base_path
        if drive_target_folder_id is None:
            if not self._ensure_drive_base_folder_exists(): # Ensure base folder ID is set and valid
                print("Cannot sync to drive: Base Drive folder ID not available.")
                return
            drive_target_folder_id = self.drive_base_folder_id

        print(f"Starting sync UP: Local '{local_start_path}' to Drive Folder ID '{drive_target_folder_id}'")

        # Get remote items once for the current Drive folder
        # print(f"Listing items in Drive folder ID: {drive_target_folder_id}...")
        remote_items_list = self.drive_service.list_folder_contents(drive_target_folder_id)
        remote_items_map = {item['name']: item for item in remote_items_list}
        # print(f"Found {len(remote_items_map)} items in remote folder.")


        for local_item_name in os.listdir(local_start_path):
            local_item_path = os.path.join(local_start_path, local_item_name)
            remote_item_metadata = remote_items_map.get(local_item_name)

            if os.path.isdir(local_item_path):
                drive_folder_id = None
                if remote_item_metadata and remote_item_metadata['mimeType'] == 'application/vnd.google-apps.folder':
                    drive_folder_id = remote_item_metadata['id']
                    # print(f"Folder '{local_item_name}' exists on Drive with ID: {drive_folder_id}.")
                else:
                    if remote_item_metadata: # It exists but is not a folder, name collision
                        print(f"Warning: Local item '{local_item_name}' is a directory, but a file with the same name exists on Drive. Skipping folder sync for this item.")
                        continue 
                    
                    print(f"Folder '{local_item_name}' not found on Drive in folder ID '{drive_target_folder_id}'.")
                    if not self.dry_run:
                        print(f"Creating folder '{local_item_name}' on Drive...")
                        drive_folder_id = self.drive_service.create_folder(local_item_name, drive_target_folder_id)
                        if not drive_folder_id:
                            print(f"Failed to create folder '{local_item_name}' on Drive. Skipping.")
                            continue
                    else:
                        print(f"[DRY RUN] Would create folder '{local_item_name}' on Drive in parent {drive_target_folder_id}.")
                        drive_folder_id = f"simulated_drive_folder_id_for_{local_item_name}" # For recursive dry run

                if drive_folder_id : # If successfully found or created (or simulated)
                    self.sync_to_drive(local_item_path, drive_folder_id) # Recurse

            elif os.path.isfile(local_item_path):
                # print(f"Processing local file: {local_item_path}")
                perform_upload = False
                update_existing = False
                existing_file_id = None

                local_mtime = get_local_file_mtime(local_item_path)

                if remote_item_metadata: # File or folder with this name exists on Drive
                    if remote_item_metadata['mimeType'] == 'application/vnd.google-apps.folder':
                        print(f"Warning: Local item '{local_item_name}' is a file, but a folder with the same name exists on Drive. Skipping file sync for this item.")
                        continue
                    
                    # It's a file on Drive, compare modification times or checksums
                    existing_file_id = remote_item_metadata['id']
                    remote_mtime_str = remote_item_metadata.get('modifiedTime')
                    remote_mtime = dateutil_parser.parse(remote_mtime_str) if remote_mtime_str else None
                    
                    # print(f"Comparing: Local mtime: {local_mtime}, Remote mtime: {remote_mtime} for '{local_item_name}'")

                    if not local_mtime: # Should not happen if file exists
                        print(f"Could not get local modification time for {local_item_path}. Skipping.")
                        continue

                    if remote_mtime:
                        if self.conflict_resolution == 'newer_wins':
                            if local_mtime > remote_mtime:
                                print(f"Local file '{local_item_name}' is newer. Preparing to update on Drive.")
                                perform_upload = True
                                update_existing = True
                            else:
                                print(f"Remote file '{local_item_name}' is newer or same. Skipping upload.")
                        elif self.conflict_resolution == 'local_wins':
                            print(f"Conflict resolution set to 'local_wins'. Preparing to update '{local_item_name}' on Drive.")
                            perform_upload = True
                            update_existing = True
                        elif self.conflict_resolution == 'remote_wins':
                             print(f"Conflict resolution set to 'remote_wins'. Skipping upload for '{local_item_name}'.")
                        elif self.conflict_resolution == 'skip':
                            print(f"Conflict resolution set to 'skip'. Skipping '{local_item_name}'.")
                        # Add more conflict resolution strategies (e.g., based on MD5 if available and not a GDoc)
                        # Note: Drive API's modifiedTime is for the Drive file, not necessarily content mod time for GDocs
                        # For non-GDoc files, md5Checksum is better if available.
                        # remote_md5 = remote_item_metadata.get('md5Checksum')
                        # if remote_md5 and not is_google_doc_type(remote_item_metadata['mimeType']):
                        #    local_md5 = calculate_local_md5(local_item_path) # you'd need this helper
                        #    if local_md5 != remote_md5:
                        #        perform_upload = True; update_existing = True

                    else: # Remote mtime not available, assume local is newer or upload
                        print(f"Remote modification time not available for '{local_item_name}'. Assuming local is to be uploaded.")
                        perform_upload = True
                        update_existing = True # Update if ID is known
                else: # File does not exist on Drive
                    print(f"File '{local_item_name}' not found on Drive. Preparing for new upload.")
                    perform_upload = True
                    update_existing = False
                
                if perform_upload:
                    if not self.dry_run:
                        print(f"{'Updating' if update_existing else 'Uploading new'} file '{local_item_name}' to Drive folder ID '{drive_target_folder_id}'.")
                        self.drive_service.upload_file(
                            local_item_path,
                            drive_target_folder_id, # Parent folder ID
                            drive_file_name=local_item_name,
                            update_existing=update_existing,
                            existing_file_id=existing_file_id
                        )
                    else:
                        if update_existing and existing_file_id:
                            print(f"[DRY RUN] Would update file '{local_item_name}' (ID: {existing_file_id}) on Drive.")
                        else:
                            print(f"[DRY RUN] Would upload new file '{local_item_name}' to Drive folder ID '{drive_target_folder_id}'.")
        # Phase 2: Delete remote files/folders that are not present locally (optional, add a flag for this)
        # for remote_name, remote_meta in remote_items_map.items():
        #     if not os.path.exists(os.path.join(local_start_path, remote_name)):
        #         if self.dry_run:
        #             print(f"[DRY RUN] Would delete '{remote_name}' from Drive (ID: {remote_meta['id']}).")
        #         else:
        #             # self.drive_service.delete_item(remote_meta['id']) # Add delete_item to GoogleDriveService
        #             print(f"Placeholder: Deleting '{remote_name}' from Drive.")


    def sync_from_drive(self, drive_start_folder_id=None, local_target_path=None):
        """
        Synchronizes a Google Drive folder (or subfolder) to a local directory.
        Mirrors the logic of the original `sync_drive_to_directory`.
        """
        if drive_start_folder_id is None:
            if not self._ensure_drive_base_folder_exists():
                print("Cannot sync from Drive: Base Drive folder ID not available.")
                return
            drive_start_folder_id = self.drive_base_folder_id
        
        if local_target_path is None:
            local_target_path = self.local_base_path

        os.makedirs(local_target_path, exist_ok=True)
        print(f"Starting sync DOWN: Drive Folder ID '{drive_start_folder_id}' to Local '{local_target_path}'")

        remote_items = self.drive_service.list_folder_contents(drive_start_folder_id)
        if not remote_items:
            # print(f"No items found in Drive folder ID '{drive_start_folder_id}'.")
            return

        local_items_map = {item_name: os.path.join(local_target_path, item_name) for item_name in os.listdir(local_target_path)}

        for item in remote_items:
            item_name = item['name']
            item_id = item['id']
            item_mime_type = item['mimeType']
            remote_mtime_str = item.get('modifiedTime')
            remote_mtime = dateutil_parser.parse(remote_mtime_str) if remote_mtime_str else None

            local_item_path = os.path.join(local_target_path, item_name)

            if item_mime_type == 'application/vnd.google-apps.folder':
                print(f"Processing Drive folder: '{item_name}' (ID: {item_id})")
                if not os.path.exists(local_item_path):
                    print(f"Local folder '{item_name}' does not exist.")
                    if not self.dry_run:
                        print(f"Creating local directory: {local_item_path}")
                        os.makedirs(local_item_path, exist_ok=True)
                    else:
                        print(f"[DRY RUN] Would create local directory: {local_item_path}")
                elif not os.path.isdir(local_item_path):
                     print(f"Warning: Remote item '{item_name}' is a folder, but a file exists locally at '{local_item_path}'. Skipping.")
                     continue
                # Recurse into the subdirectory
                self.sync_from_drive(item_id, local_item_path)
            else: # It's a file
                # print(f"Processing Drive file: '{item_name}' (ID: {item_id})")
                perform_download = False

                if os.path.exists(local_item_path):
                    if os.path.isdir(local_item_path):
                        print(f"Warning: Remote item '{item_name}' is a file, but a directory exists locally at '{local_item_path}'. Skipping.")
                        continue
                    
                    local_mtime = get_local_file_mtime(local_item_path)
                    # print(f"Comparing: Remote mtime: {remote_mtime}, Local mtime: {local_mtime} for '{item_name}'")

                    if not remote_mtime: # Should generally exist
                        print(f"Remote modification time not available for '{item_name}'. Assuming download is needed if local is older or different by other means.")
                        # This case needs careful handling. For now, let's assume download.
                        perform_download = True
                    elif not local_mtime: # Local file exists but can't get mtime (unlikely)
                         perform_download = True
                    else:
                        if self.conflict_resolution == 'newer_wins':
                            if remote_mtime > local_mtime:
                                print(f"Remote file '{item_name}' is newer. Preparing to download.")
                                perform_download = True
                            else:
                                print(f"Local file '{item_name}' is newer or same. Skipping download.")
                        elif self.conflict_resolution == 'remote_wins':
                            print(f"Conflict resolution set to 'remote_wins'. Preparing to download '{item_name}'.")
                            perform_download = True
                        elif self.conflict_resolution == 'local_wins':
                            print(f"Conflict resolution set to 'local_wins'. Skipping download for '{item_name}'.")
                        elif self.conflict_resolution == 'skip':
                             print(f"Conflict resolution set to 'skip'. Skipping download for '{item_name}'.")
                        # Add MD5 check for non-Google Doc files if available
                        # remote_md5 = item.get('md5Checksum')
                        # if remote_md5 and not is_google_doc_type(item_mime_type):
                        #    local_md5 = calculate_local_md5(local_item_path)
                        #    if local_md5 != remote_md5: perform_download = True
                else: # File does not exist locally
                    print(f"Local file '{item_name}' does not exist. Preparing to download.")
                    perform_download = True

                if perform_download:
                    if not self.dry_run:
                        print(f"Downloading file '{item_name}' (ID: {item_id}) to '{local_item_path}'")
                        # For Google Docs, Sheets, Slides, you need to export them.
                        # The current download_file method in GoogleDriveService downloads the binary content.
                        # If it's a Google Doc, you need to use files().export_media()
                        if item_mime_type.startswith('application/vnd.google-apps'):
                            print(f"Item '{item_name}' is a Google Workspace document ({item_mime_type}). Exporting is more complex and not fully implemented in this basic download.")
                            # You'd need to decide on an export format (e.g., PDF, docx)
                            # and adjust GoogleDriveService.download_file or add an export_file method.
                            # For now, let's just note it.
                            print(f"Skipping download of Google Workspace file '{item_name}' as export logic is needed.")
                            # Example export (conceptual, add to GoogleDriveService):
                            # self.drive_service.export_google_doc(item_id, local_target_path, item_name + '.pdf', 'application/pdf')
                        else:
                            self.drive_service.download_file(item_id, local_target_path, item_name)
                    else:
                        print(f"[DRY RUN] Would download file '{item_name}' (ID: {item_id}) to '{local_item_path}'.")
                        if item_mime_type.startswith('application/vnd.google-apps'):
                             print(f"[DRY RUN] Note: '{item_name}' is a Google Workspace document. Actual download would require export.")
        
        # Phase 2: Delete local files/folders that are not present remotely (optional, add a flag for this)
        # for local_name, local_path_val in local_items_map.items():
        #     if not any(remote_item['name'] == local_name for remote_item in remote_items):
        #         if self.dry_run:
        #             print(f"[DRY RUN] Would delete local item '{local_path_val}'.")
        #         else:
        #             # if os.path.isfile(local_path_val): os.remove(local_path_val)
        #             # elif os.path.isdir(local_path_val): shutil.rmtree(local_path_val)
        #             print(f"Placeholder: Deleting local item '{local_path_val}'.")


    def run(self):
        """Main execution method for the sync manager."""
        if not self._ensure_drive_base_folder_exists() and self.sync_direction != 'down': # If syncing up, we need the base folder. For down, it might be created.
            # Actually, for 'down' as well, we need to know the ID of the folder to sync from.
             print("Failed to ensure base Drive folder. Aborting sync.")
             return

        # The _ensure_drive_base_folder_exists will attempt to create the folder if not in dry_run mode.
        # If it returns None (e.g. in dry_run and folder does not exist, or creation failed),
        # then self.drive_base_folder_id will be None, and subsequent operations should handle this.
        if not self.drive_base_folder_id:
             print(f"Drive base folder '{self.drive_base_folder_name}' could not be confirmed or created. Cannot proceed.")
             return

        print(f"Sync direction: {self.sync_direction}")
        if self.sync_direction == "up":
            self.sync_to_drive(self.local_base_path, self.drive_base_folder_id)
        elif self.sync_direction == "down":
            self.sync_from_drive(self.drive_base_folder_id, self.local_base_path)
        elif self.sync_direction == "two-way":
            print("Performing two-way sync...")
            print("Step 1: Sync local changes to Drive (Uploads/Updates)...")
            self.sync_to_drive(self.local_base_path, self.drive_base_folder_id)
            print("\nStep 2: Sync Drive changes to local (Downloads/Updates)...")
            self.sync_from_drive(self.drive_base_folder_id, self.local_base_path)
            # Note: True two-way sync is complex. It needs to handle:
            # 1. Deletions on one side propagating to the other.
            # 2. Conflicts where a file is modified in both places since last sync.
            #    The current 'newer_wins' helps but might not be sufficient for all cases.
            # 3. Tracking sync state (e.g., last sync time, hashes of files) to avoid
            #    re-comparing/re-transferring everything. This is a major enhancement.
            # The current implementation of two-way is essentially an "up then down" or "down then up".
            # A more robust two-way sync often involves a database or state file.
            print("Basic two-way sync (up then down) complete.")
        else:
            print(f"Unknown sync direction: {self.sync_direction}")

        print("Synchronization process finished.")