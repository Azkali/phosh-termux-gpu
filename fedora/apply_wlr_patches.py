#!/usr/bin/env python3
# Patches wlroots 0.19.3 to let the Vulkan renderer (KGSL Turnip, no DRM fd)
# composite into shm (data-ptr) output buffers, so the X11 backend's existing
# software (XShm) present path carries GPU-composited frames. Hardware
# compositing without DRI3 / DMA-BUF.
import sys, io

ROOT = "/root/wlroots"
changes = 0

def patch(path, old, new, count=1, label=""):
    global changes
    full = ROOT + "/" + path
    with io.open(full, "r", encoding="utf-8") as f:
        s = f.read()
    n = s.count(old)
    if n != count:
        print("FAIL [%s] %s: expected %d match(es), found %d" % (label, path, count, n))
        sys.exit(1)
    s = s.replace(old, new)
    with io.open(full, "w", encoding="utf-8") as f:
        f.write(s)
    changes += 1
    print("OK   [%s] %s" % (label, path))

# ---- Patch 1: device selection without a DRM fd (vulkan.c) ----
patch("render/vulkan/vulkan.c",
"""\t\t} else {
\t\t\tfound = phdev_props.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU;
\t\t}""",
"""\t\t} else {
\t\t\t// wlroots-kgsl: no DRM fd (KGSL Turnip + software-present X11
\t\t\t// backend). Accept the first enumerated device. VK_ICD_FILENAMES
\t\t\t// is expected to restrict enumeration to the target GPU.
\t\t\tfound = true;
\t\t}""",
label="find_drm_phdev")

# ---- Patch 2: advertise DATA_PTR (shm) buffer capability (renderer.c) ----
patch("render/vulkan/renderer.c",
"\twlr_renderer_init(&renderer->wlr_renderer, &renderer_impl, WLR_BUFFER_CAP_DMABUF);",
"\twlr_renderer_init(&renderer->wlr_renderer, &renderer_impl,\n"
"\t\tWLR_BUFFER_CAP_DMABUF | WLR_BUFFER_CAP_DATA_PTR);",
label="renderer caps")

# ---- Patch 3: render-buffer struct fields (vulkan.h) ----
patch("include/render/vulkan.h",
"""\tVkDeviceMemory memories[WLR_DMABUF_MAX_PLANES];
\tuint32_t mem_count;
\tVkImage image;""",
"""\tVkDeviceMemory memories[WLR_DMABUF_MAX_PLANES];
\tuint32_t mem_count;
\tVkImage image;

\t// wlroots-kgsl: shm (data-ptr) render target. When the wlr_buffer is
\t// backed by host memory (no dmabuf), we render into the device-local
\t// "image" above and copy it out to the shm buffer after submitting.
\tbool shm_readback;
\tVkFormat shm_image_format;
\tuint32_t shm_drm_format;
\tuint32_t shm_stride;
\tVkBuffer shm_stage_buffer;
\tVkDeviceMemory shm_stage_memory;
\tvoid *shm_stage_mapped;
\tVkDeviceSize shm_stage_size;""",
label="render_buffer struct")

# ---- Patch 3b: declare the readback helper (vulkan.h) ----
patch("include/render/vulkan.h",
"""bool vulkan_setup_plain_framebuffer(struct wlr_vk_render_buffer *buffer,
\tconst struct wlr_dmabuf_attributes *dmabuf);""",
"""bool vulkan_setup_plain_framebuffer(struct wlr_vk_render_buffer *buffer,
\tconst struct wlr_dmabuf_attributes *dmabuf);

// wlroots-kgsl: copy a finished shm render buffer's device-local image out to
// its host (shm) memory. Called after the render command buffer is submitted.
void vulkan_shm_render_buffer_readback(struct wlr_vk_renderer *renderer,
\tstruct wlr_vk_render_buffer *buffer);""",
label="readback decl")

