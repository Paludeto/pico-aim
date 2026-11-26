# Code Guide and System Walkthrough

*[Versão em Português](../guia_codigo.md)*

This guide explains how the closed-loop system works end to end and outlines the responsibility of each file in the repository.

## 1. End-to-End Operation

The closed loop repeats four stages continuously:

```text
[testapp: 3D Shooter (60 Hz)]
        │  window frame (magenta core at tx, ty)
        ▼
[tracker: capture + HSV + GetCursorPos] ──► USB CDC (MEAS frame: ex, ey)
        ▲                                              │
        │  USB HID (relative mouse, 1 kHz)             ▼
[Windows moves OS pointer] ◄────────────── [RP2040: Core 0 + Core 1 (1 kHz PID)]
```

1. **3D Scene (`host/testapp`):** renders a 3D tactical shooting range in Pygame at 60 Hz. A hovering armored bot moves across the arena with a circular magenta weakspot centered at exact window coordinates `(target_x, target_y)`.
2. **Vision & Error (`host/tracker`):** locates the `"Rastreador - app de teste"` client rectangle via Win32, grabs frames via `dxcam` or `mss`, thresholds the magenta core in HSV to obtain the largest contour's centroid `(tx, ty)`, reads the OS pointer with `GetCursorPos`, and sends `ex = tx - cx`, `ey = ty - cy` over USB CDC.
3. **Real-Time Control (`firmware/`):** RP2040 Core 0 parses CDC frames and pushes measurements to Core 1 via a non-blocking queue. Every 1 ms, Core 1 updates the latency estimator (subtracting in-flight commands) and computes incremental counts `(dx, dy)` using the `Q16.16` PID controller.
4. **Actuation (`USB HID`):** when physically enabled via `BOOTSEL` and set to `AUTO` mode, Core 0 sends relative HID mouse reports to Windows, driving the cursor onto the target.

### How the 3D Interface Preserves Tracking Accuracy

- **Unwarped OS cursor:** the Windows cursor is never locked or warped to screen center, keeping the HID-to-pixel plant linear. The 3D camera achieves immersion via gentle parallax.
- **Exact projection & unprojection:** `Camera3D.screen_to_world()` computes the exact 3D world point that projects back onto `(target_x, target_y)`, keeping the 3D bot body and floor shadow coherent without shifting the logical target.
- **Color discipline & draw order:** arena geometry, weapon viewmodel, muzzle flash, sparks, radar, and HUD stay completely outside the detector's magenta HSV band. The magenta core is drawn last (above HUD and weapon) beneath an open-center reticle, maintaining 100% clean detection anywhere in the viewport.

---

## 2. File-by-File Map

### RP2040 Firmware (`firmware/`)

- `CMakeLists.txt` — Pico SDK C11 build configuration with `copy_to_ram` (runs entirely from SRAM).
- `board_config.h` — pinout (`GP25` LED, `GP2`/`GP3` debug), timing constants (1 ms control, 10 ms UI, 1 s watchdog), queue sizes, and USB descriptors/IDs.
- `prebuilt/cursor_tracker.uf2` — ready-to-flash UF2 binary for Raspberry Pi Pico.
- `src/main.c` — **Core 0** main loop: TinyUSB (`tud_task`), CDC RX/TX, telemetry emission, HID accumulation and reporting, UI polling, CPU load estimation, and watchdog feeding.
- `src/usb/tusb_config.h`, `usb_descriptors.c` — TinyUSB configuration and composite CDC-ACM + HID mouse descriptors (`bInterval = 1 ms`).
- `src/proto/crc8.c/.h`, `proto.c/.h` — CRC-8 (`0x07`), byte-wise parser syncing on `0xA5 0x5A`, and builders for `TELEM`, `ACK`, and `PARAMS`.
- `src/ctrl/fixed.h` — `Q16.16` integer math, clamping, and truncation helpers.
- `src/ctrl/params.c/.h` — default values and range validation for all 9 configurable parameters.
- `src/ctrl/estimator.c/.h` — per-axis multirate latency estimator with a 128-step circular command buffer.
- `src/ctrl/pid.c/.h` — `Q16.16` discrete PID with filtered derivative, deadband, ±127 saturation, clamping anti-windup, and fractional residue accumulator.
- `src/ctrl/loop.c/.h` — single 1 ms control tick: atomic config updates, 100 ms link failsafe, PID or open-loop identification sequence (steps + PRBS7), and 200 Hz telemetry decimation.
- `src/core1/core1.c/.h` — creates inter-core queues and runs `ctrl_loop_step()` inside the 1 kHz hardware-alarm ISR on **Core 1**.
- `src/ui/bootsel.c`, `led.c`, `ui.c/.h` — 10 ms Core 0 timer handling RAM-resident `BOOTSEL` sampling (30 ms debounce; short press vs. 1 s emergency hold) and `GP25` LED patterns.
- `src/app/app.c/.h` — Core 0 state machine, `MEAS` sequence validation, CDC command handling, and button/USB event logic.
- `src/app/persist.c/.h` — flash persistence of parameters in the last sector with header, CRC-8, and coordinated Core 1 lockout.

