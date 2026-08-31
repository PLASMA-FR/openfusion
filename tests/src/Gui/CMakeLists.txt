# SPDX-License-Identifier: LGPL-2.1-or-later

add_subdirectory(Dialogs)

# Standard C++ GTest tests
add_executable(Gui_tests_run
        Assistant.cpp
        Camera.cpp
        DiagnosticUtils.cpp
        StyleParameters/StyleParametersApplicationTest.cpp
        StyleParameters/ParserTest.cpp
        StyleParameters/ParameterManagerTest.cpp
        InputHintTest.cpp
)

# The production navlib stub is linked only on MSVC/macOS.  Compile its
# platform-neutral lazy-load boundary with a fake loader on other test hosts so
# exactly-once concurrent initialization remains covered without symbol clashes.
if(NOT MSVC AND NOT APPLE)
    target_sources(Gui_tests_run PRIVATE
        NavlibLazyLoad.cpp
        ${CMAKE_SOURCE_DIR}/src/3rdParty/3Dconnexion/src/navlib_load.cpp
    )
endif()

# Qt tests
setup_qt_test(QuantitySpinBox)
setup_qt_test(CommandPalette)
setup_qt_test(MenuManager)
setup_qt_test(WorkspaceSelector)

target_link_libraries(Gui_tests_run PRIVATE
    GTest::gtest_main
    GTest::gmock_main
    ${Google_Tests_LIBS}
    FreeCADApp
    FreeCADGui
)
