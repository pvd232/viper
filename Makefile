PYTHON ?= python

.PHONY: check check-fast check-integration check-release check-live

check: check-fast

check-fast:
	ruff check src/viper tests
	ruff format --check src/viper tests
	pyright --pythonpath "$$($(PYTHON) -c 'import shutil; print(shutil.which("python"))')"
	$(PYTHON) -m pytest tests -q -m "unit or contract"

check-integration:
	$(PYTHON) -m pytest tests -q -m "integration and not live_cuda"

check-release:
	$(PYTHON) -m pytest tests -q -m "not live_cuda"

check-live:
	VIPER_LIVE_CUDA=1 $(PYTHON) -m pytest tests -q -m live_cuda
