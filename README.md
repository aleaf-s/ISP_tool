# ISP RAW Visual Simulator V0.4.5

桌面端 RAW ISP 视觉效果仿真、参数调试与离线校准工具。V0.4.5
参考 ART/RawTherapee 的中央预览与单一参数检查器，并保留 Simatest
式的有序 ISP Pipeline。默认工作区强调快速调参，完整工程信息通过
Advanced、Scope 和专家模式按需显示。

## 启动

双击 `启动ISP仿真工具.bat`，或者：

```powershell
cd "D:\Me\个人脚本\isp_raw_simulator"
python run.py
```

启动后可在主界面直接查看当前模块的自动建议状态，或点击顶部
`Calibration` 打开完整校准工作区。

## V0.4.5 自定义 ROI 与最终效果分析

- ROI 分块改为明确的“先框选外接区域 → 在当前选区内自定义分块”
- 自定义行数、列数和单元格内缩比例，最多生成 96 个 ROI
- Bayer ROI 使用向内偶数对齐，小框不会越出用户选区
- 分块后保留外接区域虚线和行列数标记，可确认分块来源
- `预览 → 最终效果与模块影响` 打开独立分析页
- 最终效果页列出所有 ISP 模块，点击模块后临时旁路它，并重新运行后续流水线
- 同时显示完整 Final、Bypass Final 和 P99 归一化差异热力图
- 提供 Mean/P95/Max 绝对差异与有效变化像素比例
- 最终效果计算位于独立工作线程，快速切换模块时丢弃过期 UI 结果

本版同步完成一次功能重叠清理：

- 固定 4×6、6×4 ROI 入口合并为一个自定义分块对话框
- ROI 管理器只负责选择、增删和坐标微调，不再重复提供分块入口
- 顶部 `Scope` 和 `View` 合并为 `预览` 下拉菜单
- 删除右侧自动分析区从未显示的 `Open` 按钮
- Calibration 不再创建四套不可见的旧 LSC/AWB/AE/CCM 标签页

以下看似重复的入口仍有不同用途，因此保留：

- 主预览 Compare：比较当前模块输入/输出；最终效果页：比较模块旁路对最终输出的影响
- Gray Picker：单击局部灰点快速估计；Auto AWB：带样本筛选、置信度和证据的完整分析
- 顶部 Calibration：打开全局工作区；当前模块 Auto/More：直接跳转到对应校准步骤
- 菜单栏文件操作：为快捷键和键盘访问保留；工具栏提供高频操作

## V0.4.4 多图校准与参数确认

- `导入图像` 支持一次选择多张 RAW/PNG/TIFF；多文件读取在后台执行，主界面保持响应
- 顶部图像下拉框用于切换工作集，每张图独立保存 Pipeline、自动校准会话、ROI 和未确认参数预览
- 当前模块提供下拉式 `校准刷`，可选择目标图像，也可把 BLC/DPC/LSC 或 WB/CCM 组应用到其它全部图像
- 校准刷复制模块参数、启用状态以及 LSC Mesh/DPC Map 等模块状态，并提示尺寸和 Bayer Pattern 兼容性
- 所有手工参数保持实时预览；一旦修改，检查器明确显示 `应用 / 撤销预览`，CCM 3×3 矩阵同样适用
- ROI 支持最多 24 个矩形；框选外接区域后可生成 4×6 色块采样框
- 活动 ROI 支持八方向控制点缩放、拖动、方向键微调，以及坐标/尺寸管理器
- CCM 自动标定会优先复用已建立的 24 个 ROI，避免重复框选四角
- 自动白平衡默认使用 `Robust Neutral`：排除暗部、高光、纹理边缘，检查空间覆盖率和 Gr/Gb 一致性
- Gray Picker 改为复用 AWB 估计器，并显示置信度及待应用状态

## V0.4.3 简洁工作区

