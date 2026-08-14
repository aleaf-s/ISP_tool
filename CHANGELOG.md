# Changelog

## 0.4.23

- Histogram 从主界面底部抽屉迁移为单例非模态窗口，关闭后可从工具栏或预览菜单再次打开。
- 删除 Histogram 数据源与显示模式选择，统一跟随当前选中模块的实际输出。
- 按数据域精简通道：RAW 为 R/Gr/Gb/B，RGB 为 R/G/B，YUV 为原生 Y/U/V，并确保至少启用一个通道。
- 支持参数、模块、图像和 ROI 改变后的后台延迟刷新、过期结果丢弃与小型结果缓存，不因缩放和平移重复计算。
- 保存 Histogram 窗口几何信息、Log/Linear 和 ROI 状态；主窗口底部仅保留 Waveform、Vectorscope 与 Statistics 高级分析。

## 0.4.22

- 主预览工具栏新增可发现的 Histogram 按钮和底部分析抽屉，Waveform/Vectorscope/Statistics 收纳到“更多分析”。
- Histogram 数据源支持当前显示、模块输入/输出和最终输出，并支持当前 ROI、Log/Linear 纵轴和状态持久化。
- RAW 直接按实际位深 DN 统计 R/Gr/Gb/B；RGB 支持 Overlay/Luma/单通道；YUV 支持原生 Y/U/V 和转换后 RGB。
- YUV Limited Range 增加合法范围标记；增加暗部、高光、Min/Max、越界占比及悬停 bin 读数。
- 直方图延续使用延迟后台分析、过期请求取消和按阶段/ROI/模式缓存，隐藏时不运行。

## 0.4.21

- YUV Display Preview 的 Pixel Format 下拉框改为全部支持格式，并增加 Bit Depth 和 Endianness 快速选项。
- P010/YUV420P10LE 自动匹配 10-bit little-endian，YUYV/UYVY 自动匹配 8-bit；切换时重新校验文件并更新帧数。
- 底部像素栏取消归一化 RGB 数值，只显示源码值、裁剪前绝对 RGB 与显示 RGB 绝对码值。
- 移除主预览工具栏的 Gray/1:1 按钮以及视图菜单的 1:1 入口。

## 0.4.20

- YUV 导入支持从文件名提取分辨率、`8/10/12/16-bit`、格式、Color Matrix、Range、大小端和 Linear Layout。
- 支持 `420sp` 与 `420p` 通用命名；分别暂按 NV12 和 I420，并在元数据窗口提示 UV/VU 或 U/V 平面顺序存在歧义。
- 明确的 NV12/NV21/I420/YV12/P010 标记优先，高位深 420SP 会额外提示 P010/对齐方式需要人工确认。

## 0.4.19

- 主工具栏新增显性 `RAW ISP` / `YUV 预览` 工作区切换，当前工作区使用高亮状态。
- 新增“从工作区移除当前图像”，不会删除磁盘源文件；图像选择框改为更宽的动态宽度。
- 移除专家模式入口，旧配置中的专家模式状态不再恢复。
- 精简工具栏与视图菜单：计算后端、性能详情和缓存管理集中到“高级工具”子菜单。

## 0.4.18

- 新增独立 `isp_tool/yuv/` 算法层，覆盖格式定义、元数据、文件校验、逐帧读取、色度上采样、YUV→RGB 和原生直方图。
- 支持 I420、YV12、NV12、NV21、YUYV、UYVY、YUV444P、YUV422P、Gray、P010 与 YUV420P10LE。
- 新增 YUV 元数据对话框、文件名推测、1080p/4K 预设、每帧字节数和完整帧校验。
- 新增 BT.601/709/2020、Full/Limited Range、8/10/12/16-bit 归一化以及 Center/Left/Top-left 色度定位。
- YUV 使用独立四阶段预览路径；RAW BLC/LSC/WB/Demosaic/CCM 和自动校正不会运行。
- 新增逐帧 memmap 读取、前后帧/方向键导航、可取消后台转换和最近两项独立 YUV 缓存。
- 新增 Y/U/V 单通道、原生 YUV + RGB Histogram、YUV/RGB 悬停码值、越界诊断和 YUV 元数据/平面导出。
- 保留现有高倍缩放视口渲染；缩放和平移不会重新执行 YUV 转换。
- 自动化测试增加到 184 项并全部通过。

