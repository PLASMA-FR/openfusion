// SPDX-License-Identifier: LGPL-2.1-or-later

#include "CommandPalette.h"

#include <algorithm>
#include <limits>

#include <QAction>
#include <QApplication>
#include <QFontMetrics>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListView>
#include <QPainter>
#include <QSettings>
#include <QShowEvent>
#include <QStyle>
#include <QStyleOptionViewItem>
#include <QStyledItemDelegate>
#include <QTimer>
#include <QVBoxLayout>

#include "Action.h"
#include "Application.h"
#include "Command.h"

using namespace Gui;

namespace
{

constexpr auto recentCommandsKey = "OpenFusion/CommandPalette/RecentCommands";
constexpr int maxRecentCommands = 12;

bool isWordBoundary(const QString& text, int index)
{
    return index == 0 || !text.at(index - 1).isLetterOrNumber();
}

int entryScore(
    const CommandPaletteEntry& entry,
    const QString& query,
    const QStringList& recentCommands
)
{
    const QStringList tokens = query.simplified().split(QLatin1Char(' '), Qt::SkipEmptyParts);
    if (tokens.isEmpty()) {
        const int recentIndex = recentCommands.indexOf(entry.name);
        const int recentScore = recentIndex < 0 ? 0 : 100000 - recentIndex;
        const int enabledScore = entry.action && entry.action->isEnabled() ? 1000 : 0;
        return recentScore + enabledScore;
    }

    int score = 0;
    for (const QString& token : tokens) {
        int best = CommandPaletteModel::fuzzyScore(token, entry.title);

        const int nameScore = CommandPaletteModel::fuzzyScore(token, entry.name);
        if (nameScore >= 0) {
            best = std::max(best, nameScore - 150);
        }

        const int groupScore = CommandPaletteModel::fuzzyScore(token, entry.group);
        if (groupScore >= 0) {
            best = std::max(best, groupScore - 350);
        }

        const int tooltipScore = CommandPaletteModel::fuzzyScore(token, entry.tooltip);
        if (tooltipScore >= 0) {
            best = std::max(best, tooltipScore - 500);
        }

        const int shortcutScore = CommandPaletteModel::fuzzyScore(token, entry.shortcut);
        if (shortcutScore >= 0) {
            best = std::max(best, shortcutScore - 600);
        }

        if (best < 0) {
            return -1;
        }
        score += best;
    }

    const int recentIndex = recentCommands.indexOf(entry.name);
    if (recentIndex >= 0) {
        score += std::max(20, 250 - recentIndex * 15);
    }
    if (entry.action && entry.action->isEnabled()) {
        score += 20;
    }
    return score;
}

class CommandPaletteDelegate final: public QStyledItemDelegate
{
public:
    explicit CommandPaletteDelegate(QObject* parent)
        : QStyledItemDelegate(parent)
    {}

    QSize sizeHint(const QStyleOptionViewItem& option, const QModelIndex& index) const override
    {
        Q_UNUSED(option);
        Q_UNUSED(index);
        return {0, 58};
    }

