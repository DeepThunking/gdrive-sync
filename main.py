# main.py (or your main script file)
import argparse
from classes.ConfigLoader import ConfigLoader
from classes.GoogleDriveService import GoogleDriveService
from classes.SyncManager import SyncManager
# Assuming the classes are in a module named 'gdrive_sync_oop' or individual files
# For this example, let's assume they are defined in the same file or imported.
# from gdrive_sync_classes import GoogleDriveService, ConfigLoader, SyncManager

def main():
    parser = argparse.ArgumentParser(description="Synchronize files with Google Drive.")
    parser.add_argument('--config', default='config.json', help='Path to the configuration file.')
    # Add other command-line arguments to override config if needed
    # e.g., --local-dir, --drive-folder, --direction, --dry-run
    parser.add_argument('--local-dir', help='Override local sync directory from config.')
    parser.add_argument('--drive-folder', help='Override Drive sync folder name from config.')
    parser.add_argument('--direction', choices=['up', 'down', 'two-way'], help='Override sync direction from config.')
    parser.add_argument('--dry-run', action='store_true', default=None, help='Perform a dry run, no actual changes will be made.') # Default None to distinguish from False
    parser.add_argument('--no-dry-run', action='store_false', dest='dry_run', help='Ensure dry run is off (overrides config if it was true).')


    args = parser.parse_args()

    print("Loading configuration...")
    config_loader = ConfigLoader(config_file_path=args.config)
    if not config_loader.settings:
        print("Failed to load configuration. Exiting.")
        return

    # Override config with command-line arguments if provided
    if args.local_dir:
        config_loader.settings['local_sync_directory'] = args.local_dir
    if args.drive_folder:
        config_loader.settings['drive_sync_folder_name'] = args.drive_folder
    if args.direction:
        config_loader.settings['sync_direction'] = args.direction
    if args.dry_run is not None: # If --dry-run or --no-dry-run was used
        config_loader.settings['dry_run'] = args.dry_run
    elif 'dry_run' not in config_loader.settings: # Set a default if not in config and not in args
        config_loader.settings['dry_run'] = False


    print("Initializing Google Drive Service...")
    # Use credentials/token paths from config if they exist
    gdrive_service = GoogleDriveService(
        credentials_file=config_loader.get_setting('credentials_file', 'credentials.json'),
        token_file=config_loader.get_setting('token_file', 'token.pickle')
    )

    if not gdrive_service.service:
        print("Failed to initialize Google Drive service. Exiting.")
        return

    print("Initializing Sync Manager...")
    try:
        sync_manager = SyncManager(config_loader=config_loader, drive_service=gdrive_service)
        print(f"Local base path: {sync_manager.local_base_path}")
        print(f"Drive base folder name: {sync_manager.drive_base_folder_name}")
        
        sync_manager.run()

    except ValueError as ve:
        print(f"Error during SyncManager initialization: {ve}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        # import traceback
        # traceback.print_exc() # For debugging

if __name__ == '__main__':
    main()