# SFTP Upload Action (v3)

[🇨🇳 简体中文](./README_zh.md)

A GitHub Action to upload files to a server via SFTP.

## Features (v3)
*   🚀 **High Performance**: Python-based implementation with configurable concurrency.
*   🧠 **Smart Skip**: Uses content hash (`MD5`) to skip unchanged files.
*   📂 **State Management**: Maintains a `.sftp_upload_action_hashes` file on the server to track file states without needing SSH shell access.
*   🔒 **Secure**: Supports password and private key authentication.

## Inputs

| Input | Description | Required | Default |
| :--- | :--- | :--- | :--- |
| `host` | SFTP Host address | **Yes** | |
| `port` | SFTP Port | No | `22` |
| `username` | SFTP Username | **Yes** | `root` |
| `password` | SFTP Password | No | |
| `privateKey` | SSH Private Key content | No | |
| `passphrase` | Passphrase for Private Key | No | |
| `localDir` | Local directory to upload | **Yes** | |
| `remoteDir` | Remote directory path | **Yes** | |
| `dryRun` | Dry run mode (no changes) | No | `false` |
| `exclude` | Comma-separated glob patterns to exclude | No | |
| `forceUpload` | Force upload all files (disable hash check) | No | `false` |
| `removeExtraFilesOnServer` | Remove extra files on server that are not in local directory | No | `false` |
| `concurrency` | Number of concurrent uploads | No | `4` |

## Example Usage

```yaml
name: Deploy
on: [push]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Upload via SFTP
        uses: wangyucode/sftp-upload-action@v3
        with:
          host: ${{ secrets.HOST }}
          username: ${{ secrets.USERNAME }}
          password: ${{ secrets.PASSWORD }}
          localDir: 'dist'
          remoteDir: '/var/www/html'
          concurrency: 10
```

## Migrating from v2 to v3

Version 3 is a complete rewrite in Python to improve performance and reliability.

### Key Changes
1.  **Platform**: Switched from Node.js to Python (Composite Action).
2.  **Smart Skipping**: v2 used file size/timestamp. v3 uses **Content Hash** (MD5) stored in a metadata file `.sftp_upload_action_hashes` on the server. This ensures that only truly changed files are uploaded, even if timestamps change (common in CI builds).
3.  **Concurrency**: Added `concurrency` input to control parallel uploads (default: 4).

### Migration Steps
1.  Just update the version tag to `@v3` in your workflow.
2.  Enjoy faster uploads!

## Notes

### Hash File (`.sftp_upload_action_hashes`)
A `.sftp_upload_action_hashes` file is created in `remoteDir` to track file states. **Do not delete this file** to ensure "Smart Skip" works correctly.

### File Removal (`removeExtraFilesOnServer`)
When enabled, this compares local files against the *tracked* remote files in the hash file.
*   **Only tracked files are deleted.** Untracked files (e.g., manually created) are ignored.
*   This ensures safety and speed but does not strictly mirror the directory if untracked files exist.
