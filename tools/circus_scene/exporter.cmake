# Passed to circus's CMake as -DCMAKE_PROJECT_circus_INCLUDE=<this file>. CMake runs it right
# after project(circus); the deferred calls run at the end of circus's CMakeLists.txt, when the
# circus-lib target exists. The exporter so gets circus's exact flags, PROJECT_ROOT and deps.
# Deferred arguments are evaluated when the call runs, so the path goes through a variable.
set(_circus_scene_export_src "${CMAKE_CURRENT_LIST_DIR}/export_scene.cpp")
cmake_language(DEFER CALL add_executable circus_scene_export "${_circus_scene_export_src}")
cmake_language(DEFER CALL target_link_libraries circus_scene_export PRIVATE circus-lib)
