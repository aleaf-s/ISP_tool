# ISP RAW Visual Simulator V0.4.23

桌面端 RAW ISP 快速视觉矫正与参数调试工具。V0.4.23 同时提供相互隔离的
RAW ISP 流程 `BLC → LSC → WB → Demosaic → CCM` 与裸 YUV 预览流程。

## V0.4.23 独立 Histogram 窗口

- `Histogram` 现在打开单例、非模态的独立窗口，不再占用主窗口底部空间；重复点击只会激活已有窗口。
- 移除数据源选择，始终分析左侧当前选中模块的输出；切换图像、模块、参数或 ROI 后自动延迟刷新，不会重新执行 ISP 流水线。
- 通道严格跟随当前数据域：Bayer RAW 仅显示 R/Gr/Gb/B，RGB 仅显示 R/G/B，YUV 仅显示原生 Y/U/V。
- 通道可多选并保证至少保留一个；保留 ROI、Log/Linear、绝对码值横轴、Limited Range 标记、统计摘要与鼠标悬停读数。
- 窗口位置、大小、纵轴模式和 ROI 开关会随配置保存；Waveform、Vectorscope、Statistics 继续位于“更多分析”。

## V0.4.22 Histogram 分析工具

- 主预览工具栏新增明确的 `Histogram` 按钮，在当前窗口底部展开/收起，不打开额外弹窗。
- 数据源支持当前显示、当前模块输入、当前模块输出和最终输出；可切换全图/ROI 与 Log/Linear 纵轴。
- Bayer RAW 直接统计 R/Gr/Gb/B 四个 CFA 平面，横轴按实际位深显示 DN，不再将 Gr/Gb 合并为单一 G。
- RGB 支持 RGB Overlay、Luma 和 R/G/B 单通道；保留裁剪前数据，可统计负值与超范围像素。
- YUV 支持原生 Y/U/V 和转换后 RGB/Luma；Limited Range 使用虚线标出法定 Y/UV 范围。
- 底部显示暗部、高光、Min/Max 及上下越界占比；鼠标悬停曲线时显示码值区间、样本数和占比。
- Waveform、Vectorscope 和 Statistics 收纳到“更多分析”，不再用常驻标签干扰常用 Histogram。
- 面板隐藏时不计算；参数调整使用延迟刷新、后台线程、请求取消与结果缓存。

## V0.4.21 YUV 快速格式切换与绝对码值

- Display Preview 的 Pixel Format 可直接切换所有已实现格式：I420、YV12、NV12、NV21、YUYV、UYVY、YUV444P、YUV422P、GRAY、P010 和 YUV420P10LE。
- 快速参数区增加 Bit Depth 和 Endianness；选择 P010/YUV420P10LE 时自动切换为 10-bit little-endian，YUYV/UYVY 自动切换为 8-bit。
- 格式切换前检查尺寸、stride、位深与文件字节数；不合法组合会提示并恢复上次有效值。
- 底部像素栏不再显示 0～1 归一化 RGB，改为源 YUV/DN、裁剪前绝对 RGB 和最终显示 RGB 码值。
- 移除预览工具栏的 Gray 和 1:1 按钮，并移除视图菜单中的 1:1 可见入口；鼠标滚轮缩放和适合窗口保留。

## V0.4.20 YUV 文件名参数识别

- 导入 YUV 时会从文件名提取分辨率、位深、像素格式、Color Matrix、Range、大小端和 Linear Layout 标记。
- 例如 `YUV_1280x720_8bits_420sp_linear_20260810105249.yuv` 会自动填入 `1280×720`、`8-bit`、`NV12` 和 Linear Layout。
- `420sp` 只能说明色度交错存储，不能判断 UV/VU 顺序；工具暂按 NV12 并显示待确认提示，若颜色异常可直接切换 NV21。
- 明确写有 `NV12`、`NV21`、`I420`、`YV12`、`P010` 等标记时，明确格式优先于通用 `420sp/420p` 推测。

## V0.4.19 简洁双工作区

