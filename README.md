# PDF转Markdown工具

将PDF（扫描件/矢量）、Word、PPTX文档转换为结构化的Markdown格式。特别针对报告类文档优化：PDF和PPTX通过逐页转图片后使用Vision API识别，再经智能重构整理为连贯的报告格式；Word文档保持结构化提取。

---

## 功能特性

- **PDF（扫描件/矢量）**：逐页转图片 → Vision API识别 → **智能重构为报告格式**
- **PowerPoint**：转PDF → 逐页转图片 → Vision识别 → **智能重构为报告格式**
- **Word文档**：提取段落样式、表格、层级结构（无需API调用）
- **错误自动恢复**：限流失败自动补充重试，内容安全失败标注跳过
- **智能降级**：致命错误率超过10%时自动跳过重构，文件名标注未完整提取页数
- **跳过已处理**：批量处理时自动跳过已存在`.md`输出文件的源文件

---

## 安装依赖

```bash
# Python依赖
pip install -r requirements.txt

# 系统依赖
# 1. poppler（pdf2image需要）
# macOS:
brew install poppler

# Ubuntu/Debian:
apt-get install poppler-utils

# 2. LibreOffice（PPTX转PDF需要，仅处理PPTX时安装）
# macOS:
brew install libreoffice

# Ubuntu/Debian:
apt-get install libreoffice
```

---

## 环境配置

支持三种方式配置 API Key，优先级从高到低：

### 方式一：命令行参数（临时使用）

```bash
python pdf_to_markdown.py report.pdf --api-key "your_api_key_here"
```

### 方式二：Shell 配置文件（推荐，持久生效）

**macOS (zsh)**：
```bash
# 编辑 ~/.zshrc
echo 'export KIMI_API_KEY="your_api_key_here"' >> ~/.zshrc

# 使配置生效
source ~/.zshrc

# 验证
env | grep KIMI_API_KEY
```

**Linux (bash)**：
```bash
# 编辑 ~/.bashrc
echo 'export KIMI_API_KEY="your_api_key_here"' >> ~/.bashrc

# 使配置生效
source ~/.bashrc

# 验证
env | grep KIMI_API_KEY
```

### 方式三：.env 文件（项目级配置）

```bash
# 复制模板文件
cp .env.example .env

# 编辑 .env 文件，填入真实 Key
vim .env
```

`.env` 文件内容示例：
```bash
KIMI_API_KEY=your_api_key_here
# KIMI_MODEL=kimi-coding
# KIMI_BASE_URL=https://api.kimi.com/coding/
```

> **注意**：`.env` 文件已加入 `.gitignore`，不会被提交到 Git。

---

## 快捷命令配置（可选）

将项目路径设为环境变量，方便在任意目录调用：

**macOS (zsh)**：
```bash
# 编辑 ~/.zshrc，将路径替换为你的实际安装目录
echo 'export pdf2md="/Users/apple/projects/tools/pdf-to-markdown"' >> ~/.zshrc

# 可选：添加 alias 直接调用
echo 'alias pdf2md="python \$pdf2md/pdf_to_markdown.py"' >> ~/.zshrc

# 使配置生效
source ~/.zshrc
```

**Linux (bash)**：
```bash
# 编辑 ~/.bashrc，将路径替换为你的实际安装目录
echo 'export pdf2md="/Users/apple/projects/tools/pdf-to-markdown"' >> ~/.bashrc

# 可选：添加 alias 直接调用
echo 'alias pdf2md="python \$pdf2md/pdf_to_markdown.py"' >> ~/.bashrc

# 使配置生效
source ~/.bashrc
```

配置完成后，可在任意目录使用：

```bash
# 使用环境变量
python $pdf2md/pdf_to_markdown.py ~/Downloads/report.pdf

# 或使用 alias
pdf2md ~/Downloads/report.pdf
pdf2md ~/Downloads/report.pdf --no-reorganize
pdf2md ./documents/ --batch
```

---

## 使用示例

### 单文件处理（自动检测类型，默认智能重构）

```bash
# PDF（扫描件/矢量）- Vision识别 + 智能重构
python pdf_to_markdown.py report.pdf

# Word文档 - 结构化提取
python pdf_to_markdown.py document.docx

# PowerPoint - 转PDF → 图片 → Vision识别
python pdf_to_markdown.py presentation.pptx
```

### 批量处理目录

```bash
# 处理目录下所有支持的文件，自动跳过已存在的.md
python pdf_to_markdown.py ./documents/ --batch

# 强制重新处理所有文件（覆盖已存在的.md）
python pdf_to_markdown.py ./documents/ --batch --no-skip-existing
```

### 常用选项

```bash
# 禁用智能重构，使用传统逐页拼接
python pdf_to_markdown.py report.pdf --no-reorganize

# 指定页码范围和并发数
python pdf_to_markdown.py scan.pdf -s 5 -e 15 -c 5

# 调整重构批次大小（默认25页/批）
python pdf_to_markdown.py report.pdf --batch-size 15

# 保留中间转换的图片
python pdf_to_markdown.py report.pdf --keep-images

# 查看所有选项
python pdf_to_markdown.py --help
```

---