# ---- Patch 4: shm render-buffer init + readback impl, and create_render_buffer branch (renderer.c) ----
NEWFUNCS = """// wlroots-kgsl: set up a render buffer that targets a host (shm) wlr_buffer.
// We allocate a device-local color image, build the normal (plain) framebuffer
// onto it, and flag it so render_pass_submit() copies it out to the shm memory.
static bool vulkan_init_shm_render_buffer(struct wlr_vk_render_buffer *buffer,
\t\tstruct wlr_shm_attributes *shm) {
\tstruct wlr_vk_renderer *renderer = buffer->renderer;
\tVkDevice dev = renderer->dev->dev;
\tuint32_t width = buffer->wlr_buffer->width;
\tuint32_t height = buffer->wlr_buffer->height;

\tconst struct wlr_vk_format_props *fmt = vulkan_format_props_from_drm(
\t\trenderer->dev, shm->format);
\tif (fmt == NULL) {
\t\twlr_log(WLR_ERROR, "shm render buffer: unsupported format 0x%08x",
\t\t\tshm->format);
\t\treturn false;
\t}

\tVkImageCreateInfo img_info = {
\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
\t\t.imageType = VK_IMAGE_TYPE_2D,
\t\t.format = fmt->format.vk,
\t\t.mipLevels = 1,
\t\t.arrayLayers = 1,
\t\t.samples = VK_SAMPLE_COUNT_1_BIT,
\t\t.tiling = VK_IMAGE_TILING_OPTIMAL,
\t\t.initialLayout = VK_IMAGE_LAYOUT_PREINITIALIZED,
\t\t.extent = (VkExtent3D){ width, height, 1 },
\t\t.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
\t\t\tVK_IMAGE_USAGE_TRANSFER_SRC_BIT,
\t\t.sharingMode = VK_SHARING_MODE_EXCLUSIVE,
\t};
\tVkResult res = vkCreateImage(dev, &img_info, NULL, &buffer->image);
\tif (res != VK_SUCCESS) {
\t\twlr_vk_error("vkCreateImage (shm render buffer)", res);
\t\treturn false;
\t}

\tVkMemoryRequirements mem_reqs;
\tvkGetImageMemoryRequirements(dev, buffer->image, &mem_reqs);
\tint mem_type = vulkan_find_mem_type(renderer->dev,
\t\tVK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, mem_reqs.memoryTypeBits);
\tif (mem_type < 0) {
\t\twlr_log(WLR_ERROR, "shm render buffer: no device-local memory type");
\t\treturn false;
\t}
\tVkMemoryAllocateInfo mem_info = {
\t\t.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
\t\t.allocationSize = mem_reqs.size,
\t\t.memoryTypeIndex = mem_type,
\t};
\tres = vkAllocateMemory(dev, &mem_info, NULL, &buffer->memories[0]);
\tif (res != VK_SUCCESS) {
\t\twlr_vk_error("vkAllocateMemory (shm render buffer)", res);
\t\treturn false;
\t}
\tbuffer->mem_count = 1;
\tres = vkBindImageMemory(dev, buffer->image, buffer->memories[0], 0);
\tif (res != VK_SUCCESS) {
\t\twlr_vk_error("vkBindImageMemory (shm render buffer)", res);
\t\treturn false;
\t}

\tstruct wlr_dmabuf_attributes synth = {
\t\t.format = shm->format,
\t\t.width = width,
\t\t.height = height,
\t};
\tif (!vulkan_setup_plain_framebuffer(buffer, &synth)) {
\t\treturn false;
\t}

\t// host-visible staging buffer. The render command buffer copies the
\t// composited image into it (no stage-cb contention with phosh's texture
\t// uploads); after the render submit completes we memcpy it to the shm buffer.
\tbuffer->shm_stride = shm->stride;
\tbuffer->shm_stage_size = (VkDeviceSize)shm->stride * height;
\tVkBufferCreateInfo stage_info = {
\t\t.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
\t\t.size = buffer->shm_stage_size,
\t\t.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
\t\t.sharingMode = VK_SHARING_MODE_EXCLUSIVE,
\t};
\tif (vkCreateBuffer(dev, &stage_info, NULL, &buffer->shm_stage_buffer) != VK_SUCCESS) {
\t\twlr_log(WLR_ERROR, "shm render buffer: vkCreateBuffer (stage) failed");
\t\treturn false;
\t}
\tVkMemoryRequirements sreq;
\tvkGetBufferMemoryRequirements(dev, buffer->shm_stage_buffer, &sreq);
\tint smt = vulkan_find_mem_type(renderer->dev,
\t\tVK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
\t\tsreq.memoryTypeBits);
\tif (smt < 0) {
\t\twlr_log(WLR_ERROR, "shm render buffer: no host-visible memory type");
\t\treturn false;
\t}
\tVkMemoryAllocateInfo salloc = {
\t\t.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
\t\t.allocationSize = sreq.size,
\t\t.memoryTypeIndex = smt,
\t};
\tif (vkAllocateMemory(dev, &salloc, NULL, &buffer->shm_stage_memory) != VK_SUCCESS) {
\t\twlr_log(WLR_ERROR, "shm render buffer: vkAllocateMemory (stage) failed");
\t\treturn false;
\t}
\tvkBindBufferMemory(dev, buffer->shm_stage_buffer, buffer->shm_stage_memory, 0);
\tif (vkMapMemory(dev, buffer->shm_stage_memory, 0, VK_WHOLE_SIZE, 0,
\t\t\t&buffer->shm_stage_mapped) != VK_SUCCESS) {
\t\twlr_log(WLR_ERROR, "shm render buffer: vkMapMemory (stage) failed");
\t\treturn false;
\t}

\tbuffer->shm_readback = true;
\tbuffer->shm_image_format = fmt->format.vk;
\tbuffer->shm_drm_format = shm->format;
\twlr_log(WLR_DEBUG, "vulkan shm render buffer: %dx%d fmt 0x%08x",
\t\twidth, height, shm->format);
\treturn true;
}

void vulkan_shm_render_buffer_readback(struct wlr_vk_renderer *renderer,
\t\tstruct wlr_vk_render_buffer *buffer) {
\tif (getenv("WLR_KGSL_NO_READBACK")) {
\t\treturn;
\t}
\t// The render command buffer has already copied buffer->image into
\t// shm_stage_buffer. Wait for all submitted GPU work to complete, then copy
\t// the host-visible staging memory into the shm buffer.
\tVkSemaphoreWaitInfoKHR wait_info = {
\t\t.sType = VK_STRUCTURE_TYPE_SEMAPHORE_WAIT_INFO_KHR,
\t\t.semaphoreCount = 1,
\t\t.pSemaphores = &renderer->timeline_semaphore,
\t\t.pValues = &renderer->timeline_point,
\t};
\tif (renderer->dev->api.vkWaitSemaphoresKHR(renderer->dev->dev,
\t\t\t&wait_info, UINT64_MAX) != VK_SUCCESS) {
\t\twlr_log(WLR_ERROR, "shm readback: vkWaitSemaphores failed");
\t\treturn;
\t}
\tvoid *data;
\tuint32_t drm_format;
\tsize_t stride;
\tif (!wlr_buffer_begin_data_ptr_access(buffer->wlr_buffer,
\t\t\tWLR_BUFFER_DATA_PTR_ACCESS_WRITE, &data, &drm_format, &stride)) {
\t\twlr_log(WLR_ERROR, "shm readback: begin_data_ptr_access failed");
\t\treturn;
\t}
\tconst char *test_fill = getenv("WLR_KGSL_TEST_FILL");
\tif (test_fill != NULL) {
\t\tmemset(data, atoi(test_fill), stride * (size_t)buffer->wlr_buffer->height);
\t} else {
\t\tsize_t copy_size = stride * (size_t)buffer->wlr_buffer->height;
\t\tif (copy_size > buffer->shm_stage_size) {
\t\t\tcopy_size = buffer->shm_stage_size;
\t\t}
\t\tmemcpy(data, buffer->shm_stage_mapped, copy_size);
\t}
\twlr_buffer_end_data_ptr_access(buffer->wlr_buffer);
}

"""

