# использование: c_run.sh <task> <tag> <db> [srcdir] [extra docker args...]   (значения env не выводятся)
set -e
cd /tmp/pikurr_r57
TASK=$1; TAG=$2; DB=$3; SRC=$4; shift 4 || shift $#
ENVARGS=()
while IFS= read -r l; do ENVARGS+=(-e "$l"); done < <(docker inspect pikurr-system-etl-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^(DBTABLES|PATHS|INFERENCE|TILESERVICES|DZZ)__')
ENVARGS+=(-e DB__HOST=pikurr_r57_tmpdb -e DB__PORT=5432 -e DB__USER=postgres -e DB__PASSWORD=r57test -e DB__NAME=$DB -e GEE__PROJECT=dummy -e 'GEE__SERVICE_ACCOUNT={}' -e PROGRESS__INTERVAL_SECONDS=${INTERVAL:-60})
MOUNT=(); [ -n "$SRC" ] && [ "$SRC" != "-" ] && MOUNT=(-v /tmp/pikurr_r57/$SRC:/app/src:ro)
PRED=/mnt/nfsdata/PIKURR/outputs/predictions
VOL=()
case $TASK in
  save_db) VOL=(-v $PRED/predictions_final:/data_output/predictions/predictions_final:ro);;
  export)  mkdir -p out_$TAG; VOL=(-v $PRED/predictions_final:/data_output/predictions/predictions_final:ro -v /tmp/pikurr_r57/out_$TAG:/data_output/predictions/geoserver_public);;
  classify) mkdir -p out_$TAG; VOL=(-v $PRED/predictions_veget:/data_output/predictions/predictions_veget:ro -v $PRED/predictions_usab:/data_output/predictions/predictions_usab:ro -v /tmp/pikurr_r57/out_$TAG:/data_output/predictions/predictions_final);;
esac
docker run --rm --name pikurr_r57_run_${TASK}_$TAG --network pikurr-system_default "${ENVARGS[@]}" "${VOL[@]}" "${MOUNT[@]}" pikurr-system-etl:latest python3 -m src.tasks.$TASK > log_${TASK}_$TAG.txt 2>&1 && echo "OK $TASK $TAG" || echo "FAILED $TASK $TAG"
