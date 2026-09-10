"""
Разовый снимок провенанса тайлов: exportImage (блоки geodzz) vs фаза B
(потайловый водопад: dzz-tile-cache -> Esri -> Google).

Не часть пайплайна — запускать вручную:
    python scripts/provenance_snapshot.py

См. prompts/PROMPT_dzz_export_round5.md, п.1.

Разделитель источника — не время модификации, а наличие тайла в _pool/:
туда попадают только тайлы, нарезанные из блоков exportImage (см.
process_block в src/tasks/download.py); тайлы фазы B пишутся напрямую в
папку листа и в пуле отсутствуют. st_nlink/жёсткие ссылки не используются
как признак: на NFS мог сработать откат на copyfile (_link_from_pool), и
тогда nlink равен единице у всех файлов независимо от источника.

Скрипт только читает, ничего не перемещает и не удаляет.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import settings  # noqa: E402

_TILE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def _is_tile_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _TILE_EXTENSIONS


def main() -> None:
    tiles_dir = settings.paths.tiles_dir
    pool_dir = tiles_dir / "_pool"

    pool_names = (
        {p.name for p in pool_dir.glob("*") if _is_tile_file(p)}
        if pool_dir.exists() else set()
    )

    sheets = {}
    for sheet_dir in sorted(p for p in tiles_dir.iterdir() if p.is_dir()):
        if sheet_dir.name == "_pool":
            continue
        tiles = [p for p in sheet_dir.iterdir() if _is_tile_file(p)]
        from_export = sum(1 for p in tiles if p.name in pool_names)
        from_phase_b = len(tiles) - from_export
        missing_path = tiles_dir / f"{sheet_dir.name}_missing.json"
        sheets[sheet_dir.name] = {
            "tiles_total": len(tiles),
            "from_export": from_export,
            "from_phase_b": from_phase_b,
            # Полнота — по отсутствию файла *_missing.json, который
            # _check_completeness в download.py пишет рядом с папкой листа
            # (не внутри — иначе merge_tiles посчитал бы его тайлом).
            "complete": not missing_path.exists(),
        }

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool_tiles_total": len(pool_names),
        "sheets": sheets,
    }

    out_path = settings.paths.data_output / "provenance_2026-09-10.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    only_export = sum(
        1 for s in sheets.values() if s["tiles_total"] > 0 and s["from_phase_b"] == 0
    )
    only_phase_b = sum(
        1 for s in sheets.values() if s["tiles_total"] > 0 and s["from_export"] == 0
    )
    mixed = sum(
        1 for s in sheets.values()
        if s["tiles_total"] > 0 and s["from_export"] > 0 and s["from_phase_b"] > 0
    )
    empty = sum(1 for s in sheets.values() if s["tiles_total"] == 0)

    print(f"Снимок записан: {out_path}")
    print(f"Листов всего: {len(sheets)}")
    print(f"  целиком из exportImage: {only_export}")
    print(f"  целиком из фазы B:      {only_phase_b}")
    print(f"  смешанные:              {mixed}")
    print(f"  без тайлов:             {empty}")


if __name__ == "__main__":
    main()
