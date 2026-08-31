# SPDX-License-Identifier: LGPL-2.1-or-later

configure_file(freecad.rc.cmake ${CMAKE_CURRENT_BINARY_DIR}/freecad.rc)
configure_file(freecadCmd.rc.cmake ${CMAKE_CURRENT_BINARY_DIR}/freecadCmd.rc)
file(COPY icon.ico DESTINATION ${CMAKE_CURRENT_BINARY_DIR})

set(
    OPENFUSION_VERSION_SUFFIX
    "${PACKAGE_VERSION_SUFFIX}"
    CACHE STRING
    "Semantic-version suffix displayed by the OpenFusion GUI and CLI executables"
)

######################## FreeCADMain ########################
if(BUILD_GUI)

    SET(FreeCAD_SRCS
        ${CMAKE_CURRENT_BINARY_DIR}/freecad.rc
        icon.ico
        MainGui.cpp
    )

    SET(FreeCAD_LIBS
        FreeCADGui
    )

    if(NOT BUILD_DYNAMIC_LINK_PYTHON)
        # executables have to be linked against python libraries,
        # because extension modules are not.
        list(APPEND FreeCAD_LIBS
            ${Python3_LIBRARIES}
        )
    endif(NOT BUILD_DYNAMIC_LINK_PYTHON)

    add_executable(FreeCADMain WIN32 ${FreeCAD_SRCS})
    target_link_libraries(FreeCADMain ${FreeCAD_LIBS})
    target_compile_definitions(
        FreeCADMain PRIVATE OPENFUSION_VERSION_SUFFIX="${OPENFUSION_VERSION_SUFFIX}"
    )
    if (FREECAD_WARN_ERROR)
        target_compile_warn_error(FreeCADMain)
    endif()

    SET_BIN_DIR(FreeCADMain FreeCAD)

    if(UNIX AND NOT APPLE)
        set_property(
            TARGET FreeCADMain APPEND PROPERTY
            INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}"
        )
    endif()

    add_custom_command(TARGET FreeCADMain POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:FreeCADMain>"
            "$<TARGET_FILE_DIR:FreeCADMain>/OpenFusion$<TARGET_FILE_SUFFIX:FreeCADMain>"
        VERBATIM
    )

    if(WIN32)
        INSTALL(TARGETS FreeCADMain
            RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        )
    elseif(APPLE AND NOT BUILD_WITH_CONDA)
        INSTALL(TARGETS FreeCADMain
        RUNTIME DESTINATION MacOS
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        )
    else()
        INSTALL(TARGETS FreeCADMain
            RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        )
    endif()
    if(APPLE AND NOT BUILD_WITH_CONDA)
        set(OPENFUSION_GUI_INSTALL_DIR "MacOS")
    else()
        set(OPENFUSION_GUI_INSTALL_DIR "${CMAKE_INSTALL_BINDIR}")
    endif()
    install(CODE "
        file(COPY_FILE
            \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_GUI_INSTALL_DIR}/FreeCAD${CMAKE_EXECUTABLE_SUFFIX}\"
            \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_GUI_INSTALL_DIR}/OpenFusion${CMAKE_EXECUTABLE_SUFFIX}\"
            ONLY_IF_DIFFERENT
        )
    ")
    if(UNIX AND NOT APPLE)
        install(CODE "
            file(REMOVE
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_GUI_INSTALL_DIR}/FreeCAD\"
            )
            file(CREATE_LINK
                OpenFusion
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_GUI_INSTALL_DIR}/FreeCAD\"
                SYMBOLIC
            )
        ")

        add_executable(OpenFusionRuntimeLauncher OpenFusionRuntimeLauncher.c)
        set_target_properties(
            OpenFusionRuntimeLauncher PROPERTIES
            INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}"
        )
        install(
            TARGETS OpenFusionRuntimeLauncher
            RUNTIME DESTINATION libexec
        )
        install(CODE "
            file(MAKE_DIRECTORY
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/libexec\"
            )
            file(RENAME
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_GUI_INSTALL_DIR}/OpenFusion\"
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/libexec/OpenFusion.real\"
            )
            file(RENAME
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/libexec/OpenFusionRuntimeLauncher\"
                \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_GUI_INSTALL_DIR}/OpenFusion\"
            )
        ")
    endif()
endif(BUILD_GUI)
######################## FreeCADMainCmd ########################

SET(FreeCADMainCmd_SRCS
    ${CMAKE_CURRENT_BINARY_DIR}/freecadCmd.rc
    icon.ico
    MainCmd.cpp
)

add_executable(FreeCADMainCmd ${FreeCADMainCmd_SRCS})

SET(FreeCADMainCmd_LIBS
    FreeCADApp
    ${QtCore_LIBRARIES}
    ${QtXml_LIBRARIES}
)

if(NOT BUILD_DYNAMIC_LINK_PYTHON)
    # executables have to be linked against python libraries,
    # because extension modules are not.
    list(APPEND FreeCADMainCmd_LIBS
        ${Python3_LIBRARIES}
    )
