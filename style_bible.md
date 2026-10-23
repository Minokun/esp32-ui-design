# Style Bible — EVA 深空电影感 v2（含分层烘焙与 Shader 特效规范）

> 这是"风格唯一真源"。所有生成（HTML 稿 / 分层烘焙底图 / 程序化 Shader 特效 / AI 图 / 3D / 动效）都必须引用这里的 token 与提示词。
> 改风格 = 改这个文件 + 重新生成 anchor 图，不允许各页面单独发挥。

## 1. 视觉意图（一句话）

深夜的太空舱：深蓝黑底、青与紫的冷光、玻璃质感的仪表、流体能量球特效与少量暖色提示；画面安静、层次清楚、有镜头感，不像"开发板 demo"。

参考坐标：watchOS 的克制布局 × 深空/极光的氛围 × Siri Orb 折叠光谱能量球 × 玻璃拟态材质 × 电影调色（低饱和、高对比、暗部有细节）。

## 2. 色板（核心语义 token；光效扩展色见 §2.1）

| Token | Hex | 用途 |
|---|---|---|
| bg.base | `#04060D` | 最底层 |
| bg.deep | `#0B1826` | 渐变下端 |
| surface.glass | `#FFFFFF` @ 5.5% | 玻璃卡底（静态区域走离线预烘焙） |
| stroke.glass | `#FFFFFF` @ 14% | 1px 描边 + 顶部 1px 内高光 |
| text.primary | `#F4F8FF` | 主文本/数字 |
| text.secondary | `#9FB2C6` | 辅助文本 |
| accent.cyan | `#35E0FF` | 主强调/语音状态 |
| accent.teal | `#2DF6D0` | 在线/成功/聆听波纹 |
| accent.violet | `#B07CFF` | 次强调/思考旋涡/装饰光 |
| accent.amber | `#FFC857` | 提醒 |
| danger | `#FF5470` | 错误/断连 |

规则：一屏最多 2 个强调色 + 1 个语义色；禁止纯黑 `#000000` 大面积；禁止高饱和大色块。

### 2.1 光效扩展色（仅允许用于极光/玻璃边缘/声波柱等装饰渐变，不得用于语义/文字大色块）

| Hex | 用途 |
|---|---|
| `#06121C` | 极光冷色阶（深空背景上叠加团块） |
| `#8CF6FF` | 声波柱亮端 / 高光边缘 |
| `#2AD4F0` / `#22C6E8` | 声波柱渐变中段 / 深端 |
| `#0C86A8` | 极光/玻璃反光的低饱和过渡 |

> 这些色是 Chromium 渲染 CSS `radial-gradient`/`linear-gradient` 后的实际取样值；`templates/screen_480.html` 已按此使用，验收时以"不出现刺眼跳色"为准。

## 3. 字体与字阶

| 角色 | 字体 | 字号（方屏 / 圆屏） | 字距 |
|---|---|---|---|
| 大时间/主数字 | DIN Condensed / Barlow Condensed / Bebas | 170 / 146 | -2~-3 |
| 页面标题 | 思源黑体 / MiSans Medium | 28 / 24 | +1 |
| 正文 | 思源黑体 / MiSans Regular | 22 / 20 | 0 |
| 辅助 | 同上 Regular | 16 / 14 | +0.5 |
| 标签/眉题 | Avenir Next Demi / 同族 | 12 / 11 | +2~+3（大写） |

中文必须子集化（含 `…，。！？°` 等标点，严防豆腐块）；数字用 tabular figures；单位比数值小两号、降透明度。

## 4. 几何、圆屏安全区与分层烘焙材质

- **间距**：8 栅格（8/12/16/24/32/48）；卡片内边距 22~26
- **圆角**：大卡 30（圆屏 36）/ 小卡 20 / 胶囊 999 / 图标底 8
- **圆屏安全区（480×480 圆屏）**：
  - 物理可视圆半径 $R_{\text{max}} = 240\text{px}$（圆心 `(240, 240)`）；**硬门禁**：`validate_frame.py --safe-circle 240` 要求圆外高亮前景像素 = 0；
  - 文字与交互控件建议收敛在 $R_{\text{safe}} = 206\text{px}$（距圆边留 $\ge 34\text{px}$ 缓冲）；主视觉大时钟允许用到 $R\approx228$ 的视觉带，但必须用 `?shape=circle&debug=safe_area` 人工目检；
  - 顶栏 `y >= 50px` 且左右内收至 `x: 124..356`；底部玻璃卡内收至 `(72, 264, 408, 384)` 附近；
  - 注意：Chromium 渲染的 `?shape=circle` 截图在 R=240 上会有 1 px 抗锯齿越界（仍 PASS），圆屏设计稿以 `bake_layers.py` 的 `out/screen_480_circle*.png` 为准。
- **毛玻璃分层烘焙规则**：
  - 静态背景 + 极光 + 胶片噪点 + 暗角 + 毛玻璃卡片壳（`backdrop-filter: blur(18px)` + 8° 斜切高光 + `0 24px 48px` 阴影）一律在 PC 端通过 `?mode=bake_bg` 烘焙进底图；
  - 严禁在 MCU 上实时跑大面积软件高斯模糊。

## 5. 图标规范

- 24 网格、`stroke-width: 2`、`stroke-linecap/linejoin: round`、单色（recolor 跟随主题）
- 来源优先级：Lucide / Tabler / Material Symbols（Iconify 可搜）> LLM 生成 SVG
- **存储格式**：单色图标一律用 `LVGLImage.py --cf A8` 转为单通道 Alpha 蒙版（64×64 仅 4.0KB，比 `RGB565A8` 省 67%），运行时由 LVGL `image_recolor` 或 S31 PPA `fg_fix_rgb_val` 硬件着色。

