# -*- coding: utf-8 -*-
"""用纯 ctypes 创建 Windows 快捷方式（无需 pywin32 / COM 脚本）"""
import ctypes
import os
import re
import struct
from ctypes import wintypes

HRESULT = ctypes.HRESULT

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

def parse_guid(s):
    """'{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}' -> GUID 结构"""
    m = re.match(r"\{?([0-9A-Fa-f]{8})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{12})\}?", s)
    if not m: raise ValueError(f"bad GUID: {s}")
    g = GUID()
    g.Data1 = int(m.group(1), 16)
    g.Data2 = int(m.group(2), 16)
    g.Data3 = int(m.group(3), 16)
    for i, byte in enumerate(bytes.fromhex(m.group(4) + m.group(5))):
        g.Data4[i] = byte
    return g

CLSID_ShellLink  = parse_guid("{00021401-0000-0000-C000-000000000046}")
IID_IShellLinkW  = parse_guid("{000214F9-0000-0000-C000-000000000046}")
IID_IPersistFile = parse_guid("{0000010B-0000-0000-C000-000000000046}")
CLSCTX_INPROC_SERVER = 1

# vtable 索引
ISL_QueryInterface = 0
ISL_SetPath = 20
ISL_SetWorkingDirectory = 9
ISL_SetDescription = 7
ISL_SetIconLocation = 17
IPF_Save = 6

class IShellLinkW(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.c_void_p)]

class IPersistFile(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.c_void_p)]

def make_shortcut(lnk_path, target, work_dir, icon, desc):
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        ppv = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_IShellLinkW), ctypes.byref(ppv)
        )
        if hr != 0: raise OSError(f"CoCreateInstance failed: 0x{hr & 0xFFFFFFFF:08X}")

        pLink = ctypes.cast(ppv, ctypes.POINTER(IShellLinkW))
        vtbl = ctypes.cast(pLink.contents.lpVtbl, ctypes.POINTER(ctypes.c_void_p))

        # QueryInterface -> IPersistFile
        ppf = ctypes.c_void_p()
        qi = ctypes.WINFUNCTYPE(HRESULT, ctypes.POINTER(IShellLinkW),
                                 ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(vtbl[ISL_QueryInterface])
        hr = qi(pLink, ctypes.byref(IID_IPersistFile), ctypes.byref(ppf))
        if hr != 0: raise OSError(f"QueryInterface failed: 0x{hr & 0xFFFFFFFF:08X}")

        # 调 IShellLinkW 的方法
        set_path = ctypes.WINFUNCTYPE(HRESULT, ctypes.POINTER(IShellLinkW), wintypes.LPCWSTR)(vtbl[ISL_SetPath])
        set_dir  = ctypes.WINFUNCTYPE(HRESULT, ctypes.POINTER(IShellLinkW), wintypes.LPCWSTR)(vtbl[ISL_SetWorkingDirectory])
        set_desc = ctypes.WINFUNCTYPE(HRESULT, ctypes.POINTER(IShellLinkW), wintypes.LPCWSTR)(vtbl[ISL_SetDescription])
        set_icon = ctypes.WINFUNCTYPE(HRESULT, ctypes.POINTER(IShellLinkW), wintypes.LPCWSTR, ctypes.c_int)(vtbl[ISL_SetIconLocation])
        set_path(pLink, target)
        set_dir(pLink, work_dir)
        set_desc(pLink, desc)
        set_icon(pLink, icon, 0)

        # IPersistFile::Save
        pPF = ctypes.cast(ppf, ctypes.POINTER(IPersistFile))
        pfVtbl = ctypes.cast(pPF.contents.lpVtbl, ctypes.POINTER(ctypes.c_void_p))
        save = ctypes.WINFUNCTYPE(HRESULT, ctypes.POINTER(IPersistFile), wintypes.LPCWSTR, wintypes.BOOL)(pfVtbl[IPF_Save])
        hr = save(pPF, lnk_path, True)
        if hr != 0: raise OSError(f"Save failed: 0x{hr & 0xFFFFFFFF:08X}")
    finally:
        ole32.CoUninitialize()

if __name__ == "__main__":
    desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
    make_shortcut(
        os.path.join(desktop, "我的图书馆.lnk"),
        r"G:\my-library\start.bat",
        r"G:\my-library",
        r"G:\my-library\library.ico",
        "个人电子图书馆"
    )
    print("OK:", os.path.join(desktop, "我的图书馆.lnk"))
