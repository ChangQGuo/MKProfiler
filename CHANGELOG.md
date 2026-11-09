# MKProfiler Release Notes / 版本更新日志

## v1.3.1 — 2026-11-09

### English

- Ask the user to select the encoding when an unmarked result CSV is ambiguous; preserve the selected encoding and refuse to save if the file changes externally.
- Associate existing plant-level results with original identifiers recorded in `final_output_individual.csv`; hide unverified or conflicting associations unless the user explicitly chooses to trust unverified current IDs.
- Report a missing `kernel_name` column instead of silently showing an empty measurement table.
- Restore unambiguous legacy round-kernel images, contours and axes. Keep valid latent rows after a malformed row and label missing latent values as unavailable.
- Temporarily disable kernel deletion when CSV and Parquet measurements coexist, preventing one copy from overwriting newer data in the other.
- Require a folder reload if measurement or analysis files change externally; retry update rollback when Windows temporarily locks the executable.

### 中文

- 当结果 CSV 没有编码标记且存在歧义时，请用户逐文件选择编码；保存时保留所选编码，文件被外部修改后拒绝覆盖。
- 使用 `final_output_individual.csv` 保存的原始标识关联已有植株性状；无法核实或发生冲突时隐藏关联，用户可明确选择信任无法核实的当前标识。
- 测量表缺少 `kernel_name` 列时明确报错，避免静默显示空表。
- 恢复可唯一对应的旧版圆粒子图、轮廓和轴；跳过错误潜变量行，并将缺失潜变量标注为不可用。
- 当 CSV 和 Parquet 测量表同时存在时，暂时禁用单粒删除，避免其中一份覆盖另一份较新的数据。
- 测量或分析文件被外部修改后要求重新打开文件夹；Windows 暂时占用程序文件时，更新回滚会重试。

## v1.3 — 2026-11-09

### English

- Fixed loading CSV files saved by WPS or other spreadsheet programs with GB18030 or UTF-16 encoding; confirmed metadata edits preserve the original encoding.
- Show newer edited measurements CSV files instead of older Parquet copies.
- Include legacy `_round` kernel records in sample tables.

### 中文

- 修复 WPS 等表格软件保存为 GB18030 或 UTF-16 编码后，CSV 文件无法读取的问题；确认保存元数据修改时保留原编码。
- 当修改后的测量 CSV 比 Parquet 新时，优先显示 CSV 中的数据。
- 在样本表中显示旧版结果文件名带 `_round` 的籽粒记录。

## v1.2 — 2026-11-05

### English

- Added clearer, resizable panel dividers and edge-hover photo navigation.
- Added a visualization toolbar with icons for common inspection and analysis actions.
- Added deep blue, soft lavender and warm cream themes, plus saved font and text-size settings.
- Added background checks for published Windows updates, with user confirmation and checksum verification before installation.

### 中文

- 改进可拖动的分栏提示，照片导航箭头仅在鼠标靠近相应边缘时显示。
- 增加带图标的可视化工具栏，方便打开常用检查和分析功能。
- 增加深蓝、浅紫和淡黄色主题，并保存用户选择的字体和文字大小。
- 增加 Windows 版本后台更新检查，用户确认后下载，安装前校验文件。

## v1.1 — 2026-11-04

### English

- Added the current sample position, per-folder last-image memory and image or plant-name search.
- Added configurable navigation shortcuts, sample pins, image-name copying and viewer-only labels.

### 中文

- 增加当前样本位置、按文件夹记忆上次图片，以及图片名或 plant name 搜索。
- 增加自定义切换快捷键、样本置顶、图片名复制和仅在查看器中显示的别名。