    void paint(
        QPainter* painter,
        const QStyleOptionViewItem& option,
        const QModelIndex& index
    ) const override
    {
        QStyleOptionViewItem panel(option);
        initStyleOption(&panel, index);
        panel.text.clear();
        panel.icon = {};
        const QStyle* style = option.widget ? option.widget->style() : QApplication::style();
        style->drawControl(QStyle::CE_ItemViewItem, &panel, painter, option.widget);

        const bool enabled = index.data(CommandPaletteModel::EnabledRole).toBool();
        const bool selected = option.state.testFlag(QStyle::State_Selected);
        const QPalette::ColorGroup colorGroup = enabled ? QPalette::Active : QPalette::Disabled;
        const QPalette::ColorRole textRole = selected ? QPalette::HighlightedText : QPalette::Text;

        painter->save();
        QRect content = option.rect.adjusted(12, 7, -12, -7);
        const QIcon icon = qvariant_cast<QIcon>(index.data(Qt::DecorationRole));
        if (!icon.isNull()) {
            const QSize iconSize(24, 24);
            const QRect iconRect(
                content.left(),
                content.center().y() - iconSize.height() / 2,
                iconSize.width(),
                iconSize.height()
            );
            icon.paint(
                painter,
                iconRect,
                Qt::AlignCenter,
                enabled ? QIcon::Normal : QIcon::Disabled
            );
            content.setLeft(iconRect.right() + 12);
        }

        const QString shortcut = index.data(CommandPaletteModel::ShortcutRole).toString();
        QFont shortcutFont = option.font;
        shortcutFont.setPointSizeF(std::max(7.0, shortcutFont.pointSizeF() - 1.0));
        const int shortcutWidth = shortcut.isEmpty()
            ? 0
            : QFontMetrics(shortcutFont).horizontalAdvance(shortcut) + 12;

        QRect titleRect = content;
        titleRect.setBottom(content.center().y() + 1);
        titleRect.setRight(titleRect.right() - shortcutWidth);
        QFont titleFont = option.font;
        titleFont.setBold(true);
        painter->setFont(titleFont);
        painter->setPen(option.palette.color(colorGroup, textRole));
        painter->drawText(
            titleRect,
            Qt::AlignLeft | Qt::AlignVCenter,
            QFontMetrics(titleFont).elidedText(
                index.data(Qt::DisplayRole).toString(),
                Qt::ElideRight,
                titleRect.width()
            )
        );

        QRect metaRect = content;
        metaRect.setTop(content.center().y() + 1);
        QFont metaFont = option.font;
        metaFont.setPointSizeF(std::max(7.0, metaFont.pointSizeF() - 1.0));
        painter->setFont(metaFont);
        const QPalette::ColorRole metaRole = selected ? QPalette::HighlightedText : QPalette::PlaceholderText;
        painter->setPen(option.palette.color(colorGroup, metaRole));
        painter->drawText(
            metaRect,
            Qt::AlignLeft | Qt::AlignVCenter,
            QFontMetrics(metaFont).elidedText(
                index.data(CommandPaletteModel::MetaRole).toString(),
                Qt::ElideRight,
                metaRect.width()
            )
        );

        if (!shortcut.isEmpty()) {
            QRect shortcutRect = content;
            shortcutRect.setLeft(shortcutRect.right() - shortcutWidth);
            painter->setFont(shortcutFont);
            painter->setPen(option.palette.color(colorGroup, textRole));
            painter->drawText(shortcutRect, Qt::AlignRight | Qt::AlignVCenter, shortcut);
        }
        painter->restore();
    }
};

}  // namespace

CommandPaletteModel::CommandPaletteModel(QObject* parent)
    : QAbstractListModel(parent)
{}

int CommandPaletteModel::rowCount(const QModelIndex& parent) const
{
    return parent.isValid() ? 0 : _visibleEntries.size();
}

QVariant CommandPaletteModel::data(const QModelIndex& index, int role) const
{
    const CommandPaletteEntry* entry = entryAt(index);
    if (!entry) {
        return {};
    }

    const bool enabled = entry->action && entry->action->isEnabled();
    switch (role) {
        case Qt::DisplayRole:
            return entry->title;
        case Qt::DecorationRole:
            return entry->icon;
        case Qt::ToolTipRole:
            return enabled
                ? entry->tooltip
                : tr("%1\nUnavailable in the current context").arg(entry->tooltip);
        case Qt::AccessibleTextRole: {
            QString description = entry->title;
            if (!entry->shortcut.isEmpty()) {
                description += tr(", shortcut %1").arg(entry->shortcut);
            }
            if (!enabled) {
                description += tr(", unavailable in the current context");
            }
            return description;
        }
        case NameRole:
            return entry->name;
        case MetaRole:
            return entry->group.isEmpty()
                ? entry->name
                : tr("%1 - %2").arg(entry->group, entry->name);
        case ShortcutRole:
            return entry->shortcut;
        case EnabledRole:
            return enabled;
        default:
            return {};
    }
}

