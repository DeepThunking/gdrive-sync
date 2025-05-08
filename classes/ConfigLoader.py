import json

class ConfigLoader:
    def __init__(self, config_file_path='config.json'):
        self.config_file_path = config_file_path
        self.settings = self._load_config()

    def _load_config(self):
        try:
            with open(self.config_file_path, 'r') as f:
                config = json.load(f)
                # Basic validation can be added here
                if 'local_sync_directory' not in config:
                    raise ValueError("Config missing 'local_sync_directory'")
                if 'drive_sync_folder_name' not in config:
                    raise ValueError("Config missing 'drive_sync_folder_name'")
                # Add more checks as needed (sync_direction, credentials_file, etc.)
                return config
        except FileNotFoundError:
            print(f"Error: Configuration file '{self.config_file_path}' not found.")
            # You might want to create a default config here or exit
            return None # Or raise an exception
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from '{self.config_file_path}'.")
            return None # Or raise an exception
        except ValueError as ve:
            print(f"Configuration Error: {ve}")
            return None

    def get_setting(self, key, default=None):
        if self.settings:
            return self.settings.get(key, default)
        return default

    # Convenience properties (optional)
    @property
    def local_sync_directory(self):
        return self.get_setting('local_sync_directory')

    @property
    def drive_sync_folder_name(self):
        return self.get_setting('drive_sync_folder_name')
    
    @property
    def credentials_file(self):
        return self.get_setting('credentials_file', 'credentials.json')

    @property
    def token_file(self):
        return self.get_setting('token_file', 'token.pickle')

    @property
    def sync_direction(self):
        return self.get_setting('sync_direction', 'two-way') # Example default

    @property
    def conflict_resolution(self):
        return self.get_setting('conflict_resolution', 'newer_wins') # Example default

    @property
    def dry_run(self):
        return self.get_setting('dry_run', False)