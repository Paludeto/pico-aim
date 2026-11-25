"""Protocolo PC <-> MCU sobre USB CDC. Espelha firmware/src/proto/proto.h e
firmware/src/ctrl/params.h.

  A5 5A | TIPO | LEN | PAYLOAD | CRC8(TIPO .. PAYLOAD)
"""
import struct

SYNC = b"\xA5\x5A"

T_MEAS, T_SET_PARAM, T_SET_MODE, T_SAVE, T_LOAD, T_GET_PARAMS = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06
T_TELEM, T_ACK, T_PARAMS = 0x80, 0x81, 0x82

MEAS_VALID = 0x01
RX_MAX_PAYLOAD = 8                      # maior payload que o MCU aceita

# flags da telemetria (CTRL_FL_*)
FL_ENABLED, FL_LINK_OK, FL_TARGET, FL_EST_ON, FL_IDENT_DONE, FL_SATURATED = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20

MODE_OFF, MODE_AUTO, MODE_IDENT = 0, 1, 2
STATE_NAMES = ("DESLIGADO", "AUTOMATICO", "IDENTIFICACAO")

# ids dos parametros (params.h); todos viajam como int32
P_KP, P_KI, P_KD, P_LATENCY, P_DEADBAND, P_D_SHIFT, P_ID_AMP, P_PLANT_GAIN, P_EST_EN = range(1, 10)
PARAM_COUNT = 9
PARAM_NAMES = ("kp", "ki", "kd", "latency", "deadband", "d_shift", "id_amp", "plant_gain", "est_en")

ERR_OK, ERR_TYPE, ERR_LEN, ERR_PARAM_ID, ERR_RANGE, ERR_MODE, ERR_STATE, ERR_STORAGE = range(8)
ERR_NAMES = ("ok", "tipo desconhecido", "tamanho errado", "parametro inexistente", "valor fora da faixa",
             "modo invalido", "so no estado DESLIGADO", "flash sem dados validos / falha na gravacao")

CTRL_HZ = 1000
WINDOW_TITLE = "Rastreador - app de teste"
TARGET_COLOR = (255, 0, 255)        # RGB, magenta
TARGET_RADIUS = 18

_TELEM = struct.Struct("<IHBBhhhhhhHBBHH")      # payload do TELEM (28 bytes)
_PARAMS = struct.Struct("<%di" % PARAM_COUNT)
TELEM_LEN = _TELEM.size + 5


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def frame(ftype: int, payload: bytes = b"") -> bytes:
    body = bytes([ftype, len(payload)]) + payload
    return SYNC + body + bytes([crc8(body)])


def _clamp16(v) -> int:
    return max(-32768, min(32767, int(round(v))))


def pack_meas(seq: int, ex, ey, valid: bool = True) -> bytes:
    return frame(T_MEAS, struct.pack("<BBhh", seq & 0xFF, MEAS_VALID if valid else 0, _clamp16(ex), _clamp16(ey)))


def pack_set_param(param: int, value: int) -> bytes:
    return frame(T_SET_PARAM, struct.pack("<Bi", param & 0xFF, max(-2 ** 31, min(2 ** 31 - 1, int(value)))))


def pack_set_mode(mode: int) -> bytes:
    return frame(T_SET_MODE, bytes([mode & 0xFF]))


def pack_save() -> bytes:
    return frame(T_SAVE)


def pack_load() -> bytes:
    return frame(T_LOAD)


def pack_get_params() -> bytes:
    return frame(T_GET_PARAMS)


# ---- conversao entre unidades fisicas e o valor int32 de cada parametro ----
def q16(x: float) -> int:
    return int(round(x * 65536.0))


def to_raw(param: int, value: float) -> int:
    """Kp [contagens/px], Ki [1/s], Kd [s], ganho da planta [px/contagem] -> Q16.16 por amostra."""
    if param == P_KP or param == P_PLANT_GAIN:
        return q16(value)
    if param == P_KI:
        return q16(value / CTRL_HZ)
    if param == P_KD:
        return q16(value * CTRL_HZ)
    return int(round(value))


def from_raw(param: int, raw: int) -> float:
    if param == P_KP or param == P_PLANT_GAIN:
        return raw / 65536.0
    if param == P_KI:
        return raw / 65536.0 * CTRL_HZ
    if param == P_KD:
        return raw / 65536.0 / CTRL_HZ
    return raw


def unpack_params(payload: bytes) -> dict:
    """PARAMS -> {nome: valor em unidade fisica}."""
    raw = _PARAMS.unpack(payload)
    return {PARAM_NAMES[i]: from_raw(i + 1, raw[i]) for i in range(PARAM_COUNT)}


TELEM_FIELDS = ("t_us", "tick", "state", "enabled", "link_ok", "target_valid", "est_on", "ident_done",
                "saturated", "em_x", "em_y", "eh_x", "eh_y", "u_x", "u_y", "errs", "hid_drop", "meas_age",
                "load0", "load1")


def unpack_telem(payload: bytes) -> dict:
    (t_us, tick, state, fl, emx, emy, ehx, ehy, ux, uy, errs, drop, age, load0, load1) = _TELEM.unpack(payload)
    return {
        "t_us": t_us, "tick": tick, "state": state,
        "enabled": int(bool(fl & FL_ENABLED)), "link_ok": int(bool(fl & FL_LINK_OK)),
        "target_valid": int(bool(fl & FL_TARGET)), "est_on": int(bool(fl & FL_EST_ON)),
        "ident_done": int(bool(fl & FL_IDENT_DONE)), "saturated": int(bool(fl & FL_SATURATED)),
        "em_x": emx, "em_y": emy, "eh_x": ehx, "eh_y": ehy, "u_x": ux, "u_y": uy,
        "errs": errs, "hid_drop": drop, "meas_age": age,
        "load0": load0 / 10.0, "load1": load1 / 10.0,       # carga dos nucleos, em %
    }


class FrameParser:
    """Extrai quadros (tipo, payload) de um fluxo de bytes; ressincroniza no SYNC."""

    MAX_PAYLOAD = 64

    def __init__(self):
        self.buf = bytearray()
        self.crc_errors = 0

    def feed(self, data: bytes) -> list:
        self.buf += data
        out = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                del self.buf[:max(0, len(self.buf) - 1)]
                break
            if i:
                del self.buf[:i]
            if len(self.buf) < 4:
                break
            n = self.buf[3]
            if n > self.MAX_PAYLOAD:
                del self.buf[:1]
                continue
            if len(self.buf) < n + 5:
                break
            if crc8(bytes(self.buf[2:4 + n])) == self.buf[4 + n]:
                out.append((self.buf[2], bytes(self.buf[4:4 + n])))
                del self.buf[:n + 5]
            else:
                self.crc_errors += 1
                del self.buf[:1]
        return out


def telem_rows(frames) -> list:
    """Filtra e decodifica os quadros de telemetria de uma lista (tipo, payload)."""
    return [unpack_telem(p) for t, p in frames if t == T_TELEM and len(p) == _TELEM.size]
