#pragma once

//! Opaque: only gbitmap_get_info's legacy2 branch names this type, and that
//! branch is dead because the watchface is an SDK 3+ app.
typedef struct Heap Heap;

Heap *app_state_get_heap(void);
bool heap_is_allocated(Heap *heap, void *pointer);
