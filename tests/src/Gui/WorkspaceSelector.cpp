// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QComboBox>
#include <QSignalSpy>
#include <QTest>

#include "Gui/WorkbenchSelector.h"

class testWorkspaceSelector: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void activatesDesignThroughPartDesignAndPersistsStableId()
    {
        QString activated;
        QString persisted;
        Gui::WorkspaceSelectionController controller(
            [](const QString& workbench) {
                return workbench == QStringLiteral("PartDesignWorkbench");
            },
            [&activated](const QString& workbench) {
                activated = workbench;
                return true;
            },
            [&persisted](const QString& workspace) { persisted = workspace; }
        );
        QSignalSpy changed(&controller, &Gui::WorkspaceSelectionController::workspaceChanged);

        QVERIFY(controller.activateWorkspace(QStringLiteral("Design")));
        QCOMPARE(activated, QStringLiteral("PartDesignWorkbench"));
        QCOMPARE(persisted, QStringLiteral("Design"));
        QCOMPARE(changed.count(), 1);
    }

    void failedActivationDoesNotPersist()
    {
        QString persisted;
        Gui::WorkspaceSelectionController controller(
            [](const QString&) { return true; },
            [](const QString&) { return false; },
            [&persisted](const QString& workspace) { persisted = workspace; }
        );

        QVERIFY(!controller.activateWorkspace(QStringLiteral("Design")));
        QVERIFY(persisted.isEmpty());
    }

    void externalWorkbenchChangesSynchronizeStableWorkspaceIds()
    {
        QString persisted;
        Gui::WorkspaceSelectionController controller(
            {},
            {},
            [&persisted](const QString& workspace) { persisted = workspace; }
        );
        QSignalSpy changed(&controller, &Gui::WorkspaceSelectionController::workspaceChanged);

        controller.synchronizeWorkbench(QStringLiteral("PartDesignWorkbench"));
        QCOMPARE(persisted, QStringLiteral("Design"));
        QCOMPARE(changed.takeFirst().at(0).toString(), QStringLiteral("Design"));

        controller.synchronizeWorkbench(QStringLiteral("SketcherWorkbench"));
        QCOMPARE(persisted, QStringLiteral("Workbench/SketcherWorkbench"));
        QCOMPARE(
            changed.takeFirst().at(0).toString(),
            QStringLiteral("Workbench/SketcherWorkbench")
        );
    }

    void unavailableDesignIsDisabledFailClosed()
    {
        bool activationCalled = false;
        Gui::WorkspaceSelectionController controller(
            [](const QString&) { return false; },
            [&activationCalled](const QString&) {
                activationCalled = true;
                return true;
            },
            [](const QString&) {}
        );

        QVERIFY(!controller.workspaceAvailable(QStringLiteral("Design")));
        QVERIFY(!controller.activateWorkspace(QStringLiteral("Design")));
        QVERIFY(!activationCalled);
    }

    void defaultAvailabilityRequiresRegisteredAndEnabledWorkbench()
    {
        const QString design = QStringLiteral("PartDesignWorkbench");

        QVERIFY(Gui::WorkspaceSelectionController::workbenchSelectable(
            design,
            {design, QStringLiteral("SketcherWorkbench")},
            {design}
        ));
        QVERIFY(!Gui::WorkspaceSelectionController::workbenchSelectable(
            design,
            {design},
            {QStringLiteral("SketcherWorkbench")}
        ));
        QVERIFY(!Gui::WorkspaceSelectionController::workbenchSelectable(
            design,
            {QStringLiteral("SketcherWorkbench")},
            {design}
        ));
    }

    void selectorIsAccessibleAndKeyboardFocusable()
    {
        Gui::WorkspaceSelectionController controller(
            [](const QString&) { return true; },
            [](const QString&) { return true; },
            [](const QString&) {}
        );
        QComboBox selector;
        controller.configureSelector(&selector);
        selector.addItem(QStringLiteral("Design"));
        selector.show();
        selector.activateWindow();
        selector.setFocus(Qt::TabFocusReason);

        QCOMPARE(selector.objectName(), QStringLiteral("OpenFusionWorkspaceSelector"));
        QCOMPARE(selector.accessibleName(), QStringLiteral("Workspace selector"));
        QCOMPARE(selector.focusPolicy(), Qt::StrongFocus);
        QTRY_VERIFY(selector.hasFocus());
    }
};

QTEST_MAIN(testWorkspaceSelector)

#include "WorkspaceSelector.moc"