- 主工具栏显示 `RAW ISP` / `YUV 预览` 双入口，高亮当前工作区；若工作区已有图像则直接切换，否则打开对应类型的导入窗口。
- 图像名下拉框加宽并按文件名动态调整，旁边增加“移除”；移除只影响内存工作区，不删除源文件。
- 取消专家模式及其状态恢复，阶段选择、专家诊断和常驻性能状态不再占用主界面。
- 计算后端、性能详情和清缓存收纳到 `视图 → 高级工具`，常用的预览菜单只保留最终效果、Scopes 和预览质量。

## 启动

双击 `启动ISP仿真工具.bat`，或者：

```powershell
cd "D:\Me\个人脚本\isp_raw_simulator"
python run.py
```

启动后可在支持自动校正的模块中，于右侧检查器顶部直接切换 `手动 / 自动`；
两种模式共用当前图像预览，不再打开额外的校正窗口。Demosaic 直接显示算法
选项，不显示无意义的模式切换。

## V0.4.18 YUV 图像预览与分析

- `.yuv` 作为独立输入域，使用 `YUV Input → Chroma Upsampling → YUV to RGB → Display Preview`，不会执行任何 Bayer RAW ISP 模块
- 支持 I420/YUV420P、YV12、NV12、NV21、YUYV/YUY2、UYVY、YUV444P、YUV422P、Gray、P010 和 YUV420P10LE
- YUV 元数据对话框提供文件名参数推测、常用预设、stride/offset、帧数和文件大小一致性检查
- 支持 BT.601、BT.709、BT.2020，以及 Full/Limited Range；10-bit Limited Range 保持 10-bit 码值计算
- 420/422 色度上采样支持 Bilinear 与 Nearest，并区分 Center、Left 和 Top-left Chroma Siting
- 多帧 YUV 使用 `numpy.memmap` 按帧读取，左右方向键或右侧 Frame 控件切换；最近两种转换结果使用独立缓存
- Display 菜单可查看 Y/U/V 与 R/G/B 单通道；Histogram 同时显示原始 Y/U/V 和转换后 R/G/B
- 悬停显示原始 Y/U/V 绝对码值、归一化值、RGB' 和当前位深等效码值
- 支持当前帧全分辨率 RGB PNG/TIFF、YUV 元数据 JSON，以及原始/上采样 Y/U/V `.npz` 导出

YUV Limited Range 的归一化不会直接除以 255。以 8-bit 为例，Y 使用
16～235，Cb/Cr 使用以 128 为中心的 16～240 范围；更高位深按相应倍数扩展。
YUV 转换结果为显示参考的 RGB'，预览阶段不会再次执行 sRGB Gamma。

示例元数据见 `examples/yuv_nv12_1080p.json`。

当前限制：本版本提供逐帧浏览而不是按 FPS 连续播放；一次多选的裸 YUV 文件
共用导入对话框中确认的元数据；高位深打包格式目前仅包含 P010 和 10-bit planar。

## V0.4.17 BLC 零校正预览一致性

- RAW Input 是未校正传感器信号，显示时只按 White Level 缩放，不再提前扣除 Black Level
- BLC 使用 `(DN - Black) / (White - Black)` 在线性域完成校正和归一化
- 四通道 Black 与 Global Offset 全部为 0 时，BLC 前后预览现在严格一致
- RAW 悬停信息分别显示原始 DN、未校正 Normalized 值和元数据 BLC 参考值

## V0.4.16 Demosaic 与自动 CCM 约束

- Demosaic 仅保留 Nearest Neighbor、Bilinear、Adaptive Interpolation 和 Constant Color Difference
- Demosaic 页面移除“手动 / 自动”切换，选择模块后直接调算法
- 自动 CCM 在有界优化中约束主对角元素大于 1，并限制、惩罚非对角正元素
- CCM 仍同时保留行和接近 1、单位矩阵正则、感知色差与稳定性检查
- 自动结果区显示主对角值与负非对角元素数量，异常结构不会直接应用

## V0.4.15 精简自动页与码值读数