## 0.4.17

- 修复 RAW Input 与 BLC 输出使用不同显示归一化规则导致的亮度误判。
- RAW Input 预览不再提前扣除元数据 Black Level，仅按 White Level 映射传感器 DN。
- 当 R/Gr/Gb/B Black 和 Global Offset 均为 0 时，BLC 输出预览与未校正 RAW 预览逐像素一致。
- RAW 悬停读数同时显示未校正 Normalized 值和按元数据估算的 BLC 参考值。

## 0.4.16

- Demosaic 页面移除没有实际意义的“手动 / 自动”切换栏，直接显示算法参数。
- Demosaic 算法列表收敛为 Nearest Neighbor、Bilinear、Adaptive Interpolation 和 Constant Color Difference 四项。
- 新增逐 CFA 晶格的最邻近插值、方向梯度自适应插值，以及基于 R-G / B-G 局部恒定假设的色差插值。
- 自动 CCM 新增结构先验：主对角线严格大于 1，非对角元素限制为小正值或负值，并对正非对角元素施加额外惩罚。
- CCM 安全检查和结果摘要新增主对角元素、负非对角元素数量等可观测信息。

## 0.4.15

- 移除自动页重复的“快速自动矫正 / Module”表头及模块下拉选择，自动页只显示当前流水线模块的校正设置。
- RAW Input 悬停新增原始 DN、Normalized 数值及当前 Bit Depth 范围。
- 线性 Bayer 阶段新增当前位深等效绝对码值。
- RGB 阶段新增三通道当前位深等效绝对码值，并保留高精度 Linear RGB。
- 码值转换不隐藏负值或溢出，便于定位模块输出越界。
- 新增自动页重复导航清理和 Bayer/RGB 像素双表示测试。
- 自动化测试由 159 项增加到 162 项。

## 0.4.14

- 高倍缩放改为视口裁剪渲染，不再为整张图创建 2×～16×巨型 PhotoImage。
- 可见源图范围按画布、平移原点和 Zoom 动态计算，并保留 2 像素边缘缓冲。
- Raster Cache 加入视口源坐标；同一像素范围内平移可复用现有位图。
- ROI、Compare、色卡 Overlay、鼠标坐标及完整图像变换继续使用全局坐标。
- 新增 8×/16×视口范围、内存规模及真实 Tk PhotoImage 尺寸测试。
- 自动化测试由 155 项增加到 159 项。

## 0.4.13

- Demosaic 前的主预览改为严格逐像素 Bayer CFA 马赛克，不再执行 Gaussian 扩散或通道填充。
- RAW 缩小显示使用最近邻采样，避免显示缩放混合相邻 R/Gr/Gb/B 像素。
- RAW Input 按四个 CFA 通道各自 Black/White Level 归一化；BLC 后明确使用线性范围。
- 修复 WB/LSC 后大于 2 的合法线性值被误判成原始 DN 并重复归一化的问题。
- Bayer 阶段鼠标读值显示实际 CFA 通道、DN/Linear 数值和 Bayer Pattern。
- Bayer Histogram、Waveform 和 Vectorscope 改用无空间插值的原生 2×2 CFA Cell 数据。
- WB 手动与自动页面增加 Bayer 绿色采样密度说明，避免依据马赛克整体颜色错误放大 R/B。
- 新增严格 CFA 显示、强增益归一化和 WB→Demosaic 通道一致性测试。
- 自动化测试由 150 项增加到 155 项。

## 0.4.12

- 手动调整与自动校正改为主检查器内的双模式切换，不再创建新的校正窗口。
- 自动模式、手动参数、当前图像、ROI、色卡检测结果及最近参数在模式切换时保持不变。
- 增加独立的线性 RGB → sRGB 显示编码及 ±3 EV 预览亮度控制；显示变换不进入流水线、像素读值、色卡采样或导出。
- ColorChecker 改用中心有效区、Median/MAD 异常剔除，并标记过曝、欠曝、内部不均匀和异常像素色块。
- CCM 改为中性/肤色加权、单位矩阵正则、行和约束、有界最小二乘和感知误差二次优化。
- CCM 内嵌结果区新增优化前/后矩阵、原图/校正图、24 色块 RGB/ΔE、平均与最大 ΔE、行和、条件数、负值和溢出率。
- 平均 ΔE 无明显改善、最大 ΔE 恶化、中性色偏、矩阵不稳定或输出越界时禁止自动应用。
- UI 状态新增手动/自动模式与预览 EV 持久化。
- 新增 SciPy 显式运行依赖及 V0.4.12 显示隔离、稳健采样、约束 CCM 和安全拒绝测试。
- 自动化测试由 145 项增加到 150 项。

