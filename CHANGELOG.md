# Changelog

## 0.4.5

- ROI 分块统一为“当前选区内自定义网格”，支持行、列、内缩比例和最多 96 个小框。
- Bayer 分块采用向内偶数对齐，保证所有采样框严格位于选定外接区域。
- 保存并绘制分块外接区域、行列数及内缩设置，切换工作图像和保存配置后可恢复。
- 新增“最终效果与模块影响”页面，逐模块执行临时旁路并重新计算最终输出。
- 最终效果页面提供 Final/Bypass、差异热力图、Mean/P95/Max 差异和变化像素比例。
- 最终影响分析使用独立工作线程、任务代际保护和窗口级模块结果缓存。
- 顶部 Scope/View 合并为 Preview 菜单；固定 ROI 网格入口合并；删除未显示的自动分析 Open 控件。
- Calibration 不再构建不可见的旧 LSC/AWB/AE/CCM 标签页，只初始化统一工作流所需共享状态。
- 新增 `final_preview.py` 和自定义 `ROIGridDialog`。
- 自动化测试由 96 项增加到 102 项。

## 0.4.4

- 新增多图工作集：一次选择多张图像、后台读取、顶部下拉切换，并为每张图保存独立 Pipeline、Calibration、ROI 和手工预览状态。
- 新增校准刷：当前模块可应用到所选或全部其它图像，另提供 BLC/DPC/LSC 与 WB/CCM 分组刷入。
- 校准刷完整复制模块 parameters、enabled 和 state；LSC Mesh、DPC Map 可随模块迁移，并提供 Bayer/尺寸兼容性提示。
- 所有手工参数统一为实时 Preview + 显式 Apply/Revert；CCM 矩阵编辑、粘贴、导入和快捷操作均进入相同提交状态。
- ROI 从单框扩展为最多 24 框；支持 4×6 色块生成、八控制点缩放、拖动、方向键和坐标管理器微调。
- CCM 自动分析优先使用现有 24 个 ROI 作为 ColorChecker 色块。
- AWB 新增 Robust Neutral 默认方法、纹理/曝光筛选、空间覆盖率、色度离散度、Gr/Gb 一致性和更保守的置信度。
- Gray Picker 复用 AWB ROI Neutral 算法，结果作为待应用参数预览。
- 新增 `workspace.py`、`roi_tools.py` 与 `ROIEditor`，算法/工作集状态继续与 UI 解耦。
- 自动化测试由 87 项增加到 96 项。

## 0.4.3

### 简洁主工作区

- 默认界面收敛为 Pipeline、中央图像和当前模块参数三块。
- 顶部工具栏仅保留 Open、Save、Export、Calibration、Scope 和 View。
- Stage 任意输出选择、模块诊断和性能状态默认隐藏，通过专家模式显示。
- Module State、Automatic Analysis、Diagnostics 三张卡片合并为紧凑模块标题区。
- 每个模块默认仅显示常用参数，完整参数位于可展开的 Advanced 区域。
- CCM 的六个管理按钮收拢为 Identity 加单一 CCM 菜单。
- Pipeline 简洁模式只显示启用状态、模块名、建议标记和耗时。

### 按需 Scope 与步骤式 Calibration

- Scope 默认关闭，不再永久占用主预览高度。
- Scope 打开后一次只呈现一个分析页签，Waveform/Vectorscope 设置移动到各自页签。
- Calibration 从三列导航改为模块下拉框与双栏工作区。
- Calibration 明确显示 `Data → Analyze → Review → Apply` 当前步骤。
- Preview、Apply、Revert 按状态渐进显示，不再同时堆放禁用按钮。

### 兼容性与测试

- 专家模式、模块 Advanced 展开状态继续保存在 V4 `ui_state`。
- 保留 V0.4.2 快预览、延迟分析、缓存、滚轮、DPI 和任务代际保护。
- ISP 算法输出及 V1/V2/V3/V4 配置兼容保持不变。
- 自动化测试由 82 项增加到 87 项。

## 0.4.2

### 快预览与延迟分析

- 将主画布快速显示与分析刷新分离，Pipeline 完成后先显示结果，再延迟执行分析。
- 新增独立 `isp-analysis` 单线程执行器；后台线程只计算 NumPy 数据，Tk 更新仍在主线程完成。
- Histogram、Waveform、Vectorscope、Statistics 改为四个平级页签，并且只计算当前页签。
- 分析面板折叠时不提交任务；Stage、ROI 或分析设置变化会取消/丢弃过期结果。
- 新增阶段 RGB 与分析结果两级有界 LRU 缓存，结果修订号、Stage、ROI 和分析设置均参与缓存键。
- Canvas resize 使用 50 ms 防抖，分析使用 220 ms 防抖，Compare、ROI 与鼠标反馈约 30 Hz 更新。

### 界面密度、字体与滚轮

