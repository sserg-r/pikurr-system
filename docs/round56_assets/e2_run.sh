set -e
cd /tmp/pikurr_r56
NET=pikurr-system_default
IMG=pikurr-system-etl:latest
ENVARGS=()
while IFS= read -r l; do ENVARGS+=(-e "$l"); done < <(docker inspect pikurr-system-etl-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(DBTABLES|PATHS|INFERENCE|TILESERVICES|DZZ)__')
ENVARGS+=(-e DB__HOST=pikurr_r56_tmpdb -e DB__PORT=5432 -e DB__USER=postgres -e DB__PASSWORD=r56test -e DB__NAME=pikurr_db -e GEE__PROJECT=dummy -e 'GEE__SERVICE_ACCOUNT={}' -e PROGRESS__INTERVAL_SECONDS=${INTERVAL:-1})
dump() { docker exec pikurr_r56_tmpdb psql -At -U postgres -d pikurr_db -c "SELECT fid_ext, year, stats::text FROM assessment ORDER BY fid_ext, year" > "$1"; }
run_save() { # $1 = тег (before|after)
  MOUNT=()
  [ "$1" = after ] && MOUNT=(-v /tmp/pikurr_r56/new/save_db.py:/app/src/tasks/save_db.py:ro)
  docker run --rm --name pikurr_r56_run_save_$1 --network $NET "${ENVARGS[@]}" \
    -v /mnt/nfsdata/PIKURR/outputs/predictions/predictions_final:/data_output/predictions/predictions_final:ro \
    "${MOUNT[@]}" $IMG python3 -m src.tasks.save_db > save_$1.log 2>&1 || { echo "FAILED $1"; tail -20 save_$1.log; exit 1; }
}
docker exec pikurr_r56_tmpdb psql -q -U postgres -d pikurr_db -c "TRUNCATE assessment"
run_save before; dump before_assessment.txt
docker exec pikurr_r56_tmpdb psql -q -U postgres -d pikurr_db -c "TRUNCATE assessment"
run_save after; dump after_assessment.txt
wc -l before_assessment.txt after_assessment.txt
cmp before_assessment.txt after_assessment.txt && echo "assessment: ИДЕНТИЧНО (fid_ext, year, stats)" || echo "assessment: РАЗЛИЧАЕТСЯ"
sha256sum before_assessment.txt after_assessment.txt