Qt::ItemFlags CommandPaletteModel::flags(const QModelIndex& index) const
{
    const CommandPaletteEntry* entry = entryAt(index);
    if (!entry) {
        return Qt::NoItemFlags;
    }

    Qt::ItemFlags result = Qt::ItemIsSelectable;
    if (entry->action && entry->action->isEnabled()) {
        result |= Qt::ItemIsEnabled;
    }
    return result;
}

void CommandPaletteModel::setEntries(QVector<CommandPaletteEntry> entries)
{
    for (const QMetaObject::Connection& connection : _actionConnections) {
        QObject::disconnect(connection);
    }
    _actionConnections.clear();

    beginResetModel();
    _entries = std::move(entries);
    rebuildVisibleEntries();
    endResetModel();

    for (const CommandPaletteEntry& entry : _entries) {
        if (!entry.action) {
            continue;
        }
        _actionConnections.push_back(connect(entry.action, &QAction::changed, this, [this]() {
            refreshActionState();
        }));
        _actionConnections.push_back(connect(entry.action, &QObject::destroyed, this, [this]() {
            refreshActionState();
        }));
    }
}

void CommandPaletteModel::setQuery(const QString& query)
{
    const QString simplified = query.simplified();
    if (_query == simplified) {
        return;
    }
    _query = simplified;
    resetVisibleEntries();
}

QString CommandPaletteModel::query() const
{
    return _query;
}

void CommandPaletteModel::setRecentCommands(const QStringList& commands)
{
    QStringList normalized;
    normalized.reserve(std::min(commands.size(), static_cast<qsizetype>(maxRecentCommands)));
    for (const QString& command : commands) {
        if (!command.isEmpty() && !normalized.contains(command)) {
            normalized.push_back(command);
        }
        if (normalized.size() == maxRecentCommands) {
            break;
        }
    }
    if (_recentCommands == normalized) {
        return;
    }
    _recentCommands = normalized;
    resetVisibleEntries();
}

QStringList CommandPaletteModel::recentCommands() const
{
    return _recentCommands;
}

void CommandPaletteModel::recordUse(const QString& commandName)
{
    QStringList recent = _recentCommands;
    recent.removeAll(commandName);
    recent.prepend(commandName);
    setRecentCommands(recent);
}

QAction* CommandPaletteModel::actionAt(const QModelIndex& index) const
{
    const CommandPaletteEntry* entry = entryAt(index);
    return entry ? entry->action.data() : nullptr;
}

QString CommandPaletteModel::commandNameAt(const QModelIndex& index) const
{
    const CommandPaletteEntry* entry = entryAt(index);
    return entry ? entry->name : QString();
}

int CommandPaletteModel::firstEnabledRow() const
{
    for (int row = 0; row < _visibleEntries.size(); ++row) {
        const auto& entry = _entries.at(_visibleEntries.at(row));
        if (entry.action && entry.action->isEnabled()) {
            return row;
        }
    }
    return -1;
}

int CommandPaletteModel::fuzzyScore(const QString& query, const QString& candidate)
{
    const QString needle = query.trimmed().toCaseFolded();
    const QString haystack = candidate.simplified().toCaseFolded();
    if (needle.isEmpty()) {
        return 0;
    }
    if (haystack.isEmpty()) {
        return -1;
    }
    if (needle == haystack) {
        return 10000;
    }

    const int substringIndex = haystack.indexOf(needle);
    if (substringIndex >= 0) {
        if (substringIndex == 0) {
            return 8000 - haystack.size();
        }
        if (isWordBoundary(haystack, substringIndex)) {
            return 7000 - substringIndex - haystack.size();
        }
        return 6000 - substringIndex - haystack.size();
    }

    int score = 1000;
    int previous = -1;
    int consecutive = 0;
    for (const QChar character : needle) {
        const int position = haystack.indexOf(character, previous + 1);
        if (position < 0) {
            return -1;
        }

        const int gap = position - previous - 1;
        if (gap == 0) {
            ++consecutive;
            score += 45 + consecutive * 12;
        }
        else {
            consecutive = 0;
            score += 30 - gap * 3;
        }
        if (isWordBoundary(haystack, position)) {
            score += 80;
        }
        previous = position;
    }
    return score - haystack.size();
}

