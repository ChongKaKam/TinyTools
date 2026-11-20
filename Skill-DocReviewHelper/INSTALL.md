# 给 agent 的 DocReviewHelper 配置说明

用户让你配置 DocReviewHelper 时，请在**当前 agent 环境**完成安装和验证，并返回一条用户可以直接发送的审阅指令。默认配置到当前用户的技能目录；用户指定项目范围时，使用该项目的技能目录。整个过程可以离线完成。

## 找到技能和解释器

- **收到 ZIP**：读取包顶层的本说明，将包解到独立临时目录。里面的 `doc-review-helper/` 是完整技能，入口为 `doc-review-helper/SKILL.md`。
- **收到源码目录**：在该目录找到本说明和 `tools/package_skill.py`。用下面选出的解释器运行 `tools/package_skill.py --output <临时目录>/doc-review-helper.zip`，再按上一项处理。打包清单只包含随技能分发的文件。
- 选择能执行 `import sqlite3` 的 Python 3.9+。可探测 `python3`、`python`、`py -3` 或宿主提供的 Python。DocReviewHelper 的运行依赖全部来自标准库。

## 在当前宿主中注册

先识别正在执行这项任务的 agent，再选择它实际会加载的技能目录。下面的 `~` 表示目标用户的主目录。用户与项目两种范围选其一。

| 本地宿主 | 用户技能目录 | 项目技能目录 | 用户显式调用 |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/` | `<项目>/.agents/skills/` | `$doc-review-helper` |
| Claude Code | `~/.claude/skills/` | `<项目>/.claude/skills/` | `/doc-review-helper` |

Codex 使用随包的 `agents/openai.yaml` 控制显式调用。Claude Code 安装时，在**待安装副本**的 `SKILL.md` 顶部 YAML 中加入 `disable-model-invocation: true`，使它只在用户点名时运行。其他宿主按其配置或官方技能说明确认目录、显式调用语法和脚本执行能力；托管环境采用其支持的导入途径。[Codex 技能目录](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) · [Claude Code 技能配置](https://code.claude.com/docs/en/skills)

将准备好的 `doc-review-helper/` 完整复制到选定目录下，使最终路径为 `<技能目录>/doc-review-helper/SKILL.md`。复制后移走压缩包，技能也应能独立运行。已有安装与待安装文件一致时直接验证。遇到不同内容时，先辨别是否属于该技能，保留本地改动及额外文件；需要替换旧版时在技能发现目录之外保留可恢复副本。遇到同名的其他技能时，说明冲突并请用户决定。

## 从安装位置验收

1. 从**最终安装目录**定位脚本 `scripts/doc_review_helper.py` 与示例 `examples/`。新建临时工作目录，将 `search-review.md` 和 `search-latency.png` 复制进去。以下命令均以该工作目录为当前目录，使用实际解释器与脚本绝对路径。
2. 执行下列参数。首条应发布第 1 版，第二条应返回空批注数组，第三条的 UTF-8 输出应与示例 Markdown 一致。确认临时工作目录生成了 `.dochelper/reviews.sqlite3`。

   ```text
   <Python> -X utf8 <脚本> publish install-check search-review.md --base 0
   <Python> -X utf8 <脚本> notes install-check --version 1
   <Python> -X utf8 <脚本> source install-check --version 1
   ```

3. 执行 `<Python> -X utf8 <脚本> serve --port 0 --doc install-check --version 1`。用服务打印的地址读取审阅页，再从同一服务读取 `/api/view?doc=install-check&version=1`，确认返回第 1 版并含带 `asset` 的图片块。结束本次测试服务，清理临时目录。若环境限制本机监听，分别报告已通过的命令行验证和受限的网页验证。
4. 通过宿主的技能列表或显式调用入口核对 `doc-review-helper`。如果当前会话需要重新加载才能发现技能，说明刷新方式和已验证到哪一步。没有技能注册机制的环境可提供“读取持久目录中的 `SKILL.md` 并按其执行”的调用方法，并说明使用范围。

最后用目标环境的实际值报告**宿主、安装路径、验证结果、首次调用示例**。例如在 Codex 中交付 `$doc-review-helper 请把 README.md 发布为本机审阅页`。后续审阅从用户文档所属的工作目录执行，版本和批注保存在该目录。
