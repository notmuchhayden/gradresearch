// CPU implementation of the frozen upstream forward splat equations.
// A tile owns its pixels; stable depth sorting reproduces front-to-back order.
#include <algorithm>
#include <cmath>
#include <vector>
#include <cstdint>

extern "C" void splat_cpu(int n, int h, int w, int channels,
    const float* xy, const float* conic, const float* depth,
    const int32_t* radius, const float* opacity, const float* values,
    float* output) {
    const int tw = (w + 15) / 16, th = (h + 15) / 16;
    std::vector<int> order(n);
    for (int i = 0; i < n; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        return depth[a] < depth[b];
    });
    std::vector<std::vector<int>> tiles(tw * th);
    for (int i : order) {
        if (radius[i] <= 0 || !std::isfinite(xy[2*i])) continue;
        int x0 = std::min(tw, std::max(0, int((xy[2*i] - radius[i]) / 16)));
        int x1 = std::min(tw, std::max(0, int((xy[2*i] + radius[i] + 15) / 16)));
        int y0 = std::min(th, std::max(0, int((xy[2*i+1] - radius[i]) / 16)));
        int y1 = std::min(th, std::max(0, int((xy[2*i+1] + radius[i] + 15) / 16)));
        for (int y = y0; y < y1; ++y)
            for (int x = x0; x < x1; ++x) tiles[y*tw+x].push_back(i);
    }
    #pragma omp parallel for schedule(dynamic)
    for (int tile = 0; tile < tw*th; ++tile) {
        int x0 = (tile % tw)*16, y0 = (tile / tw)*16;
        for (int y = y0; y < std::min(h,y0+16); ++y) {
            for (int x = x0; x < std::min(w,x0+16); ++x) {
                float T = 1.f;
                float* pixel = output + (y*w+x)*channels;
                for (int i : tiles[tile]) {
                    float dx = xy[2*i]-x, dy = xy[2*i+1]-y;
                    float power = -0.5f*(conic[3*i]*dx*dx + conic[3*i+2]*dy*dy)
                                  -conic[3*i+1]*dx*dy;
                    if (power > 0.f) continue;
                    float alpha = std::min(0.99f,opacity[i]*std::exp(power));
                    if (alpha < 1.f/255.f) continue;
                    float next = T*(1.f-alpha);
                    if (next < 0.0001f) break;
                    for (int c = 0; c < channels; ++c)
                        pixel[c] += values[i*channels+c]*alpha*T;
                    T = next;
                }
            }
        }
    }
}
