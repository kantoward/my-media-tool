# 我的媒体工具 v1

一个适合 iPhone Safari / PWA 使用的个人媒体处理工具。

## v1 功能

- 图片加文字水印
- 视频加文字水印
- 图片固定矩形去水印（OpenCV inpaint）
- 视频固定矩形去水印（逐帧 inpaint，并尽量保留原音频）
- 单次任务文件自动清理
- 最大上传 500 MB

> 这是个人工具第一版。链接提取和移动水印跟踪没有塞进这一版，避免把“能稳定运行”和“支持所有网站”混在一起。

## 本机运行

需要 Python 3.12+ 和 FFmpeg。

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

然后浏览器打开 http://127.0.0.1:8080

## Docker 运行

```bash
docker build -t my-media-tool .
docker run --rm -p 8080:8080 my-media-tool
```

打开 http://127.0.0.1:8080

## 部署

推荐使用任何支持 Docker 的容器平台。把整个项目上传到 Git 仓库后，创建 Web Service，并让平台按 Dockerfile 构建即可。

## 重要限制

1. 视频去水印是“固定矩形区域”的逐帧修复；移动水印、复杂背景的效果可能不理想。
2. 第一版没有做任意网站链接下载。后续应针对你实际使用的平台逐个添加，并遵守对应网站的使用规则。
3. 生产环境建议再加入认证、速率限制、任务大小限制、磁盘配额和更严格的文件类型校验。
