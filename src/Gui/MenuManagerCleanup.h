// SPDX-License-Identifier: LGPL-2.1-or-later

#ifndef GUI_MENUMANAGERCLEANUP_H
#define GUI_MENUMANAGERCLEANUP_H

#include <QAction>
#include <QList>
#include <QMenu>
#include <QMenuBar>
#include <QPointer>
#include <QString>

namespace Gui::MenuManagerInternal
{
inline constexpr auto ownedWorkbenchMenuProperty = "OpenFusionOwnedWorkbenchMenu";

inline void markOwnedWorkbenchAction(QAction* action)
{
    action->setProperty(ownedWorkbenchMenuProperty, true);
}

inline void markOwnedWorkbenchMenu(QMenu* menu)
{
    menu->setProperty(ownedWorkbenchMenuProperty, true);
    markOwnedWorkbenchAction(menu->menuAction());
}

inline QAction* addOwnedWorkbenchSeparator(QMenuBar* menuBar)
{
    QAction* action = menuBar->addSeparator();
    markOwnedWorkbenchAction(action);
    return action;
}

inline QMenu* addOwnedWorkbenchMenu(QMenuBar* menuBar, const QString& title)
{
    QMenu* menu = menuBar->addMenu(title);
    markOwnedWorkbenchMenu(menu);
    return menu;
}

inline void clearOwnedWorkbenchMenus(QMenuBar* menuBar)
{
    QList<QPointer<QAction>> ownedActions;
    QList<QPointer<QMenu>> ownedMenus;
    for (QAction* action :
         menuBar->findChildren<QAction*>(QString(), Qt::FindDirectChildrenOnly)) {
        if (action->property(ownedWorkbenchMenuProperty).toBool()) {
            ownedActions.push_back(action);
        }
    }
    for (QMenu* menu : menuBar->findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly)) {
        if (menu->property(ownedWorkbenchMenuProperty).toBool()) {
            ownedMenus.push_back(menu);
        }
    }

    menuBar->clear();
    for (const QPointer<QMenu>& menu : ownedMenus) {
        delete menu;
    }
    for (const QPointer<QAction>& action : ownedActions) {
        delete action;
    }
}
}  // namespace Gui::MenuManagerInternal

#endif  // GUI_MENUMANAGERCLEANUP_H
