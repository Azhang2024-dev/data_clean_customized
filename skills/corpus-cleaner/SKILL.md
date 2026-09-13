---
name: corpus-cleaner
description: >
  语料清洗批处理工具。处理任意目录下的语料文件：重命名、去重、表格过滤、OCR 污染处理、长度标记。支持 quick/standard/thorough 三档预设。
---

# corpus-cleaner

语料清洗批处理工具。处理任意目录下的语料文件：重命名、去重、表格过滤、OCR 污染处理、长度标记。

## 触发条件

用户提到以下任一：
- "清洗语料" / "回流文件" / "corpus clean" / "语料清理" / "语料清洗"
- 用户指向一批 .md/.txt 文件需要整理
- 用户提到 "表格过滤" / "OCR 污染" / "去重" 且上下文是语料文件

## ⛔ 强制约束（MUST）

> 以下约束是硬性要求，**不可跳过**。违反即视为执行错误。

1. **必须先 dry-run**：任何正式执行前，必须先执行 `--dry-run` 并向用户呈现预览结果。
2. **必须用户确认**：dry-run 后，必须等用户明确确认（"执行" / "确认" / "可以" 等），才能进入正式执行。不得自行决定跳过确认。
3. **必须确认配置**：执行前必须向用户确认清洗档位（quick/standard/thorough），不得使用默认值直接开始。
4. **正式执行必须带 --confirm**：CLI 要求非 dry-run 执行必须带 `--confirm` 标志，否则拒绝执行并返回 exit code 2。

## 工作流程

### Step 1: 确认范围

1. 确认源文件夹路径（用户已提供则验证存在性；未提供则询问）
2. 快速扫描目录结构，告知用户：文件数量、文件类型（.md/.txt）、是否有子目录

### Step 2: 确认配置

问用户（仅 1 项，**不可跳过**）：
1. 清洗档位：quick（快速基础清洗）/ standard（默认，推荐）/ thorough（深度清洗）

各档位说明：
- **quick**：基础清洗 + ftfy 编码修复 + fast-langdetect 语言检测（~2min）
- **standard**（默认）：+ KL 散度乱码检测 + HTML 噪音识别 + 评分分类器 + 增强白名单（~2.5min）
- **thorough**：+ 逐行语言检测 + trafilatura HTML 提取 + 低阈值去重 + clean-light OCR 清洗（~8min）

### Step 3: Dry Run（预览）

构造命令加 `--dry-run`，执行，读取 `_summary.txt`，呈现给用户：
- "共 X 文件，预计保留 Y，过滤表格 Z1，隔离污染 Z2，去重 Z3"
- 按语言 x 长度档位的分布预览
- 问用户："确认执行？需要调整参数吗？"

### Step 4: 正式执行（需用户确认）

**仅在用户明确确认后**，去掉 `--dry-run`，加上 `--confirm`，执行。

### Step 5: 呈现结果

读取 `_summary.txt` 和 `_report.xlsx`，呈现：
- 最终统计
- 被过滤 / 隔离的文件数量和典型示例（供人工复核）
- 隔离目录路径（用户可自行打开复核）

## 命令构造

根据用户回答构造 CLI 命令：

    corpus-clean --input {input} --output {output} --profile {profile} [--dry-run] [--lang {LANG}] [--confirm]

**CLI 参数（6 个公开参数）**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --input, -i | 源文件夹路径（必填） | — |
| --output, -o | 输出目录 | ./corpus_cleaned |
| --profile, -p | 清洗档位：quick / standard / thorough | standard |
| --dry-run | 仅分析，不写文件 | 关 |
| --lang | 强制语言代码（如 AR），跳过检测 | 自动检测 |
| --confirm | 确认正式执行（非 dry-run 时必填） | 关 |

## 三档预设详情

| 特性 | quick | standard | thorough |
|------|-------|----------|----------|
| ftfy 编码修复 | on | on | on |
| fast-langdetect | on | on | on |
| KL 散度乱码检测 | off | on | on |
| HTML 噪音识别 | off | on | on |
| 评分分类器 | off | on | on |
| 增强双语白名单 | off | on | on |
| 逐行语言检测 | off | off | on |
| trafilatura 提取 | off | off | on |
| 模糊去重 | off | off | on |
| OCR 清洗模式 | flag-only | flag-only | clean-light |
| 去重阈值 | 0.95 | 0.95 | 0.85 |

## OCR 四级模式

| 模式 | 独立噪音 | 嵌入碎片 | 语义安全 | 适用场景 |
|------|---------|---------|---------|---------|
| flag-only | 不处理 | 不处理 | 完全安全 | 先观察污染程度（默认） |
| clean-mark | [?] 标记 | [?] 标记 | 完全安全 | 需清洗但保语义 |
| clean-light | 删除 | [?] 标记 | 较安全 | 精细清洗 |
| clean-aggressive | 删除 | 删除 | 会破坏语义 | 下游有修复能力 |

## 命名规范

输出文件名格式：{category}_{topic}_{seq:03d}_{S|M|L}.md

- category（按优先级）：exam / tutorial / book / lecture / short / table / misc
- topic：首个 # / ## / 前 20 行非空行提取，兜底 untitled
- 长度档位：基于 net_char_count（剥除 markdown/HTML 噪音后的净字符数）
  - S: <= 20K
  - M: 20K - 50K
  - L: > 50K

## 输出目录结构

    corpus_cleaned/
      {AR,RU,FR,EN,ID}/<new_name>.md     # 通过文件按语言归类
      _tables/{lang}/<original>.md       # 表格过滤隔离
      _contaminated/{lang}/<original>.md # OCR 污染隔离
      _html_noisy/{lang}/<original>.md   # HTML 噪音隔离
      _image_only/{lang}/<original>.md   # 纯图片文档隔离
      _duplicates/{exact,suspected}/     # 去重隔离
      _empty/                            # 空文件隔离
      _bad_files/                        # 损坏文件隔离
      _report.xlsx                       # 六张工作表
      _summary.txt                       # 人类可读统计
      _original_manifest.json            # 原始文件映射