patch("render/vulkan/renderer.c",
"static struct wlr_vk_render_buffer *create_render_buffer(\n"
"\t\tstruct wlr_vk_renderer *renderer, struct wlr_buffer *wlr_buffer) {",
NEWFUNCS +
"static struct wlr_vk_render_buffer *create_render_buffer(\n"
"\t\tstruct wlr_vk_renderer *renderer, struct wlr_buffer *wlr_buffer) {",
label="new funcs")

patch("render/vulkan/renderer.c",
"""\tstruct wlr_dmabuf_attributes dmabuf = {0};
\tif (!wlr_buffer_get_dmabuf(wlr_buffer, &dmabuf)) {
\t\tgoto error;
\t}""",
"""\tstruct wlr_dmabuf_attributes dmabuf = {0};
\tstruct wlr_shm_attributes shm = {0};
\tif (!wlr_buffer_get_dmabuf(wlr_buffer, &dmabuf)) {
\t\tif (wlr_buffer_get_shm(wlr_buffer, &shm)) {
\t\t\tif (!vulkan_init_shm_render_buffer(buffer, &shm)) {
\t\t\t\tgoto error;
\t\t\t}
\t\t\treturn buffer;
\t\t}
\t\tgoto error;
\t}""",
label="create_render_buffer branch")

