# SPDX-License-Identifier: LGPL-2.1-or-later

set(OPENFUSION_ACCEPTANCE_OUTPUT_DIR
    "${CMAKE_BINARY_DIR}/Testing/OpenFusionAcceptance"
)
file(MAKE_DIRECTORY "${OPENFUSION_ACCEPTANCE_OUTPUT_DIR}")

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
    LABELS "acceptance;core;serialization;interoperability"
    RUN_SERIAL TRUE
    TIMEOUT 300
)
