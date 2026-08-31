// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QAction>
#include <QMenu>
#include <QMenuBar>
#include <QPointer>
#include <QTest>

#include "Gui/MenuManagerCleanup.h"

class testMenuManager: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void repeatedRebuildDeletesOnlyTaggedOwnedMenus()
    {
        QMenuBar menuBar;
        auto* externalRoot = new QMenu(QStringLiteral("External"), &menuBar);
        auto* sharedNested = new QMenu(QStringLiteral("Shared nested"));
        QPointer<QMenu> externalRootGuard(externalRoot);
        QPointer<QMenu> sharedNestedGuard(sharedNested);
        QList<QPointer<QMenu>> previousRoots;
        QList<QPointer<QMenu>> previousNestedMenus;
        QPointer<QAction> previousSeparator;

        for (int iteration = 0; iteration < 64; ++iteration) {
            Gui::MenuManagerInternal::clearOwnedWorkbenchMenus(&menuBar);

            for (const QPointer<QMenu>& menu : previousRoots) {
                QVERIFY(menu.isNull());
            }
            for (const QPointer<QMenu>& menu : previousNestedMenus) {
                QVERIFY(menu.isNull());
            }
            QVERIFY(previousSeparator.isNull());
            QVERIFY(!externalRootGuard.isNull());
            QVERIFY(!sharedNestedGuard.isNull());
            QCOMPARE(
                menuBar.findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly).size(),
                1
            );

            menuBar.addMenu(externalRoot);
            previousRoots.clear();
            previousNestedMenus.clear();
            for (int menuIndex = 0; menuIndex < 3; ++menuIndex) {
                QMenu* root = Gui::MenuManagerInternal::addOwnedWorkbenchMenu(
                    &menuBar,
                    QStringLiteral("Managed %1-%2").arg(iteration).arg(menuIndex)
                );
                QMenu* nested = root->addMenu(QStringLiteral("Nested"));
                previousRoots.push_back(root);
                previousNestedMenus.push_back(nested);
            }
            menuBar.removeAction(previousRoots.constLast().data()->menuAction());
            previousRoots.constFirst().data()->addMenu(sharedNested);
            QAction* separator
                = Gui::MenuManagerInternal::addOwnedWorkbenchSeparator(&menuBar);
            menuBar.removeAction(separator);
            previousSeparator = separator;

            QCOMPARE(
                menuBar.findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly).size(),
                4
            );
        }

        Gui::MenuManagerInternal::clearOwnedWorkbenchMenus(&menuBar);
        for (const QPointer<QMenu>& menu : previousRoots) {
            QVERIFY(menu.isNull());
        }
        for (const QPointer<QMenu>& menu : previousNestedMenus) {
            QVERIFY(menu.isNull());
        }
        QVERIFY(previousSeparator.isNull());
        QVERIFY(!externalRootGuard.isNull());
        QVERIFY(!sharedNestedGuard.isNull());
        QCOMPARE(
            menuBar.findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly).size(),
            1
        );

        delete sharedNested;
    }
};

QTEST_MAIN(testMenuManager)

#include "MenuManager.moc"
