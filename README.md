# 第一阶段：股票横截面选股与量化回测基本功

面向大模型研究者的 Python 可复现量化研究入门指南。

[![build and publish](https://github.com/shjdjjfi/quant-cross-sectional-guide/actions/workflows/build.yml/badge.svg)](https://github.com/shjdjjfi/quant-cross-sectional-guide/actions/workflows/build.yml)

## 文件

- `main.qmd`：Computo/Quarto 正文。
- `_quarto.yml`：论文元数据与输出格式。
- `references.bib`：参考文献。
- `environment.yml`：GitHub Actions 使用的 Python 环境。
- `src/phase1_cross_sectional_backtest.py`：完整横截面回测脚本。
- `.github/workflows/build.yml`：Computo 官方自动编译与发布工作流。

## 在线自动编译

将本仓库文件上传到 GitHub 后，进入 **Actions** 查看自动编译；进入 **Settings → Pages**，将 Source 设置为 **GitHub Actions**。
