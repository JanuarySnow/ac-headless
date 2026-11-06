import os
import struct
import sys

EXE_NAME = "acs.exe"


class ReadError(Exception):
    pass


class _Reader:
    def read(self, addr, n):
        raise NotImplementedError

    def u64(self, addr):
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def i32(self, addr):
        return struct.unpack("<i", self.read(addr, 4))[0]

    def u8(self, addr):
        return self.read(addr, 1)[0]

    def f32(self, addr):
        return struct.unpack("<f", self.read(addr, 4))[0]

    def f64(self, addr):
        return struct.unpack("<d", self.read(addr, 8))[0]

    def vec3(self, addr):
        return struct.unpack("<3f", self.read(addr, 12))


class ProcReader(_Reader):
    def __init__(self, pid):
        self.pid = pid
        try:
            self.fh = open("/proc/%d/mem" % pid, "rb", 0)
        except OSError as e:
            raise ReadError(
                "cannot open /proc/%d/mem (%s). Only the run that started the game can read it, "
                "unless kernel.yama.ptrace_scope is 0 or you are root" % (pid, e))
        self.base = linux_image_base(pid)

    def read(self, addr, n):
        try:
            self.fh.seek(addr)
            data = self.fh.read(n)
        except (OSError, OverflowError, ValueError) as e:
            raise ReadError("read 0x%x failed: %s" % (addr, e))
        if len(data) != n:
            raise ReadError("short read at 0x%x" % addr)
        return data

    def close(self):
        self.fh.close()


def linux_image_base(pid):
    best = None
    try:
        with open("/proc/%d/maps" % pid) as fh:
            for line in fh:
                parts = line.split(None, 5)
                if len(parts) == 6 and parts[5].strip().lower().endswith("/" + EXE_NAME):
                    start = int(parts[0].split("-")[0], 16)
                    if int(parts[2], 16) == 0 and (best is None or start < best):
                        best = start
    except OSError:
        pass
    return best if best is not None else 0x140000000


def linux_pids(parent=None, marker=None):
    out = []
    needle = marker.encode() if marker else None
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % name) as fh:
                if fh.read().strip() != EXE_NAME:
                    continue
        except OSError:
            continue
        pid = int(name)
        if needle is not None:
            try:
                with open("/proc/%s/environ" % name, "rb") as fh:
                    if needle in fh.read().split(b"\0"):
                        out.append(pid)
            except OSError:
                pass
        elif parent is None or _descends(pid, parent):
            out.append(pid)
    return sorted(out)


def _descends(pid, ancestor):
    seen = 0
    while pid > 1 and seen < 64:
        if pid == ancestor:
            return True
        try:
            with open("/proc/%d/stat" % pid) as fh:
                pid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            return False
        seen += 1
    return pid == ancestor


class WinReader(_Reader):
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes as W
        self.ctypes = ctypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.k32.OpenProcess.restype = W.HANDLE
        self.k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k32.ReadProcessMemory.argtypes = [W.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.k32.CloseHandle.argtypes = [W.HANDLE]
        self.pid = pid
        self.handle = self.k32.OpenProcess(0x0410, False, pid)
        if not self.handle:
            raise ReadError("OpenProcess(%d) failed: %d" % (pid, ctypes.get_last_error()))
        self.base = self._base()

    def _base(self):
        ctypes = self.ctypes
        from ctypes import wintypes as W
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.EnumProcessModulesEx.argtypes = [W.HANDLE, ctypes.POINTER(ctypes.c_void_p),
                                               W.DWORD, ctypes.POINTER(W.DWORD), W.DWORD]
        mods = (ctypes.c_void_p * 1)()
        need = W.DWORD(0)
        if not psapi.EnumProcessModulesEx(self.handle, mods, ctypes.sizeof(mods),
                                          ctypes.byref(need), 0x03):
            raise ReadError("EnumProcessModulesEx failed: %d" % ctypes.get_last_error())
        return mods[0]

    def read(self, addr, n):
        ctypes = self.ctypes
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t(0)
        if not self.k32.ReadProcessMemory(self.handle, ctypes.c_void_p(addr), buf, n,
                                          ctypes.byref(got)) or got.value != n:
            raise ReadError("read 0x%x failed" % addr)
        return buf.raw

    def close(self):
        self.k32.CloseHandle(self.handle)


def windows_pids():
    import ctypes
    from ctypes import wintypes as W

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", W.DWORD),
                    ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    entry = ENTRY()
    entry.dwSize = ctypes.sizeof(ENTRY)
    out = []
    ok = k32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        if entry.szExeFile.lower() == EXE_NAME:
            out.append(entry.th32ProcessID)
        ok = k32.Process32NextW(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    return sorted(out)


def find_pids(parent=None):
    if sys.platform == "win32":
        return windows_pids()
    return linux_pids(parent)


def open_process(pid):
    if sys.platform == "win32":
        return WinReader(pid)
    return ProcReader(pid)
