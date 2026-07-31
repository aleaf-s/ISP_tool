#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <array>
#include <algorithm>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace py = pybind11;

#ifndef ISP_NATIVE_VERSION
#define ISP_NATIVE_VERSION "development"
#endif

namespace {

constexpr int kBackendAbi = 1;

unsigned int worker_count(
    py::ssize_t rows, py::ssize_t pixel_count
) {
    if (pixel_count < 256 * 1024 || rows < 2) {
        return 1;
    }
    const unsigned int hardware = std::max(
        1U, std::thread::hardware_concurrency()
    );
    return std::min(
        hardware, static_cast<unsigned int>(rows)
    );
}

template <typename Function>
void parallel_rows(
    py::ssize_t rows,
    py::ssize_t pixel_count,
    Function function
) {
    const unsigned int count = worker_count(rows, pixel_count);
    if (count == 1) {
        function(0, rows, 0);
        return;
    }
    std::vector<std::thread> workers;
    workers.reserve(count);
    for (unsigned int index = 0; index < count; ++index) {
        const py::ssize_t begin = (
            rows * static_cast<py::ssize_t>(index)
        ) / static_cast<py::ssize_t>(count);
        const py::ssize_t end = (
            rows * static_cast<py::ssize_t>(index + 1)
        ) / static_cast<py::ssize_t>(count);
        workers.emplace_back(function, begin, end, index);
    }
    for (auto& worker : workers) {
        worker.join();
    }
}

int reflect101(int value, int length) {
    if (length <= 1) {
        return 0;
    }
    while (value < 0 || value >= length) {
        value = value < 0 ? -value : 2 * length - value - 2;
    }
    return value;
}

bool is_sample(
    const std::string& pattern, int y, int x, char channel
) {
    const int pattern_index = (y & 1) * 2 + (x & 1);
    return pattern[pattern_index] == channel;
}

py::array_t<float> demosaic_bilinear(
    py::array_t<
        float,
        py::array::c_style | py::array::forcecast
    > image,
    const std::string& pattern
) {
    if (
        pattern != "RGGB" && pattern != "GRBG"
        && pattern != "GBRG" && pattern != "BGGR"
    ) {
        throw std::invalid_argument("Unsupported Bayer pattern");
    }
    if (image.ndim() != 2) {
        throw std::invalid_argument(
            "Native demosaic expects a 2-D float32 image"
        );
    }
    const py::ssize_t height = image.shape(0);
    const py::ssize_t width = image.shape(1);
    py::array_t<float> output({height, width, py::ssize_t(3)});
    const float* source = image.data();
    float* destination = output.mutable_data();
    constexpr std::array<char, 3> channels = {'R', 'G', 'B'};
    constexpr int rb_kernel[3][3] = {
        {1, 2, 1}, {2, 4, 2}, {1, 2, 1}
    };
    constexpr int g_kernel[3][3] = {
        {0, 1, 0}, {1, 4, 1}, {0, 1, 0}
    };

    py::gil_scoped_release release;
    parallel_rows(
        height,
        height * width,
        [&](py::ssize_t begin, py::ssize_t end, unsigned int) {
            for (py::ssize_t y = begin; y < end; ++y) {
                for (py::ssize_t x = 0; x < width; ++x) {
                    for (int channel_index = 0; channel_index < 3;
                         ++channel_index) {
                        const char channel = channels[channel_index];
                        float sum = 0.0F;
                        for (int ky = -1; ky <= 1; ++ky) {
                            const int sy = reflect101(
                                static_cast<int>(y) + ky,
                                static_cast<int>(height)
                            );
                            for (int kx = -1; kx <= 1; ++kx) {
                                const int weight = channel == 'G'
                                    ? g_kernel[ky + 1][kx + 1]
                                    : rb_kernel[ky + 1][kx + 1];
                                if (weight == 0) {
                                    continue;
                                }
                                const int sx = reflect101(
                                    static_cast<int>(x) + kx,
                                    static_cast<int>(width)
                                );
                                if (is_sample(
                                    pattern, sy, sx, channel
                                )) {
                                    sum += source[
                                        static_cast<py::ssize_t>(sy)
                                        * width + sx
                                    ] * static_cast<float>(weight);
                                }
                            }
                        }
                        destination[
                            (y * width + x) * 3 + channel_index
                        ] = sum * 0.25F;
                    }
                }
            }
        }
    );
    return output;
}

inline void sort_pair(float& first, float& second) {
    if (first > second) {
        std::swap(first, second);
    }
}

float median_3x3_at(
    const float* source,
    py::ssize_t height,
    py::ssize_t width,
    py::ssize_t raw_y,
    py::ssize_t raw_x
) {
    const py::ssize_t top = raw_y < 2 ? raw_y : raw_y - 2;
    const py::ssize_t bottom = (
        raw_y + 2 < height ? raw_y + 2 : raw_y
    );
    const py::ssize_t left = raw_x < 2 ? raw_x : raw_x - 2;
    const py::ssize_t right = (
        raw_x + 2 < width ? raw_x + 2 : raw_x
    );
    float values[9] = {
        source[top * width + left],
        source[top * width + raw_x],
        source[top * width + right],
        source[raw_y * width + left],
        source[raw_y * width + raw_x],
        source[raw_y * width + right],
        source[bottom * width + left],
        source[bottom * width + raw_x],
        source[bottom * width + right],
    };
    // Fixed median-of-nine sorting network. This is substantially cheaper
    // than invoking a general nth_element for every sensor pixel.
    sort_pair(values[1], values[2]);
    sort_pair(values[4], values[5]);
    sort_pair(values[7], values[8]);
    sort_pair(values[0], values[1]);
    sort_pair(values[3], values[4]);
    sort_pair(values[6], values[7]);
    sort_pair(values[1], values[2]);
    sort_pair(values[4], values[5]);
    sort_pair(values[7], values[8]);
    sort_pair(values[0], values[3]);
    sort_pair(values[5], values[8]);
    sort_pair(values[4], values[7]);
    sort_pair(values[3], values[6]);
    sort_pair(values[1], values[4]);
    sort_pair(values[2], values[5]);
    sort_pair(values[4], values[7]);
    sort_pair(values[4], values[2]);
    sort_pair(values[6], values[4]);
    sort_pair(values[4], values[2]);
    return values[4];
}

float median_at(
    const float* source,
    py::ssize_t height,
    py::ssize_t width,
    py::ssize_t raw_y,
    py::ssize_t raw_x,
    int kernel
) {
    if (kernel == 3) {
        return median_3x3_at(
            source, height, width, raw_y, raw_x
        );
    }
    std::array<float, 25> values{};
    const int radius = kernel / 2;
    const py::ssize_t parity_y = raw_y & 1;
    const py::ssize_t parity_x = raw_x & 1;
    const py::ssize_t plane_y = raw_y / 2;
    const py::ssize_t plane_x = raw_x / 2;
    const py::ssize_t plane_height = (
        height - parity_y + 1
    ) / 2;
    const py::ssize_t plane_width = (
        width - parity_x + 1
    ) / 2;
    int count = 0;
    for (int dy = -radius; dy <= radius; ++dy) {
        const py::ssize_t sample_plane_y = std::clamp(
            plane_y + dy,
            py::ssize_t(0),
            plane_height - 1
        );
        const py::ssize_t sample_y = (
            sample_plane_y * 2 + parity_y
        );
        for (int dx = -radius; dx <= radius; ++dx) {
            const py::ssize_t sample_plane_x = std::clamp(
                plane_x + dx,
                py::ssize_t(0),
                plane_width - 1
            );
            const py::ssize_t sample_x = (
                sample_plane_x * 2 + parity_x
            );
            values[count++] = source[
                sample_y * width + sample_x
            ];
        }
    }
    auto middle = values.begin() + count / 2;
    std::nth_element(values.begin(), middle, values.begin() + count);
    return *middle;
}

py::tuple dpc_correct(
    py::array_t<
        float,
        py::array::c_style | py::array::forcecast
    > image,
    int kernel,
    float threshold,
    bool detect_hot,
    bool detect_dark,
    py::array_t<
        std::uint8_t,
        py::array::c_style | py::array::forcecast
    > static_map,
    bool dynamic_enabled,
    bool static_enabled
) {
    if (image.ndim() != 2) {
        throw std::invalid_argument(
            "Native DPC expects a 2-D float32 image"
        );
    }
    if (kernel != 3 && kernel != 5) {
        throw std::invalid_argument(
            "Native DPC kernel must be 3 or 5"
        );
    }
    const py::ssize_t height = image.shape(0);
    const py::ssize_t width = image.shape(1);
    if (
        static_enabled
        && (
            static_map.ndim() != 2
            || static_map.shape(0) != height
            || static_map.shape(1) != width
        )
    ) {
        throw std::invalid_argument(
            "Native DPC static map shape does not match the image"
        );
    }
    py::array_t<float> corrected({height, width});
    py::array_t<std::uint8_t> defect_mask({height, width});
    const float* source = image.data();
    const std::uint8_t* map = (
        static_enabled ? static_map.data() : nullptr
    );
    float* output = corrected.mutable_data();
    std::uint8_t* mask = defect_mask.mutable_data();
    const unsigned int count = worker_count(
        height, height * width
    );
    struct Counts {
        std::uint64_t hot = 0;
        std::uint64_t dark = 0;
        std::uint64_t corrected = 0;
    };
    std::vector<Counts> counts(count);

    {
        py::gil_scoped_release release;
        parallel_rows(
            height,
            height * width,
            [&](py::ssize_t begin, py::ssize_t end, unsigned int worker) {
                Counts& local = counts[worker];
                for (py::ssize_t y = begin; y < end; ++y) {
                    for (py::ssize_t x = 0; x < width; ++x) {
                        const py::ssize_t index = y * width + x;
                        const float median = median_at(
                            source, height, width, y, x, kernel
                        );
                        const float delta = source[index] - median;
                        bool hot = (
                            dynamic_enabled && detect_hot
                            && delta > threshold
                        );
                        bool dark = (
                            dynamic_enabled && detect_dark
                            && delta < -threshold
                        );
                        if (map != nullptr) {
                            hot = hot || map[index] == 1;
                            dark = dark || map[index] == 2;
                        }
                        const bool replace = hot || dark;
                        output[index] = replace ? median : source[index];
                        mask[index] = static_cast<std::uint8_t>(
                            (hot ? 1 : 0) + (dark ? 2 : 0)
                        );
                        local.hot += hot ? 1 : 0;
                        local.dark += dark ? 1 : 0;
                        local.corrected += replace ? 1 : 0;
                    }
                }
            }
        );
    }
    std::uint64_t hot_count = 0;
    std::uint64_t dark_count = 0;
    std::uint64_t corrected_count = 0;
    for (const Counts& value : counts) {
        hot_count += value.hot;
        dark_count += value.dark;
        corrected_count += value.corrected;
    }
    return py::make_tuple(
        corrected,
        defect_mask,
        hot_count,
        dark_count,
        corrected_count
    );
}

py::dict backend_info() {
    py::dict result;
    result["name"] = "ISP Native C++";
    result["version"] = ISP_NATIVE_VERSION;
    result["abi"] = kBackendAbi;
    result["kernels"] = py::make_tuple(
        "demosaic_bilinear", "dpc_correct"
    );
    // Only kernels that beat the reference backend on the release machine
    // are enabled by Auto. Explicit Native C++ mode can still force all
    // available kernels for investigation.
    result["qualified_kernels"] = py::make_tuple(
        "demosaic_bilinear"
    );
    result["threading"] = "std::thread";
    return result;
}

}  // namespace

PYBIND11_MODULE(_native, module) {
    module.doc() = "Optional native kernels for ISP RAW Visual Simulator";
    module.attr("ISP_BACKEND_ABI") = kBackendAbi;
    module.def("backend_info", &backend_info);
    module.def(
        "demosaic_bilinear",
        &demosaic_bilinear,
        py::arg("image"),
        py::arg("pattern")
    );
    module.def(
        "dpc_correct",
        &dpc_correct,
        py::arg("image"),
        py::arg("kernel"),
        py::arg("threshold"),
        py::arg("detect_hot"),
        py::arg("detect_dark"),
        py::arg("static_map"),
        py::arg("dynamic_enabled"),
        py::arg("static_enabled")
    );
}
