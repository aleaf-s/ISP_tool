# Changelog

## 0.4.61

- 按用户要求，取消手动“扩展到其他亮度层”及 smoothstep 衰减；H/S 单点、邻域、拖动、粘贴和重置选区自动用中心层完整 H/S 等量覆盖全部 9 个 V 层。覆盖已有 H/S，逐节点保留未知第三字段；重置表恢复全部层。导入、取色、无数值修改的失焦和单独调整强度不压平文件；覆盖与编辑共享一次撤销记录。
- 新增独立 CLUT Attr 生效强度：Enable、gain_r/g/b 整数输入与滑条（0～4095、默认512），按公开公式 `out = in + (LUTout - in) * gain / 512` 缩放各 RGB 通道位移。512=1倍、1024=2倍，不将1024误当单位增益，也不乘绝对RGB。超范围LUT顶点保留至像素插值后再裁切，避免高增益提前裁切改变强度。
- 原整体强度更名“HSV 参数倍率”，继续缩放并烘焙 H/S 参数。RGB生效强度为独立Attr，不写入或烘焙HSV TXT，界面与导出状态明确提示设备端另填。界面导入HSV保留现有Attr，每图独立保留增益、非法草稿、撤销/重做与已应用快照，恢复时同时恢复增益。
- 预览与PNG/TIFF图像导出共用增益和应用状态。用户工具版本为PQ Tools V1.1.45；芯片/SDK尚未确认，软件HSV求解、Gamma、线性RGB域及量化仍未完成实机校准，不宣称已复现设备画面。
- 验证：增益、全亮度覆盖、HSV交互/格式及CA相关64项回归，58通过、6项旧设备界面用例按原标记跳过，0失败/错误（51.8秒）；compileall、修改文件编码与尾部空白检查通过。未重跑全项目测试，未完成实机画面对照。

## 0.4.60

- 新增 HSV 整体强度系数（0～2，默认 1），独立缩放全部亮度层的 H/S 修改量，不累乘基础参数；支持显式应用、撤销/恢复、非法输入校验，TXT 导出烘焙系数并与软件预览共用相同参数。
- 根据后续确认固定编辑 V=0.5，取消取色跟随 V 和亮度层切换；新增手动“扩展到其他亮度层”，中心修改量按 smoothstep 向两端衰减，保护文件已有调整与未知字段，支持重复更新本会话生成节点和撤销/重做。简化右侧节点数值说明与底部常规文字，保留报错。专项回归 28 项通过。
- HSV 交互修正：上方信息区保持不变，色轮/表格左置，参数与应用/文件按钮移入右侧可滚动栏。增大节点与网格线，网格随目标节点实时变形；拖动固定坐标尺度并保留鼠标偏移，避免自动缩放反馈和 0°/360° 重叠选点跳动。
- 取色默认保留当前亮度层，只定位 H/S；提供“跟随取色亮度层”开关和明确层提示，避免自动切入零偏移层被误认为重置。相关 HSV/调色/CA 回归 42 项通过，并增加实际海思 HSV 取色后原样导出校验。
- 将界面收敛为“HSV 调色”，移除设备 CLUT TXT/JSON 操作、设备数据页、预览来源和旧 HS 模型选择；每图使用独立 HSV 草稿与已应用状态。内部预览查找表及历史校验函数保留，不影响 CA/AWB/取色调色。
- HSV TXT 修改保存改为按字段替换，保留 BOM、换行、记录顺序、前缀 RGB 对和未知字段；未修改字节一致，修改同节点一个分量不重算另一分量。重置仅作用于已知 H/S，不丢弃第三字段。
- 色轮节点和表格目标色联动，表格增加原色细条；色轮保留原/目标位置并适应大于轴端点的目标 S。默认三维 HSV，支持独立 V 层、无需回车提交、草稿导出不自动应用主图。
- 未知第三字段导致图像应用失败时明确显示“未应用”并弹窗，保留参数导出；持续标注图像软件近似及 RGB 对仅保留的限制。海思实机回导尚未验收。
- 高字号下按控件所需尺寸设置调试窗口最小大小，避免底部控件挤没表格；复用每图 HSV 状态，避免重绘时反复构造 2700 节点默认网格。
- 新增 13 项 HSV 专项测试，并迁移 V0.4.57 的 HSV 工作流用例。41 项针对已删除旧 HS/设备界面的历史测试明确跳过，底层算法、打包及其余模块测试继续运行。全项目复测 525 项：484 通过、41 跳过、0 失败/错误（250.8 秒，测试间在主线程回收垃圾，仍有少量 Tcl 销毁事件警告）。此前首次完整测试暴露的旧界面用例不再适用和高字号表格高度问题已分别归档/修复。
- 最后状态读取优化后，HSV、取色调色与 CA 共 38 项收尾复测通过（47.8 秒）；compileall 和 git diff --check 通过。

## 0.4.59

- 按官方 `hi_isp_clut_lut` 核验既有格式：17³ 有效节点、八组交错地址、595 个零填充槽、共 5508 个整数；低/中/高 10 位为 R/G/B，合法偏移 −511～511。原核心布局正确，未交换通道或重排成 17×18×18。
- 修复 `pack_deltas` 使用绝对值校验时，NumPy 有符号整数最小值溢出而绕过检查的问题；地址缓存数组设为只读，防止调用者意外修改共享布局。
- 新增 6 项独立格式测试，覆盖闭式地址公式、随机全表参考编码、已知 word 和通道脉冲、数值边界、全部填充槽、用户样例 TXT 导入导出。增强只读校验脚本，输出位域、分组、有效节点及填充统计。
- 验证：本版及 V0.4.51/56/57/58 共 52 项通过（83.1 秒）。未更改软件 HSV→CLUT 求解器；硬件颜色、Gamma、增益及实际设备回导仍需验证。