- 自动页移除重复的“快速自动矫正 / Module”标题和模块下拉框；当前自动模块完全跟随左侧 ISP 流水线选择
- Bayer RAW Input 悬停同时显示原始 DN、按通道 Black/White Level 计算的 Normalized 值和当前位深范围
- BLC/LSC/WB 等线性 Bayer 阶段同时显示 Linear 值及当前位深等效绝对码值
- Demosaic/CCM 等 RGB 阶段同时显示三通道 Linear RGB 和当前位深等效绝对码值
- 等效码值不强制裁剪到位深范围，因此负数或超过最大码值时可直接发现下溢、溢出

## V0.4.14 高倍缩放视口渲染

- 1:1 及更高倍率不再创建整张放大位图，只编码和放大当前画布可见的源图区域
- 视口周围保留 2 个源像素缓冲，平移时避免边缘接缝，同时把额外位图尺寸限制在约 `画布尺寸 + 6×Zoom`
- Raster Cache Key 加入源图裁剪范围；同一源像素范围内的小幅平移可复用位图，跨像素后只更新新的可见块
- 图像坐标、ROI、Compare 分割线、色卡框和鼠标读值仍使用完整图像坐标，不受视口裁剪影响
- 以 1500×1000、16×、1000×700 画布为例，旧路径约需生成 3.84 亿显示像素；新路径通常低于 80 万像素

## V0.4.13 真实 Bayer 马赛克预览

- Demosaic 前的主预览严格按 Bayer Pattern 显示，每个传感器像素只写入自己的 R、Gr、Gb 或 B 通道
- 移除旧 Bayer 预览中的 3×3 Gaussian 扩散和 `×4` 显示放大，不再产生类似去马赛克的伪插值
- 缩小 RAW 预览时使用最近邻采样，避免显示缩放把相邻 CFA 通道混合成伪 RGB
- RAW Input 使用四通道独立 Black/White Level 做显示归一化；BLC 后阶段明确视为线性数据
- 修复以 `max > 2` 判断 RAW DN 的错误：WB/LSC 后大于 2 的合法线性值不再被误当成未归一化 RAW
- 鼠标悬停在 Bayer 阶段时显示真实 RAW 通道名称、DN/Linear 数值和 Bayer Pattern
- Histogram、Waveform、Vectorscope 使用原生 2×2 CFA Cell 统计，不调用空间去马赛克，也不把稀疏显示中的零通道计入分析
- WB 页面明确提示：Bayer 中绿色采样点是 R/B 的两倍，RAW 马赛克整体偏绿正常；最终白平衡应以 Demosaic 输出判断

## V0.4.12 内嵌校正与可信 CCM

- 手动调整和自动校正改为右侧检查器内的两个高亮模式，切换时保留图像、ROI、色卡检测结果和最近参数
- 线性 RGB 到屏幕之间补上独立的 sRGB 显示变换，解决移除 Tone 后线性图直接显示偏暗的问题
- 主预览新增 `− / 默认 / +` 显示亮度控制（±0.5 EV，范围 ±3 EV）；只改变屏幕预览，不改变 RAW、流水线结果、像素读值、色卡采样或导出
- 色卡使用色块中心区域和中位数/MAD 异常剔除，记录过曝、欠曝、内部不均匀与异常像素
- 自动 CCM 使用中性色块/肤色色块加权、单位矩阵正则、行和约束和有界最小二乘，并以感知颜色误差二次优化
- CCM 结果区显示优化前后矩阵、原图/校正图、每块输入/目标/校正 RGB、逐块 ΔE、平均/最大 ΔE、行和、条件数、负值和溢出比例
- 平均 ΔE 未明显下降、最大 ΔE 恶化、灰阶偏色、矩阵不稳定或输出越界时，结果保留供检查但不会自动应用
- CCM 应始终使用进入 CCM 模块前的线性 RGB；显示 sRGB 和预览 EV 不参与拟合

## V0.4.11 快速矫正精简版

