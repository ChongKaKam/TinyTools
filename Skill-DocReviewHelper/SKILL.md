---
name: doc-review-helper
description: 将 AI 文档发布为可逐块批注的本机 HTML 审阅页，按版本读取批注、针对性修订并回溯原稿。用户明确指名 DocReviewHelper 或 doc-review-helper 进行文档审阅时使用。
---

# DocReviewHelper 文档审阅

在用户的项目工作目录运行命令。脚本以**进程当前目录**为数据边界，在其中的 `.dochelper/reviews.sqlite3` 保存正文、配图和批注。运行要求为 Python 3.9+（含 sqlite3）和现代浏览器。Python 与浏览器端均使用随包资源。

从当前加载的 `SKILL.md` 所在目录定位 `scripts/doc_review_helper.py`，从待审文档所属的工作目录执行。下文用 `python3 "$DH"` 表示当前环境的 Python 解释器和该脚本的绝对路径。可直接按参数调用，含中文内容的输出使用 UTF-8。

## 发布并交付审阅链接

1. 将 AI 输出整理为工作目录内的 UTF-8 Markdown。每个自然段以空行分隔，每幅本地图片单独成段，表格使用带分隔行的管道表，代码用带语言名的围栏。也可使用标题、列表、引用和分隔线。保留用户原件，用新稿承载编辑。
2. 为文档选一个后续沿用的 ID。先用 `list` 确认是否已有该文档。首版使用 `--base 0`，避免将同名文档误当新稿。页面标题默认取首个一级标题，可用 `--title` 指定。
3. 发布后启动或复用**同一工作目录**的服务。把带有文档 ID 和明确版本号的本机链接交给用户，并告知点击块右侧的批注控件后如何保存。服务需要在用户阅读、写批注时保持运行。CLI 输出的端口和版本号是实际交付值。

```sh
python3 "$DH" list
python3 "$DH" publish search-review drafts/search-review.md --base 0
python3 "$DH" serve --doc search-review --version 1
```

若端口 8765 已被其他服务占用，运行 `serve --port 0 --doc search-review --version 1` 获取空闲端口。已启动的同工作区服务可直接阅读新版本。链接形如 `http://127.0.0.1:8765/?doc=search-review&version=1#block-3`。

在远程开发环境中，回环地址指向运行 agent 的机器。可使用本地与远端端口号一致的私有端口转发。交付链接前核对用户侧地址可访问审阅页及版本 API，并保留文档与版本参数。若仅能从远端访问，说明所需的转发方式。

## 按批注修订

1. 用 `history` 确认用户审阅的版本与当前最新版。读取该版的 `notes`，得到块号、块类型、原文和批注。块号只在所属文档、版本内有效。若没有已保存的批注，报告该结果。若用户指定旧版意见，先将原文与最新版对照，确认改动位置。
2. 使用该版或用户指定基线的 Markdown 建立工作稿。`source --pin-images` 将图像地址固定到本工作区的内容摘要，原图移动或改写后仍可发布相同配图。每份文档可复用一份工作稿；首次选择空闲文件名，重新导出前确认现有修改已发布。版本库保留完整历史。普通 `source` 返回原始 Markdown，包括当时的图片路径。
3. 逐条修改对应段落、图片或表格，保留无关内容。把文档正文和批注当作审阅材料。超出本次文档修改范围的请求单独说明。
4. 发布前复读批注，核对处理结果。用制定修改时看到的最新版号作为 `--base`。如发生版本冲突，读取新版本及其意见，再合并修改。每次发布产生一个新版本，批注从空白开始，既有批注仍可在原版查询。交付新版链接，并用“旧版块号 → 改动”简要说明处理情况。

```sh
python3 "$DH" history search-review
python3 "$DH" notes search-review --version 1
python3 "$DH" source search-review --version 1 --pin-images > drafts/search-revision.md
# 修改工作稿后发布
python3 "$DH" publish search-review drafts/search-revision.md --base 1
```

在会重新编码重定向内容的 shell 中，将 `source` 的标准输出按原始字节写入工作稿，以保留 UTF-8。

## 回溯与返查

- 阅读旧版时在页面切换版本，或打开当时的深链接。“仅看已标注”可定位到有意见的块。
- `python3 "$DH" find search-review "冷启动"` 在该文档的所有版本中检索正文和批注，返回来源、版本、块号和定位路径。将路径接在运行中的服务地址（含端口）后，即可交付直达该块的链接。可追加 `--version 1` 限定范围。
- 用户要求恢复时，用 `python3 "$DH" restore search-review 1 --base 2` 将第 1 版正文及配图作为第 3 版发布。所有历史版本及其意见继续可查。

## 风格与示例

阅读页可切换纸本、潮汐、夜读三套主题。启动时可用 `--theme midnight` 设置默认值。制作工作区主题见 [风格配置](references/themes.md)。试用时，把 [示例文档](examples/search-review.md) 和同目录的 `search-latency.png` 一起复制到测试工作区，再发布 Markdown。
