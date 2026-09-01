// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QAction>
#include <QMenu>
#include <QMenuBar>
#include <QPointer>
#include <QTest>

#include <array>

#include "Gui/MenuManagerCleanup.h"

class testMenuManager: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void repeatedRebuildReusesOwnedMenusAndBoundsTheCache()
    {
        QMenuBar menuBar;
        auto* externalRoot = new QMenu(QStringLiteral("External"), &menuBar);
        auto* sharedNested = new QMenu(QStringLiteral("Shared nested"));
        QPointer<QMenu> externalRootGuard(externalRoot);
        QPointer<QMenu> sharedNestedGuard(sharedNested);
        std::array<QPointer<QMenu>, 4> cachedRoots;
        std::array<QPointer<QMenu>, 4> cachedNestedMenus;
        std::array<QPointer<QAction>, 4> cachedSeparators;
        menuBar.addMenu(externalRoot);

        for (int iteration = 0; iteration < 64; ++iteration) {
            Gui::MenuManagerInternal::detachOwnedWorkbenchActions(&menuBar);
            QVERIFY(!externalRootGuard.isNull());
            QVERIFY(!sharedNestedGuard.isNull());
            QVERIFY(menuBar.actions().contains(externalRoot->menuAction()));

            const int firstIdentity = iteration % 2;
            for (int offset = 0; offset < 3; ++offset) {
                const int identityIndex = firstIdentity + offset;
                const QString identity = QStringLiteral("Managed%1").arg(identityIndex);
                QMenu* root = Gui::MenuManagerInternal::acquireOwnedWorkbenchMenu(
                    &menuBar,
                    identity,
                    identity,
                    externalRoot->menuAction()
                );
                if (cachedRoots[identityIndex]) {
                    QCOMPARE(root, cachedRoots[identityIndex].data());
                }
                else {
                    cachedRoots[identityIndex] = root;
                }

                Gui::MenuManagerInternal::detachOwnedWorkbenchActions(root);
                QMenu* nested = Gui::MenuManagerInternal::acquireOwnedWorkbenchMenu(
                    root,
                    QStringLiteral("Nested"),
                    QStringLiteral("Nested")
                );
                if (cachedNestedMenus[identityIndex]) {
                    QCOMPARE(nested, cachedNestedMenus[identityIndex].data());
                }
                else {
                    cachedNestedMenus[identityIndex] = nested;
                }

                QAction* separator = Gui::MenuManagerInternal::acquireOwnedWorkbenchSeparator(
                    root,
                    QStringLiteral("Separator:0")
                );
                if (cachedSeparators[identityIndex]) {
                    QCOMPARE(separator, cachedSeparators[identityIndex].data());
                }
                else {
                    cachedSeparators[identityIndex] = separator;
                }
            }

            if (cachedRoots[0] && !cachedRoots[0]->actions().contains(sharedNested->menuAction())) {
                cachedRoots[0]->addMenu(sharedNested);
            }

            const QList<QMenu*> directMenus
                = menuBar.findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly);
            QVERIFY(directMenus.size() <= 5);
            QVERIFY(menuBar.actions().contains(externalRoot->menuAction()));
            menuBar.removeAction(cachedRoots[firstIdentity + 2]->menuAction());
            cachedRoots[firstIdentity + 2]->removeAction(
                cachedSeparators[firstIdentity + 2].data()
            );
        }

        Gui::MenuManagerInternal::destroyOwnedWorkbenchMenus(&menuBar);
        for (const QPointer<QMenu>& menu : cachedRoots) {
            QVERIFY(menu.isNull());
        }
        for (const QPointer<QMenu>& menu : cachedNestedMenus) {
            QVERIFY(menu.isNull());
        }
        for (const QPointer<QAction>& action : cachedSeparators) {
            QVERIFY(action.isNull());
        }
        QVERIFY(!externalRootGuard.isNull());
        QVERIFY(!sharedNestedGuard.isNull());
        QVERIFY(!menuBar.isNativeMenuBar());
        QCOMPARE(
            menuBar.findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly).size(),
            1
        );

        delete sharedNested;
    }
};

QTEST_MAIN(testMenuManager)

#include "MenuManager.moc"