## 0.4.58

- 修复 HSV 将输入 S 轴 1.17 错当成目标上限：用户 `lantian_caodi_HSV.txt` 中 26 个超过 1.17、最高 1.179 的节点现在可导入；未编辑保存字节一致。目标 H 和未知第三字段不再套用未经确认的幅度范围，仍校验有限数、非负 S、节点数、轴与索引。
- 将 HSV/HS 编辑网格与导入设备 CLUT 分开保存，两种导入顺序互不覆盖。HSV 导入自动显示有变化的节点；CLUT 导入展示独立只读设备数据页，可查看全部 5508 个原始整数（含填充）及 4913 个解码 RGB 节点，不再把额外调整零表作为设备数据反馈。
- 新增显式预览来源；设备表导入后点击应用使用原设备 LUT，独立 HSV 不重复叠加。编辑节点自动切换为软件近似来源，旧设备表保留且不会自动重生成。恢复上次应用恢复两份数据与来源；设备来源导出保持 5508 个原始整数。含未知第三字段的 HSV 仍不能直接生成效果，但不妨碍独立设备表预览。
- 导入成功显示文件名/数量，失败在可见调试窗口弹窗并保留原数据。设备数据页隐藏无关的编辑区；编辑页合并操作行并优先为底部操作区分配空间，避免小窗口控件被表格挤掉。
- 新增 8 项回归，覆盖实际用户 HSV 往返、两种导入顺序、非零节点显示、设备表预览与导出、未知字段保护、非法导入原子性、恢复、图像隔离及窗口布局。未新增海思硬件/Gamma/求解器一致性承诺；未进行硬件回导或多屏 DPI 人工验收。
- 验证：CLUT/CA 相关 81 项通过（119.7 秒）；最后增加设备表自动定位非零行和重绘缓存后，本版 8 项复测通过（27.0 秒）。compileall、git diff --check 通过。本轮未重跑全项目测试。

## 0.4.57

- CLUT 增加三维 HSV 模式：25×12×9 节点（含 Hue 360° 接缝），使用用户样例的 S 轴与 9 个 V 层；亮度切片选择真实编辑层。旧版 24×9 HS 保留，切模型创建新草稿，可撤销，不自动应用图像。
- 数字输入、色轮、邻域、粘贴、选区重置作用于当前 V 层；取色同时定位 H/S/V。跨层数字草稿原子校验，失焦绑定包含层号，保持显式应用、恢复上次应用与每图隔离。
- 新增 2700 记录 HSV TXT 导入和草稿保存。目标 H/S 可编辑，未知第三字段保留；非零时禁止应用图像/生成设备表，仍可保存。用户 `74HS.txt`、`10HSV.txt`、`222HSV.txt` 未修改往返字节一致；修改后保留全部节点与前缀来源数据。
- 预览使用明确标注的软件 HSV 三线性插值及 33³ RGB 烘焙，不冒充 PQTools 求解器。设备 CLUT 仍为 5508-word TXT；`74HS.txt` 软件生成与配套 `74CLUT.txt` 仍有 31 个 word 不同，尚未对齐 Gamma/亮度处理/内部尺度。Hisi 实机回导与多屏 DPI 人工视觉验收未完成。
- 新增 8 项测试；完整 498 项中 497 项通过，既有批量导入测试在 5 秒等待后只收到一张图而失败。随后该用例与 CLUT/CA 相关共 74 项复测全部通过（58.7 秒）。完整测试期间出现既有 Tk 销毁/跨线程清理警告；不能称本轮完整回归全绿。

## 0.4.56

- 修复 CA 固定宽度、无滚动侧栏挤压/裁切控件的问题：侧栏按字体所需尺寸布局，支持滚动；应用/恢复固定在底部；曲线使用实际画布大小和字体测量留边。添加双击创建节点、Delete 删除、节点计数、端点保护及撤销/重做禁用状态；Y 失焦确认草稿，非法输入保留并提示。重复 X 不创建虚假节点，撤销删除/添加后自动恢复有效选中节点。
- 移除 CLUT 界面 JSON 导入导出入口，增加海思 5508 个整数的设备 TXT 导入。完整校验后载入为当前图像草稿，应用后真实参与预览和图像导出；未修改时原整数、顺序、数据量无损往返。导入设备表不可唯一还原 HS 网格，因此网格明确作为额外调整，重置表保留基础设备表，撤销/恢复包含设备表快照。
- CA 保持 256 个十进制值 TXT 导入导出，增删控制点不改变导出数量。配套海思 HSV 文件提供独立结构检查（样例 2700 条六字段记录），未确认字段语义前不伪造导入/导出能力；完整 HSV 工程编辑仍待芯片/SDK 资料。
- 新增 8 项回归，覆盖 CA 新增/重复/删除/撤销/失焦/拖动/显式应用、三个 Tk 字体缩放与两种高度的布局可达性、CLUT 实际变换和 TXT 导入应用导出、非法文件不覆盖以及用户样例往返。补充最后一项官方交互测试前完整 unittest 489 项通过（171.7 s）；布局/导入收尾后相关 64 项通过。参考用户提供的海思官方指南追加 X 查询和右键取消节点后，CA/CLUT 专项 18 项通过。仍有既有 Tk ThemeChanged/after 清理警告；未做真实多显示器 DPI 人工验收或海思实机颜色验收。

## 0.4.55