- 活动流水线精简为 BLC、LSC、WB、Demosaic、CCM
- 移除 DPC、Gamma/Tone Mapping、Noise Reduction、Sharpen 和基础 Contrast/Color Adjustment
- 自动矫正页只保留模块、方法、ROI/校准图像和“矫正并应用”
- 移除 Review & Apply、Measurements、Warnings、Artifacts 和 Advanced Options 界面
- 移除顶部 Calibration Workspace 会话信息、报告导出和参数建议导出
- 移除 ISP 参数配置导入/导出、CCM 参数导入/导出和跨图像“校准刷”
- 图像结果及 ROI 导出仍然保留
- Compare 与 ROI 同时开启时，分割线附近的拖动由 Compare 优先处理，不会误画 ROI
- AWB 支持全图自动中性样本和当前 ROI 灰卡/白卡两种区域
- 自动分析全部改为明确的“矫正并应用”，不再暴露 Analyze/Preview/Apply 多阶段流程
- 本机 1500×1000 Auto 冷流水线参考中位数约 34.13 ms，缓存 CCM 调参约 4.68 ms

旧 DPC、Tone、NR、Sharpen 算法文件和底层测试暂时保留，便于以后按需恢复；
它们不进入 V0.4.11 的活动流水线和界面。

## V0.4.10 原生后端真正落地

- 已使用本机 Visual Studio C++、Python 3.9 和 pybind11 实际编译并加载 `isp_tool._native`
- C++ 扩展 ABI 1 现提供精确 Bilinear Demosaic 与 DPC 3×3/5×5 两个真实内核
- 原生 Demosaic 覆盖四种 Bayer Pattern，原生 DPC 覆盖 Dynamic、Static Map、Hybrid 及亮/暗坏点
- 原生计算释放 Python GIL，并按图像规模使用 C++ 工作线程；输入输出通过 NumPy Buffer 直接交换
- 增加性能资格机制：Auto 只启用在当前发布机上快于参考实现的原生内核
- 当前实测 Native Bilinear Demosaic 约为 OpenCV 精确实现的 1.68×
- 手写 Native DPC 约为 OpenCV 的 0.87×，因此 Auto 会让 DPC 使用更快的 OpenCV，而不是为了“全 C++”牺牲性能
- 显式选择 Native C++ 可强制运行实验性 DPC，用于输出与性能对比
- Performance Details 的 `kernel_backends` 显示 DPC 和 Demosaic 实际使用的内核
- 增加不依赖 CMake 的 setuptools 一键构建，自动定位未加入 PATH 的 Visual Studio 和 Windows SDK 工具
- 增加 Native Backend Doctor，执行环境诊断、ABI/内核检查、输出一致性和固定尺寸性能测试

本机 1500×1000 默认参数参考中位数：

```text
OpenCV / NumPy cold pipeline   84.53 ms
Auto mixed backend            76.48 ms
整体提升                         约 9.5%
```

重新构建可以双击 `构建C++后端.bat`，或者执行：

```powershell
python native\setup_native.py build_ext --inplace --force
python tools\native_backend_doctor.py --verify --benchmark
```

生成的 `.pyd` 与当前 Python 主次版本及 CPU 架构绑定，不提交到 Git；更换 Python 或复制到另一台机器后应重新构建。

## V0.4.9 可选计算后端

- 新增 UI 无关的 `ProcessingBackend` 统一接口，第一批接入 DPC 和 Demosaic 热点
- 默认 `Auto`：检测到 ABI 兼容的 `isp_tool._native` 时启用 Native C++，否则无提示地使用可靠的 OpenCV/NumPy
- `预览 → 计算后端` 可选择 Auto 或固定 OpenCV/NumPy；未安装原生扩展时 Native C++ 选项明确禁用
- 后端切换会使正在运行的旧预览失效，并清理流水线缓存、最终效果缓存和多图结果缓存
- 流水线前缀缓存和多图缓存均写入后端缓存标识，不会把另一个实现生成的中间结果误认为命中
- DPC、Demosaic 诊断记录实际执行内核；原生后端不支持的算法逐项回退到 OpenCV，而非使整个应用失效
- Performance Details 显示后端偏好、实际后端、Native 可用性和回退原因
- JSON `ui_state.processing_backend` 保存后端偏好，旧配置默认迁移为 Auto
- `native/` 提供 CMake/pybind11 ABI 1 骨架和首个精确 Bilinear Demosaic C++ 内核

V0.4.9 建立接口时尚未编译原生扩展；V0.4.10 已完成真实构建、加载和性能资格验证。
详细构建方法见 `native/README.md`。

基准工具可明确请求后端：

