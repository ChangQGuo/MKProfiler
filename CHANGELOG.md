# MKProfiler Release Notes / 版本更新日志

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