- CLUT/CA 主数据导出统一为明确的 TXT 入口，并拒绝不匹配的扩展名。CLUT 使用既有 HiSilicon 5508-word 打包，CA 使用既有 256 点十进制格式；可继续编辑的 JSON 方案收进独立备份菜单，不再与设备导出混用。
- CLUT 图像取色显示原色与草稿目标色的 HSV；自动进入 Delta Hue（或保留 Delta Sat）、滚动到最近单元格并突出选中边框，标注行列。中性色的色相显示“—”。
- 修正表格点击先切换节点、后失焦导致旧输入未提交的问题。点击其他格、失焦或 Tab / Shift+Tab 均可确认草稿；仍保留显式应用，不在编辑时执行图像处理。
- 验证：CLUT/CA 相关既有 54 项测试通过；新增 TXT 实际导出、HSV 取色定位、连续输入及 Apply-only 3 项测试通过。未新增硬件兼容承诺，也未进行各类 DPI 的人工视觉验收。

## 0.4.54

- 手动调色新增独立 CA 曲线模式与可调整大小的 Chroma Adjust 窗口：亮度 Y 为横轴，0～2047 UV 色度增益为纵轴。支持控制点拖动、X/Y 数字设置、添加/删除结点、撤销/重做、加载数据、导出数据、显式应用及恢复上次应用。
- 17 个默认控制点使用保形三次插值生成 256 值曲线；默认 1024=1×。导入任意合法 256 值 TXT 后保留原始完整表，首次调整时才依据控制点重新生成。用户上传的 2830 字节样例经导入/导出为字节级一致；非法格式与越界值拒绝。
- 软件预览按 BT.709 亮度选择表值并缩放相对亮度的色度，固定 ISO 增益 1×；接入已有快速/原分辨率预览、滑动对比、按住原图、缩放与 PNG/TIFF 导出，图像导出共用处理函数。草稿/已应用曲线及数字草稿按图像隔离，调整期间不积压 ISP 任务。
- 新增 7 项 CA 测试，覆盖曲线平滑与边界、TXT 往返、图像处理、Apply-only、恢复、非法输入、按图隔离、草稿保留及导出一致性。完整 unittest 在增补最后一项测试前运行 478 项通过（222.5 s）；增补后 CA 专项 7 项、CA/CLUT 相关 31 项均通过。compileall 与 git diff --check 通过。仍有既有 Tk ThemeChanged/after 清理警告。
- 限制：硬件 ISO 比例、Y/UV 量化和内部舍入未从 TXT 获知，软件预览是明确标注的软件近似；TXT 数字布局与样例一致不等于设备画面逐像素一致。未进行实体屏幕视觉验收。

## 0.4.53

- CLUT 新增从原图取色定位：5×5 原始像素平均色定位最近色轮/表格节点，显示原色和草稿目标色；低彩度/黑色归中性轴，透明中心拒绝取色。取色不应用参数，不覆盖未提交草稿。
- 新增邻域范围和平滑强度；单点数字和拖点按环绕 HS 距离分配增量，中性轴锁定、Hue 最短角过渡、Sat 越界整体拒绝。粘贴/重置保留精确选区语义。橙色预估影响层仅绘制于预览，缓存缩略图掩码，不写入导出或像素读取。
- 新增“恢复到上次应用”，清除数字草稿并恢复已应用网格，不重算主图；“保存当前方案”原子校验后保存网格草稿，不自动应用。工具状态按图像隔离；方案 JSON 继续兼容 v1，邻域工具设置、取色和叠加状态仅会话保留。
- CLUT 底部文件操作与应用/恢复分行，取色色块根据可用宽度横排或竖排，避免窄窗口与高 DPI 下文字拥挤。
- 新增 12 项测试，覆盖原图取色、透明/低彩度、草稿保留、邻域/Hue 接缝/灰阶/原子越界、Apply-only、多图隔离、恢复、方案保存以及叠加缓存/不污染导出。
- 验证：完整 unittest 472 项通过（268.7 s）；最终底部布局调整后相关 25 项复测通过；compileall、git diff --check 通过。既有 Tk ThemeChanged/after 清理警告仍存在。computer-use 已检查合成主窗口，独立编辑器点击被前台窗口遮挡保护拦截后停止交互，未完成最终实窗视觉验收。HiSilicon 实机兼容性限制未改变。

## 0.4.52

- CLUT 改为独立可拉伸、可最大化的非模态调试窗口，色轮与表格视区随窗口扩展；右侧保留紧凑入口、状态和应用按钮，窗口底部固定文件操作与应用。关闭只隐藏，当前会话保留几何尺寸和草稿。
- 每图分离编辑网格与已应用网格；输入、拖点、撤销/重做、重置、加载只改草稿。点击应用先原子校验所有数字草稿，再更新图像；重复应用去重。预览/像素读取/导出只使用已应用快照；有待应用修改时导出提示阻止。跨图/模式切换保留状态，拖动结束不会写入另一张图。
- 新增统一数字显示格式：普通参数按 ParameterSpec.step，CLUT Hue 一位/Sat 三位，CCM Float 四位，手动调色 RGB/Hue 一位、S/V 三位、范围/强度一位。省略尾零、保留极小非零值；整数及 Fixed 编码不变。未修改字段保持原始精度，失焦不重新量化，键盘微调从实际值起算，编辑一个通道不降低其他通道精度。
- 新增 13 项回归，覆盖 Apply-only、原子验证、重复应用、草稿/已应用多图隔离、加载保存/导出保护、窗口重开与实际尺寸扩展、参数显示/微调和 CCM 格式切换精度。旧 CLUT 测试按显式应用更新。
- 验证：完整 unittest 460 项通过（265.7 s），最后调整加载确认措辞后相关 1 项复测通过；compileall 与 git diff --check 通过。仍有既有 Tk ThemeChanged/after 清理警告。缩放行为通过 Tk 自动化尺寸检查，未做各类高 DPI/多屏人工视觉验收；HiSilicon 硬件兼容限制未改变。

## 0.4.51

