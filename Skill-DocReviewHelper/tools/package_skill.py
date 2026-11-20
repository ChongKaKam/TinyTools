"""Build the distributable DocReviewHelper ZIP with Python 3.9+."""

import argparse
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "doc-review-helper.zip"
FILES = (
    "INSTALL.md",
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/doc_review_helper.py",
    "scripts/review_server.py",
    "scripts/review_store.py",
    "assets/index.html",
    "assets/app.css",
    "assets/app.js",
    "assets/render.js",
    "assets/themes/folio.css",
    "assets/themes/midnight.css",
    "assets/themes/tide.css",
    "references/themes.md",
    "examples/search-review.md",
    "examples/search-latency.png",
)


def build(output):
    if output.suffix.lower() != ".zip":
        raise ValueError("输出文件须使用 .zip 扩展名")
    if output == DEFAULT_OUTPUT and output.parent.is_symlink():
        raise ValueError("dist 目录不能是符号链接")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with ZipFile(stream, "w") as archive:
                for relative in FILES:
                    source = ROOT / relative
                    if source.resolve(strict=True) != source or not source.is_file():
                        raise ValueError(f"分发文件须为源码目录内的常规文件：{relative}")
                    name = relative if relative == "INSTALL.md" else "doc-review-helper/" + relative
                    entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    archive.writestr(entry, source.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
        temporary.chmod(0o644)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="生成 DocReviewHelper 安装包")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="输出 ZIP 路径")
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"打包失败：{error}\n")
    print(args.output.absolute())


if __name__ == "__main__":
    main()