- 主工具栏收敛为 Open、Save、Export、Calibration、View 和 Stage；ROI、通道、曝光提示与 Artifact 进入菜单。
- Calibration 数据操作收拢为 Load、DPC Map、Manage；文件和 ROI 列表增加右键菜单、Delete/Enter 快捷操作。
- 自动建议卡片按状态渐进显示 Analyze、Preview、Apply/Revert、Cancel 或 Analyze Again。
- 统一使用 Tk named fonts，默认正文 10 pt，并在创建 Tk Root 前启用 Windows Per-Monitor DPI awareness。
- 增加 Follow System、90%、100%、110%、125%、150% UI Scale 并写入 V4 `ui_state`。
- 新增鼠标所在控件滚轮路由，覆盖主参数区、Pipeline、Calibration 选项、文件/ROI 列表和诊断文本，图像画布保留缩放。

### 可观测性与兼容性

- 状态栏新增 Pipeline、View、Analysis 和 Cache 摘要。
- View → Performance Details 显示 latest、P50、P95、缓存命中、预览尺寸和结果内存估算。
- 保持 V0.4.1 ISP 算法输出、自动校准安全状态机和 V1/V2/V3/V4 JSON 配置兼容。
- 自动化测试由 72 项增加到 82 项，覆盖缓存边界、延迟分析选择、滚轮归一化、DPI 安全调用、NamedFont 缩放和快预览契约。

## 0.4.1

### 统一界面与主调试流程

- 新增集中式深色 Theme、状态颜色、字体/间距规范和 Windows 高 DPI 适配。
- 主 Pipeline 增加 Sensor/Color/Detail/Output 类别、启用状态、建议标记和模块耗时。
- 预览工具条整合 Fit、1:1、ROI、Gray Picker、Compare 和 Artifact Overlay。
- 预览角落显示 Stage、Domain、Zoom、ROI；Compare 分割线增加拖动手柄。
- 右侧检查器新增 Module State、Automatic Recommendation 和 Diagnostics。
- 底部 Histogram/Waveform/Vectorscope/Statistics 支持整体折叠。

### Calibration 工作区

- 由多标签页改为九模块统一导航和三列式 Data/Strategy/Recommendation 工作流。
- 新增纯 Python Calibration 状态机，覆盖 Running、Suggested、Previewing、Applied、Stale、Failed 和 Cancelled。
- 无建议时禁用 Preview/Apply；活动 Preview 才能 Apply/Revert；参数变化使建议进入 Stale。
- 切换模块、加载新图/配置和关闭工作区会自动 Revert 未应用 Preview。
- Dark/Flat Frame 与 Noise ROI 改为可管理列表，支持校验、选择、删除和批量分析。
- Recommendation 统一显示置信度、参数差异、测量、警告和 Artifact 画廊。

### 可复用组件、持久化与测试

- 新增 CollapsibleSection、StatusBadge、Toast、BusyOverlay、InlineMessage、ParameterDiff、ArtifactGallery、FileList 和 ROIList。
- Artifact 支持缩略图、Fit、1:1、Main、Overlay、Side by Side、Flicker、透明度及单项/批量导出。
- V4 `ui_state` 增加窗口/分栏、分析折叠、Calibration 模块和折叠区、Artifact 模式/透明度、最近方法/目录、Zoom/Fit。
- 增加完整快捷键并避免输入框焦点下误触单字母命令。
- 保持 V1/V2/V3/V4 配置兼容和 V0.4 算法行为；自动化测试从 63 项增加到 72 项。

## 0.4.0

### 统一自动分析

- 新增 `ParameterRecommendation`、`ModuleAnalyzer` 和 `AutoCalibrationController`。
- 所有自动建议统一使用 Analyze → Preview → Apply/Revert。
- Analyze 不修改流水线；Preview 保存模块参数与私有状态快照。
- 新分析会取消旧任务，过期结果不能写回界面或流水线。
- 每次建议包含 Current/Suggested、Measurements、Confidence、Warnings、Artifact 和耗时。
- 新增统一 Auto Analysis 工作区、参数差异表、诊断文本和 Artifact 预览。

### Auto BLC / DPC

- Auto BLC 支持当前暗区、Optical Black ROI 和外部暗场。
- 分通道输出 Mean、Median、Trimmed Mean、P1/P50/P99、行列变化与裁剪预测。
- DPC 增加 Dynamic、Static Map、Hybrid 三种工作模式。
- 单帧 DPC 提供稳健阈值建议；多帧标定通过时间持续性区分固定坏点和随机噪声。
- 坏点表支持 JSON、CSV、NPZ，输出 Hot/Dead/Persistent Mask、Overlay 和 Confidence Map。

### Noise / Tone / Sharpen

- Noise Profile 拟合 `variance = shot_noise × signal + read_noise`。
- 自动排除纹理、过曝和严重欠曝 ROI，并推荐 NR 参数。
- Auto Tone 支持五种目标模式，输出亮度百分位、动态范围、曲线对比和裁剪预测。
- Tone 建议曲线经过有限值和单调性验证。
- Auto Sharpen 根据平坦区域噪声、边缘、过冲/欠冲和光晕风险推荐参数。

