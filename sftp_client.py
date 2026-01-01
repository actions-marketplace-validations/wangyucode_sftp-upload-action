import os
import paramiko
import stat
import time

class SFTPClientWrapper:
    def __init__(self, host, port, username, password=None, key_data=None, passphrase=None):
        self.transport = paramiko.Transport((host, int(port)))
        self.transport.use_compression(True) # Enable compression if supported
        
        if key_data:
            pkey = self._load_private_key(key_data, passphrase)
            self.transport.connect(username=username, pkey=pkey)
        else:
            self.transport.connect(username=username, password=password)
            
    def _load_private_key(self, key_data, passphrase):
        import io
        
        # Determine if key_data is a path or content
        if os.path.exists(key_data):
            # It's a file path
            with open(key_data, 'r') as f:
                key_content = f.read()
        else:
            # It's content
            key_content = key_data

        # Try different key types
        key_classes = [
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey
        ]
        
        # Also try DSS if available
        try:
            from paramiko.dsskey import DSSKey
            key_classes.append(DSSKey)
        except ImportError:
            pass

        for key_class in key_classes:
            try:
                key_file = io.StringIO(key_content)
                return key_class.from_private_key(key_file, password=passphrase)
            except Exception:
                continue
        
        # If we get here, we failed to load the key
        raise ValueError("Could not load private key. Supported types: RSA, Ed25519, ECDSA, DSS.")

            
    def close(self):
        self.transport.close()

    def create_sftp(self):
        return paramiko.SFTPClient.from_transport(self.transport)

    def download_hashes(self, remote_path):
        sftp = self.create_sftp()
        try:
            with sftp.open(remote_path, 'r') as f:
                return f.read().decode('utf-8')
        except IOError:
            return None
        finally:
            sftp.close()

    def upload_hashes(self, remote_path, json_content):
        sftp = self.create_sftp()
        try:
            with sftp.open(remote_path, 'w') as f:
                f.write(json_content)
        finally:
            sftp.close()

    def list_remote_files_recursively(self, remote_dir):
        """
        List all files and directories in remote directory recursively.
        Returns a list of relative paths.
        """
        sftp = self.create_sftp()
        file_list = []
        remote_dir = remote_dir.replace('\\', '/')
        
        def _walk(current_path, relative_base):
            try:
                for entry in sftp.listdir_attr(current_path):
                    entry_name = entry.filename
                    full_path = f"{current_path}/{entry_name}"
                    rel_path = f"{relative_base}/{entry_name}" if relative_base else entry_name
                    
                    if stat.S_ISDIR(entry.st_mode):
                        file_list.append(rel_path)
                        _walk(full_path, rel_path)
                    else:
                        file_list.append(rel_path)
            except IOError:
                # Directory might not exist or permission denied
                pass

        try:
            _walk(remote_dir, "")
        finally:
            sftp.close()
            
        return file_list

    def delete_file(self, remote_path):
        sftp = self.create_sftp()
        try:
            try:
                sftp.remove(remote_path)
            except IOError:
                # Try rmdir if remove failed (e.g. it's a directory)
                sftp.rmdir(remote_path)
        except IOError:
            pass
        finally:
            sftp.close()


def ensure_dir_exists(sftp, remote_dir, cache=None):
    """
    Ensure a directory exists on the remote server, creating it if necessary.
    Handles recursive creation.
    """
    remote_dir = remote_dir.replace('\\', '/')
    if cache is not None and remote_dir in cache:
        return

    # Base case: root or empty
    if not remote_dir or remote_dir == '/':
        return

    # Check if exists
    try:
        sftp.stat(remote_dir)
        if cache is not None:
            cache.add(remote_dir)
        return
    except IOError:
        # Doesn't exist (or permission denied), try to create parent first
        parent = os.path.dirname(remote_dir)
        if parent and parent != remote_dir:
            ensure_dir_exists(sftp, parent, cache)
        
        # Now create this dir
        try:
            sftp.mkdir(remote_dir)
        except IOError:
            # Check again, maybe created by another worker
            try:
                sftp.stat(remote_dir)
            except IOError:
                # Still failing, raise the error
                raise
        
        if cache is not None:
            cache.add(remote_dir)



def upload_file_with_client(sftp, local_path, remote_path):
    """
    Upload a single file using an existing SFTP client instance.
    """
    try:
        # Optimization: Set window size and packet size for speed if needed
        # sftp.get_channel().set_window_size(2 * 1024 * 1024)
        sftp.put(local_path, remote_path)
    except Exception as e:
        print(f"Error uploading {local_path}: {e}")
        raise e