# ---- Patch 5: pass.c -- skip dmabuf fence waits for shm; do readback after submit ----
patch("render/vulkan/pass.c",
"""\tif (!render_pass_wait_render_buffer(pass, render_wait, &render_wait_len)) {
\t\twlr_log(WLR_ERROR, "Failed to wait for render buffer DMA-BUF fence");
\t}""",
"""\tif (!render_buffer->shm_readback &&
\t\t\t!render_pass_wait_render_buffer(pass, render_wait, &render_wait_len)) {
\t\twlr_log(WLR_ERROR, "Failed to wait for render buffer DMA-BUF fence");
\t}""",
label="pass skip dmabuf wait")

patch("render/vulkan/pass.c",
"""\tif (!vulkan_sync_render_pass_release(renderer, pass)) {
\t\twlr_log(WLR_ERROR, "Failed to sync render buffer");
\t}

\trender_pass_destroy(pass);
\twlr_buffer_unlock(render_buffer->wlr_buffer);
\treturn true;""",
"""\tif (!render_buffer->shm_readback &&
\t\t\t!vulkan_sync_render_pass_release(renderer, pass)) {
\t\twlr_log(WLR_ERROR, "Failed to sync render buffer");
\t}

\tif (render_buffer->shm_readback) {
\t\tvulkan_shm_render_buffer_readback(renderer, render_buffer);
\t}

\trender_pass_destroy(pass);
\twlr_buffer_unlock(render_buffer->wlr_buffer);
\treturn true;""",
label="pass readback")

# ---- Patch 10: tolerate layer-surface height-0 with bottom-only anchor (phosh home) ----
patch("types/wlr_layer_shell_v1.c",
"""\tif (surface->pending.desired_height == 0 && (anchor & vert) != vert) {
\t\twlr_surface_reject_pending(wlr_surface, surface->resource,
\t\t\tZWLR_LAYER_SURFACE_V1_ERROR_INVALID_SIZE,
\t\t\t"height 0 requested without setting top and bottom anchors");
\t\treturn;
\t}""",
"""\t// wlroots-kgsl: tolerate height 0 with only a bottom anchor. Phosh's
\t// \"phosh home\" full-screen overview commits this; older wlroots (and the
\t// system build) size it to the output, while this upstream-tightened
\t// rejection is fatal and kills phosh on startup. Let arrange() clamp it.
\t(void)vert;""",
label="layer-shell height0 tolerate")

# ---- Patch 9: don't transfer shm render buffer to the FOREIGN queue (fixes black readback) ----
patch("render/vulkan/pass.c",
"""\t// acquire render buffer before rendering
\tacquire_barriers[idx] = (VkImageMemoryBarrier){
\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
\t\t.srcQueueFamilyIndex = VK_QUEUE_FAMILY_FOREIGN_EXT,
\t\t.dstQueueFamilyIndex = renderer->dev->queue_family,
\t\t.image = render_buffer->image,""",
"""\t// acquire render buffer before rendering.
\t// wlroots-kgsl: an shm render buffer is read back on our own queue, so it
\t// must NOT change queue-family ownership to/from the foreign (scanout)
\t// queue - a foreign release would leave our readback reading undefined
\t// contents (observed as a black screen).
\tuint32_t rb_local_qf = render_buffer->shm_readback ?
\t\tVK_QUEUE_FAMILY_IGNORED : renderer->dev->queue_family;
\tuint32_t rb_foreign_qf = render_buffer->shm_readback ?
\t\tVK_QUEUE_FAMILY_IGNORED : VK_QUEUE_FAMILY_FOREIGN_EXT;
\t// acquire render buffer before rendering
\tacquire_barriers[idx] = (VkImageMemoryBarrier){
\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
\t\t.srcQueueFamilyIndex = rb_foreign_qf,
\t\t.dstQueueFamilyIndex = rb_local_qf,
\t\t.image = render_buffer->image,""",
label="shm acquire no-foreign")

patch("render/vulkan/pass.c",
"""\t// release render buffer after rendering
\trelease_barriers[idx] = (VkImageMemoryBarrier){
\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
\t\t.srcQueueFamilyIndex = renderer->dev->queue_family,
\t\t.dstQueueFamilyIndex = VK_QUEUE_FAMILY_FOREIGN_EXT,
\t\t.image = render_buffer->image,""",
"""\t// release render buffer after rendering
\trelease_barriers[idx] = (VkImageMemoryBarrier){
\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
\t\t.srcQueueFamilyIndex = rb_local_qf,
\t\t.dstQueueFamilyIndex = rb_foreign_qf,
\t\t.image = render_buffer->image,""",
label="shm release no-foreign")

