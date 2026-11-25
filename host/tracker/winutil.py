"""Posicao do cursor e retangulo da janela do app de teste (Win32, via ctypes)."""
import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    def set_dpi_aware():
        """Sem isso, com escala de tela != 100%, as coordenadas nao batem com os pixels capturados."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            _user32.SetProcessDPIAware()

    def cursor_pos():
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def window_client_rect(title):
        """(left, top, width, height) da area cliente, em coordenadas da tela; None se nao achar."""
        hwnd = _user32.FindWindowW(None, title)
        if not hwnd:
            return None
        rc = wintypes.RECT()
        _user32.GetClientRect(hwnd, ctypes.byref(rc))
        pt = wintypes.POINT(0, 0)
        _user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top
else:
    def set_dpi_aware():
        pass

    def cursor_pos():
        raise RuntimeError("leitura do cursor implementada so para Windows (GetCursorPos)")

    def window_client_rect(title):
        return None
