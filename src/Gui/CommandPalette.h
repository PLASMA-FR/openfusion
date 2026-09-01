// SPDX-License-Identifier: LGPL-2.1-or-later

#ifndef GUI_COMMANDPALETTE_H
#define GUI_COMMANDPALETTE_H

#include <boost/signals2/connection.hpp>

#include <FCGlobal.h>

#include <QAbstractListModel>
#include <QIcon>
#include <QPointer>
#include <QStringList>
#include <QVector>
#include <QDialog>

class QAction;
class QEvent;
class QKeyEvent;
class QLabel;
class QLineEdit;
class QListView;
class QSettings;
class QShowEvent;

namespace Gui
{

inline constexpr auto CommandPaletteIconName = "zoom-all";

struct GuiExport CommandPaletteEntry
{
    QString name;
    QString title;
    QString group;
    QString tooltip;
    QString shortcut;
    QIcon icon;
    QPointer<QAction> action;
};

class GuiExport CommandPaletteModel: public QAbstractListModel
{
    Q_OBJECT

public:
    enum Role
    {
        NameRole = Qt::UserRole + 1,
        MetaRole,
        ShortcutRole,
        EnabledRole
    };
    Q_ENUM(Role)

    explicit CommandPaletteModel(QObject* parent = nullptr);

    int rowCount(const QModelIndex& parent = QModelIndex()) const override;
    QVariant data(const QModelIndex& index, int role = Qt::DisplayRole) const override;
    Qt::ItemFlags flags(const QModelIndex& index) const override;

    void setEntries(QVector<CommandPaletteEntry> entries);
    void setQuery(const QString& query);
    QString query() const;

    void setRecentCommands(const QStringList& commands);
    QStringList recentCommands() const;
    void recordUse(const QString& commandName);

    QAction* actionAt(const QModelIndex& index) const;
    QString commandNameAt(const QModelIndex& index) const;
    int firstEnabledRow() const;

    static int fuzzyScore(const QString& query, const QString& candidate);

private:
    const CommandPaletteEntry* entryAt(const QModelIndex& index) const;
    void rebuildVisibleEntries();
    void resetVisibleEntries();
    void refreshActionState();

    QVector<CommandPaletteEntry> _entries;
    QVector<int> _visibleEntries;
    QVector<QMetaObject::Connection> _actionConnections;
    QStringList _recentCommands;
    QString _query;
};

class GuiExport CommandPalette: public QDialog
{
    Q_OBJECT

public:
    explicit CommandPalette(QWidget* parent = nullptr, CommandPaletteModel* model = nullptr);
    ~CommandPalette() override;

public Q_SLOTS:
    void showPalette();

Q_SIGNALS:
    void commandTriggered(const QString& commandName);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void showEvent(QShowEvent* event) override;

private Q_SLOTS:
    void refreshIfVisible();

private:
    void refreshEntries();
    void selectFirstEnabledEntry();
    void moveCurrentEntry(int offset);
    void activateCurrentEntry();
    void closePalette();
    void updateEmptyState();
    void saveHistory();

    CommandPaletteModel* _model = nullptr;
    QLineEdit* _search = nullptr;
    QListView* _results = nullptr;
    QLabel* _emptyState = nullptr;
    QLabel* _shortcutHint = nullptr;
    QSettings* _settings = nullptr;
    bool _usesCommandManager = false;
    bool _activationPending = false;
    boost::signals2::scoped_connection _commandConnection;
};

}  // namespace Gui

#endif  // GUI_COMMANDPALETTE_H