## 0.4.11

- 产品范围收敛为 BLC、LSC、WB、Demosaic、CCM 五模块快速矫正流水线。
- 从活动流水线、模块列表和自动分析导航移除 DPC、Tone Mapping、Noise Reduction、Sharpen 与 Color Adjustment。
- 自动矫正窗口改为单栏布局，只保留模块、方法、区域/校准图像、运行状态和“矫正并应用”。
- 移除 Review & Apply、Measurements、Warnings、Artifacts、Advanced Options 及多阶段 Preview/Apply 操作界面。
- 移除 Calibration Workspace 会话表头、报告/建议导出、ISP 参数配置导入导出、CCM 参数导入导出和跨图像校准刷入口。
- BLC、LSC、AWB、AE、CCM 统一为显式的一键分析并应用；AWB 保留全图与当前 ROI 两种来源。
- 自动矫正阶段索引改为按模块 ID 动态解析，流水线增删模块后不再依赖硬编码下标。
- Compare 分割线命中优先于 ROI 框选；拖动分割线不会再创建或移动 ROI。
- 旧算法实现仍保留为非活动兼容代码，不进入 V0.4.11 的产品流水线。
- 1500×1000 Auto 冷流水线本机参考中位数约 34.13 ms，缓存 CCM 编辑约 4.68 ms。
- 新增精简模块集合、单栏自动矫正、AWB 一键应用和 Compare/ROI 手势冲突测试。
- 自动化测试由 140 项增加到 145 项。

## 0.4.10

- 使用本机 Visual Studio C++、Python 3.9 与 pybind11 实际编译并加载 Native ABI 1 扩展。
- Native C++ 新增 DPC 3×3/5×5 内核，覆盖 Dynamic、Static Map、Hybrid、亮点和暗点检测。
- Native Bilinear Demosaic 与 DPC 均释放 GIL，并按图像规模使用 std::thread 并行处理。
- DPC 3×3 使用固定 median-of-nine 排序网络，避免逐像素通用 nth_element。
- 新增 qualified_kernels 性能资格契约；Auto 仅启用通过当前发布机性能门槛的原生内核。
- 当前 Native Demosaic 参考加速约 1.68×；Native DPC 仅约 0.87×，Auto 因此自动回退到更快的 OpenCV DPC。
- 显式 Native C++ 模式会强制启用实验内核，Auto 与强制模式使用不同缓存键。
- Performance Details 新增 kernel_backends，展示 DPC/Demosaic 实际执行实现。
- 新增 setuptools 构建入口，自动定位未加入 PATH 的 MSVC 和 Windows SDK rc/mt 工具，不再强制依赖 CMake。
- 新增一键构建批处理、PowerShell 构建脚本及 Native Backend Doctor。
- Doctor 提供工具链诊断、扩展 ABI/能力查看、Native/OpenCV 输出一致性和 1500×1000 性能对比。
- 1500×1000 默认冷流水线由固定 OpenCV 约 84.53 ms 降至 Auto 混合后端约 76.48 ms，参考提升约 9.5%。
- 新增性能资格、强制实验内核、混合执行诊断和已编译扩展契约测试。
- 自动化测试由 134 项增加到 140 项。

## 0.4.9

- 新增 UI 无关的 ProcessingBackend 抽象，首批将 DPC 与 Demosaic 热点迁移到统一执行接口。
- 新增 Auto、OpenCV/NumPy、Native C++ 三种后端偏好；Native 缺失、ABI 不匹配或内核不支持时可靠回退。
- Native C++ 未安装时菜单选项明确禁用，并提供后端状态对话框。
- 流水线任务会为整次请求捕获同一后端，避免切换过程中混用不同实现。
- Pipeline Cache 与工作集多图缓存增加 backend cache key，切换后端时不复用旧中间结果。
- 最终效果与模块影响页继承主应用后端，并校验基线结果的后端标识。
- Performance Details 新增后端偏好、实际执行后端、Native 可用性及回退原因。
- JSON UI State 新增 processing_backend，旧配置默认使用 Auto。
- 新增 CMake/pybind11 ABI 1 原生扩展骨架与首个精确 Bilinear Demosaic C++ 内核。
- 基准工具新增 `--backend auto|opencv|native`，请求 Native 但不可用时输出真实回退原因。
- 新增后端选择、ABI、原生调用分发、逐内核回退和缓存隔离测试。
- 自动化测试由 126 项增加到 134 项。

