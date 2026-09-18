"""jev-lint hero object: a stack of note pages, top corner lifted, one line
struck in correction red, the matching line on the page below in highlighter.

Build inside a running Blender (via blender-mcp execute_code) to inspect, or
render headless:

    Blender --background --python site/hero_scene.py -- --render OUT.png
"""
import sys
from math import sin, cos, radians
from random import Random

import bpy
from mathutils import Vector

COLL = "JEV_HERO"
PAGE_W, PAGE_H = 0.148, 0.105
THICK, PITCH = 0.00028, 0.00036
N_PAGES = 6

PAPER = "#f7f1e6"
RED = "#a83d29"
YELLOW = "#f2d15a"
GREY = "#8e8a80"


def lin(hexcol):
    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return (f(r), f(g), f(b), 1.0)


def curl_point(x, y, z):
    nx, ny = 0.8, -0.6
    bend_start, radius = 0.014, 0.040
    s = nx * x + ny * y
    if s <= bend_start:
        return x, y, z
    theta = (s - bend_start) / radius
    delta = bend_start + radius * sin(theta) - s
    return x + nx * delta, y + ny * delta, z + radius * (1 - cos(theta))


def grid_mesh(name, nx, ny, z, curl):
    verts, faces, uvs = [], [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            x = -PAGE_W / 2 + PAGE_W * i / nx
            y = -PAGE_H / 2 + PAGE_H * j / ny
            verts.append(curl_point(x, y, z) if curl else (x, y, z))
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            v = me.loops[li].vertex_index
            i, j = v % (nx + 1), v // (nx + 1)
            uv.data[li].uv = (i / nx, j / ny)
    me.shade_smooth()
    return me


def rect_mask(nodes, links, uv_sep, x0, x1, y0, y1):
    """1 inside the UV rectangle, 0 outside."""
    def cmp(op, inp, val):
        n = nodes.new("ShaderNodeMath"); n.operation = op
        links.new(inp, n.inputs[0]); n.inputs[1].default_value = val
        return n.outputs[0]
    def mul(a, b):
        n = nodes.new("ShaderNodeMath"); n.operation = "MULTIPLY"
        links.new(a, n.inputs[0]); links.new(b, n.inputs[1])
        return n.outputs[0]
    u, v = uv_sep.outputs["X"], uv_sep.outputs["Y"]
    return mul(mul(cmp("GREATER_THAN", u, x0), cmp("LESS_THAN", u, x1)),
               mul(cmp("GREATER_THAN", v, y0), cmp("LESS_THAN", v, y1)))


def paper_material(name, marks):
    """marks: list of (hexcolor, x0, x1, y0, y1) in page-fraction UV space,
    drawn in order (later on top)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs["Base Color"].default_value = lin(PAPER)
    bsdf.inputs["Roughness"].default_value = 0.88
    bsdf.inputs["IOR"].default_value = 1.45
    bsdf.inputs["Specular IOR Level"].default_value = 0.2

    tc = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 1500
    noise.inputs["Detail"].default_value = 2
    links.new(tc.outputs["Object"], noise.inputs["Vector"])
    rng = nodes.new("ShaderNodeMapRange")
    rng.inputs["To Min"].default_value = 0.84
    rng.inputs["To Max"].default_value = 0.92
    links.new(noise.outputs["Fac"], rng.inputs["Value"])
    links.new(rng.outputs[0], bsdf.inputs["Roughness"])

    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["UV"], sep.inputs[0])
    color = None
    for hexcol, x0, x1, y0, y1 in marks:
        mask = rect_mask(nodes, links, sep, x0, x1, y0, y1)
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs["A"].default_value = lin(PAPER)
        if color is not None:
            links.new(color, mix.inputs["A"])
        mix.inputs["B"].default_value = lin(hexcol)
        links.new(mask, mix.inputs["Factor"])
        color = mix.outputs["Result"]
    if color is not None:
        links.new(color, bsdf.inputs["Base Color"])
    return mat


def text_lines(rows, lengths, thick=0.02):
    """Grey 'text' bars. rows: page-fraction y centres; lengths: x1 fractions.
    First row is a short, heavier title."""
    bars = [(GREY, 0.10, 0.42, rows[0] - 0.014, rows[0] + 0.014)]
    bars += [(GREY, 0.10, l, r - thick / 2, r + thick / 2) for r, l in zip(rows[1:], lengths[1:])]
    return bars


def build_scene():
    scene = bpy.context.scene
    old = bpy.data.collections.get(COLL)
    if old:
        for ob in list(old.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new(COLL)
    scene.collection.children.link(coll)
    for name in ("Cube", "Light", "Camera"):  # factory startup objects
        ob = bpy.data.objects.get(name)
        if ob:
            ob.hide_render = ob.hide_viewport = True

    rnd = Random(7)
    rows = [0.82, 0.70, 0.62, 0.54, 0.46, 0.38, 0.30, 0.22]
    for k in range(N_PAGES):
        top = k == N_PAGES - 1
        z = 0.0003 + k * PITCH
        me = grid_mesh(f"page{k}", 96 if top else 2, 68 if top else 2, z, curl=top)
        ob = bpy.data.objects.new(f"page{k}", me)
        coll.objects.link(ob)
        if not top:
            ob.location = (rnd.uniform(-0.0015, 0.0015), rnd.uniform(-0.0015, 0.0015), 0)
            ob.rotation_euler = (0, 0, radians(rnd.uniform(-1.5, 1.5)))
        sol = ob.modifiers.new("Solidify", "SOLIDIFY")
        sol.thickness, sol.offset, sol.use_even_offset = THICK, -1, True
        bev = ob.modifiers.new("Bevel", "BEVEL")
        bev.width, bev.segments, bev.limit_method, bev.angle_limit = 0.00004, 2, "ANGLE", radians(30)

        lengths = [rnd.uniform(0.55, 0.88) for _ in rows]
        marks = text_lines(rows, lengths)
        if top:
            # struck line: row 0.46, red stroke across it, slightly rising
            r = rows[4]
            marks.append((RED, 0.085, lengths[4] + 0.025, r - 0.005, r + 0.005))
        elif k == N_PAGES - 2:
            # highlighter band under the matching line, in the corner the curl exposes
            r = rows[7]
            marks.insert(0, (YELLOW, 0.34, 0.93, r - 0.03, r + 0.03))
            lengths[7] = 0.90
        ob.data.materials.append(paper_material(f"paper{k}", marks))

    # camera
    cam_data = bpy.data.cameras.new("HeroCam")
    cam_data.lens, cam_data.sensor_width = 58, 36
    cam_data.clip_start, cam_data.clip_end = 0.01, 10
    cam = bpy.data.objects.new("HeroCam", cam_data)
    coll.objects.link(cam)
    cam.location = (0.085, -0.175, 0.365)  # corner side of the fold, so the flap reveals the page below
    cam.rotation_euler = (Vector((0, 0, 0.012)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    # lights
    aim = Vector((0, 0, 0.008))
    for name, loc, size, power, tint in [
        ("Key", (-0.24, -0.05, 0.32), 0.26, 3.0, (1.0, 0.94, 0.86)),
        ("Fill", (0.16, -0.18, 0.20), 0.30, 0.8, (0.90, 0.95, 1.0)),
        ("Rear", (0.04, 0.20, 0.28), 0.20, 1.2, (1.0, 0.98, 0.94)),
    ]:
        ld = bpy.data.lights.new(name, "AREA")
        ld.shape, ld.size, ld.energy, ld.color = "SQUARE", size, power, tint
        lo = bpy.data.objects.new(name, ld)
        coll.objects.link(lo)
        lo.location = loc
        lo.rotation_euler = (aim - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[1].default_value = 0.08

    # render settings
    scene.render.engine = "CYCLES"
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = 1200, 900
    scene.render.resolution_percentage = 100
    c = scene.cycles
    c.samples, c.use_adaptive_sampling, c.adaptive_threshold, c.adaptive_min_samples = 128, True, 0.02, 32
    c.use_denoising, c.denoiser = True, "OPENIMAGEDENOISE"
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces, c.transmission_bounces = 6, 4, 2, 0
    c.time_limit = 0
    scene.view_settings.view_transform = "Standard"  # AgX greys the red and yellow pigments
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"


def use_metal():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == "METAL"
    bpy.context.scene.cycles.device = "GPU"


def render_scene(path, scale=100, samples=None):
    scene = bpy.context.scene
    use_metal()
    scene.render.resolution_percentage = scale
    if samples:
        scene.cycles.samples = samples
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    build_scene()
    if "--render" in sys.argv:
        render_scene(sys.argv[sys.argv.index("--render") + 1])
