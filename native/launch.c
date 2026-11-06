#include <windows.h>
#include <stdio.h>
#include <wchar.h>

static int fail(const char *what)
{
    fprintf(stderr, "achl_launch: %s failed (%lu)\n", what, (unsigned long)GetLastError());
    fflush(stderr);
    return 2;
}

int wmain(int argc, wchar_t **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: achl_launch <dll> <exe> [workdir]\n");
        return 2;
    }
    const wchar_t *dll = argv[1];
    const wchar_t *exe = argv[2];
    const wchar_t *cwd = argc > 3 ? argv[3] : NULL;

    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION li;
        ZeroMemory(&li, sizeof(li));
        li.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &li, sizeof(li));
    }

    wchar_t cmd[MAX_PATH * 2];
    _snwprintf(cmd, MAX_PATH * 2, L"\"%ls\"", exe);
    cmd[MAX_PATH * 2 - 1] = 0;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(exe, cmd, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL, cwd, &si, &pi))
        return fail("CreateProcess");
    if (job)
        AssignProcessToJobObject(job, pi.hProcess);

    SIZE_T size = (wcslen(dll) + 1) * sizeof(wchar_t);
    void *remote = VirtualAllocEx(pi.hProcess, NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote || !WriteProcessMemory(pi.hProcess, remote, dll, size, NULL)) {
        TerminateProcess(pi.hProcess, 1);
        return fail("writing the dll path");
    }
    LPTHREAD_START_ROUTINE load =
        (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW");
    HANDLE th = CreateRemoteThread(pi.hProcess, NULL, 0, load, remote, 0, NULL);
    if (!th) {
        TerminateProcess(pi.hProcess, 1);
        return fail("CreateRemoteThread");
    }
    WaitForSingleObject(th, 30000);
    DWORD loaded = 0;
    GetExitCodeThread(th, &loaded);
    CloseHandle(th);
    if (!loaded) {
        TerminateProcess(pi.hProcess, 1);
        fprintf(stderr, "achl_launch: the dll did not load\n");
        return 3;
    }
    printf("pid=%lu\n", (unsigned long)pi.dwProcessId);
    fflush(stdout);
    ResumeThread(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    printf("exit=%lu\n", (unsigned long)code);
    fflush(stdout);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
