#include <gtest/gtest.h>

#include <exception>
#include <stdexcept>

#include <Base/Interpreter.h>

TEST(InterpreterSystemExitClassifier, RejectsEmptyException)
{
    long exitCode = 91;
    EXPECT_FALSE(Base::getSystemExitCode({}, exitCode));
    EXPECT_EQ(exitCode, 91);
}

TEST(InterpreterSystemExitClassifier, RejectsNonSystemExit)
{
    long exitCode = 91;
    const auto exception = std::make_exception_ptr(std::runtime_error("not SystemExit"));
    EXPECT_FALSE(Base::getSystemExitCode(exception, exitCode));
    EXPECT_EQ(exitCode, 91);
}

TEST(InterpreterSystemExitClassifier, ExtractsZero)
{
    long exitCode = 91;
    const auto exception = std::make_exception_ptr(Base::SystemExitException(0));
    EXPECT_TRUE(Base::getSystemExitCode(exception, exitCode));
    EXPECT_EQ(exitCode, 0);
}

TEST(InterpreterSystemExitClassifier, ExtractsSeven)
{
    long exitCode = 91;
    const auto exception = std::make_exception_ptr(Base::SystemExitException(7));
    EXPECT_TRUE(Base::getSystemExitCode(exception, exitCode));
    EXPECT_EQ(exitCode, 7);
}
