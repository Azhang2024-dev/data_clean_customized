# 语料清洗批处理工具 — 项目上下文 (AGENTS.md)

> 本项目于 2026-07-20 从 `D:\Users\admin\Desktop\My Project\Ella知识库数据集小工具` 迁出，
> 独立承载 corpus-cleaner plan 的实现。原项目同时承载多个工作流
> （爬虫 / Excel / 格式转换 / Wikipedia datasource），corpus-cleaner 作为独立工具从原项目
> `.omo/` 下迁出以独立实现。
> 全局 coding 准则见 ~/.codex/AGENTS.md（AI 八荣八耻），此处只记项目级信息。

## 项目概述

独立 CLI 工具，对 5 个用户回流语料文件夹（约 2,300 份 `.md`/`.txt` 文件）做语料清洗：
扫描分析 → 表格过滤 → OCR 污染处理 → 去重 → 语义重命名 → 输出 → 报告。

- **入口**：`corpus_clean.py`（CLI，尚未实现）
- **框架**：纯 Python 标准库 + 3 个轻量包（`langdetect` / `openpyxl` / `chardet`）
- **工具形态**：独立 CLI + 模块化包，可后续集成为 GUI Tab 或 skill
- **不调用 LLM**，纯启发式规则，离线零成本

## 输入数据范围

基路径：`D:\Users\admin\Desktop\My Project\Ella知识库数据集\语料清理文件及软件输出\`

| 文件夹 | 文件数（估） | 主语言 |
|--------|-------------|-------|
| `用户回流阿语筛选` | ~418 | AR（主）+ EN |
| `用户回流俄语` | ~140 | RU |
| `用户回流法语_1246篇` | ~1248 | FR |
| `用户回流法语_筛选_200篇` | ~200 | FR（1246 的自然去重子集） |
| `用户回流EN多格式` | ~255 | EN |

## 目录结构

```
corpus_cleaner/                  # Python 子包（工具层）
  __init__.py                    # 已建空文件占位
  pipeline.py                    # run_pipeline(config) — 待实现
  config.py                      # PipelineConfig dataclass
  scanner.py                     # scan_files(), _parse_filename(), _extract_meta()
  classifier.py                  # classify_file(meta, content) → category
  table_filter.py                # is_table_file(meta) → bool
  ocr_handler.py                 # compute_contamination(), clean_content()
  deduplicator.py                # find_duplicates(file_list)
  renamer.py                     # generate_new_name(), _extract_title(), _sanitize()
  reporter.py                    # generate_report() → Excel + txt + JSON
  i18n_tokens.py                 # 白名单正则常量
  utils.py                       # safe_filename(), md5_file(), read_file_auto()

corpus_clean.py                  # CLI 入口脚本（项目根，待实现）
.omo/plans/corpus-cleaner.md     # 详细 Work Plan (28KB，7 阶段流水线设计)
.omo/notepads/corpus-cleaner/    # OpenCode notepad（decisions/issues/learnings/problems）
.claude/settings.local.json      # Claude Code 项目级 permission 配置
```

## 关键技术约定

### 依赖限制（硬约束）
- **允许**：Python 标准库 + `langdetect` + `openpyxl` + `chardet`
- **禁止**：PyQt、litellm、asyncio、playwright 等重型库
- **理由**：保持工具离线、零成本、可独立分发

### 输出结构（Stage 6）
```
corpus_cleaned/
  {AR,RU,FR,EN}/<new_name>.md       # 通过文件按语言归类
  _tables/{lang}/<original>.md       # 表格过滤
  _contaminated/{lang}/<original>.md # OCR 污染隔离
  _duplicates/{exact,suspected}/    # 去重
  _empty/
  _bad_files/
  _report.xlsx                       # 6 张工作表
  _summary.txt
  _original_manifest.json
```

### 命名规范（Stage 5）
文件名：`{category}_{topic}_{seq:03d}_{S|M|L}.md`
- `category` 按优先级：`exam` / `tutorial` / `book` / `lecture` / `short` / `table` / `misc`
- `topic` 来自首个 `#` / `##` / 前 20 行非空行 / 兜底 `untitled`
- 长度档位基于 `net_char_count`（剥除 markdown/HTML 噪音后的净字符数）：≤20K=S, 20-50K=M, >50K=L