### Host PC Software (`host/`)

- `common/protocol.py` — mirrors `proto.h` and `params.h`: constants, CRC-8, frame packing/unpacking, physical ↔ `Q16.16` conversion, and `FrameParser`.
- `testapp/trajectories.py` — deterministic `step`, `ramp`, `sine`, `smooth`, and `shooter` trajectories.
- `testapp/shooter3d.py` — Pygame 3D software engine (`Camera3D`, `Shooter3DScene`): perspective arena, rigid-body 3D bot, HSV-safe magenta core, 3D weapon viewmodel with recoil/tracers/sparks, open-center reticle, radar, HUD, and HP/respawn mechanics.
- `testapp/__main__.py` — CLI entry point and 60 Hz window loop, Win32 cursor reader, 3D/2D view toggle (`V`), and per-frame CSV logging.
- `tracker/winutil.py` — Win32 `ctypes` wrappers for DPI awareness, `GetCursorPos`, and window client rect lookup.
- `tracker/capture.py` — BGR region grabber using `dxcam` with automatic fallback to `mss`.
- `tracker/detect.py` — OpenCV HSV thresholding + largest-contour centroid calculation (with NumPy fallback).
- `tracker/__main__.py` — 60 Hz tracker loop: captures the window, computes error, streams `MEAS` over serial, writes logs, and handles live keyboard tuning.
- `analysis/identify.py` — least-squares estimation of plant gain $g$ and latency $L$ from identification telemetry CSVs.
- `analysis/metrics.py` — computes step metrics (overshoot, rise time, 2% settling, steady-state error) and continuous tracking metrics (RMS, delay, phase lag), with `--plot` PNG export.
- `tests/test_host.py` — hardware-free Python test suite (protocol, HSV detection, trajectories, log analysis on `docs/medicoes/`, and 3D frame detection validation).
- `tests/test_ctrl.c`, `sil_shim.c/.h`, `tests.mk` — 2,165 native C unit tests for the portable firmware modules.
- `tests/hw_check.py` — bench check without cursor movement (telemetry rate, 1 ms period, NACKs, failsafe, and flash).
- `tests/hw_loop.py` — automated end-to-end hardware benchmark (`ident`, `step`, `sine`, `ramp`, `smooth`).
- `requirements.txt` — host Python dependencies (`pygame`, `numpy`, `pyserial`, `opencv-python`, `mss>=9.0,<10`, `matplotlib`, `dxcam`).

### Documentation & Measurements (`docs/`)

- `docs/arquitetura.md` / `docs/en/architecture.md` — firmware architecture, protocol, control design, and bench summary.
- `docs/guia_codigo.md` / `docs/en/code_guide.md` — system overview and code map.
- `docs/medicoes/` — bench CSV logs captured on the 3D Shooter interface (`ident_telem.csv`, `step_trim.csv`, `sine_trim.csv`, `ramp_trim.csv`, `smooth_trim.csv`).
