CLAUDE.md

You are assisting with development of a cross-platform background daemon that enables cooperative layered behavior between independent USB HID devices that are not physically connected.

Your role is to reason about architecture, tradeoffs, edge-cases, and implementation details — not to oversimplify or over-abstract. Favor system-level correctness over “developer tutorial tone”.

1. Project Summary

This project creates a host-mediated inter-HID state fabric.

It allows a pointing device (e.g., trackball) to dynamically activate a temporary “mouse layer” on a completely separate keyboard device, enabling users to perform mouse actions from the keyboard home row without touching the pointing device.
The mouse_layer is activated for a configurable time period, after which it turns off.  Any key other than the specified mouse button keys (along with exceptions for modifiers used in clicking...) exits. 
Alternatively, the timeout can be set to infinite, in which case any key other than the specified mouse button keys (along with modifiers used in clicking...) exits.

The idea is to allow a user to click with their left hand while mousing with their right, for example. And in more advanced use cases, to bind special commands that are only available while the mouse is moving.

In the basic implementation, it works with any pointing device and any keyboard. 
In a more sophisticated implementation which we will do later, it can trigger layer shifts in a Vial-QMK-powered keyboard with some special protocol features. 

There must be a straightforward and functional GUI in a taskbar daemon for configuring which pointing devices are handled in which ways. Ideally following the very excellent design used by the Windows application Eithermouse.

Build the Windows version first, but ensure that the Linux and Mac worlds are also supported. 

There is no physical connection between devices.
All communication is performed via the host OS.

2. System Model
2.1 Roles
Role	Description
Trigger Device	A pointing device that activates layer state (trackball, mouse, etc.)
Target Device	A keyboard whose behavior is remapped based on shared state
2.2 Event Flow
Trigger HID → Host OS → Daemon → Host OS → Target HID


The daemon:

listens to raw HID reports from trigger devices,

intercepts keyboard events from target devices,

maintains shared cross-device state,

rewrites and reinjects events.

3. Layer State Machine

The daemon maintains the following global states:

State	Meaning
normal	Keyboard behaves normally
mouse_layer_active	Keys emit mouse clicks / scroll / drag
latched (optional)	Layer persists until explicitly exited

Transitions are triggered by:

pointing device motion or buttons,

explicit exit keys,

inactivity timeout.

Timeout target: 300–1200 ms

4. Performance Constraints

This system must feel indistinguishable from firmware-level integration.

Target end-to-end latency:

Stage	Budget
HID → daemon	≤1 ms
daemon logic	≤0.3 ms
reinjection	≤1 ms
Total	≤3 ms typical

Avoid polling loops. Use event-driven I/O exclusively.

5. Platform Strategy
Layer	Technology
Raw HID access	HIDAPI
Global input hooks	libuiohook / SharpHook
Event injection	OS-native APIs
Configuration	YAML or JSON
Runtime	Rust or Go preferred

Cross-platform support is mandatory: Windows, macOS, Linux.

6. Device Identification

Devices are identified using:

VID / PID

HID usage pages

Vendor-defined report descriptors

Trigger devices may expose custom HID usages to ensure unambiguous detection.

7. Configuration Example
devices:
  trackball:
    vid: 0x1209
    pid: 0xABCD
    role: trigger

  left_keyboard:
    vid: 0xFEED
    pid: 0x6060
    role: target

layers:
  mouse_layer:
    timeout_ms: 900
    mappings:
      J: mouse_left_click
      K: mouse_right_click
      U: mouse_scroll_up
      I: mouse_scroll_down

8. Design Philosophy

You must adhere to these principles:

Host is the bus — devices never communicate directly.

Firmware stays dumb — existing hardware must work.

State is cross-device — layers span physical boundaries.

Latency is sacred — never sacrifice responsiveness.

9. Anti-Goals

Do NOT propose:

TRRS / I2C / UART links between devices.

Firmware-heavy solutions.

Polling-based event loops.

High-latency abstraction layers.

10. Objective

You are not building a keyboard tool.

You are building the first host-level cooperative HID fabric.