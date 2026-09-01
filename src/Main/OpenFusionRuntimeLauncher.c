// SPDX-License-Identifier: LGPL-2.1-or-later

#define _GNU_SOURCE

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int set_package_environment(const char* prefix)
{
    struct Variable
    {
        const char* name;
        const char* suffix;
    };
    static const struct Variable variables[] = {
        {"FONTCONFIG_FILE", "/etc/fonts/fonts.conf"},
        {"FONTCONFIG_PATH", "/etc/fonts"},
        {"PYTHONHOME", ""},
        {"QT_PLUGIN_PATH", "/lib/qt6/plugins"},
        {"QT_QPA_PLATFORM_PLUGIN_PATH", "/lib/qt6/plugins/platforms"},
        {"SSL_CERT_FILE", "/ssl/cacert.pem"},
        {"XDG_DATA_DIRS", "/share"},
    };

    char value[PATH_MAX];
    for (size_t index = 0; index < sizeof(variables) / sizeof(variables[0]); ++index) {
        int length = snprintf(value, sizeof(value), "%s%s", prefix, variables[index].suffix);
        if (length < 0 || (size_t)length >= sizeof(value)) {
            errno = ENAMETOOLONG;
            return -1;
        }
        if (setenv(variables[index].name, value, 1) != 0) {
            return -1;
        }
    }
    return 0;
}

int main(int argc, char** argv)
{
    (void)argc;
    char executable[PATH_MAX];
    ssize_t length = readlink("/proc/self/exe", executable, sizeof(executable) - 1);
    if (length <= 0 || (size_t)length >= sizeof(executable) - 1) {
        perror("OpenFusion launcher cannot resolve /proc/self/exe");
        return 127;
    }
    executable[length] = '\0';

    char* bin = strrchr(executable, '/');
    if (bin == NULL || strcmp(bin, "/OpenFusion") != 0) {
        fprintf(stderr, "OpenFusion launcher has an unexpected executable path\n");
        return 127;
    }
    *bin = '\0';
    char* bin_directory = strrchr(executable, '/');
    if (bin_directory == NULL || strcmp(bin_directory, "/bin") != 0) {
        fprintf(stderr, "OpenFusion launcher is not installed beneath bin\n");
        return 127;
    }
    *bin_directory = '\0';

    if (set_package_environment(executable) != 0) {
        perror("OpenFusion launcher cannot establish package environment");
        return 127;
    }

    char real_executable[PATH_MAX];
    int real_length = snprintf(
        real_executable,
        sizeof(real_executable),
        "%s/libexec/OpenFusion.real",
        executable
    );
    if (real_length < 0 || (size_t)real_length >= sizeof(real_executable)) {
        fprintf(stderr, "OpenFusion real executable path is too long\n");
        return 127;
    }
    argv[0] = real_executable;
    execv(real_executable, argv);
    perror("OpenFusion launcher cannot execute the real application");
    return 127;
}
