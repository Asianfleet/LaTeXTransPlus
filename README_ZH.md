<div align="center">

[English](README.md) | 中文

<img src="./assets/logo.png" width="100%"></img>

**LaTeXTransPlus**

直接翻译 LaTeX 论文源码，并在尽量保持文档结构的前提下生成多语言 PDF。

</div>

LaTeXTransPlus 直接处理 LaTeX 源码项目，再重构并编译翻译后的项目。项目提供基于源码的 Heavy 工作流（`latextrans`），以及包含 Heavy 和 PDF 转 Markdown Lite 工作流的 Textual 终端 UI（`latextrans-tui`）。

## 安装

使用 Python 3.10 或更高版本，并在项目环境中安装：

```bash
pip install -e .
```

需要编译 PDF 时，请安装 [MiKTeX](https://miktex.org/download) 或 [TeX Live](https://www.tug.org/texlive/)。Lite 还需要 `pandoc`、XeLaTeX 和 MinerU API token。

## 快速开始

使用 Heavy 工作流翻译 arXiv 论文：

```bash
latextrans --arxiv 2508.18791
```

翻译本地项目或压缩包：

```bash
latextrans --project D:\path\to\paper_project
```

将平台脚本目录加入 `PATH` 后，启动终端 UI：

```bash
latextrans-tui
```

### TUI 用法

运行下面的命令前，必须先将对应平台的包装脚本目录加入 `PATH`：Windows 使用 `scripts/windows`，Linux 使用 `scripts/linux`，macOS 使用 `scripts/macos`。这些脚本会先激活 `latextrans` Conda 环境，再调用已安装的命令。Linux 和 macOS 还需先执行 `chmod +x scripts/<platform>/latextrans scripts/<platform>/latextrans-tui`。

启动时选择工作流：

```bash
latextrans-tui --engine heavy
latextrans-tui -e lite
```

Heavy 支持 arXiv ID 或 URL、本地 LaTeX 项目、源码压缩包和公开源码压缩包 URL。Lite 每个任务接受一个 arXiv ID、PDF URL 或本地 PDF 路径；需要处理多个 PDF 时，请在同一个 TUI 会话中分别创建任务。

Heavy 结果默认写入 `outputs/`，Lite 结果默认写入 `output-lite/`。完整配置、语言代码、模型设置、术语审核、校验策略和更多使用示例请参阅[详细配置与使用说明](docs/configuration-and-usage.md)。

## 主要能力

- 尽量保留 LaTeX 命令、公式、环境、标题、占位符和交叉引用。
- 支持 arXiv ID/URL、本地项目、压缩包和公开源码压缩包 URL。
- 支持源语言与目标语言、项目术语、校验重试和 JSON Lines 事件流配置。
- Heavy 与 Lite 工作流相互独立，并为每个项目保存日志和生成文件。

## 致谢

LaTeXTransPlus 基于 [LaTeXTrans](https://github.com/NiuTrans/LaTeXTrans) 项目开发。
