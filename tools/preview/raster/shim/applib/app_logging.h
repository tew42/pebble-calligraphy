#pragma once
#include <stdio.h>
typedef enum { APP_LOG_LEVEL_ERROR = 1, APP_LOG_LEVEL_WARNING, APP_LOG_LEVEL_INFO,
               APP_LOG_LEVEL_DEBUG } AppLogLevel;
/* The rasterizer only logs allocation failure, which would abort the run
 * anyway; route it to stderr so a failure is never silent. */
#define APP_LOG(level, fmt, ...) fprintf(stderr, "app_log: " fmt "\n", ##__VA_ARGS__)
