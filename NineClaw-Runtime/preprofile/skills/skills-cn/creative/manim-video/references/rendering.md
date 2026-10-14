# 渲染参考

## 前置要求

```bash
manim --version       # Manim CE
pdflatex --version    # LaTeX
ffmpeg -version       # ffmpeg
```

## CLI 参考

```bash
manim -ql script.py Scene1 Scene2    # draft (480p 15fps)
manim -qm script.py Scene1           # medium (720p 30fps)
manim -qh script.py Scene1           # production (1080p 60fps)
manim -ql --format=png -s script.py Scene1  # preview still (last frame)
manim -ql --format=gif script.py Scene1     # GIF output
```

## 质量预设

| 标志 | 分辨率 | FPS | 用途 |
|------|-----------|-----|----------|
| `-ql` | 854x480 | 15 | 草稿迭代（布局、时序） |
| `-qm` | 1280x720 | 30 | 预览（用于文本较多的场景） |
| `-qh` | 1920x1080 | 60 | 成品制作 |

**文本渲染质量：** `-ql`（480p15）会产生明显较差的文本字距与可读性。对于包含大量文本的场景，应使用 `-qm` 预览静帧，以发现 480p 下无法看出的缺陷。`-ql` 仅用于测试布局和动画时序。

## 输出结构

```
media/videos/script/480p15/Scene1_Intro.mp4
media/images/script/Scene1_Intro.png  (from -s flag)
```

## 使用 ffmpeg 拼接

```bash
cat > concat.txt << 'EOF'
file 'media/videos/script/480p15/Scene1_Intro.mp4'
file 'media/videos/script/480p15/Scene2_Core.mp4'
EOF
ffmpeg -y -f concat -safe 0 -i concat.txt -c copy final.mp4
```

## 添加旁白

```bash
# Mux narration
ffmpeg -y -i final.mp4 -i narration.mp3 -c:v copy -c:a aac -b:a 192k -shortest final_narrated.mp4

# Concat per-scene audio first
cat > audio_concat.txt << 'EOF'
file 'audio/scene1.mp3'
file 'audio/scene2.mp3'
EOF
ffmpeg -y -f concat -safe 0 -i audio_concat.txt -c copy full_narration.mp3
```

## 添加背景音乐

```bash
ffmpeg -y -i final.mp4 -i music.mp3 \
  -filter_complex "[1:a]volume=0.15[bg];[0:a][bg]amix=inputs=2:duration=shortest" \
  -c:v copy final_with_music.mp4
```

## 导出 GIF

```bash
ffmpeg -y -i scene.mp4 \
  -vf "fps=15,scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  output.gif
```

## 宽高比

```bash
manim -ql --resolution 1080,1920 script.py Scene  # 9:16 vertical
manim -ql --resolution 1080,1080 script.py Scene  # 1:1 square
```

## 渲染工作流

1. 使用 `-ql` 对所有场景进行草稿渲染
2. 在关键时刻预览静帧（`-s`）
3. 仅修复并重新渲染有问题的场景
4. 使用 ffmpeg 拼接
5. 检查拼接后的输出
6. 使用 `-qh` 进行成品渲染
7. 重新拼接并添加音频

## manim.cfg——项目配置

在项目目录中创建 `manim.cfg`，用于设置各项目的默认值：

```ini
[CLI]
quality = low_quality
preview = True
media_dir = ./media

[renderer]
background_color = #0D1117

[tex]
tex_template_file = custom_template.tex
```

这样就不必在每个场景中重复设置 CLI 标志和 `self.camera.background_color`。

## Sections——章节标记

在场景内标记各个章节，以便有组织地输出：

```python
class LongVideo(Scene):
    def construct(self):
        self.next_section("Introduction")
        # ... intro content ...

        self.next_section("Main Concept")
        # ... main content ...

        self.next_section("Conclusion")
        # ... closing ...
```

渲染单独章节：`manim --save_sections script.py LongVideo`
这会为每个章节输出单独的视频文件——对于只想重新渲染其中一部分的长视频尤其有用。

## manim-voiceover 插件（推荐用于带旁白的视频）

官方 `manim-voiceover` 插件将 TTS 直接集成到场景代码中，并自动让动画时长与旁白时长同步。与上文手动使用 ffmpeg 封装的方法相比，这种方式简洁得多。

### 安装

```bash
pip install "manim-voiceover[elevenlabs]"
# Or for free/local TTS:
pip install "manim-voiceover[gtts]"    # Google TTS (free, lower quality)
pip install "manim-voiceover[azure]"   # Azure Cognitive Services
```

### 用法

```python
from manim import *
from manim_voiceover import VoiceoverScene
from manim_voiceover.services.elevenlabs import ElevenLabsService

class NarratedScene(VoiceoverScene):
    def construct(self):
        self.set_speech_service(ElevenLabsService(
            voice_name="Alice",
            model_id="eleven_multilingual_v2"
        ))

        # Voiceover auto-controls scene duration
        with self.voiceover(text="Here is a circle being drawn.") as tracker:
            self.play(Create(Circle()), run_time=tracker.duration)

        with self.voiceover(text="Now let's transform it into a square.") as tracker:
            self.play(Transform(circle, Square()), run_time=tracker.duration)
```

### 主要功能

- `tracker.duration`——旁白总时长（秒）
- `tracker.time_until_bookmark("mark1")`——让特定动画与特定词语同步
- 自动生成 `.srt` 字幕文件
- 在本地缓存音频——重新渲染时不会重新生成 TTS
- 支持：ElevenLabs、Azure、Google TTS、pyttsx3（离线）以及自定义服务

### 使用书签精确同步

```python
with self.voiceover(text='This is a <bookmark mark="circle"/>circle.') as tracker:
    self.wait_until_bookmark("circle")
    self.play(Create(Circle()), run_time=tracker.time_until_bookmark("circle", limit=1))
```

对于任何带旁白的视频，都推荐使用这种方法。上文手动使用 ffmpeg 封装的工作流仍适合添加背景音乐或进行后期音频混合。
