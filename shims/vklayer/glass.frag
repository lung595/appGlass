#version 450
// The colour-key pass of appglass-ck.c, for a Vulkan swapchain image: the image is both the
// input attachment and the colour attachment, each fragment reads its own pixel once and
// writes it once. Same formula, same defaults:
//   a_t   = colour-to-alpha opacity of P against the nearest key K (0 = pure key, 1 = unrelated)
//   out.a = 1 - (1 - a_t) * (1 - A)
//   out.rgb (premultiplied) = P - (1 - a_t) * (1 - A) * K
// Pixels that are already translucent are left alone.
layout(input_attachment_index = 0, set = 0, binding = 0) uniform subpassInput src;
layout(location = 0) out vec4 O;
// key[i] = 0xRRGGBBAA (AA = the key's alpha * 255); prm = (number of keys, tol, snap, unused)
layout(push_constant) uniform P { uvec4 key[2]; vec4 prm; } pc;

// One difference from appglass-ck.c: wgpu dithers what it draws (egui fills with a translucent
// colour land on the key +-1 level, at random). Against a dark key one level is a large colour-to-
// alpha step (1/6 for 060607), so the glass would come out speckled. A channel within one 8-bit
// level of the key counts as the key.
const float SLACK = 1.5 / 255.0;
float c2a(vec3 p, vec3 k) {
    vec3 d = vec3(0.0);
    for (int i = 0; i < 3; i++) {
        float pi = p[i], ki = k[i];
        if (pi > ki + SLACK) d[i] = (pi - ki - SLACK) / max(1.0 - ki - SLACK, 1e-4);
        else if (pi < ki - SLACK) d[i] = (ki - SLACK - pi) / max(ki - SLACK, 1e-4);
    }
    return max(d.r, max(d.g, d.b));
}

vec4 unpack(uint i) {
    uint v = pc.key[i >> 2][i & 3u];
    return vec4(float((v >> 24) & 255u), float((v >> 16) & 255u), float((v >> 8) & 255u), float(v & 255u)) / 255.0;
}

void main() {
    vec4 p = subpassLoad(src);
    int n = int(pc.prm.x);
    if (p.a < 0.999 || n == 0) { O = p; return; }
    float best = 1.0; vec4 kb = unpack(0u);
    for (int i = 0; i < 8; i++) {
        if (i >= n) break;
        vec4 k = unpack(uint(i));
        float a = c2a(p.rgb, k.rgb);
        if (a < best) { best = a; kb = k; }
    }
    float tol = pc.prm.y, snap = pc.prm.z;
    float at = clamp((best - tol) / (1.0 - tol), 0.0, 1.0);
    at = at >= snap ? 1.0 : at / snap;
    if (at >= 1.0) { O = p; return; }
    float m = (1.0 - at) * (1.0 - kb.a);
    O = vec4(max(p.rgb - m * kb.rgb, 0.0), 1.0 - m);
}
