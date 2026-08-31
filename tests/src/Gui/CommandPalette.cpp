// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QAction>
#include <QFile>
#include <QLineEdit>
#include <QListView>
#include <QSignalSpy>
#include <QTest>

#include "Gui/CommandPalette.h"

namespace
{

Gui::CommandPaletteEntry makeEntry(
    const QString& name,
    const QString& title,
    QAction* action,
    const QString& group = QStringLiteral("Design")
)
{
    Gui::CommandPaletteEntry entry;
    entry.name = name;
    entry.title = title;
    entry.group = group;
    entry.tooltip = title;
    entry.action = action;
    return entry;
}

}  // namespace

class testCommandPalette: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void commandIconResolvesWithoutFallback()
    {
        const QString resourcePath = QStringLiteral(":/icons/%1.svg")
                                         .arg(QString::fromLatin1(Gui::CommandPaletteIconName));

        QVERIFY2(QFile::exists(resourcePath), qPrintable(resourcePath));
    }

    void fuzzySearchScoresExactPrefixAndSubsequence()
    {
        const int exact = Gui::CommandPaletteModel::fuzzyScore("save", "Save");
        const int prefix = Gui::CommandPaletteModel::fuzzyScore("sav", "Save As");
        const int subsequence = Gui::CommandPaletteModel::fuzzyScore("svas", "Save As");

        QVERIFY(exact > prefix);
        QVERIFY(prefix > subsequence);
        QVERIFY(subsequence >= 0);
        QCOMPARE(Gui::CommandPaletteModel::fuzzyScore("zsa", "Save As"), -1);
    }

    void modelRanksExactMatchesAndRecentCommands()
    {
        QAction save;
        QAction saveAs;
        Gui::CommandPaletteModel model;
        model.setEntries({
            makeEntry("Std_SaveAs", "Save As", &saveAs),
            makeEntry("Std_Save", "Save", &save),
        });

        model.setQuery("save");
        QCOMPARE(model.data(model.index(0, 0), Gui::CommandPaletteModel::NameRole).toString(), "Std_Save");

        model.setRecentCommands({"Std_SaveAs"});
        model.setQuery({});
        QCOMPARE(model.data(model.index(0, 0), Gui::CommandPaletteModel::NameRole).toString(), "Std_SaveAs");

        model.setQuery("sv as");
        QCOMPARE(model.rowCount(), 1);
        QCOMPARE(model.data(model.index(0, 0), Gui::CommandPaletteModel::NameRole).toString(), "Std_SaveAs");
    }

    void disabledCommandsRemainVisibleButCannotActivate()
    {
        QAction disabled;
        disabled.setEnabled(false);
        Gui::CommandPaletteModel model;
        model.setEntries({makeEntry("PartDesign_Pad", "Pad", &disabled)});

        QCOMPARE(model.rowCount(), 1);
        const QModelIndex index = model.index(0, 0);
        QVERIFY(!model.data(index, Gui::CommandPaletteModel::EnabledRole).toBool());
        QVERIFY(!model.flags(index).testFlag(Qt::ItemIsEnabled));
        QCOMPARE(model.firstEnabledRow(), -1);

        Gui::CommandPalette palette(nullptr, &model);
        QSignalSpy triggered(&disabled, &QAction::triggered);
        palette.showPalette();
        auto* search = palette.findChild<QLineEdit*>(QStringLiteral("commandPaletteSearch"));
        QVERIFY(search);
        QTest::keyClick(search, Qt::Key_Return);
        QCoreApplication::processEvents();
        QCOMPARE(triggered.count(), 0);
        QVERIFY(palette.isVisible());
    }

    void paletteFocusesSearchAndEscapeCancels()
    {
        QAction action;
        Gui::CommandPaletteModel model;
        model.setEntries({makeEntry("Std_Save", "Save", &action)});
        Gui::CommandPalette palette(nullptr, &model);
        QSignalSpy triggered(&action, &QAction::triggered);

        palette.showPalette();
        auto* search = palette.findChild<QLineEdit*>(QStringLiteral("commandPaletteSearch"));
        QVERIFY(search);
        QTRY_VERIFY(search->hasFocus());
        QTest::keyClick(search, Qt::Key_Escape);

        QTRY_VERIFY(!palette.isVisible());
        QCOMPARE(triggered.count(), 0);
    }

    void keyboardNavigationTriggersTheRealAction()
    {
        QAction alpha;
        QAction beta;
        Gui::CommandPaletteModel model;
        model.setEntries({
            makeEntry("Std_Alpha", "Alpha", &alpha),
            makeEntry("Std_Beta", "Beta", &beta),
        });
        Gui::CommandPalette palette(nullptr, &model);
        QSignalSpy alphaTriggered(&alpha, &QAction::triggered);
        QSignalSpy betaTriggered(&beta, &QAction::triggered);

        palette.showPalette();
        auto* search = palette.findChild<QLineEdit*>(QStringLiteral("commandPaletteSearch"));
        auto* results = palette.findChild<QListView*>(QStringLiteral("commandPaletteResults"));
        QVERIFY(search);
        QVERIFY(results);
        QCOMPARE(results->currentIndex().data(Gui::CommandPaletteModel::NameRole).toString(), "Std_Alpha");

        QTest::keyClick(search, Qt::Key_Down);
        QCOMPARE(results->currentIndex().data(Gui::CommandPaletteModel::NameRole).toString(), "Std_Beta");
        QTest::keyClick(search, Qt::Key_Return);

        QTRY_COMPARE(betaTriggered.count(), 1);
        QCOMPARE(alphaTriggered.count(), 0);
        QVERIFY(!palette.isVisible());
        QCOMPARE(model.recentCommands().constFirst(), "Std_Beta");
    }

    void duplicateViewActivationTriggersOnlyOnce()
    {
        QAction action;
        Gui::CommandPaletteModel model;
        model.setEntries({makeEntry("Std_Save", "Save", &action)});
        Gui::CommandPalette palette(nullptr, &model);
        QSignalSpy triggered(&action, &QAction::triggered);

        palette.showPalette();
        auto* results = palette.findChild<QListView*>(QStringLiteral("commandPaletteResults"));
        QVERIFY(results);
        const QModelIndex index = results->currentIndex();
        QVERIFY(index.isValid());

        QVERIFY(QMetaObject::invokeMethod(
            results,
            "activated",
            Qt::DirectConnection,
            Q_ARG(QModelIndex, index)
        ));
        QVERIFY(QMetaObject::invokeMethod(
            results,
            "doubleClicked",
            Qt::DirectConnection,
            Q_ARG(QModelIndex, index)
        ));

        QTRY_COMPARE(triggered.count(), 1);
        QCOMPARE(model.recentCommands(), QStringList {QStringLiteral("Std_Save")});
    }

    void modelRefreshPreservesTheActiveSearch()
    {
        QAction alpha;
        QAction beta;
        Gui::CommandPaletteModel model;
        model.setEntries({makeEntry("Std_Alpha", "Alpha", &alpha)});
        model.setQuery("beta");
        QCOMPARE(model.rowCount(), 0);

        model.setEntries({
            makeEntry("Std_Alpha", "Alpha", &alpha),
            makeEntry("Std_Beta", "Beta", &beta),
        });
        QCOMPARE(model.query(), "beta");
        QCOMPARE(model.rowCount(), 1);
        QCOMPARE(model.data(model.index(0, 0), Gui::CommandPaletteModel::NameRole).toString(), "Std_Beta");
    }
};

QTEST_MAIN(testCommandPalette)

#include "CommandPalette.moc"