- 手动调色新增互斥的 CLUT 模式：24×9 HS 色轮、Delta Hue / Delta Sat 网格、数字编辑、矩形 TSV 复制粘贴、选区重置、撤销/重做；每图独立参数和草稿。原取色调色保留，不叠加计算。
- 33³ 编码 sRGB CLUT、周期 HS 插值和四面体 RGB 位移插值；中性轴保护，色轮 V 仅改变编辑器显示。接入现有快速/原分辨率预览与完整图像导出，保持固定中心缩放和滑动对比。
- 新增编辑参数 JSON 保存/加载、RGB CLUT JSON 导出、实验性 HiSilicon 5508-word TXT 导出及只读样例审计脚本。用户 TXT 全部数据解包/重打包一致；硬件尺度、CLUT Gain、插值和扩展 HSV 字段语义未确认，不宣称实机兼容。
- 修正高 DPI 面板宽度误引用旧取色面板的问题；色轮尺寸跟随字体，操作按钮分行，紧凑数字显示不反向量化未编辑字段，单击选点不重算图像。
- 新增 22 项 CLUT 回归，涵盖恒等/中性轴/Hue 接缝、保存加载、预览导出一致性、打包边界、失败不覆盖、多图/草稿隔离、快速请求、旁路和精度保留。
- 验证：最终完整 unittest 447 项通过（255.1 s），compileall、git diff --check 通过。1000×750 合成图单次 CLUT 处理约 281 ms（不含 UI，不作为帧率承诺）。仍有既有 Tk ThemeChanged/after 清理警告。
- 使用 computer-use 对合成窗口做了初步视觉检查并据此修正布局；之后窗口被最小化且检测到人工操作，停止自动交互。最后布局补丁通过控件尺寸回归，尚未完成最终实窗视觉复核。HiSilicon 设备验证与 `_HSV.txt` 工程导入/导出仍不在已验收范围内。

## 0.4.50

- 手动调色/AWB 仿真增加异步原分辨率可见区域预览，共用导出颜色处理，改为先处理原图像素再显示缩放。保留快速预览，150 ms 防抖、分块取消、最新视图校验和一对视口缓存。
- 取消两个模块的拖动平移和鼠标跟随缩放，固定画布中心缩放；滑动对比、取色、适应窗口仍保留。鼠标读数改为原图像素。
- 修复 AWB 过期快速任务报错后未调度最新请求的异常路径。调色 LUT 复用最多 4 份，分割线及原图切换不重算。
- 新增原分辨率预览/导出逐像素对照、缩小顺序、高倍率可见区域、Alpha/越界、取消、缓存、固定中心和草稿隔离测试。已有平移偏移恢复测试按新交互更新。
- 验证：完整 unittest 424 项通过（235.3 s）；最后补充删除图像清理预览缓存后，相关 19 项复测通过。compileall、git diff --check 通过。4K 合成图中心放大视口单次 AWB 计算约 97 ms（不含 UI 绘制，不作为帧率承诺）。仍有既有 Tk ThemeChanged/after 清理警告；本轮未做实体屏幕人工视觉验收，不改变 AWB 硬件近似模型。

## 0.4.49

- 手动调色和 AWB 仿真默认滑动对比；同会话保留用户对比模式选择。
- 修复多图共用 GradeHistory/LUT 造成的串扰：改为稳定图像 ID 绑定独立历史、草稿、启用状态和预览缓存，统一列表仅负责展示。
- 色块增加稳定 ID、名称与所有者，列表按用户反馈只保留名称/来源两列，原/目标色预览位于编辑区；支持双击/右键重命名、显式独立复制到指定图片，删除图像同步清理状态。
- 切图/选色块保护输入草稿，延迟失焦提交以编辑上下文校验，旧异步结果同时校验图像 ID、请求版本和参数签名；旧任务失败不阻塞新图。
- 更新原先共用调色测试的预期，新增默认模式、双图隔离、重命名、复制、草稿、失焦竞态、重排/同名/删除重导、过期任务和分割线交互测试。调色算法未改动。
- 验证：完整 unittest 414 项通过；最终列表精简后 13 项针对性回归通过，compileall、git diff --check 通过。合成窗口已检查布局和右键菜单；仍有既有 Tk ThemeChanged/after 清理警告，调色状态仅保留当前会话。

## 0.4.48

- 工具统一更名“AWB 仿真”，右侧按原参数/目标参数分组，相关操作就近放置，应用按钮固定在滚动区外。
- 标定表“保存并使用”持久化设备名称及完整 Float 数据，下次启动自动加载；同目录原子替换，保存失败不改变活动表，损坏文件不静默覆盖。
- 精简算法说明与正常状态文字，常规提示收进 Tooltip；保留估算/偏离轨迹/错误提示并去重，矩阵量化说明不再占据常驻行。
- 新增标定保存/恢复、写入失败、损坏文件、取消草稿、配置路径隔离、分组结构和警告显示测试。仿真算法与显式应用流程不变。
- 验证：完整 unittest 报告 401 项通过，新增 11 项独立回归通过；compileall、git diff --check 通过。首轮测试发现方式的导入路径已修复并全量复跑。全量断言结束后仍有既有 Tk ThemeChanged/after/变量析构清理问题，测试进程停留在退出清理阶段，已单独结束该测试进程；未进行实体屏幕高 DPI 视觉验收。

## 0.4.47

