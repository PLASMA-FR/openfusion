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
inline constexpr auto ownedWorkbenchMenuProperty = "OpenFusionOwnedWorkbenchMenuIdentity";

inline QString ownedWorkbenchIdentity(const QObject* object)
{
    return object->property(ownedWorkbenchMenuProperty).toString();
}

inline void markOwnedWorkbenchAction(QAction* action, const QString& identity)
{
    action->setProperty(ownedWorkbenchMenuProperty, identity);
}

inline void markOwnedWorkbenchMenu(QMenu* menu, const QString& identity)
{
    menu->setProperty(ownedWorkbenchMenuProperty, identity);
    markOwnedWorkbenchAction(menu->menuAction(), identity);
}

template<typename Container>
void detachOwnedWorkbenchActions(Container* container)
{
    const QList<QAction*> actions = container->actions();
    for (QAction* action : actions) {
        if (!ownedWorkbenchIdentity(action).isEmpty()) {
            container->removeAction(action);
        }
    }
}

template<typename Container>
QMenu* acquireOwnedWorkbenchMenu(
    Container* container,
    const QString& identity,
    const QString& title,
    QAction* before = nullptr
)
{
    QMenu* ownedMenu = nullptr;
    const QList<QMenu*> directMenus
        = container->template findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly);
    for (QMenu* menu : directMenus) {
        if (ownedWorkbenchIdentity(menu) == identity) {
            ownedMenu = menu;
            break;
        }
    }

    if (!ownedMenu) {
        ownedMenu = new QMenu(title, container);
        markOwnedWorkbenchMenu(ownedMenu, identity);
    }
    else {
        ownedMenu->setTitle(title);
    }

    if (before) {
        container->insertMenu(before, ownedMenu);
    }
    else {
        container->addMenu(ownedMenu);
    }
    ownedMenu->menuAction()->setVisible(true);
    return ownedMenu;
}

template<typename Container>
QAction* acquireOwnedWorkbenchSeparator(
    Container* container,
    const QString& identity,
    QAction* before = nullptr
)
{
    QAction* ownedAction = nullptr;
    const QList<QAction*> directActions
        = container->template findChildren<QAction*>(QString(), Qt::FindDirectChildrenOnly);
    for (QAction* action : directActions) {
        if (ownedWorkbenchIdentity(action) == identity) {
            ownedAction = action;
            break;
        }
    }

    if (!ownedAction) {
        ownedAction = new QAction(container);
        ownedAction->setSeparator(true);
        markOwnedWorkbenchAction(ownedAction, identity);
    }
    if (before) {
        container->insertAction(before, ownedAction);
    }
    else {
        container->addAction(ownedAction);
    }
    ownedAction->setVisible(true);
    return ownedAction;
}

inline void destroyOwnedWorkbenchMenus(QMenuBar* menuBar)
{
    QList<QPointer<QAction>> ownedActions;
    const QList<QAction*> directActions
        = menuBar->findChildren<QAction*>(QString(), Qt::FindDirectChildrenOnly);
    for (QAction* action : directActions) {
        if (!ownedWorkbenchIdentity(action).isEmpty()) {
            ownedActions.push_back(action);
        }
    }

    QList<QPointer<QMenu>> ownedMenus;
    const QList<QMenu*> directMenus
        = menuBar->findChildren<QMenu*>(QString(), Qt::FindDirectChildrenOnly);
    for (QMenu* menu : directMenus) {
        if (!ownedWorkbenchIdentity(menu).isEmpty()) {
            ownedMenus.push_back(menu);
        }
    }

    menuBar->setNativeMenuBar(false);
    detachOwnedWorkbenchActions(menuBar);
    for (const QPointer<QMenu>& menu : ownedMenus) {
        delete menu;
    }
    for (const QPointer<QAction>& action : ownedActions) {
        delete action;
    }
}
}  // namespace Gui::MenuManagerInternal

#endif  // GUI_MENUMANAGERCLEANUP_H
