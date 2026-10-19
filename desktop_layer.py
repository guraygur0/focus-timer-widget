"""Keep our top-level, DPI-aware widget immediately above Explorer's desktop.

No cross-process parenting, shell injection, keyboard hooks or wallpaper changes.
Explorer can reorder its desktop during Win+D; follow that window without focus.
Win32 reference: https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwindowpos
"""
import ctypes
from ctypes import wintypes


class DesktopLayer:
    def __init__(self, widget):
        self.widget=widget
        self.u=ctypes.WinDLL('user32',use_last_error=True)
        for name,args,result in [
            ('FindWindowW',[wintypes.LPCWSTR,wintypes.LPCWSTR],wintypes.HWND),
            ('FindWindowExW',[wintypes.HWND,wintypes.HWND,wintypes.LPCWSTR,wintypes.LPCWSTR],wintypes.HWND),
            ('GetWindow',[wintypes.HWND,wintypes.UINT],wintypes.HWND),
            ('GetWindowRect',[wintypes.HWND,ctypes.POINTER(wintypes.RECT)],wintypes.BOOL),
            ('GetWindowLongPtrW',[wintypes.HWND,ctypes.c_int],ctypes.c_ssize_t),
            ('IsWindow',[wintypes.HWND],wintypes.BOOL),
            ('IsWindowVisible',[wintypes.HWND],wintypes.BOOL),
            ('IsIconic',[wintypes.HWND],wintypes.BOOL),
            ('ShowWindow',[wintypes.HWND,ctypes.c_int],wintypes.BOOL),
            ('SetWindowPos',[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT],wintypes.BOOL),
        ]:
            fn=getattr(self.u,name)
            fn.argtypes=args
            fn.restype=result
        self.desktop=None
        self.last_error=0

    def find_desktop(self):
        # Wallpaper applications can put a visible WorkerW ABOVE Progman.
        # Re-enumerate: Explorer/wallpaper may recreate or reorder this layer.
        after = None
        while True:
            after = self.u.FindWindowExW(None, after, 'WorkerW', None)
            if not after:
                break
            rect = wintypes.RECT()
            if (self.u.IsWindowVisible(after) and self.u.GetWindowRect(after, ctypes.byref(rect))
                    and rect.right-rect.left >= 300 and rect.bottom-rect.top >= 300):
                self.desktop = after
                return after
        shell = self.u.FindWindowW('Progman', None)
        self.desktop = shell
        return shell

    def maintain(self):
        if self.widget.options.get('topmost',False):
            return
        desktop=self.find_desktop()
        if not desktop or not self.u.IsWindowVisible(desktop):
            return
        hwnd=int(self.widget.winId())
        if self.u.IsIconic(hwnd) or not self.u.IsWindowVisible(hwnd):
            self.u.ShowWindow(hwnd,4)  # SW_SHOWNOACTIVATE: never steal keyboard focus.
        previous=self.u.GetWindow(desktop,3)  # GW_HWNDPREV (immediately above).
        if previous==hwnd:
            return
        # Drop a temporary topmost bit acquired while Explorer was showing desktop.
        if self.u.GetWindowLongPtrW(hwnd,-20) & 8 and not self.u.GetWindowLongPtrW(desktop,-20) & 8:
            self.u.SetWindowPos(hwnd,wintypes.HWND(-2),0,0,0,0,0x13)
            previous=self.u.GetWindow(desktop,3)
            if previous==hwnd:
                return
        ok=self.u.SetWindowPos(hwnd,previous or None,0,0,0,0,0x0013 | 0x0040)
        self.last_error=0 if ok else ctypes.get_last_error()

    def status(self):
        desktop=self.find_desktop()
        hwnd=int(self.widget.winId())
        return {'desktop_host':int(desktop or 0), 'widget_handle':hwnd,
                'directly_above_desktop':bool(desktop and self.u.GetWindow(desktop,3)==hwnd),
                'visible':bool(self.u.IsWindowVisible(hwnd)),
                'minimized':bool(self.u.IsIconic(hwnd)), 'last_error':self.last_error}
