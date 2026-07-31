cmake_minimum_required(VERSION 3.18)
project(isp_native_backend VERSION 0.4.10 LANGUAGES CXX)

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(_native MODULE isp_native.cpp)
target_compile_features(_native PRIVATE cxx_std_17)
target_compile_definitions(
    _native PRIVATE ISP_NATIVE_VERSION="${PROJECT_VERSION}"
)

if(MSVC)
    target_compile_options(_native PRIVATE /O2 /EHsc)
else()
    target_compile_options(_native PRIVATE -O3)
endif()

# Install/copy the extension into the Python package so
# `import isp_tool._native` can discover it.
install(
    TARGETS _native
    LIBRARY DESTINATION isp_tool
    RUNTIME DESTINATION isp_tool
)
