# Architecture and Experimental Results

*[Versão em Português](../arquitetura.md)*

This document summarizes the RP2040 firmware architecture, composite USB interface, binary communication protocol, fixed-point controller design, and hardware bench measurements.

## 1. Dual-Core Partitioning on the RP2040

The control (`ctrl/`), protocol (`proto/`), and state-machine (`app/app.c`) modules are written in portable C11 with no Pico SDK dependencies, allowing native compilation on the host PC for unit testing. Hardware-specific code is isolated in `main.c`, `usb/`, `core1/`, `ui/`, and `app/persist.c`.

```text
CORE 0 (main.c)                                   CORE 1 (core1/core1.c)
 tud_task()                                        Hardware alarm IRQ (1 kHz):
 CDC RX -> parser -> app_on_frame                    cmd queue  -> params, mode, enable
   MEAS ----------------- meas queue (4) --------->  meas queue -> latency estimator
   config --------------- cmd queue  (2) --------->  PID / identification / failsafe
 pend_x, pend_y <-------- u queue    (16) ---------  u (enqueued only when != 0)
   -> tud_hid_mouse_report() when ready
 TELEM via CDC <--------- telem queue (8) ---------  decimated telemetry (200 Hz)
 BOOTSEL, LED, state machine, watchdog              main loop: __wfi()
```

- **Core 0:** sole owner of TinyUSB (which is not thread-safe across cores); manages parameters, mode, enable state, `BOOTSEL`, LED patterns, flash persistence, and pending HID accumulation (up to ±32,767 counts per axis) if the host delays HID polling.
- **Core 1:** executes only `ctrl_loop_step()` inside the 1 kHz hardware-alarm ISR, rearmed by absolute timestamp (`delayed_by_us`) to prevent cumulative drift.
- **Non-blocking queues:** inter-core messaging uses Pico SDK `queue_t` exclusively via `try_add`/`try_remove`. If `q_u` is full, that step's output is dropped and counted in `hid_drop`.
- **Full RAM execution (`copy_to_ram`):** the entire executable is copied into SRAM at boot. This allows Core 0 to sample `BOOTSEL` (which momentarily releases QSPI flash CS) without stalling Core 1's 1 kHz ISR. Flash writes (`SAVE`) are allowed only in `OFF` mode with Core 1 paused via `multicore_lockout`.
- **Watchdog and debug pins:** a 1 s hardware watchdog is fed by Core 0 only when Core 1's step counter (`beat`) advances. `GP2` (high during the control ISR) and `GP3` (toggled on each HID report) are exposed for oscilloscope probing.

## 2. Composite USB and CDC Binary Protocol

The RP2040 enumerates as a *Miscellaneous / IAD* composite device (`VID:PID 1209:0001`):

- **CDC-ACM (interfaces 0 and 1):** virtual serial link for measurements, configuration, and telemetry (endpoints `0x81`, `0x02`, `0x82`).
- **HID Mouse (interface 2):** standard relative mouse (`TUD_HID_REPORT_DESC_MOUSE()`, endpoint `0x83`, `bInterval = 1 ms`).

All CDC frames are little-endian and protected by CRC-8 (polynomial `0x07`):

```text
0xA5 0x5A | TYPE (1 B) | LEN (1 B) | PAYLOAD (LEN B) | CRC8(TYPE .. PAYLOAD)
```

| Code | Frame | Direction | Payload |
|---|---|---|---|
| `0x01` | `MEAS` | PC → MCU | `SEQ` (u8), `FLAGS` (u8, bit 0 = valid target), `EX` (i16), `EY` (i16) |
| `0x02` | `SET_PARAM` | PC → MCU | `ID` (u8), `VALUE` (i32) |
| `0x03` | `SET_MODE` | PC → MCU | `MODE` (u8: `0` OFF, `1` AUTO, `2` IDENT) |
| `0x04`–`0x06` | `SAVE` / `LOAD` / `GET_PARAMS` | PC → MCU | Empty |
| `0x80` | `TELEM` (200 Hz) | MCU → PC | `t_us`, `tick`, state, flags, `em`, `eh`, `Σu`, `errs`, `hid_drop`, `meas_age`, core loads 0/1 |
| `0x81` | `ACK` / `NACK` | MCU → PC | Source type (u8) and error code (u8; `0` = ok) |
| `0x82` | `PARAMS` | MCU → PC | Array of 9 parameters as `i32` |