### OCR 污染四级模式

| 模式 | 独立噪音 | 嵌入碎片 | 语义安全 | 适用 |
|------|---------|---------|---------|------|
| `flag-only`（默认） | 不处理 | 不处理 | ✅ 完全 | 先观察污染程度 |
| `clean-mark` | `[?]` 标记 | `[?]` 标记 | ✅ 完全 | 需清洗但保语义 |
| `clean-light` | 删除 | `[?]` 标记 | ⚠️ 较安全 | 精细清洗，仅删确定无语义的 |
| `clean-aggressive` | 删除 | 删除 | ❌ 会破坏 | 下游有修复能力 / 接受损失 |

### 净字符口径（net_char_count）
剥除以下噪音后的字符数：
- Markdown 标记（`#` / `**` / 列表符 `-` `•` `1.`）
- HTML 标签（`<tag>` / `<table>` 整套）
- Markdown 图片 `![](path)` / 链接语法 `[text](url)` 仅保留 text
- 代码块围栏 ` ``` `（内容保留）
- 连续空白合并为 1 空格

### 表格过滤阈值
`table_ratio`（含 `<table>` 行 / 总行数）> `0.70` → 隔离

### 合法双语白名单（不视为污染）
1. URLs: `https?://\S+`
2. Emails: `\S+@[a-zA-Z0-9._-]+\.[a-zA-Z]+`
3. Markdown 代码块内容
4. 全大写英文缩写（3+ 字符）：`\b[A-Z][A-Z0-9_]{2,}\b`
5. 数字 + 单位：`\d+(\.\d+)?\s*(%|[a-zA-Z]+)`
6. 图片标签 / HTML 属性

## 运行与验证

Plan 状态：`awaiting-approval`，尚未开始实现。实现后：

```bash
python corpus_clean.py --input <folder> --output corpus_cleaned/ \
  [--ocr-mode flag-only] [--length-thresholds 20000,50000] [--fuzzy-dedup]
```

- 完整 plan：见 `.omo/plans/corpus-cleaner.md`（578 行）
- 语法校验：`python -c "import ast; ast.parse(open('目标文件', encoding='utf-8').read())"`

## 禁改文件清单

- `.omo/plans/corpus-cleaner.md` — 待批准的核心 plan，勿改
- `.omo/notepads/corpus-cleaner/*.md` — OpenCode 运行时记事本，由 subagent 自动维护
- `.claude/settings.local.json` — Claude Code permission 配置（迁入时为空骨架，按需追加）

## 迁移来源说明

从 `D:\Users\admin\Desktop\My Project\Ella知识库数据集小工具` 迁出，原项目 AGENTS.md（Ella 专属，
9.3KB，描述爬虫/Excel/格式转换/Wikipedia datasource 等无关模块）未复制；
本 AGENTS.md 为 corpus-cleaner 专属重写版，仅保留与本项目相关的信息。

迁移清单（2026-07-20）：
- `.omo/plans/corpus-cleaner.md`（28KB，主 plan）
- `.omo/notepads/corpus-cleaner/{decisions,issues,learnings,problems}.md`（空占位）
- `corpus_cleaner/__init__.py`（0 字节占位）
- `.claude/settings.local.json`（原为 Ella 的 `firecrawl_crawler.py` permission 条目，
  指向新项目不存在的文件，建议清空 `allow` 列表为 `[]` 后按需追加）
- `AGENTS.md`（本文件，corpus-cleaner 专属重写）

**未迁移**：
- `.omo/run-continuation/*.json` — OpenCode 运行时 session 状态，仅在新项目走 OpenCode 且需
  续上之前 session 时才有意义，已确认不迁
- 原 Ella 项目的 `CLAUDE_CODE_HISTORY_EXTRACT.txt` — AGENTS.md 提及但实际不在磁盘上，无可迁内容
- 原 Ella 项目的其他模块（smart_crawler / doc_processor / md_converter / excel_processor 等）
  — 属于原项目，与 corpus-cleaner 无关
