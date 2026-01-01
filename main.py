import os
import sys
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import HashManager, compute_file_hash, scan_directory
from sftp_client import SFTPClientWrapper, upload_single_file

def main():
    # Load inputs from environment variables
    host = os.environ.get('INPUT_HOST')
    port = os.environ.get('INPUT_PORT', '22')
    username = os.environ.get('INPUT_USERNAME')
    password = os.environ.get('INPUT_PASSWORD')
    private_key = os.environ.get('INPUT_PRIVATEKEY')
    passphrase = os.environ.get('INPUT_PASSPHRASE')
    local_dir = os.environ.get('INPUT_LOCALDIR')
    remote_dir = os.environ.get('INPUT_REMOTEDIR')
    dry_run = os.environ.get('INPUT_DRYRUN', 'false').lower() == 'true'
    force_upload = os.environ.get('INPUT_FORCEUPLOAD', 'false').lower() == 'true'
    exclude_str = os.environ.get('INPUT_EXCLUDE', '')
    remove_extra_files = os.environ.get('INPUT_REMOVEEXTRAFILESONSERVER', 'false').lower() == 'true'
    concurrency = int(os.environ.get('INPUT_CONCURRENCY', '4'))

    if not host or not username or not local_dir or not remote_dir:
        print("Error: Missing required inputs (host, username, localDir, remoteDir)")
        sys.exit(1)

    # Prepare exclude patterns
    exclude_patterns = [p.strip() for p in exclude_str.split(',') if p.strip()]
    # Always exclude the hash file itself from being uploaded as a regular file
    exclude_patterns.append('.sftp_upload_action_hashes')

    print(f"Starting SFTP Upload to {host}:{port}...")
    print(f"Local Dir: {local_dir}")
    print(f"Remote Dir: {remote_dir}")
    print(f"Concurrency: {concurrency}")

    # 1. Connect
    try:
        client = SFTPClientWrapper(
            host=host, 
            port=port, 
            username=username, 
            password=password, 
            key_data=private_key, 
            passphrase=passphrase
        )
    except Exception as e:
        print(f"Failed to connect: {e}")
        sys.exit(1)

    try:
        # 2. Load Remote Hashes
        hash_file_remote_path = os.path.join(remote_dir, '.sftp_upload_action_hashes').replace('\\', '/')
        hash_manager = HashManager(hash_file_remote_path)
        
        if not force_upload:
            print("Fetching remote hash file...")
            remote_hashes_json = client.download_hashes(hash_file_remote_path)
            if remote_hashes_json:
                hash_manager.load(remote_hashes_json)
                print("Remote hash file loaded.")
            else:
                print("No remote hash file found. Full upload.")

        # 3. Scan Local Files
        print("Scanning local directory...")
        try:
            local_files = scan_directory(local_dir, exclude_patterns)
        except FileNotFoundError as e:
            print(e)
            sys.exit(1)
        
        print(f"Found {len(local_files)} files.")

        # 4. Filter Files (Delta Check)
        upload_tasks = []
        new_hashes = {}

        for rel_path in local_files:
            full_local_path = os.path.join(local_dir, rel_path)
            
            # Compute local hash
            current_hash = compute_file_hash(full_local_path)
            new_hashes[rel_path] = current_hash
            
            # Check if skip
            remote_hash = hash_manager.get_remote_hash(rel_path)
            
            if force_upload or remote_hash != current_hash:
                upload_tasks.append(rel_path)
            else:
                # Hash match, skip
                pass
        
        print(f"Files to upload: {len(upload_tasks)}")

        if dry_run:
            print("Dry run enabled. Skipping actual upload.")
            sys.exit(0)

        if not upload_tasks:
            print("Everything up to date.")
            # Still update hash file? Yes, to keep it fresh or if local deleted files (not handled here yet, but standard)
            # Actually, we should probably update hash file to reflect current state.
            # But if we didn't upload anything, maybe we don't need to. 
            # However, if we want to support "sync" (delete extra), that's another story.
            # The v2 had "removeExtraFilesOnServer". 
            # I should probably respect that if I want full v2 parity, but user didn't emphasize it.
            # I'll skip "removeExtraFiles" for now unless I see it in action.yml. 
            # Wait, action.yml had it? Yes.
            # I removed it from my new action.yml. I should check if I need to add it back.
            # The user said "rewrite... mainly 4 points". I focused on those.
            # I'll stick to upload for now.
            pass
        else:
            # 5. Ensure Remote Directories
            remote_dirs = set()
            for rel_path in upload_tasks:
                remote_rel_dir = os.path.dirname(rel_path)
                if remote_rel_dir:
                    remote_full_dir = os.path.join(remote_dir, remote_rel_dir).replace('\\', '/')
                    remote_dirs.add(remote_full_dir)
            
            # Also ensure base remote dir
            remote_dirs.add(remote_dir)

            print("Ensuring remote directories exist...")
            client.ensure_remote_dirs(remote_dirs)

            # 6. Parallel Upload
            print(f"Starting upload with {concurrency} threads...")
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {}
                for rel_path in upload_tasks:
                    local_path = os.path.join(local_dir, rel_path)
                    remote_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
                    
                    future = executor.submit(upload_single_file, client.transport, local_path, remote_path)
                    futures[future] = rel_path

                for future in as_completed(futures):
                    rel_path = futures[future]
                    try:
                        future.result()
                        print(f"Uploaded: {rel_path}")
                    except Exception as e:
                        print(f"Failed: {rel_path} - {e}")
                        # We might want to fail the whole action or continue?
                        # Usually fail.
                        sys.exit(1)

            duration = time.time() - start_time
            print(f"Upload completed in {duration:.2f}s")

        # 7. Remove Extra Files
        if remove_extra_files:
            print("Checking for extra files on server...")
            try:
                # Get all remote files and directories
                remote_files_list = client.list_remote_files_recursively(remote_dir)
                remote_files_set = set(remote_files_list)
                
                # Files we expect to be there: local files + hash file
                expected_items = set(local_files)
                expected_items.add('.sftp_upload_action_hashes')
                
                # Also add all parent directories of local files to expected_items
                for rel_path in local_files:
                    path_parts = rel_path.split('/')
                    # Iterate through all parent directories
                    for i in range(len(path_parts) - 1):
                        parent_dir = '/'.join(path_parts[:i+1])
                        expected_items.add(parent_dir)
                
                # Determine extra items
                extra_items = remote_files_set - expected_items
                
                if extra_items:
                    print(f"Found {len(extra_items)} extra items. Removing...")
                    # Sort by length descending to delete deep items first
                    sorted_extra_items = sorted(list(extra_items), key=len, reverse=True)
                    
                    for rel_path in sorted_extra_items:
                        full_remote_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
                        if not dry_run:
                            client.delete_file(full_remote_path)
                            print(f"Removed: {rel_path}")
                        else:
                            print(f"Would remove: {rel_path}")
                else:
                    print("No extra files found.")
            except Exception as e:
                print(f"Warning: Failed to remove extra files: {e}")

        # 8. Update Remote Hash File
        print("Updating remote hash file...")
        # We update the manager with ALL current local files (sync state)
        for rel_path, h in new_hashes.items():
            hash_manager.update_local_hash(rel_path, h)
        
        # Note: This logic only Adds/Updates. It doesn't remove deleted files from hash list.
        # If we want to clean up hash list for files that no longer exist locally:
        hash_manager.hashes = new_hashes 
        
        client.upload_hashes(hash_file_remote_path, hash_manager.to_json())
        print("Done.")

    finally:
        if client:
            client.close()

if __name__ == "__main__":
    main()
