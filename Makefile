PY ?= python3
XLSX := data/raw/fleek_portfolio.xlsx

.PHONY: install demo run1 run2 rerun rerun-force status queue test synthetic bench clean

install:
	$(PY) -m pip install -r requirements.txt

## The Loom demo: fresh start, first book, second batch, same batch again
demo: clean run1 run2 rerun

run1:
	$(PY) -m autopilot run --input $(XLSX) --sheet Accounts --dispatch

run2:
	$(PY) -m autopilot run --input $(XLSX) --sheet new_accounts --dispatch

rerun:
	$(PY) -m autopilot run --input $(XLSX) --sheet new_accounts --dispatch

rerun-force:
	$(PY) -m autopilot run --input $(XLSX) --sheet new_accounts --dispatch --force

status:
	$(PY) -m autopilot status

queue:
	$(PY) -m autopilot queue --bucket today

test:
	$(PY) -m pytest -q

synthetic:
	$(PY) scripts/make_synthetic.py --rows 30000

bench: synthetic
	$(PY) scripts/bench.py --rows 30000

clean:
	$(PY) -m autopilot reset