## 6. 动效与程序化 Shader 交互特效规范

| 场景 | 时长 / 帧率 | 实现方式与曲线 |
|---|---|---|
| 按压反馈 | 120ms | `lv_anim` ease-out |
| 页面转场 | 220ms | `lv_anim` ease-out，滑入 + 15% 缩放 |
| 强调/弹入 | 320ms | `lv_anim` overshoot |
| 列表入场 stagger | 每元素 +40ms | `lv_anim` ease-out |
| **语音能量球（4 态 VFX）** | 24 帧/态 @ 15~24fps | `render_shader_vfx.py` 烘焙 `180×180` 局部 `GPJM`（4 态共 264KB）：<br>• `idle`：青蓝慢呼吸 + 6 颗环绕星尘<br>• `listening`：青绿亮核 + 2 道向外声波涟漪<br>• `thinking`：紫青双旋涡 2× 速坍缩流转<br>• `speaking`：多频光谱折叠丝带 + 脉冲辉光 |
| 背景循环视频 | 12~15fps，5s | Wan3.0 首尾同帧 + `pack_frames.py --crossfade 6` |

## 7. 提示词模板（AIGC 图像/视频生成用）

**前缀（所有图共用）**

```
cinematic deep-space UI background, dark navy #05070F base, cool cyan rim light from top-left,
violet fill light on the right, soft volumetric haze, subtle film grain, low contrast in shadows,
high-end product visualization, 3D render, octane, 8k, no text, no logo, no watermark,
centered composition with negative space at top for UI overlay
```

**负面词（必带）**

```
text, letters, watermark, logo, UI elements, buttons, frames, borders, cluttered, oversaturated,
neon rainbow, plastic toy, lowres, jpeg artifacts, banding, harsh shadows
```

## 8. 验收清单（任一不过就重做）

- [ ] 颜色只用了 §2 的 token（无跳出色）
- [ ] 圆屏布局通过 `validate_frame.py --safe-circle 240`（圆外高亮像素 = 0；方形稿应 FAIL 以证明门禁有效）
- [ ] 静态毛玻璃与噪点已通过 `?mode=bake_bg` 预烘焙，未在 MCU 侧开软件模糊
- [ ] 语音球四态特效通过 `vfx_orb_sheet.png` 目检，且首尾帧 `seam_mae <= 11.0`（参考：speaking 10.80 → crossfade 后 6.25）
- [ ] 单色图标采用 `A8` 格式（≤4.5KB/个），视频帧强制为 Baseline DCT JPEG (`SOF0`)
- [ ] 字阶 ≥3 档且中文字库含 `…` 等标点（无豆腐块）
- [ ] 素材总体积 ≤ 分区预算（单套语音球 4 态 ≤300KB、背景视频 ≤1.5MB）
- [ ] **1:1 复刻门禁**：`bake_to_lvgl.py compare` 的整屏 MAE ≤ 12/255（当前基线：主表盘 5.26、菜单 3.71），且 `metrics.json.regions` 主表盘全部 `dx=dy=0`、菜单允许 ≤1 px 抗锯齿差
- [ ] **字体授权**：出货固件不得内嵌 macOS 系统字体（DIN Condensed/Avenir Next/Hiragino），必须换可商用字体（思源黑体/MiSans/Inter 等）

---

## 9. 实测基线（2026-10-23 v3，数字以 `out/metrics.json` 为准）

| 项 | 值 |
|---|---|
| 主表盘 1:1 | MAE **5.26/255**，还原度 **97.94%**，PSNR 24.44 dB，≤1 阶 85.5%，16 区域偏移 0 px |
| 控制菜单 1:1 | MAE **3.71/255**，还原度 **98.55%**，PSNR 27.27 dB，≤1 阶 95.65%，22 区域中 21 区 0 px、1 区 1 px |
| 烘焙底图 | Chromium `?mode=bake_bg` 与真值背景层 MAE=0（Python 兜底版 5.9/16.5） |
| RGB565 资产 | `eva_face3.bin` 1,293,328 B（2×480×480 底图 + 16×88×88 球） |
| 同源字库 | 11 档 4bpp，位图 70.7 KB |
| 运行时脏区 | 9,424 px = 4.09% |
| 上板门禁 | `bake_to_lvgl.py compare` MAE ≤ 12/255，超限 exit 1 |


## 10.5 ASTRO 深空单页（2026-10-24）

- 画布/安全区：480×480，圆屏可见区 R≤232，文字/关键图形放 R≤205；
- 背景：深空 #02040A→#0A1730 + 蓝/紫星云 + 细星点 + 行星/卫星 + 极淡轨道环（烘焙层，不在 MCU 实时画）；
- 动态层：30 帧预旋转宇航员（180×180，media 分区零拷贝）+ 88×88 能量球光晕 + 3 轨道粒子 + 3 流星；
- HUD：DIN 76 数字大时间 + Avenir/Montserrat 14 日期/状态；禁止把任意中文回复塞进子集字体 label；
- 交互：轻触核心区 → 2.6s 跃迁（bg1 warp 变体 + 旋转/星流加速）；
- 实测（S31，480×480 RGB565）：渲染循环 ~33ms、~23 fps、refr 8~16ms、copy ~10ms。
