import os
import paramiko
import stat
import time

class SFTPClientWrapper:
    def __init__(self, host, port, username, password=None, key_data=None, passphrase=None):
        self.transport = paramiko.Transport((host, int(port)))
        self.transport.use_compression(True) # Enable compression if supported
        
        if key_data:
            # Paramiko expects a file-like object or filename for keys
            # If key_data is string, we might need to handle it.
            # Assuming key_data is passed as a string content or path?
            # Action input usually passes content or path.
            # If it looks like a path and exists, use it.
            # Else treat as content.
            import io
            if os.path.exists(key_data):
                pkey = paramiko.RSAKey.from_private_key_file(key_data, password=passphrase)
            else:
                pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_data), password=passphrase)
            self.transport.connect(username=username, pkey=pkey)
        else:
            self.transport.connect(username=username, password=password)
            
    def close(self):
        self.transport.close()

    def create_sftp(self):
        return paramiko.SFTPClient.from_transport(self.transport)

    def ensure_remote_dirs(self, remote_dirs):
        """
        Create all directories in the list. 
        Should be called sequentially before parallel uploads.
        """
        sftp = self.create_sftp()
        try:
            # Sort by length to ensure parents are created first
            sorted_dirs = sorted(list(remote_dirs), key=len)
            cache = set()
            
            for directory in sorted_dirs:
                if directory in cache:
                    continue
                
                # Check parts
                parts = directory.split('/')
                path = ""
                for part in parts:
                    if not part: continue
                    path += "/" + part
                    if path in cache:
                        continue
                    
                    try:
                        sftp.stat(path)
                    except IOError:
                        try:
                            sftp.mkdir(path)
                        except IOError:
                            # Ignore if it exists now
                            pass
                    cache.add(path)
        finally:
            sftp.close()

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
        List all files in remote directory recursively.
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
            sftp.remove(remote_path)
        except IOError:
            pass
        finally:
            sftp.close()

def upload_single_file(transport, local_path, remote_path):
    """
    Worker function for uploading a single file.
    """
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        # Optimization: Set window size and packet size for speed
        # sftp.get_channel().set_window_size(2 * 1024 * 1024)
        sftp.put(local_path, remote_path)
    except Exception as e:
        print(f"Error uploading {local_path}: {e}")
        raise e
    finally:
        sftp.close()
