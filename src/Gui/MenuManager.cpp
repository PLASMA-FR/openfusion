/***************************************************************************
 *   Copyright (c) 2005 Werner Mayer <wmayer[at]users.sourceforge.net>     *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


#include <QApplication>
#include <QMenu>
#include <QMenuBar>


#include "MenuManager.h"
#include "MenuManagerCleanup.h"
#include "Application.h"
#include "Command.h"
#include "MainWindow.h"


using namespace Gui;

MenuItem::MenuItem() = default;

MenuItem::MenuItem(MenuItem* item)
{
    if (item) {
        item->appendItem(this);
    }
}

MenuItem::~MenuItem()
{
    clear();
}

void MenuItem::setCommand(const std::string& name)
{
    _name = name;
}

std::string MenuItem::command() const
{
    return _name;
}

bool MenuItem::hasItems() const
{
    return !_items.isEmpty();
}

MenuItem* MenuItem::findItem(const std::string& name)
{
    if (_name == name) {
        return this;
    }
    else {
        for (auto& item : _items) {
            if (item->_name == name) {
                return item;
            }
        }
    }

    return nullptr;
}

MenuItem* MenuItem::findParentOf(const std::string& name)
{
    for (auto& item : _items) {
        if (item->_name == name) {
            return this;
        }
    }

    for (auto& item : _items) {
        if (item->findParentOf(name)) {
            return item;
        }
    }

    return nullptr;
}

MenuItem* MenuItem::copy() const
{
    auto root = new MenuItem;
    root->setCommand(command());

    for (auto& item : _items) {
        root->appendItem(item->copy());
    }

    return root;
}

uint MenuItem::count() const
{
    return _items.count();
}

void MenuItem::appendItem(MenuItem* item)
{
    _items.push_back(item);
}

bool MenuItem::insertItem(MenuItem* before, MenuItem* item)
{
    int pos = _items.indexOf(before);
    if (pos != -1) {
        _items.insert(pos, item);
        return true;
    }

    return false;
}

MenuItem* MenuItem::afterItem(MenuItem* item) const
{
    int pos = _items.indexOf(item);
    if (pos < 0 || pos + 1 == _items.size()) {
        return nullptr;
    }
    return _items.at(pos + 1);
}

void MenuItem::removeItem(MenuItem* item)
{
    int pos = _items.indexOf(item);
    if (pos != -1) {
        _items.removeAt(pos);
    }
}

void MenuItem::clear()
{
    for (auto& item : _items) {
        delete item;
    }
    _items.clear();
}

MenuItem& MenuItem::operator<<(const std::string& command)
{
    auto item = new MenuItem(this);
    item->setCommand(command);
    return *this;
}

MenuItem& MenuItem::operator<<(MenuItem* item)
{
    appendItem(item);
    return *this;
}

QList<MenuItem*> MenuItem::getItems() const
{
    return _items;
}

// -----------------------------------------------------------

MenuManager* MenuManager::_instance = nullptr;

MenuManager* MenuManager::getInstance()
{
    if (!_instance) {
        _instance = new MenuManager;
    }
    return _instance;
}

void MenuManager::destruct()
{
    delete _instance;
    _instance = nullptr;
}

MenuManager::MenuManager() = default;

MenuManager::~MenuManager() = default;

void MenuManager::setup(MenuItem* menuItems) const
{
    if (!menuItems) {
        return;  // empty menu bar
    }

    QMenuBar* menuBar = getMainWindow()->menuBar();

    // By right, it should be fine for more than one command action having the
    // same shortcut but in different workbench. It should not require manual
    // conflict resolving in this case, as the action in an inactive workbench
    // is expected to be inactive as well, or else user may experience
    // seemingly random shortcut miss firing based on the order he/she
    // switches workbenches. In fact, this may be considered as an otherwise
    // difficult to implement feature of context aware shortcut, where a
    // specific shortcut can activate different actions under different
    // workbenches.
    //
    // This works as expected for action adding to a toolbar. As Qt will ignore
    // actions inside an invisible toolbar.  However, Qt refuse to do the same
    // for actions in a hidden menu action of a menu bar. This is very likely a
    // Qt bug, as the behavior does not seem to conform to Qt's documentation
    // of Qt::ShortcutContext.
    //
    // Keep a bounded cache of menus by untranslated workbench identity. Only
    // the active workbench's roots are attached, so inactive shortcuts remain
    // out of the menu hierarchy without repeatedly creating native QMenus.
    MenuManagerInternal::detachOwnedWorkbenchActions(menuBar);
    QAction* firstExternalAction
        = menuBar->actions().isEmpty() ? nullptr : menuBar->actions().constFirst();
    int separatorIndex = 0;
    for (auto& item : menuItems->getItems()) {
        const QString identity = QString::fromLatin1(item->command().c_str());
        QAction* action = nullptr;
        if (item->command() == "Separator") {
            action = MenuManagerInternal::acquireOwnedWorkbenchSeparator(
                menuBar,
                QStringLiteral("Separator:%1").arg(separatorIndex++),
                firstExternalAction
            );
            action->setObjectName(QLatin1String("Separator"));
        }
        else {
            QMenu* menu = MenuManagerInternal::acquireOwnedWorkbenchMenu(
                menuBar,
                identity,
                QApplication::translate("Workbench", item->command().c_str()),
                firstExternalAction
            );
            action = menu->menuAction();
            menu->setObjectName(identity);
            action->setObjectName(identity);
        }
        action->setData(identity);

        // flll up the menu
        if (!action->isSeparator()) {
            setup(item, action->menu());
        }
    }

    // enable update again
    // menuBar->setUpdatesEnabled(true);
}

void MenuManager::setup(MenuItem* item, QMenu* menu) const
{
    CommandManager& mgr = Application::Instance->commandManager();
    MenuManagerInternal::detachOwnedWorkbenchActions(menu);
    QList<QAction*> actions = menu->actions();
    int separatorIndex = 0;
    for (auto& item : item->getItems()) {
        const QString identity = QString::fromLatin1(item->command().c_str());
        QList<QAction*> used_actions;
        if (item->command() == "Separator") {
            QAction* action = MenuManagerInternal::acquireOwnedWorkbenchSeparator(
                menu,
                QStringLiteral("Separator:%1").arg(separatorIndex++)
            );
            action->setObjectName(QLatin1String("Separator"));
            action->setData(QLatin1String("Separator"));
            used_actions.append(action);
        }
        else if (item->hasItems()) {
            QMenu* submenu = MenuManagerInternal::acquireOwnedWorkbenchMenu(
                menu,
                identity,
                QApplication::translate("Workbench", item->command().c_str())
            );
            QAction* action = submenu->menuAction();
            submenu->setObjectName(identity);
            action->setObjectName(identity);
            action->setData(identity);
            used_actions.append(action);
        }
        else {
            used_actions = findActions(actions, identity);
            if (used_actions.isEmpty()) {
                // A command can have more than one QAction
                int count = menu->actions().count();
                // Check if action was added successfully
                if (mgr.addTo(item->command().c_str(), menu)) {
                    QList<QAction*> acts = menu->actions();
                    for (int i = count; i < acts.count(); i++) {
                        QAction* act = acts[i];
                        act->setData(identity);
                        used_actions.append(act);
                    }
                }
            }
        }

        if (!item->hasItems() && item->command() != "Separator" && !used_actions.isEmpty()) {
            for (auto& action : used_actions) {
                // put the menu item at the end
                menu->removeAction(action);
                menu->addAction(action);
                int index = actions.indexOf(action);
                if (index >= 0) {
                    actions.removeAt(index);
                }
            }
        }

        // fill up the submenu
        if (item->hasItems() && !used_actions.isEmpty()) {
            setup(item, used_actions.front()->menu());
        }
    }

    // remove all menu items which we don't need for the moment
    for (auto& action : actions) {
        menu->removeAction(action);
    }
}

void MenuManager::retranslate() const
{
    QMenuBar* menuBar = getMainWindow()->menuBar();
    for (auto& action : menuBar->actions()) {
        if (action->menu()) {
            retranslate(action->menu());
        }
    }
}

void MenuManager::retranslate(QMenu* menu) const
{
    // Note: Here we search for all menus and submenus to retranslate their
    // titles. To ease the translation for each menu the native name is set
    // as user data. However, there are special menus that are created by
    // actions for which the name of the according command name is set. For
    // such menus we have to use the command's menu text instead. Examples
    // for such actions are Std_RecentFiles, Std_Workbench or Std_FreezeViews.
    CommandManager& mgr = Application::Instance->commandManager();
    QByteArray menuName = menu->menuAction()->data().toByteArray();
    Command* cmd = mgr.getCommandByName(menuName);
    if (cmd) {
        menu->setTitle(QApplication::translate(cmd->className(), cmd->getMenuText()));
    }
    else {
        menu->setTitle(QApplication::translate("Workbench", (const char*)menuName));
    }
    for (auto& action : menu->actions()) {
        if (action->menu()) {
            retranslate(action->menu());
        }
    }
}

QAction* MenuManager::findAction(const QList<QAction*>& acts, const QString& item) const
{
    for (auto& action : acts) {
        if (action->data().toString() == item) {
            return action;
        }
    }

    return nullptr;  // no item with the user data found
}

QList<QAction*> MenuManager::findActions(const QList<QAction*>& acts, const QString& item) const
{
    // It is possible that the user text of several actions match with 'item'.
    // But for the first match all following actions must match. For example
    // the Std_WindowsMenu command provides several actions with the same user
    // name.
    bool first_match = false;
    QList<QAction*> used;
    for (auto& action : acts) {
        if (action->data().toString() == item) {
            used.append(action);
            first_match = true;
            // get only one separator per request
            if (item == QLatin1String("Separator")) {
                break;
            }
        }
        else if (first_match) {
            break;
        }
    }

    return used;
}

void MenuManager::setupContextMenu(MenuItem* item, QMenu& menu) const
{
    setup(item, &menu);
}