const CommandPaletteEntry* CommandPaletteModel::entryAt(const QModelIndex& index) const
{
    if (!index.isValid() || index.parent().isValid() || index.row() < 0
        || index.row() >= _visibleEntries.size()) {
        return nullptr;
    }
    return &_entries.at(_visibleEntries.at(index.row()));
}

void CommandPaletteModel::rebuildVisibleEntries()
{
    struct RankedEntry
    {
        int index;
        int score;
    };

    QVector<RankedEntry> ranked;
    ranked.reserve(_entries.size());
    for (int index = 0; index < _entries.size(); ++index) {
        const int score = entryScore(_entries.at(index), _query, _recentCommands);
        if (score >= 0) {
            ranked.push_back({index, score});
        }
    }

    std::stable_sort(ranked.begin(), ranked.end(), [this](const RankedEntry& left, const RankedEntry& right) {
        if (left.score != right.score) {
            return left.score > right.score;
        }
        const auto& leftEntry = _entries.at(left.index);
        const auto& rightEntry = _entries.at(right.index);
        const bool leftEnabled = leftEntry.action && leftEntry.action->isEnabled();
        const bool rightEnabled = rightEntry.action && rightEntry.action->isEnabled();
        if (leftEnabled != rightEnabled) {
            return leftEnabled;
        }
        const int titleOrder = QString::localeAwareCompare(leftEntry.title, rightEntry.title);
        return titleOrder == 0 ? leftEntry.name < rightEntry.name : titleOrder < 0;
    });

    _visibleEntries.clear();
    _visibleEntries.reserve(ranked.size());
    for (const RankedEntry& entry : ranked) {
        _visibleEntries.push_back(entry.index);
    }
}

void CommandPaletteModel::resetVisibleEntries()
{
    beginResetModel();
    rebuildVisibleEntries();
    endResetModel();
}

void CommandPaletteModel::refreshActionState()
{
    resetVisibleEntries();
}

CommandPalette::CommandPalette(QWidget* parent, CommandPaletteModel* model)
    : QDialog(parent, Qt::Tool | Qt::FramelessWindowHint)
    , _model(model ? model : new CommandPaletteModel(this))
    , _usesCommandManager(model == nullptr)
{
    setObjectName(QStringLiteral("openFusionCommandPalette"));
    setWindowTitle(tr("Command Palette"));
    setModal(false);
    setMinimumSize(480, 320);
    resize(680, 480);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(18, 16, 18, 14);
    layout->setSpacing(10);

    auto* header = new QHBoxLayout;
    auto* title = new QLabel(tr("Command Palette"), this);
    QFont titleFont = title->font();
    titleFont.setBold(true);
    titleFont.setPointSizeF(titleFont.pointSizeF() + 2.0);
    title->setFont(titleFont);
    header->addWidget(title);
    header->addStretch();
    _shortcutHint = new QLabel(this);
    _shortcutHint->setObjectName(QStringLiteral("commandPaletteShortcutHint"));
    _shortcutHint->setVisible(false);
    header->addWidget(_shortcutHint);
    layout->addLayout(header);

    _search = new QLineEdit(this);
    _search->setObjectName(QStringLiteral("commandPaletteSearch"));
    _search->setPlaceholderText(tr("Search commands..."));
    _search->setClearButtonEnabled(true);
    _search->setAccessibleName(tr("Search commands"));
    layout->addWidget(_search);

    _results = new QListView(this);
    _results->setObjectName(QStringLiteral("commandPaletteResults"));
    _results->setModel(_model);
    _results->setItemDelegate(new CommandPaletteDelegate(_results));
    _results->setSelectionMode(QAbstractItemView::SingleSelection);
    _results->setUniformItemSizes(true);
    _results->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    _results->setAccessibleName(tr("Matching commands"));
    layout->addWidget(_results, 1);

    _emptyState = new QLabel(tr("No matching commands"), this);
    _emptyState->setObjectName(QStringLiteral("commandPaletteEmptyState"));
    _emptyState->setAlignment(Qt::AlignCenter);
    _emptyState->setAccessibleName(tr("No matching commands"));
    layout->addWidget(_emptyState, 1);

    auto* footer = new QLabel(tr("Up/Down Navigate | Enter Run | Esc Close"), this);
    footer->setAlignment(Qt::AlignCenter);
    layout->addWidget(footer);

    connect(_search, &QLineEdit::textChanged, this, [this](const QString& text) {
        _model->setQuery(text);
        selectFirstEnabledEntry();
        updateEmptyState();
    });
    connect(_search, &QLineEdit::returnPressed, this, &CommandPalette::activateCurrentEntry);
    connect(_results, &QListView::activated, this, [this](const QModelIndex&) {
        activateCurrentEntry();
    });
    connect(_results, &QListView::doubleClicked, this, [this](const QModelIndex&) {
        activateCurrentEntry();
    });
    connect(_model, &QAbstractItemModel::modelReset, this, [this]() {
        selectFirstEnabledEntry();
        updateEmptyState();
    });

    _search->installEventFilter(this);
    _results->installEventFilter(this);

    if (_usesCommandManager) {
        _settings = new QSettings(this);
        if (Application::Instance) {
            QPointer<CommandPalette> guard(this);
            _commandConnection = Application::Instance->commandManager().signalChanged.connect([guard]() {
                if (guard) {
                    QMetaObject::invokeMethod(
                        guard.data(),
                        "refreshIfVisible",
                        Qt::QueuedConnection
                    );
                }
            });
        }
    }
    updateEmptyState();
}