- AWB 重调拆分原/目标 CCM；目标支持沿用原矩阵、标定表自动联动、手动输入，保留显式应用、手动草稿与共享 Float/Fixed 表示。
- 内置用户提供的 2300/3054/4166/5093/6500 K 五组 Gain 与 13-bit CCM；解码后各行和均为 1，条件数约 2.21～2.51，不静默修正数据。
- 新增独立 log-Gain 轨迹投影策略、浮点 CCM 插值、倒色温辅助估计、偏离轨迹和端点限制提示；不是硬件联动规则。
- 计算更新为 M_target D M_original^-1，恒等条件同时检查 Gain 与矩阵，验证两端、插值及组合变换的稳定性。
- 标定表窗口支持事务式编辑、增加/删除、JSON 加载保存、恢复不可变默认表；表签名与来源进入已应用快照，改表不覆盖原 CCM 或自动处理图像。
- 新增默认数据、插值、范围/异常输入、JSON 编码、双矩阵正向合成、草稿与模式切换、标定窗口操作回归。
- 验证：完整 unittest 390 项通过（用例间主线程 gc.collect）；本轮相关 21 项通过，最后补充增删标定点交互后新增 11 项复跑通过。compileall 与 diff --check 通过。仍有历史 Tk ThemeChanged/after 清理警告；未将合成验证等同于硬件精度验证。

## 0.4.46

- 工具菜单新增独立 AWB Gain 重调预览：单张截图、当前/目标 R/G 与 B/G ×1024、共享 13-bit/Float CCM 编辑器，显式应用与草稿提醒。
- 实现受条件数检查保护的 M D M^-1 线性求解、有符号 BT.709/sRGB 曲线和恒等旁路；固定 CCM/曝光，拒绝非法 Gain、奇异及严重病态矩阵。
- 明确截图 sRGB 与假设的播放器 BT.709→sRGB 转换条件；截图路径消去成对的 709 变换，导出真实 sRGB 编码，不错误标注配置文件。
- 将手动调色的视口裁剪、左右/滑动对比及导航抽为共享组件；RAW/YUV/手动调色/AWB 之间恢复菜单、快捷键、图像和草稿。
- PNG/TIFF 全尺寸导出复用显示处理并冻结已应用参数，草稿或计算未完成时禁止静默导出旧设置。
- 新增恒等、增益倍率、非单位 CCM 正向合成、Gamma、负值/超范围、ICC/Alpha/导出、草稿、过期任务、缩放和工具切换测试。
- 验证：完整 unittest 379 项通过（用例间主线程 gc.collect），包含本轮新增 10 项；相关 28 项单独通过。compileall 与 diff --check 通过。1000×750 合成截图单机计算约 151 ms，不含读图/绘制，不作为帧率承诺。仍有历史 Tk ThemeChanged/after 清理警告；未使用真实 PotPlayer 配对截图验证硬件精度。

## 0.4.45

- RAW ISP、YUV 预览、手动调色收纳到统一 ToolSelector 下拉菜单，共用选中状态；移除调色页重复返回入口，保留工作区实例与快捷键隔离。
- 调色 GradeHistory 从 ColorDocument 提升为工作区状态；多图共用颜色控制点、强度、范围、启用与撤销重做，来源只作提示，不绑定源图生命周期。
- 单图保留缩放/平移/对比状态，切图保留颜色输入草稿；当前图按需预览，跨图过期任务丢弃，导出使用公共参数快照。
- 重置全部明确提示影响所有图像，删除来源图不删除点；RAW/YUV 切换恢复上次图像与查看位置。
- 新增共享控制点、移除/新导入、草稿、全局重置、跨图任务、公共导出与统一导航回归；更新旧入口测试以验证新菜单。
- 验证：全量 unittest 368 项通过；最后补齐 RAW/YUV 模块、查看状态、输入草稿及对应导入路由后，相关 26 项复跑通过（含本轮新增 8 项）。compileall 与 diff --check 通过；仍有历史 Tk ThemeChanged/after 清理警告，本轮未宣称修复。

## 0.4.44

- 新增独立嵌入式手动调色工作区：彩色图导入、原图取色、多颜色锚点、Target RGB/HSV 联动、范围/强度、重置与撤销/重做。
- 增加同步左右对比、滑动分割线、临时原图与调色旁路；高倍缩放只绘制视口，右侧参数支持独立滚动与 DPI 自适应宽度。
- UI 外独立实现 33³ 3D LUT 生成/三线性插值、sRGB 彩色图读写和编辑历史；Identity 采用位移插值保证原数值不变。
- 后台预览合并过期请求；PNG/TIFF 全分辨率导出使用相同 LUT，保留 Alpha，明确 ICC/16-bit 输入限制。
- RAW/YUV 参数和快捷键在进出工作区时隔离/恢复，不修改 ISP 算法。
- 验证：全量 unittest 360 项通过（用例间主线程 gc.collect）；最后补充导出前草稿提交验证后，本轮 10 项回归通过。保留历史 Tk ThemeChanged/after 清理警告。
- 使用合成图实窗验证高 DPI 布局、数字提交、参数滚动、左右/滑动对比与分割线拖动；1000×750 单锚点插值单机测试约 119 ms，不含读图和绘制，不作为实时帧率保证。

## 0.4.43

- 修复可视导出漏 sRGB 编码和直接导出预览缓存的问题；完整模块前缀使用独立参数快照在后台处理，支持显式 ROI 与 Float32 计算数据导出。
- 移除重复参数说明，增加惰性 Tooltip；增加 CCM 色卡框可见性开关，不改采样几何和流水线。
- 修复标准色卡扩展 RGB 被裁剪、XYZ/RGB 正逆矩阵不一致；保留 N Ohta 光谱参考，结果记录参考照明、观察者、CAT02、Lab D65 与库版本。
- Color Analysis 统一 Δ 符号，移除底部公式，增加真实 sRGB L*=70 / D65 截面与缓存背景。
- 新增 PNG/TIFF/Float32、32 种旁路组合逐阶段导出、奇数 ROI 相位、参考 XYZ/Lab、负 RGB 参考与色域边界回归。
- 验证：unittest 全量发现 350 项通过（用例间在主线程执行 gc.collect）；最后增加 YUV 导出回归后，相关 32 项复跑通过。compileall 和 diff --check 通过。保留历史 Tk ThemeChanged/after 清理警告，不将其当作本轮已修复。

