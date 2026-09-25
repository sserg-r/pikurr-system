#!/usr/bin/env python3
"""Доля страниц файлов, резидентных в файловом кэше ОС (mincore()).

round28 (блок A2) написал этот скрипт как временный, самодостаточный
(только stdlib+ctypes, ничего не устанавливает — vmtouch/fincore на
VPS нет, а ставить пакеты на VPS не входит в "только чтение"), но не
сохранил в репозиторий. round40 (блок A3) сохраняет его на будущее —
требуется перед КАЖДОЙ серией замеров (доля резидентности мозаики/
кэша GWC как часть результата, не как предусловие).

Запуск:
    python3 mincore_residency.py <каталог1> [<каталог2> ...]
    python3 mincore_residency.py --glob '*.tif' ~/repikurr/data/geodata/2025

Печатает: файлов, страниц всего, страниц резидентно, доля %, для
каждого переданного каталога отдельно и суммарно.
"""
import ctypes
import ctypes.util
import mmap
import os
import sys

PAGE_SIZE = mmap.PAGESIZE

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
libc.mincore.restype = ctypes.c_int


def residency(path: str):
    size = os.path.getsize(path)
    if size == 0:
        return 0, 0
    n_pages = (size + PAGE_SIZE - 1) // PAGE_SIZE
    fd = os.open(path, os.O_RDONLY)
    try:
        # ACCESS_COPY (MAP_PRIVATE, писать не будем) вместо PROT_READ —
        # ctypes.c_char.from_buffer() требует ЗАПИСЫВАЕМЫЙ буфер, чтобы
        # получить адрес отображения; страницы всё равно приходят из
        # того же файлового кэша при первом чтении (COW триггерится
        # только на запись, которой здесь нет), так что семантика
        # mincore() не меняется.
        mm = mmap.mmap(fd, size, access=mmap.ACCESS_COPY)
    finally:
        os.close(fd)
    try:
        vec = (ctypes.c_ubyte * n_pages)()
        addr = ctypes.addressof(ctypes.c_char.from_buffer(mm))
        ret = libc.mincore(ctypes.c_void_p(addr), ctypes.c_size_t(size), vec)
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), path)
        resident = sum(1 for b in vec if b & 1)
        return n_pages, resident
    finally:
        mm.close()


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    pattern = "*"
    paths = argv
    if argv[0] == "--glob":
        pattern = argv[1]
        paths = argv[2:]

    import fnmatch

    total_pages = 0
    total_resident = 0
    total_files = 0
    for root in paths:
        root_pages = 0
        root_resident = 0
        root_files = 0
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not fnmatch.fnmatch(name, pattern):
                    continue
                fpath = os.path.join(dirpath, name)
                try:
                    n_pages, resident = residency(fpath)
                except OSError as e:
                    print(f"  ! пропущен {fpath}: {e}", file=sys.stderr)
                    continue
                root_pages += n_pages
                root_resident += resident
                root_files += 1
        pct = (root_resident / root_pages * 100) if root_pages else 0.0
        mb_total = root_pages * PAGE_SIZE / (1024 * 1024)
        mb_resident = root_resident * PAGE_SIZE / (1024 * 1024)
        print(f"{root}: файлов={root_files} страниц={root_resident}/{root_pages} "
              f"({pct:.1f}%) ~{mb_resident:.1f}/{mb_total:.1f} МБ")
        total_pages += root_pages
        total_resident += root_resident
        total_files += root_files

    if len(paths) > 1:
        pct = (total_resident / total_pages * 100) if total_pages else 0.0
        mb_total = total_pages * PAGE_SIZE / (1024 * 1024)
        mb_resident = total_resident * PAGE_SIZE / (1024 * 1024)
        print(f"ИТОГО: файлов={total_files} страниц={total_resident}/{total_pages} "
              f"({pct:.1f}%) ~{mb_resident:.1f}/{mb_total:.1f} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
