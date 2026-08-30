# SPDX-License-Identifier: LGPL-2.1-or-later

set(OPENFUSION_ACCEPTANCE_OUTPUT_DIR
    "${CMAKE_BINARY_DIR}/Testing/OpenFusionAcceptance"
)
file(MAKE_DIRECTORY "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}")

if(BUILD_GUI)
    add_test(
        NAME OpenFusion_GUI_SystemExit_Propagation
        COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/OpenFusionGuiSystemExitRegression.py"
            --freecad $<TARGET_FILE:FreeCADMain>
            --state-dir "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/GuiSystemExit"
    )
    set_tests_properties(OpenFusion_GUI_SystemExit_Propagation PROPERTIES
        LABELS "acceptance;gui;lifecycle;cleanup"
        RUN_SERIAL TRUE
        TIMEOUT 330
    )
    if(WIN32)
        set_property(
            TEST OpenFusion_GUI_SystemExit_Propagation
            APPEND
            PROPERTY ENVIRONMENT ${OPENFUSION_WINDOWS_QT_TEST_ENVIRONMENT}
        )
    endif()
endif()

add_test(
    NAME OpenFusion_Core_Acceptance
    COMMAND $<TARGET_FILE:FreeCADMainCmd>
        --safe-mode
        --user-cfg "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/user.cfg"
        --system-cfg "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/system.cfg"
        --log-file "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/FreeCADCmd.log"
        --python-path "${CMAKE_CURRENT_SOURCE_DIR}"
        -t OpenFusionCoreAcceptance
)

set_tests_properties(OpenFusion_Core_Acceptance PROPERTIES
    ENVIRONMENT
        "OPENFUSION_ACCEPTANCE_OUTPUT_DIR=${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}"
    FIXTURES_SETUP OpenFusionCoreModel
    LABELS "acceptance;core;serialization;interoperability"
    RUN_SERIAL TRUE
    TIMEOUT 300
)

if(BUILD_ASSEMBLY AND BUILD_GUI)
    add_test(
        NAME OpenFusion_Assembly_Acceptance
        COMMAND $<TARGET_FILE:FreeCADMainCmd>
            --safe-mode
            --user-cfg "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/assembly-user.cfg"
            --system-cfg "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/assembly-system.cfg"
            --log-file "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/FreeCADCmd-assembly.log"
            --python-path "${CMAKE_CURRENT_SOURCE_DIR}"
            -t OpenFusionAssemblyAcceptance
    )
    set_tests_properties(OpenFusion_Assembly_Acceptance PROPERTIES
        ENVIRONMENT
            "OPENFUSION_ACCEPTANCE_OUTPUT_DIR=${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}"
        FIXTURES_REQUIRED OpenFusionCoreModel
        LABELS "acceptance;assembly;serialization"
        RUN_SERIAL TRUE
        TIMEOUT 300
    )
endif()

if(BUILD_TECHDRAW)
    add_test(
        NAME OpenFusion_TechDraw_Acceptance
        COMMAND $<TARGET_FILE:FreeCADMainCmd>
            --safe-mode
            --user-cfg "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/techdraw-user.cfg"
            --system-cfg "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/techdraw-system.cfg"
            --log-file "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}/FreeCADCmd-techdraw.log"
            --python-path "${CMAKE_CURRENT_SOURCE_DIR}"
            -t OpenFusionTechDrawAcceptance
    )
    set_tests_properties(OpenFusion_TechDraw_Acceptance PROPERTIES
        ENVIRONMENT
            "OPENFUSION_ACCEPTANCE_OUTPUT_DIR=${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}"
        FIXTURES_REQUIRED OpenFusionCoreModel
        LABELS "acceptance;techdraw;serialization"
        RUN_SERIAL TRUE
        TIMEOUT 300
    )
endif()