## 0.4.42

- 用紧凑数字框替换模块参数滑块；支持草稿、提交去重、范围验证、Reset 和键盘步进，滚轮不修改参数。
- 默认浅色 UI；统一菜单、输入、选择、禁用状态与下拉箭头，保留中性灰预览。
- 新增共享 CCMMatrixEditor 与 13-bit / ×1024 补码转换；格式切换仅改变表示，显式“校正”才应用。未编辑的量化视图保留浮点原值，非法编码与溢出明确拒绝。
- 手动/自动 CCM 共用格式偏好；参数配置仍为浮点，UI 状态记录格式选择。
- 增加全 8192 编码往返、边界与舍入、草稿保留、提交去重、浅色状态和紧凑布局测试。

## 0.4.41

- 修复 CCM 色块表格/分析窗口双向同步引发的无限选择事件循环；去掉无内容变化的 FocusOut 失效处理。
- 分析窗口改为校正结果专用表：DEab / DCab / DL / DC / Dh / Da / Db；数字列按字体测量，支持横向滚动。
- a*b* 图改为彩色 Lab 背景、标准方块、输出圆点和偏差连线；背景有界生成并缓存，重绘节流。
- CCM 自动页改为可编辑矩阵与“校正 / Color Analysis”；手动校正只评估并应用输入矩阵，保留独立曝光增益，不重新拟合。
- 移除重复缩略图/结果表与非核心参数的常驻展示；方向、光源保留在区域菜单。
- 修复已有建议后“重新计算 CCM”被状态门控静默忽略的问题；分析窗口不再自动弹出。
- 新增指标公式、手动矩阵应用、选择反馈收敛、重开窗口不执行 ISP、绘图缓存及精简控件回归测试。
- 验证：全量 `python -m unittest discover -s tests -q` 332 项通过；本轮相关 17 项复跑通过。首轮全量中旧 Histogram 用例发生一次超时，单独复跑及第二轮全量均通过；测试退出时仍有历史 Tk ThemeChanged/回调清理警告。使用可见桌面合成色卡窗口实测双击打开和数字/图形布局，未将其作为真实 RAW 校准精度验证。

## 0.4.40

- 修复 CCM 结果展示在 Tk 主线程对全分辨率图执行 float64 变换导致窗口未响应的问题；缩略预览现在先降采样再套用 CCM。
- 修复分析表格行高未跟随字体/DPI造成数字裁切，以及左右窗格被表格请求宽度挤压的问题。
- 新增独立 `Pre-CCM Exposure` 参数：先以中性色块的加权中位数对数亮度比匹配标准色卡，再计算颜色矩阵。
- 自动 CCM 非线性阶段改为直接优化 CIE Lab a*/b*，L* 仅用于很弱的稳定性保护；曝光不再由矩阵承担。
- Auto CCM、手动预览、整图安全检查、CCM 导入导出均支持新的曝光标量。
- 新增 V0.4.40 回归测试，覆盖曝光分离、a*/b* 收敛、参数执行次序、高 DPI 行高、窗格宽度和缩略图计算范围。

## 0.4.39

- 进入 CCM 模块时在主预览自动创建或恢复 ColorChecker Classic 24 色卡框，支持整框移动、四角透视调整、方向标记和中心重置。
- 将色卡拖动接入统一画布手势仲裁；Compare 分割线优先于色卡，色卡优先于普通 ROI，拖动期间只更新 Overlay。
- 色卡几何、Rotation、Flip、排除块、检测来源和选中色块改为每张工作图独立保存，并随预览缩放同步换算。
- 新增 Lab→LCh 和 ΔL*/ΔC*/ΔH* 公共实现；Hue 使用 0°/360° 最短角差，低色度 Hue 单独标记为不稳定。
- CCM 感知优化改为色度/色相优先、明度低权重；使用中性色块估计曝光诊断增益，将曝光与矩阵色彩拟合解耦。
- 主对角 1.0～2.5 和非对角符号由硬边界改为软先验，异常结构作为 Warning，并继续使用行和、条件数、负值、溢出和色差作安全验收。
- 新增非模态 CCM Color Difference Analysis 窗口，提供 24 块可排序 L/C/H/ΔE 表格、等比例 Lab a*b* 误差向量图及与主预览联动高亮。
- 结果窗口支持选中色块排除/恢复并重新拟合；Calculate、Preview 与 Apply 保持显式分离。
- 新增 7 项 V0.4.39 回归，覆盖 Hue 环绕、曝光解耦、软结构先验、手势优先级、自动 Overlay、状态持久化和分析窗口联动。

## 0.4.38

- CCM 自动页新增 `Detect ColorChecker`，可搜索全图，也可通过“Region Tools”仅在当前 ROI 内搜索。
- 新增 UI 无关的 ColorChecker 检测器：候选凸四边形检测、透视展开、6×4 网格采样、参考色可拟合度、中性灰阶顺序、块内均匀度和颜色多样性联合评分。
- 自动识别横向、竖向、旋转与镜像候选，输出统一为标准 6×4 方向，检测结果不再需要额外 Rotation/Flip。
- 检测只生成四角与 24 块覆盖层，不会计算或应用 CCM；用户必须检查覆盖层后再点击 Calculate CCM。
- 界面显示 Detection Confidence；低于阈值时保留原几何不变，并建议使用 ROI 缩小搜索范围或手动微调。
- 区域相关低频操作收拢到 `Region Tools` 下拉菜单，主页仅保留一个高频自动检测按钮。
- 新增透视色卡、竖向旋转、ROI 全局坐标、非色卡拒绝和 UI 提案不应用参数测试。

