/* Link only into the save test host; production has no fault-injection hooks. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <unistd.h>

static int failure;
void save_io_failure(int mode) { failure = mode; }

size_t save_test_fwrite(const void *data, size_t size, size_t count, FILE *stream) {
    if (failure == 1) {
        size_t written = fwrite(data, size, count / 2, stream);
        errno = ENOSPC;
        return written;
    }
    return fwrite(data, size, count, stream);
}

int save_test_fflush(FILE *stream) {
    int result = fflush(stream);
    if (failure == 2) { errno = EIO; return EOF; }
    return result;
}

int save_test_fsync(int fd) {
    if (failure == 3) { errno = EIO; return -1; }
    return fsync(fd);
}

int save_test_fclose(FILE *stream) {
    int result = fclose(stream);
    if (failure == 4) { errno = EIO; return EOF; }
    return result;
}

int save_test_rename(const char *source, const char *destination) {
    if (failure == 5) { errno = EACCES; return -1; }
    return rename(source, destination);
}
