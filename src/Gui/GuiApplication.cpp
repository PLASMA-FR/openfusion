/***************************************************************************
 *   Copyright (c) 2015 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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


#include <FCConfig.h>

#ifdef FC_OS_WIN32
# include <Windows.h>
#elif defined(Q_OS_UNIX)
# include <sys/types.h>
# include <ctime>
# include <unistd.h>
#endif

#include <mutex>
#include <sstream>
#include <QAbstractSpinBox>
#include <QByteArray>
#include <QComboBox>
#include <QTextStream>
#include <QThread>
#include <QFileInfo>
#include <QFileOpenEvent>
#include <QSessionManager>
#include <QTimer>


#include <QLocalServer>
#include <QLocalSocket>


#include <App/Application.h>
#include <Base/Console.h>
#include <Base/Exception.h>

#include "GuiApplication.h"
#include "Application.h"
#include "MainWindow.h"
#include "SpaceballEvent.h"


using namespace Gui;

namespace
{
struct CaughtSystemExitState
{
    std::mutex mutex;
    Gui::GUIApplication* application = nullptr;
    bool hasExitCode = false;
    long exitCode = 0;
};

CaughtSystemExitState& caughtSystemExitState()
{
    static CaughtSystemExitState state;
    return state;
}

void resetCaughtSystemExitState(Gui::GUIApplication* application) noexcept
{
    try {
        auto& state = caughtSystemExitState();
        const std::lock_guard guard(state.mutex);
        state.application = application;
        state.hasExitCode = false;
        state.exitCode = 0;
    }
    catch (...) {
    }
}

void clearCaughtSystemExitState(const Gui::GUIApplication* application) noexcept
{
    try {
        auto& state = caughtSystemExitState();
        const std::lock_guard guard(state.mutex);
        if (state.application == application) {
            state.application = nullptr;
            state.hasExitCode = false;
            state.exitCode = 0;
        }
    }
    catch (...) {
    }
}

bool recordCaughtSystemExitCode(
    Gui::GUIApplication* application,
    long requestedCode,
    long& authoritativeCode
) noexcept
{
    try {
        auto& state = caughtSystemExitState();
        const std::lock_guard guard(state.mutex);
        if (state.application != application) {
            return false;
        }
        if (!state.hasExitCode) {
            state.exitCode = requestedCode;
            state.hasExitCode = true;
        }
        authoritativeCode = state.exitCode;
        return true;
    }
    catch (...) {
        return false;
    }
}

bool readCaughtSystemExitCode(const Gui::GUIApplication* application, long& exitCode) noexcept
{
    try {
        auto& state = caughtSystemExitState();
        const std::lock_guard guard(state.mutex);
        if (state.application != application || !state.hasExitCode) {
            return false;
        }
        exitCode = state.exitCode;
        return true;
    }
    catch (...) {
        return false;
    }
}

void reportSystemExitFailure(const char* reason) noexcept
{
    try {
        Base::Console().error("Failed to handle SystemExit: %s\n", reason);
    }
    catch (...) {
    }
}
}  // namespace

GUIApplication::GUIApplication(int& argc, char** argv)
    : GUIApplicationNativeEventAware(argc, argv)
{
    resetCaughtSystemExitState(this);
    connect(
        this,
        &GUIApplication::commitDataRequest,
        this,
        &GUIApplication::commitData,
        Qt::DirectConnection
    );
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
    setFallbackSessionManagementEnabled(false);
#endif
}

GUIApplication::~GUIApplication()
{
    clearCaughtSystemExitState(this);
}

bool GUIApplication::getCaughtSystemExitCode(long& exitCode) const noexcept
{
    return readCaughtSystemExitCode(this, exitCode);
}

bool GUIApplication::requestSystemExit(std::exception_ptr exception) noexcept
{
    long requestedCode = 0;
    if (!Base::getSystemExitCode(exception, requestedCode)) {
        return false;
    }

    long authoritativeCode = requestedCode;
    if (!recordCaughtSystemExitCode(this, requestedCode, authoritativeCode)) {
        reportSystemExitFailure("could not record the requested exit code");
        return false;
    }

    const auto applyExit = [this]() noexcept -> bool {
        long exitCode = 0;
        if (!getCaughtSystemExitCode(exitCode)) {
            reportSystemExitFailure("the recorded exit code was unavailable on the GUI thread");
            QCoreApplication::exit(1);
            return false;
        }

        try {
            if (!caughtException) {
                caughtException = std::make_shared<Base::SystemExitException>(exitCode);
            }
        }
        catch (...) {
            // The primitive code remains authoritative if retaining a copy fails.
        }

        QCoreApplication::exit(static_cast<int>(exitCode));
        return true;
    };

    if (QThread::currentThread() == thread()) {
        return applyExit();
    }

    try {
        const auto queuedExit = [applyExit]() noexcept {
            (void)applyExit();
        };
        if (!QMetaObject::invokeMethod(this, queuedExit, Qt::QueuedConnection)) {
            reportSystemExitFailure("could not queue the request on the GUI thread");
            return false;
        }
    }
    catch (...) {
        reportSystemExitFailure("queuing the request raised an exception");
        return false;
    }
    return true;
}

bool GUIApplication::notify(QObject* receiver, QEvent* event)
{
    if (!receiver) {
        Base::Console().log(
            "GUIApplication::notify: Unexpected null receiver, event type: %d\n",
            (int)event->type()
        );
        return false;
    }

    // https://github.com/FreeCAD/FreeCAD/issues/16905
    std::string exceptionWarning =
#if FC_DEBUG
        "Exceptions must be caught before they go through Qt."
        " Ignoring this will cause crashes on some systems.\n";
#else
        "";
#endif

    try {
        if (event->type() == Spaceball::ButtonEvent::ButtonEventType
            || event->type() == Spaceball::MotionEvent::MotionEventType) {
            return processSpaceballEvent(receiver, event);
        }
        else {
            return QApplication::notify(receiver, event);
        }
    }
    catch (...) {
        const std::exception_ptr exception = std::current_exception();
        if (requestSystemExit(exception)) {
            return true;
        }

        try {
            std::rethrow_exception(exception);
        }
        catch (const Base::Exception& e) {
            Base::Console().error(
                "Unhandled Base::Exception caught in GUIApplication::notify.\n"
                "The error message is: %s\n%s",
                e.what(),
                exceptionWarning
            );
        }
        catch (const std::exception& e) {
            Base::Console().error(
                "Unhandled std::exception caught in GUIApplication::notify.\n"
                "The error message is: %s\n%s",
                e.what(),
                exceptionWarning
            );
        }
        catch (...) {
            Base::Console().error(
                "Unhandled unknown exception caught in GUIApplication::notify.\n%s",
                exceptionWarning
            );
        }
    }

    // Print some more information to the log file (if active) to ease bug fixing
    try {
        std::stringstream dump;
        dump << "The event type " << (int)event->type() << " was sent to "
             << receiver->metaObject()->className() << "\n";
        dump << "Object tree:\n";
        if (receiver->isWidgetType()) {
            QWidget* w = qobject_cast<QWidget*>(receiver);
            while (w) {
                dump << "\t";
                dump << w->metaObject()->className();
                QString name = w->objectName();
                if (!name.isEmpty()) {
                    dump << " (" << (const char*)name.toUtf8() << ")";
                }
                w = w->parentWidget();
                if (w) {
                    dump << " is child of\n";
                }
            }
            std::string str = dump.str();
            Base::Console().log("%s", str.c_str());
        }
    }
    catch (...) {
        Base::Console().log("Invalid recipient and/or event in GUIApplication::notify\n");
    }

    return true;
}

void GUIApplication::commitData(QSessionManager& manager)
{
    if (manager.allowsInteraction()) {
        if (!Gui::getMainWindow()->close()) {
            // cancel the shutdown
            manager.release();
            manager.cancel();
        }
    }
    else {
        // no user interaction allowed, thus close all documents and
        // the main window
        App::GetApplication().closeAllDocuments();
        Gui::getMainWindow()->close();
    }
}

bool GUIApplication::event(QEvent* ev)
{
    if (ev->type() == QEvent::FileOpen) {
        // (macOS workaround when opening FreeCAD by opening a .FCStd file in 1.0)
        // With the current implementation of the splash screen boot procedure, Qt will
        // start an event loop before FreeCAD is fully initialized. This event loop will
        // process the QFileOpenEvent that is sent by macOS before the main window is ready.
        if (!Gui::getMainWindow()->property("eventLoop").toBool()) {
            // If we never reach this point when opening FreeCAD by double clicking an
            // .FCStd file, then the workaround isn't needed anymore and can be removed
            QEvent* eventCopy = new QFileOpenEvent(static_cast<QFileOpenEvent*>(ev)->file());
            QTimer::singleShot(0, [eventCopy, this]() {
                QCoreApplication::postEvent(this, eventCopy);
            });
            return true;
        }

        QString file = static_cast<QFileOpenEvent*>(ev)->file();
        QFileInfo fi(file);
        if (fi.suffix().toLower() == QLatin1String("fcstd")) {
            QByteArray fn = file.toUtf8();
            Application::Instance->open(fn, "FreeCAD");
            return true;
        }
    }

    return GUIApplicationNativeEventAware::event(ev);
}

// ----------------------------------------------------------------------------

class GUISingleApplication::Private
{
public:
    explicit Private(GUISingleApplication* q_ptr)
        : q_ptr(q_ptr)
        , timer(new QTimer(q_ptr))
    {
        timer->setSingleShot(true);
        std::string exeName = App::Application::getExecutableName();
        serverName = QString::fromStdString(exeName);
    }

    ~Private()
    {
        if (server) {
            server->close();
        }
        delete server;
    }

    void setupConnection()
    {
        QLocalSocket socket;
        socket.connectToServer(serverName);
        if (socket.waitForConnected(1000)) {
            this->running = true;
        }
        else {
            startServer();
        }
    }

    void startServer()
    {
        // Start a QLocalServer to listen for connections
        server = new QLocalServer();
        QObject::connect(
            server,
            &QLocalServer::newConnection,
            q_ptr,
            &GUISingleApplication::receiveConnection
        );
        // first attempt
        if (!server->listen(serverName)) {
            if (server->serverError() == QAbstractSocket::AddressInUseError) {
                // second attempt
                server->removeServer(serverName);
                server->listen(serverName);
            }
        }
        if (server->isListening()) {
            Base::Console().log("Local server '%s' started\n", qPrintable(serverName));
        }
        else {
            Base::Console().log("Local server '%s' failed to start\n", qPrintable(serverName));
        }
    }

    GUISingleApplication* q_ptr;
    QTimer* timer;
    QLocalServer* server {nullptr};
    QString serverName;
    QList<QString> messages;
    bool running {false};
};

GUISingleApplication::GUISingleApplication(int& argc, char** argv)
    : GUIApplication(argc, argv)
    , d_ptr(new Private(this))
{
    d_ptr->setupConnection();
    connect(d_ptr->timer, &QTimer::timeout, this, &GUISingleApplication::processMessages);
}

GUISingleApplication::~GUISingleApplication() = default;

bool GUISingleApplication::isRunning() const
{
    return d_ptr->running;
}

bool GUISingleApplication::sendMessage(const QString& message, int timeout)
{
    QLocalSocket socket;
    bool connected = false;
    for (int i = 0; i < 2; i++) {
        socket.connectToServer(d_ptr->serverName);
        connected = socket.waitForConnected(timeout / 2);
        if (connected || i > 0) {
            break;
        }
        int ms = 250;
#if defined(Q_OS_WIN)
        Sleep(DWORD(ms));
#else
        usleep(ms * 1000);
#endif
    }
    if (!connected) {
        return false;
    }

    QTextStream ts(&socket);
#if QT_VERSION <= QT_VERSION_CHECK(6, 0, 0)
    ts.setCodec("UTF-8");
#else
    ts.setEncoding(QStringConverter::Utf8);
#endif
#if QT_VERSION <= QT_VERSION_CHECK(5, 15, 0)
    ts << message << endl;
#else
    ts << message << Qt::endl;
#endif

    return socket.waitForBytesWritten(timeout);
}

void GUISingleApplication::readFromSocket()
{
    auto socket = qobject_cast<QLocalSocket*>(sender());
    if (socket) {
        QTextStream in(socket);
#if QT_VERSION < QT_VERSION_CHECK(6, 0, 0)
        in.setCodec("UTF-8");
#else
        in.setEncoding(QStringConverter::Utf8);
#endif
        while (socket->canReadLine()) {
            d_ptr->timer->stop();
            QString message = in.readLine();
            Base::Console().log("Received message: %s\n", message.toStdString());
            d_ptr->messages.push_back(message);
            d_ptr->timer->start(1000);
        }
    }
}

void GUISingleApplication::receiveConnection()
{
    QLocalSocket* socket = d_ptr->server->nextPendingConnection();
    if (!socket) {
        return;
    }

    connect(socket, &QLocalSocket::disconnected, socket, &QLocalSocket::deleteLater);
    connect(socket, &QLocalSocket::readyRead, this, &GUISingleApplication::readFromSocket);
}

void GUISingleApplication::processMessages()
{
    QList<QString> msg = d_ptr->messages;
    d_ptr->messages.clear();
    Q_EMIT messageReceived(msg);
}

// ----------------------------------------------------------------------------

WheelEventFilter::WheelEventFilter(QObject* parent)
    : QObject(parent)
{}

bool WheelEventFilter::eventFilter(QObject* obj, QEvent* ev)
{
    if (qobject_cast<QComboBox*>(obj) && ev->type() == QEvent::Wheel) {
        return true;
    }
    auto sb = qobject_cast<QAbstractSpinBox*>(obj);
    if (sb) {
        if (ev->type() == QEvent::Show) {
            sb->setFocusPolicy(Qt::StrongFocus);
        }
        else if (ev->type() == QEvent::Wheel) {
            return !sb->hasFocus();
        }
    }
    return false;
}

#include "moc_GuiApplication.cpp"
