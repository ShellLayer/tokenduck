"""当前 Windows 用户专用的凭证存储；磁盘上只写 DPAPI 密文。"""

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import tempfile
import threading


# Stable on-disk format and lock names preserve existing encrypted sessions.
MAGIC = b"CodexBar-DPAPI-v1\0"
MAX_SIZE = 2 * 1024 * 1024


class CredentialStoreError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, protect):
    if os.name != "nt":
        raise CredentialStoreError("凭证加密需要 Windows 当前用户环境")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    func.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                     ctypes.POINTER(_Blob)]
    func.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(data)
    incoming = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN；不使用 LOCAL_MACHINE，保持用户范围保护。
        if not func(ctypes.byref(incoming), None, None, None, None, 1,
                    ctypes.byref(outgoing)):
            raise CredentialStoreError("Windows 无法%s本地凭证（错误 %s）；原文件未覆盖" %
                                       ("加密" if protect else "解密", ctypes.get_last_error()))
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.memset(buffer, 0, len(data))
        if outgoing.data:
            ctypes.memset(outgoing.data, 0, outgoing.size)
            kernel32.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))


def protect_bytes(data):
    return _crypt(data, True)


def unprotect_bytes(data):
    return _crypt(data, False)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


class CredentialStore:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self._lock = threading.RLock()

    @contextmanager
    def _exclusive(self):
        with self._lock:
            # 同时保护程序、--once 和连接窗口之间的读改写。
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            name = "Local\\CodexBarCredentials_" + hashlib.sha256(
                self.path.casefold().encode("utf-8")).hexdigest()[:24]
            handle = kernel.CreateMutexW(None, False, name)
            if not handle:
                raise CredentialStoreError("本地凭证暂时无法访问")
            owned = False
            try:
                result = kernel.WaitForSingleObject(handle, 10000)
                if result not in (0, 0x80):
                    raise CredentialStoreError("另一个连接操作正在使用本地凭证，请稍后重试")
                owned = True
                yield
            finally:
                if owned:
                    kernel.ReleaseMutex(handle)
                kernel.CloseHandle(handle)

    def _load(self):
        try:
            with open(self.path, "rb") as f:
                blob = f.read(MAX_SIZE + 1)
        except FileNotFoundError:
            return {}
        except OSError:
            raise CredentialStoreError("无法读取本地凭证；原文件未覆盖")
        if len(blob) > MAX_SIZE or not blob.startswith(MAGIC):
            raise CredentialStoreError("本地凭证格式异常；原文件未覆盖")
        try:
            envelope = json.loads(unprotect_bytes(blob[len(MAGIC):]))
            values = envelope["values"]
            digest = hashlib.sha256(_canonical(values)).hexdigest()
            if (envelope.get("version") != 1 or not isinstance(values, dict) or
                    not hmac.compare_digest(digest, envelope["digest"])):
                raise ValueError("invalid envelope")
            return values
        except CredentialStoreError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise CredentialStoreError("本地凭证校验失败；原文件未覆盖")

    def _write(self, values):
        digest = hashlib.sha256(_canonical(values)).hexdigest()
        encrypted = MAGIC + protect_bytes(_canonical(
            {"version": 1, "values": values, "digest": digest}))
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".accounts-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(encrypted)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise CredentialStoreError("保存本地加密凭证失败；请重试连接")
        finally:
            try:
                os.remove(temporary)
            except OSError:
                pass

    def get(self, key, default=None):
        with self._exclusive():
            return self._load().get(key, default)

    def update(self, changes=None, remove=()):
        with self._exclusive():
            values = self._load()
            values.update(changes or {})
            for key in remove:
                values.pop(key, None)
            self._write(values)

    def migrate_json(self, source, key, extra=None):
        """加密写入并读回校验后才移除旧文件；冲突时保留原文件。"""
        if not os.path.isfile(source):
            return False
        with self._exclusive():
            try:
                with open(source, "r", encoding="utf-8-sig") as f:
                    legacy = json.load(f)
            except (OSError, ValueError):
                raise CredentialStoreError("旧凭证无法读取，未修改原文件")
            if not isinstance(legacy, dict) or not isinstance(legacy.get("access_token"), str):
                raise CredentialStoreError("旧凭证格式异常，未修改原文件")
            values = self._load()
            if key in values and values[key] != legacy:
                raise CredentialStoreError("新旧凭证不一致，未覆盖任何账号；请检查旧凭证文件")
            values[key] = legacy
            for name, value in (extra or {}).items():
                values.setdefault(name, value)
            self._write(values)
            if self._load().get(key) != legacy:
                raise CredentialStoreError("凭证迁移校验失败，已保留原文件")
            os.remove(source)
            return True
