// SPDX-License-Identifier: LGPL-2.1-or-later

#ifndef GUI_DIAGNOSTICUTILS_H
#define GUI_DIAGNOSTICUTILS_H

#include <algorithm>
#include <cstddef>
#include <string>

#include <QString>

namespace Gui::Detail
{
inline std::string sanitizeDiagnosticText(
    const char* message,
    std::size_t maximumInputBytes = 2048,
    int maximumLength = 512
)
{
    std::size_t inputBytes = 0;
    if (message) {
        while (inputBytes < maximumInputBytes && message[inputBytes] != '\0') {
            ++inputBytes;
        }
    }
    const bool inputTruncated = message && inputBytes == maximumInputBytes;
    QString value = message ? QString::fromUtf8(message, static_cast<int>(inputBytes))
                            : QStringLiteral("unavailable");
    const bool truncated = inputTruncated || value.size() > maximumLength;
    if (value.size() > maximumLength) {
        value.truncate(maximumLength);
    }

    QString sanitized;
    sanitized.reserve(value.size());
    for (const QChar character : value) {
        const auto category = character.category();
        const bool isControl = category == QChar::Other_Control || category == QChar::Other_Format
            || category == QChar::Other_Surrogate || category == QChar::Separator_Line
            || category == QChar::Separator_Paragraph;
        if (character == QLatin1Char('\\')) {
            sanitized.append(QStringLiteral("\\\\"));
        }
        else if (character == QLatin1Char('"')) {
            sanitized.append(QStringLiteral("\\\""));
        }
        else if (isControl) {
            sanitized.append(QStringLiteral("\\u%1").arg(character.unicode(), 4, 16, QLatin1Char('0')));
        }
        else {
            sanitized.append(character);
        }
    }
    if (truncated) {
        sanitized.append(QStringLiteral("..."));
    }
    return sanitized.toUtf8().toStdString();
}

inline std::string sanitizeDiagnosticQString(
    const QString& message,
    int maximumInputCodeUnits = 128,
    int maximumLength = 128
)
{
    const int boundedInputLength = std::max(maximumInputCodeUnits, 0);
    const int boundedMaximumLength = std::max(maximumLength, 0);
    const bool inputTruncated = message.size() > boundedInputLength;
    QString value = message.left(boundedInputLength);
    const bool truncated = inputTruncated || value.size() > boundedMaximumLength;
    if (value.size() > boundedMaximumLength) {
        value.truncate(boundedMaximumLength);
    }

    QString sanitized;
    sanitized.reserve(value.size());
    for (const QChar character : value) {
        const auto category = character.category();
        const bool isControl = category == QChar::Other_Control || category == QChar::Other_Format
            || category == QChar::Other_Surrogate || category == QChar::Separator_Line
            || category == QChar::Separator_Paragraph;
        if (character == QLatin1Char('\\')) {
            sanitized.append(QStringLiteral("\\\\"));
        }
        else if (character == QLatin1Char('"')) {
            sanitized.append(QStringLiteral("\\\""));
        }
        else if (isControl) {
            sanitized.append(QStringLiteral("\\u%1").arg(character.unicode(), 4, 16, QLatin1Char('0')));
        }
        else {
            sanitized.append(character);
        }
    }
    if (truncated) {
        sanitized.append(QStringLiteral("..."));
    }
    return sanitized.toUtf8().toStdString();
}

template<typename Provider>
std::string collectDiagnosticQString(bool enabled, Provider&& provider)
{
    if (!enabled) {
        return {};
    }
    return sanitizeDiagnosticQString(provider());
}
}  // namespace Gui::Detail

#endif  // GUI_DIAGNOSTICUTILS_H
