// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <string>

#include <Gui/DiagnosticUtils.h>

TEST(GuiDiagnosticUtils, BoundsInputBeforeUtf8Conversion)
{
    std::string message(1024 * 1024, 'x');
    message += "unreachable-tail";

    const std::string sanitized = Gui::Detail::sanitizeDiagnosticText(message.c_str());

    EXPECT_EQ(sanitized, std::string(512, 'x') + "...");
    EXPECT_EQ(sanitized.find("unreachable-tail"), std::string::npos);
}

TEST(GuiDiagnosticUtils, EscapesControlAndQuotedFieldCharacters)
{
    const std::string message = "line\n\t\x1b\"\\\xE2\x80\xA8";

    const std::string sanitized = Gui::Detail::sanitizeDiagnosticText(message.c_str());

    EXPECT_EQ(sanitized, "line\\u000a\\u0009\\u001b\\\"\\\\\\u2028");
}

TEST(GuiDiagnosticUtils, BoundsQStringBeforeUtf8Conversion)
{
    QString message(1024 * 1024, QLatin1Char('x'));
    message.append(QStringLiteral("unreachable-tail"));

    const std::string sanitized = Gui::Detail::sanitizeDiagnosticQString(message);

    EXPECT_EQ(sanitized, std::string(128, 'x') + "...");
    EXPECT_EQ(sanitized.find("unreachable-tail"), std::string::npos);
}

TEST(GuiDiagnosticUtils, DisabledCollectionDoesNotInvokeProvider)
{
    bool invoked = false;
    const std::string sanitized = Gui::Detail::collectDiagnosticQString(false, [&] {
        invoked = true;
        return QString(1024 * 1024, QLatin1Char('x'));
    });

    EXPECT_FALSE(invoked);
    EXPECT_TRUE(sanitized.empty());
}
