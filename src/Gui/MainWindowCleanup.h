// SPDX-License-Identifier: LGPL-2.1-or-later

#ifndef GUI_MAINWINDOWCLEANUP_H
#define GUI_MAINWINDOWCLEANUP_H

#include <QCoreApplication>
#include <QDockWidget>
#include <QList>
#include <QMainWindow>
#include <QPointer>
#include <QStatusBar>
#include <QToolBar>

namespace Gui::MainWindowInternal
{
inline QList<QPointer<QToolBar>> ownedToolBars(QMainWindow* mainWindow)
{
    QList<QPointer<QToolBar>> owned;
    const QList<QToolBar*> direct
        = mainWindow->findChildren<QToolBar*>(QString(), Qt::FindDirectChildrenOnly);
    for (QToolBar* toolBar : direct) {
        if (toolBar->parentWidget() == mainWindow) {
            owned.push_back(toolBar);
        }
    }
    return owned;
}

inline void destroyOwnedToolBars(
    QMainWindow* mainWindow,
    const QList<QPointer<QToolBar>>& owned
)
{
    for (const QPointer<QToolBar>& toolBar : owned) {
        if (toolBar) {
            mainWindow->removeToolBar(toolBar.data());
            if (toolBar) {
                QCoreApplication::removePostedEvents(toolBar.data(), QEvent::DeferredDelete);
                delete toolBar.data();
            }
        }
    }
}

inline QList<QPointer<QDockWidget>> ownedDockWidgets(QMainWindow* mainWindow)
{
    QList<QPointer<QDockWidget>> owned;
    const QList<QDockWidget*> direct
        = mainWindow->findChildren<QDockWidget*>(QString(), Qt::FindDirectChildrenOnly);
    for (QDockWidget* dockWidget : direct) {
        if (dockWidget->parentWidget() == mainWindow) {
            owned.push_back(dockWidget);
        }
    }
    return owned;
}

inline void destroyOwnedDockWidget(
    QMainWindow* mainWindow,
    const QPointer<QDockWidget>& dockWidget
)
{
    if (dockWidget) {
        mainWindow->removeDockWidget(dockWidget.data());
        if (dockWidget) {
            QCoreApplication::removePostedEvents(dockWidget.data(), QEvent::DeferredDelete);
            delete dockWidget.data();
        }
    }
}

inline void destroyOwnedDockWidgets(
    QMainWindow* mainWindow,
    const QList<QPointer<QDockWidget>>& owned
)
{
    for (const QPointer<QDockWidget>& dockWidget : owned) {
        destroyOwnedDockWidget(mainWindow, dockWidget);
    }
}

inline QList<QPointer<QStatusBar>> ownedStatusBars(QMainWindow* mainWindow)
{
    QList<QPointer<QStatusBar>> owned;
    const QList<QStatusBar*> direct
        = mainWindow->findChildren<QStatusBar*>(QString(), Qt::FindDirectChildrenOnly);
    for (QStatusBar* statusBar : direct) {
        if (statusBar->parentWidget() == mainWindow) {
            owned.push_back(statusBar);
        }
    }
    return owned;
}

inline void destroyOwnedStatusBars(
    QMainWindow* mainWindow,
    const QList<QPointer<QStatusBar>>& owned
)
{
    if (!owned.isEmpty()) {
        mainWindow->setStatusBar(nullptr);
    }
    for (const QPointer<QStatusBar>& statusBar : owned) {
        if (statusBar) {
            QCoreApplication::removePostedEvents(statusBar.data(), QEvent::DeferredDelete);
            delete statusBar.data();
        }
    }
}
}  // namespace Gui::MainWindowInternal

#endif  // GUI_MAINWINDOWCLEANUP_H