CommandPalette::~CommandPalette() = default;

void CommandPalette::showPalette()
{
    _activationPending = false;
    if (_usesCommandManager) {
        refreshEntries();
    }
    if (!_search->text().isEmpty()) {
        _search->clear();
    }
    else {
        _model->setQuery({});
        selectFirstEnabledEntry();
        updateEmptyState();
    }

    if (QWidget* owner = parentWidget()) {
        const QPoint ownerCenter = owner->mapToGlobal(owner->rect().center());
        move(ownerCenter - rect().center());
    }
    show();
    raise();
    activateWindow();
    _search->setFocus(Qt::ShortcutFocusReason);
}

bool CommandPalette::eventFilter(QObject* watched, QEvent* event)
{
    if (event->type() == QEvent::KeyPress && (watched == _search || watched == _results)) {
        auto* keyEvent = static_cast<QKeyEvent*>(event);
        switch (keyEvent->key()) {
            case Qt::Key_Escape:
                closePalette();
                return true;
            case Qt::Key_Down:
                moveCurrentEntry(1);
                return true;
            case Qt::Key_Up:
                moveCurrentEntry(-1);
                return true;
            case Qt::Key_PageDown:
                moveCurrentEntry(5);
                return true;
            case Qt::Key_PageUp:
                moveCurrentEntry(-5);
                return true;
            case Qt::Key_Return:
            case Qt::Key_Enter:
                activateCurrentEntry();
                return true;
            default:
                break;
        }
    }
    return QDialog::eventFilter(watched, event);
}

void CommandPalette::keyPressEvent(QKeyEvent* event)
{
    if (event->key() == Qt::Key_Escape) {
        closePalette();
        return;
    }
    QDialog::keyPressEvent(event);
}

void CommandPalette::showEvent(QShowEvent* event)
{
    QDialog::showEvent(event);
    _search->setFocus(Qt::ShortcutFocusReason);
}

void CommandPalette::refreshIfVisible()
{
    if (isVisible() && _usesCommandManager) {
        refreshEntries();
    }
}

