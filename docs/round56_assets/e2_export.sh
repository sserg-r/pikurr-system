set -e
cd /tmp/pikurr_r56
NET=pikurr-system_default
IMG=pikurr-system-etl:latest
ENVARGS=()
while IFS= read -r l; do ENVARGS+=(-e "$l"); done < <(docker inspect pikurr-system-etl-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(DBTABLES|PATHS|INFERENCE|TILESERVICES|DZZ)__')
ENVARGS+=(-e DB__HOST=pikurr_r56_tmpdb -e DB__PORT=5432 -e DB__USER=postgres -e DB__PASSWORD=r56test -e DB__NAME=pikurr_db -e GEE__PROJECT=dummy -e 'GEE__SERVICE_ACCOUNT={}' -e PROGRESS__INTERVAL_SECONDS=${INTERVAL:-1})
run_export() {
  MOUNT=()
  [ "$1" = after ] && MOUNT=(-v /tmp/pikurr_r56/new/export.py:/app/src/tasks/export.py:ro)
  rm -rf pub_$1; mkdir -p pub_$1
  docker run --rm --name pikurr_r56_run_export_$1 --network $NET "${ENVARGS[@]}" \
    -v /mnt/nfsdata/PIKURR/outputs/predictions/predictions_final:/data_output/predictions/predictions_final:ro \
    -v /tmp/pikurr_r56/pub_$1:/data_output/predictions/geoserver_public \
    "${MOUNT[@]}" $IMG python3 -m src.tasks.export > export_$1.log 2>&1 || { echo "FAILED $1"; tail -20 export_$1.log; exit 1; }
}
run_export before; run_export after
for t in before after; do echo "== $t"; (cd pub_$t/2025 && sha256sum *.tif); done
echo "== боевые geoserver_public/2025 тех же листов"
for f in $(ls pub_before/2025); do sudo -n sha256sum /mnt/nfsdata/PIKURR/outputs/predictions/geoserver_public/2025/$f; done