endif(NOT BUILD_DYNAMIC_LINK_PYTHON)

target_link_libraries(FreeCADMainCmd
    ${FreeCADMainCmd_LIBS}
)
target_compile_definitions(
    FreeCADMainCmd PRIVATE OPENFUSION_VERSION_SUFFIX="${OPENFUSION_VERSION_SUFFIX}"
)
if (FREECAD_WARN_ERROR)
    target_compile_warn_error(FreeCADMainCmd)
endif()

SET_BIN_DIR(FreeCADMainCmd FreeCADCmd)

if(UNIX AND NOT APPLE)
    set_property(
        TARGET FreeCADMainCmd APPEND PROPERTY
        INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}"
    )
endif()

add_custom_command(TARGET FreeCADMainCmd POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "$<TARGET_FILE:FreeCADMainCmd>"
        "$<TARGET_FILE_DIR:FreeCADMainCmd>/OpenFusionCmd$<TARGET_FILE_SUFFIX:FreeCADMainCmd>"
    VERBATIM
)

if(WIN32)
    INSTALL(TARGETS FreeCADMainCmd
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
elseif(APPLE AND NOT BUILD_WITH_CONDA)
    INSTALL(TARGETS FreeCADMainCmd
        RUNTIME DESTINATION MacOS
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
else()
    INSTALL(TARGETS FreeCADMainCmd
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    )
endif()

if(APPLE AND NOT BUILD_WITH_CONDA)
    set(OPENFUSION_CLI_INSTALL_DIR "MacOS")
else()
    set(OPENFUSION_CLI_INSTALL_DIR "${CMAKE_INSTALL_BINDIR}")
endif()
install(CODE "
    file(COPY_FILE
        \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_CLI_INSTALL_DIR}/FreeCADCmd${CMAKE_EXECUTABLE_SUFFIX}\"
        \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_CLI_INSTALL_DIR}/OpenFusionCmd${CMAKE_EXECUTABLE_SUFFIX}\"
        ONLY_IF_DIFFERENT
    )
")
if(UNIX AND NOT APPLE)
    install(CODE "
        file(REMOVE
            \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_CLI_INSTALL_DIR}/FreeCADCmd\"
        )
        file(CREATE_LINK
            OpenFusionCmd
            \"\$ENV{DESTDIR}\${CMAKE_INSTALL_PREFIX}/${OPENFUSION_CLI_INSTALL_DIR}/FreeCADCmd\"
            SYMBOLIC
        )
    ")
endif()

install(DIRECTORY DESTINATION "${CMAKE_INSTALL_DATADIR}/openfusion")
install(
    FILES
        "${CMAKE_SOURCE_DIR}/LICENSE"
        "${CMAKE_SOURCE_DIR}/NOTICE.md"
        "${CMAKE_SOURCE_DIR}/THIRD_PARTY_NOTICES.md"
    DESTINATION "${CMAKE_INSTALL_DATADIR}/doc/openfusion"
)

######################## FreeCADMainPy ########################

SET(FreeCADMainPy_SRCS
    MainPy.cpp
)

add_library(FreeCADMainPy SHARED ${FreeCADMainPy_SRCS})

target_link_libraries(FreeCADMainPy FreeCADApp)
if (FREECAD_WARN_ERROR)
    target_compile_warn_error(FreeCADMainPy)
endif()

SET_BIN_DIR(FreeCADMainPy FreeCAD)
SET_PYTHON_PREFIX_SUFFIX(FreeCADMainPy)

if(WIN32)
    INSTALL(TARGETS FreeCADMainPy
        RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
else(WIN32)
    INSTALL(TARGETS FreeCADMainPy
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
endif(WIN32)

######################## FreeCADGuiPy ########################
if(BUILD_GUI)

    SET(FreeCADGuiPy_SRCS
        FreeCADGuiPy.cpp
    )

    add_library(FreeCADGuiPy SHARED ${FreeCADGuiPy_SRCS})

    target_link_libraries(FreeCADGuiPy FreeCADGui)
    if (FREECAD_WARN_ERROR)
        target_compile_warn_error(FreeCADGuiPy)
    endif()

    SET_BIN_DIR(FreeCADGuiPy FreeCADGui)
    SET_PYTHON_PREFIX_SUFFIX(FreeCADGuiPy)
    if(WIN32)
        # Name clash with target "FreeCADGui"
        # Must be called "FreeCADGuiPy_d" and "FreeCADGuiPy" to work so override default
        set_target_properties(FreeCADGuiPy PROPERTIES PDB_NAME_DEBUG "FreeCADGuiPy_d")
        set_target_properties(FreeCADGuiPy PROPERTIES PDB_NAME_RELEASE "FreeCADGuiPy")
    endif(WIN32)

    if(WIN32)
        INSTALL(TARGETS FreeCADGuiPy
            RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        )
    else(WIN32)
        INSTALL(TARGETS FreeCADGuiPy
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
        )
    endif(WIN32)
endif(BUILD_GUI)
