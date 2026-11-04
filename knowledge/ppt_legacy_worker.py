"""旧版PPT隔离转换进程；只输出临时PPTX，不修改原文件。"""
from __future__ import annotations

import sys
from pathlib import Path


def convert(source: Path, target: Path) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = presentation = None
    previous_security = previous_alerts = None
    was_empty = False
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        was_empty = app.Presentations.Count == 0
        previous_security = app.AutomationSecurity
        previous_alerts = app.DisplayAlerts
        # 不能依赖用户的Office设置；任何上传文件都禁用宏、只读且不显示文档窗口。
        app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        app.DisplayAlerts = 1       # ppAlertsNone
        presentation = app.Presentations.Open(str(source.resolve()), True, False, False)
        presentation.SaveAs(str(target.resolve()), 24)  # ppSaveAsOpenXMLPresentation
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                pass
        if app is not None:
            try:
                if previous_security is not None:
                    app.AutomationSecurity = previous_security
                if previous_alerts is not None:
                    app.DisplayAlerts = previous_alerts
                # 不关闭用户已经打开的其他演示文稿。
                if was_empty and app.Presentations.Count == 0:
                    app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    try:
        convert(Path(sys.argv[1]), Path(sys.argv[2]))
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