## 0.4.8

- 新增每图运行时预览缓存，保存预览输入、流水线缓存、全部 StageResult 和实际处理快照。
- 多图切回时校验输入修订、图像对象、Pipeline 快照和预览质量；命中后直接恢复，不提交新流水线任务。
- 图像激活时立即取消待提交请求、通知运行任务停止并推进任务代际，修复缓存命中时旧图迟到结果仍可能覆盖界面的竞态。
- 输入修订号改为随工作图像保存，图像切换本身不再伪造输入内容变化。
- 缓存采用最多 3 张、总计 384 MiB 的双重 LRU 限制，超限时优先淘汰最久未使用的非当前图像。
- ROI 局部结果不会污染完整图像切换缓存；运行时 Pipeline Cache 使用独立浅层容器，避免后续任务覆盖缓存字典。
- 参数刷、元数据、参数快照、预览质量或图像内容变化会自动使对应缓存失效。
- Performance Details 新增工作集缓存占用及 Hit/Miss/Invalidation/Eviction/Manual Clear 计数。
- “预览”和“视图”菜单新增手动清除多图预览缓存入口。
- 新增容量限制、内存预算、快照失效、无任务恢复和手动清理测试。
- 自动化测试由 120 项增加到 126 项。

## 0.4.7

- DPC 动态检测迁移到 OpenCV uint8 Mask、`countNonZero` 与 `copyTo`，参考模块耗时由约 28 ms 降至约 15 ms。
- DPC Static Map 无有效坏点时增加零拷贝快速旁路，并保留可查看的空 Defect Mask。
- 新增快速 900 px、平衡 1200 px、精细 1500 px 三档预览质量，收纳于“预览”下拉菜单。
- 预览质量变化时自动缩放现有 ROI 和网格边界；多图工作集记录各自预览尺寸并在激活时换算 ROI。
- Calibration 辅助 Bayer 帧跟随当前预览质量，避免 900/1200 px 模式下被误判为尺寸不匹配。
- Demosaic 新增可选 `OpenCV Fast Bilinear`，使用自适应 uint16 缩放保留高光动态范围；精确 Bilinear 仍为默认值。
- 中性最终颜色调整在输入已经位于 0～1 时直接复用，减少重复 Clip 和大数组分配。
- 基准工具增加 `--fast-demosaic` 对比选项。
- 1500×1000 精确默认冷流水线参考中位数进一步降至约 86 ms，缓存 Tone 调参约 26 ms。
- 自动化测试由 112 项增加到 120 项。

## 0.4.6

- 完成首轮基于基准的 CPU 热点优化，1500×1000 默认冷流水线参考基准由约 400 ms 降至约 120 ms。
- Bilinear Demosaic 去除恒定归一化分母的重复 Mask 构造与卷积，并增加旧公式全 Bayer Pattern/边界等价测试。
- Tone Mapping 改用 OpenCV float32 向量化幂运算；CCM 改用等价有效矩阵与 `cv2.transform`。
- LSC、CCM、NR、Sharpen 和基础颜色调整增加中性参数快速路径，减少无效处理和大数组复制。
- 预览流水线增加模块边界协作取消；新请求启动后，旧请求不再无条件运行完整条处理链。
- Fit Raster 改为 float32 `INTER_AREA` 缩放后量化，降低图像刷新占用 UI 主线程的时间。
- Performance Details 增加 Pipeline Modules、Overhead、Preview Latency 与逐模块耗时排行。
- 流水线 `last_metrics` 增加 wall/overhead/dirty index/module timings，内存估算按共享底层数组去重。
- 新增 `tools/benchmark_pipeline.py` 固定尺寸回归基准。
- 自动化测试由 102 项增加到 112 项。

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
