# V0.4.43 CCM / 导出核验记录

## 确认的根因

1. 旧 export_image 调用 display_rgb 后直接乘 255/65535，漏掉预览使用的 sRGB 编码。线性 0.18 直接保存约 46，而正确显示编码约 118：这能解释明显的亮度差异。
2. UI 导出直接读取 results，这份缓存可能是缩小图或“仅处理 ROI”的局部图，而非完整原始分辨率输出。新导出在工作线程处理原图和点击时的参数快照，只执行至当前模块。
3. N Ohta 参考第 18 块 Cyan 在 D65 下含负的线性 sRGB 红分量，旧 CCM 度量将其裁剪成 0，错误地改变标准 Lab。标准色卡不必全部处于 sRGB 色域中。
4. 参考生成使用 colour 的 XYZ→sRGB 矩阵，分析使用独立的 SRGB_TO_XYZ 常量；本轮改为同一矩阵的正/逆变换，消除小幅不一致。

当前安装库计算的例子（近似值）：

| Cyan #18 | L* | a* | b* |
|---|---:|---:|---:|
| 未裁剪参考 | 51.6863 | -24.7275 | -25.9729 |
| 旧 RGB 裁剪后的参考 | 52.4827 | -19.9541 | -24.6773 |

线性 sRGB ≈ (-0.033365, 0.248815, 0.385504)。这是数值实现错误的修复，不是为了对齐截图手改标准值。

## 当前参考条件

- ColorChecker Classic 24 布局，colour-science `SDS_COLOURCHECKERS['ColorChecker N Ohta']` 光谱反射率。
- 来源：Noboru Ohta 数据集；应用结果记录安装的 colour-science 版本。
- CIE 1931 2° 观察者，在用户选择的 D65/D50/A 照明下积分 XYZ。
- CAT02 从源照明白点适应至 D65；Lab 与线性 sRGB 统一按 D65 处理。
- 1–18 为彩色块（dark skin…cyan），19–24 为白到黑中性色块。旋转/翻转只改变采样与参考索引配对。
- 优化、手动评估、图表都保留未经 RGB 裁剪的参考 Lab；显示时才裁剪。

## 与 Imatest 的差异不能只看截图

[Imatest Colorcheck 官方说明](https://www.imatest.com/docs/colorcheck/)列出 X-Rite old、2014 年前/后版本、BabelColor 以及自定义 Lab/XYZ 参考。其 D50 Lab 到 D65 的常用路径为 Bradford。N Ohta 光谱积分 + CAT02 不等同于这些配置。该页也特别指出 Cyan #18 超出 sRGB 色域。

[Colour 的 N Ohta 数据集文档](https://www.colour-science.org/api/0.3.4/html/colour.characterisation.dataset.colour_checkers.spds.html)提供该光谱数据集的名称与色块。实际计算取本机安装库，不从文档截图抄数值。

要逐块对齐 Imatest，还需要：Imatest Reference 的完整选项/参考文件、色卡制造版本、分析色彩空间/白点，以及是否启用了曝光/饱和度归一化。现有材料不足以声称与用户 Imatest 结果完全一致；本轮未擅自切换数据集或 CAT。

## 可视图与计算数据

- PNG：与主预览同一 8-bit sRGB LUT；包括预览 EV，排除诊断、通道单独显示和几何叠加；RGB 顺序通过 Pillow 保存。TIFF 显示图采用 sRGB 16-bit 编码。RAW/线性 RGB 可视文件附 sRGB ICC。
- Bayer：使用单像素单通道 Mosaic，不去马赛克。ROI 先形成全图 Mosaic 再裁切，保持奇数坐标的 CFA 相位。
- Float32 TIFF：非显示数据，无 Gamma/EV，无额外裁剪，保留实际域、负值和超范围值。普通看图软件不一定正确显示。
- YUV：已编码 RGB 不重复施加 sRGB 传递函数，不擅自声明未知源传递函数为 sRGB。
- 全分辨率输出与缩小预览存在采样/插值差异，不承诺逐像素等同；保证同一阶段、参数、归一化和显示映射。显示 TIFF 与 8-bit PNG 因精度及 LUT 近似可相差少量量化值。

## 色域边界含义

右图为 sRGB 在 Lab L*=70、D65 下的真实截面。沿 a*b* 方向求 RGB 立方体的边界交点，未使用裁剪结果判断边界。边界、背景色彩计算均缓存；窗口大小变化只调整栅格尺寸/坐标。

不同 L* 的色块不应仅据该截面内外判定是否超色域，因此本轮不对二维越界点自动标“超色域”。

## 验证限制

全量 unittest discovery 350 项通过，使用逐用例主线程 GC 避免历史 Tk 对象在工作线程回收时长时间阻塞；没有跳过用例。随后增加 YUV 导出测试，相关 32 项复跑通过。全 32 种模块开关组合中，每个阶段都验证了保存 PNG 与显示函数的逐像素一致性。语法编译和 diff --check 通过。

使用程序生成的 Bayer/色卡和数值测试验证；尚未用用户原始 RAW 与匹配的 Imatest 参考文件做端到端对照。Tk 多窗口测试可能输出历史 ThemeChanged/after 清理警告，须与实际断言失败区分。