| ID | Parameter | Format | Valid Range | Default |
|---|---|---|---|---|
| 1 | $K_p$ | Q16.16 counts/px | $0 \le K_p < 16$ | 0.06 |
| 2 | $K_i \cdot T$ | Q16.16 per sample | $0 \le K_i T < 16$ | 0 |
| 3 | $K_d / T$ | Q16.16 per sample | $0 \le K_d / T < 16$ | 0 |
| 4 | Latency $L$ | 1 ms steps | 0 to 127 | 30 |
| 5 | Deadband | px | 0 to 100 | 1 |
| 6 | Derivative filter | $n$ ($\alpha = 2^{-n}$) | 0 to 8 | 3 |
| 7 | Identification amplitude | HID counts | 1 to 20 | 1 |
| 8 | Plant gain $g$ | Q16.16 px/count | 0.125 to 8.0 | 1.0 |
| 9 | Estimator enable | Boolean | 0 or 1 | 1 |

**Safety & state machine:** mode (CDC) and physical enable (`BOOTSEL`) are independent; HID motion requires both. Missing valid `MEAS` packets for 100 ms triggers the failsafe (zeros output and integrator, LED blinks at 5 Hz). Invalid-target flags zero output while freezing the integrator. A 1 s `BOOTSEL` hold or USB suspend/disconnect immediately disables everything.

## 3. Fixed-Point Controller and Multirate Estimator

The HID-to-cursor path behaves as a pure integrator with gain $g$ (px/count) and transport delay $L$. Because vision runs at ~60 Hz while control runs at 1 kHz, feeding raw measurements directly causes the controller to integrate the same stale error for ~17 consecutive steps, leading to overshoot or instability.

Each axis maintains a 128-entry circular buffer of emitted commands (a Smith predictor specialized for an integrating plant):

1. When a new measurement $e_m$ arrives, the last $L$ in-flight commands are subtracted:
   $$\hat{e}[k] = e_m - g \sum_{i=1}^{L} u[k - i]$$
2. On every subsequent 1 ms tick, each emitted command is immediately subtracted from $\hat{e}$:
   $$\hat{e}[k+1] = \hat{e}[k] - g \cdot u[k]$$

Over $\hat{e}$ (clamped to $\pm 2047$ px), the discrete PID operates purely in `Q16.16` integer arithmetic (zero runtime `float`), featuring an exponential derivative filter, $\pm 127$ saturation, clamping anti-windup, fractional residue accumulation, and a configurable deadband.

## 4. Experimental Bench Measurements

Collected on a Raspberry Pi Pico with Windows 11, `mss 9.0.1` capture at 60 Hz over the 3D Shooter interface, pointer acceleration off, and pointer speed 6/11 (raw CSVs in [`docs/medicoes/`](../medicoes/)).

**Open-loop identification (`ident_telem.csv`, $\pm A$ steps + PRBS7):**
- X axis: $g = 1.250\ \text{px/count}$, $L = 6.25\ \text{ms}$, residual $0.87\ \text{px}$ (244 measurements).
- Y axis: $g = 1.250\ \text{px/count}$, $L = 6.00\ \text{ms}$, residual $0.86\ \text{px}$ (244 measurements).

The low internal latency ($L \approx 6\ \text{ms}$) results from reading the cursor directly via `GetCursorPos`: with a stationary target during identification, only the MCU → HID → OS path enters $L$.

**Closed-loop tracking ($K_p = 0.06$, $L = 6$, $g = 1.25$, estimator enabled):**

| Phase | Valid target | Overshoot | Settling (2%) | Steady-state / RMS | Delay | `hid_drop` / `errs` |
|---|---|---|---|---|---|---|
| 500 px Step (`step_trim.csv`) | 100.0% (2662/2662) | 0.0% | 86 ms (max 97 ms) | 0.9 px | — | 0 / 0 |
| 0.5 Hz Sine (`sine_trim.csv`) | 100.0% (2386/2386) | — | — | 31.3 px (RMS) | 47 ms | 0 / 0 |
| 300 px/s Ramp (`ramp_trim.csv`) | 100.0% (2386/2386) | — | — | 14.6 px (RMS) | 48 ms | 0 / 0 |
| Smooth Random (`smooth_trim.csv`) | 100.0% (2387/2387) | — | — | 22.0 px (RMS) | 45 ms | 0 / 0 |

**Firmware operational metrics:** average control period `1000.00 µs`, Core 1 load `0.4%–0.9%` (~4–9 µs per ISR), Core 0 load up to `4.4%`, flash-write pause `~24 ms` (`OFF` state only), and link-loss failsafe trip at `100–103 ms`. All 2,165 native C unit assertions in `host/tests/test_ctrl.c` pass with zero failures.
