import os
import hashlib
import fnmatch
import json

class HashManager:
    def __init__(self, hash_file_path):
        self.hash_file_path = hash_file_path
        self.hashes = {}

    def load(self, json_content):
        try:
            if json_content:
                self.hashes = json.loads(json_content)
        except Exception as e:
            print(f"Warning: Failed to parse remote hash file: {e}")
            self.hashes = {}

    def get_remote_hash(self, relative_path):
        return self.hashes.get(relative_path)

    def update_local_hash(self, relative_path, file_hash):
        self.hashes[relative_path] = file_hash

    def to_json(self):
        return json.dumps(self.hashes, indent=2)

def compute_file_hash(filepath):
    """Compute MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except FileNotFoundError:
        return None

def scan_directory(local_dir, exclude_patterns=None):
    """
    Scan directory and return list of relative paths.
    """
    file_list = []
    local_dir = os.path.abspath(local_dir)
    
    if not os.path.exists(local_dir):
        raise FileNotFoundError(f"Local directory not found: {local_dir}")

    for root, dirs, files in os.walk(local_dir):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, local_dir)
            
            # Normalize path separators to forward slash for consistency
            rel_path = rel_path.replace(os.sep, '/')
            
            if exclude_patterns:
                # Check if matches any exclude pattern
                matched = False
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(rel_path, pattern):
                        matched = True
                        break
                if matched:
                    continue
            
            file_list.append(rel_path)
            
    return file_list
