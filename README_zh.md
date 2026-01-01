# SFTP Upload Action (v3)

[🇺🇸 English](./README.md)

通过 SFTP 将文件上传到服务器的 GitHub Action。

## 特性 (v3)
*   🚀 **高性能**: 基于 Python 重写，支持可配置的并发上传。
*   🧠 **智能跳过**: 使用内容哈希 (`MD5`) 准确识别变动文件，跳过未修改的文件。
*   📂 **状态管理**: 在服务器端维护 `.sftp_upload_action_hashes` 文件以记录文件状态，**无需 SSH Shell 权限**。
*   🔒 **安全**: 支持密码和私钥认证。

## 输入参数 (Inputs)

| 参数名 | 描述 | 是否必填 | 默认值 |
| :--- | :--- | :--- | :--- |
| `host` | SFTP 服务器地址 | **是** | |
| `port` | SFTP 端口 | 否 | `22` |
| `username` | SFTP 用户名 | **是** | `root` |
| `password` | SFTP 密码 | 否 | |
| `privateKey` | SSH 私钥内容 | 否 | |
| `passphrase` | 私钥密码 | 否 | |
| `localDir` | 本地上传目录 | **是** | |
| `remoteDir` | 远程目标目录 | **是** | |
| `dryRun` | 试运行模式 (不执行上传) | 否 | `false` |
| `exclude` | 排除文件的 Glob 模式 (逗号分隔) | 否 | |
| `forceUpload` | 强制上传所有文件 (禁用哈希检查) | 否 | `false` |
| `removeExtraFilesOnServer` | 删除服务器上多余的文件 (保持同步) | 否 | `false` |
| `concurrency` | 并发上传线程数 | 否 | `4` |

## 使用示例

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

## 从 v2 迁移到 v3 (Migration Guide)

版本 3 是使用 Python 完全重写的版本，旨在提高性能和可靠性。

### 主要变化
1.  **运行环境**: 从 Node.js 切换到 Python (Composite Action)。
2.  **智能跳过策略**: v2 使用文件大小/时间戳。v3 使用 **内容哈希 (MD5)**，并将哈希值存储在服务器端的 `.sftp_upload_action_hashes` 文件中。这确保了只有内容真正改变的文件才会被上传，即使构建产生的新文件时间戳不同也能正确识别。
3.  **并发控制**: 新增 `concurrency` 参数用于控制并行上传数量 (默认: 4)。

> Action 现在会在 `remoteDir` 下创建一个 `.sftp_upload_action_hashes` 文件。请勿删除该文件，否则智能跳过功能将失效。

### 迁移步骤
1.  仅需将 Workflow 中的版本标签更新为 `@v3`。
2.  享受更快的上传速度！
