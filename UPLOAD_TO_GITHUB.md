# 无需终端的 GitHub 上传步骤

建议仓库名称：`quant-cross-sectional-guide`

1. 在 GitHub 新建一个 **Public** 仓库，Owner 选择 `shjdjjfi`，Repository name 填 `quant-cross-sectional-guide`。
2. 不要额外初始化 README、`.gitignore` 或 License。
3. 解压本 ZIP。
4. 在空仓库页面点击 **uploading an existing file**，将解压目录内的全部文件和文件夹拖入网页。
5. 必须确保仓库根目录直接出现：
   - `.github`
   - `_quarto.yml`
   - `main.qmd`
   - `environment.yml`
   - `references.bib`
6. 点击 **Commit changes**。
7. 打开仓库的 **Actions** 页面，等待 `Main Workflows` 变为绿色。
8. 打开 **Settings → Pages**，在 **Build and deployment** 中将 Source 设为 **GitHub Actions**。
9. 发布网址应为：`https://shjdjjfi.github.io/quant-cross-sectional-guide/`

注意：不要把 ZIP 文件本身上传到仓库；必须先解压并上传其中内容。
