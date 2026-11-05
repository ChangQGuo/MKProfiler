# Publishing desktop updates / 发布桌面软件更新

## English

1. Set `grainprofiler.__version__` to the new version and build the Windows executable.
2. Create a ZIP named `MKProfiler_v<version>_<YYYYMMDD>.zip` with `MKProfiler.exe` at its root. For example: `MKProfiler_v1.3_20261201.zip`.
3. Upload the ZIP and a checksum file named `MKProfiler_v<version>_<YYYYMMDD>.sha256.txt` to the same GitHub Release. The checksum file must contain one line: the ZIP's SHA-256 hash, two spaces, and the exact ZIP filename.
4. Publish a stable release tagged `v<version>` and mark it as the latest release. Include the English and Chinese notes from [CHANGELOG.md](CHANGELOG.md). The release must contain exactly one matching ZIP and one matching checksum file.

The viewer checks for a newer stable release at startup. A user chooses whether to download and install it. Checksums detect damaged or mismatched files; they are not a substitute for an independent executable signature.

Keep the update startup acknowledgement in `grainprofiler/main.py`: it lets the previous version verify that the new window opened and recover if startup fails.

## 中文

1. 将 `grainprofiler.__version__` 改为新版本号，构建 Windows 程序。
2. 创建 `MKProfiler_v<版本号>_<年月日>.zip`，将 `MKProfiler.exe` 放在压缩包根目录。例如 `MKProfiler_v1.3_20261201.zip`。
3. 将压缩包及同名校验文件 `MKProfiler_v<版本号>_<年月日>.sha256.txt` 上传至同一个 GitHub Release。校验文件应有一行，依次为压缩包的 SHA-256、两个空格和完整压缩包文件名。
4. 发布标签为 `v<版本号>` 的正式版本，并设为最新版本；使用 [CHANGELOG.md](CHANGELOG.md) 中的中英文更新说明。每个版本只能有一个符合该命名规则的压缩包和一个对应校验文件。

软件启动时检查较新的正式版本，由用户选择是否下载和安装。校验和可以检查文件损坏或不匹配，不能替代独立的程序签名。

请保留 `grainprofiler/main.py` 中的更新启动确认逻辑，以便旧版本确认新窗口已经打开，并在启动失败时恢复。