# ---- Patch 8: make deferred texture destroy idempotent (fix double-destroy crash) ----
patch("render/vulkan/texture.c",
"""\tif (texture->last_used_cb != NULL) {
\t\tassert(texture->destroy_link.next == NULL); // not already inserted
\t\twl_list_insert(&texture->last_used_cb->destroy_textures,
\t\t\t&texture->destroy_link);
\t\treturn;
\t}""",
"""\tif (texture->last_used_cb != NULL) {
\t\t// wlroots-kgsl: a texture can be destroyed twice before its command
\t\t// buffer completes (observed with shm clients under phosh: the first
\t\t// destroy defers via this list and returns without clearing
\t\t// last_used_cb). Only queue once; it is freed when the cb's resources
\t\t// are released.
\t\tif (texture->destroy_link.next == NULL) {
\t\t\twl_list_insert(&texture->last_used_cb->destroy_textures,
\t\t\t\t&texture->destroy_link);
\t\t}
\t\treturn;
\t}""",
label="texture destroy idempotent")

# ---- Patch 7: advertise shm RENDER formats (LINEAR+INVALID) for shm outputs ----
patch("render/vulkan/pixel_format.c",
"""\tif (modp.drmFormatModifierCount > 0) {
\t\tadd_fmt_props |= query_modifier_support(dev, &props,
\t\t\tmodp.drmFormatModifierCount);
\t}""",
"""\t// wlroots-kgsl: advertise this format as a RENDER target for shm
\t// (data-ptr) outputs. We render into an internal optimal-tiling image and
\t// copy out to the shm buffer, so any optimal-tiling-renderable format
\t// qualifies. Add it with LINEAR + INVALID modifiers so output_pick_format()
\t// can intersect it with the X11 backend's shm output formats.
\tif ((fmtp.formatProperties.optimalTilingFeatures & render_features) == render_features &&
\t\t\t!format->is_ycbcr) {
\t\twlr_drm_format_set_add(&dev->dmabuf_render_formats,
\t\t\tformat->drm, DRM_FORMAT_MOD_LINEAR);
\t\twlr_drm_format_set_add(&dev->dmabuf_render_formats,
\t\t\tformat->drm, DRM_FORMAT_MOD_INVALID);
\t\tadd_fmt_props = true;
\t}

\tif (modp.drmFormatModifierCount > 0) {
\t\tadd_fmt_props |= query_modifier_support(dev, &props,
\t\t\tmodp.drmFormatModifierCount);
\t}""",
label="shm render formats")

# ---- Patch 6: generic autocreate -- allow explicit vulkan without a DRM fd ----
patch("render/wlr_renderer.c",
"""\tif ((is_auto && WLR_HAS_VULKAN_RENDERER) || strcmp(renderer_name, "vulkan") == 0) {
\t\tif (!open_preferred_drm_fd(backend, &drm_fd, &own_drm_fd)) {
\t\t\tlog_creation_failure(is_auto, "Cannot create Vulkan renderer: no DRM FD available");
\t\t} else {
#if WLR_HAS_VULKAN_RENDERER
\t\t\trenderer = wlr_vk_renderer_create_with_drm_fd(drm_fd);
#else
\t\t\twlr_log(WLR_ERROR, "Cannot create Vulkan renderer: disabled at compile-time");
#endif
\t\t\tif (renderer) {
\t\t\t\tgoto out;
\t\t\t} else {
\t\t\t\tlog_creation_failure(is_auto, "Failed to create a Vulkan renderer");
\t\t\t}
\t\t}
\t}""",
"""\tif ((is_auto && WLR_HAS_VULKAN_RENDERER) || strcmp(renderer_name, "vulkan") == 0) {
\t\tbool have_fd = open_preferred_drm_fd(backend, &drm_fd, &own_drm_fd);
\t\t// wlroots-kgsl: an explicit WLR_RENDERER=vulkan is allowed to proceed
\t\t// without a DRM fd (KGSL Turnip). The patched renderer picks the device
\t\t// from the ICD. Auto-selection still requires a DRM fd.
\t\tif (!have_fd && is_auto) {
\t\t\tlog_creation_failure(is_auto, "Cannot create Vulkan renderer: no DRM FD available");
\t\t} else {
#if WLR_HAS_VULKAN_RENDERER
\t\t\trenderer = wlr_vk_renderer_create_with_drm_fd(drm_fd);
#else
\t\t\twlr_log(WLR_ERROR, "Cannot create Vulkan renderer: disabled at compile-time");
#endif
\t\t\tif (renderer) {
\t\t\t\tgoto out;
\t\t\t} else {
\t\t\t\tlog_creation_failure(is_auto, "Failed to create a Vulkan renderer");
\t\t\t}
\t\t}
\t}""",
label="autocreate vulkan no-fd")