## 0.4.37

- CCM 自动页新增紧凑的 ColorChecker 工作流：当前 ROI 外框、4×6 可微调色块、透视四角、方向/Flip、Illuminant、统计方法与手动排除。
- 修复“Use current ROI”没有真正进入 CCM 采样链路、默认坐标被误用的问题。
- 只有带明确 4×6 网格来源的 24 个 ROI 才会当作 ColorChecker 色块，避免将其他 24 个 ROI 误用于拟合。
- 修正 D50/A 光源参考色的白点适应，先经 CAT02 适应到 sRGB D65，中性色块不再因参考数据错误带暖色。
- 色块采样新增质量分数、Inlier 比例与用户排除标记；求解器可自动排除少量明显残差异常块并重新拟合。
- CCM 改为先计算、再显式 Preview/Apply；未通过 ΔE、矩阵稳定性、负值与溢出检查的结果在所有入口均不可应用。
- CCM 拟合前显式校验 BLC、WB、Demosaic 与线性归一化 RGB 数值域，避免将 RGB DN 直接与 0～1 参考色拟合。

## 0.4.36

- 新增 `ImportRequestCoordinator`，抽离 Latest-wins Generation、Future、Poll 与关闭清理。
- 新增结构化 `ImportFailure`、`PreparedImportPayload` 和导入 Payload 合同。
- 导入结果必须与活动请求路径顺序及集合匹配，每个文件恰好产生一个成功或失败结果。
- 单张普通图片与相机 RAW 也迁移到 IO Executor，避免主线程同步解码造成界面停顿。
- 旧导入任务的迟到结果在工作区写入前丢弃，重复导入不会追加错误批次。
- 保留部分成功行为，并统一失败摘要、成功/失败文件计数和 Import Task 性能状态。
- 应用退出时由协调器集中取消 Import Future 与全部 Poll 回调。
- 新增协调器、Payload 路径绑定、部分成功、单图后台导入和 Stale Workspace 隔离测试。

## 0.4.35

- 新增 `AnalysisRequestCoordinator`，抽离分析 Debounce、Generation、Future 所有权、轮询注册和关闭清理。
- 新增 `AnalysisResultApplicationController` 与标准化 Payload，验证 Value 及有限、非负的 Elapsed 时间。
- 主 Analysis Drawer 和独立 Histogram 统一使用 Wait、Stale、Cancelled、Apply 状态决策。
- 修复 Stale Analysis Payload 在 Generation 检查前写入 Render Cache 的问题。
- Histogram Window Cache 改为存储经过验证的标准 Payload，并接入统一 Hit/Miss 统计。
- Performance Monitor 增加 Analysis 与 Histogram 的 Submitted、Completed、Cancelled、Failed、Stale 和 In-flight 指标。
- 应用退出及 Histogram 关闭通过协调器集中取消全部 After/Poll 回调与未开始 Future。
- 新增协调器、决策优先级、Payload 合同、Stale Cache 防污染和 Histogram 关闭测试。

## 0.4.34

- 将旧 `PerformanceMetrics` 升级为线程安全的结构化 Timing、Cache、Memory、Value 和 Counter 快照。
- Timing 增加 Latest、Average、P50、P95、Max 和滚动样本数，状态栏自动指出当前最慢模块。
- Pipeline、Display、Analysis、Workspace Preview 和 YUV Frame 使用统一累计缓存命中率。
- 新增共享 NumPy backing store 去重估算，分别统计当前结果、Runtime Preview、Render/Analysis 和 YUV Cache 内存。
- 新增非模态三页签 `Performance Monitor`，状态栏摘要可直接点击打开，专家模式保持移除。
- 预览请求增加 Submitted、Completed、Cancelled/Superseded、Failed 和 Stale Result 计数及当前 In-flight 状态。
- 修复 Processing Backend 子菜单将“后端状态”错误标成“性能详情”的旧文案问题。
- 新增结构化快照、命中率、共享数组内存、摘要热点和窗口布局测试。

## 0.4.33

- 新增 `PreviewResultApplicationController`，抽离完成 Future 的状态决策和 RAW/YUV Payload 合同验证。
- 明确 wait、stale、cancelled、apply 四类结果，过期与取消路径不再进入通用异常弹窗。
- RAW 结果验证非空 StageResult；YUV 结果验证 Frame、Conversion、Results、Metrics 和必要属性。
- YUV Cache Write Key 成为标准化 Payload 的显式字段，缓存命中不会重复写回。
- 主窗口新增单一 Prepared Payload 应用边界，后续性能统计统一读取已验证 Metrics。
- 新增决策优先级、RAW/YUV 合同、非法 Payload 和缓存授权测试。

## 0.4.32

- 新增 `WorkItemEditableState` 与 `WorkspaceItemStateController`，集中管理工作图可编辑状态复制。
- 主窗口的 `_store_current_work_item` 与激活数据读取迁移到统一状态边界。
- Pipeline、Calibration、Manual Snapshot 使用深拷贝，Loaded Image 保持引用，避免无意义的大图复制。
- 保存状态时保留 Runtime Preview Cache；激活 Payload 与原 Work Item 隔离，防止跨图参数串改。
- Active ROI、Grid 尺寸和 Input Revision 在捕获阶段标准化。
- 新增状态捕获、隔离、缓存保留和主窗口兼容测试。

## 0.4.31

- 新增纯策略 `WorkspacePreviewCachePolicy` 及上下文、查询结果和汇总数据结构。
- 从主窗口抽离 Runtime Preview 有效性判断、单调访问时钟、确定性 LRU 和内存预算淘汰。
- 缓存查询区分 hit、miss、invalid，失效项由策略层立即释放，性能计数由 UI 边界统一记录。
- 当前工作图作为 protected entry；策略优先淘汰其他图，允许不可避免的单图超预算状态。
- 后端切换与手动清理复用统一释放接口，同时保留旧缓存配置属性兼容性。
- 新增策略汇总、容量、预算、protected、lookup、put、clear 和 UI 属性代理测试。

