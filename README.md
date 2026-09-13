# corpus-cleaner |  | 语料清洗批处理工具

对任意目录下的多语种语料文件（`.md` / `.txt`）做批处理清洗：扫描分析 → 表格过滤 →
OCR 污染处理 → 去重 → 语义重命名 → 按语言归类输出 → 生成报告。纯启发式规则，
**不调用 LLM**，离线零成本。支持 `quick / standard / thorough` 三档预设。

## 功能

- **扫描分析**：递归扫描目录，提取元信息（语言检测、净字符数、表格占比、OCR 污染度）
- **表格过滤**：`<table>` 行占比超阈值 → 隔离到 `_tables/`，不进主输出
- **OCR 污染处理**：四级模式（flag-only / clean-mark / clean-light / clean-aggressive），
  识别乱码碎片与独立噪音，按模式标记或删除
- **去重**：精确去重 + 疑似去重 +（thorough 档）模糊去重
- **语义重命名**：按 `{category}_{topic}_{seq:03d}_{S|M|L}.md` 规范重命名
  - category：exam / tutorial / book / lecture / short / table / misc
  - 长度档位：≤20K=S，20-50K=M，>50K=L（基于剥除 markdown/HTML 噪音后的净字符数）
- **按语言归类输出**：通过文件归入 `{AR,RU,FR,EN}/`，异常文件分别隔离
- **报告**：`_report.xlsx`（6 张工作表）+ `_summary.txt` + `_original_manifest.json`

## 三档预设

| 预设 | 特性 | 适用 |
|------|------|------|
| `quick` | 基础清洗 + ftfy 编码修复 + 语言检测；flag-only OCR；不模糊去重 | 快速过一遍看整体情况 |
| `standard`（默认） | 增加 KL 散度语言异常、HTML 噪音、评分分类器、双语白名单；疑似去重 | 日常清洗 |
| `thorough` | 再加行级语言检测、trafilatura 救援、模糊去重(0.85)、clean-light OCR、更低阈值 | 深度清洗，下游要求高 |

## 用法

```bash
# 1. 先 dry-run 预览（必须）
python corpus_clean.py --input <语料文件夹> --output corpus_cleaned/ \
  --profile standard --dry-run

# 2. 确认后正式执行（必须带 --confirm）
python corpus_clean.py --input <语料文件夹> --output corpus_cleaned/ \
  --profile standard --confirm

# 指定语言跳过检测
python corpus_clean.py -i <文件夹> -o corpus_cleaned/ -p thorough --lang FR --confirm
```

### 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--input` / `-i` | 必填 | 待清洗的语料根目录 |
| `--output` / `-o` | `./corpus_cleaned` | 输出目录 |
| `--profile` / `-p` | `standard` | `quick / standard / thorough` |
| `--dry-run` | off | 只分析不写文件（正式执行前必须先跑） |
| `--lang` | 自动检测 | 强制语言码（AR/FR/RU/EN），跳过检测 |
| `--confirm` | off | 非 dry-run 执行必须带，否则拒绝（exit 2） |

> 高级覆盖参数（`--ocr-mode` / `--table-threshold` / `--contamination-threshold` /
> `--length-thresholds` / `--fuzzy-dedup` / `--workers` 等）已隐藏，一般用预设即可，
> 详见 `python corpus_clean.py --help`。

## 输出结构

```
corpus_cleaned/
  {AR,RU,FR,EN}/<new_name>.md       # 通过清洗的文件按语言归类
  _tables/{lang}/<original>.md       # 表格占比过高，隔离
  _contaminated/{lang}/<original>.md # OCR 污染严重，隔离
  _duplicates/{exact,suspected}/     # 去重（精确/疑似/模糊）
  _empty/                            # 空文件
  _bad_files/                        # 无法解析的文件
  _report.xlsx                       # 6 张工作表统计报告
  _summary.txt                       # 文本摘要
  _original_manifest.json            # 原始文件清单
```

## 项目结构

```
corpus_clean.py                  # CLI 入口（5 个公开参数 + 预设）
corpus_cleaner/                  # 核心包
  pipeline.py                    # run_pipeline() — 7 阶段流水线编排
  config.py                      # PipelineConfig + PROFILE_PRESETS
  scanner.py                     # 扫描与元信息提取
  classifier.py                  # 评分分类器
  table_filter.py                # 表格占比判定
  ocr_handler.py                 # OCR 污染检测与清洗（四级模式）
  deduplicator.py                # 精确/疑似/模糊去重
  renamer.py                     # 语义重命名
  reporter.py                    # Excel/txt/JSON 报告生成
  profile_card.py                # 文件画像卡片（供 agent 重命名）
  i18n_tokens.py                 # 双语白名单正则
  utils.py                       # safe_filename / md5_file / read_file_auto
  lang_profiles/*.json           # 语言检测特征
  tests/                         # 11 个测试模块
skills/corpus-cleaner/SKILL.md   # Agent skill 定义
install_skill.py                 # 把 skill 装到 ~/.agents/skills/
docs/                            # 开发日志、策略文档、精简与开源整合计划
```

## 依赖

纯 Python 标准库 + 3 个轻量包：`langdetect` / `openpyxl` / `chardet`
（thorough 档额外用 `ftfy` / `trafilatura`）。**禁止** PyQt、litellm、asyncio 等重型库——
保持离线、零成本、可独立分发。

## 测试

```bash
python -m unittest discover -s corpus_cleaner/tests
```

## 设计约定

- **不调 LLM**：纯启发式规则，离线零成本
- **净字符口径**（net_char_count）：剥除 markdown 标记 / HTML 标签 / 图片链接语法 /
  代码块围栏 / 连续空白后的字符数，用于长度档位判定
- **表格过滤阈值**：`table_ratio`（`<table>` 行 / 总行数）> 0.70 → 隔离
- **合法双语白名单**：URL / Email / 代码块内容 / 全大写缩写 / 数字+单位 / 图片标签，
  不视为 OCR 污染
- **强制 dry-run → 确认 → --confirm** 三步流程，防止误操作