- 默认界面只保留 `ISP Pipeline / 图像预览 / 当前模块参数` 三个区域
- 顶部只保留 Open、Save、Export、Calibration、Scope 和 View
- Stage 任意输出选择、模块诊断和性能状态移入专家模式
- 当前模块的 Enable、Auto、Reset 合并到一个紧凑标题区
- 每个模块默认只显示 2～5 组常用参数，其他参数进入 `Advanced`
- CCM 的 Normalize、Copy/Paste、Import/Export 收拢到一个菜单
- Scope 默认关闭，点击后才显示当前 Histogram、Waveform、Vectorscope 或 Statistics
- Waveform 和 Vectorscope 的设置只在各自页签中显示
- Calibration 使用模块下拉框和 `Data → Analyze → Review → Apply` 两列步骤流
- Calibration 根据状态只显示当前可执行的 Preview 或 Apply/Revert
- 简洁模式、专家模式和各模块 Advanced 展开状态写入 V4 `ui_state`
- 保持 V0.4.2 的后台分析、有界缓存、DPI、滚轮路由和任务代际保护

## V0.4.2 流畅度与界面密度

- 主预览与 Histogram/Waveform/Vectorscope/Statistics 解耦：先显示图像，分析延迟到后台线程执行
- 底部只计算当前分析页签；折叠时完全停止分析任务
- 增加阶段 RGB 和分析结果两级有界 LRU 缓存，切换页签与重复查看可直接复用
- Canvas resize 使用 50 ms 防抖，分析使用 220 ms 防抖，鼠标/对比/ROI 更新限制为约 30 Hz
- View → Performance Details 提供 Pipeline、View、Raster、Analysis 的 latest、P50、P95 和缓存信息
- 顶部动作收拢为 Export、View、ROI、Display 等菜单，Calibration 数据操作收拢为 Load、DPC Map、Manage
- 自动建议卡片只显示当前状态需要的 Analyze、Preview、Apply、Revert 或 Cancel
- 使用 Tk named fonts，并在创建窗口前启用 Windows Per-Monitor DPI awareness
- View → UI Scale 提供 Follow System、90%、100%、110%、125% 和 150%
- 滚轮按鼠标所在控件路由到参数区、Calibration 选项、文件/ROI 列表和诊断文本；图像画布继续用于缩放
- UI Scale、分析页签、Performance Details、Artifact Overlay 和 Calibration 滚动位置写入 `ui_state`

## V0.4.1 调试体验

- 统一深色 Theme、Windows 高 DPI 缩放和可复用状态样式
- 主界面 Pipeline 显示模块类别、启用状态、自动建议和处理耗时
- 预览顶部集中提供 Fit、1:1、ROI、Gray Picker、Compare 和 Artifact Overlay
- 预览角落显示 Stage、Domain、Zoom 和 ROI；Compare 增加可见拖动手柄
- 右侧检查器同时呈现 Module State、Manual Parameters、Automatic Recommendation 和 Diagnostics
- Histogram、Waveform、Vectorscope、Statistics 分析区可整体折叠
- Calibration 改为九模块统一导航和“数据/策略—建议/证据”三列工作流
- Recommendation 使用明确的 Running、Suggested、Previewing、Applied、Stale、Failed 状态
- Dark/Flat 文件与 Noise ROI 使用可管理、可校验的列表
- Artifact 使用缩略图画廊，支持 Main、Overlay、Side by Side、Flicker、透明度和导出
- 窗口、分栏、折叠区、Calibration 模块、Artifact 模式和最近方法写入 V4 `ui_state`

## 基础能力

- 裸 RAW：uint8、uint16 LE/BE、MIPI RAW10/12/14、offset、stride
- 相机 RAW：rawpy
- Bayer：RGGB、GRBG、GBRG、BGGR
- BLC、DPC、LSC、WB、Demosaic、CCM、Tone、NR、Sharpen、颜色调整
- ROI/halo 局部处理
- 模块输入输出滑动对比
- DPC Mask、LSC Gain Map、Sharpen Edge Mask
- Histogram、Waveform、Vectorscope 和 Bayer/RGB 统计
- JSON 配置及 PNG/TIFF 输出

## Auto Analysis

点击顶部 `Calibration`，在左侧选择自动分析模块。支持：