void CommandPalette::refreshEntries()
{
    if (!Application::Instance) {
        _model->setEntries({});
        return;
    }

    CommandManager& manager = Application::Instance->commandManager();
    manager.testActive();
    if (Command* paletteCommand = manager.getCommandByName("Std_CommandPalette")) {
        const QString shortcut = paletteCommand->getShortcut();
        _shortcutHint->setText(shortcut);
        _shortcutHint->setToolTip(
            shortcut.isEmpty() ? QString() : tr("Open the command palette (%1)").arg(shortcut)
        );
        _shortcutHint->setAccessibleName(
            shortcut.isEmpty() ? QString() : tr("Command palette shortcut %1").arg(shortcut)
        );
        _shortcutHint->setVisible(!shortcut.isEmpty());
    }
    const std::vector<Command*> commands = manager.getAllCommands();
    QVector<CommandPaletteEntry> entries;
    entries.reserve(static_cast<int>(commands.size()));
    for (Command* command : commands) {
        if (!command || qstrcmp(command->getName(), "Std_CommandPalette") == 0) {
            continue;
        }

        command->initAction();
        Action* wrapper = command->getAction();
        if (!wrapper || !wrapper->action()) {
            continue;
        }

        CommandPaletteEntry entry;
        entry.name = QString::fromUtf8(command->getName());
        entry.title = Action::commandMenuText(command);
        if (entry.title.isEmpty()) {
            entry.title = entry.name;
        }
        entry.group = command->translatedGroupName();
        entry.tooltip = Action::commandToolTip(command, false);
        entry.shortcut = wrapper->shortcut().toString(QKeySequence::NativeText);
        entry.icon = wrapper->icon();
        entry.action = wrapper->action();
        entries.push_back(std::move(entry));
    }

    if (_settings) {
        _model->setRecentCommands(_settings->value(QLatin1String(recentCommandsKey)).toStringList());
    }
    _model->setEntries(std::move(entries));
    _model->setQuery(_search->text());
}

void CommandPalette::selectFirstEnabledEntry()
{
    int row = _model->firstEnabledRow();
    if (row < 0 && _model->rowCount() > 0) {
        row = 0;
    }
    _results->setCurrentIndex(row < 0 ? QModelIndex() : _model->index(row, 0));
}

void CommandPalette::moveCurrentEntry(int offset)
{
    const int rowCount = _model->rowCount();
    if (rowCount == 0 || offset == 0) {
        return;
    }

    int row = _results->currentIndex().row();
    if (row < 0) {
        row = offset > 0 ? -1 : 0;
    }
    const int direction = offset > 0 ? 1 : -1;
    int remaining = std::abs(offset);
    for (int attempts = 0; attempts < rowCount * std::max(1, remaining); ++attempts) {
        row = (row + direction + rowCount) % rowCount;
        const QModelIndex candidate = _model->index(row, 0);
        if (candidate.data(CommandPaletteModel::EnabledRole).toBool()) {
            --remaining;
            if (remaining == 0) {
                _results->setCurrentIndex(candidate);
                _results->scrollTo(candidate);
                return;
            }
        }
    }
}

void CommandPalette::activateCurrentEntry()
{
    if (_activationPending) {
        return;
    }
    const QModelIndex index = _results->currentIndex();
    QPointer<QAction> action = _model->actionAt(index);
    if (!action || !action->isEnabled()) {
        return;
    }

    _activationPending = true;
    const QString commandName = _model->commandNameAt(index);
    _model->recordUse(commandName);
    saveHistory();
    hide();
    Q_EMIT commandTriggered(commandName);
    QTimer::singleShot(0, action.data(), [action]() {
        if (action && action->isEnabled()) {
            action->trigger();
        }
    });
}

void CommandPalette::closePalette()
{
    hide();
    _search->clear();
}

void CommandPalette::updateEmptyState()
{
    const bool empty = _model->rowCount() == 0;
    _results->setVisible(!empty);
    _emptyState->setVisible(empty);
}

void CommandPalette::saveHistory()
{
    if (_settings) {
        _settings->setValue(
            QLatin1String(recentCommandsKey),
            _model->recentCommands()
        );
    }
}

#include "moc_CommandPalette.cpp"
