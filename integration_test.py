import unittest
import os
import shutil
import time
import subprocess
import tempfile
from unittest.mock import patch
import sys

# Add current dir to path to import main
sys.path.append(os.getcwd())
try:
    import main
except ImportError:
    # If running from a subdir or if main is not found, try adding parent
    sys.path.append(os.path.dirname(os.getcwd()))
    import main

class TestSFTPAction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("Starting SFTP Server...")
        try:
            subprocess.run(["docker-compose", "up", "-d"], check=True)
        except subprocess.CalledProcessError:
            print("Failed to start docker-compose. Make sure docker is running.")
            sys.exit(1)
        
        # Wait for server to be ready
        print("Waiting for SFTP server to be ready...")
        time.sleep(5) # Give it a few seconds
        
        # Ensure local test remote dir exists (created by docker usually)
        os.makedirs("test_remote", exist_ok=True)
        
    @classmethod
    def tearDownClass(cls):
        print("Stopping SFTP Server...")
        subprocess.run(["docker-compose", "down"], check=True)
        
        # Clean up test_remote (might need docker to remove if owned by root)
        subprocess.run(["docker", "run", "--rm", "-v", f"{os.getcwd()}:/work", "alpine", "rm", "-rf", "/work/test_remote"], check=False)
        if os.path.exists("test_remote"):
             try:
                 shutil.rmtree("test_remote")
             except:
                 pass

    def setUp(self):
        self.local_dir = tempfile.mkdtemp()
        self.test_remote_subdir = "upload" # This maps to ./test_remote locally
        
        # Clear remote dir content before each test
        # We can do this by deleting ./test_remote/* locally (if permissions allow)
        # or using docker to clean it.
        subprocess.run(["docker", "run", "--rm", "-v", f"{os.getcwd()}:/work", "alpine", "sh", "-c", "rm -rf /work/test_remote/*"], check=False)

    def tearDown(self):
        if os.path.exists(self.local_dir):
            shutil.rmtree(self.local_dir)

    def create_file(self, path, content="test content"):
        full_path = os.path.join(self.local_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

    def run_action(self, **env_vars):
        default_env = {
            'INPUT_HOST': 'localhost',
            'INPUT_PORT': '2222',
            'INPUT_USERNAME': 'testuser',
            'INPUT_PASSWORD': 'testpass',
            'INPUT_LOCALDIR': self.local_dir,
            'INPUT_REMOTEDIR': self.test_remote_subdir,
            'INPUT_DRYRUN': 'false',
            'INPUT_FORCEUPLOAD': 'false',
            'INPUT_REMOVEEXTRAFILESONSERVER': 'false',
            'INPUT_CONCURRENCY': '1', # Use 1 for deterministic tests
        }
        default_env.update(env_vars)
        
        with patch.dict(os.environ, default_env):
            # Capture stdout to avoid cluttering test output, or let it print for debug
            try:
                main.main()
            except SystemExit as e:
                if e.code != 0:
                    raise

    def check_remote_file(self, path, content=None):
        """Check if file exists in ./test_remote (which is mapped to remote /upload)"""
        local_check_path = os.path.join("test_remote", path)
        self.assertTrue(os.path.exists(local_check_path), f"File {path} not found on remote")
        
        if content is not None:
            with open(local_check_path, "r") as f:
                self.assertEqual(f.read(), content, f"Content mismatch for {path}")

    def check_remote_file_not_exists(self, path):
        local_check_path = os.path.join("test_remote", path)
        self.assertFalse(os.path.exists(local_check_path), f"File {path} exists on remote but shouldn't")

    def test_basic_upload(self):
        print("\n--- Test: Basic Upload ---")
        self.create_file("file1.txt", "content1")
        self.create_file("sub/file2.txt", "content2")
        
        self.run_action()
        
        self.check_remote_file("file1.txt", "content1")
        self.check_remote_file("sub/file2.txt", "content2")
        # Check hash file exists
        self.assertTrue(os.path.exists(os.path.join("test_remote", ".sftp_upload_action_hashes")))

    def test_incremental_upload(self):
        print("\n--- Test: Incremental Upload ---")
        # Initial upload
        self.create_file("file1.txt", "content1")
        self.run_action()
        
        # Get mod time of remote file
        remote_file = os.path.join("test_remote", "file1.txt")
        mtime1 = os.path.getmtime(remote_file)
        
        time.sleep(1.1) # Ensure filesystem time difference
        
        # Modify file
        self.create_file("file1.txt", "content1_modified")
        self.run_action()
        
        mtime2 = os.path.getmtime(remote_file)
        self.assertNotEqual(mtime1, mtime2, "File should have been updated")
        self.check_remote_file("file1.txt", "content1_modified")
        
        # Run again with no change
        time.sleep(1.1)
        self.run_action()
        mtime3 = os.path.getmtime(remote_file)
        self.assertEqual(mtime2, mtime3, "File should NOT have been updated")

    def test_delete_extra_files(self):
        print("\n--- Test: Delete Extra Files ---")
        # Initial upload
        self.create_file("keep.txt", "keep")
        self.create_file("delete.txt", "delete")
        self.run_action()
        
        # Remove local file
        os.remove(os.path.join(self.local_dir, "delete.txt"))
        
        # Run with remove enabled
        self.run_action(INPUT_REMOVEEXTRAFILESONSERVER='true')
        
        self.check_remote_file("keep.txt")
        self.check_remote_file_not_exists("delete.txt")

    def test_exclude(self):
        print("\n--- Test: Exclude ---")
        self.create_file("normal.txt", "normal")
        self.create_file("ignore.tmp", "ignore")
        
        self.run_action(INPUT_EXCLUDE='*.tmp')
        
        self.check_remote_file("normal.txt")
        self.check_remote_file_not_exists("ignore.tmp")
        
    def test_dry_run(self):
        print("\n--- Test: Dry Run ---")
        self.create_file("test.txt", "test")
        
        self.run_action(INPUT_DRYRUN='true')
        
        self.check_remote_file_not_exists("test.txt")

if __name__ == "__main__":
    unittest.main()