### 标定适配、配置与报告

- AWB、AE、LSC、CCM 通过 Adapter 接入统一 Recommendation 模型。
- ColorChecker 参考光源现在与 D65/D50/A 界面选择实际联动。
- LSC Mesh 行列数允许直接输入。
- 配置升级到 schema V4，V1/V2/V3 自动迁移。
- 静态 DPC Map 保存为配置旁的相对路径 NPZ，缺失时安全警告。
- 自动分析 Artifact 使用 NPZ 外置，JSON 保存摘要和 Artifact 元数据。
- CalibrationSession 增加自动建议、Noise Profile、应用历史和外部资源。
- JSON/CSV/Markdown 报告增加自动分析结果。
- 自动化测试从 48 项增加到 63 项。

## 0.3.0

### 自动校准

- 新增独立 Calibration Workspace，包含 LSC、AWB、AE、ColorChecker/CCM 四个工作流。
- 校准流程使用 `Not Calculated → Calculated → Previewed → Applied` 状态。
- Preview 为临时修改，关闭工作区或 Revert 会恢复原参数。
- 校准计算使用独立单线程执行器，过期排队任务会取消或丢弃。

### LSC Mesh

- Lens Shading Correction 支持 Radial Model / Mesh Model。
- 支持 R、Gr、Gb、B 四通道 Mesh 双线性插值。
- ROI Mesh 使用完整预览坐标，与全图裁剪结果一致。
- 支持 JSON、CSV、NPY、NPZ 导入导出。
- 新增 Mesh 文本编辑器和热力图。
- 支持从 BLC 后的平场 Bayer 生成 Mesh。
- 输出校正前后均匀性 CV、四通道照度 Mesh 和 Gain Map。
- Gain Map 使用有界 LRU 缓存。

### AWB / AE

- AWB 支持 ROI Neutral、Gray World、Shades of Gray、White Patch。
- 分别计算 Gr/Gb，排除过曝欠曝样本，输出置信度和 Neutral Pixel Mask。
- AE 支持 Mean、Median、Percentile、Highlight Protected。
- 输出建议曝光增益、预测亮度和预测裁剪比例。

### ColorChecker / CCM

- 支持 ColorChecker 24 色卡四角定义和可拖动角点编辑。
- 支持 6×4 / 4×6 透视网格、旋转和翻转。
- 色块采样固定使用 Demosaic 后、CCM/Gamma 前的线性 RGB。
- 通过 colour-science 从光谱数据生成 D65 线性 sRGB 参考值。
- 支持 3×3、3×3 + Offset、Ridge、权重和白点约束求解。
- 输出矩阵条件数、CIE76/CIEDE2000 校准前后统计和最差色块。

### 分析与工程

- 分析 Notebook 新增 YCbCr 和 CIE 1976 u′v′ Vectorscope。
- 支持肤色线、R/G/B/C/M/Y 目标方向和 ROI 分析。
- 新增 CalibrationSession 及 JSON/CSV/Markdown 校准报告。
- 配置升级为 schema V3，支持 V1/V2 自动迁移和外部 Mesh 安全降级。
- 自动化测试从 26 项增加到 48 项。

## 0.2.0

### 调试体验

- 增加可视化 ROI 框选、移动、清除、局部处理和单独导出。
- Bayer ROI 自动对齐到偶数坐标，并用 24 像素 halo 避免邻域算法边界伪影。
- 前后对比改为同一画布上的可拖动分割线。
- 按住空格临时显示当前模块输入，松开恢复输出。
- 增加模块辅助输出选择及叠加显示。

### 可观测性

- DPC 独立输出亮坏点/暗坏点 Mask，不再覆盖主流水线输出。
- LSC 独立输出 Gain Map，并提供平均、最大、中心和四角增益。
- Sharpen 输出 Edge Mask。
- 增加 Luma、RGB Overlay、RGB Parade Waveform。
- 增加 ROI 感知的 R/G/B 或 R/Gr/Gb/B 均值、中位数、标准差、范围及裁剪统计。
- Gamma / Tone Mapping 增加与真实算法共用函数的实时 Tone Curve。
- CCM 增加单位矩阵、行归一化、复制、粘贴、独立导入导出和奇异矩阵警告。

### 工程能力

- 配置升级到 `schema_version: 2`，支持 V1 自动迁移。
- 未知配置字段安全忽略，非法参数警告并限制到有效范围。
- 增量缓存增加命中/重算数量和真实本轮耗时。
- 模块输出增加 NaN/Infinity、尺寸和模块级错误检查。
- 自动化测试从 14 项增加到 26 项。

### 兼容性

- 保持 Python 3.9、Tkinter 和原有 V0.1 JSON 配置兼容。
- 尚未实现 PySide6、GPU、LSC Mesh、完整 AWB/AE、Vectorscope 和硬件 bit-exact。
