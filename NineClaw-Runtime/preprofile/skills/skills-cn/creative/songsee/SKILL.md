---
name: songsee
description: "通过 CLI 生成音频频谱图及特征（mel、chroma、MFCC）。"
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Audio, Visualization, Spectrogram, Music, Analysis]
    homepage: https://github.com/steipete/songsee
prerequisites:
  commands: [songsee]
---

# songsee

根据音频文件生成频谱图和多面板音频特征可视化。

## 前置条件

需要安装 [Go](https://go.dev/doc/install)：
```bash
go install github.com/steipete/songsee/cmd/songsee@latest
```

可选：安装 `ffmpeg`，用于处理 WAV/MP3 以外的格式。

## 快速开始

```bash
# Basic spectrogram
songsee track.mp3

# Save to specific file
songsee track.mp3 -o spectrogram.png

# Multi-panel visualization grid
songsee track.mp3 --viz spectrogram,mel,chroma,hpss,selfsim,loudness,tempogram,mfcc,flux

# Time slice (start at 12.5s, 8s duration)
songsee track.mp3 --start 12.5 --duration 8 -o slice.jpg

# From stdin
cat track.mp3 | songsee - --format png -o out.png
```

## 可视化类型

使用 `--viz` 并传入以逗号分隔的值：

| 类型 | 说明 |
|------|-------------|
| `spectrogram` | 标准频率频谱图 |
| `mel` | Mel 标度频谱图 |
| `chroma` | 音级分布 |
| `hpss` | 谐波与打击成分分离 |
| `selfsim` | 自相似矩阵 |
| `loudness` | 随时间变化的响度 |
| `tempogram` | 节拍速度（tempo）估计 |
| `mfcc` | Mel 频率倒谱系数 |
| `flux` | 频谱通量（起音检测） |

多个 `--viz` 类型会以网格形式渲染到一张图像中。

## 常用选项

| 选项 | 说明 |
|------|-------------|
| `--viz` | 可视化类型（以逗号分隔） |
| `--style` | 调色板：`classic`、`magma`、`inferno`、`viridis`、`gray` |
| `--width` / `--height` | 输出图像尺寸 |
| `--window` / `--hop` | FFT 窗长与帧移（hop size） |
| `--min-freq` / `--max-freq` | 频率范围过滤器 |
| `--start` / `--duration` | 音频的时间切片 |
| `--format` | 输出格式：`jpg` 或 `png` |
| `-o` | 输出文件路径 |

## 注意事项

- WAV 和 MP3 可原生解码；其他格式需要 `ffmpeg`
- 可以使用 `vision_analyze` 检查输出图像，以便进行自动化音频分析
- 适用于比较音频输出、调试音频合成或记录音频处理流水线
