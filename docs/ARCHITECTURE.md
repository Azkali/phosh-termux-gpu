# Architecture & the patches

## The two walls (and why the "obvious" approaches fail)

1. **The Adreno GPU is KGSL-only.** On Qualcomm Android there is no DRM *render* node for the GPU exposed to app domains — `/dev/dri/renderD128` either doesn't exist or is SELinux-blocked, and the only DRM node (`/sys/class/drm/renderD128` → `qcom,mdss_mdp`/`msm_drm`) is the **display controller (DPU)**, not the GPU. The GPU is reachable only via `/dev/kgsl-3d0`. Fedora's stock Turnip is DRM/`msm`-only and falls back to llvmpipe → we build Turnip with `-Dfreedreno-kmds=kgsl`.

2. **wlroots' X11 backend wants DRI3/DMA-BUF for any GPU renderer.** Termux:X11 is a *software* X server with no DRI3, so `WLR_RENDERER=vulkan` (and `gles2`) fail at `Failed to open DRI3 / no DRM FD available` before rendering. Only the pixman (CPU) path works out of the box, because it presents shm buffers via **MIT-SHM (XShm)**.

The earlier conclusion was "therefore HW compositing is impossible here." It isn't — you just have to **decouple the renderer from the present path**: composite on the GPU but present the finished frame over the existing XShm software path.

## The data flow

```
phosh (GTK, software/cairo) ── shm wl_buffer ─┐
                                              │  wl_surface.commit
phoc ── wlr_scene ── wlroots Vulkan renderer ─┘
   • uploads each client shm buffer as a Vulkan texture
   • composites them into a device-local VkImage on the Adreno GPU (Turnip)
   • vkCmdCopyImageToBuffer(image -> host-visible staging) in the render cmdbuf
   • memcpy(staging -> the output shm buffer)            <-- GPU readback
X11 backend ── import_shm() + xcb_present_pixmap()       <-- XShm, no DRI3
Termux:X11 (software X) ── Android SurfaceFlinger
```

Only the final present (GPU→CPU readback + a shm copy) is on the CPU — unavoidable, since the X server is software. Everything else (blending the whole screen, scaling) is on the GPU.

## The wlroots patches (`fedora/apply_wlr_patches.py`, wlroots 0.19.x)

phoc links `libwlroots-0.19.so` **dynamically**, so we rebuild only the lib and `LD_LIBRARY_PATH` it — **no phoc rebuild**. The build must use the full backend/renderer set (drm,libinput,x11 + gles2,vulkan + xwayland) to stay ABI-compatible with the distro's phoc.

| # | File | What |
|---|------|------|
| 1 | `render/vulkan/vulkan.c` | `vulkan_find_drm_phdev`: with no DRM fd, accept the first enumerated device (the ICD is restricted to Turnip). |
| 2 | `render/wlr_renderer.c` | `renderer_autocreate`: allow an explicit `WLR_RENDERER=vulkan` to proceed with no DRM fd. |
| 3 | `render/vulkan/renderer.c` | Advertise `WLR_BUFFER_CAP_DATA_PTR`; `create_render_buffer` handles **shm** targets (internal device-local VkImage + plain framebuffer + a host-visible staging VkBuffer). |
| 4 | `render/vulkan/pixel_format.c` | Advertise shm **render** formats with `LINEAR`+`INVALID` modifiers, so `output_pick_format` can intersect with the X11 shm output. |
| 5 | `render/vulkan/pass.c` | Skip the dmabuf fence waits + the **FOREIGN-queue** ownership transfer for shm buffers (the foreign release made the readback read undefined data → black); record `vkCmdCopyImageToBuffer(image→staging)` in the render cmdbuf; readback = wait on the render timeline + memcpy. |
| 6 | `render/vulkan/texture.c` | Make deferred texture-destroy idempotent — phosh double-destroys shm textures, tripping `assert(destroy_link.next == NULL)`. |
| 7 | `types/wlr_layer_shell_v1.c` | Tolerate a height-0 layer surface anchored bottom-only (phosh's "phosh home" overview). 0.19.3 made this a *fatal* protocol error that kills phosh; older/distro wlroots sized it to the output. |

## The Turnip patch (`fedora/3-build-turnip.sh`, Mesa main)

Mesa **main** already has native Adreno 830 (`chip_id 0x44050001`) and UBWC 5.0 (`KGSL_UBWC_5_0`). The only source change is dropping the `KHR_display` guard in `tu_knl_kgsl.cc` so `vulkaninfo` (which enables `KHR_display`) doesn't fail device creation. (On Mesa 26.0.x you additionally needed to hand-add the a830 device id and a UBWC-5 switch case — not needed on main.)

## Known rough edges

- **Rare post-unlock crash on the Adreno 830 (~1 in 4 cold starts)** — a full-speed race in the brand-new a8xx Turnip; `gdb` serialises execution and hides it (a Heisenbug). `launch-gpu.sh` auto-sets `TU_DEBUG=flushall,syncdraw` *for a8xx GPUs* (read from `/sys/class/kgsl/kgsl-3d0/gpu_model`) to serialise GPU submission and make it much rarer. **The mature Adreno 750 doesn't show the race** — verified stable over many cold starts with no `TU_DEBUG` — so the launcher runs 7xx/older at full speed. The `--debug` launcher LD_PRELOADs `libsegcatch.so` to print a backtrace if it ever bites.
- **Apps render in software** (`GSK_RENDERER=cairo`). With no DMA-BUF the compositor can't hand GTK4 a GPU surface, so GTK4's default GPU path crashes the app; cairo avoids that. The compositing is still GPU.
- **Termux:X11 staleness** — after many phoc restarts the X server shows black even for known-good software phosh; `start.sh` restarts it.
