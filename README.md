# 嘉骏15周年 AI双星登场 演示程序

## 快速启动
```bash
cd jiajun-show
./start.sh
```
然后打开浏览器：http://localhost:5001

## 使用说明
- **双发**：同时发给MM和MU
- **→MM / →MU**：只发给某一个
- **📋剧本**：展开预设台词按钮，一键播放

## 接入AI（第二阶段）
填写 app.py 里的环境变量：
- XFYUN_APPID / XFYUN_APIKEY / XFYUN_APISECRET（讯飞）

## 文件结构
- app.py — 后端
- templates/index.html — 前端UI
- start.sh — 一键启动