```powershell
python tools\benchmark_pipeline.py --backend opencv
python tools\benchmark_pipeline.py --backend native
```

第二条命令在 Native 不可用时会输出回退原因，不会伪报为 C++ 性能。

## V0.4.8 多图预览缓存

- 已完成处理的工作图像会缓存预览图、流水线前缀缓存、全部中间结果和处理参数快照
- 再次切换到缓存图像时直接恢复结果，不重新提交后台流水线任务
- 图像切换会立即取消待提交请求并使旧任务结果失效，缓存命中时也不会让上一张图的迟到结果覆盖当前界面
- 缓存严格校验图像对象、输入修订号、完整 Pipeline 快照、预览质量和最大预览尺寸
- 参数刷修改目标图、RAW 元数据变化、预览质量变化或图像内容替换后，旧缓存自动失效
- 采用 LRU 淘汰，默认最多保存 3 张图像、总预算 384 MiB；当前图像受保护，单张超预算时仍可正常显示
- ROI 局部处理不会覆盖此前保存的完整图像缓存
- Performance Details 显示缓存图像数量、内存占用、命中、未命中、失效和淘汰计数
- `预览 → 清除多图预览缓存` 可手动释放所有运行时中间结果
- 运行时缓存不写入 JSON，重新启动工具后不会保留

多图调试建议先等待当前图像状态栏显示 `Ready` 后再切换；此时完整预览结果已经进入缓存。

## V0.4.7 交互性能与预览质量

- DPC 动态检测改用 OpenCV uint8 Mask、`countNonZero` 和 `copyTo`，避免多组全尺寸布尔 Mask 与布尔索引
- DPC Static Map 无有效坏点时直接旁路，同时保留空坏点 Mask
- `预览 → 预览质量` 提供快速 900 px、平衡 1200 px、精细 1500 px 三档；默认保持精细档兼容旧工程
- 切换预览质量时自动按比例迁移 ROI、网格外接区域并保持 Bayer 偶数对齐
- 每张工作图像记录自己的预览尺寸；在不同质量档位下切换多图时，ROI 会在激活时自动换算
- Calibration 暗场/平场辅助帧遵循当前预览质量，不再固定为 1500 px
- V0.4.7 曾加入 `OpenCV Fast Bilinear` 预览路径；该入口已在 V0.4.16 的算法收敛中移除
- 最终颜色调整对已处于 0～1 的中性输入直接复用，避免重复裁剪和 RGB 大图分配

性能优先的调参建议使用“快速 900 px + Bilinear”；检查细节时切回
“精细 1500 px”，并对比 Adaptive Interpolation 或 Constant Color Difference。

## V0.4.6 流畅度与性能诊断

- Bilinear Demosaic 移除每次刷新重复执行的三次恒定分母卷积，输出与旧版归一化卷积保持一致
- Tone Mapping 使用 OpenCV float32 向量化幂运算；CCM 使用等价的有效矩阵和 `cv2.transform`
- LSC 零强度、NR 零强度、Sharpen 零强度及单位 CCM 使用快速路径，减少无效计算和 RGB 大图复制
- 基础颜色调整在 Hue/Saturation 为中性值时跳过 RGB↔HSV 往返，但仍保留最终 0～1 裁剪语义
- 新预览请求会通知旧流水线在模块边界提前终止，避免过期任务继续占用整条处理链
- Fit 预览改为先对 float32 图像执行 `INTER_AREA` 缩放，再量化显示，降低主线程 Raster 延迟
- Performance Details 新增端到端延迟、算法耗时、流水线开销和逐模块滚动耗时，并按平均耗时排列热点
- 结果内存估算按共享底层数组去重，中性模块复用输入时不再重复计数

可运行固定尺寸的可重复基准：

```powershell
python tools\benchmark_pipeline.py --width 1500 --height 1000 --iterations 5
python tools\benchmark_pipeline.py --width 1500 --height 1000 --iterations 5 --fast-demosaic
```

