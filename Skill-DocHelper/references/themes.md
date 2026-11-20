# 自定义审阅风格

主题是独立的 CSS 文件。页面共享同一份 HTML、批注逻辑和布局样式。内置的 [纸本](../assets/themes/folio.css)、[潮汐](../assets/themes/tide.css) 和 [夜读](../assets/themes/midnight.css) 分别提供纸色衬线、冷色阅读和深色阅读配置。

在当前工作目录创建 `.dochelper/themes/moss.css`，写入下面的样式，就能在“纸本”的基础上改配色。文件名去掉后缀即为主题 ID，以小写英文字母开头，可继续使用小写字母、数字和连字符，最多 64 个字符。第一行注释是选择器里的显示名。

```css
/* 苔绿 */
@import url('/themes/folio.css');
:root {
  color-scheme: light;
  --paper: #f5f7ef;
  --ink: #263224;
  --accent: #496332;
  --accent-tint: #e2ead8;
}
```

若希望完全替换已有主题，可以将内置样式完整复制到工作区的同名文件，再调整下列变量。覆盖同名主题时请直接编辑复制的样式，避免导入自身。

| 设置 | 对应变量 |
| --- | --- |
| 页面、次级区域、输入框 | `--paper`、`--surface`、`--input` |
| 正文、辅助文字、细线 | `--ink`、`--muted`、`--rule` |
| 强调色、浅底、强调色上的文字 | `--accent`、`--accent-tint`、`--on-accent` |
| 标题字体、正文字体、圆角 | `--title-face`、`--body-face`、`--radius` |
| 代码背景、默认字色、行号 | `--code-bg`、`--code-ink`、`--code-line` |
| 关键字、字符串、数字、注释、函数 | `--code-key`、`--code-str`、`--code-num`、`--code-cmt`、`--code-fn` |

保存后刷新阅读页，即可在主题菜单中选择。工作区内同名文件优先，可为当前项目覆盖内置风格。用 `serve --theme moss` 设为本次服务默认主题，也可将 `theme=moss` 放进审阅链接。字体使用本机已安装字体和 CSS 后备字体，无需联网。主题切换只影响显示，同一版本的批注在所有风格下共享。
