build:
    @bash scripts/build.sh

start:
    @bash scripts/start.sh

stop:
    @bash scripts/stop.sh

delete:
    @bash scripts/delete.sh

exec:
    @bash scripts/exec.sh $(filter-out $@,$(MAKECMDGOALS))

%:
    @: 