基准结果受 CPU、OpenCV 线程数和参数组合影响，应比较同一设备上的迭代前后数据。

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
- 当时曾提供跨图像 `校准刷`；该入口已在 V0.4.11 精简版移除
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
- BLC、LSC、WB、Demosaic、CCM
- ROI/halo 局部处理
- 模块输入输出滑动对比，Compare 手势与 ROI 框选互斥
- LSC Gain Map
- Histogram、Waveform、Vectorscope 和 Bayer/RGB 统计
- PNG/TIFF 图像结果和 ROI 输出

## Auto Analysis

点击顶部 `自动矫正`，选择模块、方法和区域后点击“矫正并应用”。支持：

- Auto BLC：当前暗区 ROI、Optical Black ROI 或外部暗场，分别测量 R/Gr/Gb/B
- LSC：平场自动生成四通道 Mesh
- AWB：Robust Neutral、ROI Neutral、Gray World、Shades of Gray、White Patch
- AE：Mean、Median、Percentile、Highlight Protected
- CCM：使用 ColorChecker 色块求解矩阵与 Offset

统一交互为：

```text
选择模块 → 选择方法/区域 → 矫正并应用 → 主预览自动刷新
```

耗时计算仍在工作线程执行，旧任务结果不能覆盖新请求。

分析结果支持导出 JSON；大型 Mask、曲线和热力图写入同名 `_artifacts.npz`，不会直接嵌入 JSON。

### Auto BLC

Auto BLC 必须使用 BLC 之前的 Bayer DN 数据，支持 Mean、Median 和 Trimmed Mean。输出：

- 四通道 Mean/Median/Trimmed Mean/σ/P1/P50/P99
- 建议 R/Gr/Gb/B Black Level
- 负值裁剪与零值比例预测
- 行、列黑电平变化
- 热像素候选和分析 ROI Artifact
- 暗场过亮、漏光、样本不足和通道差异警告

## 快速自动矫正页

快速矫正页采用单栏结构：

1. 选择 BLC、LSC、AWB、AE 或 CCM
2. 选择方法；AWB 可选全图或当前 ROI
3. BLC/LSC 按需加载暗场或平场
4. 点击“矫正并应用”

页面只显示必要状态和简短结果摘要，不再显示参数差异、测量表、警告页签、
Artifact 画廊、Advanced Options、报告或参数导出。

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
BLC → LSC → WB → Demosaic → 线性 RGB 采样
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

## 配置兼容

```json
{
  "schema_version": 4,
  "tool_version": "0.4.11",
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
  "ui_state": {
    "processing_backend": "Auto"
  }
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

当前 145 项测试覆盖：

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
- 精简流水线模块集合与旧配置兼容
- 后端自动选择、Native ABI 拒绝、不可用回退和逐内核回退
- Demosaic Native 调用契约与后端安全的流水线缓存
- 原生扩展四 Bayer Pattern 和可选二进制契约
- Auto 内核性能资格、实验内核强制模式及混合后端诊断
- 快速自动矫正的一键分析与应用，以及过期任务保护
- Compare 分割线与 ROI 手势优先级
- V1/V2/V3→V4 迁移
- Calibration UI 状态机合法/非法转换和 Stale 检测
- FileList 元数据校验与 ROI 状态
- V0.4.1～V0.4.11 UI 状态持久化
- 隐藏 Tk 窗口下的应用、单栏快速矫正、AWB 一键应用和关闭冒烟流程

## 快捷键

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl+O` | 打开 RAW / 图像 |
| `Ctrl+E` | 导出当前结果 |
| `Ctrl+Shift+C` | 打开快速自动矫正 |
| `A` | 打开当前模块的自动矫正设置 |
| `Escape` | 取消正在运行的自动矫正 |
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
- ColorChecker 需要用户提供四角，不做任意场景自动检测。
- 当前目标工作空间固定为线性 sRGB。
- V0.4.11 不提供 DPC、Tone、NR、Sharpen、Contrast/Color Adjustment。
- 配置与报告底层代码仅用于旧工程兼容，当前精简界面不提供导入/导出入口。
- 未实现 3D LUT、多帧 HDR、批处理、插件系统、PySide6/OpenGL 和 GPU。

## V0.5 建议

优先增加项目管理、批量 RAW 对比、3D LUT、模块排序、可插拔算法和校准数据集管理；PySide6/OpenGL/GPU 建议放到后续独立版本。