- Auto BLC：当前暗区 ROI、Optical Black ROI 或外部暗场，分别测量 R/Gr/Gb/B
- DPC：单帧候选检测，以及暗场/平场多帧固定坏点标定
- LSC：平场自动生成四通道 Mesh
- AWB：Robust Neutral、ROI Neutral、Gray World、Shades of Gray、White Patch
- AE：Mean、Median、Percentile、Highlight Protected
- CCM：使用 ColorChecker 色块求解矩阵与 Offset
- Noise Profile：均值—方差模型、Shot Noise、Read Noise 与 NR 参数建议
- Auto Tone：Natural、Preserve Highlights、Lift Shadows、High Contrast、Low-light
- Auto Sharpen：综合边缘、平坦区域噪声和光晕风险推荐参数

所有分析统一使用：

```text
Analyze → Measurements / Confidence / Warnings
        → Preview → Apply
                  ↘ Revert
```

`Analyze` 只测量并给出建议，不修改流水线。`Preview` 是临时事务；
切换模块、加载新图/配置、关闭工作区或点击 `Revert` 都会恢复完整模块参数
和模块状态。参数改变后建议进入 `Stale`，必须重新 Analyze。旧的后台分析
结果不能覆盖新的任务。

分析结果支持导出 JSON；大型 Mask、曲线和热力图写入同名 `_artifacts.npz`，不会直接嵌入 JSON。

### Auto BLC

Auto BLC 必须使用 BLC 之前的 Bayer DN 数据，支持 Mean、Median 和 Trimmed Mean。输出：

- 四通道 Mean/Median/Trimmed Mean/σ/P1/P50/P99
- 建议 R/Gr/Gb/B Black Level
- 负值裁剪与零值比例预测
- 行、列黑电平变化
- 热像素候选和分析 ROI Artifact
- 暗场过亮、漏光、样本不足和通道差异警告

### DPC Calibration

单帧模式提供快速阈值建议。多帧模式统计异常像素的时间持续性，区分固定 Hot/Dead Pixel 和随机噪声。坏点表支持 JSON、CSV、NPZ，并可在 DPC 的 `Dynamic`、`Static Map`、`Hybrid` 模式中使用。

配置保存时，静态坏点 Mask 自动写入相对路径的 NPZ 文件；JSON 只保存引用和摘要。

### Noise Profile

在一个或多个平坦 ROI 中统计均值、方差、MAD、梯度和裁剪比例，拟合：

```text
variance = shot_noise × signal + read_noise
```

纹理、过曝、严重欠曝和尺寸不足的 ROI 会被排除。结果用于推荐 NR Algorithm、Spatial/Chroma Strength、Edge Protection 和 Radius。

### Auto Tone / Auto Sharpen

Auto Tone 在 CCM 后、Tone 前的线性 RGB 上测量亮度百分位和动态范围，并限制预测高光裁剪。建议曲线经过有限值和单调性检查。

Auto Sharpen 在 NR 后、Sharpen 前分析边缘强度、平坦区域噪声、过冲、欠冲和光晕风险；噪声较高时会自动提高 Threshold 并限制 Strength。

## Calibration Workspace

工作区不再使用多个功能标签页，而采用统一三列结构：

1. 左侧选择 BLC、DPC、LSC、AWB、AE、CCM、Noise Profile、Tone、Sharpen
2. 中间管理数据源、文件/ROI、Basic/Advanced 选项并执行 Analyze
3. 右侧检查 Confidence、参数差异、Measurements、Warnings 和 Artifact
4. 底部固定执行 Preview、Apply、Revert、分析与 Artifact 导出

Preview 期间固定显示未应用提示；切换模块会自动 Revert。Apply 后结果写入
Calibration History。

### LSC Mesh

Lens Shading Correction 支持：

- `Radial Model`
- `Mesh Model`

Mesh Model 支持 R、Gr、Gb、B 四个独立增益网格，使用全图坐标进行双线性插值。ROI 处理会复用全图坐标，因此与全图处理后裁剪保持一致。

支持的文件格式：

- JSON
- CSV
- NPY
- NPZ

校准工作区可以：

1. 使用当前 BLC 输出作为平场输入
2. 设置 Mesh 行列数
3. 使用 Median 或 Trimmed Mean 采样
4. 生成四通道 Mesh
5. 打开文本/热力图编辑器
6. Preview
7. Apply 或 Revert

