/* ChartLibre.exe - the Windows launcher (dev/tools/make_launcher.py builds it).
 *
 * It sits in the ChartLibre folder and works from wherever that folder is:
 *
 *   - once .python holds Python and the libraries (its CHARTLIBRE_READY
 *     file says so - a ready-made package has it from the start), it starts
 *     .python\pythonw.exe ChartLibre.py with no console window at all, and exits;
 *   - an install made before .python is started from .venv the same way;
 *   - before either, it runs ChartLibre.bat in a console window, which
 *     downloads Python, installs the libraries with its progress on screen,
 *     and then starts ChartLibre itself.
 *
 * Needs nothing Windows 10 and 11 do not already have: kernel32, user32 and
 * the Universal C Runtime.
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>

#define BUF 4096

/* Built as ChartLibre Developer's launcher (-DDEVELOPER_LAUNCHER): the same job for dev\ChartLibreDeveloper.py, with
 * no installer of its own - it uses the Python ChartLibre installed in .python, and says so when there is none. */
#ifdef DEVELOPER_LAUNCHER
#define TITLE L"ChartLibre Developer"
#define SCRIPT_PATH L"\\dev\\ChartLibreDeveloper.py"
#define ROOT_LEVELS 2  /* ChartLibre\dev\ChartLibre Developer.exe */
#else
#define TITLE L"ChartLibre"
#define SCRIPT_PATH L"\\ChartLibre.py"
#define ROOT_LEVELS 1  /* ChartLibre\ChartLibre.exe */
#endif

static void fail(const wchar_t *what) {
    MessageBoxW(NULL, what, TITLE, MB_OK | MB_ICONERROR);
}

static int exists(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

/* out = a + b + c + d + e, or 0 when it would not fit in size characters.
 * Not wsprintfW: that one stops at 1024 characters, and a deep folder path
 * would be cut short without a word. */
static int join(wchar_t *out, int size, const wchar_t *a, const wchar_t *b,
                const wchar_t *c, const wchar_t *d, const wchar_t *e) {
    const wchar_t *parts[5] = {a, b, c, d, e};
    int used = 0;
    for (int i = 0; i < 5; ++i) {
        if (!parts[i]) continue;
        int n = lstrlenW(parts[i]);
        if (used + n >= size) return 0;
        lstrcpyW(out + used, parts[i]);
        used += n;
    }
    out[used] = L'\0';
    return 1;
}

static int run(wchar_t *command, const wchar_t *folder, DWORD flags) {
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof(startup));
    startup.cb = sizeof(startup);
    ZeroMemory(&process, sizeof(process));
    if (!CreateProcessW(NULL, command, NULL, NULL, FALSE, flags, NULL, folder, &startup, &process)) {
        return 0;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)arguments; (void)show;

    wchar_t folder[BUF], ready[BUF], runtime[BUF], pythonw[BUF], script[BUF], batch[BUF], command[BUF * 3];
    DWORD length = GetModuleFileNameW(NULL, folder, BUF);
    if (length == 0 || length >= BUF) {
        fail(L"ChartLibre could not find its own folder.");
        return 1;
    }
    for (int level = 0; level < ROOT_LEVELS; ++level) {  /* drop \ChartLibre.exe (and \dev) */
        wchar_t *end = folder + wcslen(folder);
        while (end > folder && *end != L'\\') --end;
        *end = L'\0';
    }

    if (!join(ready, BUF, folder, L"\\.python\\CHARTLIBRE_READY", NULL, NULL, NULL)
        || !join(runtime, BUF, folder, L"\\.python\\pythonw.exe", NULL, NULL, NULL)
        || !join(pythonw, BUF, folder, L"\\.venv\\Scripts\\pythonw.exe", NULL, NULL, NULL)
        || !join(script, BUF, folder, SCRIPT_PATH, NULL, NULL, NULL)
        || !join(batch, BUF, folder, L"\\ChartLibre.bat", NULL, NULL, NULL)) {
        fail(L"The ChartLibre folder's path is too long.");
        return 1;
    }

    if (exists(ready) && exists(runtime)) {
        if (!join(command, BUF * 3, L"\"", runtime, L"\" \"", script, L"\"")
            || !run(command, folder, 0)) {
            fail(L"ChartLibre could not start its Python (.python\\pythonw.exe).\n\n"
                 L"Delete the .python folder and open ChartLibre again to reinstall it.");
            return 1;
        }
        return 0;
    }

    if (exists(pythonw)) {
        if (!join(command, BUF * 3, L"\"", pythonw, L"\" \"", script, L"\"")
            || !run(command, folder, 0)) {
            fail(L"ChartLibre could not start Python from its .venv folder.\n\n"
                 L"Delete the .venv folder and open ChartLibre again to reinstall it.");
            return 1;
        }
        return 0;
    }

#ifdef DEVELOPER_LAUNCHER
    fail(L"ChartLibre Developer uses the Python that ChartLibre installs in its folder (.python).\n\n"
         L"Open ChartLibre once (ChartLibre.exe), then open ChartLibre Developer again.");
    return 1;
#endif
    if (!exists(batch)) {
        fail(L"ChartLibre.bat is missing from the ChartLibre folder.");
        return 1;
    }
    /* First launch: the batch file does the installation, visibly. */
    if (!join(command, BUF * 3, L"cmd.exe /c \"\"", batch, L"\"\"", NULL, NULL)
        || !run(command, folder, CREATE_NEW_CONSOLE)) {
        fail(L"ChartLibre could not start its installer (ChartLibre.bat).");
        return 1;
    }
    return 0;
}