## 命令行参数

| 参数 | 简写 | 说明 | 默认值 |
|:---|:---|:---|:---|
| `input_path` | - | 输入文件路径或目录 | 必填 |
| `--batch` | - | 批量处理目录下所有文件 | false |
| `--no-reorganize` | - | 禁用智能重构，使用简单拼接 | false |
| `--skip-existing` | - | 跳过已存在.md的文件（默认启用） | true |
| `--no-skip-existing` | - | 强制覆盖已存在的.md | - |
| `--output` | `-o` | 输出目录 | 源文件同目录 |
| `--start-page` | `-s` | 起始页码（仅PDF） | 1 |
| `--end-page` | `-e` | 结束页码（仅PDF） | 最后一页 |
| `--concurrency` | `-c` | 并发识别页数 | 10 |
| `--batch-size` | - | 重构时每批目标页数，会小幅均衡以避免小尾批 | 25 |
| `--dpi` | - | PDF转图片分辨率 | 300 |
| `--keep-images` | - | 保留中间转换的图片 | false |
| `--api-key` | - | API Key | 环境变量 |
| `--model` | - | 模型名称 | kimi-coding |
| `--base-url` | - | API基础URL | https://api.kimi.com/coding/ |

---

## 处理流程

### PDF/PPTX处理流程

```
输入PDF/PPTX
  │
  ▼
[PDF转图片] ──→ 每页转为PNG（DPI 300）
  │
  ▼
[并发识别] ──→ Vision API识别各页（含限流自动重试）
  │             ├── 成功：返回Markdown
  │             ├── high_risk：内容安全审核未通过
  │             └── rate_limit：触发限流
  │
  ▼
[补充重试] ──→ 限流失败页等待10秒后集中重试（retry×3）
  │
  ▼
[错误统计] ──→ 分类统计：成功 / high_risk / 致命错误
  │
  ▼
[阈值检查] ──→ 致命错误率 > 10% ?
  │              ├── 是：跳过重构，文件名标注"【X】页未完整提取"
  │              └── 否：进入智能重构
  │
  ▼
[智能重构] ──→ 分块并发重构（max_workers=3，每批限流重试）
  │             ├── 去除重复页眉页脚
  │             ├── 合并跨页段落
  │             ├── 构建章节层级
  │             └── 整理为报告格式
  │
  ▼
[输出Markdown]
```

### Word处理流程

```
输入Word文档
  │
  ▼
[结构化提取] ──→ python-docx提取段落、表格、标题层级
  │
  ▼
[格式转换] ──→ Markdown语法
  │
  ▼
[输出Markdown]
```

---

## 错误处理机制

### 识别阶段错误分类

| 错误类型 | 原因 | 处理方式 |
|:---|:---|:---|
| **rate_limit** | API限流（429） | 单页自动重试2次 → 补充重试（再等10秒，重试3次） |
| **high_risk** | 内容安全审核（400） | 标注跳过，不阻止重构，头部标注"内容安全未通过" |
| **other** | 网络超时、图片损坏等 | 计入致命错误，超过10%跳过重构 |

### 致命错误阈值

- 致命错误率 ≤ 10%：正常进入智能重构
- 致命错误率 > 10%：
  - 自动跳过重构，使用简单拼接
  - 输出文件名改为：`原命名_【X】页未完整提取.md`
  - 文档头部标注：`⚠️ 致命错误率XX%，跳过智能重构`

---

## 核心代码结构

```
pdf-to-markdown/
├── README.md                 # 本文档
├── .gitignore                # Git忽略规则
├── .env.example              # 环境变量模板
├── requirements.txt          # Python依赖
├── pdf_to_markdown.py        # 主程序（CLI入口、流程编排）
├── document_detector.py      # 文档类型检测（扫描件/矢量/Word/PPTX）
├── pdf_converter.py          # PDF转图片 / PPTX转PDF
├── vision_recognizer.py      # Vision API识别（含错误分类、限流重试）
├── content_reorganizer.py    # 智能重构（分块并发、限流保护）
├── result_merger.py          # 结果合并（头部标注、重构/拼接路由）
└── structured_extractors.py  # Word结构化提取
```

---

## 限制说明

- **单页识别**：依赖Kimi Code Vision API，受API速率限制
- **并发识别**：默认10并发，大文件可调低避免限流
- **智能重构**：
  - 长文档均衡分块并发重构（默认目标25页/批，并发workers=3；如51页会切为26/25）
  - 需要额外LLM调用，增加Token消耗和耗时
- **PPTX处理**：依赖LibreOffice，未安装时无法处理
- **手写体**：识别准确率低于印刷体
- **图片中的文字**：无法识别，仅生成占位符

---

## 成本估算

使用 Kimi Code Vision API + 智能重构：

| 页数 | 预估总Token | 预估总成本（人民币） |
|:---|:---|:---|
| 10页 | ~20K-40K | ¥0.7-1.3 |
| 50页 | ~95K-190K | ¥3.0-6.0 |
| 100页 | ~190K-380K | ¥6.0-12.0 |

*注：实际成本取决于页面复杂度和文字密度。使用 `--no-reorganize` 可节省约20-30%成本。*
