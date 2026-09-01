// SPDX-License-Identifier: LGPL-2.1-or-later

#include <QPointer>
#include <QProgressBar>
#include <QTest>
#include <QWidget>

#include "Gui/ProgressBar.h"

class testProgressBar: public QObject
{
    Q_OBJECT

private Q_SLOTS:
    void recreatesCachedProgressBarAfterParentDestruction()
    {
        auto* firstParent = new QWidget;
        QPointer<QProgressBar> first(
            Gui::SequencerBar::instance()->getProgressBar(firstParent)
        );
        QCOMPARE(first->parentWidget(), firstParent);
        delete firstParent;
        QVERIFY(first.isNull());

        QPointer<QProgressBar> second;
        {
            QWidget secondParent;
            second = Gui::SequencerBar::instance()->getProgressBar(&secondParent);
            QVERIFY(!second.isNull());
            QCOMPARE(second->parentWidget(), &secondParent);
        }
        QVERIFY(second.isNull());
    }
};

QTEST_MAIN(testProgressBar)

#include "ProgressBar.moc"
