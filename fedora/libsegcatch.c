/* Tiny LD_PRELOAD that prints a backtrace() on a fatal signal, then re-raises.
 * Used to catch the rare post-unlock compositor crash at full speed (gdb hides
 * it; modern Fedora has no catchsegv/libSegFault and Android can't dump cores).
 *   gcc -shared -fPIC -O0 -g -o libsegcatch.so libsegcatch.c -rdynamic
 *   LD_PRELOAD=/path/libsegcatch.so phoc ...
 */
#define _GNU_SOURCE
#include <execinfo.h>
#include <signal.h>
#include <stdio.h>
#include <unistd.h>

static void handler(int sig) {
    void *bt[96];
    int n = backtrace(bt, 96);
    char msg[96];
    int len = snprintf(msg, sizeof msg,
        "\n=====KGSL CAUGHT SIGNAL %d (pid %d)=====\n", sig, (int)getpid());
    write(2, msg, len);
    backtrace_symbols_fd(bt, n, 2);
    write(2, "=====KGSL END BT=====\n", 22);
    signal(sig, SIG_DFL);
    raise(sig);
}

__attribute__((constructor)) static void seginit(void) {
    signal(SIGSEGV, handler); signal(SIGABRT, handler);
    signal(SIGBUS, handler);  signal(SIGFPE, handler); signal(SIGILL, handler);
}
