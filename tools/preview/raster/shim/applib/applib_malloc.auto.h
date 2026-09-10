#pragma once
#include <stddef.h>
void *applib_malloc(size_t bytes);
void *applib_zalloc(size_t bytes);
void  applib_free(void *pointer);