# ---- Patch 11: free the shm staging buffer on render-buffer destroy ----
patch("render/vulkan/renderer.c",
"""\tvkDestroyImage(dev, buffer->image, NULL);
\tfor (size_t i = 0u; i < buffer->mem_count; ++i) {""",
"""\tif (buffer->shm_stage_buffer != VK_NULL_HANDLE) {
\t\tif (buffer->shm_stage_mapped != NULL) {
\t\t\tvkUnmapMemory(dev, buffer->shm_stage_memory);
\t\t}
\t\tvkDestroyBuffer(dev, buffer->shm_stage_buffer, NULL);
\t\tvkFreeMemory(dev, buffer->shm_stage_memory, NULL);
\t}
\tvkDestroyImage(dev, buffer->image, NULL);
\tfor (size_t i = 0u; i < buffer->mem_count; ++i) {""",
label="destroy free staging")

# ---- Patch 12: record image->staging copy in the RENDER cb (after end render pass) ----
patch("render/vulkan/pass.c",
"""\tvkCmdEndRenderPass(render_cb->vk);

\tsize_t pass_textures_len = pass->textures.size / sizeof(struct wlr_vk_render_pass_texture);""",
"""\tvkCmdEndRenderPass(render_cb->vk);

\t// wlroots-kgsl: for an shm render buffer, copy the composited image into the
\t// host-visible staging buffer using THIS render command buffer (avoids
\t// stage-cb contention with texture uploads under heavy load, e.g. phosh).
\t// vulkan_shm_render_buffer_readback() waits on the submit and memcpys the
\t// staging memory into the shm buffer.
\tif (render_buffer->shm_readback) {
\t\tVkImageMemoryBarrier kgsl_to_src = {
\t\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
\t\t\t.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
\t\t\t.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
\t\t\t.image = render_buffer->image,
\t\t\t.oldLayout = VK_IMAGE_LAYOUT_GENERAL,
\t\t\t.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
\t\t\t.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
\t\t\t.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
\t\t\t.subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 },
\t\t};
\t\tvkCmdPipelineBarrier(render_cb->vk,
\t\t\tVK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
\t\t\tVK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &kgsl_to_src);
\t\tVkBufferImageCopy kgsl_region = {
\t\t\t.bufferOffset = 0,
\t\t\t.bufferRowLength = render_buffer->shm_stride / 4,
\t\t\t.bufferImageHeight = render_buffer->wlr_buffer->height,
\t\t\t.imageSubresource = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 },
\t\t\t.imageExtent = { render_buffer->wlr_buffer->width,
\t\t\t\trender_buffer->wlr_buffer->height, 1 },
\t\t};
\t\tvkCmdCopyImageToBuffer(render_cb->vk, render_buffer->image,
\t\t\tVK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
\t\t\trender_buffer->shm_stage_buffer, 1, &kgsl_region);
\t\tVkImageMemoryBarrier kgsl_to_gen = {
\t\t\t.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
\t\t\t.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
\t\t\t.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
\t\t\t.image = render_buffer->image,
\t\t\t.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
\t\t\t.newLayout = VK_IMAGE_LAYOUT_GENERAL,
\t\t\t.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
\t\t\t.dstAccessMask = 0,
\t\t\t.subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 },
\t\t};
\t\tvkCmdPipelineBarrier(render_cb->vk,
\t\t\tVK_PIPELINE_STAGE_TRANSFER_BIT,
\t\t\tVK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, NULL, 0, NULL, 1, &kgsl_to_gen);
\t}

\tsize_t pass_textures_len = pass->textures.size / sizeof(struct wlr_vk_render_pass_texture);""",
label="pass record copy")

print("\\nAll %d patches applied." % changes)