## 0.4.30

- 新增纯状态机 `CanvasGestureCoordinator`，集中管理主画布 Armed/Active/Start/Current 状态。
- 明确 Gray Picker、Compare Divider、Line Profile、ROI 和 Compare Body 的统一优先级。
- 主窗口按下、拖动、释放和光标选择迁移到协调器仲裁，几何计算与渲染行为保持不变。
- 切换图像和关闭应用时统一取消待执行及活动手势，避免跨图拖动状态残留。
- 为旧手势属性提供兼容代理，现有子窗口及调用方无需同步迁移。
- 新增状态机优先级、一次性测量、光标、取消、ROI 集成和兼容属性测试。

## 0.4.29

- 在统一采样层新增 `LineProfile` 与无 UI 依赖的 Bayer/RGB/YUV 沿线绝对码值采样。
- 新增单例非模态 `Line Profile` 窗口，支持 Output 实线、可选 Input 虚线、动态通道和悬停读数。
- 主画布新增显式、一次性的绘线模式；它与 ROI 绘制互斥，并保持 Compare 分割线手势优先。
- 测量线随阶段和参数变化重新采样，切换图像或关闭窗口时清除，且不会触发 ISP 重算。
- 长剖面在 UI 绘制阶段限制为约2048点，完整采样数据与绝对码值不受影响。
- 新增 RGB 越界、Bayer CFA 相位、YUV 原生码值、窗口生命周期和手势冲突回归测试。

## 0.4.28

- 新增 UI 无关的 `ImageCoordinateMapper` 与 `PixelSamplingService`，统一 Bayer/RGB/YUV 坐标和绝对码值解释。
- 新增非模态 `Pixel Inspector`，支持鼠标跟随、5×5/7×7邻域、通道统计、绝对码值网格及最多16个固定点。
- Bayer 邻域保持 R/Gr/Gb/B CFA 相位；RGB 保留负值/溢出计算码值；YUV 使用原生 Y/U/V Source Code。
- 固定点在模块阶段或参数结果变化后重新采样，切换工作图像时安全清空。
- 主状态栏迁移到统一采样服务，保留原有 RAW DN、RGB裁剪前、显示RGB和YUV状态文本契约。
- Pixel Inspector 仅从下拉菜单打开，缩放、平移和采样不会提交 ISP 请求。

## 0.4.27

- 抽离 `PreviewRequestCoordinator`，统一负责主预览的 debounce、Generation、协作取消、Future 生命周期和 Tk 轮询回调。
- 快速连续参数请求保持 latest-wins；旧 Generation 的 Future 不再持续轮询到完成。
- 关闭应用时由控制器一次性取消待提交请求、活动任务和全部预览轮询回调。
- 主窗口保留原有预览状态属性作为兼容代理，避免结构迁移改变 UI 和历史调用方。
- 新增请求合并、显式取消、旧结果拒绝、轮询清理和关闭行为测试。

## 0.4.26

- 建立四种 Bayer Pattern、六个流水线阶段的量化 Golden Output 基线与独立验证命令。
- 性能基准新增 JSON 输出，记录运行环境、后端、冷流水线、CCM 增量刷新及逐模块中位耗时，并修复旧的未定义参数输出错误。
- 新增无 Tk 依赖的 `YUVPreviewController`，将缓存键、帧读取、YUV 转换与阶段构造从主窗口移出。
- 新增 `LanguageController`，集中管理语言选择、回退、UI 状态恢复和偏好持久化。
- 新增 V0.4.26 工程基线和 Controller 回归测试；UI、ISP 参数与输出行为保持不变。

## 0.4.25

- 新增集中式 `isp_tool/i18n` 翻译层，支持简体中文、English、默认语言回退和动态参数插值。
- 顶部菜单新增 `语言 / Language`；运行时更新主菜单、常用工具栏、AWB、状态栏和 Histogram，不提交 ISP 任务。
- 语言选择保存到用户 UI preferences 及 ISP JSON 的 `ui_state.language`。
- AWB 右侧面板删除五种方法的常驻原理文字、RAW Bayer 预览说明和 ROI 坐标长提示，保留必要校验错误。
- 内部继续使用稳定 module ID、method ID 和 Pixel Format，不以翻译后的显示文字执行业务判断。
- 新增 V0.4.25 国际化与 UI 状态保持测试。

## 0.4.24

- 新增 `StageDataState`，明确区分 Bayer RAW DN、Bayer Linear Normalized、RGB DN 和 RGB Linear Normalized，并记录位深、Black/White Level 及 BLC 状态。
- 修复 BLC/LSC 关闭后 DN 数据被当作 0～1 直接裁剪，导致后续 Demosaic/CCM 预览全白、全黑或颜色异常的问题。
- 所有模块关闭时严格保持像素和数值域描述；Demosaic 关闭时 CCM 明确跳过并保留 Bayer Mosaic 最终预览。
- Demosaic 继承输入尺度，CCM Offset 在 DN 路径按 White Level 换算，预览仅做显示映射，Histogram 和悬停读数保持真实绝对值。
- AWB/AE 的当前 UI 分析路径使用显式阶段状态，避免强 LSC/WB 增益输出被误判为 DN。
- 右侧数值参数重构为统一 `ParameterControl`，增强拖动热区、精确输入、step 对齐、键盘微调、复位和最新请求节流。
- 统一增强深色 Combobox 箭头、焦点、悬停、按下与禁用样式。
- 新增五模块 32 种启用组合与参数控件回归测试。

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
