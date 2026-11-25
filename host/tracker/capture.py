"""Captura de uma regiao da tela: dxcam (Windows) com fallback para mss."""
import sys
import numpy as np


class Grabber:
    def __init__(self, region, backend="auto"):
        """region = (left, top, width, height) em pixels da tela."""
        self.left, self.top, self.w, self.h = region
        self._cam = self._sct = None
        self._last = None
        if backend in ("auto", "dxcam") and sys.platform == "win32":
            try:
                import dxcam
                self._cam = dxcam.create(output_color="BGR")
            except Exception:
                if backend == "dxcam":
                    raise
        if self._cam is None:
            import mss
            self._sct = mss.mss()
        self.backend = "dxcam" if self._cam is not None else "mss"

    def grab(self):
        """Imagem BGR (h, w, 3). Com dxcam, repete o ultimo frame se a tela nao mudou."""
        if self._cam is not None:
            f = self._cam.grab(region=(self.left, self.top, self.left + self.w, self.top + self.h))
            if f is not None:
                self._last = f
            return self._last
        shot = self._sct.grab({"left": self.left, "top": self.top, "width": self.w, "height": self.h})
        return np.asarray(shot)[..., :3]