平场图应避免过曝、黑电平未扣除和明显纹理。

### AWB

支持：

- ROI Neutral
- Gray World
- Shades of Gray
- White Patch

AWB 在 LSC 后、White Balance 前的 Bayer 数据上计算，分别处理 R、Gr、Gb、B。输出：

- 四通道增益
- 有效样本数量
- Neutral Pixel Mask
- Neutral Fraction
- 增益限制状态
- 置信度

Calculate 不修改流水线；Preview 临时写入；Apply 确认；Revert 恢复。

### AE

支持：

- Mean Luma
- Median Luma
- Percentile
- Highlight Protected

本版本只计算离线曝光增益建议，不控制相机快门或模拟增益。结果包含：

- 当前测量亮度
- 目标亮度
- 建议增益
- 原始裁剪比例
- 预测裁剪比例
- 高光保护是否限制增益

Apply 会写入 White Balance 模块的 `exposure_gain`。

### ColorChecker / CCM

色卡校准固定使用：

```text
BLC → DPC → LSC → WB → Demosaic → 线性 RGB 采样
```

禁止使用 Gamma/Tone 后的显示 RGB 求解 CCM。

操作方式：

1. 在主界面用 ROI 粗略框住色卡
2. Calibration → ColorChecker → `Use current ROI`
3. 点击 `Edit corners`
4. 拖动 TL/TR/BR/BL 四个角点
5. 选择旋转、翻转、Offset 和 Ridge
6. Calculate CCM
7. 检查条件数与 ΔE
8. Preview、Apply 或 Revert

参考数据来自 `colour-science`，并与工作区 Illuminant 选择联动：

- ColorChecker N Ohta
- D65、D50 或 A
- CIE 1931 2° Observer
- 目标空间为线性 sRGB

求解支持：

- 3×3
- 3×3 + Offset
- Ridge Regularization
- 色块权重
- 白点约束

结果包括：

- CCM 与 Offset
- 矩阵条件数
- CIEDE2000 校准前后 Mean/Median/Max/P90
- CIE76 校准前后统计
- 每个色块 ΔE
- 最差五个色块

## Vectorscope

分析 Notebook 增加：

- YCbCr Cb/Cr
- CIE 1976 u′v′

包含中心点、肤色参考线和 R/G/B/C/M/Y 方向。支持全图或当前 ROI，大图会自动采样，切换分析视图不会重新运行 ISP。

## 校准报告

Calibration Workspace 支持导出：

- JSON
- CSV
- Markdown

报告包含 RAW 元数据、LSC Mesh、AWB、AE、CCM、条件数、ΔE 和用户会话信息。

## 配置 V4

```json
{
  "schema_version": 4,
  "tool_version": "0.4.5",
  "raw": {},
  "pipeline": [],
  "calibration": {
    "lsc_mesh": null,
    "awb": null,
    "ae": null,
    "ccm": null,
    "auto_recommendations": {},
    "calibration_history": [],
    "noise_profile": null,
    "external_assets": {}
  },
  "ui_state": {}
}
```

- V1/V2/V3 自动迁移到 V4
- LSC Mesh 可内嵌
- 配置可引用相对路径的外部 Mesh
- 静态 DPC Map 自动保存为相对路径 NPZ
- 外部 Mesh/坏点表丢失时产生警告，但其他配置仍会加载
- 自动建议保存测量摘要、置信度、警告、是否应用和 Artifact 元数据

## 测试

```powershell
python -m unittest discover -s tests -v
```

当前 72 项测试覆盖：

