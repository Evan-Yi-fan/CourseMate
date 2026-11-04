# PPT课件支持验收

上传入口、后端校验和解析分发均接受PPTX/PPT。新依赖python-pptx 1.0.2和Windows条件依赖pywin32 311已加入requirements.txt，本机锁定清单已刷新。

PPTX直接提取每张幻灯片的文本框、组合图形、表格、常见图表标签与数值以及讲者备注。按演示顺序枚举，不按内部XML文件名排序；空白页不入库，但其后的来源页码不前移。现有分块、课程隔离、同名替换、问答引用及出题流程均复用。

旧版PPT验证OLE头，在独立Python子进程调用本机PowerPoint，以只读、禁用宏、不显示文稿窗口的方式转换到临时PPTX，不修改原文件；等待限制60秒，出错提供另存PPTX的操作提示。正常完成后关闭本次文稿，不关闭用户其他已打开文稿。仅在应用初始为空、且结束后仍无其他文稿时退出PowerPoint。

此兼容路径需要Windows、本机可用的PowerPoint及pywin32。PPTX本身不需要Office；其他机器可先将旧版PPT另存为PPTX。没有OCR，图片内容及复杂SmartArt中的文字不保证提取；没有宣称读取图片中的公式或示意图。

新增12项测试覆盖页序、空白页、文本/表格/组合/备注/图表、合并单元格去重、损坏与空文件、大小写扩展名、两种上传类型、误改后缀、转换失败及超时、完整入库检索和同名替换。全量111项Python测试通过。

另外使用本机PowerPoint生成139264字节的真实旧版.ppt，实际验证解析页码为1、3、原文件名保留、SQLite状态为ready、向量检索可返回第三张幻灯片。测试使用临时课程与hash向量，不修改真实课程，也不调用付费模型。临时课件保存在已忽略的.handoff-work目录。

官方参考：
- https://python-pptx.readthedocs.io/en/latest/api/slides.html
- https://learn.microsoft.com/en-us/office/vba/api/powerpoint.application.automationsecurity
- https://learn.microsoft.com/en-us/office/vba/api/powerpoint.presentation.saveas
