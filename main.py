import os
import sys
import argparse
import time
import threading
import queue

# Set stdout to be line buffered so logs appear immediately
sys.stdout.reconfigure(line_buffering=True)

from utils import HashManager, compute_file_hash, scan_directory
from sftp_client import SFTPClientWrapper, upload_file_with_client, ensure_dir_exists

def worker_task(worker_id, client_wrapper, task_queue, result_queue, error_list, local_dir, remote_dir, dry_run, hash_manager, force_upload):
    """
    Worker thread to process upload and delete tasks using a persistent SFTP connection.
    Also handles hash computation and checking.
    """
    try:
        # Create a new SFTP client/channel for this worker
        sftp = client_wrapper.create_sftp()
    except Exception as e:
        print(f"[Worker {worker_id}] Failed to create SFTP client: {e}")
        error_list.append(e)
        return

    dir_cache = set()

    try:
        while True:
            try:
                task = task_queue.get_nowait()
            except queue.Empty:
                break
            
            # Unpack task
            if isinstance(task, tuple):
                action, rel_path = task
            else:
                action = 'upload'
                rel_path = task

            if action == 'delete':
                print(f"[Worker {worker_id}] Processing Delete: {rel_path}")
                remote_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
                
                try:
                    if dry_run:
                        print(f"[Worker {worker_id}] Dry run: Would remove {rel_path}")
                    else:
                        print(f"[Worker {worker_id}] Removing: {rel_path}")
                        try:
                            sftp.remove(remote_path)
                            print(f"[Worker {worker_id}] Removed: {rel_path}")
                        except IOError as e:
                            # If file doesn't exist, that's fine
                            print(f"[Worker {worker_id}] Warning: Failed to remove {rel_path} (maybe already gone): {e}")
                except Exception as e:
                     print(f"[Worker {worker_id}] Error removing {rel_path}: {e}")
                     error_list.append(e)
                finally:
                    task_queue.task_done()
                continue

            # Default action: upload
            print(f"[Worker {worker_id}] Processing Upload: {rel_path}")
            local_path = os.path.join(local_dir, rel_path)
            remote_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
            remote_parent = os.path.dirname(remote_path)
            
            try:
                # Compute local hash
                current_hash = compute_file_hash(local_path)
                result_queue.put((rel_path, current_hash))
                print(f"[Worker {worker_id}] Computed hash: {current_hash} for: {rel_path}")

                # Check if skip
                remote_hash = hash_manager.get_remote_hash(rel_path)
                
                if not force_upload and remote_hash == current_hash:
                    # Hash match, skip
                    print(f"[Worker {worker_id}] Skipped (no change): {rel_path}")
                    continue

                if dry_run:
                    print(f"[Worker {worker_id}] Dry run: Uploading {rel_path}")
                    continue

                print(f"[Worker {worker_id}] Uploading: {rel_path}")
                ensure_dir_exists(sftp, remote_parent, dir_cache)
                upload_file_with_client(sftp, local_path, remote_path)
                print(f"[Worker {worker_id}] Done: {rel_path}")

            except Exception as e:
                print(f"[Worker {worker_id}] Error processing {rel_path}: {e}")
                error_list.append(e)
            finally:
                task_queue.task_done()
    finally:
        if sftp:
            sftp.close()

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

    client = None
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

        # 4. Parallel Process (Hash & Upload)
        print(f"Starting processing with {concurrency} workers...")
        start_time = time.time()

        task_queue = queue.Queue()
        # Add upload tasks
        for rel_path in local_files:
            task_queue.put(('upload', rel_path))
        
        # Add delete tasks if enabled
        if remove_extra_files:
            # Files in remote hash but not in local files
            remote_tracked_files = set(hash_manager.hashes.keys())
            local_files_set = set(local_files)
            files_to_delete = list(remote_tracked_files - local_files_set)
            
            if files_to_delete:
                print(f"Found {len(files_to_delete)} files to delete (from hash records).")
                for rel_path in files_to_delete:
                    task_queue.put(('delete', rel_path))
            else:
                 print("No files to delete based on hash records.")
        
        result_queue = queue.Queue()
        threads = []
        error_list = []
        
        for i in range(concurrency):
            t = threading.Thread(target=worker_task, args=(i+1, client, task_queue, result_queue, error_list, local_dir, remote_dir, dry_run, hash_manager, force_upload))
            t.start()
            threads.append(t)
            
        for t in threads:
            t.join()
            
        if error_list:
            print(f"Upload/Hash check completed with {len(error_list)} errors.")
            sys.exit(1)

        # Collect results
        new_hashes = {}
        while not result_queue.empty():
            rel_path, h = result_queue.get()
            new_hashes[rel_path] = h

        duration = time.time() - start_time
        print(f"Processing completed in {duration:.2f}s")

        # 7. (Removed) Extra Files Cleanup is now handled in worker tasks


        # 8. Update Remote Hash File
        print("Updating remote hash file...")
        # We update the manager with ALL current local files (sync state)
        for rel_path, h in new_hashes.items():
            hash_manager.update_local_hash(rel_path, h)
        
        # Note: This logic only Adds/Updates. It doesn't remove deleted files from hash list.
        # If we want to clean up hash list for files that no longer exist locally:
        hash_manager.hashes = new_hashes 
        
        if not dry_run:
            client.upload_hashes(hash_file_remote_path, hash_manager.to_json())
            print("Done.")
        else:
            print("Dry run: Would update remote hash file.")
            print("Done.")

    finally:
        if client:
            client.close()

if __name__ == "__main__":
    main()