- V0.1/V0.2 全部能力
- Mesh 插值、四通道映射、ROI 等价和文件往返
- 平场均匀性改善
- AWB 四通道增益、限制和置信度
- AE 百分位、高光保护和预测裁剪
- ColorChecker 网格和线性 RGB 采样
- 已知 CCM/Offset 恢复和 Ridge
- CIE76/CIEDE2000
- Vectorscope
- 旧版 V1/V2/V3 配置迁移回归
- CalibrationSession 和报告导出
- Auto BLC 四通道稳健估计和异常暗场警告
- DPC 固定坏点/随机噪声区分及坏点表往返
- Shot/Read Noise 拟合与 NR 参数范围
- Tone 曲线单调性和高光保护
- 噪声感知 Auto Sharpen
- Analyze/Preview/Apply/Revert 和过期任务保护
- V1/V2/V3→V4 迁移及外部 DPC NPZ
- Calibration UI 状态机合法/非法转换和 Stale 检测
- FileList 元数据校验、ROI 接受/拒绝状态和 Artifact 类型转换
- V0.4.1/V0.4.2/V0.4.3/V0.4.4/V0.4.5 UI 状态持久化
- 隐藏 Tk 窗口下的应用、工作区、Preview、切换自动 Revert 和关闭冒烟流程

## 快捷键

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl+O` | 打开 RAW / 图像 |
| `Ctrl+S` | 保存配置 |
| `Ctrl+E` | 导出当前结果 |
| `Ctrl+Shift+C` | 打开 Calibration |
| `A` | Analyze 当前自动模块 |
| `P` | Preview 当前建议 |
| `Enter` | Apply 当前 Preview |
| `Escape` | Revert Preview 或取消正在运行的分析 |
| `F` | Fit |
| `1` | 1:1 |
| `R` | 开关 ROI 模式 |
| `Space` | 按住临时查看 Before |

输入框获得焦点时，单字母快捷键不会触发。

## 目录

```text
isp_tool/
├─ auto_calibration/
│  ├─ base.py
│  ├─ adapters.py
│  ├─ blc_analyzer.py
│  ├─ dpc_calibrator.py
│  ├─ noise_profiler.py
│  ├─ tone_analyzer.py
│  ├─ sharpen_analyzer.py
│  └─ persistence.py
├─ calibration/
│  ├─ ae.py
│  ├─ awb.py
│  ├─ ccm_solver.py
│  ├─ colorchecker.py
│  ├─ delta_e.py
│  ├─ flat_field.py
│  ├─ lsc_mesh.py
│  └─ report.py
├─ analysis/
│  ├─ histogram.py
│  ├─ statistics.py
│  ├─ vectorscope.py
│  └─ waveform.py
├─ modules/
├─ ui/
│  ├─ app.py
│  ├─ auto_calibration_panel.py
│  ├─ calibration_state.py
│  ├─ calibration_panel.py
│  ├─ colorchecker_editor.py
│  ├─ dpi.py
│  ├─ performance_metrics.py
│  ├─ render_cache.py
│  ├─ recommendation_view.py
│  ├─ scrolling.py
│  ├─ theme.py
│  ├─ widgets/
│  │  ├─ action_menu.py
│  │  ├─ artifact_gallery.py
│  │  ├─ busy_overlay.py
│  │  ├─ collapsible_section.py
│  │  ├─ file_list.py
│  │  ├─ inline_message.py
│  │  ├─ parameter_diff.py
│  │  ├─ roi_list.py
│  │  ├─ status_badge.py
│  │  └─ toast.py
│  └─ lsc_mesh_editor.py
├─ config.py
├─ models.py
└─ pipeline.py
```

## 当前边界

- 仍是离线视觉仿真，不保证硬件 bit-exact。
- AWB/AE 是辅助建议，不包含真实相机控制。
- Auto BLC 需要可信暗场或 Optical Black ROI；普通场景暗部只能作为低置信度参考。
- DPC 多帧标定当前处理同尺寸预览/标定帧，不负责跨分辨率坏点坐标变换。
- Noise Profile 是基础线性 Shot/Read Noise 模型，不替代实验室多曝光标定。
- Auto Tone/Sharpen 是可解释的保守建议，不是任意场景“一键美化”。
- ColorChecker 需要用户提供四角，不做任意场景自动检测。
- 当前目标工作空间固定为线性 sRGB。
- 未实现 3D LUT、多帧 HDR、批处理、插件系统、PySide6/OpenGL 和 GPU。

## V0.5 建议

优先增加项目管理、批量 RAW 对比、3D LUT、模块排序、可插拔算法和校准数据集管理；PySide6/OpenGL/GPU 建议放到后续独立版本。
